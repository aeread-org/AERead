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

Status: experimental. Written against the rLLM docs of 2026-07; the Episode /
Step construction is defensive because the API is evolving. Replay
verification is skipped inside RL rollouts (``verify_replay=False``) — run
``aeread submit`` for auditable scoring.
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

    def __init__(self, base_url: str, model: str, *, api_key: str = "EMPTY",
                 temperature: float = 0.7, max_tokens: int = 1200) -> None:
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key=api_key)
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
    from aeread import exchange_v1_pilot as pilot
    from aeread import exchange_v1_runner as runner
    from aeread import exchange_v1_submit as submit

    candidate = GatewayCandidate(base_url, model, temperature=temperature,
                                 max_tokens=max_tokens)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
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
    try:
        return Episode(trajectories=[trajectory], artifacts=artifacts,
                       is_correct=bool(aer is not None and aer > 0))
    except TypeError:
        return Episode(trajectories=[trajectory])
