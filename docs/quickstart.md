# Quickstart

Four rungs, each one command deeper. Rungs 1–2 are fully offline.

## 0. Install

```bash
git clone https://github.com/aeread-org/AERead && cd AERead
pip install -e ".[dev]"          # Python 3.10+
pytest -q                        # ~3 min, no API keys, all offline
```

## 1. Run a case offline (no keys, seconds)

Scripted policies through the full arena — world building, negotiation
phases, settlement, scoring:

```bash
aeread run --config cases/exchange_v1/v0/case01_visible_bilateral_ir.json \
    --mode offline --seed 7 --out runs/
```

## 2. Baselines + validity gate (no keys, ~2 min/case)

Provider-free baselines (no-op, random, greedy) and the validity orderings
that make a case admissible (`no-op ≤ random < greedy < ceiling`):

```bash
aeread baselines --configs 'cases/exchange_v1/v0/*.json' --output-md baselines.md
```

## 3. One live episode (first API call)

Your model in the under-test seat, frozen panel everywhere else
(≈ $0.02 per episode with a flash-class model via OpenRouter):

```bash
export OPENAI_API_KEY=sk-or-...   # any OpenAI-compatible provider
python examples/run_episode_minimal.py \
    --case cases/exchange_v1/v0/case01_visible_bilateral_ir.json \
    --seed 1200 --model deepseek/deepseek-v4-flash
```

## 4. A scored, replay-verified submission

Wrap your agent in the text-boundary contract and run the exam — every seeded
case, replay verification, case-set content hash, per-case AER:

```python
from aeread.exchange_v1_submit import run_submission

class MyAgent:
    def act(self, observation: str, phase: str) -> str:
        ...   # your policy: any framework, any provider, any memory

run_submission(case_paths, MyAgent(), agent_label="my-agent")
# -> submissions/<id>/submission_report.json
```

See [submissions.md](submissions.md) for the contract details and
[concepts.md](concepts.md) for what the score means. From here:

- evaluate across models/seeds → `aeread sweep` (`exchange_v1_sweep`)
- train on AER as reward → [rLLM integration](../integrations/rllm/README.md)
- give your agent persistent memory → [EverOS integration](../integrations/everos/README.md)
- contribute a case → [CONTRIBUTING.md](../CONTRIBUTING.md)
