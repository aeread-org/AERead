"""The OpenRouter driver for the pay-or-test pack: pins, the action schema, sealed limits, the stop rules, and a provider-free cell.

The driver lives in ``tools/cli_subjects``; nothing here makes a provider call.
"""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import itertools
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "tools" / "cli_subjects"))

import pay_or_test_openrouter as driver  # noqa: E402
import pay_or_test_report as report  # noqa: E402
from aeread.shared_runner.run.resolver import canonical_json_bytes  # noqa: E402
from aeread.shared_runner.task.execution import MinimalChatExecutor  # noqa: E402
from aeread_families.procurement_allocation import model_campaign as mc  # noqa: E402
from aeread_families.procurement_allocation import pay_or_test_case_matrix as pack_module  # noqa: E402
from aeread_families.procurement_allocation.environment import ACTION_FIELDS  # noqa: E402
from aeread_families.procurement_allocation.runner import SequenceResponseProvider, procurement_action_output_schema  # noqa: E402

#: Housing v14 confirmatory, read from codex/housing-lemons-outside-demand:
#: (model, revision, provider, quantization, input, cached, output, pricing id, effort, temperature, top_p).
HOUSING_V14 = {
    "gemini38_flash": ("google/gemini-3.8-flash", "google/gemini-3.8-flash-20260902", "Google AI Studio", "unknown",
                       0.75, 0.075, 3.75, "openrouter_google-ai-studio_2026-09-21_gemini-3.8-flash", "minimal", 0.0, 1.0),
    "glm53_flash_nextbit": ("z-ai/glm-5.3-flash", "z-ai/glm-5.3-flash-20260826", "NextBit", "fp8",
                            0.165, 0.033, 0.55, "openrouter_nextbit_2026-10-01_glm-5.3-flash-fp8", "low", 0.0, 1.0),
    "gpt6_luna": ("openai/gpt-6-luna", "openai/gpt-6-luna-20260922", "OpenAI", "unknown",
                  0.1, 0.01, 0.5, "openrouter_openai_2026-10-06_gpt-6-luna", "low", "unavailable", None),
}


def _profile(subject: str):
    setup = driver.build_setup(subject, driver.case_paths("gate")[0])
    (profile,) = setup.plan.agent_profiles
    return setup, profile


def _pin(subject: str) -> tuple:
    spec = driver.SUBJECTS[subject]
    route = spec["route"]
    return (route.model, route.revision, route.route_provider, route.quantization,
            route.pricing.input_per_million, route.pricing.cached_input_per_million, route.pricing.output_per_million,
            route.pricing.pricing_id, route.reasoning_effort, spec["temperature"], spec["top_p"])


def test_the_subjects_are_the_housing_v14_panel_with_glm_moved_to_morph() -> None:
    assert sorted(driver.SUBJECTS) == ["gemini38_flash", "glm53_flash_morph", "gpt6_luna"]


@pytest.mark.parametrize("subject", ["gemini38_flash", "gpt6_luna"])
def test_each_route_is_the_housing_v14_pin(subject: str) -> None:
    route = driver.SUBJECTS[subject]["route"]
    assert _pin(subject) == HOUSING_V14[subject]
    assert float(route.max_prompt_price_per_million) == route.pricing.input_per_million
    assert float(route.max_completion_price_per_million) == route.pricing.output_per_million
    assert driver.model_plan(subject, "panel")["comparability"]["route_parity_with_housing_v14"] is True


def test_glm_runs_on_the_family_morph_route_with_housing_v14_settings_and_says_it_breaks_parity() -> None:
    route = driver.SUBJECTS["glm53_flash_morph"]["route"]
    morph = mc.GLM_MORPH_CANDIDATE.route
    # The family's earlier GLM route, value for value, but for this driver's profile id.
    assert dataclasses.replace(route, profile_id=morph.profile_id) == morph
    assert (route.route_provider, route.quantization, route.pricing.pricing_id) == (
        "Morph", "fp8", "openrouter_2026-09-02_glm53_flash_morph")
    housing = HOUSING_V14["glm53_flash_nextbit"]
    pin = _pin("glm53_flash_morph")
    # Same model, revision and quantization as Housing v14; its reasoning effort, temperature and top_p.
    assert (pin[0], pin[1], pin[3]) == (housing[0], housing[1], housing[3])
    assert pin[8:] == housing[8:]
    comparability = driver.model_plan("glm53_flash_morph", "panel")["comparability"]
    assert comparability["route_parity_with_housing_v14"] is False
    assert "provider" not in comparability["same_as_housing_v14"] and "pricing" not in comparability["same_as_housing_v14"]
    was = comparability["differs_from_housing_v14"]["route"]["housing_v14"]
    assert (was["provider"], was["quantization"], was["input_per_million_usd"], was["cached_input_per_million_usd"],
            was["output_per_million_usd"], was["pricing_id"]) == (housing[2], housing[3], *housing[4:8])
    assert "P-O-05" in comparability["differs_from_housing_v14"]["route"]["why"]


def test_the_gate_plays_the_first_test_cheapest_world_in_pack_order() -> None:
    manifest = json.loads((pack_module.PACK_ROOT / "pack.json").read_text())
    first = next(w["slug"] for w in manifest["worlds"] if w["move"] == "test_cheapest")
    assert [p.stem for p in driver.case_paths("gate")] == [first] == [driver.GATE_WORLD]
    assert len(driver.case_paths("panel")) == 24


@pytest.mark.parametrize("subject", sorted(driver.SUBJECTS))
def test_the_profile_seals_every_limit_the_plan_declares(subject: str) -> None:
    _, profile = _profile(subject)
    plan = driver.model_plan(subject, "panel")
    config = profile.harness.config
    gate = driver.case_paths("gate")[0]
    assert json.loads(canonical_json_bytes(config["output_schema"])) == driver.action_output_schema(driver._payload(gate))
    assert plan["action_schema"]["sha256_by_case"][json.loads(gate.read_text())["case_id"]] == driver._schema_sha256(gate)
    assert len(plan["action_schema"]["sha256_by_case"]) == 24 and plan["action_schema"]["residual"] == list(driver.SCHEMA_RESIDUAL)
    assert profile.model.provider == "openrouter" and profile.model.revision == plan["revision"]
    assert dict(config["provider_metadata"]) == driver.provider_metadata(driver.SUBJECTS[subject]["route"])
    assert profile.sampling.max_output_tokens == plan["controls"]["max_output_tokens"] == 4096
    assert config["max_output_tokens_ceiling"] == plan["retry_policy"]["length_retry_growth"]["max_output_tokens_ceiling"]
    assert profile.sampling.seed == plan["inference_seeds"][0]
    assert profile.budgets.timeout_seconds == plan["controls"]["timeout_seconds"] == 300.0
    assert profile.budgets.max_cost_usd == plan["controls"]["max_cost_usd_per_trajectory"]
    assert profile.budgets.max_logical_actions == 10
    assert profile.retry_policy.max_action_attempts == plan["retry_policy"]["max_action_attempts"] == 8
    assert list(profile.retry_policy.retryable_conditions) == plan["retry_policy"]["retryable_conditions"]
    assert {"rate_limit", "provider_5xx", "transport"} <= set(profile.retry_policy.retryable_conditions)
    assert profile.retry_policy.sdk_retries == 0
    backoff = plan["retry_policy"]["retry_backoff"]
    assert (config["retry_backoff"], config["retry_base_seconds"], config["retry_after_max_seconds"]) == (
        backoff["policy"], backoff["retry_base_seconds"], backoff["retry_after_max_seconds"])
    assert profile.reasoning.effort == plan["route"]["reasoning_effort"]
    if plan["route"]["temperature"] == "unavailable":
        assert dict(config["sampling_controls"]) == {"temperature": "unavailable"} and profile.sampling.top_p is None
    else:
        assert "sampling_controls" not in config
        assert (profile.sampling.temperature, profile.sampling.top_p) == (plan["route"]["temperature"], plan["route"]["top_p"])
    assert plan["controls"]["total_cost_ceiling_usd"] == 3.0
    assert plan["controls"]["max_consecutive_operational_failures"] == 3


def test_the_kernel_doubles_a_truncated_answer_up_to_the_declared_ceiling() -> None:
    _, profile = _profile("gemini38_flash")
    executor = SimpleNamespace(_length_retry_ceiling=MinimalChatExecutor._length_retry_ceiling)
    budget, steps = profile.sampling.max_output_tokens, []
    while (grown := MinimalChatExecutor._grow_length_budget(executor, profile, budget)) != budget:
        steps.append(grown // budget)
        budget = grown
    assert set(steps) == {2} and budget == driver.RETRY_POLICY["length_retry_growth"]["max_output_tokens_ceiling"]


def test_identities_and_run_roots_are_what_the_report_reads() -> None:
    for subject in driver.SUBJECTS:
        gate, panel = driver.default_run_root(subject, "gate"), driver.default_run_root(subject, "panel")
        assert gate.parent == panel.parent == driver.RUNS_ROOT
        assert gate.name.startswith(report.ARMS["finalquotes"]) and panel.name.startswith(report.ARMS["finalquotes"])
        assert "_gate_" in gate.name and "_gate_" not in panel.name
        assert driver.campaign_id(subject, "gate") != driver.campaign_id(subject, "panel")


@pytest.mark.parametrize("subject", sorted(driver.SUBJECTS))
def test_version_two_identities_never_reuse_a_version_one_root(subject: str) -> None:
    gate, panel = driver.campaign_id(subject, "gate"), driver.campaign_id(subject, "panel")
    assert gate.endswith("_gate_v2") and panel.endswith("_v2") and not panel.endswith("_gate_v2")
    plan = driver.model_plan(subject, "gate")
    supersedes = plan["identity_history"]["supersedes"]
    assert supersedes.startswith("procurement_allocation_pay_or_test_v1_finalquotes_openrouter_") and "_gate_v1" in supersedes
    assert supersedes.split(" ")[0] != gate and "P-D-23" in plan["identity_history"]["changed_from_v1"]["action_schema"]
    assert driver.SUBJECTS[subject]["route"].profile_id.endswith("_v2")


def _credit(remaining: float):
    return lambda: {"total_credits_usd": 100.0, "total_usage_usd": 100.0 - remaining, "remaining_usd": remaining}


def test_nothing_runs_and_no_run_root_exists_under_the_credit_floor(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "procurement_allocation" / "gate"
    with pytest.raises(RuntimeError, match="under the 10.00 floor"):
        asyncio.run(driver.run("gemini38_flash", "gate", root, resume=False, credit_fn=_credit(9.99),
                               preflight_fn=lambda subject: {}, provider_factory=lambda: pytest.fail("called")))
    assert not root.exists()


def test_a_route_missing_from_the_catalog_consumes_no_identity(tmp_path: Path) -> None:
    root = tmp_path / "runs" / "procurement_allocation" / "gate"

    def gone(subject: str):
        raise RuntimeError(f"found no endpoint within the route pin for {subject}")

    with pytest.raises(RuntimeError, match="found no endpoint"):
        asyncio.run(driver.run("glm53_flash_morph", "gate", root, resume=False, credit_fn=_credit(20.0),
                               preflight_fn=gone, provider_factory=lambda: pytest.fail("called")))
    assert not root.exists()


@pytest.mark.parametrize("subject", sorted(driver.SUBJECTS))
def test_a_provider_free_gate_is_sealed_replayed_and_scored_by_the_report(tmp_path: Path, subject: str) -> None:
    runs = tmp_path / "runs" / "procurement_allocation"
    root = runs / driver.default_run_root(subject, "gate").name
    provider = SequenceResponseProvider((json.dumps({"action": "defer", "reason": "provider-free gate"}),))
    artifact = asyncio.run(driver.run(subject, "gate", root, resume=False, provider_factory=lambda: provider,
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {"candidate_id": s}))
    (row,) = artifact["rows"]
    assert artifact["halted"] is None and row["status"] == "completed" and row["receipt_replayed"] is True
    assert artifact["preflight"]["credit_remaining_usd_at_start"] == 20.0
    (request,) = provider.requests
    assert request.seed == 87001 and request.max_output_tokens == 4096 and request.timeout_seconds == 300.0
    assert request.provider_metadata["route_provider"] == driver.SUBJECTS[subject]["route"].route_provider
    assert request.temperature == (None if subject == "gpt6_luna" else 0.0)
    assert request.top_p == (None if subject == "gpt6_luna" else 1.0)
    assert driver.verify(subject, "gate", root)["verified"] is True
    manifest, payloads = report.load_pack()
    scored = report.score_run(root, manifest, payloads)
    (world,) = scored["worlds"]
    assert world["slug"] == driver.GATE_WORLD and world["decision"] == "defer"
    # Walking away in a world where a test beats paying gives up value.
    assert world["decision_loss_usd"] > 0 and world["paid_without_testing"] is True
    # A second invocation without --resume refuses the root; with it, nothing is rerun.
    with pytest.raises(FileExistsError):
        asyncio.run(driver.run(subject, "gate", root, resume=False, provider_factory=lambda: provider,
                               credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    again = asyncio.run(driver.run(subject, "gate", root, resume=True, provider_factory=lambda: pytest.fail("rerun"),
                                   credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    assert again["rows"] == artifact["rows"]


def test_three_failed_cells_in_a_row_stop_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Refused:
        async def complete(self, request):
            from aeread.shared_runner.task.execution import ProviderFailure
            raise ProviderFailure("provider_rejected", "refused", retryable=False)

    monkeypatch.setitem(driver.CONTROLS, "max_parallel_cells", 1)
    root = tmp_path / "runs" / "procurement_allocation" / "panel"
    artifact = asyncio.run(driver.run("gpt6_luna", "panel", root, resume=False, provider_factory=Refused,
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    assert artifact["halted"] == "consecutive operational failures"
    assert [row["status"] for row in artifact["rows"]] == ["operational_failure"] * 3


def test_a_wave_that_could_pass_the_total_ceiling_is_not_launched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(driver.CONTROLS, "total_cost_ceiling_usd", {"gate": 0.29, "panel": 3.0})
    root = tmp_path / "runs" / "procurement_allocation" / "gate"
    artifact = asyncio.run(driver.run("gpt6_luna", "gate", root, resume=False, provider_factory=lambda: pytest.fail("called"),
                                      credit_fn=_credit(20.0), preflight_fn=lambda s: {}))
    assert artifact["rows"] == [] and artifact["halted"].startswith("total cost ceiling")


def test_the_probe_sends_the_strict_request_the_cells_send() -> None:
    class Capture:
        request = None

        async def complete(self, request):
            Capture.request = request
            raise driver.ProviderFailure("provider_rejected", "captured", retryable=False, status_code=404)

    outcome = asyncio.run(driver.probe("gpt6_luna", client=Capture()))
    assert outcome == {**outcome, "answered": False, "condition": "provider_rejected", "status_code": 404}
    request = Capture.request
    assert request.seed == 87001 and request.temperature is None and request.top_p is None
    assert request.reasoning_effort == "low" and request.output_schema["additionalProperties"] is False
    assert json.loads(canonical_json_bytes(request.output_schema)) == driver.action_output_schema(driver._payload(driver.case_paths("gate")[0]))
    assert dict(request.provider_metadata) == driver.provider_metadata(driver.SUBJECTS["gpt6_luna"]["route"])


def test_the_key_loader_reads_only_the_openrouter_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OTHER_SECRET", raising=False)
    env = tmp_path / ".env"
    env.write_text("OTHER_SECRET=x\nexport OPENROUTER_API_KEY='sk-test'\n")
    driver.load_api_key(env)
    import os
    assert os.environ["OPENROUTER_API_KEY"] == "sk-test" and "OTHER_SECRET" not in os.environ


# --- the action schema agrees with the family parser ----------------------------------------------------

#: Every keyword the v2 schema uses; ``_admits`` implements exactly these, so it decides what the schema admits.
KEYWORDS = {"type", "enum", "pattern", "minimum", "minItems", "items", "properties", "required", "additionalProperties"}


def _keywords(schema) -> set[str]:
    found = set(schema) if isinstance(schema, dict) else set()
    for key, value in (schema.items() if isinstance(schema, dict) else ()):
        if key == "properties":
            for child in value.values():
                found |= _keywords(child)
        elif key == "items":
            found |= _keywords(value)
    return found


def _is(value, kind: str) -> bool:
    plain_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    return {"string": isinstance(value, str), "null": value is None, "array": isinstance(value, list),
            "object": isinstance(value, dict), "boolean": isinstance(value, bool), "number": plain_number,
            "integer": plain_number and float(value).is_integer() and not isinstance(value, float)}[kind]


def _admits(schema: dict, value) -> bool:
    kinds = schema.get("type")
    if kinds is not None and not any(_is(value, k) for k in ([kinds] if isinstance(kinds, str) else kinds)):
        return False
    if "enum" in schema and not any(value == item and type(value) is type(item) for item in schema["enum"]):
        return False
    if isinstance(value, str) and "pattern" in schema and re.search(schema["pattern"], value) is None:
        return False
    if _is(value, "number") and "minimum" in schema and value < schema["minimum"]:
        return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or ("items" in schema and not all(_admits(schema["items"], v) for v in value)):
            return False
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        if set(schema.get("required", ())) - set(value):
            return False
        if not all(_admits(properties[k], v) for k, v in value.items() if k in properties):
            return False
    return True


def _parser_accepts(case_path: Path, reply: dict) -> bool:
    return driver.parse_reply(case_path, json.dumps(reply))["ok"]


def _replies(payload: dict) -> dict[str, dict]:
    """One reply per action that both the v2 schema and the parser accept."""
    supplier = payload["suppliers"][-1]["supplier_id"]
    base = {"supplier_id": supplier, "message": "Please send your terms.", "fields": None, "offer_id": None,
            "proposal": None, "award_lines": None, "reason": "Because."}
    offer = f"offer_{supplier}_v1"
    terms = {"unit_price_usd": 1.0, "moq": None, "payment_terms_days": None, "refund_window_days": None,
             "return_freight_payer": None}
    return {
        "inquire": {**base, "action": "inquire", "fields": ["lead_time"]},
        "request_quote": {**base, "action": "request_quote"},
        "request_sample": {**base, "action": "request_sample"},
        "counter_offer": {**base, "action": "counter_offer", "offer_id": offer, "proposal": terms},
        "submit_award": {**base, "action": "submit_award", "award_lines": [{"offer_id": offer, "quantity": 5}]},
        "check_award": {**base, "action": "check_award", "award_lines": [{"offer_id": offer, "quantity": 5}]},
        "defer": {**base, "action": "defer"},
    }


_NULL_TERMS = {"unit_price_usd": None, "moq": None, "payment_terms_days": None, "refund_window_days": None,
               "return_freight_payer": None}
#: (field, label, value): every way a field's value can go wrong that the parser checks.
MUTATIONS = [
    *[(f, label, v) for f in ("supplier_id", "message", "reason")
      for label, v in (("null", None), ("empty", ""), ("blank", "   "), ("number", 3))],
    ("supplier_id", "unknown", "driver_board_l000"),
    *[("fields", label, v) for label, v in (("null", None), ("empty", []), ("duplicate", ["lead_time", "lead_time"]),
                                            ("unknown", ["price"]), ("text", "lead_time"))],
    *[("offer_id", label, v) for label, v in (("null", None), ("empty", ""), ("blank", "  "))],
    *[("proposal", label, v) for label, v in (
        ("null", None), ("all_null", dict(_NULL_TERMS)), ("negative_price", {**_NULL_TERMS, "unit_price_usd": -1.0}),
        ("zero_moq", {**_NULL_TERMS, "moq": 0}), ("fractional_moq", {**_NULL_TERMS, "moq": 2.5}),
        ("bad_payer", {**_NULL_TERMS, "return_freight_payer": "carrier"}), ("missing_term", {"unit_price_usd": 1.0}))],
    *[("award_lines", label, v) for label, v in (
        ("null", None), ("empty", []), ("blank_offer", [{"offer_id": " ", "quantity": 5}]),
        ("zero_quantity", [{"offer_id": "o", "quantity": 0}]), ("fractional_quantity", [{"offer_id": "o", "quantity": 1.5}]),
        ("extra_key", [{"offer_id": "o", "quantity": 5, "note": "x"}]))],
]
#: The mutations the schema admits and the parser rejects, by the residual entry that names each.
RESIDUAL = {
    ("inquire", "fields", "null"): "inquire with fields null",
    ("inquire", "fields", "duplicate"): "inquire naming an inquiry field twice (uniqueItems is outside the strict subset)",
    ("counter_offer", "offer_id", "null"): "counter_offer with offer_id null or proposal null",
    ("counter_offer", "proposal", "null"): "counter_offer with offer_id null or proposal null",
    ("counter_offer", "proposal", "all_null"): "counter_offer whose proposal has every term null",
    ("submit_award", "award_lines", "null"): "submit_award or check_award with award_lines null",
    ("check_award", "award_lines", "null"): "submit_award or check_award with award_lines null",
}
#: The parser accepts these and the schema does not: strict structured output writes every key, null when unused,
#: so a proposal that leaves a term out is not a reply a strict route can return.
STRICT_FORM = {("counter_offer", "proposal", "missing_term")}


def test_the_schema_uses_only_keywords_the_strict_subset_and_this_test_know() -> None:
    for path in driver.case_paths("panel"):
        assert _keywords(driver.action_output_schema(driver._payload(path))) <= KEYWORDS


def test_the_luna_reply_passed_the_v1_schema_failed_the_parser_and_fails_the_v2_schema() -> None:
    gate = driver.case_paths("gate")[0]
    payload = driver._payload(gate)
    reply = {**_replies(payload)["request_quote"], "message": None, "reason": None}
    assert _admits(procurement_action_output_schema(), reply)
    assert driver.parse_reply(gate, json.dumps(reply)) == {"ok": False, "failure_code": "malformed_procurement_action"}
    assert not _admits(driver.action_output_schema(payload), reply)


@pytest.mark.parametrize("path", driver.case_paths("panel"), ids=lambda p: p.stem)
def test_on_every_field_an_action_reads_the_schema_and_the_parser_agree_but_for_the_residual(path: Path) -> None:
    payload = driver._payload(path)
    schema = driver.action_output_schema(payload)
    hit = set()
    for action, reply in _replies(payload).items():
        assert _admits(schema, reply) and _parser_accepts(path, reply), action
        for field, label, value in MUTATIONS:
            mutated = {**copy.deepcopy(reply), field: copy.deepcopy(value)}
            admitted, accepted = _admits(schema, mutated), _parser_accepts(path, mutated)
            if field not in ACTION_FIELDS[action]:
                # The parser drops a field the action does not take; the schema may still hold it to its shape.
                assert accepted, (action, field, label)
            elif (action, field, label) in RESIDUAL:
                assert admitted and not accepted, (action, field, label)
                hit.add(RESIDUAL[(action, field, label)])
            elif (action, field, label) in STRICT_FORM:
                assert accepted and not admitted, (action, field, label)
            else:
                assert admitted == accepted, (action, field, label, admitted, accepted)
    assert hit == set(driver.SCHEMA_RESIDUAL)


def test_the_small_validator_agrees_with_jsonschema_where_it_is_installed() -> None:
    jsonschema = pytest.importorskip("jsonschema")
    gate = driver.case_paths("gate")[0]
    payload = driver._payload(gate)
    schema = driver.action_output_schema(payload)
    validator = jsonschema.Draft202012Validator(schema)
    for reply, (field, _, value) in itertools.product(_replies(payload).values(), MUTATIONS):
        mutated = {**copy.deepcopy(reply), field: copy.deepcopy(value)}
        assert _admits(schema, mutated) == validator.is_valid(mutated), (reply["action"], field, value)
