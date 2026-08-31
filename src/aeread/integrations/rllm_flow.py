"""rLLM AgentFlow for AERead (experimental).

With `rllm <https://github.com/rllm-org/rllm>`_ installed, the entry points in
``pyproject.toml`` expose this flow and its evaluator under the name
``aeread``::

    rllm eval <dataset> --agent aeread --base-url http://localhost:30000/v1 --model <m>
    rllm train <dataset> --agent aeread ...

Design (mirrors rLLM's FrozenLake cookbook shape):

- Each task row is pure parameters — ``{case_path, seed}`` — and the arena is
  rebuilt deterministically per rollout.
- The **seat under test** is a text-boundary submitted agent whose ``act()``
  calls the OpenAI-compatible endpoint at ``config.base_url``. During training
  that is rLLM's model gateway, so exactly these calls are traced and
  trainable.
- The **frozen panel / compiler / verifier** seats run on their own provider
  clients with temperature-0 caching, untouched by the gateway — frozen for
  free.
- Reward is per-episode AER (raw ``w_real / denominator``), assigned by
  :func:`aeread.integrations.rllm_eval.aeread_evaluator`. GRPO groups rollouts
  per task, so per-case denominator scale cancels in the advantage.

Status: smoke-tested end-to-end against rLLM 0.3.0rc0 (git main, 2026-07-28):
``rllm eval aeread --agent aeread --evaluator aeread`` completes with the
episode AER as reward and only the under-test seat traced. Known upstream
install skew: rllm@git-main needs the gateway from the same tree —
``pip install --force-reinstall --no-deps
"rllm-model-gateway @ git+https://github.com/rllm-org/rllm.git#subdirectory=rllm-model-gateway"``
(the PyPI 0.1.0 wheel lags and lacks ``local_handler``). Replay verification
is skipped inside RL rollouts (``verify_replay=False``) — run ``aeread
submit`` for auditable scoring.
"""
from __future__ import annotations

import json
import tempfile
from importlib import import_module
from pathlib import Path
from typing import Any


class GatewayCandidate:
    """Submitted agent backed by an OpenAI-compatible endpoint.

    Satisfies the text-boundary contract: ``act(observation, phase) -> str``.
    Keeps a turn log so the flow can reconstruct per-step chat completions.
    """

    def __init__(self, base_url: str, model: str, *, api_key: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 1200) -> None:
        import os
        from openai import OpenAI
        # rLLM's model gateway accepts any key ("EMPTY"); direct provider
        # endpoints need a real one — resolve from env when not passed.
        resolved = (api_key or os.environ.get("AEREAD_GATEWAY_API_KEY")
                    or os.environ.get("OPENAI_API_KEY") or "EMPTY")
        self._client = OpenAI(base_url=base_url, api_key=resolved)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.turns: list[dict[str, str]] = []

    def act(self, observation: str, phase: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": observation}],
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
        self.turns.append({"phase": phase, "observation": observation,
                           "response": text})
        return text


def run_episode(case_path: str | Path, seed: int, *, base_url: str,
                model: str, temperature: float = 0.7,
                max_tokens: int = 1200) -> dict[str, Any]:
    """Framework-agnostic episode core: returns score row + turn log.

    Usable directly from any RL stack (miles/slime ``generate_rollout``
    modules can call this and map the return onto their Sample type).
    """
    from aeread.exchange_v1 import pilot as pilot
    from aeread.exchange_v1 import runner as runner
    from aeread.exchange_v1 import submit as submit

    candidate = GatewayCandidate(base_url, model, temperature=temperature,
                                 max_tokens=max_tokens)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        (out / "cases").mkdir(parents=True, exist_ok=True)
        prepared = pilot.seeded_case(Path(case_path), int(seed),
                                     out / "cases", "rllm")
        sub_dir = submit.run_submission(
            [prepared], candidate, agent_label="rllm",
            out_root=out / "submissions",
            options=runner.InferenceOptions(max_tokens=max_tokens),
            verify_replay=False, quiet=True)
        report = json.loads((sub_dir / "submission_report.json").read_text())
    case_row = report["cases"][0]
    score = case_row.get("score") or {}
    w_real = score.get("w_real")
    denom = score.get("denominator")
    aer = None
    if w_real is not None and denom and denom > 1e-9:
        aer = float(w_real) / float(denom)
    return {"status": case_row.get("status"), "aer": aer,
            "w_real": w_real, "denominator": denom,
            "score": score, "turns": candidate.turns}


def _termination_error() -> Any:
    """rLLM's ERROR termination reason, or None if this rllm lays it out elsewhere."""
    for mod_name in ("rllm.workflows.workflow", "rllm.workflows", "rllm"):
        try:
            return import_module(mod_name).TerminationReason.ERROR  # type: ignore[attr-defined]
        except (ImportError, AttributeError):
            continue
    return None


def _unscorable_reason(result: dict[str, Any]) -> str | None:
    """Why this episode carries no measurement, or None if it does.

    rLLM's runner counts an item as an error only when the episode terminates
    with ERROR; anything else is read as a score. Without this, an episode
    where the seat under test never received a model response reports as
    "Accuracy 0.0%, Errors 0" and reads as a model that played and realised
    nothing. A real AER of 0.0 (or a negative one) is a measurement and must
    stay a score.
    """
    status = result.get("status")
    if status != "ok":
        return (f"aeread episode did not complete: status={status!r}. "
                "The seat under test produced no scorable run (commonly an "
                "unreachable or unhealthy --base-url endpoint). This is a "
                "harness failure, not a score of zero.")
    if result.get("aer") is None:
        return (f"aeread episode has no AER: denominator={result.get('denominator')!r}. "
                "Degenerate denominators are reported, never imputed.")
    return None


def _episode_types() -> tuple[Any, Any, Any]:
    last_err: Exception | None = None
    for mod_name in ("rllm", "rllm.types", "rllm.core.types", "rllm.data.types"):
        try:
            mod = import_module(mod_name)
            return mod.Episode, mod.Trajectory, mod.Step  # type: ignore[attr-defined]
        except (ImportError, AttributeError) as err:
            last_err = err
    raise ImportError(
        "aeread rLLM integration: could not locate Episode/Trajectory/Step "
        "in rllm — is rllm installed? (pip install 'rllm @ "
        "git+https://github.com/rllm-org/rllm.git')") from last_err


class AereadFlow:
    """rLLM AgentFlow: one AERead arena episode per task.

    rLLM's loader requires an object with a ``.run(task, config)`` method
    (a bare function is rejected) — this class is what the ``rllm.agents``
    entry point exposes; :func:`aeread_flow` remains the functional core.
    """

    name = "aeread"

    def run(self, task: Any, config: Any) -> Any:
        return aeread_flow(task, config)

    async def arun(self, task: Any, config: Any) -> Any:
        return aeread_flow(task, config)


def aeread_flow(task: Any, config: Any) -> Any:
    """rLLM AgentFlow entry point (sync ``run`` shape)."""
    Episode, Trajectory, Step = _episode_types()

    meta = getattr(task, "metadata", None) or {}
    if isinstance(task, dict):
        meta = {**task, **meta}
    case_path = meta.get("case_path")
    seed = meta.get("seed")
    if case_path is None or seed is None:
        raise ValueError(
            "aeread task rows need `case_path` and `seed` in metadata — "
            "build them with aeread.integrations.rllm_dataset.build_rows()")

    cfg_meta = getattr(config, "metadata", None) or {}
    result = run_episode(
        case_path, seed,
        base_url=getattr(config, "base_url", None) or cfg_meta.get("base_url"),
        model=getattr(config, "model", None) or cfg_meta.get("model") or "gateway",
        temperature=float(cfg_meta.get("temperature", 0.7)),
        max_tokens=int(cfg_meta.get("max_tokens", 1200)))

    steps = []
    n = len(result["turns"])
    for i, turn in enumerate(result["turns"]):
        steps.append(Step(
            chat_completions=[{"role": "user", "content": turn["observation"]}],
            model_response=turn["response"],
            action=turn["response"],
            done=(i == n - 1)))
    aer = result["aer"]
    trajectory = Trajectory(name="under_test", steps=steps,
                            reward=float(aer) if aer is not None else 0.0)
    artifacts = {"status": result["status"], "aer": aer,
                 "w_real": result["w_real"],
                 "denominator": result["denominator"]}
    reason = _unscorable_reason(result)
    if reason is not None:
        artifacts["error"] = reason
    kwargs: dict[str, Any] = {
        "trajectories": [trajectory],
        "artifacts": artifacts,
        "is_correct": bool(aer is not None and aer > 0),
    }
    if reason is not None:
        terminated = _termination_error()
        if terminated is not None:
            kwargs["termination_reason"] = terminated
        kwargs["metadata"] = {"error": {"message": reason}}
    try:
        return Episode(**kwargs)
    except TypeError:
        return Episode(trajectories=[trajectory])
