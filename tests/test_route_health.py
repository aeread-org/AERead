"""S5 (#226 items 1, 3, 4): one route-health controller shared by a process's cells.

Red-first tests for slice S5 of the provider-reliability plan, stacked on S4
(``transport_v1``, in-attempt re-send). A profile that declares
``harness.config["route_policy"] = "route_v1"`` and runs under a caller-created
``RouteHealthRegistry`` gets, per route key: a consecutive-failure breaker with
an escalating cooldown, a provider-requested pause (``Retry-After``) honoured
route-wide and uncapped, and an outage bound enforced by time. Cells consult
the route at a gate before call 0 and, for re-sends, inside S4's admission.
Profiles without the declaration behave exactly as on S4.

Test groups (ids follow the S5 spec, v0.5)
- H1-H8, S1, K1: ``RouteHealth`` and the key, as units, on a fake clock with
  origin 0.0.
- G1-G6, E1, R1-R4, T1: integration through ``execute_plan_cell`` (or
  ``AttemptExecutor`` where a test reads the complete execution record) with
  the real openai SDK over the SDK's own mock transport (``httpx`` under
  openai 2.x, ``httpx2`` under 3.x), one registry shared by consecutive or
  concurrent cells. Every waiting test runs under an ``asyncio.wait_for``
  watchdog and a bounded fake sleep, so a missing bounded wake fails instead
  of hanging.
- V1: validation at construction.
- Controls: S4's committed v0 goldens and a new ``transport_v1`` golden, each
  compared with and without a registry; a pre-request failure for v0 and
  S4-only profiles; the receipt-class pins; spend with and without route_v1.

Names the implementation must provide (imported lazily so the module collects
on the S4 base)
- ``execution``: ``declared_route_policy(profile)``, ``RoutePolicy`` (frozen;
  fields ``open_after_failures``, ``cooldown_seconds``, ``cooldown_cap_seconds``,
  ``max_outage_seconds``), ``route_health_key(profile)``,
  ``execute_plan_cell(..., route_health=...)``.
- ``model_call.harness``: ``AttemptExecutor(..., route_health=...)``.
- ``model_call.route_health``: ``RouteHealth(policy)``, ``RouteHealthRegistry()``
  with ``health_for(profile)`` (creates on first use, one object per key),
  the module functions ``_route_monotonic()`` and async ``_route_sleep(seconds)``
  (replaced by these tests), and ``RouteHealth.report(*, condition=None,
  success=False, retry_after_seconds=None, ref=None)``, ``.admits()``,
  ``.snapshot()`` and the state fields ``outage_start``, ``failures``,
  ``cooldown``, ``cooldown_until``, ``pause_until``, ``exhausted``,
  ``cooldown_ref``, ``pause_ref``. ``report``, ``admits`` and ``snapshot`` read
  the clock themselves.
- The re-send sleep keeps S4's ``harness._transport_sleep``; the gate wait uses
  ``route_health._route_sleep``. The fake here drives both from one clock.

The golden control
``test_*_goldens_*`` compare the events and the complete ``LogicalActionExecution``
records of fixed fault scripts, with fixed identity inputs and a fixed clock,
against files committed under ``tests/fixtures/route_health/`` (and S4's v0
files under ``tests/fixtures/transport_resend/``). The route_health files were
generated on the S4 head before any S5 change. To regenerate them (only when
those bytes are meant to change, and never in CI)::

    AEREAD_REGENERATE_ROUTE_GOLDENS=1 PYTHONPATH=src:. \\
        python -m pytest tests/test_route_health.py -k "goldens or pre_request" -p no:cacheprovider
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import aeread.shared_runner.model_call.harness as harness_module
from aeread.shared_runner.model_call.harness import AttemptExecutor, default_harnesses
from aeread.shared_runner.schemas import AgentProfile
from aeread.shared_runner.task.execution import (
    POST_ADMISSION_REJECTION,
    PROVIDER_CHOICE_ERROR,
    EvidenceIntegrityError,
    EvidenceStore,
    MinimalChatExecutor,
    ProviderFailure,
    execute_plan_cell,
)
from tests.test_shared_runner_execution import _decision
from tests.test_transport_resend import (
    BASE_URL,
    DECLARED,
    GOLDEN_SCRIPTS as S4_GOLDEN_SCRIPTS,
    MODEL,
    OK_COST,
    OUTPUT_SCHEMA,
    PRICING,
    PROMPT,
    PROMPT_ID,
    PROVIDER_METADATA,
    CANONICAL_MODEL,
    V0_BACKOFF,
    V1,
    Injecting,
    Scripted,
    Wire,
    _assert_evidence_survives_audit_and_resume,
    _canon,
    _plan_setup,
    _provider_failure_in,
    _release_evidence_lock,
    _scripted_503,
    _scripted_ok,
    build_client,
    exactly,
    expected_delay,
    make_profile as s4_make_profile,
    of,
    kinds,
    ok,
    read_log,
    refuse,
    started_ids,
)

_REAL_SLEEP = asyncio.sleep
ROUTE_MODULE = "aeread.shared_runner.model_call.route_health"

# --- Declarations ---------------------------------------------------------------------

ROUTE = {
    "route_policy": "route_v1",
    "route_open_after_failures": 3,
    "route_cooldown_seconds": 30.0,
    "route_cooldown_cap_seconds": 120.0,
    "route_max_outage_seconds": 600.0,
}
# Unit-test policy: small numbers, a bound that never interferes unless a test lowers it.
UNIT = {
    "route_open_after_failures": 3,
    "route_cooldown_seconds": 10.0,
    "route_cooldown_cap_seconds": 40.0,
    "route_max_outage_seconds": 10000.0,
}
ROUTE_KEYS = {
    "state",
    "cooldown_until_in",
    "pause_until_in",
    "outage_age",
    "failures",
    "cooldown",
    "exhausted",
    "cause_ref",
}


def _r1(**overrides):
    """A transport_v1 + route_v1 declaration (S4's V1 plus ROUTE)."""

    return {**V1, **ROUTE, **overrides}


def route_profile(
    config=None,
    *,
    profile_id: str = "subject_model_v1",
    remove=(),
    model: str = MODEL,
    base_url: str = BASE_URL,
    max_action_attempts: int = 3,
    retryable=DECLARED,
    timeout_seconds: float = 60.0,
    max_cost_usd: float = 0.05,
) -> AgentProfile:
    """S4's ``make_profile`` with a few more knobs (and no config defaulting to V1)."""

    harness_config = {
        "pricing_id": PRICING.pricing_id,
        "pricing_sha256": PRICING.content_sha256(),
        "output_schema": OUTPUT_SCHEMA,
        "provider_metadata": PROVIDER_METADATA,
        **(_r1() if config is None else config),
    }
    for key in remove:
        harness_config.pop(key, None)
    return AgentProfile.from_dict(
        {
            "spec_version": "aeread.agent_profile/0.1",
            "profile_id": profile_id,
            "model": {
                "provider": "openrouter",
                "model": model,
                "revision": CANONICAL_MODEL,
                "base_url": base_url,
            },
            "harness": {"id": "minimal_chat", "version": "1.0", "config": harness_config},
            "prompt": {
                "prompt_id": PROMPT_ID,
                "sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
            },
            "runtime": {
                "kind": "python",
                "implementation": "aeread.shared_runner.task.execution",
                "version": "0.1.0",
            },
            "tools": [],
            "memory": {"mode": "disabled"},
            "reasoning": {
                "condition_id": "reasoning_low_v1",
                "effort": "low",
                "token_budget": None,
                "rationale_visibility": "hidden",
            },
            "sampling": {
                "temperature": 0.0,
                "max_output_tokens": 512,
                "seed": 71001,
                "top_p": 1.0,
            },
            "budgets": {
                "max_logical_actions": 4,
                "timeout_seconds": timeout_seconds,
                "max_cost_usd": max_cost_usd,
            },
            "retry_policy": {
                "max_action_attempts": max_action_attempts,
                "retryable_conditions": list(retryable),
                "session_mode": "restart",
                "sdk_retries": 0,
            },
        }
    )


# --- Lazy names ------------------------------------------------------------------------


def _route_module():
    import importlib

    return importlib.import_module(ROUTE_MODULE)


def _new_registry():
    return _route_module().RouteHealthRegistry()


def _health(**policy):
    """A fresh ``RouteHealth`` under the unit policy, with overrides."""

    from aeread.shared_runner.task.execution import declared_route_policy

    profile = route_profile(_r1(**{**UNIT, **policy}))
    return _route_module().RouteHealth(declared_route_policy(profile))


def ref(n, condition="provider_5xx", attempt="attempt_seed"):
    return {
        "episode_attempt_id": attempt,
        "provider_call_id": f"call_{n}",
        "condition": condition,
    }


def state_of(health):
    return (
        health.outage_start,
        health.failures,
        health.cooldown,
        health.cooldown_until,
        health.pause_until,
        health.exhausted,
        health.cooldown_ref,
        health.pause_ref,
    )


# --- Fake clock and sleep --------------------------------------------------------------


class Clock:
    """One monotonic clock and one sleep for the route and for S4's port.

    Time moves only when a sleep runs (or a test moves it). A sleep yields to
    the event loop once, so a busy wait cannot starve the watchdog, and a loop
    that sleeps more than 200 times fails loudly.
    """

    def __init__(self, start: float) -> None:
        self.now = start
        self.sleeps: list[float] = []
        self.on_sleep = None

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        if len(self.sleeps) > 200:
            raise AssertionError("runaway wait loop: more than 200 sleeps")
        await _REAL_SLEEP(0)
        if self.on_sleep is not None:
            await self.on_sleep(self, seconds)
        else:
            self.now += seconds


START = 1000.0


def _install(monkeypatch, fake: Clock) -> None:
    # raising=False: on the S4 base the route names do not exist yet; the tests
    # then fail on behaviour (a missing module or name), not on a patch error.
    monkeypatch.setattr(harness_module, "_transport_monotonic", fake.monotonic, raising=False)
    monkeypatch.setattr(harness_module, "_transport_sleep", fake.sleep, raising=False)
    try:
        route = _route_module()
    except ImportError:
        return
    monkeypatch.setattr(route, "_route_monotonic", fake.monotonic, raising=False)
    monkeypatch.setattr(route, "_route_sleep", fake.sleep, raising=False)


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> Clock:
    fake = Clock(START)
    _install(monkeypatch, fake)
    return fake


@pytest.fixture
def uclock(monkeypatch) -> Clock:
    """A unit-test clock with origin 0.0 (replaces the integration clock)."""

    fake = Clock(0.0)
    _install(monkeypatch, fake)
    return fake


@pytest.fixture(autouse=True)
def _instant_asyncio_sleep(monkeypatch) -> None:
    """The executor's own between-attempt backoff must not slow the suite."""

    async def instant(delay, result=None):
        await _REAL_SLEEP(0)
        return result

    monkeypatch.setattr(asyncio, "sleep", instant)


@pytest.fixture
def reports(monkeypatch):
    """Every ``RouteHealth.report`` call, as ``"success"`` or its condition."""

    calls = []
    try:
        route = _route_module()
    except ImportError:
        return calls  # the test then fails on the missing module, not in setup
    real = route.RouteHealth.report

    def spy(self, *args, **kwargs):
        calls.append(
            SimpleNamespace(
                label="success" if kwargs.get("success") else kwargs.get("condition"),
                retry_after_seconds=kwargs.get("retry_after_seconds"),
                ref=kwargs.get("ref"),
            )
        )
        return real(self, *args, **kwargs)

    monkeypatch.setattr(route.RouteHealth, "report", spy)
    return calls


WATCHDOG_SECONDS = 30.0


def run_async(coro):
    """Run under a watchdog: a missing bounded wake fails instead of hanging."""

    return asyncio.run(asyncio.wait_for(coro, WATCHDOG_SECONDS))


# --- Provider wrappers -------------------------------------------------------------------


class Hooked:
    """Delegates to a client; runs ``before[index]()`` just before call ``index``."""

    def __init__(self, inner, before) -> None:
        self.inner = inner
        self.before = dict(before)
        self.calls = 0

    async def complete(self, request):
        index = self.calls
        self.calls += 1
        action = self.before.get(index)
        if action is not None:
            action()
        return await self.inner.complete(request)


class Hanging:
    """A provider whose first call never answers (the outer timeout must fire)."""

    def __init__(self, inner=None) -> None:
        self.inner = inner

    async def complete(self, request):
        await asyncio.Event().wait()


def _rate_limited(retry_after):
    return refuse(429, headers={"Retry-After": str(retry_after)})


def _slow_down(retry_after):
    """A non-refusal rate limit: classified, but not re-sent by S4."""

    return ProviderFailure("rate_limit", "slow down", retryable=True, retry_after_seconds=retry_after)


# --- Driving AttemptExecutor ----------------------------------------------------------------


class RouteRig:
    """One logical action through ``AttemptExecutor`` with fixed identities."""

    def __init__(self, tmp_path, steps, profile, *, registry=None, wrap=None, name="evidence"):
        self.profile = profile
        self.registry = registry
        self.wire = Wire(steps)
        client = build_client(self.wire)
        self.provider = wrap(client) if wrap else client
        self.root = tmp_path / name
        self.evidence = EvidenceStore(
            self.root,
            run_plan_id="runplan_fixture",
            cell_id="cell_fixture",
            episode_id="episode_fixture",
            episode_attempt_id="episode_attempt_fixture_0",
            clock=lambda: "2026-10-05T00:00:00Z",
        )
        kwargs = {} if registry is None else {"route_health": registry}
        self.executor = AttemptExecutor(
            evidence=self.evidence,
            profiles=(profile,),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": self.provider},
            pricing={MODEL: PRICING},
            harnesses=default_harnesses(),
            **kwargs,
        )
        self.decision = _decision()
        self.response = None
        self.error: BaseException | None = None

    @property
    def health(self):
        return self.registry.health_for(self.profile)

    def run(self) -> "RouteRig":
        try:
            self.response = run_async(self.executor(self.decision))
        except BaseException as error:  # noqa: BLE001 - CancelledError is the point
            self.error = error
        return self

    @property
    def log(self):
        return read_log(self.root)

    @property
    def execution(self):
        return self.executor.execution_for(self.decision.logical_action_id)

    def close(self) -> None:
        self.evidence.close()


def make_rig(tmp_path, steps, config=None, *, registry=None, wrap=None, seed=None, **profile_kwargs):
    """A rig on a fresh registry (unless given), optionally seeded before it runs."""

    registry = _new_registry() if registry is None else registry
    profile = route_profile(config, **profile_kwargs)
    rig = RouteRig(tmp_path, steps, profile, registry=registry, wrap=wrap)
    if seed is not None:
        seed(rig.health)
    return rig


def assert_failed_with(rig, condition):
    assert isinstance(rig.error, ProviderFailure), (
        f"expected the logical action to fail with {condition!r}; it ended with {rig.error!r}"
    )
    assert rig.error.condition == condition
    return rig.error


def open_breaker(health, *, failures=3, at=None):
    """Drive ``health`` to a breaker opening with ``failures`` transients."""

    for n in range(failures):
        health.report(condition="provider_5xx", ref=ref(n))


# --- Driving execute_plan_cell ------------------------------------------------------------


async def _execute(setup, root, wire, registry, *, ordinal=0, wrap=None):
    client = build_client(wire)
    provider = wrap(client) if wrap else client
    kwargs = {} if registry is None else {"route_health": registry}
    return await execute_plan_cell(
        plan=setup.plan,
        cell_id=setup.plan.cells[0].cell_id,
        registry=setup.registry,
        evidence_root=root,
        prompt_sources=setup.prompt_sources,
        providers={"openrouter": provider},
        pricing=setup.pricing,
        episode_attempt_ordinal=ordinal,
        **kwargs,
    )


def run_route_cell(
    tmp_path,
    monkeypatch,
    steps,
    *,
    registry=None,
    seed=None,
    name="run",
    ordinal=0,
    wrap=None,
    config=None,
    **plan_kwargs,
):
    """``execute_plan_cell`` with the real SDK behind the kernel client.

    ``seed(health)`` runs on the route's state before the cell starts, standing
    in for what earlier cells of the process left behind.
    """

    setup = _plan_setup(monkeypatch, config=_r1() if config is None else config, **plan_kwargs)
    wire = Wire(steps)
    root = tmp_path / name
    outcome = SimpleNamespace(
        setup=setup, wire=wire, root=root, execution=None, error=None, registry=registry
    )
    profile = setup.plan.agent_profiles[0]
    outcome.profile = profile
    if registry is not None and seed is not None:
        seed(registry.health_for(profile))
    try:
        outcome.execution = run_async(
            _execute(setup, root, wire, registry, ordinal=ordinal, wrap=wrap)
        )
        outcome.attempt_dir = outcome.execution.evidence.root
    except BaseException as error:  # noqa: BLE001
        outcome.error = error
        # A refusal at construction leaves no event log behind.
        logs = sorted(root.rglob("events.jsonl")) if root.exists() else []
        outcome.attempt_dir = logs[0].parent if logs else None
    outcome.log = read_log(outcome.attempt_dir) if outcome.attempt_dir is not None else []
    outcome.failure = _provider_failure_in(outcome.error)
    outcome.health = None if registry is None else registry.health_for(profile)
    return outcome


# =====================================================================================
# V1  Validation
# =====================================================================================


def _declared(profile):
    from aeread.shared_runner.task.execution import declared_route_policy

    return declared_route_policy(profile)


def test_v1_no_declaration_means_no_route_policy() -> None:
    assert _declared(route_profile(dict(V1))) is None


def test_v1_a_well_formed_declaration_is_accepted_at_its_boundaries() -> None:
    policy = _declared(route_profile(_r1()))
    assert policy is not None
    assert dataclasses.is_dataclass(policy)
    assert (
        policy.open_after_failures,
        policy.cooldown_seconds,
        policy.cooldown_cap_seconds,
        policy.max_outage_seconds,
    ) == (3, 30.0, 120.0, 600.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.open_after_failures = 4
    # Equal declarations are equal values (the registry compares them).
    assert policy == _declared(route_profile(_r1()))

    edge = _declared(
        route_profile(
            _r1(
                route_open_after_failures=1,
                route_cooldown_seconds=604800,
                route_cooldown_cap_seconds=604800,
                route_max_outage_seconds=604800,
            )
        )
    )
    assert edge.open_after_failures == 1
    assert edge.cooldown_seconds == edge.cooldown_cap_seconds == edge.max_outage_seconds == 604800
    top = _declared(route_profile(_r1(route_open_after_failures=50, route_cooldown_seconds=0.001,
                                      route_cooldown_cap_seconds=0.001, route_max_outage_seconds=0.001)))
    assert top.open_after_failures == 50


# NaN and infinity cannot reach declared_route_policy: AgentProfile refuses non-finite
# JSON values at construction. Huge integers can (S4's overflow lesson).
_MALFORMED = {
    "policy_wrong_string": {"route_policy": "route_v2"},
    "policy_not_a_string": {"route_policy": True},
    "without_transport_v1": {"transport_policy": None, "transport_max_calls": None,
                             "transport_max_retry_seconds": None},
    "open_after_zero": {"route_open_after_failures": 0},
    "open_after_51": {"route_open_after_failures": 51},
    "open_after_bool": {"route_open_after_failures": True},
    "open_after_float": {"route_open_after_failures": 3.0},
    "open_after_string": {"route_open_after_failures": "3"},
    "open_after_huge": {"route_open_after_failures": 10**400},
    "open_after_missing": {"route_open_after_failures": None},
    "cooldown_zero": {"route_cooldown_seconds": 0},
    "cooldown_negative": {"route_cooldown_seconds": -1.0},
    "cooldown_604801": {"route_cooldown_seconds": 604801, "route_cooldown_cap_seconds": 604800},
    "cooldown_bool": {"route_cooldown_seconds": True},
    "cooldown_huge": {"route_cooldown_seconds": 10**400},
    "cooldown_string": {"route_cooldown_seconds": "30"},
    "cooldown_missing": {"route_cooldown_seconds": None},
    "cap_below_cooldown": {"route_cooldown_cap_seconds": 29.0},
    "cap_604801": {"route_cooldown_cap_seconds": 604801},
    "cap_huge": {"route_cooldown_cap_seconds": 10**400},
    "cap_bool": {"route_cooldown_cap_seconds": True},
    "cap_missing": {"route_cooldown_cap_seconds": None},
    "outage_zero": {"route_max_outage_seconds": 0},
    "outage_negative": {"route_max_outage_seconds": -5},
    "outage_604801": {"route_max_outage_seconds": 604801},
    "outage_huge": {"route_max_outage_seconds": 10**400},
    "outage_bool": {"route_max_outage_seconds": True},
    "outage_missing": {"route_max_outage_seconds": None},
}


def _malformed_profile(overrides):
    config = _r1()
    for key, value in overrides.items():
        if value is None:
            config.pop(key)
        else:
            config[key] = value
    return route_profile(config)


@pytest.mark.parametrize("case", sorted(_MALFORMED))
def test_v1_every_malformed_declaration_is_refused(case) -> None:
    with pytest.raises(EvidenceIntegrityError):
        _declared(_malformed_profile(_MALFORMED[case]))


@pytest.mark.parametrize("case", ["open_after_zero", "without_transport_v1", "cap_below_cooldown", "outage_huge"])
def test_v1_the_attempt_executor_refuses_a_malformed_declaration_at_construction(tmp_path, case) -> None:
    with pytest.raises(EvidenceIntegrityError):
        RouteRig(tmp_path, [], _malformed_profile(_MALFORMED[case]), registry=_new_registry())


def test_v1_route_v1_without_a_registry_is_refused_at_construction(tmp_path) -> None:
    with pytest.raises(EvidenceIntegrityError):
        RouteRig(tmp_path, [], route_profile(_r1()), registry=None)


def test_v1_execute_plan_cell_refuses_route_v1_without_a_registry_before_any_call(
    tmp_path, monkeypatch
) -> None:
    run = run_route_cell(tmp_path, monkeypatch, [ok()], registry=None)

    assert isinstance(run.error, EvidenceIntegrityError), repr(run.error)
    assert run.wire.requests == 0
    _release_evidence_lock(run.error)


def test_v1_the_direct_minimal_chat_executor_refuses_route_v1(tmp_path) -> None:
    evidence = EvidenceStore(
        tmp_path / "direct",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    with pytest.raises(EvidenceIntegrityError):
        MinimalChatExecutor(
            evidence=evidence,
            profiles=(route_profile(_r1()),),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": build_client(Wire([]))},
            pricing={MODEL: PRICING},
        )
    evidence.close()


def test_v1_the_attempt_executor_accepts_a_valid_route_v1_profile_with_a_registry(tmp_path) -> None:
    rig = RouteRig(tmp_path, [], route_profile(_r1()), registry=_new_registry())
    rig.close()


def test_v1_two_profiles_on_one_key_with_different_policies_are_refused(tmp_path) -> None:
    first = route_profile(_r1(), profile_id="subject_a")
    second = route_profile(_r1(route_cooldown_seconds=31.0), profile_id="subject_b")
    evidence = EvidenceStore(
        tmp_path / "pair",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    with pytest.raises(EvidenceIntegrityError):
        AttemptExecutor(
            evidence=evidence,
            profiles=(first, second),
            prompt_sources={PROMPT_ID: PROMPT},
            providers={"openrouter": build_client(Wire([]))},
            pricing={MODEL: PRICING},
            harnesses=default_harnesses(),
            route_health=_new_registry(),
        )
    evidence.close()


def test_v1_two_profiles_on_one_key_with_equal_policies_are_accepted(tmp_path) -> None:
    first = route_profile(_r1(), profile_id="subject_a")
    second = route_profile(_r1(), profile_id="subject_b")
    registry = _new_registry()
    evidence = EvidenceStore(
        tmp_path / "pair_ok",
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
    )
    AttemptExecutor(
        evidence=evidence,
        profiles=(first, second),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": build_client(Wire([]))},
        pricing={MODEL: PRICING},
        harnesses=default_harnesses(),
        route_health=registry,
    )
    assert registry.health_for(first) is registry.health_for(second)
    evidence.close()


def test_v1_a_policy_that_conflicts_with_the_registered_one_is_refused_at_construction(tmp_path) -> None:
    registry = _new_registry()
    RouteRig(tmp_path, [], route_profile(_r1()), registry=registry, name="first").close()

    with pytest.raises(EvidenceIntegrityError):
        RouteRig(
            tmp_path,
            [],
            route_profile(_r1(route_max_outage_seconds=601.0)),
            registry=registry,
            name="second",
        )


# =====================================================================================
# K1  Route keys
# =====================================================================================


def _pinned(runtime, **kwargs):
    """A profile with ``provider_runtime`` pins and no ``provider_metadata``."""

    return route_profile(_r1(provider_runtime=runtime), remove=("provider_metadata",), **kwargs)


def _key(profile):
    from aeread.shared_runner.task.execution import route_health_key

    return route_health_key(profile)


def test_k1_different_provider_runtime_pins_are_separate_keys() -> None:
    first = _pinned({"route_provider": "DeepInfra", "quantization": "fp8"})
    second = _pinned({"route_provider": "Together", "quantization": "fp8"})

    assert _key(first) != _key(second)
    registry = _new_registry()
    assert registry.health_for(first) is not registry.health_for(second)


def test_k1_equal_effective_metadata_in_different_key_order_is_one_key() -> None:
    first = _pinned({"route_provider": "DeepInfra", "quantization": "fp8"})
    second = _pinned({"quantization": "fp8", "route_provider": "DeepInfra"})

    assert _key(first) == _key(second)
    registry = _new_registry()
    assert registry.health_for(first) is registry.health_for(second)
    hash(_key(first))


def test_k1_the_key_is_provider_base_url_model_and_the_canonical_effective_metadata() -> None:
    profile = route_profile(_r1())
    key = _key(profile)

    assert tuple(key[:3]) == ("openrouter", BASE_URL, MODEL)
    assert json.loads(key[3]) == PROVIDER_METADATA
    pinned = _pinned({"route_provider": "DeepInfra"})
    assert json.loads(_key(pinned)[3]) == {"route_provider": "DeepInfra"}


def test_k1_provider_metadata_is_part_of_the_key() -> None:
    other = route_profile(_r1(provider_metadata={**PROVIDER_METADATA, "quantization": "bf16"}))
    assert _key(route_profile(_r1())) != _key(other)


def test_k1_model_and_base_url_are_part_of_the_key() -> None:
    base = _key(route_profile(_r1()))
    assert base != _key(route_profile(_r1(), model="deepseek/other-model"))
    assert base != _key(route_profile(_r1(), base_url="https://example.invalid/api/v1"))


def test_k1_one_key_is_one_health_object_per_registry() -> None:
    registry = _new_registry()
    profile = route_profile(_r1())
    assert registry.health_for(profile) is registry.health_for(route_profile(_r1()))
    assert _new_registry().health_for(profile) is not registry.health_for(profile)


# =====================================================================================
# H1-H8  RouteHealth
# =====================================================================================


def test_h1_three_transients_open_the_breaker_once_and_the_next_opening_uses_the_doubled_cooldown(uclock) -> None:
    health = _health()

    for n in range(2):
        health.report(condition="provider_5xx", ref=ref(n))
    assert health.failures == 2
    assert health.cooldown_until is None
    assert health.admits() is True

    health.report(condition="provider_5xx", ref=ref(2))
    assert health.cooldown_until == 10.0
    assert health.failures == 0
    assert health.cooldown == 20.0
    assert health.outage_start == 0.0
    assert health.cooldown_ref == ref(2)
    assert health.admits() is False

    # Each later crossing, once the previous cooldown ran out, uses the doubled
    # cooldown: 20, then 40, then the cap (40) again.
    expected = [(10.0, 30.0, 40.0), (30.0, 70.0, 40.0), (70.0, 110.0, 40.0)]
    for at, until, cooldown_after in expected:
        uclock.now = at
        assert health.admits() is True
        for n in range(3):
            health.report(condition="timeout", ref=ref(10 + n, "timeout"))
        assert health.cooldown_until == until
        assert health.cooldown == cooldown_after
        assert health.failures == 0
        assert health.outage_start == 0.0


def test_h1_every_transient_condition_counts_toward_the_threshold(uclock) -> None:
    health = _health()
    for condition in ("rate_limit", "provider_5xx", "timeout", "transport"):
        health.report(condition=condition, ref=ref(0, condition))
    assert health.failures == 1  # the fourth crossed the threshold at 3 and reset
    assert health.cooldown_until == 10.0


def test_h2_a_success_mid_outage_ends_it_and_a_later_outage_starts_a_fresh_timer(uclock) -> None:
    health = _health(route_max_outage_seconds=150.0)
    open_breaker(health)
    assert health.outage_start == 0.0
    assert health.cooldown == 20.0

    uclock.now = 5.0
    health.report(success=True, ref=ref(9, "success"))
    assert health.failures == 0
    assert health.cooldown_until is None
    assert health.cooldown == 10.0
    assert health.pause_until is None
    assert health.outage_start is None
    assert health.admits() is True

    uclock.now = 100.0
    open_breaker(health)
    assert health.outage_start == 100.0
    # The old timer (origin 0) would have exhausted the route by now; the fresh one has not.
    uclock.now = 160.0
    assert health.admits() is True
    assert health.exhausted is None


def test_h3_a_long_retry_after_pauses_the_route_uncapped_and_keeps_its_reference(uclock) -> None:
    health = _health(route_open_after_failures=5)

    health.report(condition="rate_limit", retry_after_seconds=120.0, ref=ref(0, "rate_limit"))
    assert health.pause_until == 120.0
    assert health.pause_ref == ref(0, "rate_limit")
    assert health.outage_start == 0.0
    assert health.admits() is False
    assert health.snapshot()["state"] == "paused"

    # A later, shorter pause never shortens it, and the reference stays on the 120 s terminal.
    uclock.now = 1.0
    health.report(condition="rate_limit", retry_after_seconds=5.0, ref=ref(1, "rate_limit"))
    assert health.pause_until == 120.0
    assert health.pause_ref == ref(0, "rate_limit")

    # A sub-threshold transient changes no reference.
    uclock.now = 2.0
    health.report(condition="provider_5xx", ref=ref(2))
    assert health.pause_ref == ref(0, "rate_limit")
    assert health.cooldown_ref is None
    assert health.cooldown_until is None

    # A success during the pause does not end it.
    uclock.now = 3.0
    health.report(success=True, ref=ref(3, "success"))
    assert health.pause_until == 120.0
    assert health.pause_ref == ref(0, "rate_limit")
    assert health.outage_start == 0.0
    assert health.failures == 0
    assert health.admits() is False

    uclock.now = 120.0
    assert health.admits() is True


@pytest.mark.parametrize("retry_after", [5.0, 0.5, 120.0])
def test_h3_every_positive_retry_after_pauses_the_route_for_other_cells(uclock, retry_after) -> None:
    health = _health(route_open_after_failures=5)

    health.report(condition="rate_limit", retry_after_seconds=retry_after, ref=ref(0, "rate_limit"))

    assert health.pause_until == retry_after
    uclock.now = retry_after - 0.25
    assert health.admits() is False
    uclock.now = retry_after
    assert health.admits() is True  # equality admits


@pytest.mark.parametrize("retry_after", [None, 0.0])
def test_h3_a_rate_limit_without_a_positive_retry_after_pauses_nothing(uclock, retry_after) -> None:
    health = _health(route_open_after_failures=5)

    health.report(condition="rate_limit", retry_after_seconds=retry_after, ref=ref(0, "rate_limit"))

    assert health.pause_until is None
    assert health.pause_ref is None
    assert health.failures == 1
    assert health.outage_start is None


def test_h3_a_retry_after_on_a_non_rate_limit_condition_pauses_nothing(uclock) -> None:
    health = _health(route_open_after_failures=5)
    health.report(condition="provider_5xx", retry_after_seconds=90.0, ref=ref(0))
    assert health.pause_until is None


@pytest.mark.parametrize(
    "at, exhausted",
    [(99.999, None), (100.0, "outage_bound_reached"), (150.0, "outage_bound_reached")],
)
def test_h4_an_outage_reaching_the_bound_exactly_exhausts_the_route(uclock, at, exhausted) -> None:
    health = _health(
        route_open_after_failures=1,
        route_cooldown_seconds=10.0,
        route_cooldown_cap_seconds=10.0,
        route_max_outage_seconds=100.0,
    )
    health.report(condition="provider_5xx", ref=ref(0))
    assert health.outage_start == 0.0 and health.exhausted is None

    uclock.now = at
    assert health.admits() is (exhausted is None)
    assert health.exhausted == exhausted


def test_h4_a_success_after_the_bound_does_not_revive_the_route(uclock) -> None:
    health = _health(
        route_open_after_failures=1,
        route_cooldown_seconds=10.0,
        route_cooldown_cap_seconds=10.0,
        route_max_outage_seconds=100.0,
    )
    health.report(condition="provider_5xx", ref=ref(0))

    # A call that was already running succeeds after the bound, with no
    # admission check or waiter in between: time comes first.
    uclock.now = 100.0
    health.report(success=True, ref=ref(1, "success"))

    assert health.exhausted == "outage_bound_reached"
    assert health.outage_start == 0.0
    assert health.cooldown_until == 10.0
    assert health.admits() is False


def test_h4_exhaustion_is_terminal_and_later_reports_change_nothing(uclock) -> None:
    health = _health(route_open_after_failures=1, route_max_outage_seconds=100.0)
    health.report(condition="provider_5xx", ref=ref(0))
    uclock.now = 100.0
    assert health.admits() is False
    frozen = state_of(health)

    health.report(success=True, ref=ref(1, "success"))
    health.report(condition="rate_limit", retry_after_seconds=500.0, ref=ref(2, "rate_limit"))
    health.report(condition="provider_5xx", ref=ref(3))

    assert state_of(health) == frozen
    assert health.admits() is False


def test_h4_a_gate_waiter_wakes_by_its_bounded_sleep_and_fails_without_another_event(
    tmp_path, clock
) -> None:
    config = _r1(
        route_open_after_failures=1,
        route_cooldown_seconds=50.0,
        route_cooldown_cap_seconds=50.0,
        route_max_outage_seconds=100.0,
    )

    async def jump_past_the_bound(fake, seconds):
        fake.now = START + 100.0

    clock.on_sleep = jump_past_the_bound
    rig = make_rig(
        tmp_path,
        [ok()],
        config,
        seed=lambda health: health.report(condition="provider_5xx", ref=ref(0)),
    ).run()

    assert_failed_with(rig, "route_unavailable")
    assert rig.wire.requests == 0
    # One sleep, to the earlier of the cooldown (50 s) and the outage bound (100 s).
    assert clock.sleeps == [50.0]
    log = rig.log
    (completed,) = exactly(of(log, "route_wait_completed"), 1)
    assert completed["payload"]["outcome"] == "route_unavailable"
    assert completed["payload"]["waited_seconds"] == 100.0
    assert rig.health.exhausted == "outage_bound_reached"


@pytest.mark.parametrize(
    "retry_after, cooldown, outage, cause",
    [
        (500.0, 10.0, 400.0, "pause_past_outage_bound"),
        (60.0, 60.0, 50.0, "pause_past_outage_bound"),  # tie: the pause wins
        (5.0, 60.0, 50.0, "cooldown_past_outage_bound"),
    ],
)
def test_h5_a_threshold_crossing_long_429_opens_once_and_exhausts_by_the_tie_rule(
    uclock, retry_after, cooldown, outage, cause
) -> None:
    health = _health(
        route_open_after_failures=1,
        route_cooldown_seconds=cooldown,
        route_cooldown_cap_seconds=max(cooldown, 100.0),
        route_max_outage_seconds=outage,
    )

    health.report(condition="rate_limit", retry_after_seconds=retry_after, ref=ref(0, "rate_limit"))

    assert health.cooldown == min(cooldown * 2, max(cooldown, 100.0))  # doubled once, not twice
    assert health.failures == 0
    assert health.cooldown_until == cooldown
    assert health.pause_until == retry_after
    assert health.cooldown_ref == ref(0, "rate_limit")
    assert health.pause_ref == ref(0, "rate_limit")
    assert health.outage_start == 0.0
    assert health.exhausted == cause


def test_h5_a_threshold_crossing_long_429_inside_the_bound_sets_both_deadlines_once(uclock) -> None:
    health = _health(route_open_after_failures=1, route_max_outage_seconds=1000.0)

    health.report(condition="rate_limit", retry_after_seconds=500.0, ref=ref(0, "rate_limit"))

    assert health.exhausted is None
    assert health.cooldown == 20.0
    assert health.cooldown_until == 10.0
    assert health.pause_until == 500.0
    assert health.snapshot()["state"] == "paused"


def test_h6_a_reopening_at_clock_five_keeps_the_outage_start_at_origin_zero(uclock) -> None:
    health = _health(
        route_open_after_failures=1, route_cooldown_seconds=1.0, route_cooldown_cap_seconds=4.0
    )
    health.report(condition="provider_5xx", ref=ref(0))
    assert health.outage_start == 0.0

    uclock.now = 5.0
    health.report(condition="provider_5xx", ref=ref(1))

    assert health.outage_start == 0.0  # not reset by a falsy origin


def test_h7_two_thousand_reopenings_never_raise_and_the_cooldown_stays_at_the_cap(uclock) -> None:
    health = _health(
        route_open_after_failures=1,
        route_cooldown_seconds=1.0,
        route_cooldown_cap_seconds=60.0,
        route_max_outage_seconds=604800.0,
    )

    for n in range(2000):
        health.report(condition="provider_5xx", ref=ref(n))
        assert health.cooldown <= 60.0
        uclock.now = health.cooldown_until
        assert health.admits() is True

    assert health.cooldown == 60.0
    assert health.exhausted is None
    assert health.snapshot()["cooldown"] == 60.0


def test_h7_a_huge_finite_retry_after_is_total(uclock) -> None:
    health = _health(route_open_after_failures=1, route_max_outage_seconds=100.0)

    health.report(condition="rate_limit", retry_after_seconds=1e308, ref=ref(0, "rate_limit"))

    assert health.exhausted == "pause_past_outage_bound"
    snapshot = health.snapshot()
    assert snapshot["state"] == "exhausted"


@pytest.mark.parametrize(
    "condition",
    [
        "provider_rejected",  # a 404
        "account_fault",  # a 402
        "provider_contract",
        "length",
        "empty_response",
        "provider_choice_error",
        "interrupted_during_provider_call",
    ],
)
def test_h8_ignored_outcomes_change_nothing(uclock, condition) -> None:
    health = _health(route_open_after_failures=5)
    health.report(condition="provider_5xx", ref=ref(0))
    before = state_of(health)
    uclock.now = 2.0

    health.report(condition=condition, retry_after_seconds=30.0, ref=ref(1, condition))

    assert state_of(health) == before


def test_h8_a_cancellation_during_a_call_reports_nothing(tmp_path, reports) -> None:
    rig = make_rig(
        tmp_path,
        [ok()],
        wrap=lambda client: Injecting(client, {0: asyncio.CancelledError()}),
    ).run()

    assert isinstance(rig.error, asyncio.CancelledError), repr(rig.error)
    assert reports == []
    assert rig.health.failures == 0
    assert rig.health.outage_start is None


# =====================================================================================
# S1  Snapshot
# =====================================================================================


def test_s1_a_fresh_route_is_closed_with_absent_deadlines_and_the_documented_keys(uclock) -> None:
    snapshot = _health().snapshot()

    assert set(snapshot) == ROUTE_KEYS
    assert snapshot["state"] == "closed"
    assert snapshot["cooldown_until_in"] is None
    assert snapshot["pause_until_in"] is None
    assert snapshot["exhausted"] is None
    assert snapshot["cause_ref"] is None
    assert snapshot["failures"] == 0
    assert snapshot["cooldown"] == 10.0


def test_s1_cooling_names_the_cooldown_terminal_and_times_are_relative(uclock) -> None:
    health = _health()
    open_breaker(health)
    uclock.now = 4.0

    snapshot = health.snapshot()

    assert snapshot["state"] == "cooling"
    assert snapshot["cooldown_until_in"] == 6.0
    assert snapshot["pause_until_in"] is None
    assert snapshot["cause_ref"] == ref(2)
    assert snapshot["outage_age"] == 4.0
    assert snapshot["cooldown"] == 20.0


def test_s1_paused_names_the_pause_terminal(uclock) -> None:
    health = _health(route_open_after_failures=5)
    health.report(condition="rate_limit", retry_after_seconds=50.0, ref=ref(0, "rate_limit"))
    uclock.now = 10.0

    snapshot = health.snapshot()

    assert snapshot["state"] == "paused"
    assert snapshot["pause_until_in"] == 40.0
    assert snapshot["cause_ref"] == ref(0, "rate_limit")


def test_s1_the_later_deadline_decides_between_paused_and_cooling_and_ties_go_to_the_pause(uclock) -> None:
    cooling = _health(route_open_after_failures=1, route_cooldown_seconds=60.0, route_cooldown_cap_seconds=60.0)
    cooling.report(condition="rate_limit", retry_after_seconds=20.0, ref=ref(0, "rate_limit"))
    assert cooling.snapshot()["state"] == "cooling"
    assert cooling.snapshot()["cause_ref"] == cooling.cooldown_ref

    tie = _health(route_open_after_failures=1, route_cooldown_seconds=10.0)
    tie.report(condition="rate_limit", retry_after_seconds=10.0, ref=ref(1, "rate_limit"))
    assert tie.snapshot()["state"] == "paused"


def test_s1_recovering_after_the_deadlines_pass_names_the_later_deadline_ties_to_the_pause(uclock) -> None:
    health = _health(route_open_after_failures=1, route_cooldown_seconds=10.0)
    health.report(condition="rate_limit", retry_after_seconds=10.0, ref=ref(0, "rate_limit"))
    assert health.cooldown_until == health.pause_until == 10.0  # the tie
    uclock.now = 11.0

    snapshot = health.snapshot()

    assert snapshot["state"] == "recovering"
    assert snapshot["cause_ref"] == health.pause_ref

    uclock.now = 0.0
    cooldown_only = _health(route_open_after_failures=1)
    cooldown_only.report(condition="provider_5xx", ref=ref(1))
    uclock.now = 11.0
    snapshot = cooldown_only.snapshot()
    assert snapshot["state"] == "recovering"
    assert snapshot["cause_ref"] == ref(1)


def test_s1_a_success_after_the_deadlines_closes_the_route(uclock) -> None:
    health = _health(route_open_after_failures=1)
    health.report(condition="provider_5xx", ref=ref(0))
    uclock.now = 11.0
    assert health.snapshot()["state"] == "recovering"

    health.report(success=True, ref=ref(1, "success"))

    snapshot = health.snapshot()
    assert snapshot["state"] == "closed"
    assert snapshot["cause_ref"] is None
    assert snapshot["outage_age"] is None


def test_s1_exhausted_wins_over_everything_and_names_the_later_deadline(uclock) -> None:
    health = _health(
        route_open_after_failures=1,
        route_cooldown_seconds=10.0,
        route_max_outage_seconds=100.0,
    )
    health.report(condition="rate_limit", retry_after_seconds=5.0, ref=ref(0, "rate_limit"))
    uclock.now = 100.0

    snapshot = health.snapshot()

    assert snapshot["state"] == "exhausted"
    assert snapshot["exhausted"] == "outage_bound_reached"
    # The cooldown (10) is later than the pause (5): its terminal is the cause.
    assert snapshot["cause_ref"] == health.cooldown_ref


# =====================================================================================
# G1-G6  The call-0 gate, end to end
# =====================================================================================


def _cooling(health):
    open_breaker(health)  # three transients at START: cooldown 30 s


def test_g1_a_gate_wait_longer_than_the_attempt_timeout_leaves_the_full_deadline(
    tmp_path, monkeypatch, clock
) -> None:
    registry = _new_registry()
    config = _r1(transport_max_retry_seconds=8.0)
    run = run_route_cell(
        tmp_path,
        monkeypatch,
        [refuse(503), ok()],
        registry=registry,
        seed=_cooling,
        config=config,
        timeout_seconds=10.0,
    )

    assert run.error is None, repr(run.error)
    # The 30 s wait exceeds the 10 s attempt timeout; call 0 was refused and
    # re-sent, which needs an attempt deadline measured from after the wait.
    assert run.wire.requests == 2
    log = run.log
    assert kinds(
        log,
        "action_attempt_started",
        "route_wait_started",
        "route_wait_completed",
        "provider_call_started",
    )[:4] == [
        "action_attempt_started",
        "route_wait_started",
        "route_wait_completed",
        "provider_call_started",
    ]
    (attempt_started,) = exactly(of(log, "action_attempt_started"), 1)
    (wait_started,) = exactly(of(log, "route_wait_started"), 1)
    (wait_completed,) = exactly(of(log, "route_wait_completed"), 1)
    assert wait_started["action_attempt_id"] == attempt_started["action_attempt_id"]
    assert wait_completed["action_attempt_id"] == attempt_started["action_attempt_id"]
    assert set(wait_started["payload"]["route"]) == ROUTE_KEYS
    assert wait_started["payload"]["route"]["state"] == "cooling"
    assert wait_started["payload"]["route"]["cooldown_until_in"] == 30.0
    assert wait_completed["payload"]["outcome"] == "admitted"
    assert wait_completed["payload"]["waited_seconds"] == 30.0
    assert set(wait_completed["payload"]["route"]) == ROUTE_KEYS
    assert clock.sleeps[0] == 30.0
    assert run.health.snapshot()["state"] == "closed"
    run.execution.evidence.audit_reconciliation()


def test_g1_a_healthy_route_writes_no_wait_events(tmp_path, monkeypatch, clock) -> None:
    run = run_route_cell(tmp_path, monkeypatch, [ok()], registry=_new_registry())

    assert run.error is None, repr(run.error)
    assert of(run.log, "route_wait_started", "route_wait_completed") == []
    assert clock.sleeps == []


def _exhaust_by_long_retry_after(health):
    health.report(condition="rate_limit", retry_after_seconds=500.0, ref=ref(7, "rate_limit"))


def test_g2_the_gate_on_an_exhausted_route_fails_with_route_unavailable_and_a_snapshot(tmp_path) -> None:
    config = _r1(route_max_outage_seconds=100.0)
    rig = make_rig(tmp_path, [ok()], config, seed=_exhaust_by_long_retry_after).run()

    error = assert_failed_with(rig, "route_unavailable")
    assert error.retryable is False
    assert rig.wire.requests == 0
    log = rig.log
    assert kinds(
        log,
        "action_attempt_started",
        "route_wait_started",
        "route_wait_completed",
        "action_attempt_failed",
        "logical_action_failed",
        "provider_call_started",
        "provider_call_failed",
        "provider_call_succeeded",
        "provider_call_outcome_unknown",
    ) == ["action_attempt_started", "action_attempt_failed", "logical_action_failed"]
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["failure_condition"] == "route_unavailable"
    route = failed["payload"]["route"]
    assert set(route) == ROUTE_KEYS
    assert route["state"] == "exhausted"
    assert route["exhausted"] == "pause_past_outage_bound"
    assert route["cause_ref"] == ref(7, "rate_limit")
    (logical,) = exactly(of(log, "logical_action_failed"), 1)
    assert logical["payload"]["failure_condition"] == "route_unavailable"

    execution = rig.execution
    assert execution.status == "failed"
    assert execution.failure_code == "route_unavailable"
    (attempt,) = exactly(execution.attempts, 1)
    assert attempt.status == "failed"
    assert attempt.provider_calls == ()
    assert attempt.canonical_response is None
    assert attempt.ordinal == 0
    rig.evidence.audit_reconciliation()
    _assert_evidence_survives_audit_and_resume(rig)


def test_g2_the_record_keeps_earlier_attempts_and_adds_the_failed_gate_attempt(tmp_path) -> None:
    config = _r1(route_max_outage_seconds=100.0)
    rig = make_rig(
        tmp_path,
        [ok()],
        config,
        wrap=lambda client: Injecting(client, {0: _slow_down(500.0)}),
    ).run()

    assert_failed_with(rig, "route_unavailable")
    log = rig.log
    assert kinds(
        log,
        "action_attempt_started",
        "provider_call_started",
        "provider_call_failed",
        "action_attempt_failed",
        "route_wait_started",
        "route_wait_completed",
        "logical_action_failed",
    ) == [
        "action_attempt_started",
        "provider_call_started",
        "provider_call_failed",
        "action_attempt_failed",
        "action_attempt_started",
        "action_attempt_failed",
        "logical_action_failed",
    ]
    (c0,) = exactly(started_ids(log), 1)
    second_failed = of(log, "action_attempt_failed")[1]
    assert second_failed["payload"]["failure_condition"] == "route_unavailable"
    assert second_failed["payload"]["route"]["exhausted"] == "pause_past_outage_bound"
    assert second_failed["payload"]["route"]["cause_ref"] == {
        "episode_attempt_id": "episode_attempt_fixture_0",
        "provider_call_id": c0,
        "condition": "rate_limit",
    }
    execution = rig.execution
    assert execution.status == "failed"
    assert execution.failure_code == "route_unavailable"
    first, current = exactly(execution.attempts, 2)
    assert (first.ordinal, first.status) == (0, "failed")
    assert [call.provider_call_id for call in first.provider_calls] == [c0]
    assert (current.ordinal, current.status) == (1, "failed")
    assert current.provider_calls == ()
    assert current.canonical_response is None
    assert current.retry_reason == "rate_limit"
    rig.evidence.audit_reconciliation()
    _assert_evidence_survives_audit_and_resume(rig)


def test_g2_route_unavailable_is_never_retried(tmp_path) -> None:
    config = _r1(route_max_outage_seconds=100.0)
    rig = make_rig(
        tmp_path, [ok(), ok()], config, seed=_exhaust_by_long_retry_after, max_action_attempts=3
    ).run()

    assert_failed_with(rig, "route_unavailable")
    assert len(of(rig.log, "action_attempt_started")) == 1
    assert rig.wire.requests == 0


def test_v1_route_unavailable_cannot_be_declared_retryable(tmp_path) -> None:
    profile = route_profile(_r1(), retryable=(*DECLARED, "route_unavailable"))

    with pytest.raises(EvidenceIntegrityError):
        _declared(profile)
    with pytest.raises(EvidenceIntegrityError):
        RouteRig(tmp_path, [], profile, registry=_new_registry())


async def _cancel_hook(fake, seconds):
    raise asyncio.CancelledError()


async def _boom_hook(fake, seconds):
    raise RuntimeError("boom")


@pytest.mark.parametrize(
    "hook, error_type, outcome",
    [
        (_cancel_hook, asyncio.CancelledError, "cancelled"),
        (_boom_hook, RuntimeError, "interrupted"),
    ],
    ids=["cancellation", "other_exception"],
)
def test_g3_an_interruption_at_the_gate_records_an_unopened_attempt(tmp_path, clock, hook, error_type, outcome) -> None:
    clock.on_sleep = hook
    rig = make_rig(
        tmp_path,
        [ok()],
        wrap=lambda client: Injecting(client, {0: _slow_down(20.0)}),
    ).run()

    assert isinstance(rig.error, error_type), repr(rig.error)
    log = rig.log
    # Attempt 0 failed on a rate limit; attempt 1 stopped at the gate.
    (c0,) = exactly(started_ids(log), 1)
    assert [e["event_type"] for e in log if e["event_type"].startswith("provider_call_")] == [
        "provider_call_started",
        "provider_call_failed",
    ]
    (wait_completed,) = exactly(of(log, "route_wait_completed"), 1)
    assert wait_completed["payload"]["outcome"] == outcome
    assert len(of(log, "route_wait_started")) == 1
    (unknown,) = exactly(of(log, "action_attempt_outcome_unknown"), 1)
    assert unknown["payload"]["failure_condition"] == "interrupted_before_provider_call"
    assert len(of(log, "logical_action_outcome_unknown")) == 1
    assert kinds(log, "route_wait_completed", "action_attempt_outcome_unknown", "logical_action_outcome_unknown") == [
        "route_wait_completed",
        "action_attempt_outcome_unknown",
        "logical_action_outcome_unknown",
    ]

    execution = rig.execution
    assert execution.status == "outcome_unknown"
    first, current = exactly(execution.attempts, 2)
    assert (first.ordinal, first.status) == (0, "failed")
    assert [call.provider_call_id for call in first.provider_calls] == [c0]
    assert (current.ordinal, current.status) == (1, "outcome_unknown")
    assert current.provider_calls == ()
    assert current.canonical_response is None
    rig.evidence.audit_reconciliation()
    _assert_evidence_survives_audit_and_resume(rig)


def test_g3_a_gate_interruption_on_the_first_attempt_records_exactly_one_attempt(tmp_path, clock) -> None:
    clock.on_sleep = _cancel_hook
    rig = make_rig(tmp_path, [ok()], seed=_cooling).run()

    assert isinstance(rig.error, asyncio.CancelledError), repr(rig.error)
    assert started_ids(rig.log) == []
    assert of(rig.log, "provider_call_outcome_unknown", "provider_call_failed") == []
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert attempt.status == "outcome_unknown"
    assert attempt.provider_calls == ()
    assert attempt.canonical_response is None
    _assert_evidence_survives_audit_and_resume(rig)


def test_g4_consecutive_cells_wait_at_the_gate_for_the_cooldown_cell_a_opened(
    tmp_path, monkeypatch, clock
) -> None:
    registry = _new_registry()
    config = _r1(transport_max_retry_seconds=30.0)

    cell_a = run_route_cell(
        tmp_path, monkeypatch, [refuse(503)] * 3, registry=registry, name="a", config=config
    )
    assert cell_a.failure is not None and cell_a.failure.condition == "provider_5xx", repr(cell_a.error)
    assert cell_a.wire.requests == 3
    assert of(cell_a.log, "route_wait_started") == []
    assert cell_a.health.snapshot()["state"] == "cooling"
    sleeps_before = len(clock.sleeps)
    _release_evidence_lock(cell_a.error)

    cell_b = run_route_cell(
        tmp_path, monkeypatch, [ok()], registry=registry, name="b", config=config
    )

    assert cell_b.error is None, repr(cell_b.error)
    assert cell_b.wire.requests == 1
    # The wait is the deadline minus a clock reading near 1002, so it is 30 up to float rounding.
    assert clock.sleeps[sleeps_before:] == pytest.approx([30.0], abs=1e-9)
    (wait_completed,) = exactly(of(cell_b.log, "route_wait_completed"), 1)
    assert wait_completed["payload"]["outcome"] == "admitted"
    assert wait_completed["payload"]["waited_seconds"] == pytest.approx(30.0, abs=1e-9)
    assert kinds(cell_b.log, "route_wait_started", "route_wait_completed", "provider_call_started") == [
        "route_wait_started",
        "route_wait_completed",
        "provider_call_started",
    ]


def test_g6_a_real_429_retry_after_pauses_the_route_for_the_next_cell(
    tmp_path, monkeypatch, clock
) -> None:
    registry = _new_registry()
    config = _r1(
        route_open_after_failures=3,
        retry_after_max_seconds=30.0,
        transport_max_retry_seconds=20.0,
    )

    cell_a = run_route_cell(
        tmp_path, monkeypatch, [_rate_limited(120), ok()], registry=registry, name="a", config=config
    )

    # A's re-send is denied by S4's own time check: the capped delay (30 s)
    # exceeds the 20 s window, whatever the route says.
    assert cell_a.failure is not None and cell_a.failure.condition == "rate_limit", repr(cell_a.error)
    assert cell_a.wire.requests == 1
    (failed,) = exactly(of(cell_a.log, "action_attempt_failed"), 1)
    assert failed["payload"]["transport_exhausted"] is True
    assert failed["payload"]["resend_denied_by"] == "time"
    assert "route" not in failed["payload"]
    (a_call,) = exactly(started_ids(cell_a.log), 1)
    a_attempt = of(cell_a.log, "provider_call_started")[0]["episode_attempt_id"]
    health = cell_a.health
    assert health.pause_until == START + 120.0
    # Saved before cell B runs: B's success clears the shared pause reference.
    a_ref = dict(health.pause_ref)
    assert a_ref == {
        "episode_attempt_id": a_attempt,
        "provider_call_id": a_call,
        "condition": "rate_limit",
    }
    assert clock.sleeps == []
    _release_evidence_lock(cell_a.error)

    cell_b = run_route_cell(
        tmp_path, monkeypatch, [ok()], registry=registry, name="b", config=config
    )

    assert cell_b.error is None, repr(cell_b.error)
    assert clock.sleeps == [120.0]
    (wait_started,) = exactly(of(cell_b.log, "route_wait_started"), 1)
    assert wait_started["payload"]["route"]["state"] == "paused"
    assert wait_started["payload"]["route"]["pause_until_in"] == 120.0
    assert wait_started["payload"]["route"]["cause_ref"] == a_ref
    (wait_completed,) = exactly(of(cell_b.log, "route_wait_completed"), 1)
    assert wait_completed["payload"]["outcome"] == "admitted"
    assert wait_completed["payload"]["waited_seconds"] == 120.0
    assert cell_b.wire.requests == 1
    assert health.snapshot()["state"] == "closed"


def test_g5_concurrent_cells_share_one_registry_without_a_lost_or_double_report(
    tmp_path, monkeypatch, reports
) -> None:
    registry = _new_registry()
    setup = _plan_setup(monkeypatch, config=_r1(route_open_after_failures=50))
    wires = [Wire([refuse(503), ok()]) for _ in range(3)]

    async def everything():
        return await asyncio.gather(
            *(
                _execute(setup, tmp_path / f"cell_{n}", wires[n], registry)
                for n in range(3)
            ),
            return_exceptions=True,
        )

    results = run_async(everything())

    failures = [r for r in results if isinstance(r, BaseException)]
    assert failures == [], repr(failures)
    assert sorted(report.label for report in reports) == ["provider_5xx"] * 3 + ["success"] * 3
    health = registry.health_for(setup.plan.agent_profiles[0])
    assert health.failures == 0
    assert health.snapshot()["state"] == "closed"
    assert [wire.requests for wire in wires] == [2, 2, 2]


def test_e1_the_same_cell_under_two_episode_attempt_ordinals_reports_both_executions(
    tmp_path, monkeypatch, reports
) -> None:
    registry = _new_registry()
    config = _r1(route_open_after_failures=50)

    first = run_route_cell(
        tmp_path, monkeypatch, [refuse(503), ok()], registry=registry, ordinal=0, config=config
    )
    second = run_route_cell(
        tmp_path, monkeypatch, [refuse(503), ok()], registry=registry, ordinal=1, config=config
    )

    assert first.error is None and second.error is None, (first.error, second.error)
    # Provider-call ids repeat across episode attempts of one cell; each
    # terminal is still reported once.
    assert [report.label for report in reports] == ["provider_5xx", "success"] * 2
    ids = [report.ref["provider_call_id"] for report in reports]
    assert ids[0] == ids[2] and ids[1] == ids[3]
    attempts = {report.ref["episode_attempt_id"] for report in reports}
    assert len(attempts) == 2


# =====================================================================================
# R1-R4  Re-sends inside S4's admission
# =====================================================================================


def _two_failures(health):
    for n in range(2):
        health.report(condition="provider_5xx", ref=ref(n))


def test_r1_a_resend_is_denied_without_sleeping_when_the_route_is_open_past_the_window(
    tmp_path, clock
) -> None:
    config = _r1(transport_max_retry_seconds=10.0)
    rig = make_rig(tmp_path, [refuse(503), ok()], config, seed=_two_failures).run()

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 1
    assert clock.sleeps == []
    log = rig.log
    assert of(log, "retry_backoff_started", "retry_backoff_completed") == []
    (c0,) = exactly(started_ids(log), 1)
    (failed,) = exactly(of(log, "action_attempt_failed"), 1)
    assert failed["payload"]["failure_condition"] == "provider_5xx"
    assert failed["payload"]["transport_exhausted"] is True
    assert failed["payload"]["resend_denied_by"] == "route"
    route = failed["payload"]["route"]
    assert set(route) == ROUTE_KEYS
    assert route["state"] == "cooling"
    assert route["cooldown_until_in"] == 30.0
    assert [e["provider_call_id"] for e in of(log, "provider_call_failed", "provider_call_succeeded")] == [c0]
    (attempt,) = exactly(rig.execution.attempts, 1)
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [(c0, "failed")]
    rig.evidence.audit_reconciliation()


def _denied_by(rig):
    (failed,) = exactly(of(rig.log, "action_attempt_failed"), 1)
    assert failed["payload"]["transport_exhausted"] is True
    return failed["payload"]


def test_r1_control_a_count_denial_on_a_healthy_route_says_count_and_carries_no_snapshot(tmp_path) -> None:
    config = _r1(route_open_after_failures=50, transport_max_calls=2)
    rig = make_rig(tmp_path, [refuse(503), refuse(503), ok()], config).run()

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 2
    payload = _denied_by(rig)
    assert payload["resend_denied_by"] == "count"
    assert "route" not in payload


def test_r1_control_a_cost_denial_on_a_healthy_route_says_cost_and_carries_no_snapshot(tmp_path) -> None:
    from tests.test_transport_resend import choice_error

    config = _r1(route_open_after_failures=50)
    rig = make_rig(
        tmp_path,
        [choice_error(0.00002), refuse(503), ok(), ok()],
        config,
        max_cost_usd=0.00001,
        retryable=("rate_limit", "provider_5xx", PROVIDER_CHOICE_ERROR),
    ).run()

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 2
    (second,) = [
        e for e in of(rig.log, "action_attempt_failed") if e["payload"]["failure_condition"] == "provider_5xx"
    ]
    assert second["payload"]["resend_denied_by"] == "cost"
    assert "route" not in second["payload"]


def test_r1_control_a_time_denial_on_a_healthy_route_says_time_and_carries_no_snapshot(tmp_path) -> None:
    config = _r1(
        route_open_after_failures=50,
        transport_max_retry_seconds=10.0,
        retry_after_max_seconds=30.0,
    )
    rig = make_rig(tmp_path, [_rate_limited(20), ok()], config).run()

    assert_failed_with(rig, "rate_limit")
    assert rig.wire.requests == 1
    payload = _denied_by(rig)
    assert payload["resend_denied_by"] == "time"
    assert "route" not in payload


def _pause_during_call(health, seconds):
    """What another cell does while this cell's call 0 is in flight."""

    return lambda: health.report(
        condition="rate_limit", retry_after_seconds=seconds, ref=ref(50, "rate_limit", "attempt_other")
    )


def test_r2_the_effective_delay_is_the_route_wait_when_it_exceeds_the_backoff(tmp_path, clock) -> None:
    registry = _new_registry()
    config = _r1(route_open_after_failures=50, transport_max_retry_seconds=30.0)
    health = registry.health_for(route_profile(config))
    rig = make_rig(
        tmp_path,
        [refuse(503), ok()],
        config,
        registry=registry,
        wrap=lambda client: Hooked(client, {0: _pause_during_call(health, 10.0)}),
    ).run()

    assert rig.error is None, repr(rig.error)
    (c0, _) = exactly(started_ids(rig.log), 2)
    (started,) = exactly(of(rig.log, "retry_backoff_started"), 1)
    (completed,) = exactly(of(rig.log, "retry_backoff_completed"), 1)
    assert started["payload"]["delay_seconds"] == 10.0
    assert started["payload"]["route_delay_seconds"] == 10.0
    assert started["payload"]["exponential_jitter_seconds"] == pytest.approx(expected_delay(0, c0))
    assert completed["payload"]["delay_seconds"] == 10.0
    assert clock.sleeps == [10.0]
    assert rig.wire.requests == 2


def test_r2_with_no_route_wait_the_effective_delay_is_the_backoff(tmp_path, clock) -> None:
    config = _r1(route_open_after_failures=50, retry_base_seconds=4.0)
    rig = make_rig(tmp_path, [refuse(503), ok()], config).run()

    assert rig.error is None, repr(rig.error)
    (c0, _) = exactly(started_ids(rig.log), 2)
    delay = expected_delay(0, c0, base=4.0)
    (started,) = exactly(of(rig.log, "retry_backoff_started"), 1)
    (completed,) = exactly(of(rig.log, "retry_backoff_completed"), 1)
    assert started["payload"]["delay_seconds"] == pytest.approx(delay)
    assert started["payload"]["route_delay_seconds"] == 0
    assert completed["payload"]["delay_seconds"] == pytest.approx(delay)
    assert clock.sleeps == pytest.approx([delay])


def test_r4_a_sleep_that_overshoots_the_window_is_a_time_denial_not_a_route_denial(tmp_path, clock) -> None:
    """Backoff 2, route wait 10, window end 20, outage end 12; the sleep ends at 21.

    Both S4's window and the route's outage bound have passed; S4's check runs
    first, so the denial is ``time``.
    """

    registry = _new_registry()
    config = _r1(
        route_open_after_failures=50,
        transport_max_retry_seconds=20.0,
        route_max_outage_seconds=12.0,
    )
    health = registry.health_for(route_profile(config))

    async def overshoot(fake, seconds):
        fake.now = START + 21.0

    clock.on_sleep = overshoot
    rig = make_rig(
        tmp_path,
        [refuse(503), ok()],
        config,
        registry=registry,
        wrap=lambda client: Hooked(client, {0: _pause_during_call(health, 10.0)}),
    ).run()

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 1
    payload = _denied_by(rig)
    assert payload["resend_denied_by"] == "time"
    assert "route" not in payload
    assert len(of(rig.log, "retry_backoff_completed")) == 1


def test_r3_a_route_that_reopens_during_the_sleep_denies_the_resend_after_it(tmp_path, clock) -> None:
    registry = _new_registry()
    config = _r1(route_open_after_failures=50, transport_max_retry_seconds=30.0)
    health = registry.health_for(route_profile(config))

    async def reopen(fake, seconds):
        fake.now += seconds
        health.report(
            condition="rate_limit",
            retry_after_seconds=15.0,
            ref=ref(60, "rate_limit", "attempt_other"),
        )

    clock.on_sleep = reopen
    rig = make_rig(
        tmp_path,
        [refuse(503), ok()],
        config,
        registry=registry,
        wrap=lambda client: Hooked(client, {0: _pause_during_call(health, 10.0)}),
    ).run()

    # The original refusal propagates; the port never raises route_unavailable.
    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 1
    assert clock.sleeps == [10.0]
    assert len(of(rig.log, "retry_backoff_started")) == 1
    assert len(of(rig.log, "retry_backoff_completed")) == 1
    payload = _denied_by(rig)
    assert payload["resend_denied_by"] == "route"
    assert payload["route"]["state"] == "paused"
    assert payload["route"]["exhausted"] is None
    assert payload["route"]["pause_until_in"] == 15.0
    assert of(rig.log, "route_wait_started", "route_wait_completed") == []
    assert [e["payload"]["failure_condition"] for e in of(rig.log, "action_attempt_failed")] == ["provider_5xx"]


def test_r3_a_route_that_exhausts_during_the_sleep_denies_the_resend_with_an_exhausted_snapshot(
    tmp_path, clock
) -> None:
    registry = _new_registry()
    config = _r1(
        route_open_after_failures=50,
        transport_max_retry_seconds=30.0,
        route_max_outage_seconds=12.0,
    )
    health = registry.health_for(route_profile(config))

    async def pass_the_bound(fake, seconds):
        fake.now = START + 13.0

    clock.on_sleep = pass_the_bound
    rig = make_rig(
        tmp_path,
        [refuse(503), ok()],
        config,
        registry=registry,
        wrap=lambda client: Hooked(client, {0: _pause_during_call(health, 10.0)}),
    ).run()

    assert_failed_with(rig, "provider_5xx")
    assert rig.wire.requests == 1
    payload = _denied_by(rig)
    assert payload["resend_denied_by"] == "route"
    assert payload["route"]["state"] == "exhausted"
    assert payload["route"]["exhausted"] == "outage_bound_reached"
    assert len(of(rig.log, "action_attempt_failed")) == 1
    assert [e["payload"]["failure_condition"] for e in of(rig.log, "action_attempt_failed")] == ["provider_5xx"]


# =====================================================================================
# T1  Reports from the writer of each provider terminal
# =====================================================================================


def test_t1_the_outer_timeout_on_an_open_call_is_reported_once_and_counted_by_the_breaker(
    tmp_path, reports
) -> None:
    config = _r1(route_open_after_failures=1, transport_max_retry_seconds=0.2)
    rig = make_rig(
        tmp_path,
        [ok()],
        config,
        wrap=lambda client: Hanging(),
        timeout_seconds=0.3,
        max_action_attempts=1,
    ).run()

    assert_failed_with(rig, "timeout")
    log = rig.log
    (c0,) = exactly(started_ids(log), 1)
    (unknown,) = exactly(of(log, "provider_call_outcome_unknown"), 1)
    assert unknown["provider_call_id"] == c0
    assert unknown["payload"]["failure_condition"] == "timeout"
    assert [report.label for report in reports] == ["timeout"]
    assert reports[0].ref["provider_call_id"] == c0
    assert reports[0].ref["condition"] == "timeout"
    health = rig.health
    assert health.cooldown_until is not None  # open_after 1: the timeout opened the breaker
    assert health.cooldown_ref["condition"] == "timeout"
    assert health.cooldown_ref["provider_call_id"] == c0


def test_t1_a_timeout_during_a_port_backoff_reports_nothing_for_the_timeout(
    tmp_path, clock, reports
) -> None:
    config = _r1(
        route_open_after_failures=50,
        transport_max_retry_seconds=1.5,
        retry_base_seconds=0.05,
    )

    async def block(fake, seconds):
        await asyncio.Event().wait()

    clock.on_sleep = block
    rig = make_rig(
        tmp_path,
        [refuse(503), ok()],
        config,
        timeout_seconds=1.5,
        retryable=("rate_limit", "provider_5xx"),
    ).run()

    assert_failed_with(rig, "timeout")
    assert rig.wire.requests == 1
    # Only the refusal the port itself terminalized is reported.
    assert [report.label for report in reports] == ["provider_5xx"]
    (failed,) = exactly(of(rig.log, "action_attempt_failed"), 1)
    assert failed["payload"]["during_transport_backoff"] is True


def test_t1_every_provider_terminal_the_port_writes_is_reported_once(tmp_path, reports) -> None:
    config = _r1(route_open_after_failures=50)
    rig = make_rig(tmp_path, [refuse(503), refuse(503), ok()], config).run()

    assert rig.error is None, repr(rig.error)
    assert [report.label for report in reports] == ["provider_5xx", "provider_5xx", "success"]
    assert [report.ref["provider_call_id"] for report in reports] == started_ids(rig.log)


class Returning:
    """A provider client that returns something that is not a ProviderResult."""

    async def complete(self, request):
        return None


def test_t1_an_invalid_provider_result_is_one_terminal_and_one_report(tmp_path, reports) -> None:
    rig = make_rig(tmp_path, [], wrap=lambda client: Returning()).run()

    assert_failed_with(rig, "provider_contract")
    log = rig.log
    (c0,) = exactly(started_ids(log), 1)
    (terminal,) = exactly(of(log, "provider_call_failed", "provider_call_outcome_unknown"), 1)
    assert terminal["provider_call_id"] == c0
    assert terminal["payload"]["failure_condition"] == "provider_contract"
    (report,) = exactly(reports, 1)
    assert report.label == "provider_contract"
    assert report.ref == {
        "episode_attempt_id": "episode_attempt_fixture_0",
        "provider_call_id": c0,
        "condition": "provider_contract",
    }
    assert rig.health.failures == 0  # ignored by the breaker
    execution = rig.execution
    assert (execution.status, execution.failure_code) == ("failed", "provider_contract")
    (attempt,) = exactly(execution.attempts, 1)
    assert [(call.provider_call_id, call.status) for call in attempt.provider_calls] == [(c0, "failed")]


@pytest.mark.parametrize("scenario", ["invalid_result", "outer_timeout"])
def test_t1_the_executor_reports_only_after_its_attempt_record_is_written(tmp_path, monkeypatch, scenario) -> None:
    route = _route_module()
    real = route.RouteHealth.report
    seen = []
    holder = {}

    def spy(self, **kwargs):
        rig = holder["rig"]
        execution = rig.execution
        seen.append(
            (
                len(execution.attempts),
                execution.status,
                len(of(rig.log, "action_attempt_failed")),
                len(of(rig.log, "provider_call_failed", "provider_call_outcome_unknown")),
            )
        )
        return real(self, **kwargs)

    monkeypatch.setattr(route.RouteHealth, "report", spy)
    if scenario == "invalid_result":
        rig = make_rig(tmp_path, [], wrap=lambda client: Returning())
    else:
        rig = make_rig(
            tmp_path,
            [ok()],
            _r1(transport_max_retry_seconds=0.2),
            wrap=lambda client: Hanging(),
            timeout_seconds=0.3,
            max_action_attempts=1,
        )
    holder["rig"] = rig
    rig.run()

    assert isinstance(rig.error, ProviderFailure), repr(rig.error)
    # The terminal, the failed attempt event and the record all precede the report.
    assert seen == [(1, "failed", 1, 1)]


def test_g1_a_real_gate_wait_longer_than_the_attempt_timeout_does_not_consume_it(
    tmp_path, monkeypatch
) -> None:
    """Real timers: a gate wrapped in the attempt's wait_for would time out here."""

    route = _route_module()

    async def real_sleep(seconds):
        await _REAL_SLEEP(seconds)

    monkeypatch.setattr(route, "_route_monotonic", time.monotonic)
    monkeypatch.setattr(route, "_route_sleep", real_sleep)
    registry = _new_registry()
    config = _r1(
        route_open_after_failures=1,
        route_cooldown_seconds=0.6,
        route_cooldown_cap_seconds=0.6,
        transport_max_retry_seconds=0.2,
    )

    cell_a = run_route_cell(
        tmp_path, monkeypatch, [refuse(503)], registry=registry, name="a", config=config,
        timeout_seconds=0.25,
    )
    assert cell_a.failure is not None and cell_a.failure.condition == "provider_5xx", repr(cell_a.error)
    _release_evidence_lock(cell_a.error)

    cell_b = run_route_cell(
        tmp_path, monkeypatch, [ok()], registry=registry, name="b", config=config,
        timeout_seconds=0.25,
    )

    assert cell_b.error is None, repr(cell_b.error)
    assert cell_b.wire.requests == 1
    (wait_completed,) = exactly(of(cell_b.log, "route_wait_completed"), 1)
    assert wait_completed["payload"]["outcome"] == "admitted"
    assert wait_completed["payload"]["waited_seconds"] > 0.25  # longer than the attempt timeout


@pytest.mark.parametrize("kind", ["v0", "transport_v1"])
@pytest.mark.parametrize("with_registry", [False, True], ids=["without_registry", "with_registry"])
def test_non_route_profiles_never_enter_the_route_helpers(tmp_path, monkeypatch, kind, with_registry) -> None:
    entered = []
    for owner, name in (
        (harness_module.KernelModelPort, "_report"),
        (harness_module.KernelModelPort, "_deny"),
        (MinimalChatExecutor, "_report_route"),
        (MinimalChatExecutor, "_pass_route_gate"),
    ):
        monkeypatch.setattr(owner, name, lambda *a, _n=name, **k: entered.append(_n))

    def build(**kwargs):
        if kind == "v0":
            return route_profile(
                V0_BACKOFF,
                retryable=("rate_limit", "provider_5xx", POST_ADMISSION_REJECTION),
                **kwargs,
            )
        window = 0.04 if "timeout_seconds" in kwargs else 30.0  # the window fits the timeout
        return route_profile(
            {**V1, "transport_max_calls": 2, "transport_max_retry_seconds": window}, **kwargs
        )

    profile = build()
    if kind == "v0":
        scripts = [[refuse(503), ok()], [refuse(503), refuse(503), refuse(503), ok()]]
    else:
        scripts = [[refuse(503), ok()], [refuse(503), refuse(503), ok()]]
    for number, steps in enumerate(scripts):
        rig = RouteRig(
            tmp_path,
            steps,
            profile,
            registry=_new_registry() if with_registry else None,
            name=f"trace_{number}",
        ).run()
        rig.close()
        assert rig.wire.requests >= 2  # both the failing and the answered path ran

    # The executor writes a terminal itself on an outer timeout and on an invalid result.
    for number, wrap in enumerate((lambda client: Hanging(), lambda client: Returning())):
        rig = RouteRig(
            tmp_path,
            [ok()],
            build(timeout_seconds=0.05, max_action_attempts=1),
            registry=_new_registry() if with_registry else None,
            wrap=wrap,
            name=f"executor_terminal_{number}",
        ).run()
        rig.close()
        assert isinstance(rig.error, ProviderFailure), repr(rig.error)
        assert len(of(rig.log, "provider_call_failed", "provider_call_outcome_unknown")) == 1

    assert entered == []


# =====================================================================================
# Controls: receipt classes, spend
# =====================================================================================


def _finalize_failure(run):
    from aeread.shared_runner.task.evaluation import finalize_family_failure
    from tests.test_shared_runner_research import _score

    plan = run.setup.plan
    return finalize_family_failure(
        setup=run.setup,
        cell_id=plan.cells[0].cell_id,
        evidence_root=run.root,
        error=run.error,
        leaf_builder=lambda family_case: _score(plan).leaf,
    )


def test_receipt_a_cell_whose_only_failure_is_the_gate_is_an_environment_failure(tmp_path, monkeypatch) -> None:
    registry = _new_registry()
    run = run_route_cell(
        tmp_path,
        monkeypatch,
        [ok()],
        registry=registry,
        seed=_exhaust_by_long_retry_after,
        config=_r1(route_max_outage_seconds=100.0),
    )

    assert run.failure is not None and run.failure.condition == "route_unavailable", repr(run.error)
    assert run.wire.requests == 0
    _release_evidence_lock(run.error)
    receipt = _finalize_failure(run)
    assert receipt.failure.failure_class == "environment_failure"
    assert receipt.failure.condition == "route_unavailable"


def test_receipt_a_cell_with_an_earlier_retryable_failure_is_retryable_infrastructure(
    tmp_path, monkeypatch
) -> None:
    registry = _new_registry()
    run = run_route_cell(
        tmp_path,
        monkeypatch,
        [ok()],
        registry=registry,
        config=_r1(route_max_outage_seconds=100.0),
        wrap=lambda client: Injecting(client, {0: _slow_down(500.0)}),
    )

    assert run.failure is not None and run.failure.condition == "route_unavailable", repr(run.error)
    _release_evidence_lock(run.error)
    receipt = _finalize_failure(run)
    assert receipt.failure.failure_class == "retryable_infrastructure"
    assert receipt.failure.condition == "route_unavailable"


def test_spend_of_a_recovered_cell_is_the_same_with_and_without_route_v1(tmp_path, monkeypatch) -> None:
    from aeread.shared_runner.task.spend import attempt_spend

    plain = run_route_cell(
        tmp_path, monkeypatch, [refuse(503), ok()], name="plain", config=dict(V1)
    )
    routed = run_route_cell(
        tmp_path,
        monkeypatch,
        [refuse(503), ok()],
        name="routed",
        registry=_new_registry(),
        config=_r1(),
    )

    assert plain.error is None and routed.error is None, (plain.error, routed.error)
    spends = [attempt_spend(run.execution.evidence) for run in (plain, routed)]
    for spend in spends:
        assert spend.provider_call_count == 2
        assert spend.cost_usd == pytest.approx(OK_COST)
        assert spend.cost_accounting == "exact"
    assert plain.execution.total_cost_usd == routed.execution.total_cost_usd


# =====================================================================================
# Goldens: profiles without route_v1 are byte-identical to S4
# =====================================================================================

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "route_health"
S4_GOLDEN_DIR = Path(__file__).parent / "fixtures" / "transport_resend"
REGENERATE = "AEREAD_REGENERATE_ROUTE_GOLDENS"


def _v0_profile():
    return s4_make_profile(
        V0_BACKOFF,
        max_action_attempts=3,
        retryable=("rate_limit", "provider_5xx", POST_ADMISSION_REJECTION),
    )


def _v1_profile():
    return s4_make_profile()


def _pre_request_profile(kind):
    """A profile whose request cannot be built: the mapping lacks the action schema."""

    base = dict(V0_BACKOFF) if kind == "v0" else dict(V1)
    base["output_schema_by_action_schema"] = {"some_other_action_v1": OUTPUT_SCHEMA}
    return route_profile(
        base,
        remove=("output_schema",),
        max_action_attempts=3,
        retryable=("rate_limit", "provider_5xx", POST_ADMISSION_REJECTION),
    )


V1_GOLDEN_SCRIPTS = {
    "recovered_refusal": lambda: [_scripted_503(), _scripted_ok],
    "exhaustion": lambda: [_scripted_503(), _scripted_503(), _scripted_503()],
    "cancel_during_provider_call": lambda: [_scripted_503(), asyncio.CancelledError()],
    "cancel_during_port_backoff": lambda: [_scripted_503()],
}


def _run_golden(
    tmp_path, clock, profile, outcomes, *, registry=None, cancel_backoff=False, stamp="2026-10-05T00:00:00Z"
):
    if cancel_backoff:
        clock.on_sleep = _cancel_hook
    root = tmp_path / "golden"
    evidence = EvidenceStore(
        root,
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        clock=lambda: stamp,
    )
    kwargs = {} if registry is None else {"route_health": registry}
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=(profile,),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": Scripted(outcomes)},
        pricing={MODEL: PRICING},
        harnesses=default_harnesses(),
        **kwargs,
    )
    decision = _decision()
    error = None
    try:
        run_async(executor(decision))
    except BaseException as caught:  # noqa: BLE001
        error = caught
    execution = {
        "error": None if error is None else [type(error).__name__, str(error)],
        "total_cost_usd": executor.total_cost_usd,
        "execution": executor.execution_for(decision.logical_action_id),
    }
    events = (root / "events.jsonl").read_bytes()
    evidence.close()
    return events, _canon(execution)


WITH = pytest.mark.parametrize("with_registry", [False, True], ids=["without_registry", "with_registry"])


def _registry_for(with_registry):
    return _new_registry() if with_registry else None


def _compare_or_regenerate(events, execution, stem, directory, *, regenerate_allowed, with_registry):
    events_path = directory / f"{stem}.events.jsonl"
    execution_path = directory / f"{stem}.execution.json"
    if regenerate_allowed and os.environ.get(REGENERATE) == "1":
        if with_registry:
            pytest.skip("regeneration run: the registry variant only compares")
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        events_path.write_bytes(events)
        execution_path.write_bytes(execution)
        pytest.skip("goldens regenerated; run again without the flag to compare")
    assert events_path.is_file() and execution_path.is_file(), f"golden files are missing: {stem}"
    assert events == events_path.read_bytes()
    assert execution == execution_path.read_bytes()


@WITH
@pytest.mark.parametrize("name", sorted(S4_GOLDEN_SCRIPTS))
def test_s4_v0_goldens_are_byte_identical_with_and_without_a_registry(tmp_path, clock, name, with_registry) -> None:
    events, execution = _run_golden(
        tmp_path,
        clock,
        _v0_profile(),
        S4_GOLDEN_SCRIPTS[name](),
        registry=_registry_for(with_registry),
        stamp="2026-10-04T00:00:00Z",  # the stamp S4 generated its files under
    )
    _compare_or_regenerate(
        events, execution, f"v0_{name}", S4_GOLDEN_DIR, regenerate_allowed=False, with_registry=with_registry
    )


@WITH
@pytest.mark.parametrize("name", sorted(V1_GOLDEN_SCRIPTS))
def test_transport_v1_goldens_are_byte_identical_with_and_without_a_registry(
    tmp_path, clock, name, with_registry
) -> None:
    events, execution = _run_golden(
        tmp_path,
        clock,
        _v1_profile(),
        V1_GOLDEN_SCRIPTS[name](),
        registry=_registry_for(with_registry),
        cancel_backoff=name == "cancel_during_port_backoff",
    )
    _compare_or_regenerate(
        events,
        execution,
        f"transport_v1_{name}",
        GOLDEN_DIR,
        regenerate_allowed=True,
        with_registry=with_registry,
    )


@WITH
@pytest.mark.parametrize("kind", ["v0", "transport_v1"])
def test_a_pre_request_failure_is_byte_identical_with_and_without_a_registry(
    tmp_path, clock, kind, with_registry
) -> None:
    """A missing action-schema mapping fails after ``action_attempt_started``,
    before any request exists, outside every handler: no provider event, no
    attempt record, whatever the profile or registry."""

    events, execution = _run_golden(
        tmp_path,
        clock,
        _pre_request_profile("v0" if kind == "v0" else "v1"),
        [],
        registry=_registry_for(with_registry),
    )
    assert b"provider_call_started" not in events
    assert b"route_wait" not in events
    _compare_or_regenerate(
        events,
        execution,
        f"pre_request_failure_{kind}",
        GOLDEN_DIR,
        regenerate_allowed=True,
        with_registry=with_registry,
    )


def test_a_pre_request_failure_under_route_v1_on_a_healthy_route_adds_no_gate_events(tmp_path, clock) -> None:
    profile = route_profile(
        {**_r1(), "output_schema_by_action_schema": {"some_other_action_v1": OUTPUT_SCHEMA}},
        remove=("output_schema",),
    )
    registry = _new_registry()
    events, execution = _run_golden(tmp_path, clock, profile, [], registry=registry)

    kinds_written = [json.loads(line)["event_type"] for line in events.decode().splitlines()]
    assert kinds_written == ["logical_action_started", "action_attempt_started"]
    assert json.loads(execution)["error"][0] == "EvidenceIntegrityError"
