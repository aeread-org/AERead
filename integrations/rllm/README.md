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
pip install "aeread @ git+https://github.com/aeread-org/AERead"
pip install "rllm @ git+https://github.com/rllm-org/rllm.git"
# upstream skew note: rllm@main needs its gateway from the same tree
pip install --force-reinstall --no-deps \
    "rllm-model-gateway @ git+https://github.com/rllm-org/rllm.git#subdirectory=rllm-model-gateway"

python -m aeread.integrations.rllm_dataset --register   # dev rows -> ~/.rllm
rllm eval aeread --agent aeread --evaluator aeread \
    --base-url https://openrouter.ai/api/v1 --model google/gemini-2.5-flash
```

Last verified 2026-08-05 against rLLM 0.3.0rc0: one rollout, `status: ok`,
episode AER returned as the reward, only the seat under test in the trace.

## Choosing `--base-url`

rLLM routes the seat under test through its model gateway, and the gateway
health-checks the endpoint you give it before routing. Not every
OpenAI-compatible URL passes that check.

| endpoint | works | note |
|---|---|---|
| OpenRouter (`https://openrouter.ai/api/v1`) | yes | verified |
| a local vLLM / SGLang worker | yes | the intended training path |
| Gemini's OpenAI-compat shim (`generativelanguage.googleapis.com/v1beta/openai/`) | no | gateway reports `RuntimeError: No healthy workers available` |

If the gateway cannot route, the seat under test gets no model response. The
run then terminates with rLLM's ERROR reason and the eval report counts it
under **Errors** rather than showing it as a score of 0.0. If you see that,
the endpoint is the first thing to check, not the model.

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
