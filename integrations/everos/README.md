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
    --case cases/exchange_v1/v0/case03_hidden_discovery.json \
    --seeds 1200:1212 --model deepseek/deepseek-v4-flash \
    --arms nomem,mem --distill --everos-url http://127.0.0.1:8377 \
    --out output/everos_ab
```

Episodes run sequentially in seed order so memory accumulates; per-arm output
is `results.jsonl` + `summary.json` (pooled AER `ΣW/ΣD`, seeded episode
bootstrap CI, snippet/error counts) and per-episode turn logs under `turns/`.

### Validity counters (read these before pooling)

Three failure modes here produce a valid-looking pooled AER rather than an
error, so each arm's `summary.json` carries a `health` block and the run exits
non-zero if any arm fails it:

| counter | what it catches |
|---|---|
| `blank_turns` / `blank_turn_rate` | muted turns: the candidate emitted nothing and the round scored as a deliberate no-op. Flagged above `--max-blank-rate` (default 10%). This is what invalidated the first published A/B. |
| `memory_snippets` | the memory arm injected nothing and is silently a second control. A live-but-empty server passes `memory_errors == 0`, so this is the only signal. Checked *during* the run too: an arm aborts after 3 completed episodes with zero injection rather than paying for twelve. |
| `memory_errors` | partial degradation to memoryless on some turns. |

The runner's own mute circuit breaker cannot cover this: it excludes
`submitted`-origin calls by design, because the no-op baseline is silent on
purpose, and the memory candidate enters through that same boundary.

**Measured results (corrected 2026-08-01).** An earlier version of this guide
reported a **+0.059 memory lift**. That result was an artifact: it was measured
through a client that silently dropped ~40% of the candidate's turns (a
completion-budget defect — reasoning consumed the token cap before any content
was emitted, and an empty utterance scores as a valid no-op). It has been
**retracted**.

Re-run on the fixed client with **three independent sequences per condition**
(case03, deepseek-v4-flash, 12 dev seeds each):

| | control (no memory) | memory (recap) |
|---|---|---|
| pooled, 34 paired episodes | **+0.114** | **+0.082** |
| paired delta | — | **−0.032** [−0.066, +0.002] |
| per-sequence deltas | — | −0.037, −0.045, −0.012 |

So: *memory helps* is refuted on this benchmark as integrated; *memory hurts*
is suggested but not established (the CI grazes zero). The control's
between-sequence SD is 0.014 — worth knowing before reading any
single-sequence memory comparison, here or elsewhere. What this result does and
does not license is in [LIMITATIONS.md](LIMITATIONS.md).

## Caveats (deliberate, documented)

Full detail, including what a result from this integration does and does not
license, is in **[LIMITATIONS.md](LIMITATIONS.md)**. The short version:

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
  [LIMITATIONS.md](LIMITATIONS.md) for the measured consequences and the
  one-line local override (`AgentCaseExtractor(min_tool_call_rounds=0)`).
