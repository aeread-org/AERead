# PR #7 contract-decision request

*Draft for Zeyu to post as a comment on PR #7. Not part of the shipped docs.*

---

Chenyu — the kernel now runs. The scheduler exists, and `housing_v1` has been driven
through it end to end, provider-free: three phases, a signed lease, per-seat utility,
and a complete evidence log. Six commits, local only, on `zeyu/kernel-r1` off
`c8176ad`. Full suite 1450 passed / 4 skipped / 1 xfailed.

Building it turned up decisions that are yours, not mine. Three are amendments already
present in the branch that were never put to you; three are new questions the first real
family surfaced. I have implemented the reading I think is right in each case, cited
below, so nothing is blocked — but each is reversible and I would rather you rule than
inherit my defaults.

## A. Amendments to the frozen contract, made on the branch, never approved

These were introduced while the taxonomy and roadmap were frozen. I think all three are
improvements and I have built on them; they need your yes or no so there is one contract
rather than two.

**A1. A decision is a slot with typed channels, and an action is a bundle.**
`LogicalAction` gained a layer: `DecisionSlot` (a stable decision identity with an
`order_key`) carries one or more `ActionChannel`s (each with a recipient set and
min/max cardinality), and one successful action closes as one atomic `ActionBundle` of
ordered `ActionEnvelope`s. Partial bundles are never applied.

This is load-bearing for housing, not decoration. A landlord answering an inbox of three
offers is one decision producing three channel-keyed actions; the previous flat model
could not express "one decision, several directed replies, all or nothing".

**A2. `AttemptObserver` is how an adapter records a provider call.**
The adapter receives it as a keyword argument it cannot avoid
(`act(request, *, attempts)`) and must open every call before the side effect and close
it afterwards. The runner refuses an adapter that leaves a call open. This makes
write-before-side-effect a signature rather than a convention.

**A3. Plugin categories are Environment / Verifier / BenchmarkSource / AgentAdapter /
ExecutionBackend.** Reference providers and case generators are *typed implementation
roles*, not separate protocols or entry-point groups in 0.1 — the roadmap on the branch
already says so explicitly, which resolves a concern I raised earlier and was wrong
about. Same for `CallAttemptStart`/`CallAttemptToken`: the branch keeps them as stable
compatibility exports with any rename deferred to Task 2.1a, additively. I withdraw both
of those objections.

## B. New questions from running a real family

**B1. Seats cannot be enumerated before an episode starts.** A plugin only reveals a
phase's slots once the state is already in that phase, so asking housing for its commit
seats while the state says `contact` is a contract violation. The scheduler therefore
binds an adapter the first time a seat acts. That works, but a resolver that must pin
`seat_profile_id_by_seat` in the `RunPlan` *before* execution needs the seat list from
somewhere else. My reading: the **case** declares its seats (`CaseManifest.seats`
already exists), the plugin decides who acts when. Confirm, and I will make the resolver
read seats from the case rather than the plugin.

**B2. `invalid_action_policy` needed a vocabulary, so I locked one.** The field was a
free string, and the scheduler recognised only `"forfeit"`; anything else — including a
typo — silently produced the milder outcome. It now accepts `pass` or `forfeit` and
refuses everything else loudly.

That change made housing fail immediately, because its phases carried the placeholder
`"formal_failure_disposition_requires_shared_contract"`. I set them to `pass`, on the
strength of your PR #6 answer of 2026-08-23: *"record the typed action failure and apply
`pass` for that phase … invalid tenant contact means no offer, invalid landlord response
means no hold, invalid tenant commit means the hold expires unsigned"*. If that reading
is wrong, say so and I will revert it. `HousingContractStatus.unresolved_contract_gaps`
still lists `formal_action_failure_disposition_requires_shared_contract` as open —
whether that declaration should now close is a case-owner call I deliberately did not
make.

**B3. Is `PhaseSpec.mode` binding or descriptive?** `single | sequential | simultaneous`
is currently recorded and logged but does not change scheduling: every phase freezes all
observations, collects every slot's action, and applies one batch. A phase declaring
`single` may still return ten slots and nothing complains. Two coherent answers — the
runner enforces the declaration, or the field is documented as descriptive with
sequencing expressed through `next_phases` — and I would rather implement your choice
than guess. Nothing depends on it today.

## C. Two rulings still open from the earlier list

**C1. Is `user_simulator` a seat kind or a counterpart profile?** tau3 needs a simulated
user with its own model and its own seed. Your earlier position was that it looks more
like a counterpart policy/profile than an economic seat, and I now agree: it is not a
party with a payoff. But it does act, so it needs a place in the evidence and its seed
needs a place in the sampling declaration. Ruling wanted before I write the tau3 adapter.

**C2. Which record carries the reasoning condition?** The reasoning-condition document
requires every evaluated cell to bind a versioned condition. `AgentExecutionConfig`
currently has provider, model, harness, runtime, prompt, sampling, tools, memory,
budgets, and retry policy, but no reasoning block. I plan to add it there, so it is part
of the hashed configuration a receipt reproduces. Say if you want it elsewhere.

## What I am doing next, in this order

`ToolInvocation` as a first-class evidence record — read-only and mutating tools
distinguished — since tau3 is entirely tool calls and nothing else in the plan is
blocked on a ruling. Then the reasoning condition, the ID grammar with the no-colon rule
for identifiers that leave the repository, and the remaining free-string vocabularies.
Then `exchange_v1` old/new parity, which is the safety belt for everything above.

Two things I have deliberately not touched: the `SamplingPlan` / `AnalysisPlan` public
façade over the 59 planned-identity micro-records, and the analysis DAG language. Neither
has a consumer in the current experiment plan, and I would rather add them when the
analysis layer needs them than freeze a surface nobody has used.

One risk that is not mine to close: housing's strategic content is unverified under the
binding-hold semantics — the regenerated baselines are naive 0.852 against adaptive
0.849, and the profitable-deviation audit that §4 of the case document elevates to an
admission gate was withdrawn and has not been rerun. That audit should land before any
paid model run on housing.
