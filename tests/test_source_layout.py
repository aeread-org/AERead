"""Structural and compatibility checks for the case-oriented source layout."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path

import aeread

from aeread import cli


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "aeread"


def test_root_package_contains_only_cross_family_entry_modules() -> None:
    root_modules = {path.name for path in PACKAGE_ROOT.glob("*.py")}

    assert root_modules == {"__init__.py", "cli.py"}
    assert {
        "exchange_v1",
        "housing_v1",
        "inference",
        "integrations",
        "shared_runner",
    }.issubset(
        path.name
        for path in PACKAGE_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__pycache__")
    )


def test_cli_verb_modules_use_the_organized_package_paths() -> None:
    for verb, (module_name, _description) in cli.VERBS.items():
        if verb == "export-tables":
            assert module_name == "aeread.shared_runner.research"
        else:
            assert module_name.startswith("aeread.exchange_v1.")
        import_module(module_name)


def test_legacy_package_attributes_resolve_to_canonical_modules() -> None:
    aliases = {
        "exchange_economy": "aeread.exchange_v1.economy",
        "exchange_v1_runner": "aeread.exchange_v1.runner",
        "housing_env": "aeread.housing_v1.environment",
        "llm_agent": "aeread.inference.llm_agent",
        "gemini_llm": "aeread.inference.gemini",
    }

    for legacy_name, canonical_name in aliases.items():
        assert getattr(aeread, legacy_name) is import_module(canonical_name)
