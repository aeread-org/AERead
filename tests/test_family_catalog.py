"""The generated family catalog reproduces its committed bytes.

``README.md`` once listed three of twenty-one families and ``cases/README.md``
missed nine of twenty-six case directories, because both tables were written
by hand and nothing failed when a family landed without a row. They are
generated now; these tests are the part that fails.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools import family_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_committed_catalog_matches_what_the_generator_produces() -> None:
    stale = [
        path
        for path, text in family_catalog.generate(ROOT).items()
        if (ROOT / path).read_text(encoding="utf-8") != text
    ]
    assert not stale, f"run `python tools/family_catalog.py --write`: {stale}"


def test_every_package_case_directory_and_document_directory_is_placed() -> None:
    families, _unowned = family_catalog.collect(ROOT)
    packages = {
        path.name
        for path in (ROOT / "src" / "aeread_families").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert packages <= {family.package for family in families}
    placed_cases = sorted(d for family in families for d in family.case_directories)
    assert placed_cases == sorted(p.name for p in (ROOT / "cases").iterdir() if p.is_dir())
    placed_documents = {d for family in families for d in family.document_directories}
    assert placed_documents == {
        p.name for p in (ROOT / "docs" / "families").iterdir() if p.is_dir()
    }


def test_registered_identities_are_the_registry_trusted_keys() -> None:
    from aeread.shared_runner.registry import TRUSTED_BUILTIN_PLUGIN_KEYS

    families, unowned = family_catalog.collect(ROOT)
    listed = sorted(identity for family in families for identity in family.identities) + unowned
    assert sorted(listed) == sorted(
        f"{family_id}@{version}" for family_id, version, _plugin in TRUSTED_BUILTIN_PLUGIN_KEYS
    )


def _copy_tree(tmp_path: Path) -> Path:
    root = tmp_path / "tree"
    for relative in ("src", "cases", "docs/families", "evidence"):
        shutil.copytree(
            ROOT / relative,
            root / relative,
            ignore=lambda _dir, names: [n for n in names if n not in {"README.md"} and "." in n and not n.endswith(".py")],
        )
    for relative in (family_catalog.README, family_catalog.CASES_README):
        shutil.copy(ROOT / relative, root / relative)
    return root


def test_a_family_package_the_catalog_does_not_declare_is_an_error(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    package = root / "src" / "aeread_families" / "undeclared_family"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    with pytest.raises(family_catalog.CatalogError, match="undeclared_family"):
        family_catalog.collect(root)


def test_a_case_directory_nobody_owns_is_an_error(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    (root / "cases" / "orphan_cases_v1").mkdir()
    with pytest.raises(family_catalog.CatalogError, match="orphan_cases_v1"):
        family_catalog.collect(root)


def test_a_new_case_directory_makes_the_committed_tables_stale(tmp_path: Path) -> None:
    root = _copy_tree(tmp_path)
    (root / "cases" / "housing_v2").mkdir()
    generated = family_catalog.generate(root)
    assert "housing_v2/" in generated[family_catalog.CASES_README]
    assert generated[family_catalog.README] != (ROOT / family_catalog.README).read_text(
        encoding="utf-8"
    )
