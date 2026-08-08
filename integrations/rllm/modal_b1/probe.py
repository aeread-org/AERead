"""Stage 0: measure AER variance before any optimizer step is paid for.

A group of identical AERs produces a zero GRPO advantage for every member,
so a training run over it would satisfy B1 vacuously. This stage costs
roughly ten cents and prevents that outcome.

KNOWN BLOCKING FINDING (2026-08-08, verified on a live run, not assumed):
this module's execution pattern, calling ``aeread_flow.run(task, config)``
directly and then ``aeread_evaluator(task, episode)`` on the result, matches
the brief this file was written from, but is structurally incompatible with
the pinned rLLM revision and fails every episode, deterministically,
regardless of model or case. Root cause, traced in the installed source:

1. ``aeread.integrations.rllm_flow._build_measured_episode`` builds each
   ``Step`` with ``chat_completions=[{"role": "user", ...}]`` only. It never
   appends an ``{"role": "assistant", ...}`` entry.
2. ``aeread.integrations.rllm_eval._validate_enriched_candidate_trace``
   requires ``_assistant_content(step) == step.model_response``.
   ``_assistant_content`` reads the last assistant-role message from
   ``chat_completions``; with none present it always returns ``None``, so
   the equality always fails for any non-blank response.
3. ``rllm.eval.run_dataset``'s own docstring names the missing step: "the
   engine creates a gateway session, runs the agent flow against the
   session URL, fetches traces, enriches the Episode, then runs the
   per-task evaluator." That enrichment (populating the assistant message
   and ``response_ids`` from the gateway's recorded trace) only happens
   inside ``rllm.engine.agentflow_engine.AgentFlowEngine.execute_tasks``,
   reached via the async ``run_dataset``/``EvalGatewayManager`` path. This
   module's direct ``AgentConfig(base_url=VLLM_BASE_URL, ...)`` +
   ``aeread_flow.run`` + ``aeread_evaluator`` chain never creates a gateway
   session at all, so no enrichment ever happens.

Every one of the four probe episodes in the 2026-08-08 run failed with
``CandidateTraceMismatch: enriched candidate response does not match its
recorded action`` after every environment-level defect below was already
fixed (vLLM healthy, real model responses generated, real OpenRouter calls
made for the panel/compiler/verifier roles). This is not a probe
misconfiguration: switching models would not change it, since the missing
enrichment step is independent of which model generates the response.

The correct fix is adopting ``rllm.eval.run_dataset`` (async, and pulling in
``AgentFlowEngine``/``EvalGatewayManager``/``sandbox_backend`` machinery)
in place of the manual chain below. That is a materially different,
heavier execution model than this brief specifies, and it overlaps
directly with Task 4's trainer construction, so per this task's own
principle for the ``needs_env`` check ("stop and report, do not try to
fix"), it was reported rather than silently adopted here. See
``task-3-report.md`` for the full trace and the go/no-go verdict.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import modal

# Modal automounts the local entrypoint script itself as a flat file at
# /root/probe.py in the remote container -- a separate, un-packaged copy
# from the full repo baked into the image at /workspace/aeread by
# modal_app.py's add_local_dir(copy=True) step. Without this, the container's
# reimport of this module (to reconstruct the decorated `probe` function)
# cannot resolve the package-relative sibling import below, because /root has
# no `integrations/` package alongside it. Prepending the image's baked-in
# repo root makes both this import and probe()'s own runtime import of
# `integrations.rllm.modal_b1.report` resolve identically in the container.
# The path does not exist on the local machine, so this is a no-op locally.
if "/workspace/aeread" not in sys.path:
    sys.path.insert(0, "/workspace/aeread")

from integrations.rllm.modal_b1.modal_app import (
    GPU,
    RUNS_DIR,
    app,
    image,
    openrouter_secret,
    volume,
)

DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
VLLM_PORT = 8000
VLLM_BASE_URL = f"http://127.0.0.1:{VLLM_PORT}/v1"


def _serve_vllm(model: str) -> subprocess.Popen:
    """Start vLLM and block until it answers, or raise after two minutes.

    The brief's original redirect (``stdout=DEVNULL, stderr=STDOUT``) sends
    stderr to wherever stdout goes, but stdout goes nowhere, so a crash
    reason was silently discarded. This captures both into a log file and
    surfaces its tail in the raised error, since a crash with no diagnostic
    output cannot be triaged from the caller.
    """
    log_path = "/tmp/vllm_server.log"
    log_file = open(log_path, "wb")
    # This image's base has the GPU driver but no CUDA toolkit (no `nvcc`).
    # vLLM's default top-k/top-p sampler JIT-compiles a FlashInfer CUDA
    # kernel on first use, which needs nvcc and crashed the engine during
    # its warm-up profiling pass (verified: RuntimeError "Could not find
    # nvcc" surfaced only after capturing vLLM's own stderr, which the
    # brief's original DEVNULL/STDOUT redirect had been silently discarding).
    # Disabling it falls back to vLLM's pure-PyTorch sampler, which needs no
    # compilation step.
    vllm_env = dict(os.environ)
    vllm_env["VLLM_USE_FLASHINFER_SAMPLER"] = "0"
    process = subprocess.Popen(
        [
            "python", "-m", "vllm.entrypoints.openai.api_server",
            "--model", model,
            "--port", str(VLLM_PORT),
            # 8192 (the brief's original value) was too small: one dev case's
            # prompt alone measured 8193 input tokens, leaving zero room for
            # output and failing every call against it with a 400 from the
            # OpenAI-compatible endpoint (verified: BadRequestError in the
            # run log). Qwen2.5-0.5B-Instruct's published context is 32768;
            # this stays well inside it while giving every dev case in this
            # probe headroom for both its prompt and sampling_params'
            # max_tokens=1200.
            "--max-model-len", "32768",
            "--gpu-memory-utilization", "0.55",
            # At max-model-len=32768 vLLM's default compiled mode captures a
            # CUDA graph per batch size (~53 sizes) plus a torch.compile
            # pass, which pushed startup past the 120s health-check deadline
            # (verified: the container was still mid-load, no crash, when
            # the deadline hit). A stage-0 probe needs correctness, not
            # inference throughput, so skip that warm-up entirely.
            "--enforce-eager",
        ],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=vllm_env,
    )

    def _tail_log(n_bytes: int = 60000) -> str:
        log_file.flush()
        try:
            with open(log_path, "rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - n_bytes))
                return handle.read().decode("utf-8", errors="replace")
        except Exception as exc:  # never let log-reading mask the real error
            return f"(could not read vLLM log: {exc})"

    # 120s (this function's original value) covered a warm container where the
    # model weights were already cached, but a cold container also pays a
    # fresh HuggingFace download plus full engine init, and the two together
    # can run past 120s while still progressing normally (verified 2026-08-08:
    # a real train_smoke run logged steady progress -- APIServer start, model
    # resolved, engine init begun -- the whole time, then hit this deadline
    # mid-init, never having crashed). 600s covers a cold download without
    # weakening the crash-detection below, which still exits immediately
    # rather than waiting out the budget.
    deadline = time.time() + 600
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "vLLM exited before becoming healthy "
                f"(exit code {process.returncode}); tail of {log_path}:\n{_tail_log()}"
            )
        try:
            with urllib.request.urlopen(f"{VLLM_BASE_URL}/models", timeout=3):
                return process
        except Exception:
            time.sleep(3)
    process.kill()
    raise RuntimeError(
        f"vLLM did not become healthy within 600s; tail of {log_path}:\n{_tail_log()}"
    )


@app.function(
    image=image,
    gpu=GPU,
    timeout=3600,
    volumes={RUNS_DIR: volume},
    secrets=[openrouter_secret],
)
def probe(model: str = DEFAULT_MODEL, episodes: int = 4) -> dict[str, Any]:
    """Run N dev episodes and report AER spread, blanks, and failures."""
    os.chdir("/workspace/aeread")

    # The brief's original `from rllm.agents.agent import AgentConfig` does not
    # exist at the pinned rLLM revision (verified: ImportError in-container).
    # `src/aeread/integrations/rllm_flow.py` already imports AgentConfig from
    # `rllm.types` successfully at this same revision, so this matches the
    # proven working path rather than guessing at a second one.
    from rllm.types import AgentConfig
    from rllm.data import DatasetRegistry

    from aeread.integrations.rllm_dataset import register
    from aeread.integrations.rllm_eval import aeread_evaluator
    from aeread.integrations.rllm_flow import (
        aeread_flow,
        get_flow_telemetry,
        reset_flow_telemetry,
    )

    from integrations.rllm.modal_b1.report import (
        ESTIMATED_USD_PER_EPISODE,
        build_run_report,
        format_cost_line,
        signal_rows_from_eval_output,
        write_report,
    )

    counts = register()
    print(f"registered splits: {counts}")

    dataset = DatasetRegistry.load_dataset("aeread", "dev")
    tasks = list(dataset)[:episodes]
    if len(tasks) < 2:
        raise RuntimeError(f"need at least 2 dev tasks to judge variance, got {len(tasks)}")

    reset_flow_telemetry()
    server = _serve_vllm(model)
    started = time.time()
    rows: list[dict[str, Any]] = []
    try:
        def one(task: Any) -> dict[str, Any]:
            task_id = (getattr(task, "metadata", None) or task).get("id", "unknown")
            try:
                # AgentConfig.session_uid is a required field the brief's
                # snippet omitted (verified: TypeError in-container). aeread's
                # own flow code never reads it, but rLLM's rollout wrapper is
                # per-session bookkeeping, so each concurrently-run episode
                # gets its own config with a unique session_uid tied to its
                # task id rather than four episodes sharing one config object.
                config = AgentConfig(
                    base_url=VLLM_BASE_URL,
                    model=model,
                    session_uid=str(task_id),
                    sampling_params={"temperature": 0.7, "max_tokens": 1200},
                )
                episode = aeread_flow.run(task, config)
                output = aeread_evaluator(task, episode)
                return signal_rows_from_eval_output(task_id, output)
            except Exception as error:
                failure_class = getattr(
                    getattr(error, "failure_class", None), "value", "unclassified"
                )
                print(f"episode {task_id} failed: {type(error).__name__}: {error}")
                return {
                    "task_id": task_id,
                    "valid_measurement": False,
                    "failure_class": failure_class,
                    "blank_completion_count": 0.0,
                }

        # Honour the adapter's own concurrency hint rather than overriding it.
        with ThreadPoolExecutor(max_workers=getattr(aeread_flow, "max_concurrent", 2)) as pool:
            rows = list(pool.map(one, tasks))
    finally:
        server.kill()
        gpu_seconds = time.time() - started

    report = build_run_report(
        stage="probe",
        rows=rows,
        telemetry=get_flow_telemetry(),
        gpu_seconds=gpu_seconds,
        openrouter_usd=len(rows) * ESTIMATED_USD_PER_EPISODE,
        live_calls=len(rows),
        cached_calls=0,
        total_tokens=0,
        extra={"model": model, "episodes": len(rows)},
    )
    slug = model.replace("/", "_")
    write_report(f"{RUNS_DIR}/probe_{slug}.json", report)
    volume.commit()

    print(f"variance: {report['variance']}")
    print(format_cost_line(report))
    return report


@app.local_entrypoint(name="probe_main")
def main(model: str = DEFAULT_MODEL, episodes: int = 4) -> None:
    report = probe.remote(model=model, episodes=episodes)
    verdict = report["variance"]
    print(f"\nAER spread: {verdict['spread']:.6f} over n={verdict['n']}")
    print(f"recommendation: {verdict['recommendation']}")
    if verdict["degenerate"]:
        print("\nGATE: degenerate group. Re-run with --model Qwen/Qwen3-1.7B before stage 1.")
    else:
        print("\nGATE: passed. Stage 1 is worth running.")
