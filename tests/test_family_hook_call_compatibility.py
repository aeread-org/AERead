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
