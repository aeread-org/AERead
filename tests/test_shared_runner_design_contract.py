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
PUBLIC_ENVIRONMENT_SPEC = (
    Path(__file__).parents[1]
    / "docs"
    / "public_environment_and_external_adapter_spec.md"
)


def _markdown_table_row(
    text: str, label: str, *, expected_cells: int
) -> tuple[str, ...]:
    matches = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = tuple(cell.strip() for cell in line.strip("|").split("|"))
        if label in cells:
            matches.append(cells)
    assert len(matches) == 1, f"expected one Markdown row for {label!r}: {matches!r}"
    assert (
        len(matches[0]) == expected_cells
    ), f"expected {expected_cells} cells for {label!r}: {matches[0]!r}"
    return matches[0]


def _row_has_semantics(
    row: tuple[str, ...],
    *,
    required: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> bool:
    row_text = " | ".join(row)
    return all(fragment in row_text for fragment in required) and not any(
        fragment in row_text for fragment in forbidden
    )


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


def test_shared_runner_design_uses_authoritative_public_execution_api() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    assert "class EnvironmentPlugin(Protocol):" in text
    assert "class CaseFamilyPlugin(Protocol):" not in text
    assert ") -> ParseResult: ..." in text
    assert ") -> Mapping[str, ParseResult]: ..." not in text
    assert ") -> LegalityResult: ..." in text
    assert ") -> Mapping[str, LegalityResult]: ..." not in text
    assert "class AttemptObserver(Protocol):" in text
    assert "*, attempts: AttemptObserver" in text


def test_public_environment_spec_uses_plan_cell_only() -> None:
    text = PUBLIC_ENVIRONMENT_SPEC.read_text(encoding="utf-8")
    unexpected_retired_lines = [
        line
        for line in text.splitlines()
        if ("EpisodeCell" in line or "EpisodeCellT" in line)
        and not any(
            label in line.lower()
            for label in ("retired", "historical", "negative migration")
        )
    ]

    assert "PlanCell" in text
    assert not unexpected_retired_lines, (
        "authoritative public signatures retain retired plan-cell names: "
        f"{unexpected_retired_lines}"
    )


def test_shared_runner_design_allows_zero_provider_calls_per_attempt() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    assert "ProviderCall 0..n" in text
    assert "zero `ProviderCall` records" in text
    assert "ProviderCall 1..n" not in text


def test_housing_full_information_relaxation_is_a_bound_not_an_oracle() -> None:
    text = DESIGN.read_text(encoding="utf-8")

    assert 'bound_provider_id = "housing_exact_assignment_v1"' in text
    assert 'oracle_id = "housing_exact_assignment_v1"' not in text


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


def test_verifier_case_mapping_gives_one_real_workflow_and_benchmark_per_class() -> None:
    assert VERIFIER_CASE_MAPPING.exists(), "verifier-to-case example mapping is missing"
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")

    examples = {
        "canonical/reference": ("retail refund", "tau3-bench"),
        "rule/constraint/temporal": ("regulated refund process", "STATE-Bench"),
        "objective/optimum/bound": ("procurement and scheduling", "EconEvals"),
        "comparative": ("supplier price negotiation", "TERMS-Bench"),
        "rater/judge": ("professional analyst deliverable", "GDPval"),
        "simulation/statistical": ("inventory and pricing", "Vending-Bench"),
        "integrity/admissibility": ("audited agent episode", "AERead EvaluationReceipt"),
    }
    for verifier_class, (workflow, benchmark) in examples.items():
        assert verifier_class in text, f"verifier class is missing: {verifier_class}"
        assert workflow in text, f"real-world workflow is missing: {workflow}"
        assert benchmark in text, f"benchmark mapping is missing: {benchmark}"

    assert "five semantic verifier families" in text
    assert "two cross-cutting layers" in text
    assert "not a standalone capability benchmark" in text
    assert "## The 23-paper routing table" not in text

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


def test_verifier_mapping_marks_primary_leaf_not_full_scalar() -> None:
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")
    row = _markdown_table_row(text, "**canonical/reference**", expected_cells=4)
    required = (
        "primary deterministic database leaf, not the full upstream scalar",
        "112 of 114",
        "DB + NL_ASSERTION",
        "natural-language assertions remain a separate leaf",
    )
    forbidden = (
        "is the full upstream scalar",
        "equals the full upstream scalar",
        "full tau3 parity",
        "DB-only benchmark",
    )

    assert _row_has_semantics(row, required=required, forbidden=forbidden)

    mutated = tuple(
        cell.replace(
            "is a primary deterministic database leaf, not the full upstream scalar",
            "is the full upstream scalar",
        )
        for cell in row
    )
    assert not _row_has_semantics(mutated, required=required, forbidden=forbidden)


def test_state_mapping_separates_machine_state_and_judged_requirements() -> None:
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")
    row = _markdown_table_row(text, "**rule/constraint/temporal**", expected_cells=4)
    required = (
        "final-state requirements are the official deterministic layer",
        "non-empty task requirements use the locked task-requirements judge",
        "empty task-requirement set uses the official deterministic identity shortcut",
        "does not call a judge",
        "task 142: 5 state, 0 task",
        "compiled into a versioned predicate over recorded trace evidence",
    )
    forbidden = (
        "all task requirements are deterministic",
        "all task requirements use the locked judge",
        "generic deterministic temporal scorer",
    )

    assert _row_has_semantics(row, required=required, forbidden=forbidden)

    mutated = tuple(
        cell.replace(
            "non-empty task requirements use the locked task-requirements judge",
            "all task requirements use the locked judge",
        )
        for cell in row
    )
    assert not _row_has_semantics(mutated, required=required, forbidden=forbidden)


def test_econ_and_vending_mapping_preserves_reference_and_admission_limits() -> None:
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")
    econ_row = _markdown_table_row(
        text, "**objective/optimum/bound**", expected_cells=4
    )
    required = (
        "empirical random-matching comparison baseline, not an exact optimum",
        "pinned solver and certificate",
        "declared validity domain",
    )
    forbidden = ("random-matching optimum", "always exact", "seed-only reference")

    assert _row_has_semantics(econ_row, required=required, forbidden=forbidden)

    mutated = tuple(
        cell.replace(
            "empirical random-matching comparison baseline, not an exact optimum",
            "random-matching optimum",
        )
        for cell in econ_row
    )
    assert not _row_has_semantics(mutated, required=required, forbidden=forbidden)

    vending_row = _markdown_table_row(
        text, "**simulation/statistical**", expected_cells=4
    )
    assert _row_has_semantics(
        vending_row,
        required=(
            "official V2 code, license, and state contract",
            "official adapter parity is blocked",
        ),
        forbidden=("official adapter parity is available",),
    )


def test_terms_and_gdpval_mapping_carries_admission_protocol_caveats() -> None:
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")
    terms_row = _markdown_table_row(text, "**comparative**", expected_cells=4)
    assert _row_has_semantics(
        terms_row,
        required=(
            "AERead-owned TERMS-style conformance",
            "official simulator, defaults, and license",
            "official parity is blocked",
        ),
        forbidden=("official TERMS parity",),
    )

    gdpval_row = _markdown_table_row(text, "**rater/judge**", expected_cells=4)
    assert _row_has_semantics(
        gdpval_row,
        required=(
            "occupational experts in blinded pairwise comparison",
            "dataset license must pass admission",
        ),
        forbidden=("LLM judge is official expert parity",),
    )


def test_housing_mapping_separates_baseline_lower_and_upper_refs() -> None:
    text = VERIFIER_CASE_MAPPING.read_text(encoding="utf-8")

    assert "`B` is the naive executable comparison baseline" in text
    assert "`L = 0` is a separate feasible lower-bound witness" in text
    assert "`U` is a full-information maximum-weight relaxation" in text
    assert "not one oracle score" in text


def test_public_spec_reports_implemented_foundation_and_missing_runtime() -> None:
    text = PUBLIC_ENVIRONMENT_SPEC.read_text(encoding="utf-8")
    status_section = text.split("## 11. Mapping to the current repository", 1)[1].split(
        "## 12. Implementation and review gates", 1
    )[0]
    implementation_row = _markdown_table_row(
        status_section,
        "`src/aeread/runner/planning.py`, `registry.py`, and `event_store.py`",
        expected_cells=3,
    )

    assert "exact-version developer registry/discovery foundation" in " | ".join(
        implementation_row
    )
    assert "trusted registry" not in status_section
    assert "trusted discovery" not in status_section
    assert "Formal/paper plugin discovery is not implemented" in status_section
    for requirement in (
        "allowlist before `entry_point.load()`",
        "distribution name/version",
        "source/code pin",
        "PlanCell and receipt provenance",
    ):
        assert requirement in status_section
    assert (
        "scheduler, attempt executor, receipt finalization, replay/resume, and benchmark adapters do not yet exist"
        in text
    )
    assert "implementation has not started" not in text
    assert "There is currently no `RunPlan`" not in text


def test_attempt_observer_docs_separate_normative_target_from_current_sdk() -> None:
    public_text = PUBLIC_ENVIRONMENT_SPEC.read_text(encoding="utf-8")
    section = public_text.split(
        "### 3.3 Observation and canonical response boundary", 1
    )[1].split("### 3.4 Verifier contract", 1)[0]
    normalized_section = " ".join(section.split())

    assert "Normative target (proposed; not the current import surface)" in section
    assert "ProviderCallStart" in section
    assert "ProviderCallToken" in section
    assert "provider_call_id" in section
    assert "CallAttemptStart" not in section.split("The current SDK", 1)[0]
    assert "CallAttemptToken" not in section.split("The current SDK", 1)[0]
    assert "The current SDK still exports the retired compatibility names" in section
    assert "`CallAttemptStart` and `CallAttemptToken`" in normalized_section
    assert "Task 2.1" in section

    design = DESIGN.read_text(encoding="utf-8")
    roadmap = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")
    for text in (design, roadmap):
        assert (
            "normative ProviderCall target is not yet the current import surface"
            in text
        )
        assert "Task 2.1" in text


def test_shared_runner_status_reports_landed_foundation_and_missing_runtime() -> None:
    status = DESIGN.read_text(encoding="utf-8").splitlines()[2]

    assert "authoring/planning/measurement records" in status
    assert "evidence foundation" in status
    for missing in (
        "scheduler",
        "executor",
        "receipt finalization",
        "replay",
        "adapters",
    ):
        assert missing in status
    assert "schemas remain to be landed" not in status


def test_roadmap_does_not_invent_reference_or_generator_plugin_groups() -> None:
    text = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")

    assert (
        "implementation role; not a separate public Protocol or entry-point group in `0.1`"
        in text
    )
    assert "aeread.reference_providers" not in text
    assert "aeread.case_generators" not in text


def test_runner_taxonomy_architecture_and_build_roadmap_are_frozen() -> None:
    assert RUNNER_ARCHITECTURE.exists(), "runner architecture walkthrough is missing"
    assert WALKTHROUGH_INDEX.exists(), "walkthrough index is missing"
    text = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")

    for term in (
        "FamilyManifest",
        "EnvironmentPlugin",
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
        "DecisionSlot",
        "ActionChannel",
        "LogicalAction",
        "ActionAttempt",
        "ProviderCall",
        "ToolInvocation",
        "AttemptObserver",
        "CanonicalResponse",
        "ActionBundle",
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


def test_runner_architecture_preserves_public_decision_topology() -> None:
    text = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")

    for term in (
        "EnvironmentPlugin",
        "DecisionSlot",
        "ActionChannel",
        "ActionBundle",
        "AttemptObserver",
    ):
        assert term in text, f"runner architecture is missing public topology term: {term}"

    assert "FamilyPlugin" not in text
    assert (
        "One `DecisionSlot` creates one `LogicalAction`, and one successful logical "
        "action closes as one ordered atomic `ActionBundle`."
    ) in text
