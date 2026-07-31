# EverOS integration — persistent memory as a treatment arm

[EverOS](https://github.com/EverMind-AI/EverOS) is an open-source,
markdown-first memory service. This integration
(`aeread.integrations.everos_memory`, experimental) turns it into a measurable
**treatment arm**: does persistent cross-episode memory change the welfare an
agent actually realizes?

- `MemoryCandidate` satisfies the text-boundary contract
  (`act(observation, phase) -> str`) while **searching** EverOS before every
  action (past episodes of the same case family) and **writing** each finished
  episode transcript + realized outcome back after scoring.
- `NullMemory` is the control: identical code path, no recall, writes
  discarded.
- Memory is scoped per case family via EverOS `project_id`. No information
  crosses the submission info-barrier — the agent only ever remembers what it
  itself observed through the text boundary in earlier episodes.
- Optional `distill=True` ends each episode with an LLM-written
  transferable-lessons reflection (explicitly forbidden from citing
  world-specific quantities — retrieval feeds these lessons into *different*
  worlds, where this episode's numbers are false).

## Setup

EverOS runs as a service (Python **3.12+** — on 3.11 pip resolves to an older
cloud-client package with a different surface):

```bash
pip install everos && everos init
# fill in [llm] and [embedding] in ~/.everos/everos.toml — any
# OpenAI-compatible endpoints work (OpenRouter serves both).
everos server start --port 8377
```

No rerank provider is needed: the integration searches with `method="vector"`,
which never reaches EverOS's reranker stage.

## Run the memory A/B

```bash
python integrations/everos/everos_memory_ab.py \
    --case configs/exchange_economy/cases_v0/case03_hidden_discovery.json \
    --seeds 1200:1212 --model deepseek/deepseek-v4-flash \
    --arms nomem,mem --distill --everos-url http://127.0.0.1:8377 \
    --out output/everos_ab
```

Episodes run sequentially in seed order so memory accumulates; per-arm output
is `results.jsonl` + `summary.json` (pooled AER `ΣW/ΣD`, seeded episode
bootstrap CI, snippet/error counts) and per-episode turn logs under `turns/`.

**First published result** (case03, deepseek-v4-flash candidate, 10 paired dev
seeds): memory-on **+0.144** vs memory-off **+0.085** pooled AER, paired delta
**+0.059 [95% CI +0.019, +0.103]** — with the lift concentrated in episodes
the memoryless control fails to settle at all.

## Caveats (deliberate, documented)

- **Replay:** cross-episode state means a replayed episode's *policy* is not
  reproducible from the manifest alone (byte-replay of recorded actions still
  passes). A/B runs use `verify_replay=False`; official replay-verified
  leaderboard submissions remain memory-off until a memory-state manifest
  (hash of the EverOS markdown tree per episode) makes memory pinnable.
- **Memory failures never fail an episode** — the agent degrades to memoryless
  and counts `memory_errors`. Check that column before believing an A/B: a
  dead memory server silently turns the treatment arm into a second control.
- **Extraction tracks:** stock EverOS gates its agent-case (strategy) track on
  tool-call rounds, which dialogue-only negotiation episodes never have — see
  the integration report for the measured consequences and the one-line
  upstream fix (`AgentCaseExtractor(min_tool_call_rounds=0)`).
