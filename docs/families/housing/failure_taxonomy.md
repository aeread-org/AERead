# Housing v1: a taxonomy of failures inside completed trajectories

The operational register counts failures that stopped a cell: rate limits,
timeouts, route rejections. There are 54 of them across every Housing campaign,
and they describe infrastructure rather than agents.

This document counts a different population. Of the 1233 completed
trajectories that can be reconstructed from published evidence, most contain at
least one economic failure that the campaign's primary outcome cannot see,
because welfare cancels every transfer and an agent can give away its entire
surplus without moving the score (D-16, D-27). Those failures are the material
a capability analysis would actually use, and until now nobody had counted
them.

Two layers. The outcome layer is derived from committed rows and is published
at `evidence/housing/failure_taxonomy/`, rebuilt with
`python -m aeread_families.housing.failure_taxonomy`, regenerating byte for
byte. The action layer is richer and is **not** published, because it needs
episode event logs that live in the ignored run root; its counts are reported
here as unverifiable observations and marked as such.

## 1. What counts as a failure, and what only looks like one

Three groups, which matter because they call for different responses.

**A, participation-constraint violations.** An agent agreed to terms worse than
not trading at all, and could have detected this from its own private
information alone, without knowing anything about any other agent. These are
self-checkable, so a schema floor or a validity gate can close them.

**B, allocative shortfalls.** The market cleared somewhere other than where the
oracle would. These are not individually attributable: leaving surplus on the
table takes both seats and the search process together.

**C, process signatures.** How the episode was conducted. Not errors in
themselves, but they separate a market that converged from one that churned,
and they characterise a counterparty, which matters because counterparty
behaviour drives the variance the paired design cannot remove.

And one group that is **not** failure at all, which any naive count gets
badly wrong. See section 4.

## 2. Outcome layer, from committed evidence

1233 completed trajectories across 13 campaigns; nothing skipped.
"Occurrences" counts events, "cases" counts distinct campaign, world,
configuration and condition combinations, since two replicates of one cell are
one example.

| class | occurrences | cases |
|---|---|---|
| A1 tenant signed above its own value | 36 | 30 |
| A2 landlord signed at exactly zero rent | 362 | 216 |
| A3 landlord signed below cost, nonzero rent | 27 | 24 |
| A4 pair destroys value, both consented | 68 | 50 |
| B1 a listing the oracle leases stayed empty | 414 | 297 |
| B2 leased a listing the oracle leaves empty | 57 | 41 |
| B3 right listings, wrong tenants | 1210 | 685 |
| C1 wasted contacts above one per tenant | 749 | 468 |
| C3 landlord rejected more than it accepted | 216 | 154 |
| C4 tenant walked more than it signed | 107 | 82 |

Class A is attributable to a seat, because one agent agreed to the terms:

| class | attribution |
|---|---|
| A1 tenant signed above its own value | DeepSeek 30, GLM 6 |
| A2 landlord signed at zero rent | GLM 362, DeepSeek 0 |
| A3 landlord signed below cost | GLM 25, DeepSeek 2 |

Class B is the sorting story from the estimand review seen as a count. B3 at
685 distinct cases is the largest class in the taxonomy and is also the
component that supplies 68 percent of the gap below the oracle.

## 3. Action layer, local evidence only

From the 720 episodes of `housing_confirmatory_parasail_v2`, 31,235 parsed
actions. **These counts cannot be verified from the repository.** The episode
logs are in the ignored run root, and the publication policy excludes them. A
sanitised action projection would be needed to publish this layer.

| class | count | attribution |
|---|---|---|
| L1 landlord countered at zero rent | 275 | GLM 275 |
| L2 landlord accepted below its own cost | 24 | GLM 22, DeepSeek 2 |
| L3 landlord countered below its own cost | 6 | GLM 6 |
| L4 landlord accepted a dominated offer | 14 | GLM 14 |
| L5 landlord rejected all while holding a profitable offer | 5 | DeepSeek 4, GLM 1 |
| L8b landlord named an offer that did not exist, with real offers present | 8 | GLM 8 |
| T1 tenant offered above its own value | 159 | DeepSeek 84, GLM 75 |
| T3 tenant offered on a listing that was not open | 4 | DeepSeek 4 |
| T4 tenant passed with a profitable listing open | 127 | DeepSeek 118, GLM 9 |
| T5 tenant signed a hold above its own value | 27 | DeepSeek 23, GLM 4 |
| T6 tenant walked from a profitable hold | 90 | DeepSeek 88, GLM 2 |
| T7 tenant passed while holding an active hold | 17 | DeepSeek 17 |
| malformed action | 9 | GLM 9 |

L1 to L3, T1 and T5 are the self-checkable class A violations seen as
decisions. L4, L5, T4, T6 and T7 are a different and more interesting class:
**decision errors under complete local information.** Nothing hidden is
involved in walking away from a hold that pays, or passing when a profitable
listing is open. 235 of those 239 cases are DeepSeek in the tenant seat.

## 4. The artifact that inflates a naive count two hundredfold

A first pass of this taxonomy reported 1541 cases of a landlord naming an
offer that did not exist. That number is almost entirely wrong, and the way it
is wrong is worth recording.

Action schema `housing_actions/2.0` requires `offer_id` to be a non-empty
string for `accept` and `counter`, and null for `reject_all`. A landlord whose
inbox is empty therefore has exactly one representable way to say "there is
nothing to answer": reject everything. A landlord that does not want to reject
must invent an identifier.

| | count | attribution |
|---|---|---|
| empty inbox, invented identifier, a schema artifact | 1533 | DeepSeek 1211, GLM 322 |
| real offers present, invented identifier, an error | 8 | GLM 8 |

The environment discards the first group harmlessly. Counting them as model
failures would have overstated the class by a factor of 190 and pointed the
blame at the wrong model, since the artifact is mostly DeepSeek and the real
error is entirely GLM. Any taxonomy over structured output has to separate what
the schema made impossible to express from what the agent got wrong.

## 5. The two models fail in nearly disjoint ways

| | GLM 5.3 Flash | DeepSeek V4 Flash |
|---|---|---|
| seat where errors concentrate | landlord | tenant |
| characteristic failure | conceding price | abandoning commitments |
| zero-rent signings | 362 | 0 |
| accepted a dominated offer | 14 | 0 |
| walked from a profitable hold | 2 | 88 |
| passed with profit available | 9 | 118 |
| signed above its own value | 6 | 30 |

This is a qualitative difference, not a difference of degree, and the
confirmatory comparison reported the two as indistinguishable. That is not a
contradiction: welfare is invariant to price, and both failure modes move
price or move who ends up unmatched rather than which listings clear. It is
the clearest available illustration of why an efficiency metric alone cannot
carry a capability claim.

## 6. What this corpus supports, and what it does not

Supports: a failure-mode description of each model; a check on whether a
proposed guard would have caught a real case; a regression set for the rent
floor and the individual-rationality gate; and an argument for which estimand
to make primary.

Does not support: a ranking. The counts are pooled over campaigns with
different panels, routes, prompts and schema versions, and the confirmatory run
contributes most of them. Nor does it support a claim about either model in
general, since every count is conditional on this environment, these two
seats, and an action schema now known to distort what an agent can express.

Two custody limits. The action layer is unverifiable outside this machine. And
the outcome layer's classes A and B require private values and costs, which no
published row carries, so they are reconstructed by regenerating each world
from the committed sweep contract with the deterministic generator. That
reconstruction is exact and re-derivable, but it is a derivation rather than a
reading, and it fails for any campaign whose configuration is not in a
committed sweep.
