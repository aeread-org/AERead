# rLLM integration: handover

Everything a new owner needs to take this over. The user-facing recipe lives in
[README.md](README.md); this file is the part that is hard to reconstruct from
the code, namely why it is shaped this way, what has actually been verified,
and what is still open.

Status as of 2026-08-05: working, experimental, verified end to end against
rLLM 0.3.0rc0. Not yet in rLLM's dataset catalog.

## The whole surface

| File | Role |
|---|---|
| `src/aeread/integrations/rllm_flow.py` | `run_episode()`, the framework-neutral episode core, plus `AereadFlow`, the rLLM AgentFlow wrapper around it |
| `src/aeread/integrations/rllm_eval.py` | `aeread_evaluator()`, maps a finished episode to a reward |
| `src/aeread/integrations/rllm_dataset.py` | task rows (`case_path`, `seed`) and local registration into `~/.rllm` |
| `tests/test_rllm_integration.py` | provider-free tests, no network, no LLM |
| `integrations/rllm/README.md` | install recipe, endpoint table, notes |
| `pyproject.toml` | `rllm.agents` / `rllm.evaluators` entry points; `force-include` of `configs/` |
| `examples/run_episode_minimal.py` | the episode core with no rLLM involved, for other stacks |

Roughly 400 lines including tests. There is no vendored rLLM code and no patch
against rLLM: discovery is entirely through setuptools entry points, so an
installed `rllm` finds `aeread` by name and neither side forks.

## Design, and why

**Rows are parameters, not states.** A task row is `{case_path, seed}` and the
arena is rebuilt deterministically per rollout. This mirrors rLLM's FrozenLake
cookbook shape and is what makes a rollout reproducible from the row alone.
Resist the temptation to put a serialized world in the row.

**Only the seat under test is traced.** It is a text-boundary submitted agent
whose `act()` calls the OpenAI-compatible endpoint at `config.base_url`, which
during training is rLLM's model gateway. The frozen panel, the compiler, and
the verifier use their own provider clients with temperature-0 caching, so they
never enter the trace and cost almost nothing during training. Freeze the panel
to score, unfreeze it to train. This split is the load-bearing idea of the
integration: keep it.

**Reward is raw AER**, `w_real / denominator`, negatives preserved. Do not
normalize or clip it here. GRPO groups rollouts per task, so the per-case
denominator scale cancels in the advantage, which is the reason the raw value
is safe to hand over directly.

**Replay verification is off inside rollouts** (`verify_replay=False`) for
speed. Auditable scoring is `aeread submit`, not the RL path. If you ever make
a leaderboard claim from RL rollouts, that flag is the thing to revisit first.

## What is actually verified

Provider-free tests (`pytest tests/test_rllm_integration.py`, 7 tests, no
network) cover row resolution outside a checkout, explicit globs, the empty
glob error, and all four branches of the score-versus-error decision.

Live, against rLLM 0.3.0rc0 on 2026-08-05, one rollout each way:

| endpoint | result |
|---|---|
| `https://openrouter.ai/api/v1`, `google/gemini-2.5-flash` | `status: ok`, `Errors 0`, `ENV_DONE`, AER returned as the reward, 8 traced steps, only the seat under test in the trace |
| Gemini OpenAI-compat shim | `Errors 1`, `TerminationReason.ERROR`, cause printed |

Roughly 2.5 to 3.5 minutes and about $0.007 per episode on the OpenRouter path.

## Traps, all of which cost someone a debugging session

**rLLM's loader wants an object with `.run()`.** A bare function is rejected.
That is why `AereadFlow` is a class wrapping the functional `aeread_flow`.

**The gateway health-checks `--base-url` before routing.** Not every
OpenAI-compatible URL passes. OpenRouter and local vLLM workers do; Gemini's
OpenAI-compat shim does not, and fails with `RuntimeError: No healthy workers
available`. See the endpoint table in the README.

**A broken run must never look like a score of zero.** rLLM counts an eval item
as an error only when the episode terminates with `TerminationReason.ERROR`
(see `rllm/eval/runner.py`); anything else is read as a score. The flow
originally always reported `ENV_DONE`, so an episode where the seat never
received a model response reported as "Accuracy 0.0%, Errors 0", which reads as
a model that played and realized nothing. `_unscorable_reason()` now flags both
a non-ok status and a missing AER from a degenerate denominator. A real AER of
0.0 or below is a measurement and stays a plain score, and there is a test
pinning that so a future fix cannot swallow real zeros. If you touch the reward
path, keep this property.

**`rllm@main` needs its gateway from the same tree.** The PyPI
`rllm-model-gateway` 0.1.0 wheel lags and lacks `local_handler`. Force-reinstall
it from the monorepo subdirectory; the README recipe does this.

**Case configs ship inside the wheel.** `pyproject.toml` force-includes
`configs/` next to the package and `rllm_dataset._search_roots()` looks there
first, then the checkout root, then the CWD. Without this, `--register` only
works if you happen to be standing in a checkout. If you restructure packaging,
re-verify from a venv with no checkout present, not from the repo.

**The episode construction is deliberately defensive.** `_episode_types()` and
`_termination_error()` probe several module paths because the upstream API is
still moving. Written against rLLM of 2026-07.

## Open work, roughly in order

1. **Catalog entry.** Entries live in `rllm/registry/datasets.json`, schema
   `{description, source, builder, category, splits, eval_split, default_agent,
   reward_fn}`, with the builder in rLLM's tree and `source` pointing at a
   HuggingFace dataset. Our rows are pure parameters so the builder is trivial.
   The blocker is not code: `source` means publishing the dev rows to
   HuggingFace, and the public/held-out boundary has to be decided first. Dev
   seeds are publishable; the private held-out seed set and its generator salt
   are not, ever.
2. **Cookbook example** in rLLM's docs once the catalog entry exists.
3. **A real GRPO run.** Nobody has trained through this path yet. Our own 4B
   attempt (outside rLLM) improved on-config welfare but never exceeded the
   bilateral floor on multi-party deal construction, at any checkpoint. That is
   the open research question this integration exists to let someone attack.
4. **Sampling versus caching under training.** The README notes the mechanism
   (`model@t0.7:s2` per-sample indices bypass the temp-0 cache for the trained
   seat) but it has not been exercised across a full training run.
5. **`validate-case` calibration.** The strict gate mechanically rejects
   `cases_v0` because its thresholds were frozen on the v1 ladder family. Known,
   documented in CONTRIBUTING, unrelated to rLLM but it will confuse anyone who
   runs the gate on the public case set.

## Where this code is canonical

`src/aeread/integrations/*` and `pyproject.toml` are **canonical in this public
repo**. They are not produced by the private repo's export tool and do not
exist in its tree, so edit them here directly. By contrast `configs/` and
`exchange_economy.py` arrive by export and must be changed upstream first.

## Running the tests

```bash
pip install -e '.[dev]'
pytest tests/test_rllm_integration.py -q     # 7 tests, offline
pytest tests/ -q                             # full suite, 390 passed 1 xfailed
```

The rLLM-specific tests `importorskip("rllm")` for the parts that need the real
`Episode` type, so they degrade to skips rather than failures when rLLM is not
installed. CI does not install rLLM today, which is a deliberate choice to keep
the public suite provider-free and fast. If you want those covered in CI, add
an optional job rather than making rLLM a hard dependency.
