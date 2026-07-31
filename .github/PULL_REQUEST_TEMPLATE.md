## What

<!-- one paragraph: what this PR does and why -->

## Type

- [ ] New case (`configs/…`) — attach the `aeread baselines` output showing `no-op ≤ random < greedy < ceiling`
- [ ] New integration (`src/aeread/integrations/` + `integrations/<name>/`)
- [ ] Core code / fix
- [ ] Docs

## Checklist

- [ ] `pytest -q` green locally (offline, no keys needed)
- [ ] New behavior has offline, deterministic tests (fakes for servers/LLMs — see `tests/test_everos_memory.py` for the pattern)
- [ ] No response caches, run outputs, API keys, or held-out seeds in the diff
- [ ] Scoring-contract changes: none, or explicitly called out below (tier mixing, clipping, gate semantics are frozen surfaces)
