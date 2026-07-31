# Contributing to AERead

Four contribution channels: **cases** (§1), **agents/results** (§2),
**integrations** (§3), and **code** (§4).

## 0. Dev setup

```bash
git clone https://github.com/aeread-org/AERead && cd AERead
pip install -e ".[dev]"     # Python 3.10+
pytest -q                   # offline, deterministic, no API keys (~3 min)
```

New to the project? Read [docs/quickstart.md](docs/quickstart.md) (5 minutes,
rungs 1–2 need no keys) and [docs/concepts.md](docs/concepts.md) first.

## 1. Contribute a case

A case is one JSON file under `configs/exchange_economy/` (case sets live in
versioned subdirectories, e.g. `cases_v0/`). Anatomy:

```jsonc
{
  "name": "my_case",
  "description": "what this case is and why",           // required
  "intended_capability": "what passing demonstrates",   // required for new cases
  "interpretation_if_failed": "what failing means",     // required for new cases
  "num_agents": 5, "num_resources": 5, "rounds": 4, "seed": 1105,
  "units_per_home_resource": 10, "utility_mode": "concave_separable",
  "controllers": [1, 1, 1, 1],
  "protocol": { /* visibility, atomic_commit, ir_enforce, settlement limits,
                   communication/response scope, information reveal profile … */ },
  "institution_pressure": { /* search costs, shocks, recurring demand */ },
  "roles": {
    "under_test": {"agents": [1], "policy": {"kind": "llm", "model": "…"}},
    "panel":  [{"agents": [2,3,4,5], "policy": {"kind": "frozen_llm", "model": "…"}}],
    "compiler": {"policy": {"kind": "frozen_llm", "model": "…"}},
    "verifier": {"policy": {"kind": "frozen_llm", "model": "…"}}
  }
}
```

The `roles` table is validated strictly (exactly one `under_test`; every agent
covered exactly once; `compiler`/`verifier` may not be scripted; only
`under_test` may be `submitted`). Unknown keys elsewhere in the config are
currently ignored — double-check field names against
`aeread.exchange_economy.ProtocolConfig`.

**Admission gate (required before opening a PR):**

```bash
aeread baselines --configs 'configs/exchange_economy/your_case.json' --output-md /tmp/b.md
aeread validate-case --configs 'configs/exchange_economy/your_case.json' --strict --gate
```

The gate enforces, provider-free: meaningful attainable surplus; an
individually-rational path to it; the non-triviality ordering
`no-op ≤ random < greedy < ceiling` (a case that random walks can ace, or that
greedy saturates, measures nothing); and bounded hidden-information gaps.
Budget ~2 minutes of CPU per case.

**Calibration note:** the gate's default thresholds and strict heuristic
orderings were frozen against the `v1_ladder_*`/`v1_main` family; on the
`cases_v0` set they currently report threshold rejections and ordering ties
(recorded in `configs/exchange_economy/v1_manifest.json`). cases_v0 was
admitted on the empirical non-triviality ordering (`no-op ≤ random < greedy <
model-ceiling` holds on all five cases on dev and held-out seeds). For a new
case PR, include the full gate output — maintainers review the numbers and
orderings, they do not require a mechanical `accept` verdict; recalibrating
the thresholds per case family is an open item.

Dev seeds are public; official evaluation adds private held-out seeds that
never ship in this repo.

## 2. Submit an agent / results

Implement the text-boundary contract (your code never receives world objects):

```python
class MyAgent:
    def act(self, observation: str, phase: str) -> str: ...
```

Run the submission harness and open a PR containing your
`submission_report.json` (and, if you want a *verified* row, a way for us to
run your agent — a pip-installable package exposing `module:Class`, or a model
name on a public endpoint):

```bash
aeread submit --cases configs/exchange_economy/cases_v0/case0*.json \
    --agent mypkg.myagent:MyAgent --out submissions/
```

What the report contains and how we audit it:

- a **case-set content hash** — reports are only comparable when hashes match;
- **replay verification** — the run is re-executed with your agent absent
  (every one of its actions was snapshotted) and must reproduce the trace
  byte-identically; we re-run this audit on every submitted report;
- per-case scores with denominator tiers, never silently pooled across tiers.

*Self-reported* = you ran it on public dev seeds. *Verified* = we reproduced
the replay audit and re-evaluated on the private held-out seed set. PRs are
labeled accordingly.

## 3. Contribute an integration

Connect AERead to another framework, memory system, or training stack. The
full guide (the two seams, replay semantics for stateful agents, layout
conventions) is [integrations/README.md](integrations/README.md); the short
version:

- importable code + offline deterministic tests in the package
  (`src/aeread/integrations/<name>.py`, `tests/test_<name>.py` — fake the
  external service and the LLM; `tests/test_everos_memory.py` is the
  pattern);
- guide + runnable example in `integrations/<name>/`;
- your integration drives only the under-test seat — panel/compiler/verifier
  stay frozen, or results stop being comparable;
- open a [new-integration issue](.github/ISSUE_TEMPLATE/new_integration.md)
  first if you want design feedback before building.

## 4. Code

```bash
pip install -e '.[dev]'
pytest tests/ -q        # provider-free; no API keys needed
```

- Python ≥ 3.10, no new runtime dependencies without discussion.
- Every behavioural change needs a test; the suite must stay green.
- Scoring-contract changes (anything touching `exchange_v1_scoring`,
  `aer_scorer`, denominator tiers, or the replay/manifest format) additionally
  need a design note in the PR description — these are the benchmark's
  auditability guarantees.

Note on provenance: `src/aeread/`, `tests/`, and `configs/` are periodically
synchronized from a private development repo (see `export_manifest.json`).
Upstream code PRs are welcome here — maintainers reconcile them with the
private tree when re-exporting; your authorship is preserved in the merge.
