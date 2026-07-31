---
name: New case proposal
about: Propose a new scored world/protocol for the benchmark
labels: new-case
---

**Capability claim** — what does passing this case demonstrate, and what does
failing mean? (These become the config's `intended_capability` /
`interpretation_if_failed` fields.)

**World + protocol sketch** — visibility, communication scope, consent/IR,
settlement limits, institution pressure.

**Why existing cases don't cover it** — check
[CAPABILITIES.md](../../CAPABILITIES.md) first.

**Admission gate** — have you run `aeread baselines` on it? Paste the
ordering (`no-op ≤ random < greedy < ceiling` required):
```
```
