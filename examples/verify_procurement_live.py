"""Read-only receipt, billing, privacy, and independent world-cluster report checks.

No provider clients are constructed. The optional output is a separate audit report;
the frozen experiment evidence is never rewritten.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from scipy import stats


def recompute_panel(rows, *, worlds, conditions, replicates, bootstrap_draws,
                    bootstrap_seed, score_support_by_world=None):
    expected = {(condition, world, repeat) for condition in conditions
                for world in worlds for repeat in range(replicates)}
    indexed = {(row["condition_id"], row["world_seed"], row["replicate_index"]): row for row in rows}
    if len(indexed) != len(rows) or not set(indexed).issubset(expected):
        raise ValueError("episode identity is duplicate or outside the declared panel")
    complete, differences, bounds = [], [], []
    for world in sorted(worlds):
        means, ranges = {}, {}
        for condition in conditions:
            scores = []
            for repeat in range(replicates):
                row = indexed.get((condition, world, repeat))
                if row is not None and row["status"] == "completed":
                    score = row["within_case_score"]
                    if isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score) or score > 1:
                        raise ValueError("included score must be finite and at most one")
                    scores.append(score)
            if len(scores) == replicates:
                means[condition] = sum(scores) / replicates
                ranges[condition] = (means[condition], means[condition])
            elif score_support_by_world is not None and world in score_support_by_world:
                lower, upper = score_support_by_world[world]
                missing = replicates - len(scores)
                ranges[condition] = ((sum(scores) + missing * lower) / replicates,
                                     (sum(scores) + missing * upper) / replicates)
        control, treatment = conditions
        if len(means) == 2:
            complete.append(means)
            differences.append(means[treatment] - means[control])
        if len(ranges) == 2:
            bounds.append((ranges[treatment][0] - ranges[control][1],
                           ranges[treatment][1] - ranges[control][0]))
    interval = t_interval = None
    if len(differences) >= 2 and set(indexed) == expected:
        values = np.asarray(differences)
        draws = np.random.default_rng(bootstrap_seed).choice(
            values, size=(bootstrap_draws, len(values)), replace=True).mean(axis=1)
        interval = np.percentile(draws, [2.5, 97.5]).tolist()
        radius = stats.t.ppf(.975, len(values) - 1) * stats.sem(values)
        t_interval = [float(values.mean() - radius), float(values.mean() + radius)]
    return {
        "planned_world_count": len(worlds), "planned_episode_count": len(expected),
        "unattempted_count": len(expected - set(indexed)), "complete_world_count": len(complete),
        "condition_means": {condition: sum(row[condition] for row in complete) / len(complete)
                            for condition in conditions} if complete else None,
        "mean_paired_difference": sum(differences) / len(differences) if differences else None,
        "cluster_bootstrap_95": interval, "paired_t_95": t_interval,
        "missingness_difference_bounds": [sum(pair[i] for pair in bounds) / len(bounds) for i in (0, 1)]
            if len(bounds) == len(worlds) else None,
        "resampling_unit": "world_seed",
    }


def _evidence_fingerprint(root):
    paths = []
    for phase in ("admission", "sample"):
        paths.extend((root / phase).glob("*/results/*.json"))
        paths.extend((root / phase).glob("*/evidence/*/*/*/evaluation_receipt.json"))
        paths.extend((root / phase).glob("*/evidence/*/*/*/events.jsonl"))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest(), len(paths)


def audit_prior_spend(authorization):
    entries = authorization.get("prior_runs")
    if entries is None:
        entries = [{"evidence_root": authorization["prior_evidence_root"],
                    "summary_path": "admission/summary.json",
                    "summary_sha256": authorization["prior_summary_sha256"],
                    "recorded_cost_usd": authorization["prior_recorded_cost_usd"]}]
    total = Decimal("0")
    for entry in entries:
        raw = (Path(entry["evidence_root"]) / entry["summary_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["summary_sha256"]:
            raise ValueError("prior summary hash changed")
        cost = Decimal(str(json.loads(raw)["total_known_cost_usd_including_admission"]))
        if cost != Decimal(str(entry["recorded_cost_usd"])):
            raise ValueError("prior recorded cost differs from its summary")
        total += cost
    for entry in authorization.get("lost_prior_runs", []):
        if entry.get("evidence_status") != "unrecoverable_after_temporary_storage_cleanup":
            raise ValueError("lost prior evidence status is not recognized")
        known = Decimal(str(entry["known_recorded_cost_usd"]))
        unknown_calls = entry["unknown_call_count"]
        per_call_reserve = Decimal(str(entry["per_call_reserve_usd"]))
        reserved = Decimal(str(entry["reserved_cost_usd"]))
        if (not known.is_finite() or known < 0
                or isinstance(unknown_calls, bool) or not isinstance(unknown_calls, int) or unknown_calls < 0
                or not per_call_reserve.is_finite() or per_call_reserve <= 0
                or reserved != known + unknown_calls * per_call_reserve):
            raise ValueError("lost prior evidence reserve is not conservative")
        total += reserved
    if (total != Decimal(str(authorization["prior_recorded_cost_usd"]))
            or total + Decimal(str(authorization["remaining_run_limit_usd"]))
            != Decimal(str(authorization["approved_total_usd"]))):
        raise ValueError("authorization does not carry forward all prior spend")
    return total


def audit_unknown_billing_recovery(phase_root, rows):
    """Independently validate a sealed unknown-billing prefix and its full reserve."""
    from aeread.shared_runner.resolver import canonical_json_bytes

    phase_root = Path(phase_root)
    checkpoint_path = phase_root / "recovery_checkpoint.json"
    unknown_rows = [row for row in rows if row["unknown_cost_provider_call_count"]]
    if not checkpoint_path.exists():
        if unknown_rows:
            raise ValueError("unknown billing lacks a sealed recovery checkpoint")
        return {"acknowledged_unknown_cost_provider_call_count": 0,
                "reserved_unknown_cost_usd": Decimal("0"),
                "acknowledged_result_sha256s": []}
    checkpoint = json.loads(checkpoint_path.read_bytes())
    sealed = {key: value for key, value in checkpoint.items() if key != "result_sha256"}
    if checkpoint.get("result_sha256") != hashlib.sha256(canonical_json_bytes(sealed)).hexdigest():
        raise ValueError("unknown-billing recovery checkpoint seal changed")
    if checkpoint.get("spec_version") != "aeread.unknown_billing_recovery/1":
        if unknown_rows:
            raise ValueError("unknown billing is not covered by its recovery type")
        return {"acknowledged_unknown_cost_provider_call_count": 0,
                "reserved_unknown_cost_usd": Decimal("0"),
                "acknowledged_result_sha256s": []}
    hashes = checkpoint.get("prefix_result_sha256s")
    if (not isinstance(hashes, list) or not hashes
            or [row["result_sha256"] for row in rows[:len(hashes)]] != hashes):
        raise ValueError("unknown-billing recovery prefix differs from the receipts")
    acknowledged = set(hashes)
    if any(row["result_sha256"] not in acknowledged for row in unknown_rows):
        raise ValueError("unknown billing appears outside the acknowledged prefix")
    if any(row["status"] == "completed"
           or (row.get("failure") or {}).get("condition") != "timeout"
           for row in unknown_rows):
        raise ValueError("only excluded timeout rows may carry acknowledged unknown billing")
    count = sum(row["unknown_cost_provider_call_count"] for row in unknown_rows)
    if checkpoint.get("acknowledged_unknown_cost_provider_call_count") != count:
        raise ValueError("unknown-billing checkpoint count differs from the receipts")
    each = Decimal(str(checkpoint["unknown_call_reserve_usd_each"]))
    reserved = Decimal(str(checkpoint["reserved_unknown_cost_usd"]))
    bounds = [Decimal(str(value)) for value in checkpoint["request_cost_upper_bounds_usd"]]
    before = Decimal(str(checkpoint["account_usage_before_usd"]))
    after = Decimal(str(checkpoint["account_usage_after_usd"]))
    account_known = Decimal(str(checkpoint["account_known_cost_usd"]))
    unexplained = Decimal(str(checkpoint["account_unexplained_delta_usd"]))
    if (any(not value.is_finite() or value < 0
            for value in [each, reserved, before, after, account_known, unexplained, *bounds])
            or each <= 0 or len(bounds) != count or any(bound > each for bound in bounds)
            or reserved != count * each
            or abs(unexplained - (after - before - account_known)) > Decimal("1e-12")
            or unexplained > reserved):
        raise ValueError("unknown-billing reserve or account usage delta is invalid")
    predecessor_sha = checkpoint.get("predecessor_checkpoint_sha256")
    if predecessor_sha is not None:
        predecessor_path = Path(checkpoint["source_root"]) / "recovery_checkpoint.json"
        predecessor = json.loads(predecessor_path.read_bytes())
        predecessor_sealed = {key: value for key, value in predecessor.items()
                              if key != "result_sha256"}
        previous_count = predecessor.get("acknowledged_unknown_cost_provider_call_count")
        previous_hashes = predecessor.get("prefix_result_sha256s")
        previous_bounds = [Decimal(str(value))
                           for value in predecessor.get("request_cost_upper_bounds_usd", [])]
        previous_each = Decimal(str(predecessor.get("unknown_call_reserve_usd_each")))
        previous_reserved = Decimal(str(predecessor.get("reserved_unknown_cost_usd")))
        if (predecessor.get("result_sha256") != predecessor_sha
                or predecessor_sha != hashlib.sha256(canonical_json_bytes(predecessor_sealed)).hexdigest()
                or predecessor.get("spec_version") != "aeread.unknown_billing_recovery/1"
                or not isinstance(previous_count, int) or previous_count >= count
                or hashes[:len(previous_hashes)] != previous_hashes
                or previous_each != each
                or bounds[:previous_count] != previous_bounds
                or previous_reserved != previous_count * each):
            raise ValueError("unknown-billing recovery does not preserve its cumulative predecessor")
    return {"acknowledged_unknown_cost_provider_call_count": count,
            "reserved_unknown_cost_usd": reserved,
            "acknowledged_result_sha256s": hashes}


def audit_live_run(root):
    from aeread.shared_runner.batch import read_family_batch
    from aeread.shared_runner.execution import _paired_cell_request_seed
    from aeread.shared_runner.procurement_experiment import DEEPSEEK_MODEL, DEEPSEEK_ROUTE, validate_live_admission
    from aeread.shared_runner.procurement_measurement import procurement_score_support
    from aeread.shared_runner.procurement_rfq import ProcurementRFQPlugin, build_procurement_rfq_smoke

    root = Path(root)
    study = json.loads((root / "live_study.json").read_bytes())
    if study.get("evidence_kind") != "native_live_provider" or study.get("provider") != "deepseek":
        raise ValueError("audit requires native_live_provider DeepSeek evidence")
    authorization = json.loads((root / "authorization.json").read_bytes())
    before = _evidence_fingerprint(root)
    summaries = {phase: json.loads((root / phase / "summary.json").read_bytes())
                 for phase in ("admission", "sample")}
    conditions = [condition for condition, _ in study["ordered_conditions"]]
    assert len(study["panel_seeds"]) == 100 and study["replicates"] == 3 and len(conditions) == 2
    assert not set(study["panel_seeds"]) & set(study["admission_seeds"])
    phase_rows, setup_maps, reconciliations = {}, {}, {}
    for phase in summaries:
        setups = {condition: build_procurement_rfq_smoke(
            buyer_provider="openrouter", buyer_model=DEEPSEEK_MODEL,
            buyer_revision=DEEPSEEK_ROUTE.canonical_model, openrouter_route=DEEPSEEK_ROUTE,
            world_seeds=study["admission_seeds"] if phase == "admission" else study["panel_seeds"],
            replicates=1 if phase == "admission" else study["replicates"],
            reasoning_effort=effort, condition_id=condition,
            inference_seed_base=study["inference_seed_base"], **study["buyer_runtime_limits"])
            for condition, effort in study["ordered_conditions"]}
        rows = read_family_batch(setups=setups, output_root=root / phase)
        assert {r["result_sha256"] for r in rows} == {
            r["result_sha256"] for r in summaries[phase]["batch"]["rows"]}
        assert len(rows) == summaries[phase]["batch"]["attempted_cell_count"]
        reconciliation = audit_unknown_billing_recovery(root / phase, rows)
        assert summaries[phase]["batch"].get(
            "acknowledged_unknown_cost_provider_call_count", 0) == reconciliation[
                "acknowledged_unknown_cost_provider_call_count"]
        assert Decimal(str(summaries[phase]["batch"].get(
            "reserved_unknown_cost_usd", 0))) == reconciliation["reserved_unknown_cost_usd"]
        phase_rows[phase], setup_maps[phase], reconciliations[phase] = rows, setups, reconciliation
    validate_live_admission(phase_rows["admission"], setups=setup_maps["admission"])
    assert summaries["admission"]["live_admission"] is True
    assert len(phase_rows["sample"]) == 600, "sample has not attempted its full frozen panel"

    costs = Counter()
    calls, events, outcomes, tokens = Counter(), Counter(), defaultdict(Counter), Counter()
    unknown_events = Counter()
    for phase, rows in phase_rows.items():
        phase_cost = Decimal("0")
        for row in rows:
            condition = row["condition_id"]
            assert row["external_fixture_call_count"] == 0
            acknowledged_hashes = set(reconciliations[phase]["acknowledged_result_sha256s"])
            if row["unknown_cost_provider_call_count"]:
                assert row["result_sha256"] in acknowledged_hashes and row["status"] != "completed"
            if row["status"] == "completed":
                assert row["external_provider_call_count"] >= 4
                assert row["route_providers"] == ["Parasail"] and row["route_verification_failures"] == 0
                assert row["resolved_models"] == [DEEPSEEK_ROUTE.canonical_model]
                assert row["request_seeds"] == [_paired_cell_request_seed(
                    base_seed=study["inference_seed_base"], world_seed=row["world_seed"],
                    replicate_index=row["replicate_index"])]
            if condition == "reasoning_none_v1":
                assert row["reasoning_tokens"] == 0
            evidence = (root / phase / row["receipt_path"]).parent
            row_cost = Decimal("0")
            for line in (evidence / "events.jsonl").read_text().splitlines():
                event = json.loads(line)
                events[phase] += 1
                payload = json.loads((evidence / event["payload_ref"]).read_bytes())
                if event["event_type"] == "provider_call_started" and payload["request"]["provider"] == "openrouter":
                    request = payload["request"]
                    assert "unit_cost" not in json.dumps(request), "private supplier-cost field in buyer prompt"
                    assert request["model"] == DEEPSEEK_MODEL
                    assert request["reasoning_effort"] == dict(study["ordered_conditions"])[condition]
                    ceiling = study["buyer_runtime_limits"]["buyer_max_output_tokens"]
                    assert request["max_output_tokens"] in (ceiling, ceiling * 2)
                    calls[phase] += 1
                if event["event_type"] in {"provider_call_succeeded", "provider_call_failed", "provider_call_outcome_unknown"}:
                    cost = payload.get("cost_usd")
                    if cost == "unknown":
                        assert event["event_type"] == "provider_call_outcome_unknown"
                        assert row["result_sha256"] in acknowledged_hashes
                        unknown_events[phase] += 1
                        continue
                    assert isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0
                    row_cost += Decimal(str(cost))
                    result = payload.get("provider_result") or {}
                    if result.get("resolved_model") == DEEPSEEK_ROUTE.canonical_model:
                        usage = result["raw_response"]["usage"]
                        assert Decimal(str(usage["cost"])) == Decimal(str(cost))
                        for field in ("prompt_tokens", "completion_tokens"):
                            tokens[field] += usage[field]
                        tokens["reasoning_tokens"] += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
                if event["event_type"] == "family_outcome_recorded":
                    outcome = payload["outcome"]
                    if row["status"] == "completed":
                        assert math.isclose(outcome["buyer_surplus"], row["primary_value"], abs_tol=1e-9)
                        assert math.isclose(outcome["buyer_surplus"] / outcome["oracle_total"],
                                            row["within_case_score"], abs_tol=1e-12)
                    if phase == "sample" and row["status"] == "completed":
                        outcomes[condition]["executed"] += int(outcome["executed"])
                        outcomes[condition]["approval_granted"] += int(outcome["approval_granted"])
                        outcomes[condition]["disclosed_target_price"] += int(outcome["disclosed_rfq_count"] > 0)
                        outcomes[condition]["negative_surplus"] += int(outcome["buyer_surplus"] < 0)
            assert abs(row_cost - Decimal(str(row["cost_usd"]))) < Decimal("1e-12")
            assert row_cost <= Decimal(str(study["inflight_episode_reserve_usd"]))
            phase_cost += row_cost
        assert abs(phase_cost - Decimal(str(summaries[phase]["batch"]["known_cost_usd"]))) < Decimal("1e-10")
        assert unknown_events[phase] == reconciliations[phase][
            "acknowledged_unknown_cost_provider_call_count"]
        costs[phase] = phase_cost

    prior = audit_prior_spend(authorization)
    reserved_unknown = sum((value["reserved_unknown_cost_usd"]
                            for value in reconciliations.values()), Decimal("0"))
    total = prior + costs["admission"] + costs["sample"] + reserved_unknown
    assert total <= Decimal(str(authorization["approved_total_usd"]))
    assert abs(costs["admission"] + costs["sample"] - Decimal(str(
        summaries["sample"]["total_known_cost_usd_including_admission"]))) < Decimal("1e-10")

    plugin = ProcurementRFQPlugin()
    supports = {case.world_seed: procurement_score_support(plugin.validate_payload(case.payload))
                for case in next(iter(setup_maps["sample"].values())).plan.cases}
    independent = recompute_panel(phase_rows["sample"], worlds=study["panel_seeds"], conditions=conditions,
        replicates=study["replicates"], bootstrap_draws=study["bootstrap_draws"],
        bootstrap_seed=study["bootstrap_seed"], score_support_by_world=supports)
    reported = summaries["sample"]["analysis"]["analysis"]
    assert reported is not None, "too few complete world clusters for the planned inference"
    assert independent["complete_world_count"] == reported["complete_pair_world_count"]
    for field in ("mean_paired_difference", "cluster_bootstrap_95", "paired_t_95", "missingness_difference_bounds"):
        assert np.allclose(independent[field], reported[field], rtol=0, atol=1e-12), field
    for condition in conditions:
        assert math.isclose(independent["condition_means"][condition], reported["condition_means"][condition], abs_tol=1e-12)
    after = _evidence_fingerprint(root)
    assert after == before, "read-only audit changed evidence"
    return {
        "status": "verified", "evidence_root": str(root), "source_commit": authorization["source_commit"],
        "admission_episodes": len(phase_rows["admission"]), "sample_episodes": len(phase_rows["sample"]),
        "sample_included": sum(r["status"] == "completed" for r in phase_rows["sample"]),
        "sample_excluded": sum(r["status"] != "completed" for r in phase_rows["sample"]),
        "external_calls": dict(calls), "audited_events": dict(events), "tokens": dict(tokens),
        "cost_usd": {"prior_admission": str(prior), **{p: str(v) for p, v in costs.items()},
                     "reserved_unknown": str(reserved_unknown), "all_runs": str(total)},
        "remaining_authorization_usd": str(Decimal(str(authorization["approved_total_usd"])) - total),
        "privacy_field_check_passed": True, "outcomes_by_condition": dict(outcomes),
        "acknowledged_unknown_billing_calls": sum(unknown_events.values()),
        "independent_analysis": independent,
        "ninety_complete_world_target_met": independent["complete_world_count"] >= 90,
        "unchanged_evidence_fingerprint": before[0], "unchanged_evidence_file_count": before[1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit_live_run(args.root)
    if args.output:
        from aeread.shared_runner.batch import atomic_write_json
        atomic_write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
