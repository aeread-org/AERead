"""A 4xx after the route has answered cannot mean the route does not exist.

Parasail returned a spurious 404 twice during the econevals first light, each
time killing a panel mid-run while OpenRouter's own metadata listed the
endpoint as available. A first-call 404 must still fail fast -- it usually
means a wrong model id, and retrying it ten times turns an instant error into
a slow one -- so the two cases are typed separately.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from aeread.shared_runner.task.execution import (
    POST_ADMISSION_REJECTION,
    ProviderFailure,
)


class _Executor:
    """Only the seam under test, with the real method bound to it."""

    from aeread.shared_runner.task.execution import (  # type: ignore[misc]
        MinimalChatExecutor as _Real,
    )

    _is_post_admission_rejection = _Real._is_post_admission_rejection

    def __init__(self, proven: set[str]) -> None:
        self._routes_proven = proven


def _profile(profile_id: str = "p1"):
    return SimpleNamespace(profile_id=profile_id)


def test_first_call_rejection_stays_non_retryable() -> None:
    executor = _Executor(proven=set())
    failure = ProviderFailure("provider_rejected", "404", retryable=False)
    assert executor._is_post_admission_rejection(_profile(), failure) is False


def test_rejection_after_a_success_is_typed_separately() -> None:
    executor = _Executor(proven={"p1"})
    failure = ProviderFailure("provider_rejected", "404", retryable=False)
    assert executor._is_post_admission_rejection(_profile(), failure) is True


def test_a_different_profile_does_not_inherit_another_route_s_proof() -> None:
    executor = _Executor(proven={"p1"})
    failure = ProviderFailure("provider_rejected", "404", retryable=False)
    assert executor._is_post_admission_rejection(_profile("p2"), failure) is False


@pytest.mark.parametrize("condition", ["rate_limit", "provider_5xx", "timeout"])
def test_other_conditions_keep_their_own_typing(condition: str) -> None:
    """Only a rejection is reinterpreted; nothing else is relabelled."""
    executor = _Executor(proven={"p1"})
    failure = ProviderFailure(condition, "x", retryable=True)
    assert executor._is_post_admission_rejection(_profile(), failure) is False


def test_the_condition_is_opt_in_by_name() -> None:
    """A family must list it to get the retry; it is not retryable by default."""
    assert POST_ADMISSION_REJECTION != "provider_rejected"
