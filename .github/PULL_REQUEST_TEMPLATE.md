## What

<!-- one paragraph: what this PR does and why. If this is a draft, line one says why and what would make it ready. -->

## Lane

<!-- see docs/operations/pr_lanes.md; the pr-lanes workflow labels the PR, this is your declaration -->

- [ ] **kernel** (`src/aeread/shared_runner/**`, `src/aeread/cli.py`, `conftest.py`) — needs one approving review on the current head from someone other than me; reviewer: @
- [ ] **evidence** (`evidence/**`) — review is verification; the outputs are pasted below
- [ ] **family / docs** — CI green is the gate
- [ ] Stack: `n of N`, rooted in `main`, merge order: <!-- or "not stacked" -->
- [ ] I have ≤3 ready PRs open including this one

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

## Evidence verification (evidence lane only)

<!-- paste, do not describe: -->
- [ ] artifact digests match the manifest; nothing on disk unlisted
- [ ] prohibited-text scan clean
- [ ] replay / recompute reproduced state and score (`replay_family_receipt` or the bundle's script)
- [ ] `aeread errata` regenerated; affected-bundle rows unchanged or explained
- [ ] declaration matches measurement (`docs/getting-started/reviewing_trajectories.md` §3)
