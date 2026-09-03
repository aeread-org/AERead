# Concepts

The vocabulary of the arena, in dependency order.

## World

A seeded exchange economy: agents with resource endowments and private
(concave, separable) utilities. Same case config + seed ⇒ the same world,
byte-for-byte. Worlds are built so that welfare gains are attainable — the
question is who realizes them.

## Case

One JSON config = world parameters + **protocol** (visibility, communication
scope, atomic commit, consent/IR enforcement, settlement row limits,
information-reveal profile) + **institution pressure** (search costs, shocks)
+ **roles**. Cases live in versioned sets (`cases/exchange_v1/v0/`)
and each declares what capability passing demonstrates. The current coverage
map is [CAPABILITIES.md](../../CAPABILITIES.md).

## Roles: one seat under test, frozen everything else

- **under_test** — the candidate (an LLM spec, or a `submitted` agent behind
  the text boundary).
- **panel** — the counterparty seats: frozen LLMs (temperature 0, cached,
  model-pinned) or scripted policies.
- **compiler** — turns the negotiation dialogue into concrete settlement rows.
- **verifier** — checks feasibility and authorization of those rows.

Freezing everything but one seat is what makes the score attributable to the
candidate rather than to the ensemble.

## Episode and the funnel

One run of a case at one seed: communication → proposal → response →
finalization → (optional) private acceptance, over N rounds, then compile →
verify → settle. Value is realized only if a deal survives the *whole* funnel
— an agent that negotiates brilliantly but phrases settlements the compiler
can't ground scores what actually settled: nothing.

## AER (Attainable-welfare Efficiency Ratio)

Per episode the scorer records `w_real` (realized welfare gain of the world)
and a `denominator` (attainable welfare gain under the case's **oracle
tier** — exact Bayes, Monte-Carlo Bayes, or W* fallback). The headline is the
pooled raw aggregate `ΣW_real / ΣD` per tier with a seeded bootstrap CI.
Contract:

- negatives are preserved (an agent can destroy value), values can exceed 1;
- a clipped companion (`aer_clip`) is presentation-only;
- failed feasibility/authorization gates zero the episode's `w_real` but keep
  its denominator;
- tiers are never pooled together; degenerate denominators are surfaced with a
  reason, never silently scored.

## Baselines and the admission gate

Provider-free baselines anchor every case: **no-op** (status quo), **random**
(seeded random legal actions), **greedy** (deterministic ledger-greedy
clearing). A case is admissible only if `no-op ≤ random < greedy < ceiling`
on its seed grid — worlds where naive strategies already saturate, or where
nothing separates action from inaction, are rejected.

## Replay verification

Every LLM call lands in an inference manifest with response snapshots.
`--mode replay` re-executes a run with **zero live calls** and must reproduce
the trace byte-identically; submissions are verified this way (the run is
replayed with the submitted agent absent, served from its recorded actions).
This is what makes results auditable by anyone, cost-free.

## Dev vs held-out seeds

Public dev seeds ship in the case configs. Held-out evaluation uses a private
seed set (kept out of this repository by design; `export_manifest.json`
documents the exclusion) so that reported held-out numbers cannot be tuned
against.
