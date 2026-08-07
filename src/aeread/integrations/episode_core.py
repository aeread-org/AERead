"""Framework-neutral AERead episode core."""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aeread.integrations.gateway_candidate import GatewayCandidate


DEFAULT_EXTERNAL_SCORING_MAX_TOKENS = 1200
DEFAULT_EXTERNAL_SCORING_TEMPERATURE = 0.0


def _configure_cache_environment() -> dict[str, str]:
    """Keep mutable inference caches outside an installed package tree."""
    cache_home = Path(
        os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    )
    defaults = {
        "AEREAD_CACHE_DIR": cache_home / "aeread" / "llm_responses",
        "AEREAD_GEMINI_CACHE_DIR": cache_home / "aeread" / "gemini",
    }
    for name, path in defaults.items():
        os.environ.setdefault(name, str(path))
    return {name: os.environ[name] for name in defaults}


def _close_candidate(candidate: Any) -> None:
    close = getattr(candidate, "close", None)
    if callable(close):
        close()


def run_episode(
    case_path: str | Path,
    seed: int,
    *,
    candidate: Any | None = None,
    candidate_factory: Callable[[], Any] | None = None,
    base_url: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1200,
    external_scoring_temperature: float = DEFAULT_EXTERNAL_SCORING_TEMPERATURE,
    external_scoring_max_tokens: int = DEFAULT_EXTERNAL_SCORING_MAX_TOKENS,
) -> dict[str, Any]:
    """Run one seeded episode and return its score row and candidate turns.

    ``temperature`` and ``max_tokens`` configure only the standalone candidate
    constructed when no candidate or factory is injected. External panel,
    compiler, and verifier calls have separate inference options. The rLLM
    adapter injects a gateway candidate whose session owns policy sampling.
    """
    if candidate is not None and candidate_factory is not None:
        raise ValueError("pass either candidate or candidate_factory, not both")

    _configure_cache_environment()
    from aeread import exchange_v1_pilot as pilot
    from aeread import exchange_v1_runner as runner
    from aeread import exchange_v1_submit as submit

    owns_candidate = candidate is None
    if candidate is None:
        if candidate_factory is not None:
            candidate = candidate_factory()
        else:
            if not base_url or not model:
                raise ValueError(
                    "standalone run_episode needs base_url and model when no "
                    "candidate is injected"
                )
            candidate = GatewayCandidate(
                base_url,
                model,
                temperature=temperature,
                max_tokens=max_tokens,
            )

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir)
            (out / "cases").mkdir(parents=True, exist_ok=True)
            prepared = pilot.seeded_case(
                Path(case_path), int(seed), out / "cases", "rllm"
            )
            sub_dir = submit.run_submission(
                [prepared],
                candidate,
                agent_label="rllm",
                out_root=out / "submissions",
                options=runner.InferenceOptions(
                    max_tokens=int(external_scoring_max_tokens),
                    temperature=float(external_scoring_temperature),
                ),
                verify_replay=False,
                quiet=True,
            )
            report = json.loads(
                (sub_dir / "submission_report.json").read_text()
            )

        raise_if_failed = getattr(candidate, "raise_if_failed", None)
        if callable(raise_if_failed):
            raise_if_failed()

        case_row = report["cases"][0]
        turns = list(getattr(candidate, "turns", []))
        request_count = int(
            getattr(candidate, "candidate_request_count", len(turns))
        )
        blank_count = int(getattr(candidate, "blank_completion_count", 0))
        if case_row.get("status") == "ok":
            assert_trace_safe = getattr(candidate, "assert_trace_safe", None)
            if callable(assert_trace_safe):
                assert_trace_safe()
            elif request_count != len(turns):
                raise RuntimeError(
                    "successful candidate requests do not match recorded turns"
                )

        score = case_row.get("score") or {}
        w_real = score.get("w_real")
        denominator = score.get("denominator")
        aer = None
        if w_real is not None and denominator and denominator > 1e-9:
            aer = float(w_real) / float(denominator)
        return {
            "status": case_row.get("status"),
            "error": case_row.get("error"),
            "failure": case_row.get("failure"),
            "failure_class": case_row.get("failure_class"),
            "retryable": case_row.get("retryable"),
            "aer": aer,
            "w_real": w_real,
            "denominator": denominator,
            "denominator_tier": score.get("denominator_tier"),
            "score": score,
            "turns": turns,
            "candidate_request_count": request_count,
            "blank_completion_count": blank_count,
            "completed_turn_count": len(turns),
            "candidate_sampling": dict(
                getattr(candidate, "sampling_provenance", {})
            ),
            "external_scoring": {
                "temperature": float(external_scoring_temperature),
                "max_tokens": int(external_scoring_max_tokens),
            },
        }
    finally:
        if owns_candidate:
            _close_candidate(candidate)
