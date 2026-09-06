"""Structural and compatibility checks for the case-oriented source layout."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import aeread

from aeread import cli


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "aeread"
FAMILIES_ROOT = ROOT / "src" / "aeread_families"
SHARED_RUNNER_ROOT = PACKAGE_ROOT / "shared_runner"
EVIDENCE_ROOT = ROOT / "evidence"


def test_root_package_contains_only_cross_family_entry_modules() -> None:
    root_modules = {path.name for path in PACKAGE_ROOT.glob("*.py")}

    assert root_modules == {"__init__.py", "cli.py"}
    assert {
        "exchange_v1",
        "inference",
        "integrations",
        "shared_runner",
    }.issubset(
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__pycache__")
    )


def test_shared_runner_uses_the_run_task_model_call_hierarchy() -> None:
    assert {path.name for path in SHARED_RUNNER_ROOT.glob("*.py")} == {
        "__init__.py",
        "measurement.py",
        "quality.py",
        "registry.py",
        "schemas.py",
    }
    assert {
        path.name
        for path in SHARED_RUNNER_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__pycache__")
    } == {"analysis", "model_call", "run", "task"}

    shared_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SHARED_RUNNER_ROOT.rglob("*.py")
    )
    assert "aeread_families" not in shared_source
    assert not list(SHARED_RUNNER_ROOT.rglob("housing*.py"))


def test_housing_family_owns_its_complete_execution_surface() -> None:
    housing_root = FAMILIES_ROOT / "housing"
    assert {path.name for path in housing_root.glob("*.py")} == {
        "__init__.py",
        "backend_campaign.py",
        "backend_publication.py",
        "case_sweep.py",
        "environment.py",
        "failure_register.py",
        "harness_bakeoff.py",
        "harness_leaderboard.py",
        "model_sensitivity.py",
        "population_campaign.py",
        "provider_concurrency.py",
        "provider_cooldown.py",
        "provider_pacing.py",
        "qc.py",
        "qc_bundle.py",
        "runner.py",
    }


def test_cli_verb_modules_use_the_organized_package_paths() -> None:
    for verb, (module_name, _description) in cli.VERBS.items():
        if verb == "export-tables":
            assert module_name == "aeread.shared_runner.analysis.research"
        else:
            assert module_name.startswith("aeread.exchange_v1.")
        import_module(module_name)


def test_legacy_package_attributes_resolve_to_canonical_modules() -> None:
    aliases = {
        "exchange_economy": "aeread.exchange_v1.economy",
        "exchange_v1_runner": "aeread.exchange_v1.runner",
        "housing_env": "aeread_families.housing.environment",
        "llm_agent": "aeread.inference.llm_agent",
        "gemini_llm": "aeread.inference.gemini",
    }

    for legacy_name, canonical_name in aliases.items():
        assert getattr(aeread, legacy_name) is import_module(canonical_name)


def test_artifact_roots_have_one_meaning_and_no_generic_output_aliases() -> None:
    ignored_roots = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "runs/" in ignored_roots
    assert "work/" in ignored_roots
    assert "output/" not in ignored_roots
    assert "outputs/" not in ignored_roots
    assert EVIDENCE_ROOT.is_dir()


def test_evidence_bundles_use_the_standard_publication_categories() -> None:
    allowed_root_files = {"README.md", "publication_manifest.json"}
    allowed_categories = {"tables", "trajectories", "receipts", "reports", "qc"}

    assert {path.name for path in EVIDENCE_ROOT.iterdir() if path.is_file()} == {
        "README.md"
    }
    for bundle in (path for path in EVIDENCE_ROOT.iterdir() if path.is_dir()):
        unexpected_files = {
            path.name
            for path in bundle.iterdir()
            if path.is_file() and path.name not in allowed_root_files
        }
        unexpected_directories = {
            path.name
            for path in bundle.iterdir()
            if path.is_dir() and path.name not in allowed_categories
        }
        assert not unexpected_files, (bundle.name, unexpected_files)
        assert not unexpected_directories, (bundle.name, unexpected_directories)
