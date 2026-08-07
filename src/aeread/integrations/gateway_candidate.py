"""OpenAI-compatible candidate used at the submitted-agent boundary."""
from __future__ import annotations

import os
from collections.abc import Mapping
from types import TracebackType
from typing import Any

from aeread.integrations.failure_taxonomy import (
    EmptyModelResponse,
    InvalidMeasurementError,
)


NO_ACTION = "NO_ACTION"
"""Canonical non-empty action for intentional inactivity."""

DEFAULT_CANDIDATE_TIMEOUT = 60.0


class CandidateTraceMismatch(InvalidMeasurementError):
    """Candidate request telemetry cannot align one-to-one with its turns."""


class GatewayCandidate:
    """Submitted agent backed by one OpenAI-compatible client.

    ``sampling_params`` is provenance only. rLLM gateway sessions enforce it
    server-side, so those values are deliberately not copied into requests.
    Standalone callers may instead pass ``temperature`` and ``max_tokens``;
    those explicit values are sent because no gateway session owns sampling.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        timeout: float = DEFAULT_CANDIDATE_TIMEOUT,
        temperature: float | None = None,
        max_tokens: int | None = None,
        sampling_params: Mapping[str, Any] | None = None,
        client: Any | None = None,
    ) -> None:
        if sampling_params is not None and (
            temperature is not None or max_tokens is not None
        ):
            raise ValueError(
                "gateway-session sampling provenance cannot be combined with "
                "client-side temperature or max_tokens"
            )
        if client is None:
            from openai import OpenAI

            resolved = (
                api_key
                or os.environ.get("AEREAD_GATEWAY_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or "EMPTY"
            )
            client = OpenAI(
                base_url=base_url,
                api_key=resolved,
                max_retries=0,
                timeout=timeout,
            )
        self._client = client
        self.model = model
        self.timeout = float(timeout)
        self.temperature = temperature
        self.max_tokens = max_tokens
        if sampling_params is None:
            params = {
                key: value
                for key, value in {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }.items()
                if value is not None
            }
            source = "standalone_client"
        else:
            params = dict(sampling_params)
            source = "rllm_gateway_session"
        self.sampling_provenance = {"source": source, "params": params}
        self.turns: list[dict[str, Any]] = []
        self.candidate_request_count = 0
        self.blank_completion_count = 0
        self.request_failure_count = 0
        self._last_error: Exception | None = None
        self._closed = False

    @property
    def completed_turn_count(self) -> int:
        return len(self.turns)

    @property
    def telemetry(self) -> dict[str, int]:
        return {
            "candidate_request_count": self.candidate_request_count,
            "blank_completion_count": self.blank_completion_count,
            "completed_turn_count": self.completed_turn_count,
            "candidate_request_failure_count": self.request_failure_count,
        }

    def act(self, observation: str, phase: str) -> str:
        """Perform one logical action with at most one gateway request."""
        self.candidate_request_count += 1
        request: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": observation}],
        }
        if self.temperature is not None:
            request["temperature"] = self.temperature
        if self.max_tokens is not None:
            request["max_tokens"] = self.max_tokens
        try:
            response = self._client.chat.completions.create(**request)
        except Exception as err:
            self.request_failure_count += 1
            self._last_error = err
            raise

        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError):
            content = None
        text = content if isinstance(content, str) else ""
        if not text.strip():
            self.blank_completion_count += 1
            err = EmptyModelResponse(
                request_count=self.candidate_request_count,
                blank_completion_count=self.blank_completion_count,
                completed_turn_count=self.completed_turn_count,
            )
            self.request_failure_count += 1
            self._last_error = err
            raise err

        self.turns.append(
            {
                "phase": phase,
                "observation": observation,
                "response": text,
                "response_id": getattr(response, "id", None),
            }
        )
        return text

    def raise_if_failed(self) -> None:
        """Re-raise a candidate error swallowed by the batch submission shell."""
        if self._last_error is not None:
            raise self._last_error

    def assert_trace_safe(self) -> None:
        """Require one recorded turn for every successful logical request."""
        if self.blank_completion_count or (
            self.candidate_request_count != self.completed_turn_count
        ):
            raise CandidateTraceMismatch(
                "candidate requests cannot align with completed turns "
                f"(requests={self.candidate_request_count}, "
                f"blanks={self.blank_completion_count}, "
                f"completed_turns={self.completed_turn_count})"
            )

    def close(self) -> None:
        """Close the underlying SDK client exactly once."""
        if not self._closed:
            self._client.close()
            self._closed = True

    def __enter__(self) -> GatewayCandidate:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
