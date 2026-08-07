# rLLM integration

Train and evaluate agents on AERead through
[rLLM](https://github.com/rllm-org/rllm)'s agent trainer. Taking this over or
extending it? Start with [HANDOVER.md](HANDOVER.md): design rationale, what is
verified, the traps, and the open work. The packaged entry
points (see `[project.entry-points]` in `pyproject.toml`) expose an AgentFlow
and an evaluator under the name `aeread`, so rLLM discovers them by name once
this package is installed.

**How it maps** (mirrors rLLM's FrozenLake cookbook shape):

- Each dataset row is a versioned parameter contract — package-relative case
  resource, frozen SHA-256, seed, and stable `id` — and the arena is rebuilt
  deterministically per rollout after its case hash is verified.
- The **seat under test** is a text-boundary submitted agent whose `act()`
  calls the OpenAI-compatible endpoint at `config.base_url`. During training
  that is rLLM's model gateway, so exactly these calls are traced and
  trainable.
- The **frozen panel / compiler / verifier** run on their own provider clients
  with temperature-0 caching, untouched by the gateway — frozen for free.
- Reward is per-episode AER (raw `w_real / denominator`). GRPO groups rollouts
  per task, so per-case denominator scale cancels out of the advantage.

## Working recipe (pinned rLLM revision)

Install AERead, then pin both rLLM and its model gateway to the verified
revision `1d1109a655e291b3001d8526d7c9ecc5b9328226` -- the gateway must come
from the same tree as rLLM itself, not the lagging PyPI package:

```bash
pip install aeread
pip install \
    'rllm @ git+https://github.com/rllm-org/rllm.git@1d1109a655e291b3001d8526d7c9ecc5b9328226' \
    'rllm-model-gateway @ git+https://github.com/rllm-org/rllm.git@1d1109a655e291b3001d8526d7c9ecc5b9328226#subdirectory=rllm-model-gateway'
# equivalently: pip install -r integrations/rllm/constraints.txt, the file
# CI and integrations/rllm/compat.json also pin against.

python -m aeread.integrations.rllm_dataset --preflight
python -m aeread.integrations.rllm_dataset --register   # train/dev/test -> ~/.rllm
rllm eval aeread --agent aeread --evaluator aeread \
    --base-url https://openrouter.ai/api/v1 --model google/gemini-2.5-flash \
    --sampling-params temperature=0.7,max_tokens=1200 --concurrency 2
```

The compatibility suite is pinned to rLLM revision
`1d1109a655e291b3001d8526d7c9ecc5b9328226`. A constructor mismatch fails at
integration import instead of dropping episode artifacts.

The `integration-v1` case set contains exactly four public case families:
16 training rows use seeds 1200–1203, and eight public-development rows use
seeds 2200–2201. The registry's `test` split is an exact alias of `dev` for
rLLM's current eval CLI default. It is not AERead's future private test set.

## One-command no-credit B0 verification

Every command below is provider-free. Together they verify source-tree case
resource hashes and stable train/dev registration; candidate-client lifecycle,
timeouts, sampling provenance, failure filtering, and reward/reporting
contracts; and, against the pinned rLLM revision, plugin discovery, concurrent
decorated rollouts, strict trace enrichment, complete trajectory grouping, and
numerically expected GRPO rewards and advantages. They make no model call and
run no optimizer:

```bash
git clone https://github.com/rllm-org/rllm.git /tmp/rllm-src
git -C /tmp/rllm-src checkout 1d1109a655e291b3001d8526d7c9ecc5b9328226
pip install -e '.[dev]' click   # aeread checkout; click is rllm's CLI dep

python -m aeread.integrations.rllm_dataset --preflight && \
pytest tests/ -q && \
PYTHONPATH=/tmp/rllm-src pytest tests/test_rllm_integration.py -q
```

This installs AERead from source rather than installing rLLM's heavy training
dependency chain: putting the checked-out revision on `PYTHONPATH` is enough
for the provider-free pinned-rLLM tests. The separate wheel-acceptance command
(`pytest tests/test_wheel_acceptance.py -m wheel -q`) builds and installs the
wheel outside the checkout, checks its entry-point metadata, and verifies all
packaged case resources; see
[`../../tests/test_wheel_acceptance.py`](../../tests/test_wheel_acceptance.py).
One known, tracked gap remains: CI runs that wheel-metadata test and the
pinned-rLLM tests in separate environments, so installed-wheel plus pinned-rLLM
plugin loading is not yet tested as a single conjunction.

B0 is the provider-free training-contract target of this branch; its exact
scope is defined in [`READINESS_PROPOSAL.md`](READINESS_PROPOSAL.md). B1 is an
executed micro-GRPO run and has not been done: no optimizer has ever run for
this integration. C is benchmark readiness, a separate program not established
by either B0 or B1.

CI also runs a weekly non-blocking canary against rLLM `main` so upstream drift
surfaces before an adopter reports it -- see
[`../../.github/workflows/ci.yml`](../../.github/workflows/ci.yml) and the
checked-in [`compat.json`](compat.json) record.

## Example results

`rllm eval aeread` prints its own summary first, and that summary is not
AERead's benchmark number:

```text
Results:
  Accuracy:  100.0% (8/8)
  Errors:    0
```

Read AERead's numbers, not rLLM's. `Accuracy` above is the fraction of
measured episodes with `episode_aer > 0.0` — the evaluator's `is_correct`
compatibility diagnostic, `positive_welfare_rate`, not AERead's aggregate. A
single episode AER of `0.031` can print as `Accuracy: 100.0%`.

The evaluator's `EvalOutput` carries the actual measurement as named
signals (`episode_aer`, `w_real`, `denominator`, `valid_measurement`,
`blank_completion_count`, with the denominator tier attached where the
scorer reports one). Its metadata also records the exact case-set hash,
candidate model and sampling, prompt and panel specification hashes, and
scorer version/tier. Feed the collected per-episode signals through
`aeread.integrations.pooled_aer` to get AER and coverage first:

```python
from aeread.integrations.pooled_aer import aggregate_eval_signals

report = aggregate_eval_signals(per_episode_signal_rows)
# {
#     "episode_count": 8,
#     "measured_episode_count": 8,
#     "measurement_coverage": 1.0,
#     "pooled_aer_by_tier": {"wstar_fallback": 0.031},
#     "mean_episode_aer": 0.045,        # diagnostic only, never the headline
#     "positive_welfare_rate": 1.0,     # what rLLM's Accuracy line shows above
#     "errors_by_class": {},
#     "blank_completion_count": 0,
# }
```

`pooled_aer_by_tier` — `sum(w_real) / sum(denominator)` per denominator
tier, never a mean of per-episode ratios — is AERead's official headline,
the same formula `exchange_v1_submit.py` uses for a submission report.
**The rLLM `Accuracy` line is `positive_welfare_rate`, not AER, until rLLM
supports a custom aggregate or headline-label hook** (see
[`READINESS_PROPOSAL.md`](READINESS_PROPOSAL.md), Workstream 5). Do not
quote it as one.

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

- **Sampling:** the rLLM gateway session enforces candidate temperature and
  output-token limits. `AgentConfig.sampling_params` is recorded as provenance;
  the AERead adapter does not override it from agent metadata. Frozen external
  scoring services retain their separate temperature-0 inference options.
- **Concurrency and resources:** [`prototype_train.yaml`](prototype_train.yaml)
  caps external-provider development at two parallel tasks. The candidate SDK
  request timeout is 60 seconds with zero SDK retries; rLLM owns whole-rollout
  retries. External scoring has a separate 1,200-token budget and AERead's
  provider timeout/retry controls. A value above two requires an explicit
  `rllm.workflow.n_parallel_tasks` config or CLI override after checking both
  services' rate limits and cost.
- **Failure filtering:** the prototype retries exceptions three times, then
  returns an ERROR episode for compact filtering. `mask_error: true` removes
  that episode, and `min_trajs_per_group` equals `rollout.n`, so one invalid
  rollout drops the complete prompt group rather than changing its advantages.
  Finite zero and negative AER measurements remain in the group unchanged.
- **Measurement telemetry:** measured episodes carry per-attempt
  `measurement_counters` and process-level `flow_counters` artifacts. Raised
  typed exceptions carry the same flow snapshot in `.telemetry`; audit code
  can also call `aeread.integrations.rllm_flow.get_flow_telemetry()` for
  attempted, measured, and failed-by-class counts.
- **Client and cache lifecycle:** every per-rollout candidate client is closed.
  Mutable scoring caches default under the user cache directory and can be
  redirected with `AEREAD_CACHE_DIR` and `AEREAD_GEMINI_CACHE_DIR`.
- **Intentional inactivity:** use the explicit non-empty `NO_ACTION` protocol
  action. Missing, empty, or whitespace-only completions fail the rollout.
- **Replay:** replay verification is skipped inside RL rollouts
  (`verify_replay=False`) for speed — run `aeread submit` for auditable
  scoring of a checkpoint.
- **Framework-neutral core:** `aeread.integrations.rllm_flow.run_episode` has
  no rLLM dependency — miles/slime-style `generate_rollout` modules can call
  it directly and map the returned dict onto their sample type. See
  [`examples/run_episode_minimal.py`](../../examples/run_episode_minimal.py).
- **Status:** experimental; verified against the pinned revision above. Other
  rLLM revisions are unsupported unless they pass the compatibility probe and
  provider-free integration suite.
