"""Bounded one-decision GLM diagnostic; not full procurement episodes.

Prepare freezes all requests and controls without credentials or paid calls.
Execute refuses to overwrite an existing run; replay grades saved final answers.
Raw provider records stay under ignored runs/, including any provider reasoning.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
import getpass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

from check_procurement_information_design import (
    FIXTURES, ROOT, action_values, allocation_choices, evaluate, number,
)

MODEL = "z-ai/glm-5.3-flash"
PROVIDER = "Parasail"
ENDPOINTS = f"https://openrouter.ai/api/v1/models/{MODEL}/endpoints"
API = "https://openrouter.ai/api/v1/chat/completions"
PRICE_INPUT = Decimal("0.00000015")
PRICE_OUTPUT = Decimal("0.0000005")
SOURCE_PATHS = [
    "tools/run_procurement_information_pilot.py",
    "tools/check_procurement_information_design.py",
    "tests/test_procurement_information_pilot.py",
    "tests/fixtures/procurement_information_design_v1.json",
    "src/aeread_families/procurement_allocation/phase2_runner.py",
]
COMMON = """You are a procurement buyer choosing exactly one next action.
Maximize expected incremental contribution in USD from the current decision point.
The supplied probabilities, conditional payoffs and observation likelihoods are public
calibrated information. The realized condition is unknown. Array positions refer to the
same possible condition throughout a case. Do not treat a possible payoff as known truth.
Research costs are paid on every outcome, including later deferral. Research consumes
stated days and one research action. After research, update beliefs using its observation
likelihoods and then choose a legal final action. Keep the final action; it does not count
against research_actions_left. max_uses limits each research action. No unlisted actions.
Terminal payoffs already include purchase, freight and service costs but exclude research.
A terminal choice with requires is unavailable until those research actions are completed.
last_award_day is the last legal day relative to now (day 0), inclusive. Research can expire
an offer. Existing quote/sample qualification is stated explicitly in the observation.
Defer has zero incremental payoff. Sunk research remains spent regardless of your action.
No certified market-wide bounds exist unless explicitly provided in the observation.
For allocation_market cases, construct your own quantities. All suppliers are qualified,
usable and on time. A used supplier requires quantity = moq + k*order_step, k a nonnegative
integer, and quantity <= capacity. Unused suppliers have quantity 0. Pay shipping once per
used supplier. Total purchase plus shipping must fit cash_budget_usd. Completed kits equal
min(target_kits, floor(component inventory / BOM requirement) for every component).
An award must meet minimum_service_kits. Revenue is completed kits * revenue_per_kit_usd.
Unused excess parts have no salvage. There are no other penalties or costs in this probe.
Return JSON with exactly action, quantities, explanation. For non-allocation cases action
is a listed research/terminal ID or defer, with quantities {}. For allocation cases action
is award or defer; award quantities maps supplier IDs to positive integer quantities.
Give a concise decision justification in explanation, not a long reasoning transcript.
"""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def save_new(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def strategy_text():
    tree = ast.parse((ROOT / SOURCE_PATHS[-1]).read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "TREATMENT_PROMPT" for t in node.targets
        ):
            return ast.literal_eval(node.value.right)
    raise ValueError("Original strategy paragraph not found")


def public_observation(case):
    # Explicit allowlist: fixture IDs, mechanism labels and answer keys never enter requests.
    result = {"context": case["decision_point"].split(" These are decision-point probes")[0],
              "research_actions_left": case["research_actions_left"],
              "sunk_research_cost_usd": case.get("sunk_research_cost_usd", "0")}
    if "allocation_market" in case:
        result["allocation_market"] = case["allocation_market"]
    else:
        result.update(public_current_belief=case["prior"],
                      terminal_choices=case["terminal_choices"],
                      research_actions=case["research_actions"])
        if "belief_provenance" in case:
            result["belief_provenance"] = case["belief_provenance"]
    return result


def request_for(case):
    vendors = case.get("allocation_market", {}).get("vendors", [])
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["action", "quantities", "explanation"],
        "properties": {
            "action": {"type": "string"},
            "quantities": {"type": "object", "additionalProperties": False,
                           "properties": {v["id"]: {"type": "integer", "minimum": 0}
                                          for v in vendors}},
            "explanation": {"type": "string"},
        },
    }
    return dict(
        model=MODEL, temperature=0, seed=73001, max_tokens=4096,
        reasoning={"effort": "low", "exclude": True},
        provider={"only": [PROVIDER], "order": [PROVIDER], "allow_fallbacks": False,
                  "require_parameters": True,
                  "max_price": {"prompt": "0.15", "completion": "0.50"}},
        response_format={"type": "json_schema", "json_schema": {
            "name": "procurement_decision", "strict": True, "schema": schema}},
        messages=[{"role": "system", "content": COMMON + strategy_text()},
                  {"role": "user", "content": encoded(public_observation(case)).decode()}],
    )


def reserve(request):
    # Conservative input bound: UTF-8 bytes plus 1024 tokens for framing, no cache discount.
    return (len(encoded(request)) + 1024) * PRICE_INPUT + request["max_tokens"] * PRICE_OUTPUT


def load_cases():
    cases = json.loads(FIXTURES.read_text())["cases"]
    evaluate(cases)  # All offline reversal and answer-key checks must pass before freezing.
    return cases


def source_hashes():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCE_PATHS}


def prepare(directory):
    cases = load_cases()
    with urllib.request.urlopen(ENDPOINTS, timeout=30) as response:
        endpoints = json.load(response)
    matches = [e for e in endpoints["data"]["endpoints"] if e["provider_name"] == PROVIDER]
    assert matches, "Requested provider unavailable; substitution forbidden"
    endpoint = matches[0]
    assert Decimal(endpoint["pricing"]["prompt"]) <= PRICE_INPUT
    assert Decimal(endpoint["pricing"]["completion"]) <= PRICE_OUTPUT
    requests = [{"row_id": f"decision_{i+1:02d}", "case_id": c["id"],
                 "request": request_for(c)} for i, c in enumerate(cases)]
    total = sum(reserve(r["request"]) for r in requests)
    assert total <= Decimal("0.05")
    plan = dict(
        campaign_id="procurement_information_decision_glm_v1", created_at=datetime.now(timezone.utc).isoformat(),
        scope="12 one-decision authoring probes, one attempt each; six matched families; descriptive only",
        model=MODEL, provider=PROVIDER, immutable_model_revision=None,
        max_requests=12, retries=0, timeout_seconds=180, max_wall_seconds=2400,
        hard_ceiling_usd="0.05", conservative_total_reserve_usd=str(total),
        missing_cost_policy="retain full request reserve when usage cost is absent",
        early_stop_policy="stop on provider failure, route mismatch, budget or wall limit; no model-outcome stopping",
        score="V*(public belief) - Q*(chosen action), optimal subsequent continuation assumed",
        invalid_policy="malformed/illegal reported separately; economic decision loss null, never dropped",
        continuation_policy="no live continuation; no realized profit or full-episode claim",
        public_belief_policy="posterior supplied, including walkaway; belief updating from raw history is not tested",
        inference_seed=73001, strategy_sha256=digest(strategy_text()),
        sources=source_hashes(), endpoint_snapshot=endpoint, rows=requests,
    )
    plan["plan_sha256"] = digest(plan)
    directory.mkdir(parents=True, exist_ok=False)
    save_new(directory / "plan.json", plan)
    print(json.dumps({"plan_sha256": plan["plan_sha256"], "rows": len(requests),
                      "maximum_reserved_usd": str(total), "paid_calls": 0}))


def grade(case, content):
    try:
        answer = json.loads(content)
    except (ValueError, TypeError):
        return dict(status="malformed", decision_loss_usd=None)
    if (not isinstance(answer, dict) or set(answer) != {"action", "quantities", "explanation"}
        or not isinstance(answer["action"], str) or not isinstance(answer["quantities"], dict)
        or not isinstance(answer["explanation"], str) or not answer["explanation"].strip()):
        return dict(status="malformed", decision_loss_usd=None)
    evaluated = dict(case)
    selected = answer["action"]
    if "allocation_market" in case:
        evaluated["terminal_choices"] = allocation_choices(case["allocation_market"])
        quantities = answer["quantities"]
        if selected == "award" and quantities and all(type(q) is int and q > 0 for q in quantities.values()):
            matches = [c for c in evaluated["terminal_choices"] if c["quantities"] == quantities]
            selected = matches[0]["id"] if matches else "illegal_allocation"
        elif selected != "defer" or quantities:
            selected = "illegal_allocation"
    elif answer["quantities"]:
        selected = "unexpected_quantities"
    values = action_values(evaluated)
    if selected not in values:
        return dict(status="illegal_action", selected_action=selected, answer=answer, decision_loss_usd=None)
    best = max(values.values())
    return dict(status="valid", selected_action=selected, answer=answer,
                best_actions=[a for a, v in values.items() if v == best],
                optimal=values[selected] == best, best_value_usd=float(best),
                chosen_action_value_usd=float(values[selected]),
                decision_loss_usd=float(best - values[selected]),
                decision_loss_exact=str(best - values[selected]))


def read_plan(directory):
    plan = json.loads((directory / "plan.json").read_text())
    sealed = plan.pop("plan_sha256")
    assert digest(plan) == sealed, "Plan changed"
    plan["plan_sha256"] = sealed
    assert source_hashes() == plan["sources"], "Frozen sources changed; do not reuse campaign identity"
    return plan


def replay(directory):
    plan = read_plan(directory)
    cases = {c["id"]: c for c in load_cases()}
    rows = []
    actual_cost, unknown_reserve = Decimal(0), Decimal(0)
    for item in plan["rows"]:
        path = directory / f"{item['row_id']}.receipt.json"
        row = {"row_id": item["row_id"], "case_id": item["case_id"], "status": "unattempted",
               "decision_loss_usd": None}
        if not path.exists() and (directory / f"{item['row_id']}.request.json").exists():
            row["status"] = "interrupted_unknown"
            unknown_reserve += reserve(item["request"])
        if path.exists():
            assert json.loads((directory / f"{item['row_id']}.request.json").read_text()) == item["request"]
            receipt = json.loads(path.read_text())
            assert receipt["request_sha256"] == digest(item["request"])
            assert receipt["plan_sha256"] == plan["plan_sha256"]
            if "raw_sha256" in receipt:
                raw = (directory / f"{item['row_id']}.raw.json").read_bytes()
                assert hashlib.sha256(raw).hexdigest() == receipt["raw_sha256"]
                data = json.loads(raw)
                assert receipt["reported_cost_usd"] == data.get("usage", {}).get("cost")
                if receipt["status"] == "completed":
                    assert data.get("model") == MODEL and data.get("provider") == PROVIDER
                    assert receipt["final_content"] == data["choices"][0]["message"].get("content")
            row.update(status=receipt["status"], latency_seconds=receipt["latency_seconds"])
            cost = receipt.get("reported_cost_usd")
            if cost is None:
                unknown_reserve += reserve(item["request"])
            else:
                actual_cost += Decimal(str(cost))
            if receipt["status"] == "completed":
                row.update(grade(cases[item["case_id"]], receipt["final_content"]))
            row["receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(row)
    valid = [r for r in rows if r["status"] == "valid"]
    pairs = [{"family": cases[rows[i]["case_id"]]["mechanism"],
              "both_optimal": all(r.get("optimal", False) for r in rows[i:i+2]),
              "row_ids": [r["row_id"] for r in rows[i:i+2]]} for i in range(0, len(rows), 2)]
    return dict(plan_sha256=plan["plan_sha256"], scope=plan["scope"], model=plan["model"],
                provider=plan["provider"], planned=12, status_counts=dict(Counter(r["status"] for r in rows)),
                optimal_decisions=sum(r.get("optimal", False) for r in rows),
                matched_pairs_both_optimal=sum(p["both_optimal"] for p in pairs), pairs=pairs,
                valid_decision_loss_sum_usd=sum(r["decision_loss_usd"] for r in valid),
                valid_decision_loss_mean_usd=(sum(r["decision_loss_usd"] for r in valid) / len(valid) if valid else None),
                reported_cost_usd=str(actual_cost), unknown_charge_reserve_usd=str(unknown_reserve),
                accounted_cost_usd=str(actual_cost + unknown_reserve), rows=rows)


def execute(directory):
    plan = read_plan(directory)
    # A fresh route read is free; reject unexpected pricing before any generation.
    with urllib.request.urlopen(ENDPOINTS, timeout=30) as response:
        endpoint_data = json.load(response)
    assert any(e["provider_name"] == PROVIDER
               and Decimal(e["pricing"]["prompt"]) <= PRICE_INPUT
               and Decimal(e["pricing"]["completion"]) <= PRICE_OUTPUT
               for e in endpoint_data["data"]["endpoints"])
    if (directory / "execution_started.json").exists():
        raise RuntimeError("Existing attempt cannot be restarted or selectively retried")
    key = os.environ.get("OPENROUTER_API_KEY") or getpass.getpass("OpenRouter key (hidden): ")
    save_new(directory / "execution_started.json", dict(plan_sha256=plan["plan_sha256"],
             git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
             started_at=datetime.now(timezone.utc).isoformat(), endpoint_snapshot=endpoint_data))
    started = time.monotonic()
    accounted = Decimal(0)
    for item in plan["rows"]:
        request = item["request"]
        reserved = reserve(request)
        if accounted + reserved > Decimal(plan["hard_ceiling_usd"]):
            break
        if time.monotonic() - started + plan["timeout_seconds"] > plan["max_wall_seconds"]:
            break
        prefix = directory / item["row_id"]
        save_new(prefix.with_suffix(".request.json"), request)
        receipt = dict(plan_sha256=plan["plan_sha256"], request_sha256=digest(request),
                       status="provider_failure", reported_cost_usd=None)
        call_started = time.monotonic()
        try:
            http = urllib.request.Request(API, data=encoded(request), method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            with urllib.request.urlopen(http, timeout=plan["timeout_seconds"]) as response:
                raw = response.read()
            prefix.with_suffix(".raw.json").write_bytes(raw)
            data = json.loads(raw)
            receipt["raw_sha256"] = hashlib.sha256(raw).hexdigest()
            receipt.update(generation_id=data.get("id"), observed_model=data.get("model"),
                           observed_provider=data.get("provider"), usage=data.get("usage"),
                           reported_cost_usd=data.get("usage", {}).get("cost"))
            if data.get("model") != MODEL or data.get("provider") != PROVIDER:
                receipt["status"] = "route_mismatch"
            elif not data.get("choices"):
                receipt["status"] = "provider_failure"
            else:
                receipt.update(status="completed", final_content=data["choices"][0]["message"].get("content"),
                               finish_reason=data["choices"][0].get("finish_reason"))
        except urllib.error.HTTPError as exc:
            prefix.with_suffix(".error.txt").write_bytes(exc.read())
            receipt.update(error_type="HTTPError", http_status=exc.code)
        except Exception as exc:
            receipt["error_type"] = type(exc).__name__  # no credential-bearing exception text
        receipt["latency_seconds"] = round(time.monotonic() - call_started, 3)
        save_new(prefix.with_suffix(".receipt.json"), receipt)
        cost = receipt["reported_cost_usd"]
        accounted += reserved if cost is None else Decimal(str(cost))
        print(json.dumps({"row_id": item["row_id"], "status": receipt["status"],
                          "seconds": receipt["latency_seconds"], "accounted_usd": str(accounted)}), flush=True)
        if receipt["status"] != "completed":
            break
    key = None
    result = replay(directory)
    save_new(directory / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "pairs"}}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "execute", "replay"])
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.run_dir)
    elif args.mode == "execute":
        execute(args.run_dir)
    else:
        print(json.dumps(replay(args.run_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
