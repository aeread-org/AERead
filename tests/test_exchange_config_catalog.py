"""Structural contract for the organized Exchange configuration catalog."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "configs" / "exchange_economy"
RELEASE_ROOT = CONFIG_ROOT / "releases" / "v1"


def test_exchange_configs_are_grouped_by_role() -> None:
    role_directories = {
        path.name
        for path in CONFIG_ROOT.iterdir()
        if path.is_dir() and not path.is_symlink()
    }

    assert role_directories == {
        "baselines",
        "diagnostics",
        "ladders",
        "mechanisms",
        "releases",
        "treatments",
    }
    assert list(CONFIG_ROOT.glob("*.json")) == []


def test_exchange_config_catalog_links_resolve_within_the_catalog() -> None:
    toolbox = json.loads(
        (CONFIG_ROOT / "treatments" / "treatment_toolbox.json").read_text()
    )
    toolbox_paths = [toolbox["main_config"]]
    toolbox_paths.extend(
        step["config"]
        for mechanism in toolbox["mechanisms"].values()
        for step in mechanism.get("steps", [])
    )
    for relative_path in toolbox_paths:
        resolved = (CONFIG_ROOT / relative_path).resolve()
        assert resolved.is_relative_to(CONFIG_ROOT.resolve())
        assert resolved.is_file()

    manifest = json.loads((RELEASE_ROOT / "v1_manifest.json").read_text())
    manifest_paths = [ROOT / entry["config_path"] for entry in manifest["configs"]]
    assert len(manifest_paths) == 7
    assert all(path.parent == RELEASE_ROOT for path in manifest_paths)
    assert all(path.is_file() for path in manifest_paths)


def test_export_provenance_tracks_every_exchange_config_at_its_current_path() -> None:
    current_paths = {
        path.relative_to(ROOT).as_posix() for path in CONFIG_ROOT.rglob("*.json")
    }
    export_manifest = json.loads((ROOT / "export_manifest.json").read_text())
    provenance_paths = {
        path
        for path in export_manifest["sha256"]
        if path.startswith("configs/exchange_economy/") and path.endswith(".json")
    }

    assert provenance_paths == current_paths


def test_legacy_case_link_still_targets_the_canonical_exchange_cases() -> None:
    legacy = CONFIG_ROOT / "cases_v0"
    assert legacy.is_symlink()
    assert legacy.resolve() == ROOT / "cases" / "exchange_v1" / "v0"
