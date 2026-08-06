# Integrations

AERead is designed to plug into other agent stacks without either side
forking: the arena exposes two small, stable seams, and every integration is
built against them.

## The two seams

| Seam | Contract | Use it for |
|---|---|---|
| **Submitted agent** (text boundary) | `act(observation: str, phase: str) -> str` — your agent sees exactly the per-phase prompt an LLM seat would see, nothing else (no world object). Driven by `aeread.exchange_v1_submit.run_submission`. | Evaluating any agent: your framework, your memory layer, your fine-tune. Replay-verified scoring. |

Everything else — frozen panel, compiler, verifier, seeding, scoring,
manifests — is the arena's job and identical across integrations, so results
stay comparable.

## Current integrations

| Integration | What it does | Guide |
|---|---|---|
| **[EverOS](https://github.com/EverMind-AI/EverOS)** (EverMind) | Persistent cross-episode memory as a *treatment arm*: a submitted agent that searches an EverOS server before every action and writes each finished episode + outcome back. Ships a memory-on vs memory-off A/B runner. | [everos/](everos/README.md) |

Code lives in the installable package (`src/aeread/integrations/`) so entry
points and imports stay stable; each folder here is the human side — guide,
examples, and caveats.

## Adding an integration

1. **Pick the seam.** Evaluation/memory/tooling → the submitted-agent
   contract.
2. **Keep the arena frozen.** Your integration may only drive the under-test
   seat. Panel/compiler/verifier stay on their pinned models — that is what
   makes scores comparable across integrations.
3. **Code + tests in the package**, guide + example here:
   `src/aeread/integrations/<name>.py`, `tests/test_<name>.py` (offline,
   deterministic — inject fakes for servers and LLMs; see
   `tests/test_everos_memory.py` for the pattern), `integrations/<name>/README.md`.
4. **Declare replay semantics.** If your agent is stateful across episodes
   (memory, learning), say so and run with `verify_replay=False` — official
   leaderboard submissions must be replay-verified, so cross-episode state
   needs a recorded-state manifest before it can be a leaderboard row.
5. Open a PR using the "New integration" issue template first if you want
   design feedback before building.
