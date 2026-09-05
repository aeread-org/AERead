"""Provider-free regret decomposition over published GLM procurement bundles.

Every tracked GLM evidence row carries its parsed action trace. Because the
procurement environment is deterministic given the case, each trace can be
re-driven through the family plugin locally to recover the full award
evaluation the scorer computed. For feasible purchase awards the objective is
additive, so the row's regret to the full-information bound decomposes exactly
into term-level gaps against the oracle award plan: lost revenue, excess
purchase, shipping, duty, working-capital, information, return-freight, and
refund-financing cost, lost refund recovery, and shortfall penalty.

The replay must reproduce the published feasibility, margin, regret, and kit
count exactly; a mismatch is an integrity failure, not a finding. Rows that are
infeasible, deferred, or failed are categorized but not decomposed because
their regret is the whole bound rather than a sum of economic terms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.scheduler import (
    ActionEnvelope,
    LegalityResult,
    ParseResult,
)

from .environment import (
    ProcurementAllocationPlugin,
    _base_offer,
    _best_offer,
    _plain,
    evaluate_award,
    solve_full_information_upper_bound,
)
from .model_campaign import _validate_publication_root
from .runner import load_case


ANALYSIS_ID = "procurement_allocation_glm_regret_decomposition_v1"
SCHEMA_VERSION = "aeread.procurement_allocation_regret_decomposition/0.1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASE_ROOT = Path("cases") / "procurement_allocation_v1"
_PANEL_DIRECTORIES = {
    "dev": CASE_ROOT / "dev",
    "blinded_v3": CASE_ROOT / "blinded_v3",
    "confirmatory_v1_labeled": CASE_ROOT / "confirmatory_v1" / "labeled",
    "confirmatory_v1_opaque": CASE_ROOT / "confirmatory_v1" / "opaque",
}

REGRET_TERMS = (
    "revenue_shortfall",
    "purchase_cost_excess",
    "shipping_cost_excess",
    "duty_cost_excess",
    "working_capital_cost_excess",
    "information_cost_excess",
    "return_freight_cost_excess",
    "refund_financing_cost_excess",
    "recovery_shortfall",
    "shortfall_penalty_excess",
)
_COST_TERMS = {
    "purchase_cost_excess": "purchase_cost_usd",
    "shipping_cost_excess": "shipping_cost_usd",
    "duty_cost_excess": "duty_cost_usd",
    "working_capital_cost_excess": "working_capital_cost_usd",
    "information_cost_excess": "information_cost_usd",
    "return_freight_cost_excess": "return_freight_cost_usd",
    "refund_financing_cost_excess": "refund_financing_cost_usd",
    "shortfall_penalty_excess": "shortfall_penalty_usd",
}


@dataclass(frozen=True, slots=True)
class BundleReport:
    report_id: str
    campaign_id: str
    report_path: str
    panel: str
    surface: str
    prompt: str
    route: str


_CONFIRMATORY = "evidence/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2"
_SCAFFOLD = "evidence/procurement_allocation_glm53_flash_parasail_strategy_scaffold_v4_retry_after"
BUNDLE_REPORTS: tuple[BundleReport, ...] = (
    BundleReport(
        report_id="dev_v2_labeled_unscaffolded",
        campaign_id="procurement_allocation_glm_morph_case_variance_v2",
        report_path=(
            "evidence/procurement_allocation_glm_morph_case_variance_v2/"
            "reports/qualification.json"
        ),
        panel="development",
        surface="labeled",
        prompt="unscaffolded",
        route="glm53_flash_morph",
    ),
    BundleReport(
        report_id="blinded_v3_opaque_unscaffolded",
        campaign_id="procurement_allocation_glm_morph_blinded_invariance_v3",
        report_path=(
            "evidence/procurement_allocation_glm_morph_blinded_invariance_v3/"
            "reports/qualification.json"
        ),
        panel="development",
        surface="opaque",
        prompt="unscaffolded",
        route="glm53_flash_morph",
    ),
    BundleReport(
        report_id="scaffold_v4_labeled_strategy",
        campaign_id=(
            "procurement_allocation_glm53_flash_parasail_strategy_scaffold_v4_retry_after.labeled_original"
        ),
        report_path=f"{_SCAFFOLD}/reports/labeled_original_qualification.json",
        panel="development",
        surface="labeled",
        prompt="strategy_v4",
        route="glm53_flash_parasail",
    ),
    BundleReport(
        report_id="scaffold_v4_opaque_strategy",
        campaign_id=(
            "procurement_allocation_glm53_flash_parasail_strategy_scaffold_v4_retry_after.opaque_reordered"
        ),
        report_path=f"{_SCAFFOLD}/reports/opaque_reordered_qualification.json",
        panel="development",
        surface="opaque",
        prompt="strategy_v4",
        route="glm53_flash_parasail",
    ),
    BundleReport(
        report_id="confirmatory_v2_labeled_control",
        campaign_id=(
            "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2.labeled_control"
        ),
        report_path=f"{_CONFIRMATORY}/reports/labeled_control.json",
        panel="confirmatory",
        surface="labeled",
        prompt="unscaffolded",
        route="glm53_flash_parasail",
    ),
    BundleReport(
        report_id="confirmatory_v2_labeled_treatment",
        campaign_id=(
            "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2.labeled_treatment"
        ),
        report_path=f"{_CONFIRMATORY}/reports/labeled_treatment.json",
        panel="confirmatory",
        surface="labeled",
        prompt="strategy_v4",
        route="glm53_flash_parasail",
    ),
    BundleReport(
        report_id="confirmatory_v2_opaque_control",
        campaign_id=(
            "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2.opaque_control"
        ),
        report_path=f"{_CONFIRMATORY}/reports/opaque_control.json",
        panel="confirmatory",
        surface="opaque",
        prompt="unscaffolded",
        route="glm53_flash_parasail",
    ),
    BundleReport(
        report_id="confirmatory_v2_opaque_treatment",
        campaign_id=(
            "procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v2.opaque_treatment"
        ),
        report_path=f"{_CONFIRMATORY}/reports/opaque_treatment.json",
        panel="confirmatory",
        surface="opaque",
        prompt="strategy_v4",
        route="glm53_flash_parasail",
    ),
)


class ReplayMismatchError(ValueError):
    """A published trace could not be reproduced by the current environment."""


def _sha256_of(value: Mapping[str, Any], *, omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def verified_bundle_report(path: Path) -> tuple[dict[str, Any], str]:
    """Load one published qualification report and verify its digest chain."""
    raw_bytes = Path(path).read_bytes()
    value = json.loads(raw_bytes)
    if not isinstance(value, dict):
        raise ValueError(f"bundle report must be an object: {path}")
    if value.get("artifact_sha256") != _sha256_of(value, omit="artifact_sha256"):
        raise ValueError(f"bundle artifact digest mismatch: {path}")
    rows = value.get("rows")
    if not isinstance(rows, list):
        raise ValueError(f"bundle rows must be an array: {path}")
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"bundle row must be an object: {path}")
        if row.get("result_sha256") != _sha256_of(row, omit="result_sha256"):
            raise ValueError(f"bundle row digest mismatch: {path}")
    return value, hashlib.sha256(raw_bytes).hexdigest()


def case_path_for_id(case_id: str, *, repository_root: Path = REPOSITORY_ROOT) -> Path:
    family, panel, slug = case_id.split(".")
    if family != "procurement_allocation_v1" or panel not in _PANEL_DIRECTORIES:
        raise ValueError(f"unsupported published case id: {case_id}")
    return Path(repository_root) / _PANEL_DIRECTORIES[panel] / f"{slug}.json"


def _trace_action(family_case: Mapping[str, Any], entry: Mapping[str, Any]) -> dict[str, Any]:
    action = entry["action"]
    if action == "inquire":
        return {
            "action": "inquire",
            "supplier_id": entry["supplier_id"],
            "fields": [family_case["policy"]["inquiry_fields"][0]],
            "message": "replay",
        }
    if action in {"request_quote", "request_sample"}:
        return {"action": action, "supplier_id": entry["supplier_id"], "message": "replay"}
    if action == "counter_offer":
        return {
            "action": "counter_offer",
            "supplier_id": entry["supplier_id"],
            "offer_id": entry["offer_id"],
            # Mirror parse_action: null superset fields carry no proposal.
            "proposal": {
                key: value for key, value in _plain(entry["proposal"]).items() if value is not None
            },
            "message": "replay",
        }
    if action in {"submit_award", "check_award"}:
        return {"action": action, "award_lines": _plain(entry["award_lines"])}
    if action == "defer":
        return {"action": "defer", "reason": "replay"}
    raise ReplayMismatchError(f"unknown trace action: {action}")


def replay_action_trace(
    family_case: Mapping[str, Any], action_trace: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Re-drive a published action trace through the deterministic environment."""
    plugin = ProcurementAllocationPlugin()
    phase = plugin.phases(family_case)[0]
    state = plugin.initial_state(family_case, None)
    for entry in action_trace:
        if state["done"]:
            raise ReplayMismatchError("action trace continues after termination")
        if entry.get("status") != "succeeded":
            envelope = ActionEnvelope(
                seat_id="buyer",
                valid=False,
                action=None,
                parse=ParseResult.failure("replayed_agent_action_failure"),
                legality=None,
            )
        else:
            action = _trace_action(family_case, entry)
            legality = plugin.legal(family_case, state, "buyer", phase, action)
            envelope = ActionEnvelope(
                seat_id="buyer",
                valid=legality.legal,
                action=action,
                parse=ParseResult.success(action),
                legality=legality,
            )
        state = plugin.step(family_case, state, phase, {"buyer": envelope}).state
    terminal = plugin.terminal(family_case, state)
    if terminal is None:
        raise ReplayMismatchError("action trace did not reach a terminal state")
    outcome = plugin.outcome(family_case, terminal)
    evaluation = None
    if terminal["reason"] == "submitted":
        evaluation = evaluate_award(
            family_case,
            award_lines=terminal["award_lines"],
            offers=terminal["offers"],
            quality_evidence=terminal["quality_evidence"],
            elapsed_days=terminal["elapsed_days"],
            information_cost_usd=terminal["information_cost_usd"],
        )
    return {"terminal": terminal, "outcome": outcome, "evaluation": evaluation}


def oracle_evaluation(family_case: Mapping[str, Any]) -> dict[str, Any]:
    """Recover the term-level evaluation behind the full-information bound."""
    upper = solve_full_information_upper_bound(family_case)
    interaction = family_case["interaction"]
    suppliers = {supplier["supplier_id"]: supplier for supplier in family_case["suppliers"]}
    offers: dict[str, dict[str, Any]] = {}
    qualities: dict[str, dict[str, Any]] = {}
    lines: list[dict[str, Any]] = []
    elapsed_days = 0
    information_cost = 0.0
    for item in upper.award_plan:
        supplier = suppliers[item["supplier_id"]]
        negotiated = item["mode"] == "negotiated"
        offer = (
            _best_offer(supplier, version=2, issued_day=0)
            if negotiated
            else _base_offer(supplier, version=1, issued_day=0)
        )
        offers[offer["offer_id"]] = offer
        lines.append({"offer_id": offer["offer_id"], "quantity": item["quantity"]})
        quality = supplier["private_terms"]["quality"]
        qualities[item["supplier_id"]] = {
            **_plain(quality),
            "supplier_id": item["supplier_id"],
            "variant_id": supplier["private_terms"]["variant_id"],
            "evidence_status": "verified_sample",
        }
        elapsed_days += (
            interaction["quote_days"]
            + quality["sample_lead_time_days"]
            + (interaction["counter_days"] if negotiated else 0)
        )
        information_cost += (
            interaction["quote_cost_usd"]
            + quality["sample_cost_usd"]
            + (interaction["counter_cost_usd"] if negotiated else 0.0)
        )
    if not lines:
        raise ValueError("oracle award plan is empty; the bound is the defer value")
    evaluation = evaluate_award(
        family_case,
        award_lines=lines,
        offers=offers,
        quality_evidence=qualities,
        elapsed_days=elapsed_days,
        information_cost_usd=information_cost,
    )
    if abs(evaluation["contribution_margin_usd"] - upper.contribution_margin_usd) > 1e-6:
        raise ValueError("oracle re-evaluation does not reproduce the upper bound")
    return {
        "award_plan": [dict(item) for item in upper.award_plan],
        "actions_required": upper.actions_required,
        "elapsed_days": elapsed_days,
        "information_cost_usd": information_cost,
        "offers": offers,
        "evaluation": evaluation,
    }


def _revenue(evaluation: Mapping[str, Any]) -> float:
    return (
        float(evaluation["raw_contribution_margin_usd"])
        + float(evaluation["total_cost_usd"])
        + float(evaluation["shortfall_penalty_usd"])
    )


def decompose_feasible_award(
    family_case: Mapping[str, Any],
    replay: Mapping[str, Any],
    *,
    oracle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Split one feasible award's regret into additive term gaps against the oracle."""
    evaluation = replay["evaluation"]
    if evaluation is None or not evaluation["feasible"]:
        raise ValueError("only feasible submitted awards decompose")
    if oracle is None:
        oracle = oracle_evaluation(family_case)
    reference = oracle["evaluation"]
    terms = {"revenue_shortfall": _revenue(reference) - _revenue(evaluation)}
    for term, field in _COST_TERMS.items():
        terms[term] = float(evaluation[field]) - float(reference[field])
    terms["recovery_shortfall"] = float(reference["expected_recovery_usd"]) - float(
        evaluation["expected_recovery_usd"]
    )
    terms = {key: round(value, 8) for key, value in terms.items()}
    regret = float(replay["outcome"]["regret_to_upper_bound_usd"])
    residual = regret - sum(terms.values())

    terminal = replay["terminal"]
    awarded = {
        terminal["offers"][line["offer_id"]]["supplier_id"]: {
            "quantity": line["quantity"],
            "negotiated": terminal["offers"][line["offer_id"]]["version"] > 1,
        }
        for line in terminal["award_lines"]
    }
    oracle_plan = {
        item["supplier_id"]: {
            "quantity": item["quantity"],
            "negotiated": item["mode"] == "negotiated",
        }
        for item in oracle["award_plan"]
    }
    return {
        "terms": terms,
        "identity_residual_usd": round(residual, 8),
        "structure": {
            "supplier_set_matches_oracle": set(awarded) == set(oracle_plan),
            "quantities_match_oracle": awarded == oracle_plan
            if set(awarded) == set(oracle_plan)
            else False,
            "model_negotiated_supplier_count": sum(
                1 for item in awarded.values() if item["negotiated"]
            ),
            "oracle_negotiated_supplier_count": sum(
                1 for item in oracle_plan.values() if item["negotiated"]
            ),
            "model_action_count": int(terminal["actions_used"]),
            "oracle_actions_required": int(oracle["actions_required"]),
            "model_elapsed_days": int(terminal["elapsed_days"]),
            "oracle_elapsed_days": int(oracle["elapsed_days"]),
        },
    }


def _regret_category(row: Mapping[str, Any]) -> str:
    if row["feasible"] and row["decision"] == "award":
        return "feasible_award"
    if row["feasible"] and row["decision"] == "defer":
        return "feasible_defer"
    if row["termination_reason"] == "submitted":
        return "infeasible_award"
    return str(row["termination_reason"])


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 8) if values else None


def _summarize_feasible(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    feasible = [row for row in rows if row["regret_category"] == "feasible_award"]
    regret_total = sum(row["regret_to_upper_bound_usd"] for row in feasible)
    term_totals = {
        term: round(sum(row["terms"][term] for row in feasible), 8) for term in REGRET_TERMS
    }
    shares = (
        {term: round(total / regret_total, 8) for term, total in term_totals.items()}
        if regret_total > 1e-9
        else {term: 0.0 for term in REGRET_TERMS}
    )
    structure_keys = (
        "supplier_set_matches_oracle",
        "quantities_match_oracle",
    )
    worlds = sorted({row["case_id"] for row in feasible})
    return {
        "row_count": len(feasible),
        "world_count": len(worlds),
        "zero_regret_row_count": sum(
            1 for row in feasible if row["regret_to_upper_bound_usd"] <= 1e-9
        ),
        "regret_total_usd": round(regret_total, 8),
        "mean_regret_usd": _mean([row["regret_to_upper_bound_usd"] for row in feasible]),
        "term_total_usd": term_totals,
        "term_mean_usd": {
            term: _mean([row["terms"][term] for row in feasible]) for term in REGRET_TERMS
        },
        "term_share_of_regret": shares,
        "structure_counts": {
            key: sum(1 for row in feasible if row["structure"][key]) for key in structure_keys
        },
        "negotiation": {
            "rows_where_oracle_negotiates": sum(
                1 for row in feasible if row["structure"]["oracle_negotiated_supplier_count"]
            ),
            "rows_where_model_negotiated": sum(
                1 for row in feasible if row["structure"]["model_negotiated_supplier_count"]
            ),
        },
        "mean_action_excess": _mean(
            [
                row["structure"]["model_action_count"]
                - row["structure"]["oracle_actions_required"]
                for row in feasible
            ]
        ),
    }


def _by_world(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for case_id in sorted({row["case_id"] for row in rows}):
        world_rows = [row for row in rows if row["case_id"] == case_id]
        feasible = [row for row in world_rows if row["regret_category"] == "feasible_award"]
        result[case_id] = {
            "row_count": len(world_rows),
            "feasible_award_count": len(feasible),
            "mean_regret_usd": _mean([row["regret_to_upper_bound_usd"] for row in world_rows]),
            "feasible_mean_regret_usd": _mean(
                [row["regret_to_upper_bound_usd"] for row in feasible]
            ),
            "feasible_term_mean_usd": {
                term: _mean([row["terms"][term] for row in feasible]) for term in REGRET_TERMS
            },
        }
    return result


def build_report(*, repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Replay and decompose every published GLM row; bind every source digest."""
    repository_root = Path(repository_root)
    rows: list[dict[str, Any]] = []
    bundle_bindings: dict[str, Any] = {}
    case_digests: dict[str, str] = {}
    oracle_cache: dict[str, dict[str, Any]] = {}
    mismatches: list[dict[str, Any]] = []
    for bundle in BUNDLE_REPORTS:
        report_path = repository_root / bundle.report_path
        report, file_sha = verified_bundle_report(report_path)
        if report.get("campaign_id") != bundle.campaign_id:
            raise ValueError(f"campaign identity mismatch for {bundle.report_id}")
        manifest_path = report_path.parent.parent / "publication_manifest.json"
        bundle_bindings[bundle.report_id] = {
            "campaign_id": bundle.campaign_id,
            "report_path": bundle.report_path,
            "report_file_sha256": file_sha,
            "artifact_sha256": report["artifact_sha256"],
            "publication_manifest_file_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "row_count": len(report["rows"]),
            "panel": bundle.panel,
            "surface": bundle.surface,
            "prompt": bundle.prompt,
            "route": bundle.route,
        }
        for row in report["rows"]:
            case_path = case_path_for_id(row["case_id"], repository_root=repository_root)
            case = load_case(case_path)
            if case.content_sha256 != row["case_content_sha256"]:
                raise ValueError(f"case digest drift for {row['case_id']}")
            case_digests[row["case_id"]] = case.content_sha256
            family_case = json.loads(case_path.read_text(encoding="utf-8"))["payload"]
            replay = replay_action_trace(family_case, row["action_trace"])
            outcome = replay["outcome"]
            checks = {
                "feasible": outcome["feasible"] == row["feasible"],
                "contribution_margin_usd": abs(
                    outcome["contribution_margin_usd"] - row["contribution_margin_usd"]
                )
                <= 1e-6,
                "regret_to_upper_bound_usd": abs(
                    outcome["regret_to_upper_bound_usd"] - row["regret_to_upper_bound_usd"]
                )
                <= 1e-6,
                "completed_kits": outcome["completed_kits"] == row["completed_kits"],
            }
            if not all(checks.values()):
                mismatches.append(
                    {
                        "report_id": bundle.report_id,
                        "case_id": row["case_id"],
                        "inference_seed": row["inference_seed"],
                        "failed_checks": sorted(k for k, ok in checks.items() if not ok),
                    }
                )
                continue
            category = _regret_category(row)
            record: dict[str, Any] = {
                "report_id": bundle.report_id,
                "panel": bundle.panel,
                "surface": bundle.surface,
                "prompt": bundle.prompt,
                "route": bundle.route,
                "case_id": row["case_id"],
                "inference_seed": row["inference_seed"],
                "result_sha256": row["result_sha256"],
                "regret_category": category,
                "regret_to_upper_bound_usd": float(row["regret_to_upper_bound_usd"]),
                "upper_bound_usd": float(row["upper_bound_usd"]),
                "violations": list(row["violations"]),
                "terms": None,
                "structure": None,
            }
            if category == "feasible_award":
                if row["case_id"] not in oracle_cache:
                    oracle_cache[row["case_id"]] = oracle_evaluation(family_case)
                decomposed = decompose_feasible_award(
                    family_case, replay, oracle=oracle_cache[row["case_id"]]
                )
                if abs(decomposed["identity_residual_usd"]) > 1e-6:
                    raise ValueError(
                        f"regret identity failed for {row['case_id']}/{row['inference_seed']}"
                    )
                record["terms"] = decomposed["terms"]
                record["structure"] = decomposed["structure"]
            rows.append(record)
    if mismatches:
        raise ReplayMismatchError(json.dumps(mismatches, sort_keys=True))

    by_report: dict[str, Any] = {}
    for bundle in BUNDLE_REPORTS:
        subset = [row for row in rows if row["report_id"] == bundle.report_id]
        categories: dict[str, int] = {}
        for row in subset:
            categories[row["regret_category"]] = categories.get(row["regret_category"], 0) + 1
        by_report[bundle.report_id] = {
            "panel": bundle.panel,
            "surface": bundle.surface,
            "prompt": bundle.prompt,
            "route": bundle.route,
            "row_count": len(subset),
            "category_counts": dict(sorted(categories.items())),
            "regret_total_usd": round(
                sum(row["regret_to_upper_bound_usd"] for row in subset), 8
            ),
            "regret_total_by_category_usd": {
                category: round(
                    sum(
                        row["regret_to_upper_bound_usd"]
                        for row in subset
                        if row["regret_category"] == category
                    ),
                    8,
                )
                for category in sorted(categories)
            },
            "feasible_awards": _summarize_feasible(subset),
            "by_world": _by_world(subset),
        }
    by_panel_prompt: dict[str, Any] = {}
    for panel in ("development", "confirmatory"):
        for prompt in ("unscaffolded", "strategy_v4"):
            subset = [row for row in rows if row["panel"] == panel and row["prompt"] == prompt]
            if subset:
                by_panel_prompt[f"{panel}:{prompt}"] = _summarize_feasible(subset)

    report = {
        "schema_version": SCHEMA_VERSION,
        "analysis_id": ANALYSIS_ID,
        "sources": {"bundles": bundle_bindings, "cases": dict(sorted(case_digests.items()))},
        "replay_integrity": {
            "rows_replayed": len(rows),
            "mismatch_count": len(mismatches),
            "tolerance_usd": 1e-6,
        },
        "regret_terms": list(REGRET_TERMS),
        "rows": rows,
        "by_report": by_report,
        "by_panel_prompt": by_panel_prompt,
        "pooled_feasible_awards": _summarize_feasible(rows),
        "interpretation": (
            "Term gaps are exact additive components of each feasible award's regret "
            "against the deterministic full-information plan. Aggregates are "
            "descriptive over curated worlds and mixed prompts and routes; the "
            "independent unit is the economic world and no inferential ranking is "
            "implied. Infeasible, deferred, and failed rows are categorized, not "
            "decomposed."
        ),
    }
    report["artifact_sha256"] = _sha256_of(report, omit="artifact_sha256")
    return report


def publish_report(report: Mapping[str, Any], *, publication_root: Path) -> dict[str, Any]:
    """Write the report and a digest-bound manifest under one evidence bundle."""
    publication_root = Path(publication_root)
    _validate_publication_root(publication_root)
    if publication_root.exists() and any(publication_root.iterdir()):
        raise FileExistsError(f"publication root is not empty: {publication_root}")
    reports_dir = publication_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "regret_decomposition.json"
    report_bytes = canonical_json_bytes(dict(report))
    report_path.write_bytes(report_bytes)
    manifest = {
        "schema_version": "aeread.publication_manifest/0.1",
        "publication_id": report["analysis_id"],
        "campaign_id": report["analysis_id"],
        "artifacts": {
            "reports/regret_decomposition.json": hashlib.sha256(report_bytes).hexdigest()
        },
        "source_bindings": {
            "analysis_artifact_sha256": report["artifact_sha256"],
            "bundles": {
                report_id: {
                    "report_file_sha256": binding["report_file_sha256"],
                    "artifact_sha256": binding["artifact_sha256"],
                    "publication_manifest_file_sha256": binding[
                        "publication_manifest_file_sha256"
                    ],
                }
                for report_id, binding in report["sources"]["bundles"].items()
            },
        },
        "privacy_boundary": {
            "included": (
                "case identities, per-row regret categories, additive term gaps, "
                "structural comparisons to the oracle plan, and source digests"
            ),
            "excluded": (
                "provider payloads, prompts, event logs, and any content not already "
                "present in the tracked source bundles"
            ),
        },
    }
    manifest["manifest_sha256"] = _sha256_of(manifest, omit="manifest_sha256")
    (publication_root / "publication_manifest.json").write_bytes(
        canonical_json_bytes(manifest)
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--publish", action="store_true")
    arguments = parser.parse_args(argv)
    report = build_report(repository_root=arguments.repository_root)
    if arguments.publish:
        if arguments.publication_root is None:
            parser.error("--publish requires --publication-root")
        value: Mapping[str, Any] = publish_report(
            report, publication_root=arguments.publication_root
        )
    else:
        value = {key: item for key, item in report.items() if key != "rows"}
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ANALYSIS_ID",
    "BUNDLE_REPORTS",
    "REGRET_TERMS",
    "ReplayMismatchError",
    "build_report",
    "case_path_for_id",
    "decompose_feasible_award",
    "oracle_evaluation",
    "publish_report",
    "replay_action_trace",
    "verified_bundle_report",
]
