"""Failure and measurement types shared by framework integrations."""
from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from numbers import Real
from threading import Lock
from typing import Any


MIN_DENOMINATOR = 1e-9


class FailureClass(str, Enum):
    """Stable failure classes emitted by integration adapters."""

    RETRYABLE_INFRASTRUCTURE = "retryable_infrastructure"
    INVALID_MEASUREMENT = "invalid_measurement"
    INTEGRATION_CONFIGURATION = "integration_configuration"


class IntegrationError(RuntimeError):
    """Base class for an outcome that must not become a training reward."""

    failure_class: FailureClass
    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.details = dict(details or {})
        self.telemetry: dict[str, Any] = {}
        super().__init__(message)


class RetryableInfrastructureError(IntegrationError):
    """A transient service or transport failure invalidated the rollout."""

    failure_class = FailureClass.RETRYABLE_INFRASTRUCTURE
    retryable = True


class InvalidMeasurementError(IntegrationError):
    """AERead did not produce a complete finite measurement."""

    failure_class = FailureClass.INVALID_MEASUREMENT


class IntegrationConfigurationError(IntegrationError):
    """The integration contract or deterministic configuration is invalid."""

    failure_class = FailureClass.INTEGRATION_CONFIGURATION


class EmptyModelResponse(RetryableInfrastructureError):
    """The candidate gateway returned no usable action text."""

    def __init__(
        self,
        *,
        request_count: int,
        blank_completion_count: int,
        completed_turn_count: int,
    ) -> None:
        self.request_count = request_count
        self.blank_completion_count = blank_completion_count
        self.completed_turn_count = completed_turn_count
        super().__init__(
            "candidate gateway returned an empty completion "
            f"(requests={request_count}, blanks={blank_completion_count}, "
            f"completed_turns={completed_turn_count})",
            status="blank_response",
            details={
                "candidate_request_count": request_count,
                "blank_completion_count": blank_completion_count,
                "completed_turn_count": completed_turn_count,
            },
        )


@dataclass(frozen=True)
class EpisodeMeasurement:
    """One complete finite AERead measurement accepted for optimization."""

    aer: float
    w_real: float
    denominator: float

    @classmethod
    def from_result(cls, result: Mapping[str, Any]) -> EpisodeMeasurement:
        """Validate a result and preserve its raw finite AER."""
        status = result.get("status")
        if status != "ok":
            raise failure_from_result(result)
        failure = _failure_payload(result)
        if (
            _raw_failure_class(result) is not None
            or failure
            or result.get("error") is not None
            or result.get("retryable") is not None
        ):
            raise IntegrationConfigurationError(
                "successful result unexpectedly carries failure metadata",
                status="ok",
                details=_failure_details(result),
            )

        aer = _finite_number("aer", result.get("aer"), result)
        w_real = _finite_number("w_real", result.get("w_real"), result)
        denominator = _finite_number(
            "denominator", result.get("denominator"), result
        )
        if denominator <= MIN_DENOMINATOR:
            raise InvalidMeasurementError(
                "AERead denominator is missing or degenerate: "
                f"{denominator!r}",
                status="ok",
                details=_failure_details(result),
            )
        expected = w_real / denominator
        if not math.isclose(aer, expected, rel_tol=1e-9, abs_tol=1e-12):
            raise InvalidMeasurementError(
                "AERead AER does not match w_real / denominator "
                f"({aer!r} != {expected!r})",
                status="ok",
                details=_failure_details(result),
            )
        return cls(aer=aer, w_real=w_real, denominator=denominator)


_FAILURE_CLASS_ALIASES = {
    "retryable_infrastructure": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "retryable_infrastructure_error": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "infrastructure": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "provider_error": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "invalid_measurement": FailureClass.INVALID_MEASUREMENT,
    "invalid_measurement_error": FailureClass.INVALID_MEASUREMENT,
    "integration_configuration": FailureClass.INTEGRATION_CONFIGURATION,
    "integration_configuration_error": FailureClass.INTEGRATION_CONFIGURATION,
    "configuration_error": FailureClass.INTEGRATION_CONFIGURATION,
}

_STATUS_FAILURE_CLASSES = {
    "harness_error": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "provider_error": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "gateway_timeout": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "rate_limited": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "blank_response": FailureClass.RETRYABLE_INFRASTRUCTURE,
    "invalid_measurement": FailureClass.INVALID_MEASUREMENT,
    "incomplete_score": FailureClass.INVALID_MEASUREMENT,
    "failed_verification": FailureClass.INVALID_MEASUREMENT,
    "configuration_error": FailureClass.INTEGRATION_CONFIGURATION,
    "invalid_configuration": FailureClass.INTEGRATION_CONFIGURATION,
    "invalid_schema": FailureClass.INTEGRATION_CONFIGURATION,
    "missing_case": FailureClass.INTEGRATION_CONFIGURATION,
    "unsupported_rllm_api": FailureClass.INTEGRATION_CONFIGURATION,
}


def _failure_payload(result: Mapping[str, Any]) -> Mapping[str, Any]:
    failure = result.get("failure")
    return failure if isinstance(failure, Mapping) else {}


def _raw_failure_class(result: Mapping[str, Any]) -> Any:
    failure = _failure_payload(result)
    for value in (
        result.get("failure_class"),
        failure.get("class"),
        failure.get("failure_class"),
    ):
        if value is not None:
            return value
    return None


def _retryable_value(result: Mapping[str, Any]) -> Any:
    failure = _failure_payload(result)
    for value in (result.get("retryable"), failure.get("retryable")):
        if value is not None:
            return value
    return None


def _failure_details(result: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only compact outcome fields suitable for error telemetry."""
    failure = _failure_payload(result)
    details = {
        "status": result.get("status"),
        "error": result.get("error") or failure.get("message"),
        "failure_class": _raw_failure_class(result),
        "retryable": _retryable_value(result),
        "aer": result.get("aer"),
        "w_real": result.get("w_real"),
        "denominator": result.get("denominator"),
        "candidate_request_count": result.get("candidate_request_count"),
        "blank_completion_count": result.get("blank_completion_count"),
        "completed_turn_count": result.get("completed_turn_count"),
    }
    return {key: value for key, value in details.items() if value is not None}


def _structured_failure_class(
    result: Mapping[str, Any],
) -> FailureClass | None:
    raw = _raw_failure_class(result)
    if raw is None:
        return None
    return _FAILURE_CLASS_ALIASES.get(str(raw).strip().lower())


def failure_from_result(result: Mapping[str, Any]) -> IntegrationError:
    """Map a structured non-measurement outcome to one typed exception.

    Unknown statuses and failure classes are integration contract failures.
    They always raise rather than acquiring an imputed reward.
    """
    status_value = result.get("status")
    status = str(status_value).strip().lower() if status_value is not None else ""
    failure = _failure_payload(result)
    raw_class = _raw_failure_class(result)
    failure_class = _structured_failure_class(result)
    if raw_class is not None and failure_class is None:
        return IntegrationConfigurationError(
            f"unrecognized AERead failure class {raw_class!r}",
            status=status or None,
            details=_failure_details(result),
        )
    if failure_class is None:
        failure_class = _STATUS_FAILURE_CLASSES.get(status)
    if failure_class is None:
        return IntegrationConfigurationError(
            f"unrecognized AERead result status {status_value!r}",
            status=status or None,
            details=_failure_details(result),
        )

    retryable_value = _retryable_value(result)
    expected_retryable = (
        failure_class is FailureClass.RETRYABLE_INFRASTRUCTURE
    )
    if retryable_value is not None:
        if not isinstance(retryable_value, bool):
            return IntegrationConfigurationError(
                "AERead failure retryability must be a Boolean",
                status=status or None,
                details=_failure_details(result),
            )
        if retryable_value != expected_retryable:
            return IntegrationConfigurationError(
                "AERead failure retryability conflicts with its failure class",
                status=status or None,
                details=_failure_details(result),
            )

    message = str(
        result.get("error")
        or failure.get("message")
        or f"AERead episode failed with status {status_value!r}"
    )
    kwargs = {
        "status": status or None,
        "details": _failure_details(result),
    }
    if status == "blank_response":
        return EmptyModelResponse(
            request_count=int(result.get("candidate_request_count", 0)),
            blank_completion_count=int(
                result.get("blank_completion_count", 1)
            ),
            completed_turn_count=int(result.get("completed_turn_count", 0)),
        )
    if failure_class is FailureClass.RETRYABLE_INFRASTRUCTURE:
        return RetryableInfrastructureError(message, **kwargs)
    if failure_class is FailureClass.INVALID_MEASUREMENT:
        return InvalidMeasurementError(message, **kwargs)
    return IntegrationConfigurationError(message, **kwargs)


def _finite_number(
    name: str, value: Any, result: Mapping[str, Any]
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise InvalidMeasurementError(
            f"AERead {name} is missing or not numeric: {value!r}",
            status="ok",
            details=_failure_details(result),
        )
    number = float(value)
    if not math.isfinite(number):
        raise InvalidMeasurementError(
            f"AERead {name} is not finite: {value!r}",
            status="ok",
            details=_failure_details(result),
        )
    return number


_RETRYABLE_EXCEPTION_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectionError",
    "InternalServerError",
    "RateLimitError",
    "ReadTimeout",
    "ServiceUnavailableError",
    "TimeoutError",
}


def normalize_integration_exception(error: Exception) -> IntegrationError:
    """Classify an exception escaping the episode core without swallowing it."""
    if isinstance(error, IntegrationError):
        return error
    status_code = getattr(error, "status_code", None)
    retryable_status = isinstance(status_code, int) and (
        status_code in {408, 409, 425, 429} or 500 <= status_code <= 599
    )
    retryable_type = any(
        cls.__name__ in _RETRYABLE_EXCEPTION_NAMES
        for cls in type(error).__mro__
    )
    if retryable_status or retryable_type:
        return RetryableInfrastructureError(
            f"{type(error).__name__}: {error}",
            details={"exception_type": type(error).__name__},
        )
    return IntegrationConfigurationError(
        "unclassified exception escaped the AERead integration: "
        f"{type(error).__name__}: {error}",
        details={"exception_type": type(error).__name__},
    )


class FlowTelemetry:
    """Thread-safe process counters for adapter attempts and outcomes."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._attempted = 0
        self._measured = 0
        self._failed_by_class: Counter[str] = Counter()

    def record_attempt(self) -> dict[str, Any]:
        with self._lock:
            self._attempted += 1
            return self._snapshot_unlocked()

    def record_measurement(self) -> dict[str, Any]:
        with self._lock:
            self._measured += 1
            return self._snapshot_unlocked()

    def record_failure(self, failure_class: FailureClass) -> dict[str, Any]:
        with self._lock:
            self._failed_by_class[failure_class.value] += 1
            return self._snapshot_unlocked()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def reset(self) -> None:
        with self._lock:
            self._attempted = 0
            self._measured = 0
            self._failed_by_class.clear()

    def _snapshot_unlocked(self) -> dict[str, Any]:
        failed_by_class = dict(sorted(self._failed_by_class.items()))
        return {
            "attempted": self._attempted,
            "measured": self._measured,
            "failed": sum(failed_by_class.values()),
            "failed_by_class": failed_by_class,
        }


__all__ = [
    "EmptyModelResponse",
    "EpisodeMeasurement",
    "FailureClass",
    "FlowTelemetry",
    "IntegrationConfigurationError",
    "IntegrationError",
    "InvalidMeasurementError",
    "RetryableInfrastructureError",
    "failure_from_result",
    "normalize_integration_exception",
]
