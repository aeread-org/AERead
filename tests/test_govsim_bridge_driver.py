"""Tests for ``govsim_bridge_driver.py``'s own exception-handling contract
(triage Finding 3): only upstream's own intended malformed-action assertion
(QC Gate 2's "malformed-operational" golden) should ever be downgraded into
a typed, index-carrying action failure; any OTHER exception type raised by
upstream's ``step()`` is a genuine adapter/infrastructure incompatibility
and must propagate, never be silently indistinguishable from a deliberately
malformed action.

Pure, no bridge subprocess or pinned upstream checkout needed:
``govsim_bridge_driver.py`` has zero module-level third-party imports
(``omegaconf``/``simulation.persona`` are imported lazily, function-local --
see that module's own docstring), so ``_op_run_actions`` is importable and
directly testable under the project's own venv, with ``_build_env``/
``_build_action`` monkeypatched to a minimal fake environment rather than
the real upstream ``ConcurrentEnv``.
"""
from __future__ import annotations

from typing import Any

import pytest

from aeread_families.govsim import govsim_bridge_driver as driver


class _FakeEnv:
    """Minimal stand-in for upstream's real ``ConcurrentEnv``: ``reset()``
    is a no-op, and ``step()`` raises whatever exception the test wants to
    simulate upstream raising for a given action."""

    def __init__(self, step_exception: BaseException) -> None:
        self._step_exception = step_exception

    def reset(self, *, seed: int) -> None:
        del seed

    def step(self, action: Any) -> Any:
        raise self._step_exception


def _request(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": "fishing",
        "env_cfg": {},
        "seed": 0,
        "actions": [action],
    }


def test_op_run_actions_still_downgrades_upstreams_own_malformed_action_assertion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one intended path (spec section 4's "malformed-operational"
    golden): upstream's own ``assert`` on a malformed action still becomes
    a typed, index-carrying action failure -- this must keep working
    exactly as before after narrowing the ``except`` clause."""
    monkeypatch.setattr(
        driver, "_build_env", lambda scenario, env_cfg: _FakeEnv(AssertionError("bad location"))
    )
    monkeypatch.setattr(driver, "_build_action", lambda env, action: action)

    response = driver._op_run_actions(
        _request({"kind": "harvesting", "agent_id": "persona_0", "quantity": 1})
    )

    assert response["ok"] is False
    assert response["error_type"] == "AssertionError"
    assert response["failed_action_index"] == 0


@pytest.mark.parametrize(
    "exception", [KeyError("boom"), AttributeError("boom"), TypeError("boom")]
)
def test_op_run_actions_never_downgrades_a_non_assertion_exception_to_an_action_failure(
    monkeypatch: pytest.MonkeyPatch, exception: BaseException
) -> None:
    """Closes triage Finding 3: an adapter incompatibility (a ``KeyError``/
    ``AttributeError``/other programming error raised by upstream's own
    ``step()`` for what this adapter itself considers a valid action) must
    surface as a genuine infrastructure failure, never a typed,
    index-carrying action failure indistinguishable from the intended
    malformed-action assertion above. Before the fix, ``_op_run_actions``
    caught every ``Exception`` here identically and always attached
    ``failed_action_index`` -- which ``GovsimBridge.run_actions()`` then
    unconditionally turned into a ``GovsimActionError``, and
    ``GovsimPlugin.step()`` unconditionally downgraded to
    ``operational_failure``.
    """
    monkeypatch.setattr(driver, "_build_env", lambda scenario, env_cfg: _FakeEnv(exception))
    monkeypatch.setattr(driver, "_build_action", lambda env, action: action)

    with pytest.raises(type(exception)):
        driver._op_run_actions(
            _request({"kind": "harvesting", "agent_id": "persona_0", "quantity": 1})
        )
