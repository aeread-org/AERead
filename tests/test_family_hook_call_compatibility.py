"""Every family plugin must accept the kernel's own ``initial_state`` call form.

The kernel calls this hook from two places with two different call forms:
``scheduler.py`` passes the second argument positionally, while
``evaluation.py``'s replay path used to pass it as ``run=``. Nine of the
eleven external adapters name that parameter ``cell``, so the keyword call
raised ``TypeError`` for every one of them -- meaning no external adapter
could produce a replayed receipt, while the natively-built families (which
happen to name it ``run``) passed. Only tau3.retail exercised
``replay_family_receipt`` in tests, and tau3 is one of the families that
named it ``run``, so the gap stayed invisible.

This test pins the contract at the signature level so a future family
cannot reintroduce it by choosing either name.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import aeread_families


def _plugin_classes() -> list[tuple[str, type]]:
    found: list[tuple[str, type]] = []
    for module_info in pkgutil.iter_modules(aeread_families.__path__):
        name = module_info.name
        try:
            module = importlib.import_module(f"aeread_families.{name}.environment")
        except Exception:  # families without an environment module
            continue
        for attribute in vars(module).values():
            if (
                inspect.isclass(attribute)
                and attribute.__module__ == module.__name__
                and hasattr(attribute, "initial_state")
                and hasattr(attribute, "phases")
            ):
                found.append((name, attribute))
    return found


PLUGINS = _plugin_classes()


def test_families_were_discovered() -> None:
    assert len(PLUGINS) >= 10, [name for name, _ in PLUGINS]


@pytest.mark.parametrize("family,plugin", PLUGINS, ids=[name for name, _ in PLUGINS])
def test_initial_state_accepts_a_positional_second_argument(
    family: str, plugin: type
) -> None:
    """scheduler.py and evaluation.py both call this hook positionally."""
    signature = inspect.signature(plugin.initial_state)
    parameters = [
        parameter
        for name, parameter in signature.parameters.items()
        if name != "self"
    ]
    assert len(parameters) == 2, f"{family}: expected (family_case, cell/run)"
    for parameter in parameters:
        assert parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), f"{family}: {parameter.name} must be passable positionally"


def _scorer_builders() -> list[tuple[str, type]]:
    return [(name, plugin) for name, plugin in PLUGINS if hasattr(plugin, "build_scorer")]


SCORERS = _scorer_builders()

# Families whose scorer still takes a recorded-outcome Mapping rather than the
# FamilyScoringInput the kernel passes. This is a ratchet, not an amnesty: the
# test is green today so CI stays honest, and it fails the moment a NEW family
# joins the list. Remove an entry when its issue lands; do not add one without
# an issue.
KNOWN_UNMIGRATED_SCORERS = {
    "govsim": "#76",
    # Found by this test, not previously tracked:
    "aucarena": "untracked -- needs an issue",
    "consent_ir": "untracked -- needs an issue",
}


@pytest.mark.parametrize(
    "family,plugin", SCORERS, ids=[name for name, _ in SCORERS]
)
def test_scorer_signature_matches_the_kernel_call(family: str, plugin: type) -> None:
    """`build_scorer(...)` must return something the kernel can actually call.

    `evaluation.py` calls it as `scorer(scoring_input, evidence_refs=...)`
    with a FamilyScoringInput dataclass. Four adapters were found taking a
    recorded-outcome Mapping instead (#74 econevals, #75 termsbench,
    #76 govsim, #80 amazonbarg), which fails on the first subscript and
    keeps every non-primary leaf out of the receipt. This asserts the shape
    at the signature level so the fifth is caught before a live run pays for
    it.

    A family with no `__call__` at all is reported as such rather than
    skipped: uncallable is the same defect, discovered later.
    """
    import typing

    from aeread.shared_runner.task.evaluation import FamilyScoringInput

    scorer_type = typing.get_type_hints(plugin.build_scorer).get("return")
    if scorer_type is None or not inspect.isclass(scorer_type):
        pytest.skip(f"{family}: build_scorer has no resolvable return annotation")
    call = getattr(scorer_type, "__call__", None)
    assert call is not None and call is not object.__call__, (
        f"{family}: {scorer_type.__name__} is not callable, so the kernel's "
        "finalizer cannot score it"
    )
    hints = typing.get_type_hints(call)
    parameters = [
        name for name in inspect.signature(call).parameters if name != "self"
    ]
    assert parameters, f"{family}: scorer __call__ takes no scoring input"
    first = hints.get(parameters[0])
    migrated = (
        first in (FamilyScoringInput, typing.Any, None) or first is object
    )
    if family in KNOWN_UNMIGRATED_SCORERS:
        assert not migrated, (
            f"{family} now matches the kernel contract -- remove it from "
            "KNOWN_UNMIGRATED_SCORERS "
            f"({KNOWN_UNMIGRATED_SCORERS[family]})"
        )
        pytest.xfail(
            f"{family}: scorer takes {first!r}, tracked as "
            f"{KNOWN_UNMIGRATED_SCORERS[family]}"
        )
    assert migrated, (
        f"{family}: scorer __call__ takes {first!r} as its first argument; the "
        "kernel passes a FamilyScoringInput"
    )
