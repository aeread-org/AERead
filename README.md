<p align="center">
  <a href="https://aeread.org"><img src="assets/logo.svg" alt="AERead" width="96"></a>
</p>

# AERead — an agentic economic environment for LLM agents

[![CI](https://github.com/aeread-org/AERead/actions/workflows/ci.yml/badge.svg)](https://github.com/aeread-org/AERead/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Site](https://img.shields.io/badge/results-aeread.org-black.svg)](https://aeread.org)

**Start here:** [5-minute quickstart](docs/quickstart.md) ·
[Concepts](docs/concepts.md) · [Submit an agent](docs/submissions.md) ·
[Integrations (EverOS, yours)](integrations/README.md) ·
[Contribute](CONTRIBUTING.md)

AERead (AgentEcon Readiness) is an open environment + benchmark for studying how
LLM agents behave in **multi-agent exchange economies**: bilateral trade,
multiparty clearing, hidden-counterparty discovery, consent under hidden
information, procurement, and bundle-purchase worlds. It asks a deployment
question — *how much of the attainable welfare does an agent actually realize
when it has to trade with others?* — and measures it with a single auditable
score.

Results and methodology: https://aeread.org · **Capability coverage map:**
[CAPABILITIES.md](CAPABILITIES.md) — what is covered, partial, and planned,
toward a general evaluation of agent economic capabilities.

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
pip install aeread                 # Python 3.10+

# or from a checkout, for development:
pip install -e '.[dev]'

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

## Integrations

AERead plugs into other agent stacks through two small seams — the
text-boundary submitted-agent contract (`act(observation, phase) -> str`) and
the framework-neutral episode core (`run_episode(...) -> score row`). See
[integrations/](integrations/README.md) for the contract and the
add-your-own guide.

- **[EverOS](integrations/everos/README.md)**
  (upstream: [EverMind-AI/EverOS](https://github.com/EverMind-AI/EverOS)) —
  persistent memory as a treatment arm: a submitted agent that searches an
  EverOS server before every action and writes each finished episode +
  outcome back; a memory-on vs memory-off A/B measures what cross-episode
  memory is worth in realized welfare. Measured on the fixed client with
  three independent sequences per condition: control **+0.114**, memory
  **+0.082**, paired delta **−0.032** [−0.066, +0.002]. An earlier
  **+0.059 lift** reported from this integration was a measurement
  artifact and is **retracted** (see the guide for the full notice).
- **`aeread.exchange_rl_env`**: a structured (LLM-free) bilateral negotiation
  env with `reset()` / `step(agent_id, StructuredAction)` for classical RL
  and unit-testable reward shaping — no external framework needed.

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

## Repository map

```
src/aeread/            the installable package: arena engine, runner, scorer,
                       submission harness, baselines, oracles, CLI
src/aeread/integrations/   EverOS memory (importable code)
integrations/          per-integration guides + examples (human side)
configs/exchange_economy/  versioned case sets (cases_v0/, …) + variants
docs/                  quickstart, concepts, submission contract
examples/              minimal runnable entry points
tests/                 offline, deterministic; no API keys needed
CAPABILITIES.md        coverage map: covered / partial / planned capabilities
export_manifest.json   provenance of every exported module (see Provenance)
```

## Ecosystem & partnerships

- **[EverOS](https://github.com/EverMind-AI/EverOS)** — EverMind's
  open-source, markdown-first memory service. The persistent-memory
  treatment arm is developed in design partnership with the EverOS team.
  ([guide](integrations/everos/README.md))

Building on AERead, or want your framework listed? Open a
[new-integration issue](.github/ISSUE_TEMPLATE/new_integration.md).

## Community & contributing

- **[CONTRIBUTING.md](CONTRIBUTING.md)** — four channels: cases, agents &
  results, integrations, core code. Cases must pass the admission gate
  (`no-op ≤ random < greedy < ceiling`); code lands with offline tests.
- **Issues** — templates for [bugs](.github/ISSUE_TEMPLATE/bug_report.md),
  [new cases](.github/ISSUE_TEMPLATE/new_case.md), and
  [new integrations](.github/ISSUE_TEMPLATE/new_integration.md). Replay
  mismatches are P0.
- **[Code of Conduct](CODE_OF_CONDUCT.md)** — Contributor Covenant;
  benchmark disputes are settled with reproducible runs.

## License & citation

Apache-2.0. A methodology preprint is in preparation; until then, cite this
repository and https://aeread.org.
