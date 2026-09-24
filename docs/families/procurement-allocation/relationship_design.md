# Procurement over periods: the award as a relationship

**Status:** built, offline-verified; one live pilot, one three-seed variance
run and a second route on the same cells, the last two sealed as
`development_qualification` bundles. No confirmatory identity. Implements §4 of the [economic primitives extension
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

### 3.1 Generated packs: selected by rule, in disjoint seed domains

The six worlds above are authored. Two packs are generated:
`cases/procurement_allocation_v1/relationship_dev_v2/` (seed domain from
2420000) and `relationship_holdout_v1/` (from 2430000). Seed `s` is offered
to stratum `(s − start) mod 6`, its numbers are drawn from the stratum's
declared ranges by a generator seeded with `s`, and the world is admitted
when the screen admits it and the stratum is not yet full at two. Every
generated world declares binomial `sample_noise`, so a campaign seed, which
is re-sealed into it, reaches the evidence the buyer reads from period one
and seeds become replicates rather than repeats (P-D-01). Each pack's
`pack.json` records the rule, the seeds scanned, every exclusion with its
verdict, the admission rate, and per world the bound, the three references,
the headroom fractions and the outcome of each public-observation policy.

| Pack | Domain | Scanned | Admitted | Refused (all `trivial (myopic)`) | Admission rate |
|---|---|---:|---:|---:|---:|
| `relationship_dev_v2` | 2420000+ | 36 | 12 | 6 | 67% |
| `relationship_holdout_v1` | 2430000+ | 42 | 12 | 11 | 52% |

On both packs the displayed-price-greedy policy scores below deferral on the
retaliation worlds, and not in the way this paragraph first said ("quotes both
suppliers and drops one every period"). Traced action by action (P-D-04,
P-D-07): it quotes and samples all four suppliers in period 1, which runs the
clock past the last day an order can arrive, so it orders nothing; every
supplier it quoted and dropped marks up the next period; it re-quotes all four
each period, pads its order for delivery risk, finds the marked-up basket over
budget and orders nothing again. It never awards, and its negative margin is
its information spend. The competent `deadline_aware` rule recorded beside it
orders every period there. The holdout was generated after the prompt and the
tool were frozen and no live cell has read it.

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

## 6. Live pilot: Gemini 3.8 Flash, one seed, six worlds

Run 2026-09-21 with `tools/run_procurement_relationship_pilot.py` at commit
5495d115 (plan `014ecfdf…`), route `google/gemini-3.8-flash` pinned to
Google AI Studio at the datacenter campaigns' reviewed prices, reasoning
effort low, temperature 0, seed 73101, one attempt per action, $0.60 per
trajectory and $4 for the run. Six of six cells completed, every receipt
replayed live and re-audited from disk without a provider, 296,980 input and
11,414 output tokens, $0.2629 reported. The run directory is gitignored and
nothing from it is evidence-lane.

| World | Margin | Bound | Myopic | Loyal | Regret | Against myopic |
|---|---:|---:|---:|---:|---:|---:|
| `loyalty_investment` | 365.82 | 413.14 | 388.60 | 388.60 | 47.32 | −22.78 |
| `qualification_investment` | 357.46 | 401.85 | 380.78 | 380.78 | 44.39 | −23.32 |
| `demand_ramp` | 401.62 | 422.09 | 395.21 | 85.98 | 20.47 | +6.41 |
| `incumbent_capacity` | 357.46 | 407.51 | 380.78 | 380.78 | 50.05 | −23.32 |
| `retaliation_trap` | 395.19 | 416.83 | 392.30 | 392.30 | 21.65 | +2.89 |
| `unreliable_incumbent` | 369.58 | 413.19 | 392.12 | 392.12 | 43.61 | −22.54 |

Mean regret $37.91 on a mean bound of $412. All 24 periods awarded, 48 of
48 lines delivered on time, no violations, no switches.

**One routine in every world.** Fourteen actions each: sample both
components' chosen suppliers, quote them, award; then quote the same two and
award, three more times. No `inquire`, no `counter_offer`, no second quote in
any component, ever. The regret therefore decomposes cleanly. Where the model
chose the myopic reference's supplier (four worlds) its shortfall against
that reference is $22.5–23.3, which is the un-negotiated floor: the
reference counters to 94% of the quote and the model never counters. The rest
of each regret is the world's tension left on the table: the partner never
quoted, the unproven supplier never sampled, the flexible supplier never
tried.

**The relationship supplier was chosen twice, once by design and once by
chance.** On `demand_ramp` the model quoted `scale` from period one, the one
supplier able to fill the thirty-kit periods on the demand plan it was shown,
and beat the myopic reference by $6.41 without negotiating. On
`retaliation_trap` it chose `partner` and rode the discount to $2.89 above
myopic; on `loyalty_investment`, whose controller pair is identical, it chose
`spot`. A programme is not visible before a quote, so the choice between two
listings a cent apart was not informed by it, and with one seed the two
outcomes cannot be told from a coin flip. The retaliation and
verbal-reliability traps were never triggered, because the model never
shopped and never asked.

**What this says about the extension, not the model.** The environment ran
four periods through the kernel on a live route with standing, history and
receipts intact, at four cents a world, so a variance pilot at the family's
usual scale is affordable. The screen did what it was built for: on the
four worlds where the model behaved myopically it scored under the myopic
reference by exactly the negotiation gap, so the intertemporal headroom the
screen certified is measurable as a separate quantity. What the run cannot
say is anything about Gemini in general: one route, one seed, six curated
worlds, descriptive only.

**Tooling note.** At interpreter exit the run printed a closed-event-loop
traceback from the per-cell provider client's teardown, after every cell had
completed and sealed. The client is now closed inside the loop; the plan's
source hash for the tool records the bytes the run was made with.

### 6.1 Variance run: the same six worlds at three seeds

`procurement_allocation_relationship_gemini38_flash_variance_v1`, run
2026-09-21 at commit 56437642 on the same route and contract, seeds 73201,
73202 and 73203. A seed sets the inference seed and is re-sealed into the
world's `delivery_seed`, so the buyer's history differs between seeds from
period two on while the bound and references do not. Eighteen of eighteen
cells completed, every receipt replayed live and re-audited from disk,
$0.7958 reported, 72 of 72 periods awarded, 0 counters, 0 inquiries.

| World | Bound | Myopic | Regret by seed | Mean | Against myopic |
|---|---:|---:|---|---:|---:|
| `loyalty_investment` | 413.14 | 388.60 | 21.09, 21.09, 21.09 | 21.09 | +3.45 |
| `qualification_investment` | 401.85 | 380.78 | 44.39, 44.39, 44.39 | 44.39 | −23.32 |
| `demand_ramp` | 422.09 | 395.21 | 37.68, 20.47, 20.47 | 26.21 | +0.67 |
| `incumbent_capacity` | 407.51 | 380.78 | 50.05, 50.05, 50.05 | 50.05 | −23.32 |
| `retaliation_trap` | 416.83 | 392.30 | 21.65, 20.84, 46.14 | 29.54 | −5.00 |
| `unreliable_incumbent` | 413.19 | 392.12 | 43.61, 43.61, 43.61 | 43.61 | −22.54 |

Mean regret over worlds $35.81, 95% world-clustered bootstrap 27.24 to
44.06. Mean margin against the myopic reference −$11.68, 95% interval
−20.14 to −2.40: on this route the buyer sits below a period-by-period
optimizer that negotiates, and the interval excludes zero over six worlds.

**Seeds were repeats on four worlds and route draws on two.** The delivery
seed is hidden from the buyer and the period-one prompt is byte-identical
across seeds, so a deterministic route returns the same episode; four
worlds did, to the cent. On `demand_ramp` and `retaliation_trap` the three
seeds produced three distinct action routines, one of which quoted a third
supplier and paid for it ($17 and $25 under the other two). That variance
is the route's, not the environment's: the delivery draws never changed a
decision anywhere. On `loyalty_investment` all three seeds chose the
partner supplier where the single-seed pilot on identical bytes had chosen
the spot supplier, which is nondeterminism between runs rather than between
seeds. A variance design for this family therefore cannot rely on the
delivery seed to make replicates; the independent unit is the world, and a
tighter interval needs more worlds, not more seeds.

**What moved and what did not.** Every cell ran the same shape as the
pilot: sample, quote, award, re-quote, re-award, and never a counter. The
un-negotiated floor is again $22.5–23.3 on the three worlds where the model
matched the myopic reference's suppliers. Where it chose the relationship
supplier (`loyalty_investment` on all three seeds, `demand_ramp` on two,
`retaliation_trap` on two) it finished within $5 of that reference without
negotiating, which says the loyalty discount roughly pays for the missing
negotiation and no more.

### 6.2 Second route: GLM 5.3 Flash on the same cells, and the paired contrast

Jev (`typesafe/jev-1.13`) was asked for as the second route and could not
take the seat: it is a finite-choice decisions endpoint without seed,
temperature or reasoning, so it needs a menu adapter, and a menu is a
different interface, which would confound route with interface. The
family's own chat route, GLM 5.3 Flash on Parasail, ran instead on the
identical worlds, seeds and family bytes as the Gemini run
(`procurement_allocation_relationship_glm53_flash_variance_v3`, 2026-09-21).
Two earlier identities were spent and are recorded: v1 on Parasail's shared
pool returning 429 with no retry declared (P-O-01, P-T-07), v2 on my own
error of restoring edited family sources under the running campaign, which
the scorer hashes from disk at finalize (P-O-02, P-J-03). v3 declared three
attempts with retries on rate limits and 5xx and a stop after three
consecutive failures; it needed neither.

Eighteen of eighteen cells, $0.1978, 1,181,601 input and 45,040 output
tokens. Mean regret over worlds $109.02 (95% world bootstrap 73.38 to
144.48); margin against the myopic reference −$84.88 (−120.50 to −49.67).
Sixty-two of 72 periods awarded: ten awards were submitted and rejected,
nine for `minimum_service_not_met` and three for a supplier without a
verified sample, each scoring the period at its information cost. GLM
explores where Gemini did not: 34 inquiries, 4 counters, a third supplier
quoted in nine cells, six switches, three distinct routines on five of six
worlds. It also loses periods that Gemini never lost.

| World | Gemini regret by seed | GLM regret by seed | GLM lost periods |
|---|---|---|---:|
| `loyalty_investment` | 21.09, 21.09, 21.09 | 47.37, 47.42, 47.42 | 0 |
| `qualification_investment` | 44.39 ×3 | 134.10, 44.49, 44.59 | 1 |
| `demand_ramp` | 37.68, 20.47, 20.47 | 49.26, 198.54, 201.15 | 2 |
| `incumbent_capacity` | 50.05 ×3 | 140.41, 124.05, 124.10 | 3 |
| `retaliation_trap` | 21.65, 20.84, 46.14 | 147.94, 47.98, 48.18 | 1 |
| `unreliable_incumbent` | 43.61 ×3 | 43.86, 235.19, 236.24 | 3 |

**Paired contrast.** Per world and seed, averaged within world, Gemini's
regret is $73.20 below GLM's (95% world bootstrap −106.53 to −40.66), lower
on six of six worlds. This is a descriptive paired contrast between two
routes on six curated worlds, with an interval; it ranks nothing, and the
difference is dominated by GLM's rejected awards rather than by either
route's handling of the relationship.

**The shopping reference.** A fourth full-information reference now sits
beside the others: myopic, and quoting every supplier every period, so
every supplier it drops retaliates next period. On the six worlds it lands
$2.33 to $3.30 under the myopic reference (386.27, 378.31, 391.91, 378.44,
389.20, 389.65), the price of the extra quotes and of the days they cost
against the deadline. Every outcome and the screen now carry it. It is a
control, not a guard: the screen still admits on the myopic and loyal
margins.

**Published.** Both runs are sealed under `evidence/procurement_allocation/`
as `development_qualification` bundles with the frozen plan, every cell and
period row, the receipt projections, the re-audit from disk, the kernel
trajectory grain and each other's paired comparison. The single-seed pilot
of §6 stays a described local run.

## 7. Open

- Solicitation (§2.1) and the concession schedule (§2.2), so that finding a
  supplier and pushing back on one become decisions with a price.
- A variance pilot: the six worlds at three or more seeds on one route, then
  a frozen confirmatory on a held-out pack, before any interval is quoted.
- A frozen confirmatory on `relationship_holdout_v1`, powered on the
  world variance of a variance pilot on `relationship_dev_v2`; both packs
  exist and neither has been run.
- A menu adapter if a finite-choice route such as Jev is ever wanted in
  this seat, reported as its own interface condition.
