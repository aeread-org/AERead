"""The alympics upstream-import placeholder must not outlive that import.

``alympics_wac.environment`` binds a bare ``types.ModuleType`` to the name
``openai`` before importing the pinned upstream: ``Alympics.py`` does a
module-level ``import openai`` that the adapter has to satisfy without the
real client ever being constructed, and ``LLM.__init__`` only ever *sets*
attributes on it.

``sys.modules`` is process-global, so the placeholder cannot be left there.
Every later ``import openai`` anywhere in the process resolves to whatever is
resident, and a bare ``ModuleType`` carries none of the real package's
attributes -- so the next family that needs the real ``openai`` fails with an
``AttributeError`` raised in its own code and caused by another family's.
amazonbarg's upstream shim subclasses ``openai.OpenAI`` and fails outright
once alympics has run in the same interpreter. Recorded as issue #162.

Dropping the name on the way out costs alympics nothing: upstream's own
module global still holds a direct reference to the placeholder object from
its import, so the attributes ``LLM.__init__`` sets keep landing on the
placeholder. It is in fact stricter -- those assignments can no longer reach
the real package's shared module state.

These tests need no upstream checkout. They pin the placeholder's scoping
contract, so they run in the provider-free suite, which is where the families
this defect breaks actually live.
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Iterator

from aeread_families.alympics_wac import environment as environment_module


@contextmanager
def _openai_name_unbound() -> Iterator[None]:
    """Run the body with no ``openai`` in ``sys.modules``, then restore."""
    saved = sys.modules.pop("openai", None)
    try:
        yield
    finally:
        if saved is not None:
            sys.modules["openai"] = saved
        else:
            sys.modules.pop("openai", None)


def test_the_placeholder_is_removed_when_the_import_window_closes() -> None:
    with _openai_name_unbound():
        with environment_module._openai_placeholder():
            placeholder = sys.modules.get("openai")
            assert isinstance(placeholder, types.ModuleType), (
                "the upstream import needs the name bound to something"
            )
            assert getattr(placeholder, "__file__", None) is None, (
                "a placeholder, not the real package"
            )
        assert "openai" not in sys.modules, (
            "the placeholder outlived the upstream import; every later "
            "`import openai` in this process now resolves to it, and a bare "
            "module has none of the real package's attributes"
        )


def test_an_already_imported_openai_is_never_displaced() -> None:
    """The real package wins if anything imported it first."""
    real_enough = types.ModuleType("openai")
    real_enough.__file__ = "/nonexistent/site-packages/openai/__init__.py"
    with _openai_name_unbound():
        sys.modules["openai"] = real_enough
        with environment_module._openai_placeholder():
            assert sys.modules["openai"] is real_enough
        assert sys.modules["openai"] is real_enough


def test_only_the_placeholder_this_window_installed_is_removed() -> None:
    """Teardown removes our own object by identity, never someone else's.

    If anything inside the window replaced the binding -- the real package
    finally getting imported, say -- that replacement is what every later
    importer should keep seeing.
    """
    replacement = types.ModuleType("openai")
    replacement.__file__ = "/nonexistent/site-packages/openai/__init__.py"
    with _openai_name_unbound():
        with environment_module._openai_placeholder():
            sys.modules["openai"] = replacement
        assert sys.modules.get("openai") is replacement
