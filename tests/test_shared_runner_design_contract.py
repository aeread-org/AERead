from pathlib import Path


DESIGN = Path(__file__).parents[1] / "docs" / "shared_runner_design.md"
CASE_AUDIT = Path(__file__).parents[1] / "docs" / "problem_bound_case_audit.md"
REFUND_PLAN = Path(__file__).parents[1] / "docs" / "refund_external_benchmark_integration.md"
REASONING_PLAN = Path(__file__).parents[1] / "docs" / "reasoning_condition_and_diagnostics.md"
VERIFIER_TAXONOMY = Path(__file__).parents[1] / "docs" / "verifier_taxonomy.md"
VERIFIER_CASE_MAPPING = Path(__file__).parents[1] / "docs" / "verifier_case_mapping.md"
RUNNER_ARCHITECTURE = (
    Path(__file__).parents[1]
    / "docs"
    / "walkthroughs"
    / "shared_runner_architecture_roadmap.md"
)
WALKTHROUGH_INDEX = Path(__file__).parents[1] / "docs" / "walkthroughs" / "README.md"


def test_shared_runner_design_records_frozen_execution_contract() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    required_terms = {
        "runner-owned declarative phase schedule": "PhaseSpec",
        "phase-specific parsing": "parse_action",
        "explicit action retry record": "ActionAttempt",
        "atomic provider request": "ProviderCall",
        "atomic tool side effect": "ToolInvocation",
        "length retry accounting": "retried_for_length",
        "stable event identity": "event_id",
        "crash-safe continuation": "resume",
        "first clean native family": "housing_v1",
    }
    missing = {meaning: term for meaning, term in required_terms.items() if term not in text}
    assert not missing, f"shared-runner design is missing execution contracts: {missing}"

    assert "async def run(self, ctx" not in text
    assert "at most one provider request per logical action" not in text
    assert "`CallAttempt`" not in text


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


def test_verifier_taxonomy_maps_deployment_cases_and_saturation_claims() -> None:
    text = VERIFIER_TAXONOMY.read_text(encoding="utf-8")

    assert "seven-part operational verification framework" in text
    assert "five semantic verifier families plus two cross-cutting layers" in text

    representative_papers = {
        "canonical/reference": "P11 FinanceBench",
        "rule/constraint/temporal": "P21 AucArena",
        "objective/optimum/bound": "P19 Market-Bench",
        "comparative": "P07 TERMS-Bench",
        "rater/judge": "P12 GDPval",
        "simulation/statistical": "P23 Vending-Bench",
        "integrity/admissibility": "P02 AERead",
    }
    missing = {
        verifier: paper
        for verifier, paper in representative_papers.items()
        if verifier not in text or paper not in text
    }
    assert not missing, f"deployment verifier mappings are missing: {missing}"

    for status in ("not_demonstrated", "saturation_undecidable", "not_applicable"):
        assert status in text, f"saturation status is missing: {status}"
    assert "None of these seven representative mappings is currently certified as `ceiling_exhausted`" in text


def test_verifier_case_mapping_covers_every_audited_and_paper_target() -> None:
    assert VERIFIER_CASE_MAPPING.exists(), "verifier-to-case mapping is missing"
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")

    for family in (
        "canonical_reference",
        "rule_constraint",
        "objective_reference",
        "comparative",
        "rater_judge",
    ):
        assert family in text, f"semantic verifier family is missing: {family}"

    for layer in ("stochastic_estimator", "measurement_validity"):
        assert layer in text, f"cross-cutting verifier layer is missing: {layer}"

    for row_id in [
        *(f"P{i:02d}" for i in range(1, 24)),
        *(f"A{i:02d}" for i in range(1, 6)),
        *(f"M{i:02d}" for i in range(1, 8)),
    ]:
        assert f"| {row_id} |" in text, f"verifier mapping is missing row: {row_id}"

    for mixed_id in ("P05", "P10", "P13", "P14", "P15"):
        row = next(line for line in text.splitlines() if line.startswith(f"| {mixed_id} |"))
        assert "split_required" in row, f"mixed paper must route below paper level: {mixed_id}"

    assert "The primary mapping unit is the estimand" in text
    assert "Neither cross-cutting layer is a primary semantic family" in text
    assert "No row authorizes a cross-family scalar" in text

    taxonomy = VERIFIER_TAXONOMY.read_text(encoding="utf-8")
    audit = CASE_AUDIT.read_text(encoding="utf-8")
    design = DESIGN.read_text(encoding="utf-8")
    for source_text, source_name in (
        (taxonomy, "taxonomy"),
        (audit, "case audit"),
        (design, "shared-runner design"),
    ):
        assert "verifier_case_mapping.md" in source_text, (
            f"{source_name} does not link the verifier-to-case mapping"
        )


def test_runner_taxonomy_architecture_and_build_roadmap_are_frozen() -> None:
    assert RUNNER_ARCHITECTURE.exists(), "runner architecture walkthrough is missing"
    assert WALKTHROUGH_INDEX.exists(), "walkthrough index is missing"
    text = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")

    for term in (
        "FamilyManifest",
        "FamilyPlugin",
        "CaseManifest",
        "SuiteManifest",
        "SamplingPlan",
        "EvaluationBlock",
        "AgentProfile",
        "RunSpec",
        "RunPlan",
        "PlanCell",
        "EpisodeAttempt",
        "PhaseInstance",
        "LogicalAction",
        "ActionAttempt",
        "ProviderCall",
        "ToolInvocation",
        "CanonicalResponse",
        "ActionEnvelope",
        "TransitionResult",
        "Artifact",
        "Projection",
        "EvaluationReceipt",
        "EstimandSpec",
        "VerifierSpec",
        "ReferenceSpec",
        "ScoreEnvelope",
        "ClusterSpec",
        "AnalysisPlan",
        "AggregateResult",
    ):
        assert term in text, f"runner architecture taxonomy is missing: {term}"

    for source_ref in (
        "src/aeread/cli.py:L27-L40",
        "src/aeread/exchange_v1_runner.py:L950-L1234",
        "src/aeread/exchange_economy.py:L4919-L5078",
    ):
        assert source_ref in text, f"current-flow walkthrough is missing: {source_ref}"

    for stage in range(9):
        assert f"| R{stage} |" in text, f"build roadmap is missing stage R{stage}"

    assert "one `PlanCell` = one `Episode`" in text
    assert "Reserve `oracle` for an exact" in text
    assert "write-before-side-effect" in text
    assert "run directory already exists" in text
    assert "exchange_v1 parity" in text
    assert "housing_v1" in text
    assert "tau3" in text

    index = WALKTHROUGH_INDEX.read_text(encoding="utf-8")
    assert "shared_runner_architecture_roadmap.md" in index

    design = DESIGN.read_text(encoding="utf-8")
    assert "walkthroughs/shared_runner_architecture_roadmap.md" in design
