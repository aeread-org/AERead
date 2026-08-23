from pathlib import Path


DESIGN = Path(__file__).parents[1] / "docs" / "shared_runner_design.md"


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
        "feasible floor": "feasible_floor",
        "comparison baseline": "comparison_baseline",
        "attainable ceiling": "attainable_ceiling",
        "undecidable compressed frontier": "compressed_undecidable",
        "separate social outcome": "social_welfare",
        "separate private outcome": "principal_utility",
        "distributional capture": "capture_by_seat",
        "special-case bargaining reference": "symmetric_nash_par",
    }
    missing = {meaning: term for meaning, term in required_terms.items() if term not in text}
    assert not missing, f"shared-runner design is missing measurement contracts: {missing}"

    assert "cross_family_scalar: disabled" in text


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
