# Submitting an agent

The submission harness scores **any** agent — any framework, provider,
memory system, or hand-written policy — through one contract.

## The contract

```python
class MyAgent:
    def act(self, observation: str, phase: str) -> str:
        ...
```

- `observation` is exactly the per-phase prompt an LLM seat would see: your
  agent's private state plus the public transcript, rendered by the engine's
  own prompt builders. **The information barrier is total** — no world object,
  no other seat's private values, no oracle.
- `phase` is one of `communication / proposal / response / finalization /
  private_acceptance`.
- The returned string is your seat's utterance/action for that phase, parsed
  by the same funnel as every other seat (compiler grounds settlements,
  verifier checks feasibility + authorization).

## Running the exam

```python
from aeread.exchange_v1_submit import run_submission

sub_dir = run_submission(
    case_paths,                  # the seeded case set
    MyAgent(),
    agent_label="my-agent",
)
```

What you get in `submission_report.json`:

- per-case status + score row (`w_real`, `denominator`, tier) — pool as
  `ΣW/ΣD`;
- **case-set content hash** — reports are comparable iff hashes match;
- **replay verification** — the run is re-executed with your agent absent
  (its actions served from recorded snapshots) and must reproduce the trace
  byte-identically;
- per-seat inference manifest + cost split.

## Rules of the road

1. **Pre-flight validation** rejects malformed cases before anything runs or
   spends.
2. **A runtime failure in your agent never sinks the submission** — the
   episode is recorded as `harness_error` and excluded from the pooled score
   (watch that column: errors shrink your n).
3. **Statefulness within an episode is free** (your agent sees its own turn
   history if it keeps it). **Statefulness across episodes** (memory,
   learning) breaks policy-level replayability — run experiments with
   `verify_replay=False` and label results accordingly; official
   leaderboard rows must be replay-verified. See the
   [EverOS integration](../integrations/everos/README.md) for the measured
   memory treatment arm and the memory-manifest direction.
4. **Baselines are your floor**: report against no-op / random / greedy on
   the same seeds (`aeread baselines`). A model below the greedy floor is a
   finding, not a bug.
5. Dev seeds are public; held-out seeds are private. Tune on dev, report
   both, never ask for the held-out set.
