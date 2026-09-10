"""A class may not define the same method twice.

Python does not error on a duplicated method: the later definition silently
replaces the earlier one. That makes this the exact shape a version-control
merge can produce without any conflict, and it did.

Two branches migrated the same family scorer. Each added a ``__call__`` to the
same class, at a different point in the file. Git saw two non-overlapping
insertions and merged both, with no conflict to review. The merged
``EconevalsScorer`` carried two ``__call__`` definitions with identical
signatures; the second won, the first became unreachable, and the branch that
lost also lost its delegation to ``score_all`` -- which its own docstring
called "this family's single source of truth". Each branch passed its own
suite (30 tests and 24 tests). The merge failed 6.

The sibling govsim pair edited the *same lines* and conflicted loudly, so a
human looked and it was safe. The only difference between "caught" and
"silently wrong" was where in the file each person happened to put the method.
That is not a property to rely on, so this test removes the reliance.

Scope note: this checks for duplicate *definitions* in one class body. It
cannot catch two definitions that a person merged by hand into one wrong one
-- for that, see "A clean merge is not evidence" in docs/operations/pr_lanes.md.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# ``tests`` is in scope deliberately. The file two family branches conflict in
# on every single merge is tests/test_shared_runner_scoring_contract.py, and the
# two duplicate-binding incidents this module records both happened there, not
# under src/.
SOURCE_ROOTS = (
    ROOT / "src" / "aeread_families",
    ROOT / "src" / "aeread",
    ROOT / "tests",
)

# A property and its setter legitimately repeat the name, as do
# ``functools.singledispatchmethod`` and ``typing.overload`` registrations.
# Only an undecorated redefinition is a mistake.
_LEGITIMATE_REDEFINITION_DECORATORS = frozenset(
    {"overload", "setter", "getter", "deleter", "register"}
)


def _decorator_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def _python_files() -> list[Path]:
    found: list[Path] = []
    for root in SOURCE_ROOTS:
        if root.exists():
            found.extend(sorted(root.rglob("*.py")))
    return found


FILES = _python_files()


def test_source_files_were_discovered() -> None:
    assert len(FILES) > 50, f"expected the family and kernel trees, found {len(FILES)}"


def duplicate_methods(source: str, filename: str = "<memory>") -> list[str]:
    """Every method a class in ``source`` defines more than once."""
    tree = ast.parse(source, filename=filename)
    offences: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        definitions: dict[str, list[ast.stmt]] = collections.defaultdict(list)
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                definitions[statement.name].append(statement)
        for name, statements in definitions.items():
            if len(statements) < 2:
                continue
            if any(
                _decorator_names(statement) & _LEGITIMATE_REDEFINITION_DECORATORS
                for statement in statements[1:]
            ):
                continue
            lines = ", ".join(str(statement.lineno) for statement in statements)
            offences.append(
                f"{node.name}.{name} defined {len(statements)} times "
                f"(lines {lines}); the last one silently wins"
            )
    return offences


@pytest.mark.parametrize(
    "path", FILES, ids=[str(p.relative_to(ROOT)) for p in FILES]
)
def test_no_class_defines_the_same_method_twice(path: Path) -> None:
    offences = duplicate_methods(path.read_text(), str(path))
    assert not offences, (
        f"{path.relative_to(ROOT)} has duplicate method definitions -- this is "
        "what an unconflicted merge of two branches that both added the same "
        "method looks like. " + "; ".join(offences)
    )


# The guard above passes on a healthy tree, which on its own tells us nothing:
# a check that has only ever been green is not known to be able to go red.
# These reproduce the merge that motivated it, and the two legitimate shapes it
# must not flag.

_MERGED_SCORER = """
class EconevalsScorer:
    def __call__(self, scoring_input, *, evidence_refs=()):
        return self.score_all(scoring_input)

    def __call__(self, scoring_input, *, evidence_refs=()):
        return self._score(scoring_input)
"""

_PROPERTY_PAIR = """
class Profile:
    @property
    def budget(self):
        return self._budget

    @budget.setter
    def budget(self, value):
        self._budget = value
"""

_OVERLOADS = """
import typing

class Store:
    @typing.overload
    def get(self, key: str) -> str: ...

    @typing.overload
    def get(self, key: int) -> int: ...

    def get(self, key):
        return self._items[key]
"""


def test_the_guard_fires_on_the_merge_that_motivated_it() -> None:
    offences = duplicate_methods(_MERGED_SCORER)
    assert offences, "the guard must catch two __call__ definitions in one class"
    assert "EconevalsScorer.__call__ defined 2 times" in offences[0]
    assert "silently wins" in offences[0]


def test_the_guard_ignores_a_property_and_its_setter() -> None:
    assert duplicate_methods(_PROPERTY_PAIR) == []


def test_the_guard_ignores_typing_overloads() -> None:
    assert duplicate_methods(_OVERLOADS) == []


# --- Module level, not just class bodies -----------------------------------
#
# The same silent-shadowing shape happens one indent level out, and the class
# check cannot see it. Both of these are real:
#
#   * A family branch produced two module-level definitions of the same
#     constant in tests/test_shared_runner_scoring_contract.py after a
#     hand-resolved registration conflict. Git saw no conflict, Python did not
#     error, the later one won, and the class check above does not look at
#     module bodies.
#   * PR #154 added six module-level test functions whose names already existed
#     on ``main``. Six tests became unreachable and the suite still reported
#     them as collected, because the later definition is the one pytest sees.
#
# Only DIRECT children of the module body are examined. A name defined twice
# under ``if TYPE_CHECKING:`` or in a ``try``/``except ImportError`` fallback is
# the normal way to write a conditional import and is not a duplicate binding.

# A module-level assignment is flagged only when the name reads as a constant:
# ALL_CAPS or a dunder such as ``__all__``. Rebinding a lower-case module
# variable on purpose is legal and occasionally deliberate, while rebinding a
# constant is the shape that silently drops whatever the first one declared.
def _is_constant_name(name: str) -> bool:
    return name.isupper() or (name.startswith("__") and name.endswith("__"))


def duplicate_module_bindings(source: str, filename: str = "<memory>") -> list[str]:
    """Every module-level name bound more than once by a definition or constant."""
    tree = ast.parse(source, filename=filename)
    definitions: dict[str, list[ast.stmt]] = collections.defaultdict(list)
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[statement.name].append(statement)
        elif isinstance(statement, ast.Assign):
            for target in statement.targets:
                if isinstance(target, ast.Name) and _is_constant_name(target.id):
                    definitions[target.id].append(statement)
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and _is_constant_name(statement.target.id)
        ):
            definitions[statement.target.id].append(statement)
    offences: list[str] = []
    for name, statements in definitions.items():
        if len(statements) < 2:
            continue
        if any(
            _decorator_names(statement) & _LEGITIMATE_REDEFINITION_DECORATORS
            for statement in statements[1:]
        ):
            continue
        lines = ", ".join(str(statement.lineno) for statement in statements)
        offences.append(
            f"{name} bound {len(statements)} times at module level "
            f"(lines {lines}); the last one silently wins"
        )
    return offences


@pytest.mark.parametrize(
    "path", FILES, ids=[str(p.relative_to(ROOT)) for p in FILES]
)
def test_no_module_binds_the_same_name_twice(path: Path) -> None:
    offences = duplicate_module_bindings(path.read_text(), str(path))
    assert not offences, (
        f"{path.relative_to(ROOT)} binds a module-level name more than once -- "
        "this is what a hand-resolved merge of two branches that both added to "
        "the same file looks like, and everything the earlier binding declared "
        "is silently discarded. " + "; ".join(offences)
    )


_MERGED_REGISTRATION = """
_BRIDGE_GATED = {("steer", "0.1.0")}

_BRIDGE_GATED = {("negarena", "0.1.0")}
"""

_MERGED_TEST_FUNCTIONS = """
def test_receipt_round_trips():
    assert True

def test_receipt_round_trips():
    assert False
"""

_SHADOWED_EXPORTS = """
__all__ = ["PROHIBITED_PUBLIC_TEXT", "main"]

__all__ = ["publish_campaign_evidence"]
"""

_CONDITIONAL_IMPORT = """
import typing

if typing.TYPE_CHECKING:
    from collections.abc import Mapping
else:
    Mapping = dict

try:
    import orjson as _json
except ImportError:
    import json as _json
"""

_REBOUND_LOWER_CASE = """
seen = []
seen = sorted(seen)
"""


def test_the_module_guard_fires_on_a_hand_merged_registration_constant() -> None:
    offences = duplicate_module_bindings(_MERGED_REGISTRATION)
    assert offences and "_BRIDGE_GATED bound 2 times" in offences[0]


def test_the_module_guard_fires_on_two_test_functions_of_one_name() -> None:
    offences = duplicate_module_bindings(_MERGED_TEST_FUNCTIONS)
    assert offences and "test_receipt_round_trips bound 2 times" in offences[0]


def test_the_module_guard_fires_on_a_shadowed_export_list() -> None:
    offences = duplicate_module_bindings(_SHADOWED_EXPORTS)
    assert offences and "__all__ bound 2 times" in offences[0]


def test_the_module_guard_ignores_conditional_imports() -> None:
    assert duplicate_module_bindings(_CONDITIONAL_IMPORT) == []


def test_the_module_guard_ignores_a_rebound_lower_case_variable() -> None:
    assert duplicate_module_bindings(_REBOUND_LOWER_CASE) == []
