# Scored controls for the V3 joint venture

Four provider-free developer policies -- the scripted reference funding its
capacity share of the shared feeder, walking away at the first offer, adopting
every counter (which opens the joint venture at nothing and then takes whatever
share the utility's counter assigns), and the free rider, which offers nothing
toward the feeder in every round -- run through the real scheduler on the six
curated joint-venture cases (`full_stack_jv_001`, `full_stack_jv_002`, `full_stack_jv_003`, `full_stack_jv_004`, `full_stack_jv_005`, `full_stack_jv_006`, `full_stack_jv_007`, `full_stack_jv_008`). The first three are the sincere stratum,
one per partner type that does what it announced (pro-rata, conditional,
generous), three joint-offer rounds. The last three are the credibility
stratum, one joint-offer round each, where the partner's announcement can be
untrue and its public record of earlier feeders is the only evidence: a
bluffing partner that announces full coverage and funds pro rata, a generous
partner whose record shows it kept its word, and a posturing partner that
announces pro rata and covers the rest. Every trajectory is finalised, verified
and replayed offline. The reference funds the share the evidence licenses: the
one with the lower expected cost, given the fraction of recorded feeders the
partner funded in full, or the territory's declared prior when there is no
record. Because that is an ex-ante rule, a control can beat the reference on a
single case; what must hold is the aggregate below. `free_rider` and
`fair_share` are the two synthetic arms the rule rejects.

- cases: 8; trajectories: 40, all included, all replay-verified
- coalition decisions by policy: scripted best_response 8; walk_away not_reached 8; adopt_every_counter best_response 6, under_funded 2; free_rider best_response 3, under_funded 5; fair_share best_response 5, over_funded 3
- the reference beats walking away in 8 of 8 cases
- the reference beats adopting every counter in 8 of 8 cases
- adopting every counter is admitted in 8 of 8 cases
- the free rider is admitted in 8 of 8 cases; the reference clears it by 30,000, 30,000, -18,000, 30,000, 0, 0, -18,000, 0 cents per case
- coalition decisions by policy: scripted best_response 8; walk_away not_reached 8; adopt_every_counter best_response 6, under_funded 2; free_rider best_response 3, under_funded 5; fair_share best_response 5, over_funded 3
- realised equity NPV summed over the cases: scripted -530,000, walk_away -800,000, adopt_every_counter -1,134,000, free_rider -584,000, fair_share -584,000; the reference beats both arms; an arm wins on 2 single cases

The reference is the fair share, not the highest NPV. The partner states its
position before anyone offers, so the developer knows what a free ride is
worth: against a generous partner the rider is admitted and beats the reference
by its whole share of the feeder, which is the exploitation stratum by design;
against a pro-rata or conditional partner nobody funds the feeder, the rider's
solo stack still finances at the utility's solo interconnection price, and it
trails the reference by that premium. This bundle is derived only from
committed cases and the family engine and is regenerated, never edited. No
claim about any model is made here.
