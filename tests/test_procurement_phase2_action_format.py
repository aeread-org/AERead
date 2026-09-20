"""Regression examples from the preserved failed pilot, never repaired live."""

import copy
import hashlib
import json
from pathlib import Path

from jsonschema import validate

from aeread_families.procurement_allocation.phase2_admission import action_schema
from aeread_families.procurement_allocation.phase2_environment import Phase2Plugin
from aeread_families.procurement_allocation.phase2_campaign import (
    prior_campaign_accounting,
    BASELINE_SETTLED_USD,
    BASELINE_RESERVED_USD,
)
from aeread_families.procurement_allocation.phase2_runner import PROMPTS
from aeread_families.procurement_allocation.phase2_worlds import build_world
from aeread_families.procurement_allocation.runner import (
    procurement_action_output_schema,
)

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "evidence/procurement_allocation/procurement_allocation_phase2_pilot_v1"


def test_all_eleven_observed_failures_remain_failures_and_localize_missing_field():
    diagnosis = json.loads((PILOT / "qc/action_format_diagnosis.json").read_text())
    traces = {
        t["row_id"]: t["canonical_actions"]
        for t in diagnosis["canonical_action_traces"]
    }
    assert len(diagnosis["failures"]) == 11
    for failure in diagnosis["failures"]:
        index = int(failure["row_id"].split("_")[1]) - 1
        case = build_world(index)["payload"]
        plugin = Phase2Plugin()
        state, phase = plugin.initial_state(case, None), plugin.phases(case)[0]
        original = traces[failure["row_id"]][failure["action_ordinal"] - 1]
        validate(original, action_schema())
        assert (
            plugin.parse_action(case, state, "buyer", phase, original).error_code
            == "malformed_procurement_action"
        )
        # Diagnostic counterfactual only: not an executed or rescored episode.
        probe = copy.deepcopy(original)
        field = failure["null_required_field"]
        assert probe[field] is None
        probe[field] = {
            "message": "Please provide the requested evidence.",
            "proposal": {
                "unit_price_usd": 1.0,
                "moq": None,
                "payment_terms_days": None,
                "refund_window_days": None,
                "return_freight_payer": None,
            },
            "fields": ["lead_time"],
        }[field]
        validate(probe, action_schema())
        assert plugin.parse_action(case, state, "buyer", phase, probe).ok
        assert original[field] is None


def test_recovery_schema_changes_documentation_only_and_common_prompt_is_shared():
    baseline = procurement_action_output_schema()
    baseline["properties"]["action"]["enum"].remove("check_award")
    current = action_schema()
    assert "request_quote" in current["properties"]["message"]["description"]
    assert "counter_offer" in current["properties"]["proposal"]["description"]
    assert "inquire" in current["properties"]["fields"]["description"]
    for value in current["properties"].values():
        value.pop("description", None)
    assert current == baseline
    for prompt in PROMPTS.values():
        common = prompt.split("Action format contract:", 1)[1].split(
            "Before returning the JSON", 1
        )[0]
        assert all(
            action in common for action in baseline["properties"]["action"]["enum"]
        )
    control = PROMPTS["control"].split("Before returning the JSON", 1)[0]
    treatment = PROMPTS["treatment"].split("Before returning the JSON", 1)[0]
    assert control == treatment


def test_economics_worlds_and_verifier_bytes_are_unchanged_from_failed_pilot():
    manifest = json.loads((PILOT / "publication_manifest.json").read_text())
    pins = manifest["source_bindings"]["implementation_pins"]
    for name in (
        "environment.py",
        "phase2_environment.py",
        "phase2_worlds.py",
        "phase2_policies.py",
        "runner.py",
    ):
        path = "src/aeread_families/procurement_allocation/" + name
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == pins[path]
    prior = prior_campaign_accounting()
    assert prior["settled_cost_usd"] == BASELINE_SETTLED_USD > 0
    assert prior["unresolved_reserved_cost_usd"] == BASELINE_RESERVED_USD > 0
