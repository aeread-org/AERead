from aeread_families.steer.campaign import _failure_condition


class _ProviderError(Exception):
    condition = "length"


def test_failure_condition_recovers_wrapped_provider_condition() -> None:
    provider = _ProviderError("provider failed")
    scheduler = RuntimeError("scheduler failed")
    scheduler.__cause__ = provider

    assert _failure_condition(scheduler) == "length"


def test_failure_condition_falls_back_for_untyped_error() -> None:
    assert _failure_condition(RuntimeError("failed")) == "execution_failure"
