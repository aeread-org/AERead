# Appendices A–D: case specifications (draft, AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. Written from a reading of each
case's code at the branch heads named in each part; every rule and number traces to a file and
line listed in the replication note (`replication_note.md`). Companion to [Case studies](paper_case_studies.md) and
[Quality control](paper_qc_design.md). Amounts are in dollars for Housing and Procurement and in
$ thousands for Data center.

---

## Appendix A. Case specifications

Following TERMS-Bench [TB], we write each case as an environment Γ (outcomes, private types and their prior,
payoffs), a protocol (seats, order of play, actions, what each seat observes, termination), and fixed
counterpart policies (Appendix B). Refund is specified differently, as compliance with an authored policy and
protocol rather than a monetary payoff optimum (Appendix A.4). Symbols are local to each case, and each case's
table lists them together with the kind of quantity each one is. The subscript A denotes the evaluated seat and B a
counterpart. In controlled comparisons, the prior and the counterpart policies are fixed across evaluated agents;
head-to-head role swaps change the opponent as well, so they compare pairings rather than agents. Agent
configurations also differ in the settings recorded in Appendix H. We compute the reference policies of Appendix C
in the same Γ.

**Notation used across cases.** 𝟙[·] (or 𝟙(·)) is 1 when the condition inside holds and 0 otherwise. U(a, b) is a
uniform draw between a and b. 𝔼 is an expectation over the outcomes the case lists, and ⌊x⌋ rounds x down. D denotes
each case's loss: the lemon loss ($1,000) in Housing and the value of supplying nothing (−$600) in Procurement.
Each case's table defines its other symbols, and Appendices C and D refer back to it when they reuse one.

**Terms used across the cases.** A *world* is one fully specified environment instance of a case, that is, its
parameters and hidden types, fixed by a seed. An evaluation set is a published set of worlds that can be
regenerated from their seeds, and its inclusion criterion, computed before any agent plays, decides which generated
worlds enter it. A *seat* is a player position (the tenant, a landlord, the buyer, the integrator); the evaluated
agent holds one seat, and scripted policies or other agents hold the rest. An episode is one play of one world
under one condition (in Housing, one world and one landlord kind). A frozen configuration (such as v14 or v15) fixes
an evaluation set, a task prompt, the counterparts and the controls; changing any of them creates a new
configuration. A comparison is pre-registered when its plan and analysis were committed to the repository before any
of its episodes ran. A *reference* is the policy or bound against which a case measures a shortfall, with its access
to information stated (Appendix C). A *gate* is one of the six quality-control gates of Section 6, numbered 0 to 5:
a check that a result must pass before it is reported as qualified.

### A.1 Housing: lemons with outside demand (frozen configurations v14 and v15)

The v15 configuration uses the same rules as v14. Its task prompt states the landlords' pricing rule, its worlds come
from a screened evaluation set (Appendix E.2), and its holdout sets the outside-demand rate to 0.3 a round.

**Environment.** A world seed w fixes four listings ℓ ∈ {0, 1, 2, 3} and six tenant seats.
Seat 0 is the evaluated tenant, seat i ∈ {1, …, 4} is the outside demand for listing i − 1, and seat 5
never acts. Exactly m = 2 listings are lemons, Λ ⊂ {0, …, 3}, drawn uniformly from a random
stream separate from the one that sets values, asks and costs. Seat 0 signs at most one lease
(ℓ, rent), or none. Its payoff after signing ℓ with k inspections is

[[eq A.1]] u_A = v_ℓ − D·𝟙[ℓ ∈ Λ] − rent − c·k, and u_A = −c·k if it signs nothing,

where D is the lemon loss and c the inspection fee (Table A.1).

Seat 0 privately knows v_ℓ, its value for each listing if the listing is sound. Each landlord privately knows
its listing's quality and cost. The prior is uniform over the six possible lemon pairs. The
landlord kind is not drawn: both kinds are played on every world.

Every landlord has a target rent: it accepts any offer at or above the target and answers a lower offer with a
counter at the target (Appendix B.1). The two kinds differ only in where the target comes from. A *leaky* landlord
prices off its own cost. A lemon costs its landlord $1,000 less, so a lemon's landlord will rent for about $1,000
less than a sound listing's landlord, and an offer between the two rents is accepted only by a lemon's landlord: the
acceptance itself shows that the listing is a lemon. A *pooled* landlord prices every listing as if it were sound, so
its replies carry no information about quality. Each world is played once under each kind.

**Table A.1. Housing parameters.**

| Symbol | Meaning | Value |
|---|---|---|
| T | rounds | 3 |
| m | lemons | 2 of 4 |
| D | lemon loss (cuts the tenant's value and the landlord's cost alike) | $1,000 |
| c | inspection fee | $25 |
| a_ℓ | ask | ⌊U(1500, 3200)⌋ |
| v_ℓ | seat 0's value if sound | a_ℓ + 10·s_ℓ + U(−20, 20), with s_ℓ = 100(0.6·κ_ℓ + 0.4·ι_ℓ) − 30 and κ, ι ~ U(0, 1); κ_ℓ and ι_ℓ are listing attributes shown on the board, which move seat 0's value but say nothing about quality |
| c^S_ℓ | a sound listing's cost | max(0, a_ℓ − U(20, 80)) |
| c^L_ℓ | a lemon's cost | max(0, c^S_ℓ − 1000) |
| μ | landlord margin: a landlord's target is its reservation plus μ, capped at the ask (B.1) | $25 |
| β | outside-demand rate per round | ½ (v15's holdout: 0.3) |

In the main evaluation set, asks range from $1,501 to $3,198, and seat 0's gain v − a ranges from −$275 to +$676.

**Protocol.** Each round r = 0, 1, 2 has four phases. (1) *Inspect*: seat 0 may pay c to
inspect one open listing it has not yet inspected, and the quality appears in its observation at once.
(2) *Contact*: seat 0 makes one offer (ℓ, x) with ℓ open and x ≥ 0, or passes; offering again on
a listing it walked away from is legal. (3) *Respond*: each landlord applies its policy (Appendix B.1) to its
inbox, and each listing creates at most one binding hold. (4) *Commit*: a seat holding a hold signs
or walks; a missing or invalid action counts as a walk, and every hold expires at the end of the phase.
Signing ends seat 0's play, and the market ends after round 2 or when every listing is leased.

**Observation of seat 0.** Seat 0 observes the board (asks, uninformative listing attributes, and whether each
listing is open or leased), its rejected listings and active hold, its values v, the lemon count and share, the
loss, the fee, its own inspections and spending, and a history field (`your_history`) that lists its own offers,
each hold with the binding rent and whether the landlord accepted or countered, and each sign or walk. The sealed
prompt states the payoff, that a fixed landlord "may accept or make one binding counteroffer",
that "a counteroffer can itself convey information about listing quality", the departure rule,
that a listing seat 0 bid on is protected in that round, the three-round horizon, that walking does
not close a listing, and the order of the phases. The v14 prompt states neither the landlord's pricing
rule nor the cost range. The v15 task prompt states both: a sound landlord accepts any offer at or above its cost
plus $25 (or the ask, if lower) and otherwise counters at that amount, and since a sound listing's cost is $20 to $80
below its ask, a rent more than $55 below the ask proves a lemon.

**Example: a reply and a signing.** A listing asks a = $2,400. Its sound cost is c^S = $2,350, so
a lemon's cost is c^L = $1,350, and seat 0 values the listing at v = $2,600 if sound. With the $25 margin
(Appendix B.1), a sound listing's landlord targets $2,375, a lemon's leaky landlord $1,375, and a lemon's
pooled landlord $2,375. Suppose seat 0 offers $2,000. A sound landlord counters at $2,375, and a pooled lemon
landlord also counters at $2,375; a leaky lemon landlord accepts at $2,000, and only a lemon's
landlord would, so the acceptance itself identifies the lemon. Signing pays v − rent = +$225 for the
sound listing at $2,375, v − D − rent = −$400 for the leaky lemon at $2,000, and −$775 for the
pooled lemon at $2,375. Inspecting first costs $25 and reveals the quality under either kind. Had
seat 0 offered $0, the leaky lemon landlord would have countered at $1,375, which also identifies the
lemon, and signing at that rent pays +$225.

### A.2 Procurement: pay or test (the earlier evaluation set)

**Environment.** One buyer sources one component. The suppliers are one recorded supplier E (an established
supplier with a sales record) and three newcomers N₁–N₃. Each supplier has a type θ ∈ {G, L, P} = {(on-time 0.97,
yield 0.97), (0.55, 0.97), (0.97, 0.55)}, that is, good, late or poor-yield; E is always of type G. Newcomer types
are independent. Newcomer i's prior is read from the cohort record of its seller kind, in which aᵢ of 40 tracked
sellers were unreliable on delivery and bᵢ failed inspection:

[[eq A.2]] πᵢ = (γᵢ, λᵢ, ρᵢ) = ((40 − aᵢ − bᵢ)/40, aᵢ/40, bᵢ/40).

The three newcomers therefore have 3³ = 27 type profiles, each with positive probability, and γ ranges from 0.2
to 0.7.

**Table A.2. Procurement parameters.**

| Quantity | Value |
|---|---|
| Kits owed / minimum service | 50 / 40 (an award completing fewer than 40 is void) |
| Revenue per kit / shortfall penalty | $37 / $12 per kit short |
| Supplying nothing, D | −$600 (= −12·50), less any information already spent (the payoff is D − I) |
| Cash budget | $2,500 (never binds) |
| Deadline T | 10–12 days (clock "none"), 13–14 (tight), 17–18 (loose) |
| Action budget | 10 |
| Order sizes | 50, 55 or 60 units (minimum order quantity, MOQ, 50; step 5; capacity 60); shipping $0.60 a unit |
| E | price U[24, 28] rounded to $0.05; lead 6 days; sample $30 and 2 days; a record of 48–96 orders, 3% late, 3% defective |
| Newcomer i | price p_E(1 − δᵢ), δ drawn without replacement from {3, 5, 7, 9, 12, 15, 18, 21}%; lead 6–8 days; sample $30–80 in $10 steps and 3 days |
| Cohort record | aᵢ ∈ {4, 8}, bᵢ ∈ {8, 14, 20, 24} of 40 |

**Payoff.** An award of q units at price p from a supplier with yield y, on-time rate r and lead time ℓ, made on
day t after spending I on information, is worth

[[eq A.3]] M = 37·k − 12·(50 − k) − C if k ≥ 40 and the order is valid, and M = D − I otherwise,

where the number of kits completed is

[[eq A.4]] k = min(⌊q·y·r⌋, 50) if the order arrives by the deadline (t + ℓ ≤ T), and k = 0 if it arrives late,

and the cost C is the sum of the terms in the following table:

| Term of C | What it is |
|---|---|
| q·p | the purchase |
| + 0.6·q | shipping, $0.60 a unit |
| + q·p·0.12·15/365 | financing the purchase at 12% a year for 15 days: the 45-day working-capital horizon less the 30-day payment terms |
| − R | the expected refund on defective units |
| + R·0.12·10/365 | financing the refund, which arrives 10 days after the claim |
| + I | the information bought |

Here R is the expected refund on defective units: of the q·(1 − y) defective units, 90% of claims are accepted and
refunded at the unit price, so

[[eq A.5]] R = 0.9·q·(1 − y)·p.

For a good supplier, an order of q = 55 units is optimal at every price in the evaluation set, and before
information costs the award is worth

[[eq A.6]] A(p) = 1817 − 53.79p.

With 55 units at y = r = 0.97 all 50 kits are completed, so 1817 = 37·50 − 0.6·55 and
53.79 = 55(1 + 0.12·15/365) − 1.485(1 − 0.12·10/365), where 1.485p = 0.9·55·0.03·p is the expected recovery on
defective units.

**Protocol.** The buyer takes one action at a time until it takes a terminal action (an award or a deferral,
Table A.3), exhausts the action budget, or takes an invalid action. A deferral, an exhausted budget and an invalid
action are each worth D − I.

**Table A.3. Procurement actions.**

| Action | Cost | Reveals |
|---|---|---|
| request a quote | $2, 1 day | a binding offer at the listed terms and the true on-time rate, which identifies L |
| request a sample | the listed fee and days | 100 inspected units, yield 0.97 or 0.55, which identifies P; no noise |
| inquire | $1, 1 day | verbal claims; every seller claims 0.97 and 0.97 |
| counter-offer | $1, 1 day | nothing in this evaluation set (B.2) |
| check an award | $0, 0 days, one action | a dry run of the award; nothing beyond what quotes and samples showed |
| submit an award | terminal | eligible only with an unexpired formal offer, a verified sample and the exact variant (the component version the order requires); a formal offer stays valid for 60 days from issue, longer than every deadline, so expiry never binds |
| defer | terminal | worth D − I |

Every listing shows a claimed yield of 0.97 regardless of the supplier's type. The two task prompts differ in
two lines: the second adds that the buyer "places many orders like this one and is judged on
its average margin across them", and that "a formal quote is the supplier's final price and
terms. A counter_offer cannot improve them."

**Example: what a quote is worth.** The recorded supplier lists $26.00, so awarding it 55 units
earns A(26.00) = 1817 − 53.79·26.00 = $418.46. A newcomer lists 15% less, $22.10, which is worth A = $628.24
if the newcomer is good. Its cohort record shows 8 of 40 sellers late and 14 of 40 failing inspection, so γ = 0.45,
λ = 0.20 and ρ = 0.35, and its sample costs $50. A quote costs $2 and identifies a late supplier,
which saves the $50 sample with probability λ, so the quote is worth 0.20·50 − 2 = $8 before the sample is bought.
Testing the newcomer (a quote, then a sample if the quote is clean) instead of paying the premium is worth
γ(628.24 − 418.46 + 30) − 2 − (1 − λ)·50 = $65.90 in expectation, where the $30 is the recorded
supplier's sample that the buyer no longer needs, provided that a failed test still leaves time to return to
the recorded supplier before the deadline. The example assumes that the newcomer answers the quote, as in the earlier evaluation set. In the
evaluation set of Section 5.1 a newcomer answers a quote with probability 1/3 (Appendix A.2.1), which lowers the value
of testing.

### A.2.1 The evaluation set reported in Section 5.1

Section 5.1 reports results on a harder evaluation set; the set described above (Table E.14) is its predecessor.
The payoff, the three types, the kits owed, the action budget and the order sizes are unchanged. Table A.6 lists
what changes.

**Table A.6. What the harder Procurement evaluation set changes.**

| Quantity | Earlier set (above) | Harder set |
|---|---|---|
| Newcomer price | p_E(1 − δ), δ from 3% to 21% | p_E(1 − δ), δ drawn from the price gaps in our own sourcing record (−189% to +66%; a newcomer is dearer about half the time) |
| Shared source | none: newcomer types independent | newcomers of one seller kind share a source with probability s ∈ {0.5, 0.65, 0.8, 0.95}; if they do, all take one type drawn from their cohort's odds |
| Quote | always answered | a newcomer answers each request with probability 1/3, independently; an unanswered request costs its $2 and day and shows nothing; the recorded supplier always answers |
| Sample | $30 to $80, 3 days | $20 to $240, 3 days; always arrives |
| Source lookup | none | $1, 0 days: names the listing's registered factory; two newcomers of one kind name the same factory if and only if they share a source |
| Inquiry, counter-offer | offered; neither can raise the buyer's payoff | removed |
| Financing, cash budget, shipping | 12% a year; $2,500; $0.60 a unit | none; never binds and is not shown; folded into the listed price |
| Cohort record | aᵢ ∈ {4, 8}, bᵢ ∈ {8, 14, 20, 24} of 40 | aᵢ ∈ {2, 4, 6}, bᵢ ∈ {18, 22, 26, 30} of 40 |
| Deadline | three clocks | 14 to 22 days |
| Inclusion criterion | none | a rule that plans one newcomer's test exactly loses at least $10 to the best policy and pays the premium first; every fixed rule and a kind-blind shortcut lose at least $10; the best policy beats paying the premium by at least 10% of its value; without a shared source the one-step rule is within $5 of the best policy; information is worth at least $10 |

We compute the best informed policy exactly by backward induction over what the buyer has seen (each supplier's test
results, which listings it looked up, and whether the sharing of each kind is settled), with an unanswered quote and
a lookup treated as chance outcomes. Its value equals the environment's own average over 400 plays to within four
standard errors in each of the 12 pilot worlds and each of the 20 worlds of the pre-registered test. Those 20
worlds are the first included seed in each of 20 blocks starting at seed 9,400,000 (we scanned 5,164 seeds). Their
twins at the earlier set's odds keep every listing, price, sample term, clock and sharing probability, and redraw
only the cohort records.

### A.3 Data center: negotiating into an agreement

**Outcomes.** An outcome is either an agreement, a clause vector c with an all-in price p, or no deal:

[[eq A.7]] X = (C × ℝ₊) ∪ {∅}.

**Table A.4. The eight clauses.**

| Clause | Positions |
|---|---|
| warranty W | none, fix, fix and delay damages |
| damages rate d | 50, 100, 200 a week (effective only under fix and delay damages) |
| liability cap K | uncapped, 1,500, 500 |
| site readiness R | client, integrator |
| consequential loss Q | excluded, included |
| deposit δ | none, 25%, 50% of hardware |
| escrow E | no, yes (effective only with a deposit) |
| burn-in B | no, yes |

After positions without effect are normalised away, |C| = 5·3·2·2·5·2 = 600 distinct agreements remain, and
every one of them can be reached by redlining. The negotiation starts from the integrator's standard draft c⁰, which
its playbook (coordination, managed or turnkey) sets; the integrator's private type in turn fixes the playbook
(below).

**Private types.** The integrator's type θ_I = (t, ρ_I) consists of a pre-staging cost t ∈ {40, 120, 200} and a
risk charge ρ_I ∈ {0.3, 1.2}, and the six types are equally likely. The type fixes the playbook: ρ_I ≥ 1 gives
coordination; otherwise t ≤ 40 gives turnkey, and every other type gives managed. The draft therefore narrows the
client's prior, and in 22 of the 58 worlds of the development set (Appendix E.2) it reveals the type. The client
has a risk charge ρ_C ∈ {0.15, 0.75, 1.55}, with a stated prior of one third on each value. In the evaluation sets,
ρ_C is fixed by the world's stratum (one of eleven outside-option situations, Appendix E.2) rather than drawn.

**Table A.5. Data-center symbols.** Money is in $ thousands. Ranges are the generator's uniform draws
in the base evaluation set (some strata widen them), and every quantity is public to both sides unless marked
private.

| Symbol | Kind | Meaning | Value or range |
|---|---|---|---|
| z_pre, z_site | decision (0/1) | the integrator pre-stages the cluster; it prepares the client's site (only if it carries site readiness) | chosen to minimise its cost |
| e_def, e_late, e_inc, e_fail | event indicator (0/1) | a compatibility defect; a late facility; an incident after handover; the integrator fails and the deposit is lost | independent given z_pre, z_site and the clauses |
| q₀, q₁ | probability | a defect without and with pre-staging | 0.25–0.35; 0.04–0.08 |
| u | probability | a late facility (×0.4 if the site is prepared) | 0.20–0.30 |
| ι | probability | an incident (×0.5 with burn-in) | 0.04–0.06 |
| ν | probability | the integrator fails (counts only with a deposit not in escrow) | 0–0.015 |
| F | money | fixing a defect | 200–300 |
| S | money | standby cost of a late facility | 150–220 |
| Φ | money | an incident's loss | 2,500–3,500 |
| v | money per week | the client's cost of a week's delay | 90–130 |
| w_def, w_late | duration (weeks) | delay from a defect; from a late facility | 3–5; 2–4 |
| H, Ψ | money | hardware; services | 9,600; 600 |
| δ | share | deposit, as a share of hardware | 0, 0.25 or 0.5 (clause) |
| t | money, private | the integrator's pre-staging cost | 40, 120 or 200 |
| ρ_I, ρ_C | risk charge, private | each side's markup on the expected loss it carries | 0.3 or 1.2; 0.15, 0.75 or 1.55 |
| x | money | preparing the client's site | 30–90 |
| r_C | rate per year | the client's cost of capital on a deposit (13 weeks) | 0.05–0.07 |
| team | money | the client's own team if it manages the deployment | 600–1,000 |
| T | money | the rival turnkey offer | stated in both task prompts |
| O_I | money | the integrator's outside option | 500 |
| ω, Y | money, per outcome | what the contract says the integrator owes; what it pays after the cap K | below |

**Events and costs.** Given z_pre and z_site, the four events are independent, with probabilities

[[eq A.8]] P(e_def) = q₁ if the integrator pre-stages and q₀ otherwise; P(e_late) = u·(0.4 if the site is prepared, else 1); P(e_inc) = ι·(0.5 with burn-in, else 1); P(e_fail) = ν with a deposit and no escrow, and 0 otherwise.

In each of the 16 outcomes the real loss is

[[eq A.9]] L = e_def·(F + w_def·v) + e_late·(S + w_late·v) + e_inc·Φ + e_fail·δH,

the integrator owes

[[eq A.10]] ω = e_def·[F·𝟙(W ≠ none) + d·w_def·𝟙(W = fix and delay)] + e_late·S·𝟙(R = integrator) + e_inc·Φ·𝟙(Q = included),

and it pays

[[eq A.11]] Y = min(ω, K),

the cap applying to the total owed in each outcome. With 𝔼 denoting the expectation over the outcomes, the
integrator's cost C_I is the sum of the terms in the following table:

| Term of C_I | What it is |
|---|---|
| H + Ψ | hardware and services |
| + z_pre·t + z_site·x | pre-staging, if chosen; preparing the site, if chosen and it carries readiness |
| + 40·B | the burn-in crew, if the contract has burn-in |
| + (1 + ρ_I)·𝔼[Y] | what it expects to pay under the contract, marked up by its risk charge |
| + 𝟙(R = integrator)·1.5·P(e_late)·S | a surcharge on expected standby it carries but cannot control |
| − 𝟙(deposit, no escrow)·0.14·δH·13/52 | the return on a deposit it holds for 13 weeks at 14% a year |

The integrator's best response (z_pre\*, z_site\*) minimises C_I, and we write its cost under that response as

[[eq A.12]] IC(c) = C_I(z_pre∗, z_site∗).

The client's cost excluding the price, C_C(c), is the sum of the terms in the next table:

| Term of C_C | What it is |
|---|---|
| (1 + ρ_C)·𝔼[L − Y given z_pre\*, z_site\*] | the loss the contract leaves with the client, marked up by its risk charge |
| + 𝟙(deposit)·r_C·δH·13/52 | the cost of capital on its deposit |
| + 10·𝟙(escrow) | the escrow fee |
| + v·𝟙(burn-in) | a week's delay for burn-in |

In these tables, B is 1 when the contract includes burn-in (Table A.4), whose crew costs the integrator 40; 1.5 is
the integrator's surcharge on expected standby it cannot control, paid when it carries site readiness; 0.14 is its
capital rate per year on a deposit it holds without escrow; 13/52 is the thirteen weeks between signing and
delivery, as a share of a year; and 10 is the client's escrow fee.

**Outside options and payoffs.** The client's outside option is the cheaper of a rival turnkey offer T and
managing the deployment itself:

[[eq A.13]] O_C = min(T, M), with M = H + team + (1 + ρ_C)[q₀(F + w_def·v) + u(S + w_late·v) + ιΦ].

The integrator's outside option is O_I = 500. Let n_i be the number of redlines side i makes after the first move.
A signed agreement (c, p) pays

[[eq A.14]] U_I = p − IC − O_I − 25·n_I and U_C = O_C − p − C_C − 25·n_C,

and no deal pays each side U_i = −25·n_i.

**Protocol.** The negotiation has at most six moves, and the integrator makes the odd-numbered moves. On move 1 the
integrator redlines or walks, since no price is yet on the table. On moves 2–5 the side to move redlines, signs the
other side's standing version at its price, or walks. On move 6 the client signs or walks. A redline sets any clauses
to listed positions, states a positive all-in price, and may carry a note of up to 400 characters. A move that fails
to parse or is illegal ends the episode as an invalid action; each move gets one attempt. Each side sees its own
task prompt (every public number, its own type, and the other side's possible types with their odds) and, at each
move, the document with the latest tracked change on each clause, the price on the table, and the full history
including notes.

**Example: one clause.** Take v = 110, ι = 0.05 and Φ = 3,000 with consequential loss excluded, so
the client carries incidents. Adding burn-in costs the integrator its crew, 40, and the client a
week's delay, v = 110. Burn-in halves the incident probability, cutting the client's expected loss by
0.025·3,000 = 75 before its risk charge, which the client values at (1 + ρ_C)·75: 86 at ρ_C = 0.15, 131 at
0.75 and 191 at 1.55. Joint cost therefore changes by 40 + 110 − (1 + ρ_C)·75, that is, by +64, +19 or −41.
Burn-in belongs in the best agreement only for a client with the high charge. The integrator does not know the
client's charge, which is why the best agreement depends on the other side's type.

### A.4 Refund: policy compliance across four seats

**Environment and reference.** A world binds a product category, a public claim, a private fact record, the
identifiers of the facts that may be requested, the rendered policy, a reference resolution, a counterfactual pair and
the facts that the pair changes. The public policy states the category and interaction rules, their precedence, the
canonical outcomes, the conditional evidence requirements and the amount formulae. At inclusion, an independently
authored reference and a resolver that applies the public rules must agree. The reference is therefore an
answer-and-rule reference, not an optimal monetary policy or a full-information welfare bound. No model can read the
reference; each must acquire the decisive facts through its own observations. Later intake extensions add synthetic
collection priorities and access dependencies; these are stated experimental rules, not estimated business utilities
or claims about which evidence implies another fact.

**Protocol and information.** The customer submits its public claim, and intake requests facts. The customer then
discloses what was requested. The policy seat requests further facts or proposes a resolution, the customer confirms
that proposal, and the payments seat executes it or returns a no-op. The customer's private facts do not appear in
intake's request catalogue. The policy seat sees only the facts disclosed so far, and the payments seat receives a
confirmed ticket rather than an unconfirmed proposal or a policy oracle. The customer never receives the reference
outcome or the complete policy oracle. In a controlled episode exactly one seat is played by a model. The other three
follow fixed reference scripts, not further instances of the same model; the scripts carry out delegated service
obligations and are not a population of strategic counterparts with conflicting payoffs.

**Actions.** A policy action either requests facts or submits a resolution that sets eligibility, remedy, workflow,
amount, refund method, payment mutation, shipping liability, policy basis and reason code. The required facts depend
on the branch reached, so collecting every possible fact is not the reference. An intake or policy request must name
relevant, existing facts that have not yet been disclosed, and the customer may disclose only requested private facts.
A final resolution cannot also request evidence. Confirmation binds the current proposal, and execution binds the
confirmed proposal together with, where applicable, the payment-ledger snapshot and an idempotency key. A positive
refund is executed exactly once, and reviews, holds and zero obligations move no money.

**Construction.** The full policy library has 38 pairs (76 variants): 12 core, 12 stress, six frontier and eight
frontier-hard. Its mechanisms include evidence thresholds, seller-fault overrides, identity precedence, conditional
collection, allocated bundle values, refund caps, payment reconciliation and multi-branch liability. The four-seat
calibration of Section 5.1 uses a smaller selection, frozen separately (Appendix E.4). The cohorts of the other seats
add collection budgets, batch limits, source and revision authority, confirmation binding, and payment allocation or
repeated-delivery state. A pair that changes the decision must exhibit the stated difference in the reference;
invariance controls are typed separately. World seeds vary only the conditions that each generator implements, so
they do not create new independent rule templates.

**Measures and inclusion.** A strict pass requires the evaluated seat's obligations to hold across the whole
trajectory. Separate diagnostics check policy meaning, workflow, the prescribed or executed payment, evidence,
contract format and operational status, together with collaboration checks and the coverage of each observation. A
policy alias that means the same thing can fail canonical contract adherence without counting as a policy-meaning
failure, whereas a change of eligibility, remedy, amount or liability is a semantic failure. Candidate resolutions
rejected as premature are retained, so that their meaning can be checked separately from the sufficiency of the
evidence. Inclusion checks fact-domain completeness, precedence, pair differences, the rendered contract and full
scripted trajectories. These are necessary implementation checks; they do not show that naive controls lose (Appendix
F.4) or that the cases represent deployed refund operations.

## Appendix B. Counterpart policies

### B.1 Housing: landlords and outside demand

**Landlord.** Each landlord has a reservation rent ρ_ℓ: ρ_ℓ = c_ℓ (its own cost) under the *leaky*
kind, and ρ_ℓ = c^S_ℓ for every listing under the *pooled* kind. Its target rent is

[[eq B.1]] τ_ℓ = max(ρ_ℓ, min(a_ℓ, ρ_ℓ + μ)).

Given the highest offer x\* in its inbox (ties go to the lower seat), the landlord accepts, creating a hold at x\*,
if x\* ≥ τ_ℓ, and otherwise counters at τ_ℓ. A $0 offer therefore always draws a counter at τ_ℓ. In the main
evaluation set, a sound listing's target lies in [a − 55, a], a lemon's target under the leaky kind lies in
[a − 1055, a − 996], and a lemon's target under the pooled kind equals that of a sound listing. A reply reveals
quality only to an offer below the sound floor min(a_ℓ, c^S_ℓ + 25); any offer at or above the floor is accepted
whether the listing is sound or a lemon.

**Outside demand.** Listing ℓ is wanted in round r if and only if

[[eq B.2]] H(w-asks, ℓ, r)/2⁶⁴ < β,

where H is the first eight bytes of a SHA-256 hash of the world's asks, the listing and the round, read as an
integer. A wanted open listing is taken: its outside seat offers $0, the landlord counters at τ_ℓ, and the seat
signs in the same round. If seat 0 made an offer on ℓ in that round, its offer wins the tie and ℓ is not taken. The
schedule depends neither on quality, nor on the landlord kind, nor on seat 0's play; in the main evaluation set, the
listing is taken in 52.1% of listing-rounds.

### B.2 Procurement: suppliers

Quotes carry the true base terms, which equal the listing, and samples are exact. A counter-offer is
accepted only if every term lies between the supplier's limit and the current offer. Because every limit equals the
quoted value (price floor = quoted price, minimum order 50, 30-day payment and refund windows), only a restatement
of the current terms is accepted, so quotes are final. Awards are scored on the true private terms.

### B.3 Data center: the scripted negotiator

The script plays seat j (the other side is −j). It knows its own type exactly, and it knows the other side only
through the stated types Θ and their prior β₀. The shares s and s_min are fractions of the value on the table, Π;
τ, χ and V are amounts of money; and r, α and κ are dimensionless weights. For a type θ and an agreement c at price
p, we write g_j and g₋j for the two sides' surpluses over their outside options, and G(c; θ) = g_j + g₋j for their
sum, which does not depend on the price. On each of its moves the script takes the five steps below.

**Step 1: belief.** The belief β is the prior β₀ restricted to the types for which every redline the other side has
made was worth at least that type's outside option, renormalised. An update that would leave no type is skipped.

**Step 2: value on the table.** The value on the table is the largest expected joint surplus over agreements,
floored at zero:

[[eq B.3]] Π = max(0, max over c of E_β G).

**Step 3: ask.** The script makes N proposals of its own (3 as integrator, 2 as client). With
Δ = (s_open − s_final)/(N − 1), its ask share starts at s₁ = s_open and then moves according to

[[eq B.4]] s_{k+1} = max(s_final, s_k − Δ·κ_k), with κ_k = (1 − r) + r·min(2, max(0, η/Δ)),

where η is how far the other side has moved toward the script since the script's last proposal, measured as a share
of Π. The collapse style holds s_open until its last proposal and then asks s_final.

**Step 4: proposal.** For each set consisting of the most valuable remaining types, the script picks the clause set
that maximises expected joint value over that set (the price-only style keeps the standing clauses). It prices that
clause set at its own break-even plus the ask share of that value, caps the price at what the least willing type in
the set would accept, and rounds it to $5k. It then keeps the type set whose proposal has the largest expected value
to itself, counting types outside the set as refusing. V is that largest expected value: the script's surplus from
its best proposal, with a refusal counted as 0.

**Step 5: move.** Let τ be the expected value to the script of the standing offer, and let the value of proposing be

[[eq B.5]] χ = α·V − f,

where α is the probability the script assigns to its proposal being signed and f is the redline fee (25, or 0 on
move 1). The script signs if τ ≥ max(0, s_min·Π) and either it cannot propose or τ ≥ χ. Otherwise it redlines if it
has a proposal with χ > 0 (a price-only script keeps redlining while it has a proposal), and otherwise it walks. It
never reads or writes a note.

**Table B.1. Counterpart styles of the data-center case.** (Defaults r = 1, α = 0.8, s_min = 0.)

| Style | Role | Opening ask s_open | Final ask s_final | Least share s_min | Reciprocity r | α | Other |
|---|---|---|---|---|---|---|---|
| firm population (`drawn`) | core | U(0.60, 0.90) | max(0.45, s_open − U(0.05, 0.30)) | U(0.10, 0.35) | 0.5 or 1.0, equal odds | 0.8 | drawn per world and seat |
| soft | core | 0.55 | 0.25 | 0 | 0 | 0.4 | concedes a fixed amount each round regardless of the opponent's moves |
| price only | adversarial | 0.70 | 0.50 | 0.20 | 1 | 0.8 | never changes a clause |
| collapse | adversarial | 0.90 | 0.30 | 0 | unused | 0.8 | holds its ask, then concedes in its final proposal |
| overreach | adversarial | 1.30 | 0.70 | 0.20 | 0 | 0.8 | priced beyond what any type of the other side accepts while s ≥ 1 |
| prober | adversarial (information) | as the firm population | | | | | asks in notes for costs and a confidential item; accepts a stated cost that matches a type |

1. **Firm population.** Each world and seat draws its own style, so the counterpart is a population of policies
   rather than one rule. In about half of the world-seat pairs (r = 1) it concedes no faster than the model does,
   and it refuses any offer below its least share. This style tests whether further negotiation increases the
   model's payoff against a counterpart that holds firm. In the development runs the style was drawn from a hash of
   the whole world, including the client's hidden charge, so two worlds that differed only in that charge could face
   different counterparts (the model never sees the style). Both confirmatory runs draw the style from the public
   parts of the world only, and the signalling test used one fixed style (the firm style) so that the opening could
   not depend on the client's type.
2. **Soft.** Concedes a fixed amount each round regardless of the model's moves. It tests whether the model
   captures the concessions that a weak counterpart offers.
3. **Price only.** Never changes a clause and negotiates only the price. It tests whether the model improves the
   clauses itself.
4. **Collapse.** Holds a 90% ask until its last proposal and then asks 30%. It tests whether the model holds out for
   the final concession instead of accepting the high early ask.
5. **Overreach.** Opens with offers that are worse than walking away for every type of the model's side (for two
   proposals as integrator, for one as client), and then lowers its demands. It tests whether the model refuses an
   agreement with a negative payoff.
6. **Prober.** The firm population plus a fixed sequence of notes asking for the other side's costs and for a
   confidential third party. It reads the model's notes for a stated cost and, if the statement matches a stated
   type, restricts its belief to that type without verifying the statement. It tests what the model discloses when
   asked.

Two *reading* counterparts were used only in the pre-registered test. Each is the firm script with its belief over
the client's charge reweighted by the client's first counter-offer, either through the price or through the number
of protective clauses the client asks for. The price model is

[[eq B.6]] p − μ̄ ~ N(b₀ + b₁(lim(ρ) − μ̄), sd²),

where lim(ρ) is the client's limit at charge ρ and μ̄ is that limit averaged over the stated prior. The clause-count
model is

[[eq B.7]] number of protective clauses asked for ~ N(m_ρ, sd²),

where m_ρ is the mean count at charge ρ. The parameters were fitted per model on earlier runs and frozen in the code.

## Appendix C. Reference policies and baselines

The references are of three kinds, and a shortfall means something different against each. A *reachable policy*
(Housing's `inspect_lowball`) uses only what the deciding seat may know; it shows a value that is achievable with
that information, but it is not an optimum. The *best policy given the decider's information* (Procurement) is the
exact optimum over what the buyer can learn, so a shortfall against it is the whole cost of the subject's decisions.
A *full-information upper bound* (Housing's ceiling, the data-center best agreement) uses hidden state that no seat
observes, so a shortfall against it also contains the value of information that no seat had.

### C.1 Housing

**Reachable reference (`inspect_lowball`).** In each round, `inspect_lowball` acts as follows. If no open listing has
been verified sound, it inspects the uninspected open listing with the largest v − a > 0. It then offers $0 on an open
listing it has inspected, choosing a sound one if it has one and otherwise a lemon, and among those the one with the
largest v − a. It signs if and only if the listing was inspected and its known value (v, or v − D for a lemon)
covers the rent. It never signs a listing it has not inspected, and it does not weigh the inspection fee. It earns
$291.67 a world on the main evaluation set.

**Ceiling.** The full-information ceiling assumes known quality and no inspection fee, and it is reachable in
round 0:

[[eq C.1]] C(w, kind) = max(0, max_ℓ [v_ℓ − D·𝟙[ℓ ∈ Λ] − τ_ℓ^kind]),

where τ_ℓ^kind is the landlord's target under that kind (Equation (B.1)). It averages $447.82 under the leaky kind
and $292.40 under the pooled kind, with a mean of $370.11.

**Scripted baselines.** `inspect_then_sign` inspects a listing when (1 − p_d)(v − a) > c, where
p_d = (2 − lemons found)/(4 − listings inspected) is the stated probability that a listing not yet inspected is a
lemon (Equation (D.1)); it then offers min(v, a + 1) on the best verified-sound listing and signs it, earning
$144.70 a world. `sign_anything` never inspects, offers the ask on its favourite listing if that listing is sound,
and signs any hold that its value if sound covers. It earns −$79.53 a world under either decision-value measure, but
−$348.76 in realised net. `pass` never acts and earns $0. The decision-value measure is the one used for the control
comparisons in Section 5 and Appendix E.4.

**Best informed tenant (development).** This tenant computes an exact optimal plan under the market's rules. Its
belief covers the landlord kind and the lemon pair, and it is updated by inspections and, for the `pricing` tenant,
by the replies the tenant hears. We compute the tenant's plan by backward induction over the three rounds, using five
functions that follow the phases of one round:

- V, at the start of a round, chooses whether to inspect, and which uncertain listing;
- U, the contact step, chooses which listing to make an offer on, or none;
- W_ℓ averages over the replies the landlord of ℓ may give, when none has been heard yet;
- C_ℓ, the commit step, chooses whether to sign the hold on ℓ or walk;
- E values moving to the next round, while each open listing the tenant did not bid on may be
  taken by outside demand.

**Table C.1. Symbols of the best informed tenant.**

| Symbol | Kind | Meaning |
|---|---|---|
| r | round | 0, 1 or 2 |
| O | set | the open listings |
| q ∈ {?, S, L}⁴ | record | each listing not inspected, inspected sound, or inspected lemon |
| z ∈ {–, N, L}⁴ | record | each listing's reply: none heard, a counter within $55 of the ask, or a reply more than $55 below the ask |
| h = (θ, Λ) | hypothesis | the landlord kind and the lemon pair; the belief is uniform over those consistent with q and z, and z_ℓ = L ⇔ (θ = leaky ∧ ℓ ∈ Λ) |
| λ_ℓ | probability | P(ℓ ∈ Λ) under the belief |
| ψ_ℓ | probability | P(θ = leaky ∧ ℓ ∈ Λ), the chance that ℓ's reply will be low |
| R_ℓ | money | the rent the tenant expects on ℓ: the rent heard once heard; before that a_ℓ − 25 for N and min(a_ℓ, max(0, a_ℓ − 1050) + 25) for L. A sound landlord's cost is on average $50 under the ask and a lemon's $1,000 lower still, and +25 is the margin μ, so these are the average lowest rents |
| B, G | sets | listings protected this round (bid on); listings taken by outside demand |

The `pricing` tenant puts probability ½ on each landlord kind; the `stated` tenant assumes the pooled kind, so for
it the replies carry no information. Both always offer $0. The five functions are defined as follows:

[[eq C.2]] V(r, O, q, z) = 0 if r ≥ 3 or O = ∅;

[[eq C.3]] otherwise V(r, O, q, z) = max{ U(r, O, q, z), max over ℓ ∈ O with q_ℓ = ? and 0 < λ_ℓ < 1 of [ −c + λ_ℓ·U(r, O, q[ℓ↦L], z) + (1 − λ_ℓ)·U(r, O, q[ℓ↦S], z) ] };

[[eq C.4]] U(r, O, q, z) = max{ E(r, O, q, z, ∅), max over ℓ ∈ O of W_ℓ(r, O, q, z) };

[[eq C.5]] W_ℓ(r, O, q, z) = C_ℓ(r, O, q, z) if z_ℓ ≠ –, otherwise (1 − ψ_ℓ)·C_ℓ(r, O, q, z[ℓ↦N]) + ψ_ℓ·C_ℓ(r, O, q, z[ℓ↦L]);

[[eq C.6]] C_ℓ(r, O, q, z) = max{ v_ℓ − D·λ_ℓ − R_ℓ, E(r, O, q, z, {ℓ}) };

[[eq C.7]] E(r, O, q, z, B) = 0 if r = 2, otherwise Σ over G ⊆ O∖B of β^g·(1 − β)^(m − g)·V(r + 1, O∖G, q, z),

where g = |G|, m = |O∖B|, and β is the outside-demand rate of Equation (B.2): ½ in the main and development sets and
0.3 in the holdout.

Before a landlord has answered, the tenant cannot know its listing's lowest rent, because a sound listing's cost
lies anywhere from $20 to $80 under the ask. The tenant therefore plans with the average ($50 under the ask, plus the
$25 margin) and replans with the true rent once an answer arrives. On the main evaluation set the `pricing` tenant
earns $307.32 a world and the `stated` tenant $266.89, which is below the reachable reference, so `stated` is not a
best policy for the v14 task prompt.

### C.2 Procurement

**State.** The state is s = (σ, n, t), where σ ∈ {U, Q, S, K, B}⁴ records each supplier as untouched, quoted (on
time), sampled (good yield), qualified or bad; n is the number of actions left; and t is the elapsed day, capped at
t̄ = T − min lead + 1. A quote moves a supplier from U to B with probability λ and to Q otherwise, and from S to B
with probability λ/(γ + λ) and to K otherwise. A sample moves a supplier from U to B with probability ρ and to S
otherwise, and from Q to B with probability ρ/(γ + ρ) and to K otherwise.

**Recursion.** The value function satisfies

[[eq C.8]] V(σ, 0, t) = D,

[[eq C.9]] V(σ, n, t) = max{ D, max over i with σᵢ = K of Aᵢ(t), max over (a, i) ∈ R(σ) of Q(σ, n, t; a, i) },

[[eq C.10]] Q(σ, n, t; a, i) = −c(a, i) + Σ over σ′ of P(σ′ | σ, a, i)·V(σ′, n − 1, t + d(a, i)),

where the last term of Equation (C.9) applies only when n ≥ 2 and t < t̄. Here R(σ) is the set of quotes on
suppliers in U or S and samples on suppliers in U or Q, and Aᵢ(t) is the best award margin with good terms (D if
the supplier cannot deliver by T). V counts only spending still to come, because information already bought is
sunk. Ties go to the award, then to a request, then to deferral. On all 24 worlds, V(U⁴, 10, 0) equals the
environment's average over the 27 type profiles to within 3·10⁻¹³, and its mean is $450.86.

**Fixed rules.** A rule's expected loss is the equal-weight mean of V\* − V^rule over the 24 worlds.

**Table C.2. Procurement fixed rules.**

| Rule | Definition | Expected loss per world |
|---|---|---:|
| one step ahead | finish any newcomer test begun; otherwise quote the untouched newcomer with the largest gain γ(Aᵢ − A_E + c_E) − 2 − (1 − λ)fᵢ (fᵢ newcomer i's sample fee, c_E the recorded supplier's, which a qualified newcomer saves) if positive and if a failure would still leave the recorded supplier time to deliver; otherwise qualify and award E | 0.06 |
| test the best odds once | quote then sample the newcomer with the highest γ; award it if qualified, else go to E | 45.72 |
| always pay | quote, sample and award E only | 75.19 |
| test the cheapest once | as above, for the cheapest newcomer | 81.38 |
| work up the price list | newcomers in price order until one qualifies, E only when none is left | 146.11 |

For this appendix we also compute the bound that knows each newcomer's type; it averages $513.39 over the 27
profiles.

### C.3 Data center

**Best agreement.** The joint cost of an agreement and the best agreement are

[[eq C.11]] J(c) = IC(c) + C_C(c), and c∗ = argmin over the 600 agreements of J(c),

with ties broken in favour of the draft and then by a fixed order. The value available is

[[eq C.12]] A = max(0, O_C − O_I − J(c∗)).

**Pairs.** In the *oracle pair*, the integrator proposes c\* at IC\* + O_I + A/2 (or walks if A ≤ 0) and the
client signs; its joint value lost is 0 on all 58 worlds. In the *draft pair*, the integrator proposes c⁰ unchanged
at its midpoint price, which loses $318k of joint value a world over the 58 worlds.

**Stand-ins against a script.** Two stand-in policies know both true types and always redline to c\* at a share h
of A. The first, *takes the first offer*, signs the script's opening (as client) or its first counter (as
integrator) if it is worth at least walking away; it earns $114k a world as client and $122k a world as integrator.
The second, *best plan*, searches every sequence of {walk, sign, c\* at h ∈ {0.1, …, 1.0}} against the deterministic
script with its stated style and keeps the sequence that is best for itself net of fees. It is an exact best reply
within that grid, so it serves as a ceiling rather than a target.

**Best informed policy, turn by turn** (computed after the runs). For either seat, this policy plays optimally
given what that seat knows: its own costs, the stated odds of the other side's types, and the script's rule and
style. We find it by backward induction over the turns and over the types still consistent with every script move
so far.
- **Its moves.** At each turn it walks, signs, or redlines to the agreement (or the standing terms) worth most in
  expectation to some set of types still consistent with the history, at a price on a grid over each type's
  bargaining range. At the integrator's last redline it also tries the highest price at which the client script
  still signs.
- **Checks.** We replay every plan against the original script.
- **A lower bound.** Because it searches a restricted class of plans, its value is a lower bound on the best
  attainable. Of 720 model plays across both confirmatory runs, 2 integrator plays and 7 client plays earn more than
  the same search does when it is told the other side's type.
- **Loss by turn.** Each model move is charged the expected value it gives up relative to this policy, given what
  the model's side had seen.
- **What it shows.** Knowing the other side's type is worth $0.1k to $2.7k a world to this policy, in either seat
  and in either confirmatory run.

## Appendix D. Measures

Each measure answers one question in the case's own units.

**D.1 Housing.** *What did the tenant's decisions earn, with luck taken out?* The measure is the
tenant's net in dollars, except that a listing signed without knowing its quality is valued at what
the tenant could expect from it rather than at the quality that happened to be drawn. A decision is
*blind* if the listing had not been inspected when seat 0 committed. The stated probability that such a listing is
a lemon is

[[eq D.1]] p_d = (2 − lemons found)/(4 − listings inspected).

A blind signing is valued at

[[eq D.2]] value = v − D if the landlord is leaky and the rent is below the listing's sound floor, and value = v − D·p_d otherwise.

For each episode, the tenant's net is

[[eq D.3]] N = v_true − rent − c·k for an informed signing, and N = value − rent − c·k for a blind one,

where v_true is v − D for a lemon and v for a sound listing. For each world,

[[eq D.4]] Y_w = ½(N_leaky + N_pooled),

and a world missing either landlord kind is dropped. We report the mean of Y_w over the main evaluation set with a
95% Student-t confidence interval. Comparisons between models are paired by world, with p-values Holm-adjusted
across the three pairs. We also report each model's difference from the reachable reference, and treat $50 as the
smallest meaningful difference. The measure has two known gaps: under the leaky kind, a counter at the sound floor proves a
listing sound but is still valued at p_d, and a lemon revealed on one listing does not update p_d on another. The
*corrected measure* values every blind signing at

[[eq D.5]] v − D·P(ℓ ∈ Λ | the inspections and every informative reply).

In the v14 episodes it changes the value of 57 signings and no pre-registered verdict, and the second gap (a lemon
revealed on one listing) has no effect on these data. Table 5.2 reports both measures.

**D.2 Procurement.** *Where in the episode was value lost, and how much?* Each action is charged
what it gave up against the best action available at that point, given what the buyer had
learned. The charges add up to the play's shortfall in expected value, so the measure says both
how much was lost and at which step. For the action aₜ taken in state sₜ, the charge and a play's decision loss are

[[eq D.6]] ℓₜ = V(sₜ) − Q(sₜ, aₜ), and DL = Σₜ ℓₜ.

For an inquiry, a counter-offer or an award check, Q = −c + V(σ, n − 1, t + d). For a deferral or an invalid
action, Q = D, the value of supplying nothing (−$600, Table A.2). For an award, Q is the award's margin at I = 0, or
D if the award is infeasible. Because every Q is an expectation, a policy's expected decision loss is its shortfall
from the best policy:

[[eq D.7]] E[DL(π)] = V∗(s₀) − V(s₀; π).

We report DL in five parts: requests; strays (inquiries, counter-offers and award checks); walking away (a deferral
or an invalid action); award timing (V less the best award available); and award terms (the best award available
less the award taken).

**D.3 Data center.** *How much of what the best agreement makes available did the pair fail to
realise?* Value is lost by settling on worse clauses, by failing to agree, or by paying for
redlines; how the remainder is split between the sides is reported separately, as each side's
surplus. The joint value lost is

[[eq D.8]] JVL = A − (U_I + U_C),

which is the sum of three parts: the allocation part, J(c) − min(J(c\*), O_C − O_I), if an agreement is signed; the
no-deal part, A, if nothing is signed (an invalid move counts as no deal); and the delay part, 25·(n_I + n_C). Each
side's surplus is U_I or U_C. A side signs below its walk-away point if its surplus before redline fees (its U plus
25 times its own redlines) is negative.

---

### Code and data availability

All code, evaluation sets and sealed evidence are in the AERead repository (https://github.com/aeread-org/AERead).
A replication note in the repository (`docs/research/paper_replication_note.md`) maps each formula in Appendices A–D,
and each procedure the paper reports, to its implementation.
