# AERead — an agentic economic environment for LLM agents

AERead (AgentEcon Readiness) is an open environment + benchmark for studying how
LLM agents behave in **multi-agent exchange economies**: bilateral trade,
multiparty clearing, hidden-counterparty discovery, consent under hidden
information, procurement, and bundle-purchase worlds. It asks a deployment
question — *how much of the attainable welfare does an agent actually realize
when it has to trade with others?* — and measures it with a single auditable
score.

Results and methodology: https://aeread.org

## What makes it a benchmark, not just a sandbox

- **Deterministic seeded cases.** A case is a JSON config (world + protocol +
  role table). Same config + seed ⇒ same world, byte-for-byte.
- **One seat under test, frozen everything else.** The other seats are a frozen
  LLM panel (temperature 0, cached, model-pinned) or scripted policies, so the
  score isolates the candidate.
- **AER scoring.** `AER = W_real / denominator` — realized welfare gain over the
  attainable welfare gain, pooled as `ΣW/ΣD`. Raw ratio: negatives are
  preserved, values can exceed 1, denominator tiers are never mixed, degenerate
  denominators are reported instead of imputed.
- **Byte-replayable runs.** Every LLM call lands in an inference manifest with
  response snapshots; `--mode replay` re-executes a run with zero live calls and
  must reproduce the trace byte-identically. Submissions are verified this way.

## Install

```bash
pip install -e '.[dev]'      # from a checkout; PyPI release forthcoming
aeread --help
```

## 60-second offline quickstart (no API keys)

```bash
# run a case fully offline (scripted policies, no LLM calls):
aeread run --config configs/exchange_economy/cases_v0/case01_visible_bilateral_ir.json \
    --mode offline --seed 7 --out runs/

# provider-free baselines + validity orderings for a case (~2 min/case, pure CPU):
aeread baselines --configs 'configs/exchange_economy/cases_v0/case01_visible_bilateral_ir.json' \
    --output-md /tmp/case01_baselines.md
```

## Evaluate a model

Models route through any OpenAI-compatible endpoint (`OPENAI_API_KEY` +
`OPENAI_BASE_URL`, defaults to OpenRouter slash-names) or natively to Gemini
(`GEMINI_API_KEY`).

```bash
export OPENAI_API_KEY=...    # OpenRouter (or set OPENAI_BASE_URL for another provider)

aeread eval --cases 'configs/exchange_economy/cases_v0/case0*.json' \
    --agents noop random greedy your-provider/your-model \
    --seeds 5 --seed-base 1200 --workers 8 --out output/my_eval
# -> output/my_eval/summary.json: pooled AER + bootstrap CI per agent, vs the baselines
```

Note: for configs with a `roles` block, the under-test model comes from the
role table (or the `--agents` spec in `aeread eval`), not `aeread run --model`.

## Submit an agent

Your agent never sees the world object — it gets the exact rendered text
observation an LLM seat would get, and returns text. One method:

```python
class MyAgent:
    def act(self, observation: str, phase: str) -> str:
        # phase ∈ {communication, proposal, response, finalization, private_acceptance}
        ...
```

```bash
aeread submit --cases configs/exchange_economy/cases_v0/case0*.json \
    --agent mypkg.myagent:MyAgent --out submissions/
# -> submission_report.json: per-case scores, case-set content hash,
#    replay verification (the run is re-executed with your agent absent and
#    must reproduce byte-identically)
```

**Two trust tiers.** Anything you run locally on the public dev seeds is
*self-reported*. A *verified* result is produced by the maintainers: we re-run
your submission's replay audit and evaluate the agent on a **private held-out
seed set** that never ships in this repo. Open a PR with your
`submission_report.json` to start that process (see CONTRIBUTING).

## Add a case

Cases are JSON: world spec (agents, resources, utility mode, world type),
protocol knobs (visibility, atomic commit, IR enforcement, settlement limits,
communication scope…), an `institution_pressure` block, and a strictly
validated `roles` table. New cases must pass the provider-free admission gate
(`aeread validate-case`), which enforces the non-triviality ordering
`no-op ≤ random < greedy < ceiling` and rejects degenerate worlds. See
[CONTRIBUTING.md](CONTRIBUTING.md) and `configs/exchange_economy/cases_v0/README.md`.

## RL

Two surfaces:

- **rLLM integration** (`aeread.integrations`, smoke-tested against rLLM
  0.3.0rc0): the packaged entry points expose an AgentFlow + evaluator — the
  seat under test samples through rLLM's model gateway (trainable, traced), the
  frozen panel stays on its own cached endpoints, and per-episode AER is the
  reward. GRPO groups rollouts per case, so per-case denominator scale cancels
  out of the advantage. Working recipe:

  ```bash
  pip install "rllm @ git+https://github.com/rllm-org/rllm.git"
  # upstream skew note: rllm@main needs its gateway from the same tree
  pip install --force-reinstall --no-deps \
      "rllm-model-gateway @ git+https://github.com/rllm-org/rllm.git#subdirectory=rllm-model-gateway"

  python -m aeread.integrations.rllm_dataset --register   # dev rows -> ~/.rllm
  rllm eval aeread --agent aeread --evaluator aeread \
      --base-url <openai-compatible-endpoint> --model <model>
  ```
- **`aeread.exchange_rl_env`**: a structured (LLM-free) bilateral negotiation
  env with `reset()` / `step(agent_id, StructuredAction)` for classical RL and
  unit-testable reward shaping.

For RL sampling, disable the response cache for the trained seat (temperature
> 0 with a per-sample index, e.g. agent spec `model@t0.7:s2`); frozen seats
keep temp-0 caching.

## Scoring semantics, in one paragraph

Per episode the scorer records `w_real` (realized welfare gain of the world,
from the trace) and a `denominator` (attainable welfare gain under the case's
oracle tier — exact Bayes, Monte-Carlo Bayes, or W* fallback). The headline is
the pooled raw aggregate `ΣW_real/ΣD` per tier with a bootstrap CI; a clipped
companion (`aer_clip`) is presentation-only. Failed feasibility/authorization
gates zero the episode's `W_real` but keep its denominator. Tiers are never
pooled together, and degenerate denominators are surfaced with a reason, never
silently scored.

## Provenance

This repository is a curated export of a private development repo:
`export_manifest.json` records the source commit and per-file SHA-256 for every
exported module, test, and config. Response caches, run archives, and the
private held-out seed set are excluded by design.

## Environment variables

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | OpenAI-compatible provider (default OpenRouter) |
| `GEMINI_API_KEY` | native Gemini path for `google/gemini-*` models |
| `AEREAD_CACHE_DIR`, `AEREAD_GEMINI_CACHE_DIR` | response-cache locations |
| `POC_MODEL`, `POC_MT`, `POC_TEMPERATURE` | runner defaults (model, max tokens, temperature) |

## License & citation

Apache-2.0. A methodology preprint is in preparation; until then, cite this
repository and https://aeread.org.
