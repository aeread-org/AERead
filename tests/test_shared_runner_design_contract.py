from pathlib import Path


DESIGN = Path(__file__).parents[1] / "docs" / "shared_runner_design.md"
CASE_AUDIT = Path(__file__).parents[1] / "docs" / "problem_bound_case_audit.md"
REFUND_PLAN = Path(__file__).parents[1] / "docs" / "refund_external_benchmark_integration.md"
REASONING_PLAN = Path(__file__).parents[1] / "docs" / "reasoning_condition_and_diagnostics.md"
VERIFIER_TAXONOMY = Path(__file__).parents[1] / "docs" / "verifier_taxonomy.md"


def test_shared_runner_design_records_frozen_execution_contract() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = {
        "runner-owned declarative phase schedule": "PhaseSpec",
        "phase-specific parsing": "parse_action",
        "explicit provider attempt record": "CallAttempt",
        "length retry accounting": "retried_for_length",
        "stable event identity": "event_id",
        "crash-safe continuation": "resume",
        "first clean native family": "housing_v1",
    }
    missing = {meaning: term for meaning, term in required_terms.items() if term not in text}
    assert not missing, f"shared-runner design is missing execution contracts: {missing}"

    assert "async def run(self, ctx" not in text
    assert "at most one provider request per logical action" not in text


def test_shared_runner_design_records_measurement_contract() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = {
        "optimum lower bound": "optimum_lower_bound",
        "optimum upper bound": "optimum_upper_bound",
        "comparison baseline": "comparison_baseline",
        "outcome support": "outcome_support_min",
        "bound routing": "epsilon_solved",
        "undecidable compressed frontier": "compressed_undecidable",
        "separate social outcome": "social_welfare",
        "separate private outcome": "principal_utility",
        "distributional capture": "capture_by_seat",
        "special-case bargaining reference": "symmetric_nash_par",
    }
    missing = {meaning: term for meaning, term in required_terms.items() if term not in text}
    assert not missing, f"shared-runner design is missing measurement contracts: {missing}"

    assert "cross_family_scalar: disabled" in text
    assert "V_LB <= V* <= V_UB" in text
    assert "A feasible policy is not an outcome floor" in text
    assert "`feasible_floor`" not in text
    assert "`attainable_ceiling`" not in text


def test_shared_runner_design_records_cluster_contract() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    for term in (
        "cluster_id",
        "cluster_level",
        "observations_per_cluster",
        "world_seed",
        "paired",
        "fixed_panel",
    ):
        assert term in text, f"shared-runner design is missing cluster term: {term}"

    assert "resample clusters" in text
    assert "not treat decision rows" in text


def test_problem_bound_case_audit_covers_survey_and_native_cases() -> None:
    text = CASE_AUDIT.read_text(encoding="utf-8")

    assert "# Problem-to-bound audit: 23 papers and five AERead cases" in text
    assert "22 external papers plus the AERead paper" in text
    assert "PDF-checked" in text
    for row_id in [*(f"P{i:02d}" for i in range(1, 24)), *(f"A{i:02d}" for i in range(1, 6))]:
        assert f"| {row_id} |" in text

    assert "Economic task versus economic coordination mechanism" in text
    assert "A feasible policy witnesses `optimum_lower_bound`; it is not an outcome floor" in text


def test_refund_external_benchmark_plan_records_adapter_and_measurement_gates() -> None:
    assert REFUND_PLAN.exists(), "refund external-benchmark integration plan is missing"
    text = REFUND_PLAN.read_text(encoding="utf-8")

    required_terms = {
        "pinned tau3 release": "v1.0.1",
        "pinned tau3 commit": "fc0055dc4e0a316c3f83133267fbd6faaa770992",
        "retail task split": "retail/base",
        "legacy repository prohibition": "sierra-research/tau-bench",
        "deterministic primary estimand": "tau3_retail_db_state",
        "upstream judge-dependent result": "tau3_upstream_reward",
        "measurement routing": "property_or_answer",
        "upstream parity": "component-level parity",
        "receipt task provenance": "task_sha256",
        "receipt database provenance": "database_sha256",
        "receipt simulator provenance": "user_simulator_prompt_sha256",
        "receipt scorer provenance": "scorer_version",
        "independent cluster": "task instance",
        "nested reruns": "nested replicates",
        "fixed-suite saturation scope": "fixed-suite ceiling exhaustion",
        "native refund admission gate": "refund_v1",
    }
    missing = {meaning: term for meaning, term in required_terms.items() if term not in text}
    assert not missing, f"refund integration plan is missing contracts: {missing}"

    assert "112 of 114" in text
    assert "40 of 114" in text
    assert "18-task pilot" in text
    assert "universal refund capability" in text

    design = DESIGN.read_text(encoding="utf-8")
    assert "refund_external_benchmark_integration.md" in design


def test_reasoning_condition_plan_keeps_behavior_primary_and_diagnostics_typed() -> None:
    assert REASONING_PLAN.exists(), "reasoning-condition diagnostic plan is missing"
    text = REASONING_PLAN.read_text(encoding="utf-8")

    for term in (
        "reasoning_condition_id",
        "reasoning_effort",
        "reasoning_token_budget",
        "rationale_visibility",
        "objective_selection",
        "strategic_modeling",
        "constraint_tracking",
        "execution",
        "reasoning_tokens",
        "judge_dependent",
        "post-hoc rationalization",
        "paired",
        "task/user seed",
    ):
        assert term in text, f"reasoning-condition plan is missing: {term}"

    assert "actions and outcomes remain primary" in text
    assert "secondary diagnostic surface" in text
    assert "reasoning on/off" in text
    assert "must not be scored as an economic no-op" in text

    design = DESIGN.read_text(encoding="utf-8")
    assert "reasoning_condition_and_diagnostics.md" in design


def test_verifier_taxonomy_separates_semantics_references_and_validity() -> None:
    assert VERIFIER_TAXONOMY.exists(), "verifier taxonomy is missing"
    text = VERIFIER_TAXONOMY.read_text(encoding="utf-8")

    for term in (
        "VerifierSpec",
        "canonical_point",
        "canonical_set",
        "terminal_state_equivalence",
        "distance_to_canonical_set",
        "constraint_satisfaction",
        "temporal_property",
        "exact_optimum",
        "bound_certificate",
        "baseline_headroom",
        "outcome_support_normalized",
        "baseline_delta",
        "paired_comparison",
        "head_to_head",
        "human_rubric",
        "llm_rubric",
        "stochastic_estimator",
        "measurement_validity",
        "hybrid_gate",
    ):
        assert term in text, f"verifier taxonomy is missing: {term}"

    assert "V_LB <= V* <= V_UB" in text
    assert "max(0, V_LB - V_agent) <= regret <= V_UB - V_agent" in text
    assert "headroom_capture = (V_agent - B) / (V_UB - B)" in text
    assert "support_score = (V - S_min) / (S_max - S_min)" in text
    assert "A feasible policy is not an outcome floor" in text
    assert "one canonical action sequence" in text

    design = DESIGN.read_text(encoding="utf-8")
    assert "verifier_taxonomy.md" in design
