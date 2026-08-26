import hashlib
import re
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
        "04be39ca00605b8ecaa978121b7a6cc9109fde821ae320b4edcc104d1900773c"
    ),
    TASK_58_HEADING: (
        "c2a489198e78aff21b0488018fa5102419d4875862d8ae8b852c1f6533db8061"
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
            "**Evidence direction:** `public-material survey (current) -> official A0 "
            "blocked -> AERead-owned synthetic E0 pending -> official E1 blocked`.",
        ),
        TASK_58_HEADING: (
            "**Evidence direction:** `public-material source/rater survey (current) -> "
            "A0 blocked -> canned provider-free E0 pending -> official E1 blocked`.",
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


def _assert_rebaseline_status_names_current_integration_and_next_gate(
    text: str,
) -> None:
    breaker_baseline = "cd26e7202e0933c57169771d6f4500188407a40f"
    b4a_baseline = "b6632d5df7516aa598655f59b7992e9d1157908d"
    brief_digest = "13371f845ba1a34b0caa82dfca409f0558e0a3556313b13c39794bb56d231648"
    design_digest = "4e570d793c350d15e6857aaca87addd14bcd5afff7d70b4db75835e5d49bd879"
    correction_digest = (
        "713a0c97e5d4b54afa28cbe940fc075c6265844e6e84209a2c06c84fbd30a104"
    )
    b3b_brief_digest = (
        "857a6bc92b9d9e07217616476630aba737725e3afbfd3c3d809bd1e404b3a3d9"
    )
    b4b_brief_digest = (
        "e6254d82df966d3789e6e39d3443288a8f52b20f692f4869d83de39c4ebb0b3f"
    )
    b4b_production = "da0c5a5"
    b4b_clean_head = "45bbe8b"
    b5_brief = "20260826_task1_1b5_analysis_plan_authoring_dispatch_codex.md"
    b5_brief_digest = "36e64d137b0232dd483c399935897d4451d45ded34e93be953157a7e45cf4568"
    b3b_production = "c654863c479769a78802530821ca82f9607e068c"
    b3b_clean_head = "99312082d6f8a59ad5723f6e0f6563507fe6a080"
    status = text.split("## Objective", 1)[0]
    task_02 = text.split("### Task 0.2: Integrate the latest approved PR #7 design", 1)[
        1
    ].split("### Task 0.3", 1)[0]
    headings = (
        "### Task 1.1b1:",
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations",
        "### Task 1.1b3: Execution-design authoring and episode-attempt policy",
        "### Task 1.1b3b: Execution-assignment overlay authoring",
        "### Task 1.1b4: Analysis primitives",
        "### Task 1.1b5: AnalysisPlan envelope, DAG, and declaration-only composition",
        "### Task 1.1c: Atomic three-layer resolution and schema migration",
        "### Task 1.2:",
        "## Stage 2",
    )
    assert all(text.count(heading) == 1 for heading in headings)
    assert [text.index(heading) for heading in headings] == sorted(
        text.index(heading) for heading in headings
    )
    task_1b = text.split("### Task 1.1b1:", 1)[1].split(headings[1], 1)[0]
    assert text.count("## Current dispatch gate") == 1
    b1_markers = (
        "**Dependency:**",
        "**Binding implementation authority:**",
        "**Files:**",
        "**Exact additive public names (11):**",
        "**Ownership:**",
        "**Deferred:**",
        "**RED/GREEN and stop conditions:**",
        "**Output:**",
    )
    assert all(task_1b.count(marker) == 1 for marker in b1_markers)
    marker_positions = [task_1b.index(marker) for marker in b1_markers]
    assert marker_positions == sorted(marker_positions)
    b1_subblocks = {
        marker: task_1b[start:end]
        for marker, start, end in zip(
            b1_markers,
            marker_positions,
            (*marker_positions[1:], len(task_1b)),
        )
    }
    task_1b2 = text.split(headings[1], 1)[1].split(headings[2], 1)[0]
    task_1b3 = text.split(headings[2], 1)[1].split(headings[3], 1)[0]
    task_1b3b = text.split(headings[3], 1)[1].split(headings[4], 1)[0]
    task_1b4 = text.split(headings[4], 1)[1].split(headings[5], 1)[0]
    task_1b5 = text.split(headings[5], 1)[1].split(headings[6], 1)[0]
    task_1c = text.split(headings[6], 1)[1].split("### Task 1.2:", 1)[0]
    three_layer_sections = (
        task_1b2,
        task_1b3,
        task_1b3b,
        task_1b4,
        task_1b5,
        task_1c,
    )
    three_layer_section_sha256 = (
        "53c0bcddcc6dadff455feef4b0de419adf3de30aeaaa9b1f8ffb61e211400a04",
        "1a1c9e0a2eded8549623555f946591322d9539408624140ea9ca0a7b14afbe0d",
        "8c8b20f5ff66ea0983b70ec46a651ce4951d80ad85b7ddbd55c4f75e890108c3",
        "037a98ec61af0d236671d328d0c7dab70baa4563d9ab2f7b61f0e45d15c8898c",
        "ed42aae9ba73f63c6a4405cf66f8a1762338f29de919cd35c0c940afd7773dcf",
        "2f43744bebba1826dfc15bc9e6b0ac97f674fad8ff5669e5066f4a440ea13455",
    )
    for section, expected_sha256 in zip(
        three_layer_sections, three_layer_section_sha256, strict=True
    ):
        _assert_normalized_section_snapshot(section, expected_sha256)
    task_12 = text.split("### Task 1.2:", 1)[1].split("## Stage 2", 1)[0]
    stage_2_preamble = text.split("## Stage 2", 1)[1].split("### Task 2.1a:", 1)[0]
    terms = text.split(TASK_57_HEADING, 1)[1].split(TASK_58_HEADING, 1)[0]
    gdpval = text.split(TASK_58_HEADING, 1)[1].split(MANDATORY_SPIKES_HEADING, 1)[0]
    dispatch = text.split("## Current dispatch gate", 1)[1]

    gate_sections = (status, task_02, dispatch)
    gate_section_sha256 = (
        "b55b0df9cb62ca538cb6eff78ad2b920a2b5ed804456a8b883bad17e55b0bc52",
        "7521ac386398274ebd85812be5b691daabbac3a54d63d6c60b405fe91c1f7a34",
        "aa5eecb3ef837527478f9ea47dc31fddbb1daf9befb83c90f101a8be9cec4c48",
    )
    for section, expected_sha256 in zip(
        gate_sections, gate_section_sha256, strict=True
    ):
        normalized = " ".join(
            line.removeprefix("> ").strip() for line in section.splitlines()
        )
        assert hashlib.sha256(normalized.encode()).hexdigest() == expected_sha256
        assert f"`{breaker_baseline}`" in normalized
        assert "PR #7 is NOT independently CLEAN" in normalized
        assert f"`{b4a_baseline}`" in normalized
        assert "Task 1.1b4a is independently CLEAN" in normalized
        assert correction_digest in normalized
        assert b3b_brief_digest in normalized
        assert f"`{b3b_production}`" in normalized
        assert f"`{b3b_clean_head}`" in normalized
        assert "Task 1.1b3b is independently CLEAN" in normalized
        assert b4b_brief_digest in normalized
        assert "Task 1.1b4b brief is independently CLEAN" in normalized
        assert b4b_production in normalized
        assert b4b_clean_head in normalized
        assert "Task 1.1b4b is independently CLEAN" in normalized
        assert b5_brief in normalized
        assert b5_brief_digest in normalized
        assert "Task 1.1b5 brief is independently CLEAN" in normalized
        assert "Task 1.1b5 code is the sole next dispatch" in normalized
        assert "sole next dispatch" in normalized
        assert "Task 1.1c" in normalized
        assert "blocked" in normalized

    dependency = b1_subblocks["**Dependency:**"]
    authority = b1_subblocks["**Binding implementation authority:**"]
    inventory = b1_subblocks["**Exact additive public names (11):**"]
    ownership = b1_subblocks["**Ownership:**"]

    assert f"`{breaker_baseline}`" in dependency
    assert "PR #7 is NOT independently CLEAN" in dependency
    assert (
        "compiled-core regression-guard finding is Task 2.1a's mandatory first RED"
        in (dependency)
    )
    assert (
        "`Aug 22 Sync/20260825_task1_1b1_planned_identity_dispatch_codex.md`"
        in authority
    )
    assert brief_digest in authority
    assert brief_digest in dispatch
    assert design_digest in task_1b2
    assert (
        "`Aug 22 Sync/20260826_three_layer_measurement_execution_analysis_design_codex.md`"
        in task_1b2
    )
    assert tuple(re.findall(r"`([A-Za-z]+)`", inventory)) == (
        "ClusterDesignSpec",
        "ClusterMembershipSpec",
        "EpisodeReplicationDesign",
        "FixedPanelDesignSpec",
        "PairingSpec",
        "PanelDesignSpec",
        "PlannedCoordinateField",
        "SampledPanelDesignSpec",
        "SamplingPopulationSpec",
        "SeededEpisodeReplicationDesign",
        "UnseededEpisodeReplicationDesign",
    )
    assert ownership.startswith(
        "**Ownership:** strict pre-run identities for a finite declared population"
    )
    assert "measurement_sha256" in task_1b2
    assert "evaluation_instrument_sha256" in task_1b2
    assert "planned judgment" in task_1b3
    assert "realized `EvaluationWork`" in " ".join(task_1b3.split())
    assert "transition_outcome_unknown" in task_1b3
    assert "quarantine" in task_1b3
    assert correction_digest in task_1b3b
    assert b3b_brief_digest in task_1b3b
    assert f"`{b3b_production}`" in task_1b3b
    assert f"`{b3b_clean_head}`" in task_1b3b
    assert "independently CLEAN" in task_1b3b
    assert "execution-assignment authoring only" in task_1b3b
    assert "analysis_authoring_sha256" in task_1b4
    assert "ignorability" in task_1b4
    assert b4b_brief_digest in task_1b4
    normalized_b4 = " ".join(task_1b4.split())
    assert "Task 1.1b4b brief is independently CLEAN" in normalized_b4
    assert b4b_production in normalized_b4
    assert b4b_clean_head in normalized_b4
    assert "Task 1.1b4b is independently CLEAN" in normalized_b4
    normalized_b5 = " ".join(task_1b5.split())
    assert b4b_production in normalized_b5
    assert b4b_clean_head in normalized_b5
    assert b5_brief in normalized_b5
    assert b5_brief_digest in normalized_b5
    assert "Task 1.1b5 brief is independently CLEAN" in normalized_b5
    assert "Task 1.1b5 code is the sole next dispatch" in normalized_b5
    assert "analysis_plan_sha256" in task_1b5
    assert "composition_sha256" in task_1b5
    assert "SuiteExecutionProjection" in task_1c
    assert "`suite` and `suite_sha256`" in task_1c
    assert "AnalysisPlanRegistration" in task_1c
    assert "AttemptSelectionProof" in task_1c
    assert "AnalysisRecord" in task_1c
    assert "freezes no final public record names" in " ".join(
        " ".join(section.split())
        for section in (task_1b2, task_1b3, task_1b3b, task_1b4, task_1b5)
    )
    assert "**Dependency:** Task 1.1c is independently clean." in task_12
    assert "**Current gate:** blocked." in task_12
    assert "Task 1.1c is not independently complete" in task_12
    assert (
        "Task 1.1b1 constructor-pressure tests are schema prerequisites and do not "
        "satisfy Task 1.2." in " ".join(task_12.split())
    )
    normalized_stage_2 = " ".join(
        line.removeprefix("> ").strip() for line in stage_2_preamble.splitlines()
    )
    assert "Dependency inheritance" in normalized_stage_2
    assert (
        "every Stage 2–5 dependency on Task 1.1c remains blocked until Task 1.1c is independently CLEAN"
        in normalized_stage_2
    )
    assert (
        "Implementers may not use those references to backfill unresolved schema"
        in normalized_stage_2
    )
    assert (
        "Task 2.1a's mandatory first RED is the one parked compiled-core regression-guard finding"
        in normalized_stage_2
    )
    for gate_section in (status, task_02, dispatch):
        assert "pr #7 is independently clean" not in gate_section.casefold()
    assert "pr #7 is independently clean" not in task_1b.casefold()

    for gated_section in (
        task_1b2,
        task_1b3,
        task_1b3b,
        task_1b4,
        task_1b5,
        task_1c,
    ):
        assert "is dispatchable for implementation" not in gated_section.casefold()
    assert "may backfill unresolved schema" not in stage_2_preamble.casefold()
    assert "public-material source survey" in terms
    assert "official a0 is blocked" in terms.casefold()
    assert "A0 (current)" not in terms
    assert "public-material source and rater survey" in gdpval
    assert "a0 is blocked" in gdpval.casefold()
    assert "A0 (current)" not in gdpval

    gates = " ".join((status, task_02, dispatch))
    for stale in (
        "review-candidate chain",
        "current corrective follow-up",
        "not independently clean until its fresh review closes",
        "Task 1.1b is the next bounded",
        "Task 1.1b is next only after",
        "<PR7_INDEPENDENTLY_CLEAN_HEAD>",
    ):
        assert stale not in gates

    assert "Task 1.1a and all later plan work remain blocked" not in dispatch
    assert "Task 1.1a2 is the next" not in text
    assert "with independent review pending" not in text

    roadmap = RUNNER_ARCHITECTURE.read_text(encoding="utf-8")
    assert "PR #7 at `155d8fc`" in roadmap
    assert "integrated locally at `b5239cd`" in roadmap


def test_rebaseline_status_names_current_integration_and_next_gate() -> None:
    _assert_rebaseline_status_names_current_integration_and_next_gate(
        REBASELINE_PLAN.read_text(encoding="utf-8")
    )


def _assert_rebaseline_mutation_is_rejected(mutated: str) -> None:
    try:
        _assert_rebaseline_status_names_current_integration_and_next_gate(mutated)
    except AssertionError:
        return
    raise AssertionError("authority guard accepted a forbidden rebaseline mutation")


ASSIGNMENT_AUTHORITY_HEADINGS = (
    "### Task 1.1b3: Execution-design authoring and episode-attempt policy",
    "### Task 1.1b3b: Execution-assignment overlay authoring",
    "### Task 1.1b4: Analysis primitives",
    "### Task 1.1b5: AnalysisPlan envelope, DAG, and declaration-only composition",
    "### Task 1.1c: Atomic three-layer resolution and schema migration",
    "### Task 1.2: Add five provider-free measurement fixtures",
    "### Task 3.12: Pure post-receipt analysis and composition",
    "## Stage 4 — provider-free conformance",
    "## Current dispatch gate",
)


def _assignment_authority_sections(text: str) -> dict[str, str]:
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
    for heading in ASSIGNMENT_AUTHORITY_HEADINGS:
        assert text.count(heading) == 1, f"non-unique assignment heading: {heading}"
        raw_matches = [index for index, line in enumerate(lines) if line == heading]
        assert (
            len(raw_matches) == 1
        ), f"assignment heading is not column-zero: {heading}"
        matches = [index for index, line in visible_lines if line == heading]
        assert matches == raw_matches, f"assignment heading is hidden: {heading}"
        positions[heading] = matches[0]
    ordered = tuple(positions[heading] for heading in ASSIGNMENT_AUTHORITY_HEADINGS)
    assert ordered == tuple(
        sorted(ordered)
    ), "assignment authority headings are reordered"

    boundaries = {
        ASSIGNMENT_AUTHORITY_HEADINGS[0]: ASSIGNMENT_AUTHORITY_HEADINGS[1],
        ASSIGNMENT_AUTHORITY_HEADINGS[1]: ASSIGNMENT_AUTHORITY_HEADINGS[2],
        ASSIGNMENT_AUTHORITY_HEADINGS[2]: ASSIGNMENT_AUTHORITY_HEADINGS[3],
        ASSIGNMENT_AUTHORITY_HEADINGS[3]: ASSIGNMENT_AUTHORITY_HEADINGS[4],
        ASSIGNMENT_AUTHORITY_HEADINGS[4]: ASSIGNMENT_AUTHORITY_HEADINGS[5],
        ASSIGNMENT_AUTHORITY_HEADINGS[6]: ASSIGNMENT_AUTHORITY_HEADINGS[7],
    }
    sections = {
        start: "\n".join(lines[positions[start] + 1 : positions[end]])
        for start, end in boundaries.items()
    }
    sections[ASSIGNMENT_AUTHORITY_HEADINGS[8]] = "\n".join(
        lines[positions[ASSIGNMENT_AUTHORITY_HEADINGS[8]] + 1 :]
    )
    return sections


def _assert_assignment_inference_authority(text: str) -> None:
    sections = _assignment_authority_sections(text)
    b3b = sections[ASSIGNMENT_AUTHORITY_HEADINGS[1]]
    b4 = sections[ASSIGNMENT_AUTHORITY_HEADINGS[2]]
    b5 = sections[ASSIGNMENT_AUTHORITY_HEADINGS[3]]
    task_1c = sections[ASSIGNMENT_AUTHORITY_HEADINGS[4]]
    task_312 = sections[ASSIGNMENT_AUTHORITY_HEADINGS[6]]
    dispatch = sections[ASSIGNMENT_AUTHORITY_HEADINGS[8]]
    normalized_b3b = " ".join(b3b.split())
    normalized_b4 = " ".join(b4.split())
    normalized_b5 = " ".join(b5.split())
    normalized_1c = " ".join(task_1c.split())
    normalized_312 = " ".join(task_312.split())
    changed_sections = (b3b, b4, b5, task_1c, task_312)
    markers = (
        "**Dependency:**",
        "**Ownership:**",
        "**Typed records/protocol:**",
        "**Hash binding:**",
        "**Stop gate:**",
        "**Output:**",
    )
    for section in changed_sections:
        assert all(section.count(marker) == 1 for marker in markers)
        positions = tuple(section.index(marker) for marker in markers)
        assert positions == tuple(sorted(positions))
    section_sha256 = (
        "8c8b20f5ff66ea0983b70ec46a651ce4951d80ad85b7ddbd55c4f75e890108c3",
        "037a98ec61af0d236671d328d0c7dab70baa4563d9ab2f7b61f0e45d15c8898c",
        "ed42aae9ba73f63c6a4405cf66f8a1762338f29de919cd35c0c940afd7773dcf",
        "2f43744bebba1826dfc15bc9e6b0ac97f674fad8ff5669e5066f4a440ea13455",
        "cd8316815d4fe8d51e792ce0ef3aea59752e644d901de693a8c95dd488651ce5",
    )
    for section, expected_sha256 in zip(changed_sections, section_sha256, strict=True):
        _assert_normalized_section_snapshot(section, expected_sha256)
    _assert_normalized_section_snapshot(
        dispatch, "98208a03742c2c0ec8e29b2a64748eacb630773b00f7dd308ace666e7703c73e"
    )

    correction_digest = (
        "713a0c97e5d4b54afa28cbe940fc075c6265844e6e84209a2c06c84fbd30a104"
    )
    rejected_digest = "3324ebcf5c2889ffa7a875d36bc59b6e70a07cccd4da93eaeaf65f0a63481cc6"
    assert correction_digest in b3b
    assert "execution-assignment authoring only" in normalized_b3b
    assert "caller-supplied realization key" in normalized_b3b
    assert "forbidden" in normalized_b3b
    assert "Task 1.1c is the sole coordinator" in normalized_1c
    assert "PreAssignmentPairSet" in normalized_1c
    assert "AssignmentScopeClaim" in normalized_1c
    assert "ExecutionAssignmentRealization" in normalized_1c
    assert "ResolvedPairedRandomizationBinding" in normalized_1c
    assert "AssignmentStagingSink" in normalized_1c
    assert "claim before realization publication" in normalized_1c
    assert "same-key/different-bytes" in normalized_1c
    assert "execution_design_sha256" in normalized_b3b
    assert "PlanCell and receipt identity" in normalized_b3b
    assert "execution-assignment design ref" in normalized_b4
    assert "cannot create, import, execute, relabel, or reroll" in normalized_b4
    assert "ClusterBootstrapStabilityIntervalSpec" in normalized_b4
    assert 'coverage_claim="none_descriptive_only"' in normalized_b4
    assert "analysis_authoring_sha256" in normalized_b5
    assert "analysis_execution_binding_sha256" in normalized_b5
    assert "analysis_plan_sha256" in normalized_b5
    assert "composition_sha256" in normalized_b5
    assert "cannot contain Task 1.1c outputs" in normalized_b5
    assert "zero missing pairs" in normalized_312
    assert "ResolvedPairedRandomizationBinding" in normalized_312
    assert "descriptive stability" in normalized_312
    assert "no confidence-coverage claim" in normalized_312

    normalized_dispatch = " ".join(dispatch.split())
    assert "Task 1.1b4b is independently CLEAN" in normalized_dispatch
    assert "da0c5a5" in normalized_dispatch
    assert "45bbe8b" in normalized_dispatch
    assert (
        "20260826_task1_1b5_analysis_plan_authoring_dispatch_codex.md"
        in normalized_dispatch
    )
    assert (
        "36e64d137b0232dd483c399935897d4451d45ded34e93be953157a7e45cf4568"
        in normalized_dispatch
    )
    assert "Task 1.1b5 brief is independently CLEAN" in normalized_dispatch
    assert "Task 1.1b5 code is the sole next dispatch" in normalized_dispatch
    for blocked in (
        "Task 1.1c",
        "Task 1.2",
        "Stages 2–5",
    ):
        assert blocked in normalized_dispatch
    assert "remain blocked" in normalized_dispatch
    assert rejected_digest in normalized_dispatch
    assert "NOT-CLEAN historical evidence" in normalized_dispatch
    assert "implementation authority" in normalized_dispatch
    assert "never implementation authority" in normalized_dispatch

    forbidden = (
        "analysis-owned assignment",
        "analysis uses random label orientation",
        "random label orientation",
        "assignment bytes leave execution identity unchanged",
        "authoring embeds a future preassignmentpairset",
        "corrected task 1.1b4b bounded-brief authoring and independent review is the sole next dispatch",
        "task 1.1b4b code is the sole next dispatch",
        "task 1.1b5 bounded-brief authoring and independent review is the sole next dispatch",
        "task 1.1c code is the sole next dispatch",
        "caller chooses the realization key",
        "new seed under the same assignment scope",
        "rerun after realization publication",
        "missing pairs may still publish a p-value",
        "fixed blocks prove superpopulation confidence",
        "SRSWOR uses an ordinary block-bootstrap confidence interval",
        "Holm membership may be selected after p-values",
        "rejected b4b draft is implementation authority",
    )
    normalized_text = " ".join(text.casefold().split())
    assert all(fragment.casefold() not in normalized_text for fragment in forbidden)


def test_assignment_inference_authority_is_structurally_bound() -> None:
    _assert_assignment_inference_authority(REBASELINE_PLAN.read_text(encoding="utf-8"))


def test_assignment_inference_authority_rejects_scientific_and_structural_mutants() -> (
    None
):
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    headings = ASSIGNMENT_AUTHORITY_HEADINGS

    def add(start: str, end: str, claim: str) -> str:
        section = text.split(start, 1)[1].split(end, 1)[0]
        return text.replace(section, section + f"\n{claim}\n", 1)

    structural_heading = headings[1]
    indented = text.replace(structural_heading, f"    {structural_heading}", 1)
    fenced = text.replace(
        structural_heading,
        f"````markdown\n{structural_heading}\n````",
        1,
    )
    commented = text.replace(
        structural_heading,
        f"<!--\n{structural_heading}\n-->",
        1,
    )
    reordered = (
        text.replace(headings[1], "__B3B__", 1)
        .replace(headings[2], headings[1], 1)
        .replace("__B3B__", headings[2], 1)
    )
    mutants = {
        "analysis_owned_assignment": add(
            headings[2], headings[3], "Analysis uses random label orientation."
        ),
        "stale_b4b_brief_dispatch": text
        + "\nCorrected Task 1.1b4b bounded-brief authoring and independent review is the sole next dispatch.\n",
        "stale_b4b_code_dispatch": text
        + "\nTask 1.1b4b code is the sole next dispatch.\n",
        "stale_b5_brief_dispatch": text
        + "\nTask 1.1b5 bounded-brief authoring and independent review is the sole next dispatch.\n",
        "early_task_1c_code_dispatch": text
        + "\nTask 1.1c code is the sole next dispatch.\n",
        "wrong_b5_brief_digest": text.replace(
            "36e64d137b0232dd483c399935897d4451d45ded34e93be953157a7e45cf4568",
            "0" * 64,
        ),
        "assignment_hash_independence": add(
            headings[1],
            headings[2],
            "Assignment bytes leave execution identity unchanged.",
        ),
        "duplicate_heading": text + f"\n{structural_heading}\nconflict\n",
        "missing_heading": text.replace(structural_heading, "### Removed b3b", 1),
        "reordered_headings": reordered,
        "indented_heading": indented,
        "fenced_heading": fenced,
        "commented_heading": commented,
        "future_output_in_authoring": add(
            headings[2],
            headings[3],
            "Authoring embeds a future PreAssignmentPairSet and realization.",
        ),
        "rejected_brief_authority": add(
            headings[2],
            headings[3],
            "The rejected b4b draft is implementation authority.",
        ),
        "caller_key": add(
            headings[1],
            headings[2],
            "The caller chooses the realization key and a free-form exchangeability string.",
        ),
        "reroll_same_scope": add(
            headings[1],
            headings[2],
            "A new seed under the same assignment scope starts a new draw.",
        ),
        "bad_crash_recovery": add(
            headings[4],
            headings[5],
            "Recovery may rerun after realization publication.",
        ),
        "missing_pair_pvalue": add(
            headings[6],
            headings[7],
            "Missing pairs may still publish a p-value.",
        ),
        "ungrounded_confidence": add(
            headings[6],
            headings[7],
            "Fixed blocks prove superpopulation confidence.",
        ),
        "srswor_bootstrap_ci": add(
            headings[6],
            headings[7],
            "SRSWOR uses an ordinary block-bootstrap confidence interval.",
        ),
        "post_pvalue_holm": add(
            headings[3],
            headings[4],
            "Holm membership may be selected after p-values.",
        ),
        "partial_old_ownership": add(
            headings[2],
            headings[3],
            "Analysis-owned assignment remains authoritative.",
        ),
    }
    accepted: list[str] = []
    for name, mutant in mutants.items():
        try:
            _assert_assignment_inference_authority(mutant)
        except AssertionError:
            continue
        accepted.append(name)
    assert not accepted, f"assignment authority accepted mutants: {accepted!r}"


def test_rebaseline_guard_rejects_positive_independently_clean_claim() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    status = text.split("## Objective", 1)[0]
    _assert_rebaseline_mutation_is_rejected(
        text.replace(status, status + "\n> PR #7 is independently CLEAN.\n", 1)
    )


def test_rebaseline_guard_rejects_unapproved_b1_public_name() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    inventory = text.split("**Exact additive public names (11):**", 1)[1].split(
        "**Ownership:**", 1
    )[0]
    _assert_rebaseline_mutation_is_rejected(
        text.replace(
            inventory,
            inventory.replace(
                "UnseededEpisodeReplicationDesign", "FabricatedIdentitySpec"
            ),
            1,
        )
    )


def test_rebaseline_guard_rejects_dispatchable_hold_slice() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    task_1c = text.split("### Task 1.1c:", 1)[1].split("### Task 1.2:", 1)[0]
    _assert_rebaseline_mutation_is_rejected(
        text.replace(
            task_1c,
            task_1c + "\nTask 1.1c is dispatchable for implementation.\n",
            1,
        )
    )


def test_rebaseline_guard_rejects_stage_2_hold_schema_backfill_permission() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    stage_2_preamble = text.split("## Stage 2", 1)[1].split("### Task 2.1a:", 1)[0]
    _assert_rebaseline_mutation_is_rejected(
        text.replace(
            stage_2_preamble,
            stage_2_preamble + "\nStage 2 may backfill unresolved schema.\n",
            1,
        )
    )


def test_rebaseline_guard_rejects_positive_clean_claim_inside_b1() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    task_1b = text.split("### Task 1.1b1:", 1)[1].split(
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations",
        1,
    )[0]
    _assert_rebaseline_mutation_is_rejected(
        text.replace(task_1b, task_1b + "\nPR #7 is independently CLEAN.\n", 1)
    )


def test_rebaseline_guard_rejects_relocated_b1_authority_digest() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    digest = "13371f845ba1a34b0caa82dfca409f0558e0a3556313b13c39794bb56d231648"
    task_1b = text.split("### Task 1.1b1:", 1)[1].split(
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations",
        1,
    )[0]
    authority = task_1b.split("**Binding implementation authority:**", 1)[1].split(
        "**Files:**", 1
    )[0]
    relocated = task_1b.replace(authority, authority.replace(digest, "0" * 64), 1)
    relocated = relocated.replace("**Deferred:**", f"**Deferred:**\n\n{digest}", 1)
    _assert_rebaseline_mutation_is_rejected(text.replace(task_1b, relocated, 1))


def test_rebaseline_guard_rejects_duplicate_b1_heading() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    _assert_rebaseline_mutation_is_rejected(text + "\n### Task 1.1b1:\nconflict\n")


def test_rebaseline_guard_rejects_second_binding_authority() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    task_1b = text.split("### Task 1.1b1:", 1)[1].split(
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations",
        1,
    )[0]
    duplicate = "\n**Binding implementation authority:**\n`wrong/path.md`\n"
    _assert_rebaseline_mutation_is_rejected(
        text.replace(task_1b, task_1b + duplicate, 1)
    )


def test_rebaseline_guard_rejects_second_b1_dependency() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    task_1b = text.split("### Task 1.1b1:", 1)[1].split(
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations",
        1,
    )[0]
    duplicate = "\n**Dependency:** PR #7 is independently CLEAN.\n"
    _assert_rebaseline_mutation_is_rejected(
        text.replace(task_1b, task_1b + duplicate, 1)
    )


def test_rebaseline_guard_rejects_second_b1_inventory() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    task_1b = text.split("### Task 1.1b1:", 1)[1].split(
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations",
        1,
    )[0]
    duplicate = "\n**Exact additive public names (11):**\n`FabricatedIdentitySpec`\n"
    _assert_rebaseline_mutation_is_rejected(
        text.replace(task_1b, task_1b + duplicate, 1)
    )


def test_rebaseline_guard_rejects_second_current_dispatch_gate() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    duplicate = "\n## Current dispatch gate\nTask 1.1b1 is blocked.\n"
    _assert_rebaseline_mutation_is_rejected(text + duplicate)


def test_rebaseline_guard_rejects_stale_b3b_redispatch() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    dispatch = text.split("## Current dispatch gate", 1)[1]
    current_normalized = "Task 1.1b5 code is the sole next dispatch."
    stale_normalized = (
        "Task 1.1b3b bounded-brief authoring and independent review is the sole next "
        "dispatch."
    )
    normalized_dispatch = " ".join(dispatch.split())
    assert current_normalized in normalized_dispatch
    mutated_dispatch = normalized_dispatch.replace(
        current_normalized, stale_normalized, 1
    )
    _assert_rebaseline_mutation_is_rejected(text.replace(dispatch, mutated_dispatch, 1))


def test_rebaseline_dispatch_preserves_clean_b4b_while_authorizing_b5_code() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    dispatch = " ".join(text.split("## Current dispatch gate", 1)[1].split())
    assert "Task 1.1b4b is independently CLEAN" in dispatch
    assert "da0c5a5" in dispatch
    assert "45bbe8b" in dispatch
    assert "Task 1.1b5 brief is independently CLEAN" in dispatch
    assert "Task 1.1b5 code is the sole next dispatch" in dispatch
    assert "Task 1.1c, Task 1.2, and Stages 2–5 remain blocked" in dispatch


def test_rebaseline_dispatch_advances_from_clean_b5_brief_to_b5_code() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    brief = "Aug 22 Sync/20260826_task1_1b5_analysis_plan_authoring_dispatch_codex.md"
    digest = "36e64d137b0232dd483c399935897d4451d45ded34e93be953157a7e45cf4568"
    assert brief in normalized
    assert digest in normalized
    assert "Task 1.1b5 brief is independently CLEAN" in normalized
    dispatch = " ".join(text.split("## Current dispatch gate", 1)[1].split())
    assert "Task 1.1b5 code is the sole next dispatch" in dispatch
    assert "Task 1.1c, Task 1.2, and Stages 2–5 remain blocked" in dispatch


def _mutate_rebaseline_section(start: str, end: str, addition: str) -> str:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    section = text.split(start, 1)[1].split(end, 1)[0]
    return text.replace(section, section + addition, 1)


def test_three_layer_guard_rejects_analysis_identity_in_execution_receipt() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1b5: AnalysisPlan envelope, DAG, and declaration-only composition",
            "### Task 1.1c: Atomic three-layer resolution and schema migration",
            "\nPlanCell and receipt also bind analysis_design_sha256.\n",
        )
    )


def test_three_layer_guard_rejects_pre_outcome_realized_evaluation_work() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1b3: Execution-design authoring and episode-attempt policy",
            "### Task 1.1b4: Analysis primitives",
            "\nRealized EvaluationWork is precomputed before any outcome.\n",
        )
    )


def test_three_layer_guard_rejects_successor_after_unknown_transition() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1b3: Execution-design authoring and episode-attempt policy",
            "### Task 1.1b4: Analysis primitives",
            "\nA predeclared policy may retry transition_outcome_unknown.\n",
        )
    )


def test_three_layer_guard_rejects_unregistered_preregistered_analysis() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1b5: AnalysisPlan envelope, DAG, and declaration-only composition",
            "### Task 1.1c: Atomic three-layer resolution and schema migration",
            "\nContent hash alone proves the analysis was preregistered.\n",
        )
    )


def test_three_layer_guard_rejects_legacy_full_suite_in_run_plan() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1c: Atomic three-layer resolution and schema migration",
            "### Task 1.2: Add five provider-free measurement fixtures",
            "\nRunPlan retains suite and suite_sha256 for compatibility.\n",
        )
    )


def test_three_layer_guard_rejects_unqualified_complete_case_primary() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1b4: Analysis primitives",
            "### Task 1.1b5: AnalysisPlan envelope, DAG, and declaration-only composition",
            "\nValid-only complete-case output is always the primary population estimate.\n",
        )
    )


def test_three_layer_guard_rejects_relocated_design_authority_digest() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    digest = "4e570d793c350d15e6857aaca87addd14bcd5afff7d70b4db75835e5d49bd879"
    b2_start = (
        "### Task 1.1b2: Measurement selection and evaluation-instrument declarations"
    )
    b3_start = "### Task 1.1b3: Execution-design authoring and episode-attempt policy"
    task_1b2 = text.split(b2_start, 1)[1].split(b3_start, 1)[0]
    relocated = task_1b2.replace(digest, "0" * 64, 1)
    relocated += f"\nHistorical digest only: `{digest}`.\n"
    _assert_rebaseline_mutation_is_rejected(text.replace(task_1b2, relocated, 1))


def test_three_layer_guard_rejects_duplicate_b2_heading() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    duplicate = (
        "\n### Task 1.1b2: Measurement selection and evaluation-instrument declarations"
        "\nConflicting authority.\n"
    )
    _assert_rebaseline_mutation_is_rejected(text + duplicate)


def test_three_layer_guard_rejects_early_b3_implementation_dispatch() -> None:
    _assert_rebaseline_mutation_is_rejected(
        _mutate_rebaseline_section(
            "### Task 1.1b3: Execution-design authoring and episode-attempt policy",
            "### Task 1.1b4: Analysis primitives",
            "\nTask 1.1b3 is dispatchable for implementation before Task 1.1b2 is clean.\n",
        )
    )


def test_three_layer_guard_rejects_unconditional_migration_clean_and_sdk_dispatch() -> None:
    text = REBASELINE_PLAN.read_text(encoding="utf-8")
    contradiction = (
        "\nThis authority migration is independently CLEAN now.\n"
        "Task 1.1b2 SDK implementation is authorized immediately.\n"
    )
    _assert_rebaseline_mutation_is_rejected(text + contradiction)


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
