"""The failure register must be trustworthy without the run artifacts.

`runs/` is gitignored, so every check here reads only the committed register.
That is deliberate: a suite that needs local run output cannot pass from a
clean checkout, which is itself one of the open defects the register tracks.
"""

from __future__ import annotations

import json

from aeread_families.datacenter_development.failure_register import (
    ATTRIBUTION_BY_CONDITION,
    KNOWN_DEFECTS,
    check_register,
    load_register,
    render_register,
)


def test_committed_register_passes_its_own_checks() -> None:
    assert check_register(load_register()) == []


def test_register_accounts_for_every_incident() -> None:
    register = load_register()
    incidents = register["incidents"]

    assert register["total_incidents"] == len(incidents) > 0
    assert register["total_cells"] >= register["total_incidents"]
    assert sum(register["by_class"].values()) == len(incidents)
    assert sum(register["by_attribution_as_recorded"].values()) == len(incidents)
    assert sum(register["by_attribution_corrected"].values()) == len(incidents)
    for incident in incidents:
        assert incident["run_id"]
        assert incident["cell_key"]
        assert incident["class"] in {"operational", "excluded", "no_agreement"}
        assert incident["attribution"] in {
            "model",
            "provider",
            "environment",
            "budget",
            "negotiation",
        }


def test_no_failure_condition_is_left_unclassified() -> None:
    """An unrecognised condition must fail loudly, not sit in a bucket."""
    register = load_register()

    assert register["unclassified_conditions"] == []
    assert not any(
        incident["attribution"] == "unclassified" for incident in register["incidents"]
    )


def test_model_errors_are_never_charged_to_the_provider() -> None:
    """Anything a model can trigger belongs to the model.

    The scheduler recorded these as provider missingness because the failure is
    raised inside the provider call. The register keeps the original condition
    and records the correction beside it.
    """
    register = load_register()
    reclassified = [i for i in register["incidents"] if "reclassified" in i]

    assert reclassified, "expected the mis-typed oversized-integer incidents"
    assert register["reclassified_incidents"] == len(reclassified)
    for incident in reclassified:
        assert incident["attribution"] == "provider"
        assert incident["reclassified"]["corrected_attribution"] == "model"
        assert incident["reclassified"]["reason"]
        assert incident["condition"] in ATTRIBUTION_BY_CONDITION

    corrected = register["by_attribution_corrected"]
    recorded = register["by_attribution_as_recorded"]
    assert corrected["provider"] < recorded["provider"]
    assert corrected["model"] > recorded["model"]
    assert recorded["provider"] - corrected["provider"] == len(reclassified)


def test_every_closed_defect_names_a_regression_test() -> None:
    """A defect is only closed when something stops it coming back."""
    for defect in KNOWN_DEFECTS:
        if defect["status"] in {"fixed", "worked_around"}:
            assert defect["regression_test"], defect["id"]
            assert "::" in defect["regression_test"], defect["id"]
            assert defect["fix"], defect["id"]
        else:
            assert defect["status"] == "open", defect["id"]
            assert defect["fix"] is None, defect["id"]


def test_defects_found_by_live_panels_are_recorded() -> None:
    """The defects only a live run could surface must not be lost."""
    register = load_register()
    by_id = {defect["id"]: defect for defect in register["defects"]}

    for defect_id in (
        "forced-amendment-no-decline",
        "undeclared-decline-transition",
        "model-error-booked-as-provider",
    ):
        assert by_id[defect_id]["detected_by"] == "live panel", defect_id
        assert by_id[defect_id]["status"] == "fixed", defect_id


def test_superseded_runs_are_marked_so_stale_results_are_not_reused() -> None:
    register = load_register()
    current = [run for run in register["runs"] if not run["superseded"]]
    superseded = [run for run in register["runs"] if run["superseded"]]

    assert len(current) == 1, "exactly one run is the current one"
    assert superseded, "the aborted and pre-fix runs must stay visible"
    assert all(run["incidents"] <= run["cells"] for run in register["runs"])


def test_rendered_register_reports_attribution_and_open_defects() -> None:
    text = render_register(load_register())

    assert "failure register" in text.lower()
    assert "Attribution" in text
    assert "suite-needs-gitignored-artifacts" in text


def test_named_regression_tests_actually_exist() -> None:
    """A register that names a test that does not exist is worse than silence."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for defect in KNOWN_DEFECTS:
        reference = defect["regression_test"]
        if not reference:
            continue
        path, _, name = reference.partition("::")
        source = root / path
        assert source.is_file(), f"{defect['id']}: missing {path}"
        assert f"def {name}(" in source.read_text(encoding="utf-8"), (
            f"{defect['id']}: {path} has no {name}"
        )
