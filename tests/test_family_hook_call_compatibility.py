"""Every family plugin must accept the kernel's own ``initial_state`` call form.

The kernel calls this hook from two places with two different call forms:
``scheduler.py`` passes the second argument positionally, while
``evaluation.py``'s replay path used to pass it as ``run=``. Nine of the
eleven external adapters name that parameter ``cell``, so the keyword call
raised ``TypeError`` for every one of them -- meaning no external adapter
could produce a replayed receipt, while the natively-built families (which
happen to name it ``run``) passed. Only tau3.retail exercised
``replay_family_receipt`` in tests, and tau3 is one of the families that
named it ``run``, so the gap stayed invisible.

This test pins the contract at the signature level so a future family
cannot reintroduce it by choosing either name.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import aeread_families


def _plugin_classes() -> list[tuple[str, type]]:
    found: list[tuple[str, type]] = []
    for module_info in pkgutil.iter_modules(aeread_families.__path__):
        name = module_info.name
        try:
            module = importlib.import_module(f"aeread_families.{name}.environment")
        except Exception:  # families without an environment module
            continue
        for attribute in vars(module).values():
            if (
                inspect.isclass(attribute)
                and attribute.__module__ == module.__name__
                and hasattr(attribute, "initial_state")
                and hasattr(attribute, "phases")
            ):
                found.append((name, attribute))
    return found


PLUGINS = _plugin_classes()


def test_families_were_discovered() -> None:
    assert len(PLUGINS) >= 10, [name for name, _ in PLUGINS]


@pytest.mark.parametrize("family,plugin", PLUGINS, ids=[name for name, _ in PLUGINS])
def test_initial_state_accepts_a_positional_second_argument(
    family: str, plugin: type
) -> None:
    """scheduler.py and evaluation.py both call this hook positionally."""
    signature = inspect.signature(plugin.initial_state)
    parameters = [
        parameter
        for name, parameter in signature.parameters.items()
        if name != "self"
    ]
    assert len(parameters) == 2, f"{family}: expected (family_case, cell/run)"
    for parameter in parameters:
        assert parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), f"{family}: {parameter.name} must be passable positionally"


def _scorer_builders() -> list[tuple[str, type]]:
    return [(name, plugin) for name, plugin in PLUGINS if hasattr(plugin, "build_scorer")]


SCORERS = _scorer_builders()

# Families whose scorer still takes a recorded-outcome Mapping rather than the
# FamilyScoringInput the kernel passes. This is a ratchet, not an amnesty: the
# test is green today so CI stays honest, and it fails the moment a NEW family
# joins the list. Remove an entry when its issue lands; do not add one without
# an issue.
KNOWN_UNMIGRATED_SCORERS = {
    "govsim": "#76",
    # Found by this test, filed from it:
    "aucarena": "#119",
    "consent_ir": "#120",
}


@pytest.mark.parametrize(
    "family,plugin", SCORERS, ids=[name for name, _ in SCORERS]
)
def test_scorer_signature_matches_the_kernel_call(family: str, plugin: type) -> None:
    """`build_scorer(...)` must return something the kernel can actually call.

    `evaluation.py` calls it as `scorer(scoring_input, evidence_refs=...)`
    with a FamilyScoringInput dataclass. Four adapters were found taking a
    recorded-outcome Mapping instead (#74 econevals, #75 termsbench,
    #76 govsim, #80 amazonbarg), which fails on the first subscript and
    keeps every non-primary leaf out of the receipt. This asserts the shape
    at the signature level so the fifth is caught before a live run pays for
    it.

    A family with no `__call__` at all is reported as such rather than
    skipped: uncallable is the same defect, discovered later.
    """
    import typing

    from aeread.shared_runner.task.evaluation import FamilyScoringInput

    scorer_type = typing.get_type_hints(plugin.build_scorer).get("return")
    if scorer_type is None or not inspect.isclass(scorer_type):
        pytest.skip(f"{family}: build_scorer has no resolvable return annotation")
    call = getattr(scorer_type, "__call__", None)
    assert call is not None and call is not object.__call__, (
        f"{family}: {scorer_type.__name__} is not callable, so the kernel's "
        "finalizer cannot score it"
    )
    hints = typing.get_type_hints(call)
    parameters = [
        name for name in inspect.signature(call).parameters if name != "self"
    ]
    assert parameters, f"{family}: scorer __call__ takes no scoring input"
    first = hints.get(parameters[0])
    migrated = (
        first in (FamilyScoringInput, typing.Any, None) or first is object
    )
    if family in KNOWN_UNMIGRATED_SCORERS:
        assert not migrated, (
            f"{family} now matches the kernel contract -- remove it from "
            "KNOWN_UNMIGRATED_SCORERS "
            f"({KNOWN_UNMIGRATED_SCORERS[family]})"
        )
        pytest.xfail(
            f"{family}: scorer takes {first!r}, tracked as "
            f"{KNOWN_UNMIGRATED_SCORERS[family]}"
        )
    assert migrated, (
        f"{family}: scorer __call__ takes {first!r} as its first argument; the "
        "kernel passes a FamilyScoringInput"
    )


# --- Coverage against the trusted registry, not against whatever imports ---
#
# The discovery above walks `aeread_families.*.environment` and skips any
# package that fails to import. That is two blind spots (review finding 6 on
# #125): an import error is silently a pass, and a plugin registered from
# anywhere but `<family>.environment` is never seen. This half enumerates the
# registry's own trusted catalog instead. Every key either resolves -- and the
# real registered plugin is checked -- or is named below with the reason it
# cannot resolve in a plain environment. Both directions ratchet: an unlisted
# unresolvable key fails, and a listed key that starts resolving fails until
# it is removed from the list.

import importlib as _importlib

from aeread.shared_runner.registry import PluginRegistry, TRUSTED_BUILTIN_PLUGIN_KEYS

KNOWN_UNRESOLVABLE_IN_PLAIN_ENV: dict[tuple[str, str], str] = {
    # register_plugin(registry) constructs the adapter, which needs a pinned
    # upstream checkout; the bridge-gated suites cover these when it exists.
    ("econagent_v1", "0.1.0"): "register_plugin needs upstream_root",
    ("govsim", "0.1.0"): "register_plugin needs upstream_root",
    ("negarena", "0.1.0"): "register_plugin needs upstream_root",
    ("tau3.retail", "0.1.0"): "register_plugin needs upstream_root",
    ("alympics.wac", "0.1.0"): "register_plugin needs upstream_root",
    ("amazonbarg.bilateral", "0.1.0"): "register_plugin needs upstream_root",
    ("agenticpay.bilateral", "0.1.0"): "register_plugin needs upstream_root",
    ("steer", "0.1.0"): "register_plugin needs steer_data_root",
    # Registered by campaign or test code rather than a package-level hook.
    ("housing_v1", "1.0.0"): "registered by aeread_families.housing campaign modules",
    ("single_offer_v1", "1.0.0"): "no environment module; registered by its own campaign code",
    ("datacenter_development_v1", "1.1.0"): "versioned plugin registered by datacenter campaign code",
    ("datacenter_development_v1", "2.0.0"): "versioned plugin registered by datacenter campaign code",
    ("kernel_contract_reference_v1", "1.0.0"): "kernel-owned fixture family, registered by its test",
    ("kernel_contract_sequential_v1", "1.0.0"): "kernel-owned fixture family, registered by its test",
}


def _trusted_registry() -> tuple[PluginRegistry, dict[str, str]]:
    """Register every family package that can register itself.

    Returns the registry and, per package that could not, the reason -- an
    import error is reported, never swallowed.
    """
    registry = PluginRegistry()
    failures: dict[str, str] = {}
    for module_info in pkgutil.iter_modules(aeread_families.__path__):
        name = module_info.name
        try:
            module = _importlib.import_module(f"aeread_families.{name}")
            hook = getattr(module, "register_plugin", None)
            if hook is None:
                environment = _importlib.import_module(f"aeread_families.{name}.environment")
                hook = getattr(environment, "register_plugin", None)
            if hook is None:
                failures[name] = "no register_plugin hook"
                continue
            hook(registry)
        except Exception as error:  # reported below, not skipped
            failures[name] = f"{type(error).__name__}: {error}"
    return registry, failures


def test_every_trusted_key_is_checked_or_named_as_uncovered() -> None:
    registry, _failures = _trusted_registry()
    unlisted_unresolvable: list[str] = []
    listed_but_resolvable: list[str] = []
    checked = 0
    for family_id, version, plugin_id in sorted(TRUSTED_BUILTIN_PLUGIN_KEYS):
        try:
            plugin = registry.resolve(family_id, version, plugin_id)
        except Exception:
            if (family_id, version) not in KNOWN_UNRESOLVABLE_IN_PLAIN_ENV:
                unlisted_unresolvable.append(f"{family_id} {version}")
            continue
        if (family_id, version) in KNOWN_UNRESOLVABLE_IN_PLAIN_ENV:
            listed_but_resolvable.append(f"{family_id} {version}")
        # The same contract the discovery half checks, on the real registered
        # object rather than on whatever class the module happened to expose.
        parameters = [
            p for n, p in inspect.signature(plugin.initial_state).parameters.items() if n != "self"
        ]
        assert len(parameters) == 2, f"{family_id} {version}: initial_state must take (family_case, cell/run)"
        assert all(
            p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            for p in parameters
        ), f"{family_id} {version}: initial_state's second parameter must be passable positionally"
        checked += 1
    assert not unlisted_unresolvable, (
        "trusted key(s) could not be resolved and are not named in "
        "KNOWN_UNRESOLVABLE_IN_PLAIN_ENV -- an unlisted gap is a silent skip: "
        + ", ".join(unlisted_unresolvable)
    )
    assert not listed_but_resolvable, (
        "these keys now resolve; remove them from KNOWN_UNRESOLVABLE_IN_PLAIN_ENV "
        "so they are actually checked: " + ", ".join(listed_but_resolvable)
    )
    assert checked >= 5, f"only {checked} trusted plugins were actually checked"
