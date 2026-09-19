"""Phase 2 offline admission, fixed panel, behavioral diagnostics and inference."""

from __future__ import annotations
import json
import statistics
from pathlib import Path
import numpy as np
from scipy.optimize import brentq
from scipy.stats import nct, t
from .phase2_admission import digest, source_pins
from .phase2_worlds import (
    build_world,
    episode_case,
    CATEGORIES,
    SCREEN_SEEDS,
    PILOT_SEEDS,
    CONFIRMATORY_SEEDS,
)
from .phase2_policies import replay_policy
from .phase2_runner import PROMPTS
from .environment import solve_full_information_upper_bound
from .headroom_screen import classify_world_continuous
from .strategy_scaffold import GLM_PARASAIL_CANDIDATE
from aeread.shared_runner.run.resolver import canonical_json_bytes

CAMPAIGN_ID = "procurement_phase2_provider_recovery_v1"
HARD_COST_CEILING_USD = 0.45
BASELINE_SETTLED_USD = 0.0260186355
BASELINE_RESERVED_USD = 0.0051345
PRIOR_PUBLICATIONS = (
    (
        "procurement_allocation_phase2_pilot_v1",
        "41e5ee0d0ba06f650388d3bdd9f46caddccfe7253f0b67eab940d88f3c88d84c",
        "settled_cost_usd",
        "confirmatory_rows_executed",
    ),
    (
        "procurement_allocation_phase2_action_format_recovery_v1",
        "ea8e2e3d9ff97379e16978014540fcdf025e74a78dc33e5e30a387ef38b0d494",
        "recovery_settled_cost_usd",
        "confirmation_rows_executed",
    ),
)


def prior_campaign_accounting():
    """Carry each prior attempt once, including charges still unknown after 429."""
    import hashlib
    import math

    base = Path(__file__).resolve().parents[3] / "evidence/procurement_allocation"
    campaigns = []
    for name, expected_manifest, settled_key, confirmation_key in PRIOR_PUBLICATIONS:
        root = base / name
        manifest = json.loads((root / "publication_manifest.json").read_text())
        if manifest["manifest_sha256"] != expected_manifest or expected_manifest != digest(
            {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        ):
            raise ValueError("prior Phase 2 publication digest changed")
        path = root / "reports/execution_status.json"
        status_sha = manifest["artifacts"]["reports/execution_status.json"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != status_sha:
            raise ValueError("prior Phase 2 execution status changed")
        status = json.loads(path.read_text())
        if status["status"] != "pilot_operational_gate_failed" or status[confirmation_key] != 0:
            raise ValueError("prior campaign is not the declared stopped pilot")
        campaigns.append(dict(
            campaign_id=status["campaign_id"],
            publication_manifest_sha256=expected_manifest,
            status_file_sha256=status_sha,
            settled_cost_usd=status[settled_key],
            unresolved_reserved_cost_usd=status["unresolved_reserved_cost_usd"],
        ))
    settled = sum(c["settled_cost_usd"] for c in campaigns)
    reserved = sum(c["unresolved_reserved_cost_usd"] for c in campaigns)
    if not (
        len({c["campaign_id"] for c in campaigns}) == len(campaigns)
        and math.isclose(settled, BASELINE_SETTLED_USD, rel_tol=0, abs_tol=1e-12)
        and math.isclose(reserved, BASELINE_RESERVED_USD, rel_tol=0, abs_tol=1e-12)
    ):
        raise ValueError("prior Phase 2 accounting does not match frozen baseline")
    return dict(
        campaigns=campaigns,
        settled_cost_usd=BASELINE_SETTLED_USD,
        unresolved_reserved_cost_usd=BASELINE_RESERVED_USD,
        accounted_cost_usd=BASELINE_SETTLED_USD + BASELINE_RESERVED_USD,
        pooling="no outcome pooling; prior settled spend and unknown-charge reservations count toward combined ceiling",
    )


def power_sensitivity():
    def power(n, d):
        crit = t.ppf(0.975, n - 1)
        return float(
            nct.sf(crit, n - 1, d * n**0.5) + nct.cdf(-crit, n - 1, d * n**0.5)
        )

    return dict(
        method="two-sided paired noncentral t sensitivity, not bootstrap power",
        independent_worlds=8,
        alpha=0.05,
        power_at_d_095=power(8, 0.95),
        d_for_80_percent_power=brentq(lambda d: power(8, d) - 0.8, 0.1, 3.0),
        guaranteed_power=False,
        within_world_pilot_variance="unidentified with one seed per arm",
    )


def offline_screen():
    worlds = []
    for i in range(8):
        case = build_world(i)
        upper = solve_full_information_upper_bound(case["payload"])
        rows = []
        for seed in SCREEN_SEEDS:
            payload = episode_case(case, seed)["payload"]
            results = {
                p: replay_policy(payload, p)["outcome"]
                for p in ("greedy", "best_qualified", "defer", "always_buy")
            }
            rows.append(dict(seed=seed, policies=results))
        greedy = statistics.mean(
            r["policies"]["greedy"]["regret_to_upper_bound_usd"] for r in rows
        )
        reference = statistics.mean(
            r["policies"]["best_qualified"]["regret_to_upper_bound_usd"] for r in rows
        )
        trap = i >= 6
        spread = None if trap else (greedy - reference) / upper.contribution_margin_usd
        classification = (
            None
            if trap
            else classify_world_continuous(
                [
                    r["policies"]["best_qualified"]["regret_to_upper_bound_usd"]
                    for r in rows
                ],
                {"greedy": greedy},
                materiality_scale=upper.contribution_margin_usd,
            )
        )
        passed = (
            (
                all(
                    r["policies"]["best_qualified"]["decision"] == "defer" for r in rows
                )
                and upper.contribution_margin_usd == 0
            )
            if trap
            else spread >= 0.15
        )
        worlds.append(
            dict(
                world_id=case["case_id"],
                category=CATEGORIES[i],
                case_sha256=case["content_sha256"],
                upper_bound_usd=upper.contribution_margin_usd,
                optimal_award_supplier_count=len(upper.award_plan),
                mean_greedy_regret_usd=greedy,
                mean_reference_regret_usd=reference,
                relative_policy_spread=spread,
                continuous_classifier_diagnostic=classification,
                reference_within_world_variance=statistics.variance(
                    r["policies"]["best_qualified"]["regret_to_upper_bound_usd"]
                    for r in rows
                ),
                passed=passed,
                rows=rows,
            )
        )
    return dict(
        campaign_id=CAMPAIGN_ID,
        passed=all(w["passed"] for w in worlds),
        worlds=worlds,
        screen_seeds=list(SCREEN_SEEDS),
        live_calls=0,
        admission_rule="six worlds >=15% mean public-greedy vs public-reference regret spread / certified bound; two certified purchase-infeasible traps",
        classifier_scope="classify_world_continuous is reported, not relabelled: it tests within-policy noise spread, a different criterion from the requested greedy-optimal gap",
        power=power_sensitivity(),
        implementation_pins=source_pins(),
    )


def execution_contract(cases, screen):
    if not screen["passed"] or screen["implementation_pins"] != source_pins():
        raise ValueError("screen failed or source changed")
    value = dict(
        campaign_id=CAMPAIGN_ID,
        implementation_pins=source_pins(),
        case_digests=[c["content_sha256"] for c in cases],
        world_ids=[c["case_id"] for c in cases],
        categories=list(CATEGORIES),
        pilot_seeds=list(PILOT_SEEDS),
        confirmatory_seeds=list(CONFIRMATORY_SEEDS),
        paired_environment_and_inference_seeds=True,
        arms=list(PROMPTS),
        prompt_sha256={a: digest(p) for a, p in PROMPTS.items()},
        screen_sha256=digest(screen),
        route=json.loads(canonical_json_bytes(GLM_PARASAIL_CANDIDATE)),
        hard_total_cost_ceiling_usd=HARD_COST_CEILING_USD,
        baseline_phase1_cost_usd=0.0,
        prior_phase2_campaigns=prior_campaign_accounting(),
        recovery_scope="fresh full-panel operational attempt; carry both prior attempts and unresolved reservations; preserve provider exception messages privately; unchanged prompts, parser, economics, worlds, route, seeds, retry policy and analysis",
        provider_failure_evidence="retain original exception message and typed fields in ignored billing; message digest may be published; raw response body availability depends on adapter",
        max_output_tokens_per_action=1200,
        max_actions=10,
        max_trajectory_cost_usd=0.025,
        retry_policy=dict(
            max_action_attempts=2,
            conditions=["rate_limit"],
            minimum_delay_seconds=60.0,
            maximum_retry_after_seconds=180.0,
        ),
        canary_requests=2,
        pilot_rows=16,
        confirmatory_rows=48,
        row_is="interactive episode, not a single provider call",
        primary="treatment minus control regret; average paired seeds within each world, then equal weight eight worlds",
        bootstrap=dict(
            resamples=50000, seed=20260919, unit="world", interval="percentile 95%"
        ),
        promotion_guard="complete paired replay; finite consistent accounting; no treatment constraint violations; upper CI < 0",
        secondary="category means, nontrap sensitivity, trap defer and invalid-award rates, quote order, sample counts, split awards, research costs",
        freeze_policy="implementation and both prompts fixed before pilot; no outcome-based retuning; confirmation digest sealed after operational pilot gate",
        pilot_gate="16 completed replayed rows; no schema/invalid-action failures; at least one explicit trap defer and one profitable valid nontrap award",
        pilot_variance="one seed cannot identify within-world model variance; offline reference variance and across-world pilot dispersion are descriptive",
    )
    return {**value, "plan_sha256": digest(value)}


def check_panel(rows, worlds, seeds):
    expected = {(w, s, a) for w in worlds for s in seeds for a in PROMPTS}
    actual = [(r["world_id"], r["environment_seed"], r["arm"]) for r in rows]
    return (
        len(actual) == len(expected)
        and len(set(actual)) == len(actual)
        and set(actual) == expected
    )


def pilot_gate(rows, worlds):
    complete = check_panel(rows, worlds, PILOT_SEEDS)
    operational = complete and all(
        r.get("status") == "completed"
        and r.get("receipt_replayed") is True
        and r.get("decision") != "failed"
        and r.get("termination_reason")
        not in {"invalid_action", "interaction_budget_exhausted"}
        for r in rows
    )
    trap_defer = any(
        r.get("category", "").startswith("trap") and r.get("decision") == "defer"
        for r in rows
    )
    real_award = any(
        not r.get("category", "").startswith("trap")
        and r.get("feasible_award") is True
        and r.get("contribution_margin_usd", 0) > 0
        for r in rows
    )
    return dict(
        passed=operational and trap_defer and real_award,
        complete_panel=complete,
        operationally_complete=operational,
        trap_defer_observed=trap_defer,
        profitable_nontrap_award_observed=real_award,
        within_world_variance=None,
        variance_status="not identifiable from one seed",
        selected_for_treatment_advantage=False,
    )


def analyze(rows, worlds, seeds=CONFIRMATORY_SEEDS):
    complete = check_panel(rows, worlds, seeds)
    measured = complete and all(
        r.get("status") == "completed" and r.get("receipt_replayed") is True
        for r in rows
    )
    result = dict(
        complete_panel=complete,
        fully_replayed=measured,
        planned_rows=len(worlds) * len(seeds) * 2,
        observed_rows=len(rows),
        support=False,
        inference_scope="fixed curated panel; eight worlds, not 48 independent observations",
    )
    if not measured:
        return {
            **result,
            "delta_usd": None,
            "ci95": None,
            "missingness": "report separately; never drop failed cells",
        }
    index = {(r["world_id"], r["environment_seed"], r["arm"]): r for r in rows}
    guard = True
    deltas = []
    per_world = []
    for w in worlds:
        for s in seeds:
            a, b = index[w, s, "control"], index[w, s, "treatment"]
            for r in (a, b):
                numbers = [
                    r.get(k)
                    for k in (
                        "upper_bound_usd",
                        "contribution_margin_usd",
                        "regret_to_upper_bound_usd",
                    )
                ]
                if not all(
                    isinstance(n, (int, float))
                    and not isinstance(n, bool)
                    and np.isfinite(n)
                    for n in numbers
                ):
                    raise ValueError("nonfinite measurement in completed row")
                if (
                    abs(max(0.0, numbers[0] - numbers[1]) - numbers[2]) > 1e-6
                    or numbers[1] > numbers[0] + 1e-6
                ):
                    raise ValueError("inconsistent regret accounting")
            if a["upper_bound_usd"] != b["upper_bound_usd"]:
                raise ValueError("paired upper bounds differ")
            guard = (
                guard
                and b["feasible"]
                and not b["violations"]
                and b["decision"] in {"award", "defer"}
            )
        d = statistics.mean(
            index[w, s, "treatment"]["regret_to_upper_bound_usd"]
            - index[w, s, "control"]["regret_to_upper_bound_usd"]
            for s in seeds
        )
        deltas.append(d)
        per_world.append(
            dict(
                world_id=w,
                category=index[w, seeds[0], "control"]["category"],
                delta_usd=d,
                within_arm_variance={
                    arm: (
                        statistics.variance(
                            index[w, s, arm]["regret_to_upper_bound_usd"] for s in seeds
                        )
                        if len(seeds) > 1
                        else None
                    )
                    for arm in PROMPTS
                },
            )
        )
    rng = np.random.default_rng(20260919)
    ci = np.quantile(
        np.array(deltas)[rng.integers(0, len(worlds), size=(50000, len(worlds)))].mean(
            axis=1
        ),
        [0.025, 0.975],
    ).tolist()
    by_category = {
        c: statistics.mean(w["delta_usd"] for w in per_world if w["category"] == c)
        for c in sorted({w["category"] for w in per_world})
    }
    return {
        **result,
        "delta_usd": statistics.mean(deltas),
        "ci95": ci,
        "treatment_validity_guard": bool(guard),
        "support": bool(guard and ci[1] < 0),
        "per_world": per_world,
        "category_deltas_usd": by_category,
        "nontrap_delta_usd": statistics.mean(
            w["delta_usd"] for w in per_world if not w["category"].startswith("trap")
        ),
        "trap_deferrals": {
            a: sum(
                r["arm"] == a
                and r["category"].startswith("trap")
                and r["decision"] == "defer"
                for r in rows
            )
            for a in PROMPTS
        },
        "invalid_awards": {
            a: sum(
                r["arm"] == a and r["decision"] == "award" and not r["feasible_award"]
                for r in rows
            )
            for a in PROMPTS
        },
    }
