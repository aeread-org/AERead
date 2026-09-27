<p align="center">
  <a href="https://aeread.org"><img src="assets/logo.svg" alt="AERead" width="96"></a>
</p>

# AERead — an agentic economic environment for LLM agents

[![CI](https://github.com/aeread-org/AERead/actions/workflows/ci.yml/badge.svg)](https://github.com/aeread-org/AERead/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![Site](https://img.shields.io/badge/results-aeread.org-black.svg)](https://aeread.org)

**New here?** Follow the [onboarding journey](#onboarding-journey) below.

**Reference:** [Documentation map](docs/README.md) ·
[Concepts](docs/getting-started/concepts.md) ·
[Case catalog](cases/README.md) · [Benchmark QC](docs/operations/benchmark_qc.md) ·
[Experiment SOP](docs/operations/experiment_campaign_sop.md) ·
[Artifact layout](docs/architecture/artifact_layout.md) · [Source layout](docs/architecture/source_layout.md)

AERead (AgentEcon Readiness) is an open environment + benchmark for studying how
LLM agents behave in **economic and stateful decision environments**: bilateral
trade, multiparty clearing, hidden-counterparty discovery, consent under hidden
information, procurement, housing allocation, bundle-purchase worlds, and
refund/return tasks. It asks deployment questions about attainable welfare,
policy-correct state changes, and evidence-grounded decisions, then records the
case-native result in an auditable receipt.

Results and methodology: https://aeread.org · **Capability coverage map:**
[CAPABILITIES.md](CAPABILITIES.md) — what is covered, partial, and planned,
toward a general evaluation of agent economic capabilities.

## Onboarding journey

Follow these steps in order. Each step adds one architectural layer, and each
ends at a useful stopping point. You do not need to understand the entire
repository before running or extending one case.

### 1. Start with the measurement story

AERead is a measurement system, not just a collection of agent tasks. A case
defines a world and valid actions; a profile fixes how an agent is invoked; the
runner records what happened; a verifier derives typed measurements; and a
receipt binds the result to its exact inputs and evidence.

```text
case + profiles + run specification
              |
              v
       resolved RunPlan
              |
              v
     tasks -> attempts -> model-call and action events
              |
              v
     verifier -> typed metrics -> EvaluationReceipt
              |
              v
       research tables -> selected evidence publication
```

Keep these units distinct:

| Unit | Meaning |
|---|---|
| **Campaign** | A governed experiment that can contain multiple runs and promotion gates. |
| **Run** | One resolved, content-bound plan containing a declared task matrix. |
| **Task** | One `PlanCell`: a case, profiles, controls, world seed, and replicate. |
| **Attempt** | One retained execution of a task, including failed or retried attempts. |
| **Model call** | A provider interaction recorded as an append-only event inside an attempt. |
| **Receipt** | The sealed validity, measurement, replay, and inclusion decision for an attempt. |
| **Publication** | A sanitized, digest-bound projection selected from local run evidence. |

If that vocabulary is enough for now, continue to the first offline run. For
the full terminology, read [Concepts](docs/getting-started/concepts.md).

### 2. Install a development checkout

AERead requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

The editable install exposes the `aeread` CLI and the family packages used in
the examples below. No provider key is needed for the onboarding path.

### 3. Run one complete Housing task offline

This uses deterministic tenant and landlord policies, but otherwise follows
the same task scheduler, evidence, verifier, receipt, and replay boundaries as
a model-backed run.

```bash
ONBOARDING_RUN_ROOT="runs/onboarding/$(date +%Y%m%d-%H%M%S)"

python -m aeread_families.housing.runner \
    --provider scripted \
    --world-seed 7 \
    --tenants 2 \
    --listings 1 \
    --rounds 2 \
    --run-root "$ONBOARDING_RUN_ROOT"
```

The command prints a JSON summary. Look first for:

- `measurement_status: "ok"`, showing that the typed measurement was valid;
- `outcome.within_case_score`, the case-native normalized outcome;
- `receipt_path`, the sealed evaluation record;
- `replay_level: "state_and_score"`, the declared replay guarantee; and
- `total_cost_usd: 0.0`, confirming that this path made no paid model calls.

At this point you have executed the whole core path once. The scripted policy
is a control, not evidence about model capability.

### 4. Read the run from outside in

List the three records that explain the execution:

```bash
find "$ONBOARDING_RUN_ROOT" -type f \
    \( -name run_plan.json -o -name events.jsonl -o -name evaluation_receipt.json \)
```

Read them in this order:

1. `run_plan.json` — what was supposed to run: resolved cases, profiles,
   controls, seeds, implementation pins, and the complete task matrix.
2. `events.jsonl` — what actually happened: observations, actions, provider or
   scripted calls, transitions, failures, and terminal accounting.
3. `evaluation_receipt.json` — what may be claimed: evidence hashes, typed
   metrics, validity, replay level, and inclusion status.

Their location mirrors the conceptual hierarchy:

```text
runs/<workspace>/<run_id>/
  run_plan.json
  tasks/<task_id>/
    attempts/<attempt_id>/
      events.jsonl
      artifacts/
      evaluation_receipt.json
```

Raw execution state stays under ignored `runs/`. Only intentionally selected,
sanitized artifacts are committed under `evidence/`. See the
[artifact contract](docs/architecture/artifact_layout.md) before moving or publishing a run.

### 5. Trace the same path through the source tree

Do not begin with the largest implementation file. Follow one Housing task
across ownership boundaries:

| Question | Start here | Responsibility |
|---|---|---|
| What records can a user author? | [`schemas.py`](src/aeread/shared_runner/schemas.py) | Cross-level family, case, profile, analysis, and run contracts. |
| How does a specification become a fixed run? | [`run/resolver.py`](src/aeread/shared_runner/run/resolver.py) | Admission, matrix expansion, implementation pins, and `RunPlan` identity. |
| Where are run paths and campaign gates owned? | [`run/`](src/aeread/shared_runner/run/) | Run layout, append-only gate history, and invalidation rules. |
| How is one task advanced? | [`task/scheduler.py`](src/aeread/shared_runner/task/scheduler.py) | Private observations, legal actions, transitions, and terminal semantics. |
| How are calls and evidence recorded? | [`task/execution.py`](src/aeread/shared_runner/task/execution.py) | Attempts, provider calls, retries, budgets, events, and artifact sealing. |
| What may a harness access? | [`model_call/harness.py`](src/aeread/shared_runner/model_call/harness.py) | Brokered model/tool ports and framework-neutral harness contracts. |
| How does a result become a claim? | [`task/evaluation.py`](src/aeread/shared_runner/task/evaluation.py) | Family scoring, failure classification, replay, and receipt finalization. |
| Where does Housing behavior live? | [`aeread_families/housing/`](src/aeread_families/housing/) | Environment, prompts, policies, QC, campaigns, and Housing reports. |
| How do receipts become tables? | [`analysis/research.py`](src/aeread/shared_runner/analysis/research.py) | Run, task, model-call, trajectory, profile, feature, and result projections. |

The dependency direction is deliberate: a family may import the shared runner;
the shared runner must not import Housing or any other family. Read the
[source-layout contract](docs/architecture/source_layout.md) before adding a module.

### 6. Understand how a run becomes benchmark evidence

A successful task is not automatically a benchmark result. Campaigns advance
through ordered gates:

```text
design contract
  -> provider-free validation
  -> profile admission
  -> full-trajectory qualification
  -> variance pilot
  -> confirmatory freeze
  -> confirmatory execution
  -> publication
```

Failures and exclusions remain visible. Operational failures are missingness,
not zero-quality outcomes. A control change reopens the affected gates; after
confirmatory freeze it requires a new campaign identity. Read
[Benchmark QC](docs/operations/benchmark_qc.md), then the
[Experiment SOP](docs/operations/experiment_campaign_sop.md). Housing-specific checks are
in [Housing QC](docs/families/housing/qc.md).

### 7. Choose your next path

| Goal | Continue with |
|---|---|
| Grasp the complete architecture | [Follow the architecture reading journey](docs/README.md#architecture-reading-journey). |
| Evaluate a hosted model | [Evaluate a model](#evaluate-a-model), then the relevant family README. |
| Understand the available tasks | [Case catalog](cases/README.md) and [capability coverage](CAPABILITIES.md). |
| Compare harnesses | [Open-harness testing](docs/operations/open_harness_testing.md). |
| Design or execute a campaign | [Experiment SOP](docs/operations/experiment_campaign_sop.md). |
| Add a benchmark family or case | [Add a case](#add-a-case), [source layout](docs/architecture/source_layout.md), and [CONTRIBUTING](CONTRIBUTING.md). |
| Submit an external agent | [Submit an agent](#submit-an-agent) and [submission contract](docs/getting-started/submissions.md). |
| Connect a training or memory stack | [Integrations](integrations/README.md). |

## What makes it a benchmark, not just a sandbox

- **Resolved, reproducible cases.** Static JSON cases, generated worlds, and
  pinned upstream tasks are content-bound before execution. The same resolved
  inputs + seed produce the same world byte-for-byte.
- **One seat under test, frozen everything else.** The other seats are a frozen
  LLM panel (temperature 0, cached, model-pinned) or scripted policies, so the
  score isolates the candidate.
- **Typed, case-native scoring.** Welfare families use
  `AER = W_real / denominator`, pooled as `ΣW/ΣD`; stateful families can instead
  use deterministic property or answer checks. Unlike estimands and denominator
  tiers are never silently pooled, and degenerate denominators are reported
  instead of imputed.
- **Byte-replayable runs.** Every LLM call lands in an inference manifest with
  response snapshots; `--mode replay` re-executes a run with zero live calls and
  must reproduce the trace byte-identically. Submissions are verified this way.

## Evaluate a model

The top-level `aeread eval` command is the established Exchange-family
convenience workflow. Other families expose their executable entry points from
their package and document campaign-specific controls in their family README.

Models route through any OpenAI-compatible endpoint (`OPENAI_API_KEY` +
`OPENAI_BASE_URL`, defaults to OpenRouter slash-names) or natively to Gemini
(`GEMINI_API_KEY`).

```bash
export OPENAI_API_KEY=...    # OpenRouter (or set OPENAI_BASE_URL for another provider)

aeread eval --cases 'cases/exchange_v1/v0/case0*.json' \
    --agents noop random greedy your-provider/your-model \
    --seeds 5 --seed-base 1200 --workers 8 --out runs/my_eval
# -> runs/my_eval/summary.json: pooled AER + bootstrap CI per agent, vs the baselines
```

Note: for configs with a `roles` block, the under-test model comes from the
role table (or the `--agents` spec in `aeread eval`), not `aeread run --model`.

## Included case families

The canonical [case catalog](cases/README.md) includes these economic and
stateful-agent evaluations:

| Case | What it measures | Current scope |
|---|---|---|
| **Procurement** | Evidence-grounded sourcing plus interactive supplier qualification, negotiation, and allocation across quality, lead time, landed cost, margin, and return/refund terms | [`procurement_grounding_v1`](cases/procurement_grounding_v1/) tests the frozen 231-project evidence snapshot. [`procurement_allocation_v1`](cases/procurement_allocation_v1/) adds a synthetic objective-reference case with formal quotes, verified samples, and an actual award decision. The catalog also includes the specialized [`procurement_electronics_q3`](cases/exchange_v1/specialized/procurement_electronics_q3.json) exchange case. |
| **Housing** | Multi-round housing search and assignment under private tenant preferences and listing capacity | [`housing_v1`](cases/housing_v1/) generates deterministic worlds from case parameters and seeds; it intentionally has no static JSON fixtures. |
| **Refund and return** | Policy-constrained customer-service actions, exact final database state, required communication, and unintended mutations | [`tau3_retail`](cases/tau3_retail/) pins 114 upstream retail tasks and an [18-task refund/return pilot](cases/tau3_retail/base/pilot_manifest.json). The [integration plan](docs/families/tau3-retail/refund_external_benchmark_integration.md) keeps deterministic database-state results separate from judge-dependent assertions. |

Case-specific READMEs document the authoritative runner, scorer, provenance,
and maturity status. Results from unlike families are reported separately; they
are not collapsed into a universal cross-family score.

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
aeread submit --cases cases/exchange_v1/v0/case0*.json \
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
[CONTRIBUTING.md](CONTRIBUTING.md) and `cases/exchange_v1/v0/README.md`.

## Integrations

AERead plugs into other agent stacks through two small seams — the
text-boundary submitted-agent contract (`act(observation, phase) -> str`) and
the framework-neutral episode core (`run_episode(...) -> score row`). See
[integrations/](integrations/README.md) for the contract and the
add-your-own guide.

- **[rLLM](integrations/rllm/README.md)**
  (upstream: [rllm-org/rllm](https://github.com/rllm-org/rllm)) — train on
  AER as reward, smoke-tested against 0.3.0rc0: the seat under test samples
  through rLLM's model gateway; the frozen panel stays cached and untraced;
  GRPO groups rollouts per case so denominator scale cancels in the
  advantage.
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
- **`aeread.exchange_v1.rl_env`**: a structured (LLM-free) bilateral negotiation
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
src/aeread/exchange_v1/   Exchange environments, runners, scoring, and oracles
src/aeread_families/      Family-owned environments, runners, QC, and campaigns
src/aeread/inference/     case-independent provider and LLM execution helpers
src/aeread/shared_runner/ run/task/model-call kernel plus shared analysis
src/aeread/integrations/   rLLM flow/eval/dataset, EverOS memory (importable code)
integrations/          per-integration guides + examples (human side)
cases/                 canonical case catalog, grouped by family and version/split
configs/exchange_economy/  experiment configs grouped by role and frozen release
docs/                  sequenced guides, architecture contracts, family docs, operations, and research
examples/              minimal runnable entry points
tests/                 offline, deterministic; no API keys needed
CAPABILITIES.md        coverage map: covered / partial / planned capabilities
export_manifest.json   provenance of every exported module (see Provenance)
```

## Ecosystem & partnerships

- **[rLLM](https://github.com/rllm-org/rllm)** — Berkeley Sky Lab's agent
  post-training framework. AERead ships rLLM entry points; the seat under
  test trains through rLLM's gateway with per-episode AER as reward.
  ([guide](integrations/rllm/README.md))
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
