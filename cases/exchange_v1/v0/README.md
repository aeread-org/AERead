# Exchange v1 / v0 — the first official AERead case set

Four arena cases, one per headline family, each declaring a full `roles` seat table
(D9) so the D10 submission harness (`sprint/exchange_v1/submit.py`) can seat one
foreign agent in `under_test` against a **frozen panel** and score it with the D15
scorer (`sprint/exchange_v1/scoring.py` → carve-out contract v2: raw aggregate,
negatives preserved, `wstar_fallback` denominator tier).

Only the four `case0*.json` files directly in this directory belong to the
official scored set. `diagnostics/` contains panel-analysis artifacts and is
deliberately excluded from the default case glob and case-set hash.

| Case | Family | Seed | Rounds | Unsaturated? |
|---|---|---|---|---|
| `case01_visible_bilateral_ir` | bilateral gains-from-trade (calibration floor) | 1101 | 4 | no — separates no-op/random from anything that reasons |
| `case02_multiparty_clearing` | multi-party construction | 1102 | 4 | partial — >2-party settlements beyond the bilateral floor |
| `case03_hidden_discovery` | counterparty discovery / solicitation | 1103 | 6 | **yes** (the surfacing axis) |
| `case04_consent_under_hidden_info` | consent / exploitation-resistance | 1104 | 4 | **yes** (hidden allocations + private sign-off) |

Design decisions:

- **Candidate-driven**: `controllers = [1, 1, ...]` — the under-test seat proposes every
  round, so realized welfare is attributable to the submission (delegate-performance
  semantics; the frozen panel responds and consents but never drives).
- **Seat table**: `under_test` = agent 1 (`llm` kind by default; the harness rewrites it
  to `submitted` for foreign agents); panel = agents 2..N frozen `gemini-2.5-flash`;
  compiler/verifier = frozen `gemini-2.5-flash` (cost discipline — the compiler role is
  ~20-30x cheaper there with no measured quality loss).
- **Why the panel is 2.5-flash, not 3.5-flash**: the free-tier quota for
  `gemini-3.5-flash` is **20 requests/day/project** (measured 2026-07-16, quota id
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), which a single 4-round panel run
  exhausts. `gemini-2.5-flash` free tier sustains thousands of calls/day. A stronger
  panel (3.5-flash or cross-provider via OpenRouter) is a paid run — gated on the
  explicit cost checkpoint, and lands as a separate versioned panel for the
  panel-sensitivity phase rather than mutating this set.
- **Pinned seeds** (1101-1104): every submission faces byte-identical worlds, hidden
  values, and visibility draws; reports are comparable iff their case-set content hash
  matches (`submission_report.json: caseset_hash`).
- **No `pin_resolved_model` yet**: pins need the provider-resolved version string, which
  is only observable after a live run; freeze them from the first official panel run's
  manifest before leaderboard use.
- `case04` is the 10-agent `mech_private_acceptance_treatment` scaled to 5 agents /
  4 rounds for case-set cost discipline; its D1b baselines must be recomputed before it
  is used for admission decisions.

Baseline candidates (`sprint/exchange_v1/candidates.py`): `NoOpCandidate` and seeded
`RandomCandidate` run as submitted agents; the greedy floor runs as the
`scripted_bilateral_ir` under-test seat; a model runs as the `llm` under-test seat.
Non-triviality ordering to demand of every case: `no-op <= random < greedy < model-ceiling`.

**Still owed (tracked, not in this set):** probe-exact ports of the four unsaturated
`eval_dev` cases (market pricing / surfacing / negotiation-vs-frozen-seller / strategic
disclosure). Those need per-case Bayes denominators (`mc_wbayes`) or bespoke oracle
adapters, and land as
`cases/exchange_v1/v1` without disturbing this set's content hash.
