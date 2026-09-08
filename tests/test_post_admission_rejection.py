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
    _route_key = staticmethod(_Real._route_key)

    def __init__(self, proven: set[tuple[str, str | None, str]]) -> None:
        self._routes_proven = proven


def _profile(profile_id: str = "p1", *, provider: str = "openrouter", model: str = "m"):
    return SimpleNamespace(
        profile_id=profile_id,
        model=SimpleNamespace(provider=provider, base_url="https://r/v1", model=model),
    )


ROUTE = ("openrouter", "https://r/v1", "m")


def test_first_call_rejection_stays_non_retryable() -> None:
    executor = _Executor(proven=set())
    failure = ProviderFailure("provider_rejected", "404", retryable=False, status_code=404)
    assert executor._is_post_admission_rejection(_profile(), failure) is False


def test_rejection_after_a_success_is_typed_separately() -> None:
    executor = _Executor(proven={ROUTE})
    failure = ProviderFailure("provider_rejected", "404", retryable=False, status_code=404)
    assert executor._is_post_admission_rejection(_profile(), failure) is True


def test_proof_follows_the_route_not_the_profile() -> None:
    """Two profiles on one route share the proof; one profile on a different
    route does not. The thing that answered was the route."""
    executor = _Executor(proven={ROUTE})
    failure = ProviderFailure("provider_rejected", "404", retryable=False, status_code=404)
    assert executor._is_post_admission_rejection(_profile("p2"), failure) is True
    assert executor._is_post_admission_rejection(_profile("p1", model="other"), failure) is False


@pytest.mark.parametrize("status", [400, 401, 403, None])
def test_only_a_404_is_promoted_after_proof(status: int | None) -> None:
    """A 401 after a success is a revoked credential, not a flaky route;
    retrying it is three more 401s (review finding 2)."""
    executor = _Executor(proven={ROUTE})
    failure = ProviderFailure("provider_rejected", "rejected", retryable=False, status_code=status)
    assert executor._is_post_admission_rejection(_profile(), failure) is False


@pytest.mark.parametrize("condition", ["rate_limit", "provider_5xx", "timeout"])
def test_other_conditions_keep_their_own_typing(condition: str) -> None:
    """Only a rejection is reinterpreted; nothing else is relabelled."""
    executor = _Executor(proven={ROUTE})
    failure = ProviderFailure(condition, "x", retryable=True, status_code=404)
    assert executor._is_post_admission_rejection(_profile(), failure) is False


def test_the_condition_is_opt_in_by_name() -> None:
    """A family must list it to get the retry; it is not retryable by default."""
    assert POST_ADMISSION_REJECTION != "provider_rejected"


# ---------------------------------------------------------------------------
# Length-retry growth is bounded (issue #131).
# ---------------------------------------------------------------------------


def test_length_retry_growth_is_capped_at_a_multiple_of_the_declared_budget() -> None:
    """Doubling is right; unbounded doubling is not.

    A 2,400-token budget under a ten-attempt policy reached 1,228,800 --
    larger than the model's whole context window -- and the provider refused
    the request, turning a recoverable truncation into a failed case.
    """
    from aeread.shared_runner.task.execution import _LENGTH_RETRY_MAX_GROWTH

    declared = 2400
    ceiling = declared * _LENGTH_RETRY_MAX_GROWTH
    budget = declared
    for _ in range(10):
        budget = min(budget * 2, ceiling)
    assert budget == ceiling
    assert budget <= 1_048_576, "must stay inside a 1M context window"
    # And it still grows: a cap is not a freeze.
    assert min(declared * 2, ceiling) == 4800
