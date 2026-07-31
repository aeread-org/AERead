# rLLM integration

Train and evaluate agents on AERead through
[rLLM](https://github.com/rllm-org/rllm)'s agent trainer. The packaged entry
points (see `[project.entry-points]` in `pyproject.toml`) expose an AgentFlow
and an evaluator under the name `aeread`, so rLLM discovers them by name once
this package is installed.

**How it maps** (mirrors rLLM's FrozenLake cookbook shape):

- Each dataset row is pure parameters — `{case_path, seed}` — and the arena is
  rebuilt deterministically per rollout.
- The **seat under test** is a text-boundary submitted agent whose `act()`
  calls the OpenAI-compatible endpoint at `config.base_url`. During training
  that is rLLM's model gateway, so exactly these calls are traced and
  trainable.
- The **frozen panel / compiler / verifier** run on their own provider clients
  with temperature-0 caching, untouched by the gateway — frozen for free.
- Reward is per-episode AER (raw `w_real / denominator`). GRPO groups rollouts
  per task, so per-case denominator scale cancels out of the advantage.

## Working recipe (smoke-tested against rLLM 0.3.0rc0)

```bash
pip install "rllm @ git+https://github.com/rllm-org/rllm.git"
# upstream skew note: rllm@main needs its gateway from the same tree
pip install --force-reinstall --no-deps \
    "rllm-model-gateway @ git+https://github.com/rllm-org/rllm.git#subdirectory=rllm-model-gateway"

python -m aeread.integrations.rllm_dataset --register   # dev rows -> ~/.rllm
rllm eval aeread --agent aeread --evaluator aeread \
    --base-url <openai-compatible-endpoint> --model <model>
```

## Notes

- **Sampling vs caching:** disable the response cache for the trained seat
  (temperature > 0 with a per-sample index, e.g. agent spec `model@t0.7:s2`);
  frozen seats keep temp-0 caching.
- **Replay:** replay verification is skipped inside RL rollouts
  (`verify_replay=False`) for speed — run `aeread submit` for auditable
  scoring of a checkpoint.
- **Framework-neutral core:** `aeread.integrations.rllm_flow.run_episode` has
  no rLLM dependency — miles/slime-style `generate_rollout` modules can call
  it directly and map the returned dict onto their sample type. See
  [`examples/run_episode_minimal.py`](../../examples/run_episode_minimal.py).
- **Status:** experimental; written against the rLLM docs of 2026-07. The
  Episode/Step construction is defensive because the upstream API is evolving.
