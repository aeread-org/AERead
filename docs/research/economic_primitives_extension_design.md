# Economic primitives the map lacks: three extensions and two shared mechanics

**Status:** design; nothing here is built. Written 2026-09-21 after the second
datacenter confirmatory, before any code.

**Decision:** extend three existing families rather than start new ones —
coalition / joint funding as a datacenter joint venture, repeated relationships
with reputation as multi-period procurement, refusal under adverse selection as
housing with hidden unit quality — and give every scripted counterparty two
mechanics the profiled families lack today: discoverability (counterparties
that must be found) and strategy (a private reservation with a declared
concession schedule). Each extension is a new campaign identity with its own
guard, controls and pilot.

**Case type:** the same case types as the host families. No new environment,
no new scorer kernel; new world strata, one new phase or period loop per
family, new scripted-seat policies, and one new endpoint (the principal's
payoff, for housing).

## 1. Why these three

A six-family / five-primitive framing of economic interaction — exchange,
allocation, complementarity, asymmetric information, intertemporal choice,
crossed with information, motive, repetition, party count, counterparty
discoverability and stochasticity — maps onto the 22 families in
`src/aeread_families/` as follows.

| Primitive | Measured (profiled, live evidence) | Present, unmeasured | Absent |
|---|---|---|---|
| Exchange (bilateral) | termsbench | negarena, amazonbarg, agenticpay, `exchange_v1` case01 | — (six families; over-covered) |
| Allocation / matching | procurement_allocation, housing | aucarena, alympics_wac | — |
| Complementarity | datacenter (inside one agent's stack) | consent_ir cycles, bundle-under-budget (unscored) | **joint funding across agents; free-riding** |
| Asymmetric information | termsbench, procurement information splits, datacenter verbal/written, refund | `exchange_v1` case03/04 | **adverse selection / no-surplus worlds; refusal** |
| Intertemporal | econevals periods, govsim (adapter) | collusion, econagent | **repeated relationships with reputation or credit** |
| Discoverable counterparties | — | `exchange_v1` case03 only | as a scored family |
| Strategic counterparties | — | `policies.<seat>.utility` on one datacenter seat | in every profiled family the other side is a band or a script |

Bilateral bargaining is the least scarce capability in the map and the
capability that produced every finding of the datacenter campaigns was
composition plus information, not price. The three absences are the parts of
an economy where other agents must matter. The two missing dimensions are
what turns a scripted seat from a wall into a counterparty.

## 2. Shared mechanics

Both are world data, declared in the case and applied by the environment; the
harness never judges a move (the TERMS-Bench rule, TB-D-02). Both get a guard
in the family's admission gate.

### 2.1 Solicitation: counterparties that must be found

Pattern from `cases/exchange_v1/v0/case03_hidden_discovery.json`
(`direct_contact_scope`, `public_broadcast`, `solicited_public`), lifted into
a phase any family can declare:

- the observation lists only counterparties already **contactable**: a small
  `direct_contact_scope` known at the start, plus any that replied;
- a `solicit` action broadcasts a request on a public board at a declared cost
  in days and money (the `inquiry_cost_usd` / `inquiry_days` pattern of
  procurement, `environment.py:286-325`); hidden counterparties reply
  according to their own declared rule (interest threshold on the broadcast
  terms), and a reply makes the seat contactable;
- a `contact` action reaches one named counterparty directly at a smaller
  cost.

Guard: at least one counterparty on the reference path must be hidden at the
start, and the reference path must beat the best path over the initial
contact scope by a declared margin (search must pay).

### 2.2 Concession policy: a reservation the seat moves toward

Every scripted seat today accepts inside a band and otherwise returns one
fixed counter package (`policies.<seat>.counter_terms`,
`stack_environment.py:terms_acceptable`; housing's midpoint counter,
`housing/environment.py:709-734`; procurement's floor test,
`procurement_allocation/environment.py:511-573`). Pushing back is therefore
never rewarded and, under a round cap, is punished. The replacement:

```
concession:
  opening: <package>              # the first counter, as today
  reservation: <package or scalar>  # private; the seat never goes past it
  fraction_per_round: 0.35        # of the remaining distance to the reservation
  retaliation: { trigger: <rule>, floor_shift: <fraction> }   # optional
```

The seat's counter in round r is `opening + (1 - (1-f)^r) · (reservation -
opening)` per term, clipped at the reservation; acceptance stays the band /
valuation rule (`counterparty_utility`, `stack_environment.py:230`). Round
caps rise from 3 to 5 where the policy is declared.

Guards: `concession_is_free` (the reservation must differ from the opening on
at least one term the reference uses) and `reservation_unreachable_by_
persistence` (a scripted policy that only re-offers cannot reach the
reservation inside the cap). The scripted reference negotiates to the
reservation, not the opening, so "copy the counter" stops being near the
reference — which is the separation the datacenter controls currently lack.

## 3. Datacenter: joint venture (coalition / joint funding)

**World.** Two developers on adjacent sites; one utility feeder can serve
both. A solo interconnection costs each developer `C_solo`; the shared feeder
costs `C_jv < 2·C_solo` once. The ledger already books interconnection to
month-0 development cost (`stack_cashflow.py:169-173`); the JV world books
each developer's declared share of `C_jv` there instead, and energization for
both depends on the feeder being funded (`energized_capacity_kw_by_month`).

**Phase graph.** Before `power`: `jv_developer_offer` (kernel mode
`simultaneous`, both developers act on a frozen state; `scheduler.py:25,790`)
→ `jv_utility_response` → `jv_developer_commit`. The JV executes only if the
shares sum to at least 100% and the utility's band holds; otherwise each
developer proceeds to its own solo power agreement at `C_solo`. `eligible_
actors` (`stack_environment.py:681`) returns one seat per phase today; the JV
phase returns both developers.

**Trap.** Offering a 0% share still energizes the site if the partner covers
100% — the attractive path. Whether it works depends on the partner, so the
scripted partner type is a stratum: pro-rata (funds its capacity share),
conditional cooperator (funds only if the other's offer covers its own share),
free-rider (offers 0%, signs whatever is funded). Live-vs-scripted-partner is
the controlled condition; live-vs-live uses the model-to-model setup that
already exists (`stack_runner.py:862`) and is a separate condition, never
pooled.

**Discoverable.** Three candidate neighbours; one has a compatible
energization window and capacity. They appear only through §2.1.

**Strategic.** The utility already carries a valuation with a reservation; it
gets §2.2. The landowner and lender get §2.2 in the same stratum so that the
JV world is also the first world with conceding seats.

**Reference, controls, guard.** Reference: pro-rata JV, then the floor path.
Controls: walk-away; adopt-every-counter; a scripted free-rider. Guards:
`C_jv` must beat solo by the declared margin (the `lever_is_inert` pattern in
`stack_worlds.py`); free-riding must not be admitted on every partner
stratum.

**Endpoints.** Per-developer admission as today; coalition formed or not;
free-riding index = share paid − capacity share. Claims: descriptive per
partner stratum; no winner, no causal claim.

**Build.** Generator stratum and share term, one simultaneous phase and its
tie rule (shares that over- or under-sum; declared in the contract), two
scripted partner policies, the solicitation phase. About two days.

## 4. Procurement: repeated relationship with reputation

**World.** The same buyer sources the same BOM over `T = 4` periods from one
supplier population. Supplier traits are already private and persistent
(`on_time_probability`, `quality.verified_yield_rate`, `verbal_bias`;
`procurement_allocation/environment.py:346-467`). Each supplier gains a
declared `relationship` block in `private_terms`: a loyalty discount on the
price floor per consecutive award, capacity priority for the incumbent, and
retaliation — a supplier quoted but not awarded in the previous period raises
its floor for one period.

**Period loop.** Today the episode is one self-looping phase ending at
`submit_award` (`environment.py:1102-1115`) and `initial_state` carries
nothing across episodes (`:1082-1100`). The award becomes a period
transition: the realized delivery — on-time draw and defects, using the
seeded binomial machinery already present (`:217-240`) — is written to a
`history` the next period's observation shows. Reputation is the buyer's
posterior over persistent traits formed from its own realized outcomes; there
is no reputation field.

**Discoverable.** Not every supplier is listed; `search_market` (a §2.1
broadcast at a declared cost) reveals `k` new listings per period. Search
versus exploit the incumbent is the intertemporal choice.

**Strategic.** §2.2 within a period; across periods the floor moves by the
loyalty and retaliation rules.

**Oracle, controls, guard.** The full-information upper bound
(`solve_full_information_upper_bound`, `:758-905`) generalizes to `T`
periods with relationship state — branching over awards per period, pruned
under `UPPER_BOUND_ENUMERATION_LIMIT`. Controls: the existing `defer`,
`displayed_price_greedy`, `listing_claim_fit`, plus **myopic** (period-optimal,
relationship ignored) and **loyal** (always re-award the incumbent). Guard:
the `T`-period optimum must beat both myopic and loyal by a declared margin
(`headroom_screen.classify_world`, `headroom_screen.py:65-90`, extended), or
the world is trivial.

**Endpoints.** Cumulative contribution margin over `T` against the
`T`-period bound; secondary: switches, realized on-time rate against the
population, information cost.

**Build.** Multi-period state and transition, the `relationship` block, two
baselines, the `T`-period oracle. About three days; the oracle is the long
pole.

## 5. Housing: refusal under adverse selection

**World.** A fraction of listings are lemons with the same ask as sound
units. Landlord cost is already private (`make_bid_world`,
`housing/environment.py:216-218`); tenant value now depends on true quality,
with a pooled prior under which the expected value at the ask is below the
ask. An `inspect` action (declared cost, one per round) reveals quality.
Signing uninspected at the pooled price is adverse selection; refusing an
uninspected lemon is correct.

**Scoring — the one real change.** Welfare cannot score refusal: a lemon
signed above the tenant's value still adds `value − cost` while the tenant
seat loses (`economics()`, `environment.py:683-708`). The primary endpoint
becomes the **principal's** outcome: tenant realized payoff against the oracle
tenant payoff, abstention correctness (declined iff the expected value given
the tenant's signals is below the rent), and IR violations. Welfare stays as a
secondary. These are the principal-service and abstention axes
`CAPABILITIES.md` names and no family scores.

**Admission.** The gate drops zero-welfare worlds (`case_sweep.py:446-450`).
Refusal worlds need the inverted ordering `CAPABILITIES.md` anticipates for
adversarial cases: sign-anything < pass < inspect-then-sign, with
sign-anything strictly negative for the tenant.

**Discoverable.** Listings are hidden until contacted or solicited on the
board (§2.1), so search effort is real; today every listing is on the board
every round (`environment.py:381-395`).

**Strategic.** Landlords keep their private-cost reservation and gain §2.2 —
and lemon landlords concede faster. Price concession becomes a quality
signal, which is the adverse-selection mechanic itself.

**Existing.** `pass`, `reject_all` and `walk` are legal and score as silence
(`runner.py:678-751`); phases are already `simultaneous` (`runner.py:610-650`).
The only "no trade" artefact is the zero-upper-bound golden. The landlord
cost-floor controls discussed in September are not on `main`.

**Build.** Quality field, `inspect`, the tenant-payoff endpoint, the inverted
gate, §2.2. About two days.

## 6. What each extension may claim

Every identity keeps `winner_claim_allowed: false` and
`inferential_model_ranking_allowed: false`. Permitted: one route's descriptive
rates with world-clustered intervals per stratum — coalition formation and the
free-riding index; cumulative margin and switching under reputation; tenant
payoff and abstention correctness. Two routes on one pack give a paired
contrast with an interval (`confirmatory.analyze_two_routes`), not a ranking.
Not permitted: anything about negotiation quality in the absolute; the
reference is the generator's reservation path, not an optimum.

## 7. Order, effort, cost

1. **Housing refusal** — smallest, and it creates the principal-payoff endpoint
   the whole map lacks.
2. **Datacenter JV** — the ledger, seats and valuation hook are ready.
3. **Procurement periods** — the `T`-period oracle is the risk.

Roughly a week of build for all three before a paid cell. Pilots at the
current scale (24 worlds × 2 seeds, one route) cost $2–4 each; a two-route
confirmatory $8–15. Each is a new campaign identity: a changed world or
policy is never a rerun in place.

## 8. Open questions

- JV tie rule when simultaneous shares over- or under-sum (pro-rata scaling
  versus refusal): a contract control, to be declared before the pilot.
- Whether the `T`-period oracle must be exact or a declared bound; if a
  bound, the regret endpoint changes meaning and the profile must say so.
- Whether the tenant-payoff endpoint should net the inspection cost (it
  should; the oracle tenant payoff must then include the oracle's inspections).
- Whether §2.2 changes the sealed datacenter controls' reading: the adopter
  copies the *opening* counter, so under a concession schedule it will sit
  further from the reference — a stronger separation, but a different bundle.
