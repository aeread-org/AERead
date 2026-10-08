"""S4b: first-progress and idle deadlines for streamed provider calls (#226 items 1 and 3).

A profile that declares ``transport_v1`` and ``provider_stream`` may add
``transport_first_progress_seconds`` and ``transport_idle_seconds`` to
``harness.config``. The streamed client then bounds the wait for the first
chunk that carries output and the gap between such chunks, and an expiry is a
retryable ``timeout`` with ``stream_deadline`` set.

The streamed golden control
``test_streamed_transport_v1_goldens_are_byte_identical`` compares the events
and the complete execution record of a streamed ``transport_v1`` profile
without the knobs against files in ``tests/fixtures/stream_deadlines/``. They
were generated on the #248 head 77254689 before any S4b change, once per
openai major version, since the SDK's ``model_dump`` of the same stream
differs between them (3.x adds nullable usage fields):

    AEREAD_REGENERATE_STREAM_GOLDENS=1 PYTHONPATH=src:. \\
        python -m pytest tests/test_stream_deadlines.py -k streamed_transport_v1_goldens -p no:cacheprovider
"""

from __future__ import annotations

import os
from pathlib import Path

import openai
import pytest

from aeread.shared_runner.model_call.harness import AttemptExecutor, default_harnesses
from aeread.shared_runner.task.execution import EvidenceStore
from tests.test_route_health import (  # noqa: F401  (autouse fixtures)
    _instant_asyncio_sleep,
    clock,
    run_async,
)
from tests.test_shared_runner_execution import _decision
from tests.test_transport_resend import (
    MODEL,
    PRICING,
    PROMPT,
    PROMPT_ID,
    Wire,
    _canon,
    build_client,
    make_profile,
    ok,
    refuse,
)


# =====================================================================================
# The streamed golden control
# =====================================================================================

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "stream_deadlines"
REGENERATE = "AEREAD_REGENERATE_STREAM_GOLDENS"
SDK_MAJOR = f"openai{openai.__version__.split('.')[0]}"

GOLDEN_STEPS = {
    "recovered_refusal": lambda: [refuse(503), ok()],
    "streamed_success": lambda: [ok()],
}


def _run_streamed_golden(tmp_path, steps):
    root = tmp_path / "golden"
    evidence = EvidenceStore(
        root,
        run_plan_id="runplan_fixture",
        cell_id="cell_fixture",
        episode_id="episode_fixture",
        episode_attempt_id="episode_attempt_fixture_0",
        clock=lambda: "2026-10-08T00:00:00Z",
    )
    wire = Wire(steps)
    executor = AttemptExecutor(
        evidence=evidence,
        profiles=(make_profile(stream=True),),
        prompt_sources={PROMPT_ID: PROMPT},
        providers={"openrouter": build_client(wire)},
        pricing={MODEL: PRICING},
        harnesses=default_harnesses(),
    )
    decision = _decision()
    error = None
    try:
        run_async(executor(decision))
    except BaseException as caught:  # noqa: BLE001
        error = caught
    execution = {
        "error": None if error is None else [type(error).__name__, str(error)],
        "total_cost_usd": executor.total_cost_usd,
        "execution": executor.execution_for(decision.logical_action_id),
    }
    events = (root / "events.jsonl").read_bytes()
    evidence.close()
    return events, _canon(execution), wire


@pytest.mark.parametrize("name", sorted(GOLDEN_STEPS))
def test_streamed_transport_v1_goldens_are_byte_identical(tmp_path, clock, name) -> None:
    """A streamed transport_v1 profile without the knobs is untouched by S4b."""

    events, execution, wire = _run_streamed_golden(tmp_path, GOLDEN_STEPS[name]())
    assert wire.requests == len(GOLDEN_STEPS[name]())
    assert b'"stream": true' in wire.bodies[0] or b'"stream":true' in wire.bodies[0]
    stem = f"transport_v1_streamed_{name}.{SDK_MAJOR}"
    events_path = GOLDEN_DIR / f"{stem}.events.jsonl"
    execution_path = GOLDEN_DIR / f"{stem}.execution.json"
    if os.environ.get(REGENERATE) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        events_path.write_bytes(events)
        execution_path.write_bytes(execution)
        pytest.skip("goldens regenerated; run again without the flag to compare")
    assert events_path.is_file() and execution_path.is_file(), f"golden files are missing: {stem}"
    assert events == events_path.read_bytes()
    assert execution == execution_path.read_bytes()
