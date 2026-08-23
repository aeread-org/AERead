from pathlib import Path


DESIGN = Path(__file__).parents[1] / "docs" / "shared_runner_design.md"
CASE_AUDIT = Path(__file__).parents[1] / "docs" / "problem_bound_case_audit.md"


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
