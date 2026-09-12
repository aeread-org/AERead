from __future__ import annotations

from pathlib import Path

import pytest

from tools.check_registration_merge import check_merge, missing_returns, module_bindings


def test_dropped_import_is_rejected():
    assert "dropped module bindings" in check_merge("", "from a import x\n", "")[0]


def test_new_shadowing_import_is_rejected():
    left, right = "from a import x\n", "from b import x\n"
    assert "new duplicate binding" in check_merge(left + right, left, right)[0]


def test_existing_duplicate_does_not_create_a_new_merge_error():
    source = "from a import x\nfrom a import x\n"
    assert check_merge(source, source, "from a import x\n") == []


@pytest.mark.parametrize(("name", "expected"), [
    ("_NOT_YET_MIGRATED_TRUSTED_KEYS", {"shared"}),
    ("_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS", {"left", "right", "shared"}),
])
def test_registration_set_policy_preserves_migrations(name, expected):
    left = f"{name} = frozenset({{'left', 'shared'}})\n"
    right = f"{name} = frozenset({{'right', 'shared'}})\n"
    resolved = f"{name} = frozenset({expected!r})\n"
    assert check_merge(resolved, left, right) == []
    assert check_merge(f"{name} = frozenset()\n", left, right)


def test_assignment_unpacking_preserves_every_bound_name():
    original = "left, right = pair\n"
    assert check_merge("left = pair\n", original, "") == ["dropped module bindings: ['right']"]


def test_attribute_and_subscript_updates_do_not_rebind_the_container():
    assert module_bindings("OBJECT.attribute = 1\nOBJECT['key'] = 2\n") == {}


@pytest.mark.parametrize("source", [
    "def helper() -> int:\n    value = 1\n",
    "def helper() -> int:\n    return\n",
    "def helper() -> int:\n    return None\n",
    "def helper(flag) -> int:\n    if flag:\n        return 1\n",
    "def helper() -> int:\n    def nested():\n        return 1\n",
])
def test_non_none_helper_cannot_lose_its_return(source):
    assert missing_returns(source)


@pytest.mark.parametrize("source", [
    "def helper(flag) -> int:\n    if flag:\n        return 1\n    else:\n        raise ValueError\n",
    "def helper() -> int:\n    try:\n        return 1\n    except ValueError:\n        pytest.skip('missing bridge')\n",
    "def helper() -> int | None:\n    return None\n",
    "def helper() -> Iterator[int]:\n    yield 1\n",
])
def test_valid_exit_paths_and_optional_returns_are_preserved(source):
    assert missing_returns(source) == []


def test_current_registration_files_satisfy_the_checks():
    root = Path(__file__).resolve().parents[1]
    for name in ("tests/test_shared_runner_scoring_contract.py", "conftest.py",
                 "src/aeread/shared_runner/registry.py"):
        source = (root / name).read_text()
        assert check_merge(source, source, source) == []
