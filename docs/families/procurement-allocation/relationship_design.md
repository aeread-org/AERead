# Procurement over periods: the award as a relationship

**Status:** built, offline-verified, one live pilot; no campaign identity
sealed. Implements §4 of the [economic primitives extension
design](../../research/economic_primitives_extension_design.md) (PR #213).

**What it adds.** The single-period family ends at `submit_award`. A case
that declares `interaction.periods` runs the same buyer over `T` sourcing
periods on the same BOM. The award becomes a period transition: the period
is scored exactly as a single-period award is, realized delivery is drawn
from a declared seed and written to a history the next period's observation
shows, every supplier's *standing* moves, and the next period opens with the
period-local state reset. Suppliers may declare a `relationship` block that
turns standing into terms: a loyalty discount per consecutive award, a
capacity reservation for the incumbent, and a retaliation markup for a
supplier quoted and then dropped. The reference is an exact finite-horizon
dynamic programme over standing. Two full-information references sit under
it, and a world is admitted only when the optimum beats both.

Nothing here changes a case that omits the block: the single-period
observation, bound and scores are byte-identical, and the existing
procurement suite passes unchanged.

## 1. The contract

```json
"interaction": {
  "...": "the single-period interaction block, max_actions is per period",
  "periods": {
    "count": 4,
    "delivery_seed": 2510001,
    "overrides": [ {}, {}, {"target_kits": 30, "minimum_service_kits": 24}, {} ]
  }
}
```

- `count` in [2, 8]. `episode.max_logical_actions` in the manifest is
  `max_actions × count`; the kernel cap is per episode, the case budget per
  period.
- `delivery_seed` drives the realized-delivery draws and nothing else.
- `overrides`, optional, one object per period, may change `target_kits`,
  `minimum_service_kits`, `cash_budget_usd`, `revenue_per_completed_kit_usd`,
  `shortfall_penalty_per_kit_usd`, `deadline_days`. The buyer sees the whole
  plan as `period_schedule`.

```json
"private_terms": {
  "...": "the single-period terms",
  "relationship": {
    "loyalty_discount_per_award": 0.08,
    "loyalty_discount_cap": 0.24,
    "incumbent_capacity_bonus": 10,
    "retaliation_markup": 0.06
  }
}
```

All four fields are required when the block is present; a block without
`periods` is a validation error. A supplier without the block trades the same
every period.

**Standing** per supplier is `(consecutive_awards, retaliation_periods_left)`.
At a period's close: awarded → streak +1, grievance cleared; quoted and not
awarded → streak 0, retaliation for exactly one period; not approached →
streak 0, any grievance lapses. A rejected award counts as not awarded.

**Effective terms** this period: quote and floor both scale by
`(1 − min(cap, rate × streak)) × (1 + markup if retaliating)`; capacity
gains the bonus while the streak is positive. The formal offer carries a
`relationship` field stating the schedule and what was applied, so the
programme is learnable at quote time. Listings and verbal bias are untouched.

**Period close.** `submit_award`, `defer` or an exhausted budget ends the
period. The period's margin is `evaluate_award` on that period's objective,
or `defer_value − information_cost` for a defer or an exhausted budget.
Realized delivery is drawn per awarded line: on-time from the true
probability (never, if the lead time overruns the deadline), defects
binomially at the true yield, with the seeded counter-based draws the family
already uses. The buyer's history shows award lines, feasibility and
violations, cash and information spend, and the delivery record; it does not
show the margin, exactly as the single-period buyer never sees its score.
Formal offers lapse; verified samples and verbal claims persist; offer ids
keep counting so they stay unique across the episode. An invalid action ends
the episode where it stands: the interrupted period scores as an exhausted
budget and every later period at its outside option.

**Outcome.** `contribution_margin_usd` is the sum of period margins;
`upper_bound_usd` the T-period optimum; `regret_to_upper_bound_usd` their
difference. `feasible` requires every period to end by a passed award or an
explicit defer; `feasible_award` requires every period awarded. Secondary:
`periods_awarded`, `period_decisions`, `period_margins`, `switches` (periods
whose non-empty awarded set differs from the previous non-empty one),
`realized_on_time_rate`, and the two references. Every scorer field the
single-period leaf reads is present and summed.

## 2. The reference and the two under it

`relationship.solve_relationship_upper_bound` is a dynamic programme over
`(period, standing)` where standing carries, per supplier, the streak, the
grievance and whether a verified sample exists. Per period it enumerates
every awarded set, every mode (base or negotiated to the floor) and every
admissible quantity, exactly as the single-period bound does, and charges
quote, sample (once, ever) and counter actions, days and cost. It also
allows *prequalification*, sampling a supplier without awarding it, because
a later period with a binding action budget, deadline or cash budget could
be worth it; the variants are derived from one evaluation per plan and
re-scored exactly only when a sample would push a line past its deadline.
The optimum is therefore exact for the action model the environment
exposes, and `test_every_world_admits_and_its_bound_is_attainable` replays
each world's optimal plan through the environment and reaches the bound to
the cent. A brute-force enumeration on a two-supplier three-period world
agrees with it.

- **myopic**: each period's best plan given the standing it inherits, the
  future ignored; it uses loyalty it has earned, never invests in it, and
  prices a qualification sample into every period it has not yet paid it.
- **loyal**: the first period's myopic choice re-awarded every period,
  quantities and mode re-optimized; it defers a period the set cannot serve.

The screen (`headroom_screen.classify_relationship_world`) rejects a world
whose optimum is within 5% of either reference (`trivial (myopic)`,
`trivial (loyal)`) or does not beat the summed outside option (`floored`).
The margin is measured against the T-period optimum, the same materiality
rule as the Gate 1 continuous screen.

## 3. The six worlds

`cases/procurement_allocation_v1/relationship_v1/`, generated by
`relationship_case_matrix.py` and refused at generation if the screen does
not admit them. Four periods, ten actions each, twenty kits (the ramp world
varies), two components with two suppliers each. One component carries the
stratum's tension; the other a trap or nothing.

| World | Tension (guard) | Trap (buyer) | Bound | Myopic | Loyal |
|---|---|---|---:|---:|---:|
| `loyalty_investment` | partner 2.5% dearer today, 8%/award to 24% | retaliation 6% on both | 413.14 | 388.60 (−5.9%) | 388.60 |
| `qualification_investment` | unproven 30% cheaper, $9.50 sample no period recovers | — | 401.85 | 380.78 (−5.2%) | 380.78 |
| `demand_ramp` | targets 10, 10, 30, 30; only `scale` fills 30 and rewards prior awards | small supplier cheapest early | 422.09 | 395.21 (−6.4%) | 85.98 (−79.6%) |
| `incumbent_capacity` | `flex` fills half until incumbent, then all at a growing discount | a split today costs a little more | 407.51 | 380.78 (−6.6%) | 380.78 |
| `retaliation_trap` | as `loyalty_investment` | displays priced a cent apart, 15% retaliation | 416.83 | 392.30 (−5.9%) | 392.30 |
| `unreliable_incumbent` | as `qualification_investment` | cheapest controller lies about reliability verbally; its quote and history tell the truth | 413.19 | 392.12 (−5.1%) | 392.12 |

Myopic and loyal coincide wherever the myopic path never switches, which is
every world but the ramp; there the myopic buyer switches twice and the loyal
buyer defers the two volume periods. The optimum switches once on
`incumbent_capacity` (split, then single-source) and nowhere else.

## 4. Choices the design left open, and what was chosen

- **Discount on the quote, not only the floor.** §4 says "a loyalty
  discount on the price floor". A floor-only discount is invisible unless
  the buyer counters, so the schedule shifts quote and floor together and the
  quote says so.
- **Defer is a period action.** Deferring skips one period at its outside
  option; the episode continues. Ending the episode on a defer would make
  "no order this quarter" indistinguishable from walking away for good.
- **Qualification persists.** A verified sample is a fact about the
  supplier, and re-charging it would make the qualification-investment
  stratum impossible.
- **Scored on expectation, realized for information.** Period margins use
  the family's expected-units scorer; the seeded draws only feed history.
  A plan's score never depends on a draw, so the bound stays exact and the
  seed changes what the buyer knows, not what it earns.
- **Forfeited periods score at the outside option.** The single-period
  family's floor, applied once per period.
- **Per-period objective overrides.** Not in §4. Without them a
  full-information optimum never switches supplier, so the `switches`
  endpoint would be dead; a demand plan is the smallest world change that
  makes switching optimal.
- **Not built:** `search_market` (§2.1 solicitation) and the within-period
  concession schedule (§2.2). Both are shared mechanics with their own
  guards; the standing and history state here is where they attach.

## 5. What a result here may claim

The same boundary as the family: one route's descriptive cumulative margin
and regret per world, `switches`, `periods_awarded` and the realized on-time
rate, never a winner or a model ranking. Six worlds is a development panel,
not a variance pilot: the independent unit is the world, and no interval is
computable from one seed. The single-period construct gate is `failed` and
this extension does not reopen it; it adds a construct the single-period
worlds cannot express and a screen that says when a world expresses it.

## 6. Live pilot

Recorded in §7 once run. Route, seed, temperature, per-trajectory cost
ceiling and attempt count are frozen in
`tools/run_procurement_relationship_pilot.py`; the run directory is
gitignored under `runs/` and nothing from it is evidence-lane.
