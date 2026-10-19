# Appendices A–D: case specifications (draft, AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. Written from a reading of each
case's code at the branch heads named in each part; every rule and number traces to a file and
line listed under "Code references". Companion to [Case studies](paper_case_studies.md) and
[Quality control](paper_qc_design.md). Amounts are in dollars for Housing and Procurement and in
$ thousands for Data center.

---

## Appendix A. Case specifications

Following TERMS-Bench [TB], each case is written as an environment Γ (outcomes, private types and their prior, payoffs), a
protocol (seats, order of play, actions, what each seat observes, termination), and fixed
counterpart policies (Appendix B). Refund is not specified here. Symbols are local to each case;
each case's table lists them, with the kind of quantity each is. The evaluated seat is subscript A, a counterpart B. In controlled comparisons, the
prior and counterpart policies are fixed across evaluated agents; head-to-head role swaps change
the opponent as well, so they compare pairings. Agent configurations also differ in the settings
recorded in Appendix H. The reference policies of Appendix C are computed in the same Γ.

### A.1 Housing: lemons with outside demand (identity v14)

**Environment.** A world seed w fixes four listings ℓ ∈ {0, 1, 2, 3} and six tenant seats.
Seat 0 is the evaluated tenant; seat i ∈ {1, …, 4} is outside demand for listing i − 1; seat 5
never acts. Exactly m = 2 listings are lemons, Λ ⊂ {0, …, 3}, drawn uniformly from a random
stream separate from the one that sets values, asks and costs. Seat 0 signs at most one lease
(ℓ, rent), or none. Its payoff after signing ℓ with k inspections is

u_A = v_ℓ − D·𝟙[ℓ ∈ Λ] − rent − c·k, and u_A = −c·k if it signs nothing.

Seat 0 privately knows v_ℓ, its value for each listing if sound. Each landlord privately knows
its listing's quality and cost. The prior is uniform over the six possible lemon pairs. The
landlord kind is not drawn: both kinds are played on every world.

**Table A.1. Housing parameters.**

| Symbol | Meaning | Value |
|---|---|---|
| T | rounds | 3 |
| m | lemons | 2 of 4 |
| D | lemon loss (cuts the tenant's value and the landlord's cost alike) | $1,000 |
| c | inspection fee | $25 |
| a_ℓ | ask | ⌊U(1500, 3200)⌋ |
| v_ℓ | seat 0's value if sound | a_ℓ + 10·s_ℓ + U(−20, 20), with s_ℓ = 100(0.6κ_ℓ + 0.4ι_ℓ) − 30 and κ, ι ~ U(0, 1) |
| c^S_ℓ | a sound listing's cost | max(0, a_ℓ − U(20, 80)) |
| c^L_ℓ | a lemon's cost | max(0, c^S_ℓ − 1000) |
| μ | landlord margin | $25 |
| β | outside-demand rate per round | ½ |

On the main pack asks run from $1,501 to $3,198, and seat 0's gain v − a from −$275 to +$676.

**Protocol.** Each round r = 0, 1, 2 has four phases. (1) *Inspect*: seat 0 may pay c to
inspect one open listing it has not inspected; the quality appears in its observation at once.
(2) *Contact*: seat 0 makes one offer (ℓ, x) with ℓ open and x ≥ 0, or passes; offering again on
a listing it walked from is legal. (3) *Respond*: each landlord applies its policy (B.1) to its
inbox; each listing creates at most one binding hold. (4) *Commit*: a seat holding a hold signs
or walks; a missing or invalid action is a walk, and every hold expires at the end of the phase.
Signing ends seat 0's play; the market ends after round 2 or when every listing is leased.

**Observation of seat 0.** The board (asks, uninformative listing attributes, open or leased),
its rejected listings and active hold, its values v, the lemon count and share, the loss, the
fee, its own inspections and spend, and `your_history`: its own offers, each hold with the
binding rent and whether the landlord accepted or countered, and each sign or walk. The sealed
prompt states the payoff, that a fixed landlord "may accept or make one binding counteroffer",
that "a counteroffer can itself convey information about listing quality", the departure rule,
that a listing seat 0 bid on is protected that round, the three-round horizon, that walking does
not close a listing, and the order of phases. It does not state the landlord's pricing rule or
the cost range.

**Example: a reply and a signing.** A listing asks a = $2,400; its sound cost is c^S = $2,350, so
a lemon's is c^L = $1,350, and seat 0 values it at v = $2,600 if sound. With the $25 margin
(B.1) a sound listing's landlord targets $2,375, a lemon's leaky landlord $1,375, and a lemon's
pooled landlord $2,375. Seat 0 offers $2,000. A sound landlord counters at $2,375; a pooled lemon
landlord also counters at $2,375; a leaky lemon landlord accepts at $2,000, and only a lemon's
landlord would, so the acceptance itself marks the lemon. Signing pays v − rent = +$225 for the
sound listing at $2,375, v − D − rent = −$400 for the leaky lemon at $2,000, and −$775 for the
pooled lemon at $2,375; inspecting first costs $25 and shows the quality under either kind. Had
seat 0 offered $0, the leaky lemon landlord would have countered at $1,375, which also marks the
lemon, and signing there pays +$225.

### A.2 Procurement: pay or test (`pay_or_test_v1`)

**Environment.** One buyer and one component. The suppliers are one recorded supplier E and
three newcomers N₁–N₃. Each supplier has a type θ ∈ {G, L, P} = {(on-time 0.97, yield 0.97),
(0.55, 0.97), (0.97, 0.55)}; E is always G. Newcomer types are independent with prior
πᵢ = (γᵢ, λᵢ, ρᵢ) = ((40 − aᵢ − bᵢ)/40, aᵢ/40, bᵢ/40), read from the cohort record of Nᵢ's seller
kind (aᵢ of 40 tracked sellers unreliable on delivery, bᵢ failed inspection). That gives 3³ = 27
type profiles, each with positive weight; γ ranges from 0.2 to 0.7.

**Table A.2. Procurement parameters.**

| Quantity | Value |
|---|---|
| Kits owed / minimum service | 50 / 40 (an award completing fewer than 40 is void) |
| Revenue per kit / shortfall penalty | $37 / $12 per kit short |
| Supplying nothing, D | −$600 (= −12·50), plus any information already spent |
| Cash budget | $2,500 (never binds) |
| Deadline T | 10–12 days (clock "none"), 13–14 (tight), 17–18 (loose) |
| Action budget | 10 |
| Order sizes | 50, 55 or 60 units (MOQ 50, step 5, capacity 60); shipping $0.60 a unit |
| E | price U[24, 28] rounded to $0.05; lead 6 days; sample $30 and 2 days; a record of 48–96 orders, 3% late, 3% defective |
| Newcomer i | price p_E(1 − δᵢ), δ drawn without replacement from {3, 5, 7, 9, 12, 15, 18, 21}%; lead 6–8 days; sample $30–80 in $10 steps and 3 days |
| Cohort record | aᵢ ∈ {4, 8}, bᵢ ∈ {8, 14, 20, 24} of 40 |

**Payoff.** For an award line of q units at price p, yield y, on-time rate r and lead ℓ, made on
day t with information spend I: units = q·y·r if t + ℓ ≤ T and 0 otherwise; kits k = min(⌊units⌋,
50); recovery R = 0.9·q(1 − y)·p; cost C = qp + 0.6q + qp·0.12·15/365 − R + R·0.12·10/365 + I; and
the margin is M = 37k − 12(50 − k) − C if k ≥ 40 and the line is valid, otherwise D − I. For a good
supplier q = 55 is optimal at every pack price and gives A(p) = 1817 − 53.79p before information
cost.

**Protocol.** One action at a time until a terminal action, the action budget, or an invalid
action; the last three are worth D − I.

**Table A.3. Procurement actions.**

| Action | Cost | Reveals |
|---|---|---|
| request a quote | $2, 1 day | a binding offer at the listed terms and the true on-time rate, which identifies L |
| request a sample | the listed fee and days | 100 inspected units, yield 0.97 or 0.55, which identifies P; no noise |
| inquire | $1, 1 day | verbal claims; every seller claims 0.97 and 0.97 |
| counter-offer | $1, 1 day | nothing in this pack (B.2) |
| check an award | $0, 0 days, one action | a dry run of the award; nothing beyond what quotes and samples showed |
| submit an award | terminal | eligible only with an unexpired formal offer, a verified sample and the exact variant |
| defer | terminal | worth D − I |

Every listing shows a claimed yield of 0.97 whatever the supplier's type. The two briefs differ
by two lines; the second adds that the buyer "places many orders like this one and is judged on
its average margin across them", and that "a formal quote is the supplier's final price and
terms. A counter_offer cannot improve them."

**Example: what a quote is worth.** The recorded supplier lists $26.00, so awarding it 55 units
earns A(26.00) = 1817 − 53.79·26.00 = $418.46. A newcomer lists 15% less, $22.10, worth A = $628.24
if good; its cohort record shows 8 of 40 sellers late and 14 of 40 failing inspection, so γ = 0.45,
λ = 0.20, ρ = 0.35, and its sample costs $50. A quote costs $2 and identifies a late supplier,
which saves the $50 sample with probability λ: worth 0.20·50 − 2 = $8 before the sample. Testing
the newcomer (quote, then sample if the quote is clean) instead of paying the premium is worth
γ(628.24 − 418.46 + 30) − 2 − (1 − λ)·50 = $65.90 in expectation, where the $30 is the recorded
supplier's sample the buyer no longer needs, provided a failed test still leaves time to return to
the recorded supplier before the deadline.

### A.3 Data center: negotiating into an agreement

**Outcomes.** X = (C × ℝ₊) ∪ {∅}: a clause vector c with an all-in price p, or no deal.

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

Positions without effect are normalised away, leaving |C| = 5·3·2·2·5·2 = 600 distinct
agreements, all reachable by redlining. The document opens on the integrator's standard draft
c⁰, set by its playbook (coordination, managed or turnkey).

**Private types.** The integrator θ_I = (t, ρ_I) has a pre-staging cost t ∈ {40, 120, 200} and a
risk charge ρ_I ∈ {0.3, 1.2}, six types equally likely; the type fixes the playbook (ρ_I ≥ 1 gives
coordination, otherwise t ≤ 40 gives turnkey, otherwise managed), so the draft narrows the
client's prior and in 22 of 58 worlds reveals the type. The client has a risk charge
ρ_C ∈ {0.15, 0.75, 1.55}, declared prior one third each; in the packs ρ_C is fixed by the world's
cell rather than drawn.

**Table A.5. Data-center symbols.** Money in $ thousands; ranges are the generator's uniform draws
on the base pack (some cells widen them), public to both sides unless marked private.

| Symbol | Kind | Meaning | Value or range |
|---|---|---|---|
| a, s | decision (0/1) | the integrator pre-stages the cluster; it prepares the client's site (only if it carries site readiness) | chosen to minimise its cost |
| e_def, e_late, e_inc, e_fail | event indicator (0/1) | a compatibility defect; a late facility; an incident after handover; the integrator fails and the deposit is lost | independent given a, s and the clauses |
| q₀, q₁ | probability | a defect without and with pre-staging | 0.25–0.35; 0.04–0.08 |
| u | probability | a late facility (×0.4 if the site is prepared) | 0.20–0.30 |
| ι | probability | an incident (×0.5 with burn-in) | 0.04–0.06 |
| ν | probability | the integrator fails (counts only with a deposit not in escrow) | 0–0.015 |
| F | money | fixing a defect | 200–300 |
| S | money | standby cost of a late facility | 150–220 |
| Φ | money | an incident's loss | 2,500–3,500 |
| v | money per week | the client's cost of a week's delay | 90–130 |
| w_def, w_late | duration (weeks) | delay from a defect; from a late facility | 3–5; 2–4 |
| H, σ | money | hardware; services | 9,600; 600 |
| δ | share | deposit, as a share of hardware | 0, 0.25 or 0.5 (clause) |
| t | money, private | the integrator's pre-staging cost | 40, 120 or 200 |
| ρ_I, ρ_C | risk charge, private | each side's markup on the expected loss it carries | 0.3 or 1.2; 0.15, 0.75 or 1.55 |
| x | money | preparing the client's site | 30–90 |
| r_C | rate per year | the client's cost of capital on a deposit (13 weeks) | 0.05–0.07 |
| team | money | the client's own team if it manages the deployment | 600–1,000 |
| T | money | the rival turnkey offer | stated in both briefs |
| m | money | the integrator's outside option | 500 |
| O, Y | money, per outcome | what the contract says the integrator owes; what it pays after the cap K | below |

**Events and costs.** Given a and s, the four events are independent: P(e_def) = q₁ if a else q₀;
P(e_late) = u·(0.4 if s else 1); P(e_inc) = ι·(0.5 if burn-in else 1); P(e_fail) = ν if there is a
deposit and no escrow, else 0. In each of the 16 outcomes the real loss is

L = e_def·(F + w_def·v) + e_late·(S + w_late·v) + e_inc·Φ + e_fail·δH,

the integrator owes

O = e_def·[F·𝟙(W ≠ none) + d·w_def·𝟙(W = fix and delay)] + e_late·S·𝟙(R = integrator) + e_inc·Φ·𝟙(Q = included),

and pays Y = min(O, K), the cap applying to the total in each outcome. With 𝔼 the expectation over
the outcomes, the integrator's cost is

C_I = H + σ + a·t + s·x + 40·B + (1 + ρ_I)·𝔼[Y] + 𝟙(R = integrator)·1.5·P(e_late)·S − 𝟙(deposit, no escrow)·0.14·δH·13/52;

its best response (a\*, s\*) minimises C_I, and IC(c) = C_I(a\*, s\*). The client's cost, excluding
price, is

CC(c) = (1 + ρ_C)·𝔼[L − Y | a\*, s\*] + 𝟙(deposit)·r_C·δH·13/52 + 10·𝟙(escrow) + v·𝟙(burn-in).

**Outside options and payoffs.** The client's outside option is O_C = min(T, M), the cheaper of a
rival turnkey offer T and managing the deployment itself, M = H + team + (1 + ρ_C)[q₀(F + w_def·v) +
u(S + w_late·v) + ιΦ]; the integrator's is m = 500. With n_i side i's redlines after the first move,
a signed (c, p) pays U_I = p − IC − m − 25·n_I and U_C = O_C − p − CC − 25·n_C; no deal pays
U_i = −25·n_i.

**Protocol.** Six moves, the integrator on odd moves. Move 1: redline or walk (no price is yet on
the table). Moves 2–5: redline, sign the other side's standing version at its price, or walk.
Move 6 (client): sign or walk. A redline sets any clauses to listed positions and states a
positive all-in price, and may carry a note of up to 400 characters. A move that fails to parse or
is illegal ends the episode as an invalid action; each move gets one attempt. Each side sees its
own brief (every public number, its own type, the other side's possible types with their odds)
and, at each move, the document with the latest tracked change on each clause, the price on the
table and the full history including notes.

**Example: one clause.** Take v = 110, ι = 0.05 and Φ = 3,000 with consequential loss excluded, so
the client carries incidents. Adding burn-in costs the integrator its crew, 40, and the client a
week's delay, v = 110. It halves the incident chance, cutting the client's expected loss by
0.025·3,000 = 75 before its risk charge, which it values at (1 + ρ_C)·75: 86 at ρ_C = 0.15, 131 at
0.75 and 191 at 1.55. Joint cost therefore changes by 40 + 110 − (1 + ρ_C)·75: +64, +19 or −41. So
burn-in belongs in the best agreement only for a client with the high charge, which the integrator
does not know; that is why the best agreement depends on the other side's type.

## Appendix B. Counterpart policies

### B.1 Housing: landlords and outside demand

**Landlord.** Each landlord has a reservation ρ_ℓ: ρ_ℓ = c_ℓ (its own cost) under the *leaky*
kind, and ρ_ℓ = c^S_ℓ for every listing under the *pooled* kind. Its target is
τ_ℓ = max(ρ_ℓ, min(a_ℓ, ρ_ℓ + μ)). Given the highest offer x\* in its inbox (ties to the lower seat),
it accepts (hold at x\*) if x\* ≥ τ_ℓ and otherwise counters at τ_ℓ. A $0 offer therefore always
draws a counter at τ_ℓ. On the main pack a sound listing's target lies in [a − 55, a]; a lemon's
under the leaky kind in [a − 1055, a − 996]; a lemon's under the pooled kind equals a sound one's.
A reply reveals quality only to an offer below the sound floor min(a_ℓ, c^S_ℓ + 25); any offer at or
above it is accepted by both.

**Outside demand.** Listing ℓ is wanted in round r iff H(w-asks, ℓ, r)/2⁶⁴ < β, with H the first
eight bytes of a SHA-256 of the world's asks, the listing and the round. A wanted open listing is
taken: its outside seat offers $0, the landlord counters at τ_ℓ, and the seat signs in the same
round. If seat 0 made an offer on ℓ that round, its offer wins the tie and ℓ is not taken. The
schedule depends on neither quality, nor landlord kind, nor seat 0's play; on the main pack 52.1%
of listing-rounds are takes.

### B.2 Procurement: suppliers

Quotes carry the true base terms, which equal the listing. Samples are exact. A counter-offer is
accepted only if every term lies between the supplier's limit and the current offer, and every
limit equals the quoted value (price floor = quoted price, minimum order 50, 30-day payment and
refund windows), so only a restatement of the current terms is accepted: quotes are final.
Awards are scored on the true private terms.

### B.3 Data center: the scripted negotiator

The script plays seat σ, knows its own type exactly, and knows the other side through the
declared types Θ and their prior β₀. Shares (s, s_min) are fractions of the value on the table Π;
τ, χ and V are money; r, α and κ are dimensionless weights. For a type θ write v_σ and v₋σ for the two sides' surpluses
and G(c; θ) = v_σ + v₋σ, which does not depend on price.

1. **Belief.** β ∝ β₀ restricted to types for which every redline the other side made was worth
   at least its outside option to it; an update that would leave no type is skipped.
2. **Value on the table.** Π = max(0, max over c of E_β G).
3. **Ask.** With N own proposals (3 as integrator, 2 as client) and Δ = (s_open − s_final)/(N − 1),
   the ask share starts at s₁ = s_open and moves to s_{k+1} = max(s_final, s_k − Δκ_k), with
   κ = (1 − r) + r·min(2, max(0, η/Δ)), where η is how far the other side moved toward the script
   since its last proposal, measured as a share of Π. Collapse holds s_open until its last
   proposal, then asks s_final.
4. **Proposal.** For each set of the most valuable remaining types, the script picks the clause
   set maximising expected joint value over that set (price only keeps the standing clauses),
   prices it at its break-even plus the ask share of that value, capped at what the least willing
   type in the set would accept, rounds to $5k, and keeps the set with the largest expected value
   to itself, types outside the set counting as refusing.
5. **Move.** With τ the expected value to the script of the standing offer and χ = α·V − 25 the
   value of proposing, it signs if τ ≥ max(0, s_min·Π) and either it cannot propose or τ ≥ χ; otherwise
   it redlines if it has a proposal with χ > 0; otherwise it walks. It never reads or writes a
   note.

**Table B.1. Counterpart styles of the data-center case.** (Defaults r = 1, α = 0.8, s_min = 0.)

| Style | Role | Opening ask s_open | Final ask s_final | Least share s_min | Reciprocity r | α | Other |
|---|---|---|---|---|---|---|---|
| firm population (`drawn`) | core | U(0.60, 0.90) | max(0.45, s_open − U(0.05, 0.30)) | U(0.10, 0.35) | 0.5 or 1.0, equal odds | 0.8 | drawn per world and seat |
| soft | core | 0.55 | 0.25 | 0 | 0 | 0.4 | concedes on a clock |
| price only | adversarial | 0.70 | 0.50 | 0.20 | 1 | 0.8 | never changes a clause |
| collapse | adversarial | 0.90 | 0.30 | 0 | unused | 0.8 | holds, then gives way on its last proposal |
| overreach | adversarial | 1.30 | 0.70 | 0.20 | 0 | 0.8 | priced past every type of the other side while s ≥ 1 |
| prober | adversarial (information) | as the firm population | | | | | asks in notes for costs and a confidential item; believes a stated cost matching a type |

1. **Firm population.** Each world and seat draws its own style, so the counterpart is a
   population rather than one rule. It concedes no faster than the model does in about half of
   world-seats (r = 1) and refuses any offer below its least share. It tests whether pressing pays
   against a counterpart that holds. Its draw hashes the whole world, including the client's
   hidden charge, which leaks nothing to the model; the declared test used a fixed style.
2. **Soft.** Concedes on a clock whatever the model does. It tests whether the model takes what a
   weak counterpart gives up.
3. **Price only.** Never changes a clause and haggles the price. It tests whether the model fixes
   the clauses itself.
4. **Collapse.** Holds a 90% ask until its last proposal, then asks 30%. It tests patience.
5. **Overreach.** Opens with offers worse than walking away for every type of the model's side (as
   integrator for two proposals, as client for one), then comes down. It tests whether the model
   refuses a losing deal.
6. **Prober.** The firm population plus a fixed ladder of notes asking for the other side's costs
   and for a confidential third party; it reads the model's notes for a stated cost and, if the
   statement matches a declared type, narrows its belief without checking. It tests what the model
   discloses when asked.

Two *reading* counterparts were used only in the declared test: the firm script with its belief
over the client's charge reweighted by the client's first counter-offer, through the price
(p − μ̄ ~ N(a + b(lim(ρ) − μ̄), sd²)) or through the number of protective clauses asked for
(~ N(m_ρ, sd²)), with parameters fitted per model on earlier runs and frozen in code.

## Appendix C. Reference policies and baselines

The references are of three kinds, and a shortfall means something different against each. A
*reachable policy* (Housing's `inspect_lowball`) uses only what the deciding seat may know; it is
a witness to what is achievable, not an optimum. The *best policy given the decider's
information* (Procurement) is the exact optimum over what the buyer can learn, so a shortfall
against it is the whole cost of the subject's decisions. A *full-information upper bound*
(Housing's ceiling, the data-center best agreement) uses hidden state that no seat sees, so a
shortfall against it also contains the value of information no seat had.

### C.1 Housing

**Reachable reference (`inspect_lowball`).** Each round: if no open, verified-sound listing exists,
inspect the uninspected open listing with the largest v − a > 0; offer $0 on the verified open
listing that is sound before lemon and has the largest v − a; sign iff the listing was inspected
and its known value (v, or v − D for a lemon) covers the rent. It never signs blind and never
weighs the fee. It earns $291.67 a world on the main pack.

**Ceiling.** C(w, kind) = max(0, max_ℓ [v_ℓ − D·𝟙[ℓ ∈ Λ] − τ_ℓ^kind]): known quality, no fee,
reachable in round 0. $447.82 (leaky), $292.40 (pooled), mean $370.11.

**Scripted baselines.** `inspect_then_sign` inspects when (1 − p)(v − a) > c, offers min(v, a + 1) on
the best verified-sound listing and signs it ($144.70). `sign_anything` never inspects,
offers the ask on its favourite listing if sound, and signs any hold covered by its value if
sound: −$79.53 under either decision-value measure, but −$348.76 in realised net. `pass`
never acts ($0). The decision-value measure is the one used for the control comparisons in
Section 5 and Appendix E.4.

**Best informed tenant (development).** This tenant plans exactly against the market's rules. Its
belief covers the landlord kind and the lemon pair and is updated by inspections and, for the
`pricing` tenant, by the replies it hears. It is computed by backward induction over the three
rounds in five functions that follow one round's phases:

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
| R_ℓ | money | the rent the tenant expects on ℓ: the rent heard once heard; before that a_ℓ − 25 for N and min(a_ℓ, max(0, a_ℓ − 1050) + 25) for L |
| B, G | sets | listings protected this round (bid on); listings taken by outside demand |

The `pricing` tenant puts ½ on each landlord kind; the `stated` tenant assumes the pooled kind, so
its replies carry no information. Offers are always $0. The five functions are:

V(r, O, q, z) = 0 if r ≥ 3 or O = ∅; otherwise

V(r, O, q, z) = max{ U(r, O, q, z), max over ℓ ∈ O with q_ℓ = ? and 0 < λ_ℓ < 1 of [ −c + λ_ℓ·U(r, O, q[ℓ↦L], z) + (1 − λ_ℓ)·U(r, O, q[ℓ↦S], z) ] }

U(r, O, q, z) = max{ E(r, O, q, z, ∅), max over ℓ ∈ O of W_ℓ(r, O, q, z) }

W_ℓ(r, O, q, z) = C_ℓ(r, O, q, z) if z_ℓ ≠ –, otherwise (1 − ψ_ℓ)·C_ℓ(r, O, q, z[ℓ↦N]) + ψ_ℓ·C_ℓ(r, O, q, z[ℓ↦L])

C_ℓ(r, O, q, z) = max{ v_ℓ − D·λ_ℓ − R_ℓ, E(r, O, q, z, {ℓ}) }

E(r, O, q, z, B) = 0 if r = 2, otherwise Σ over G ⊆ O∖B of 2^(−|O∖B|)·V(r + 1, O∖G, q, z)

An unheard floor is set to its mean and the tenant re-plans when a rent is heard. Main pack: `pricing`
$307.32, `stated` $266.89 (below the reachable reference, so `stated` is not a best policy for the
v14 prompt).

### C.2 Procurement

**State.** s = (σ, n, t): σ ∈ {U, Q, S, K, B}⁴ records each supplier as untouched, quoted (on time),
sampled (good yield), qualified or bad; n is actions left; t the elapsed day, capped at
t̄ = T − min lead + 1. A quote on U goes to B with probability λ, else Q; on S to B with λ/(γ + λ),
else K. A sample on U goes to B with ρ, else S; on Q to B with ρ/(γ + ρ), else K.

**Recursion.**

V(σ, 0, t) = D

V(σ, n, t) = max{ D, max over i with σᵢ = K of Aᵢ(t), max over (a, i) ∈ R(σ) of Q(σ, n, t; a, i) }, the last term only when n ≥ 2 and t < t̄

Q(σ, n, t; a, i) = −c(a, i) + Σ over σ′ of P(σ′ | σ, a, i)·V(σ′, n − 1, t + d(a, i))

with R(σ) the quotes on suppliers in U or S and the samples on suppliers in U or Q, and Aᵢ(t) the best
award margin with good terms (D if the supplier cannot deliver by T). V counts only future spending;
ties go to the award, then a request, then defer. On all 24 worlds V(U⁴, 10, 0) equals the
environment's average over the 27 type profiles to within 3·10⁻¹³; its mean is $450.86.

**Fixed rules.** Expected loss is the equal-weight mean over the 24 worlds of V\* − V^rule.

**Table C.2. Procurement fixed rules.**

| Rule | Definition | Expected loss per world |
|---|---|---:|
| one step ahead | finish any newcomer test begun; otherwise quote the untouched newcomer with the largest gain γ(Aᵢ − A_E + c_E) − 2 − (1 − λ)fᵢ if positive and if a failure would still leave the recorded supplier time to deliver; otherwise qualify and award E | 0.06 |
| test the best odds once | quote then sample the newcomer with the highest γ; award it if qualified, else go to E | 45.72 |
| always pay | quote, sample and award E only | 75.19 |
| test the cheapest once | as above, for the cheapest newcomer | 81.38 |
| work up the price list | newcomers in price order until one qualifies, E only when none is left | 146.11 |

The bound that knows each newcomer's type averages $513.39 over the 27 profiles (computed for this
appendix).

### C.3 Data center

**Best agreement.** J(c) = IC(c) + CC(c); c\* = argmin over the 600 agreements of J (ties to the
draft, then a fixed order). The value available is A = max(0, O_C − m − J(c\*)).

**Pairs.** The *oracle pair* has the integrator propose c\* at IC\* + m + A/2 (or walk if A ≤ 0) and the
client sign: joint value lost 0 on all 58 worlds. The *draft pair* proposes c⁰ unchanged at its
midpoint: $318k a world lost over the 58.

**Stand-ins against a script** (they know both true types and always redline to c\* at share a of A):
*takes the first offer* signs the script's opening (as client) or its first counter (as integrator)
if it is worth at least walking away, and earns 114 and 122; *best plan* searches every sequence of
{walk, sign, c\* at a ∈ {0.1, …, 1.0}} against the deterministic script with its declared style and
keeps the best for itself net of fees, an exact best reply within that grid and a ceiling, not a
target.

## Appendix D. Measures

Each measure answers one question in the case's own units.

**D.1 Housing.** *What did the tenant's decisions earn, with luck taken out?* The measure is the
tenant's net in dollars, except that a listing signed without knowing its quality is valued at what
the tenant could expect from it rather than at the quality that happened to be drawn. A decision is
*blind* if the listing was not inspected when seat 0 committed; its
stated lemon probability is p_d = (2 − lemons found)/(4 − listings inspected). A blind signing is
valued at v − D when the landlord is leaky and the rent is below the listing's sound floor, and at
v − D·p_d otherwise. Per cell, N = (v_true − rent) for an informed signing or (value − rent) for a
blind one, less c·k; per world, Y_w = ½(N_leaky + N_pooled), a world missing either kind being
dropped. Reported: the mean of Y_w over the main pack with a 95% Student-t interval; model pairs
paired by world, Holm-adjusted over three; each model minus the reachable reference; $50 as the
smallest meaningful difference. A counter at the sound floor proves a listing sound but is still
valued at p_d, and a lemon revealed on one listing does not update p_d on another. The
*corrected measure* (`price_reply_posterior`) values every blind signing at v − D·P(ℓ ∈ Λ | the
inspections and every informative reply); in the v14 cells it moves 57 signings and no declared
verdict, and the second gap has no effect on these data. Table 5.2 reports both.

**D.2 Procurement.** *Where in the episode was value lost, and how much?* Each action is charged
what it gave up against the best action available at that point, given what the buyer had
learned; the charges add up to the play's shortfall in expected value, so the measure says both
how much was lost and at which step. For each action taken, ℓₜ = V(sₜ) − Q(sₜ, aₜ), and a play's decision loss is
DL = Σₜ ℓₜ. For inquire, counter and check, Q = −c + V(σ, n − 1, t + d); for defer or an invalid
action Q = D; for an award, Q is its margin at I = 0, or D if infeasible. Because every Q is an
expectation, E[DL(π)] = V\*(s₀) − V^π(s₀). DL is reported in five parts: requests, strays, walking
away, award timing (V less the best award available) and award terms (the best award available less
the award taken).

**D.3 Data center.** *How much of what the best agreement makes available did the pair fail to
realise?* Value is lost by settling on worse clauses, by failing to agree, or by paying for
redlines; how the remainder is split between the sides is reported separately, as each side's
surplus. Joint value lost = A − (U_I + U_C), the sum of three parts: allocation
J(c) − min(J(c\*), O_C − m) if signed; no deal, A, if nothing is signed (an invalid move counts as no
deal); and delay, 25·(n_I + n_C). Each side's surplus is U_I or U_C. A side signs below its walk-away
point if its surplus before fees is negative.

---

### Code references

Paths are relative to the AERead repository; line numbers refer to the revisions used for the
reported runs.

Housing (`src/aeread_families/housing/`): world `environment.py`:108–241,
`lemons.py`:49–171; phases `environment.py`:408–787; expected value and stated odds
`environment.py`:41–54, 797–823; history `runner.py`:1136–1360; prompt `runner.py`:249–267 and
`price_outside_demand.py`:64–70, 163–168, 343–357; landlord `price_bargaining.py`:21–40; outside
demand `price_outside_demand.py`:54–122; references `price_reference.py`:39–147, `lemons.py`:245–316;
best-informed tenant `price_best_informed.py`:51–226; measure `price_endpoint.py`:42–109,
`price_publication.py`:42–185; pack `lemons_design.py`:231–305.

Procurement (`src/aeread_families/procurement_allocation/`): constants and listings `pay_or_test_case_matrix.py`:94–236; types and prior
`pay_or_test_reference.py`:39–64; margin `environment.py`:581–740; actions `environment.py`:52–62,
1377–1606; recursion `pay_or_test_reference.py`:111–225; rules 285–371; decision loss 401–460;
cells and admission `pay_or_test_case_matrix.py`:302–399; prompts `pay_or_test_prompt.py`:17–93.

Data center (`src/aeread_families/datacenter_development/`): agreement, protocol and grading `agreement.py`:45–268; clause costs, events and
outside options `risk_allocation_contracts.py`:57–217, 299–308; constants `risk_allocation.py`:
145–148, 660–672; parsing and legality `agreement_environment.py`:48–203; negotiator
`agreement_negotiator.py`:45–254; prober `agreement_prober.py`:110–162; readers
`agreement_reader.py`:39–102; stand-ins `agreement_negotiator_check.py`:27–115; packs
`agreement_pack.py`:31–55.
