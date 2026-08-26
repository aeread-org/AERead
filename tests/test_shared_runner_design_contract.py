import hashlib
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
PYPROJECT = Path(__file__).parents[1] / "pyproject.toml"
SDK_V1_INIT = (
    Path(__file__).parents[1] / "src" / "aeread" / "sdk" / "v1" / "__init__.py"
)
FOUNDATION_PLAN = (
    Path(__file__).parents[1]
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-24-shared-runner-sdk-kernel.md"
)
REBASELINE_PLAN = (
    Path(__file__).parents[1]
    / "docs"
    / "superpowers"
    / "plans"
    / "2026-08-25-shared-runner-post-sync-rebaseline.md"
)

TASK_22_HEADING = "### Task 2.2: Add episode-scoped harness lifecycle"
TASK_23_HEADING = "### Task 2.3: Freeze whole-trial admission semantics without implementing a protocol"
TASK_32_HEADING = "### Task 3.2: Episode/session lifecycle coordinator"
TASK_33_HEADING = "### Task 3.3: Action-attempt executor"
STAGE5_HEADING = "## Stage 5 — native parity and external compatibility laboratory"
TASK_53_HEADING = "### Task 5.3: Five-source admission matrix"
TASK_54_HEADING = "### Task 5.4: tau3 canonical/reference adapter spike"
TASK_55_HEADING = "### Task 5.5: STATE rule/constraint adapter spike"
TASK_56_HEADING = "### Task 5.6: EconEvals objective adapter spike"
TASK_57_HEADING = "### Task 5.7: TERMS comparative fixture"
TASK_58_HEADING = "### Task 5.8: GDPval rater fixture"
MANDATORY_SPIKES_HEADING = "## Mandatory conformance spikes"
AUTHORITATIVE_HEADINGS = (
    TASK_22_HEADING,
    TASK_23_HEADING,
    TASK_32_HEADING,
    TASK_33_HEADING,
    STAGE5_HEADING,
    TASK_53_HEADING,
    TASK_54_HEADING,
    TASK_55_HEADING,
    TASK_56_HEADING,
    TASK_57_HEADING,
    TASK_58_HEADING,
    MANDATORY_SPIKES_HEADING,
)

TASK_22_SECTION_SHA256 = (
    "bc38fb28e40f8148acb15b867776807af6b3b46400f4d2f657d9034d76271917"
)
TASK_32_SECTION_SHA256 = (
    "edf21c87a62e4a57f40ea26b19b584cf0907e1112e3c7702c72293aa0c1bca7b"
)
STAGE5_SECTION_SHA256 = {
    TASK_54_HEADING: (
        "344063a54256f9a583931e195d5c6afc5ffb483a958a539b5211a1a8e052fc3f"
    ),
    TASK_55_HEADING: (
        "472f9a24ab06774beae55ff72079b2e84eda96aa3f713966595223ed9a7c56f6"
    ),
    TASK_56_HEADING: (
        "4332085f3e9db2dcda7c0a6dd29c47c22a5f62c9cafe940c1e88984360632693"
    ),
    TASK_57_HEADING: (
        "4ab695589186e813152888831da6c9b3d809188785ab1e481efff8cfff408a65"
    ),
    TASK_58_HEADING: (
        "60e2debd1ed40f0a4902ccd3963a71579676f7ababfa6efc1f152940c3abcc00"
    ),
}


def _has_unclosed_html_comment(line: str) -> bool:
    remainder = line
    while "<!--" in remainder:
        comment = remainder.split("<!--", 1)[1]
        if "-->" not in comment:
            return True
        remainder = comment.split("-->", 1)[1]
    return False


def _strict_authoritative_sections(text: str) -> dict[str, str]:
    lines = text.splitlines()
    visible_lines: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    in_html_comment = False
    for index, line in enumerate(lines):
        if fence is not None:
            fence_character, minimum_length = fence
            stripped = line.lstrip(" ")
            indentation = len(line) - len(stripped)
            marker_length = len(stripped) - len(stripped.lstrip(fence_character))
            if (
                indentation <= 3
                and marker_length >= minimum_length
                and not stripped[marker_length:].strip()
            ):
                fence = None
            continue

        if in_html_comment:
            closing = line.find("-->")
            if closing >= 0:
                in_html_comment = _has_unclosed_html_comment(line[closing + 3 :])
            continue

        stripped = line.lstrip(" ")
        indentation = len(line) - len(stripped)
        if indentation <= 3 and stripped[:1] in ("`", "~"):
            fence_character = stripped[0]
            marker_length = len(stripped) - len(stripped.lstrip(fence_character))
            suffix = stripped[marker_length:]
            if marker_length >= 3 and not (fence_character == "`" and "`" in suffix):
                fence = (fence_character, marker_length)
                continue

        if "<!--" in line:
            in_html_comment = _has_unclosed_html_comment(line)
            continue

        visible_lines.append((index, line))

    positions: dict[str, int] = {}
    for heading in AUTHORITATIVE_HEADINGS:
        candidates = [index for index, line in visible_lines if line == heading]
        assert (
            len(candidates) == 1
        ), f"expected one authoritative heading {heading!r}: {candidates!r}"
        positions[heading] = candidates[0]

    ordered_positions = tuple(positions[heading] for heading in AUTHORITATIVE_HEADINGS)
    assert ordered_positions == tuple(
        sorted(ordered_positions)
    ), f"authoritative headings are out of order: {ordered_positions!r}"

    section_boundaries = {
        TASK_22_HEADING: TASK_23_HEADING,
        TASK_32_HEADING: TASK_33_HEADING,
        STAGE5_HEADING: MANDATORY_SPIKES_HEADING,
        TASK_53_HEADING: TASK_54_HEADING,
        TASK_54_HEADING: TASK_55_HEADING,
        TASK_55_HEADING: TASK_56_HEADING,
        TASK_56_HEADING: TASK_57_HEADING,
        TASK_57_HEADING: TASK_58_HEADING,
        TASK_58_HEADING: MANDATORY_SPIKES_HEADING,
    }
    return {
        start: "\n".join(lines[positions[start] + 1 : positions[end]])
        for start, end in section_boundaries.items()
    }


def _assert_normalized_section_snapshot(section: str, expected_sha256: str) -> None:
    normalized = " ".join(section.split()).encode()
    assert hashlib.sha256(normalized).hexdigest() == expected_sha256


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


def _row_matches_contract(
    row: tuple[str, ...],
    *,
    verifier_class: str,
    workflow: str,
    benchmark: str,
    caveat: str,
) -> bool:
    return (
        len(row) == 4
        and verifier_class in row[0]
        and workflow in row[1]
        and benchmark in row[2]
        and caveat in row[3]
    )


def _markdown_list_item(text: str, marker: str) -> str:
    matches = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("- ") or marker not in line:
            continue
        parts = [line[2:].strip()]
        for continuation in lines[index + 1 :]:
            if continuation.startswith("- ") or not continuation.strip():
                break
            if not continuation.startswith("  "):
                break
            parts.append(continuation.strip())
        matches.append(" ".join(parts))
    assert len(matches) == 1, (
        f"expected one Markdown list item for {marker!r}: {matches!r}"
    )
    return matches[0]


def _assert_task_22_structural_ownership(section: str) -> None:
    normalized = " ".join(section.split())
    _assert_normalized_section_snapshot(section, TASK_22_SECTION_SHA256)
    role_lines = [
        line.strip()
        for line in section.splitlines()
        if line.strip().startswith("**Production lifecycle role:**")
    ]
    assert role_lines == [
        "**Production lifecycle role:** `contract_only`; Task 3.2 is the sole "
        "production owner."
    ]
    ownership_boundary = (
        "Task 2.2 declares only the wrapper's structural contract and a scripted "
        "conformance fake; it does not implement or execute the production wrapper"
    )
    assert ownership_boundary in normalized
    assert "Task 3.2 alone owns its production implementation and execution tests" in (
        normalized
    )
    assert "src/aeread/runner/lifecycle.py" not in section
    assert (
        "Task 2.2 implements the runner-owned stateless compatibility wrapper"
        not in normalized
    )


def _assert_task_32_production_ownership(section: str) -> None:
    normalized = " ".join(section.split())
    _assert_normalized_section_snapshot(section, TASK_32_SECTION_SHA256)
    role_lines = [
        line.strip()
        for line in section.splitlines()
        if line.strip().startswith("**Production lifecycle role:**")
    ]
    assert role_lines == [
        "**Production lifecycle role:** `production_owner`; Task 2.2 is "
        "contract-only."
    ]
    assert "Create `src/aeread/runner/lifecycle.py`" in section
    assert "implements the runner-owned stateless compatibility wrapper" in normalized


def _assert_stage5_evidence_directions(sections: dict[str, str]) -> None:
    expected = {
        TASK_54_HEADING: (
            "**Evidence direction:** `O0 (current) -> E0 (next) -> E1 (after E0 parity gate)`.",
        ),
        TASK_55_HEADING: (
            "**Evidence direction:** `O0 (current) -> E0 (next) -> E1 (after E0 parity gate)`.",
        ),
        TASK_56_HEADING: (
            "**Evidence direction:** `Scheduling O0 (current) -> Scheduling E0 (next) "
            "-> Scheduling E1 (after E0 parity gate)`; Procurement remains blocked.",
        ),
        TASK_57_HEADING: (
            "**Evidence direction:** `A0 (current) -> AERead-owned E0 (next) -> official "
            "E1 blocked` until upstream is admitted.",
        ),
        TASK_58_HEADING: (
            "**Evidence direction:** `A0 (current) -> canned provider-free E0 (next) -> "
            "official E1 blocked` until the official protocol is admitted.",
        ),
    }
    for heading, fragments in expected.items():
        section = sections[heading]
        _assert_normalized_section_snapshot(section, STAGE5_SECTION_SHA256[heading])
        expected_line = "".join(fragments)
        nonempty_lines = [line.strip() for line in section.splitlines() if line.strip()]
        direction_lines = [
            line
            for line in nonempty_lines
            if line.startswith("**Evidence direction:**")
        ]
        assert direction_lines == [expected_line]
        assert nonempty_lines[0] == expected_line
    assert "E3" not in " ".join(sections.values())


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
        "canonical/reference": (
            "retail refund",
            "tau3-bench",
            "primary deterministic database leaf",
        ),
        "rule/constraint/temporal": (
            "regulated refund process",
            "STATE-Bench",
            "final-state requirements are the official deterministic layer",
        ),
        "objective/optimum/bound": (
            "procurement and scheduling",
            "EconEvals",
            "empirical random-matching comparison baseline",
        ),
        "comparative": (
            "supplier price negotiation",
            "TERMS-Bench",
            "no E0 conformance or E1 adapter/parity result exists",
        ),
        "rater/judge": (
            "professional analyst deliverable",
            "GDPval",
            "occupational experts in blinded pairwise comparison",
        ),
        "simulation/statistical": (
            "inventory and pricing",
            "Vending-Bench",
            "official adapter parity is blocked",
        ),
        "integrity/admissibility": (
            "audited agent episode",
            "AERead EvaluationReceipt",
            "measurement_validity",
        ),
    }
    rows = {}
    for verifier_class, (workflow, benchmark, caveat) in examples.items():
        row = _markdown_table_row(
            text, f"**{verifier_class}**", expected_cells=4
        )
        rows[verifier_class] = row
        assert _row_matches_contract(
            row,
            verifier_class=verifier_class,
            workflow=workflow,
            benchmark=benchmark,
            caveat=caveat,
        ), f"mapping row does not bind its four fields: {row!r}"

    tau3_row = rows["canonical/reference"]
    state_row = rows["rule/constraint/temporal"]
    tau3_with_state_benchmark = (*tau3_row[:2], state_row[2], tau3_row[3])
    state_with_tau3_benchmark = (*state_row[:2], tau3_row[2], state_row[3])
    assert not _row_matches_contract(
        tau3_with_state_benchmark,
        verifier_class="canonical/reference",
        workflow="retail refund",
        benchmark="tau3-bench",
        caveat="primary deterministic database leaf",
    )
    assert not _row_matches_contract(
        state_with_tau3_benchmark,
        verifier_class="rule/constraint/temporal",
        workflow="regulated refund process",
        benchmark="STATE-Bench",
        caveat="final-state requirements are the official deterministic layer",
    )

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
        "customer_support/142-hard_compound_exchange_plus_late_compensation",
        "5 state requirements and 0 task requirements",
        "compiled into a versioned predicate over recorded trace evidence",
    )
    forbidden = (
        "all task requirements are deterministic",
        "all task requirements use the locked judge",
        "generic deterministic temporal scorer",
        "task 142:",
        "task 142 has",
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
            "public materials support a proposed AERead-owned TERMS-style fixture",
            "no E0 conformance or E1 adapter/parity result exists",
            "official simulator, defaults, and license",
            "official parity is blocked",
        ),
        forbidden=(
            "currently admitted",
            "E0 conformance is complete",
            "E1 adapter parity is complete",
            "official TERMS parity",
        ),
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
    item = _markdown_list_item(text, "Native `housing_v1`")
    required = (
        "`B` is the naive executable comparison baseline",
        "`L = 0` is a separate feasible lower-bound witness",
        "`U` is a full-information maximum-weight relaxation",
        "three typed references, not one oracle score",
    )
    assert all(fragment in item for fragment in required)

    relocated = text.replace(required[0], "`B` is declared elsewhere", 1)
    relocated += f"\n- Unrelated benchmark: {required[0]}.\n"
    assert required[0] in relocated
    relocated_item = _markdown_list_item(relocated, "Native `housing_v1`")
    assert not all(fragment in relocated_item for fragment in required)

    wrong_owner = item.replace(
        required[0], "`U` is the naive executable comparison baseline"
    )
    assert not all(fragment in wrong_owner for fragment in required)


def test_public_sdk_stability_policy_preserves_existing_v1_exports() -> None:
    text = PUBLIC_ENVIRONMENT_SPEC.read_text(encoding="utf-8")
    section = text.split("### 3.1 Package and version policy", 1)[1].split(
        "### 3.2 Environment contract", 1
    )[0]
    normalized = " ".join(section.split())

    required = (
        "AERead already declares package version `0.1.0`",
        "`aeread.sdk.v1` is the current stable authoring namespace",
        "`CallAttemptStart` and `CallAttemptToken` remain stable compatibility exports",
        "Task 2.1a may deprecate them but must not remove, repurpose, or change",
        "breaking removal or incompatible serialized change requires `aeread.sdk.v2`",
    )
    assert all(fragment in normalized for fragment in required)
    assert 'version = "0.1.0"' in PYPROJECT.read_text(encoding="utf-8")

    sdk_text = SDK_V1_INIT.read_text(encoding="utf-8")
    assert '"""Stable v1 environment-authoring API for AERead."""' in sdk_text
    assert '"CallAttemptStart"' in sdk_text
    assert '"CallAttemptToken"' in sdk_text

    foundation = FOUNDATION_PLAN.read_text(encoding="utf-8").split(
        "## Global Constraints", 1
    )[1].split("## Execution workflow", 1)[0]
    rebaseline = REBASELINE_PLAN.read_text(encoding="utf-8").split(
        "### Task 2.1a: Add precise action/call/tool evidence vocabulary", 1
    )[1].split("### Task 2.1b", 1)[0]
    roadmap = RUNNER_ARCHITECTURE.read_text(encoding="utf-8").split(
        "### 3. Execution objects", 1
    )[1].split("### 4. Evidence objects", 1)[0]
    design = DESIGN.read_text(encoding="utf-8").split(
        "class AttemptObserver(Protocol):", 1
    )[1].split("The public executable names", 1)[0]
    required_compatibility = (
        "existing `CallAttemptStart` and `CallAttemptToken` remain"
    )
    for authority in (foundation, rebaseline, roadmap, design):
        authority_normalized = " ".join(authority.split())
        assert (
            required_compatibility in authority_normalized
        )
        assert "not compatibility exports" not in authority_normalized
        assert "does not create a compatibility promise" not in authority_normalized

        relocated = authority_normalized.replace(
            required_compatibility, "compatibility is declared elsewhere", 1
        )
        relocated += f" Outside this authority: {required_compatibility}."
        assert required_compatibility not in relocated.split(" Outside this authority:", 1)[0]


def test_rebaseline_status_names_current_integration_and_next_gate() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    status = text.split("## Objective", 1)[0]
    task_02 = text.split(
        "### Task 0.2: Integrate the latest approved PR #7 design", 1
    )[1].split("### Task 0.3", 1)[0]
    dispatch = text.split("## Current dispatch gate", 1)[1]

    for section in (status, task_02, dispatch):
        normalized = " ".join(
            line.removeprefix("> ").strip() for line in section.splitlines()
        )
        assert "`155d8fc`" in normalized
        assert "`b5239cd`" in normalized
        assert "`c7aca60`" in normalized
        assert (
            "last independently clean implementation baseline is `a7ddbb2`"
            in normalized
        )
        assert (
            "review-candidate chain is `2654b2d` -> `011475f` -> the current "
            "corrective follow-up" in normalized
        )
        assert "not independently clean until its fresh review closes" in normalized
        assert "Task 1.1a1" in normalized
        assert "Task 1.1a2" in normalized
        assert "Task 1.1b" in normalized
    assert "Task 1.1a and all later plan work remain blocked" not in dispatch
    assert "Task 1.1a2 is the next" not in text
    assert "with independent review pending" not in text

    roadmap = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")
    assert "PR #7 at `155d8fc`" in roadmap
    assert "integrated locally at `b5239cd`" in roadmap


def test_existing_attempt_observer_and_agent_adapter_signatures_remain_stable() -> None:
    public_section = PUBLIC_ENVIRONMENT_SPEC.read_text(encoding="utf-8").split(
        "### 3.3 Observation and canonical response boundary", 1
    )[1].split("### 3.4 Verifier contract", 1)[0]
    rebaseline_section = REBASELINE_PLAN.read_text(encoding="utf-8").split(
        "### Task 2.1a: Add precise action/call/tool evidence vocabulary", 1
    )[1].split("### Task 2.1b", 1)[0]
    design_section = DESIGN.read_text(encoding="utf-8").split(
        "class AttemptObserver(Protocol):", 1
    )[1].split("The public executable names", 1)[0]
    roadmap_section = RUNNER_ARCHITECTURE.read_text(encoding="utf-8").split(
        "### 3. Execution objects", 1
    )[1].split("### 4. Evidence objects", 1)[0]
    foundation_section = FOUNDATION_PLAN.read_text(encoding="utf-8").split(
        "## Global Constraints", 1
    )[1].split("## Execution workflow", 1)[0]

    required = (
        "existing `AttemptObserver.call_started`, `call_succeeded`, and `call_failed` "
        "signatures remain stable",
        "existing `AgentAdapter.act(..., attempts: AttemptObserver)` signature remains stable",
        "translates those callbacks into the additive `ProviderCall*` evidence records",
    )
    for authority in (
        public_section,
        rebaseline_section,
        design_section,
        roadmap_section,
        foundation_section,
    ):
        normalized = " ".join(authority.split())
        assert all(fragment in normalized for fragment in required)
        assert "observer signatures must not use" not in normalized

        relocated = normalized.replace(
            required[0], "stable observer methods are declared elsewhere", 1
        )
        relocated += f" Outside this authority: {required[0]}."
        local_section = relocated.split(" Outside this authority:", 1)[0]
        assert not all(fragment in local_section for fragment in required)


def test_future_lifecycle_contract_is_additive_to_stable_agent_adapter() -> None:
    authoritative_sections = _strict_authoritative_sections(
        REBASELINE_PLAN.read_text(encoding="utf-8")
    )
    public_section = PUBLIC_ENVIRONMENT_SPEC.read_text(encoding="utf-8").split(
        "### 3.3 Observation and canonical response boundary", 1
    )[1].split("### 3.4 Verifier contract", 1)[0]
    rebaseline_section = authoritative_sections[TASK_22_HEADING]
    lifecycle_runtime_section = authoritative_sections[TASK_32_HEADING]
    design_section = DESIGN.read_text(encoding="utf-8").split(
        "class AttemptObserver(Protocol):", 1
    )[1].split("The public executable names", 1)[0]
    roadmap_section = RUNNER_ARCHITECTURE.read_text(encoding="utf-8").split(
        "### 3. Execution objects", 1
    )[1].split("### 4. Evidence objects", 1)[0]
    foundation_section = FOUNDATION_PLAN.read_text(encoding="utf-8").split(
        "## Global Constraints", 1
    )[1].split("## Execution workflow", 1)[0]

    required = (
        "`AgentAdapter` remains the stable act-only v1 Protocol",
        "`LifecycleAgentAdapter` is a separately named additive Protocol",
        "runner-owned stateless compatibility wrapper",
        "must not add required lifecycle methods to `AgentAdapter`",
    )
    for authority in (
        public_section,
        rebaseline_section,
        design_section,
        roadmap_section,
        foundation_section,
    ):
        normalized = " ".join(authority.split())
        assert all(fragment in normalized for fragment in required)

        relocated = normalized.replace(
            required[0], "stable adapter compatibility is declared elsewhere", 1
        )
        relocated += f" Outside this authority: {required[0]}."
        local_section = relocated.split(" Outside this authority:", 1)[0]
        assert not all(fragment in local_section for fragment in required)

    assert "LifecycleAgentAdapter.setup" in rebaseline_section
    assert "LifecycleAgentAdapter.open_session" in rebaseline_section
    assert "LifecycleAgentAdapter.cleanup" in rebaseline_section
    for legacy_lifecycle_call in (
        "-> AgentAdapter.setup",
        "-> AgentAdapter.open_session",
        "-> AgentAdapter.cleanup",
    ):
        assert legacy_lifecycle_call not in rebaseline_section
    assert "execute through the stateless wrapper after this task lands" not in (
        rebaseline_section
    )
    normalized_rebaseline = " ".join(rebaseline_section.split())
    assert "structural conformance" in normalized_rebaseline
    ownership_boundary = (
        "Task 2.2 declares only the wrapper's structural contract and a scripted "
        "conformance fake; it does not implement or execute the production wrapper"
    )
    _assert_task_22_structural_ownership(rebaseline_section)
    _assert_task_32_production_ownership(lifecycle_runtime_section)

    implementation_mutation = normalized_rebaseline.replace(
        ownership_boundary,
        "Task 2.2 implements the runner-owned stateless compatibility wrapper",
        1,
    )
    try:
        _assert_task_22_structural_ownership(implementation_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("implementation-ownership mutation escaped the guard")
    file_mutation = rebaseline_section.replace(
        "- Create `tests/shared_runner/test_agent_lifecycle_contract.py`.",
        "- Create `src/aeread/runner/lifecycle.py`.\n"
        "- Create `tests/shared_runner/test_agent_lifecycle_contract.py`.",
        1,
    )
    try:
        _assert_task_22_structural_ownership(file_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("Task 2.2 runtime-file mutation escaped the guard")
    outside_files_path_mutation = (
        rebaseline_section
        + "\nTask 2.2 also creates `src/aeread/runner/lifecycle.py` in production.\n"
    )
    try:
        _assert_task_22_structural_ownership(outside_files_path_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("Task 2.2 path outside Files escaped the guard")
    paraphrase_mutation = (
        rebaseline_section
        + "\nTask 2.2 also owns the production stateless compatibility wrapper.\n"
    )
    try:
        _assert_task_22_structural_ownership(paraphrase_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("Task 2.2 ownership paraphrase escaped the guard")
    runtime_role_mutation = lifecycle_runtime_section.replace(
        "`production_owner`; Task 2.2 is contract-only",
        "`contract_only`; Task 2.2 is contract-only",
        1,
    )
    try:
        _assert_task_32_production_ownership(runtime_role_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("Task 3.2 production-owner mutation escaped the guard")
    reviewer_ownership_mutants = {
        "passive implementation": (
            rebaseline_section
            + "\nThe production wrapper is implemented by this task.\n"
        ),
        "shared execution owner": (
            rebaseline_section
            + "\nProduction execution ownership is shared with Task 2.2.\n"
        ),
        "dot path": (
            rebaseline_section
            + "\nCreate `src/aeread/runner/./lifecycle.py` in this task.\n"
        ),
        "short path": (
            rebaseline_section + "\nCreate `runner/lifecycle.py` in this task.\n"
        ),
    }
    for label, mutant in reviewer_ownership_mutants.items():
        try:
            _assert_task_22_structural_ownership(mutant)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"reviewer {label} mutant escaped the guard")
    second_owner_mutation = (
        lifecycle_runtime_section
        + "\nProduction execution ownership is shared with Task 2.2.\n"
    )
    try:
        _assert_task_32_production_ownership(second_owner_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("Task 3.2 second-owner mutant escaped the guard")
    normalized_runtime = " ".join(lifecycle_runtime_section.split())
    assert "act-only v1 adapter" in normalized_runtime


def test_stage5_dispatch_matches_the_locked_five_benchmark_crosswalk() -> None:
    plan = REBASELINE_PLAN.read_text(encoding="utf-8")
    authoritative_sections = _strict_authoritative_sections(plan)
    stage5 = authoritative_sections[STAGE5_HEADING]

    expected_tasks = {
        TASK_53_HEADING: (
            "tau3",
            "STATE-Bench",
            "EconEvals",
            "TERMS-Bench",
            "GDPval",
        ),
        TASK_54_HEADING: (),
        TASK_55_HEADING: (),
        TASK_56_HEADING: (
            "Scheduling",
            "Procurement",
        ),
        TASK_57_HEADING: (),
        TASK_58_HEADING: (),
    }
    headings = tuple(expected_tasks)
    sections: dict[str, str] = {}
    for heading in headings:
        section = authoritative_sections[heading]
        normalized_section = " ".join(section.split())
        sections[heading] = section
        assert all(
            fragment in normalized_section for fragment in expected_tasks[heading]
        )

    for stale_dispatch in ("FinanceBench", "AucArena", "Market-Bench"):
        assert stale_dispatch not in stage5
    _assert_stage5_evidence_directions(sections)

    tau3_heading = TASK_54_HEADING
    tau3_direction = "**Evidence direction:** `O0 (current) -> E0 (next) -> E1 (after E0 parity gate)`."
    tau3_swap_mutation = dict(sections)
    tau3_swap_mutation[tau3_heading] = tau3_swap_mutation[tau3_heading].replace(
        tau3_direction,
        "**Evidence direction:** `E1 (current) -> E0 (next) -> O0 (after E0 parity gate)`.",
        1,
    )
    try:
        _assert_stage5_evidence_directions(tau3_swap_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("tau3 O0/E1 direction swap escaped the guard")

    contrary_current_mutation = dict(sections)
    contrary_current_mutation[tau3_heading] += "\n**Current evidence:** E1.\n"
    try:
        _assert_stage5_evidence_directions(contrary_current_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("contrary current-evidence claim escaped the guard")

    relocated_history_mutation = dict(sections)
    relocated_history_mutation[tau3_heading] = relocated_history_mutation[
        tau3_heading
    ].replace(
        tau3_direction,
        f"Historical claim, retained only as a rejected example.\n\n{tau3_direction}",
        1,
    )
    try:
        _assert_stage5_evidence_directions(relocated_history_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("historical evidence relocation escaped the guard")

    duplicate_direction_mutation = dict(sections)
    duplicate_direction_mutation[
        tau3_heading
    ] += "\n**Evidence direction:** `E1 (current) -> E0 (next) -> O0 (blocked)`.\n"
    try:
        _assert_stage5_evidence_directions(duplicate_direction_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("duplicate evidence direction escaped the guard")

    reviewer_status_mutants = {
        "historical preceding direction": (
            sections[tau3_heading]
            + "\nThe preceding direction is historical; tau3 has reached E1 today.\n"
        ),
        "current direction": (
            sections[tau3_heading]
            + "\n**Current direction:** `E1 today; O0 is historical`.\n"
        ),
        "as-of-plan status": (
            sections[tau3_heading] + "\nAs of this plan, tau3 is at E1.\n"
        ),
    }
    for label, mutant in reviewer_status_mutants.items():
        mutated_sections = dict(sections)
        mutated_sections[tau3_heading] = mutant
        try:
            _assert_stage5_evidence_directions(mutated_sections)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"reviewer {label} mutant escaped the guard")

    econ_heading = TASK_56_HEADING
    econ_e3_mutation = dict(sections)
    econ_e3_mutation[econ_heading] = econ_e3_mutation[econ_heading].replace(
        "Scheduling E1", "Scheduling E3", 1
    )
    try:
        _assert_stage5_evidence_directions(econ_e3_mutation)
    except AssertionError:
        pass
    else:
        raise AssertionError("EconEvals E3 mutation escaped the guard")


def test_authoritative_heading_code_block_mutant_is_rejected() -> None:
    plan = REBASELINE_PLAN.read_text(encoding="utf-8")
    headings = AUTHORITATIVE_HEADINGS
    mutated = "\n".join(
        f"    {line}" if line in headings else line for line in plan.splitlines()
    )
    task_22 = mutated.split(headings[0], 1)[1].split(headings[1], 1)[0]
    task_32 = mutated.split(headings[2], 1)[1].split(headings[3], 1)[0]
    stage5 = mutated.split(headings[4], 1)[1].split(headings[-1], 1)[0]
    stage5_sections = {}
    for index, heading in enumerate(headings[6:11]):
        section = stage5.split(heading, 1)[1]
        if index + 1 < len(headings[6:11]):
            section = section.split(headings[6:11][index + 1], 1)[0]
        stage5_sections[heading] = section

    _assert_task_22_structural_ownership(task_22)
    _assert_task_32_production_ownership(task_32)
    _assert_stage5_evidence_directions(stage5_sections)
    try:
        _strict_authoritative_sections(mutated)
    except AssertionError:
        pass
    else:
        raise AssertionError("indented authoritative headings escaped the guard")


def test_authoritative_heading_parser_rejects_duplicates_and_relocation() -> None:
    plan = REBASELINE_PLAN.read_text(encoding="utf-8")
    duplicate = plan + f"\n{TASK_54_HEADING}\n"
    relocated = "\n".join(
        (
            TASK_55_HEADING
            if line == TASK_54_HEADING
            else TASK_54_HEADING if line == TASK_55_HEADING else line
        )
        for line in plan.splitlines()
    )

    for label, mutant in (("duplicate", duplicate), ("relocated", relocated)):
        try:
            _strict_authoritative_sections(mutant)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"{label} authoritative heading escaped the guard")


def test_authoritative_heading_parser_rejects_fenced_authority() -> None:
    plan = REBASELINE_PLAN.read_text(encoding="utf-8")
    fenced_mutants = {
        "four-backtick fence": f"````markdown\n{plan}\n````\n",
        "five-tilde fence": f"~~~~~\n{plan}\n~~~~~\n",
        "short closing fence": f"````\n```\n{plan}\n````\n",
    }

    for label, mutant in fenced_mutants.items():
        try:
            _strict_authoritative_sections(mutant)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"{label} authority escaped the guard")


def test_authoritative_heading_parser_rejects_commented_authority() -> None:
    plan = REBASELINE_PLAN.read_text(encoding="utf-8")
    commented = f"<!--\n{plan}\n-->\n"

    try:
        _strict_authoritative_sections(commented)
    except AssertionError:
        pass
    else:
        raise AssertionError("commented authoritative sections escaped the guard")


def test_authoritative_heading_parser_ignores_non_authority_contexts() -> None:
    plan = REBASELINE_PLAN.read_text(encoding="utf-8")
    hidden_duplicate = f"\n<!--\n{TASK_54_HEADING}\n-->\n"
    closed_fence_before_plan = f"```\ndecoy\n````\n{plan}"
    single_line_comment_before_plan = f"<!-- historical only -->\n{plan}"

    _strict_authoritative_sections(plan + hidden_duplicate)
    _strict_authoritative_sections(closed_fence_before_plan)
    _strict_authoritative_sections(single_line_comment_before_plan)


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
    assert "Target vocabulary only; field-level Python contract is not frozen" in section
    assert "ProviderCallStart" in section
    assert "ProviderCallToken" in section
    assert "versioned discriminated parent" in section
    for parent_kind in ("action_attempt", "rater_attempt", "lifecycle_operation"):
        assert f"`{parent_kind}`" in section
    assert "class ProviderCallStart" not in section
    assert "class ProviderCallToken" not in section
    assert "provider_call_id: str" not in section
    assert "def call_started(self, start: CallAttemptStart)" in section
    assert "def call_succeeded(" in section
    assert "def call_failed(" in section
    assert "attempts.call_started()" not in section
    assert (
        "existing `CallAttemptStart` and `CallAttemptToken` remain stable "
        "compatibility exports"
        in normalized_section
    )
    assert "may deprecate" in normalized_section
    assert "may not remove or repurpose" in normalized_section
    assert "Task 2.1a" in section

    design = DESIGN.read_text(encoding="utf-8")
    roadmap = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")
    for text in (design, roadmap):
        normalized_text = " ".join(text.split())
        assert (
            "ProviderCall target vocabulary is not a frozen field contract"
            in normalized_text
        )
        assert (
            "existing `CallAttemptStart` and `CallAttemptToken` remain stable "
            "compatibility exports"
            in normalized_text
        )
        assert "cannot remove or repurpose them in v1" in normalized_text
        assert "Task 2.1a" in normalized_text


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
