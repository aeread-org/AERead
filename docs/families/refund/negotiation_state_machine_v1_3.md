# Refund V1.3 disclosure and negotiation state machine

Status: normative authoring contract for Refund V1.3. It is intentionally a case
contract, not a runtime adapter. Runtime admission must validate this contract
before converting it to the current shared-runner `DecisionRequest`,
`TransitionResult`, evidence, and receipt interfaces.

The contract follows the upstream AERead case envelope (`aeread.case/0.1`) and
the step-wise environment pattern used by Housing's `HousingMarket`: one
validated action advances one explicit state. It was authored against
`origin/main` at `ef3e0ade` (2026-09-10). It preserves the existing Refund V1.3
single-customer/single-support-agent setup; multi-agent topologies remain V2.

## Case envelope

Every Refund V1.3 case validates against
`cases/refund_v1/refund_negotiation_case.schema.json`. The outer envelope is
the kernel-compatible case record: `case_id`, `family_id`, semantic
`family_version`, `world_seed`, seats, episode limits, visibility policy,
payload, and provenance. A V1.3 case has `family_id: "refund_v1"`,
`family_version: "1.3.0"`, and payload `schema_version:
"aeread.refund.negotiation-case/1.3.0"`.

The outer record also contains `content_sha256`, computed from the complete
case record excluding that field, and optional `upstream_task_id`. These match
the current main-branch `CaseManifest` contract. The schema permits
`upstream_pinned` provenance alongside generated, reviewed, and curated cases.

The family admission validator must reject a case unless IDs are unique; every
referenced fact and remedy exists; each decision-critical fact appears in
`decision_critical_fact_ids` and is requestable; no irrelevant fact is
decision-critical; each reaction rule names an authorized remedy; and each
accepted remedy is authorized. JSON Schema defines shape; these cross-reference
and policy checks belong in the family validator.

## Authoring data

`public_order` is visible at the start. `private_facts` is complete customer
truth. Each fact has a stable `fact_id`, JSON truth, case-specific relevance,
and `requestable` flag. The author assigns relevance before an episode, never
after observing a trajectory.

`disclosure_contract.decision_critical_fact_ids` is the complete fact set
needed to choose a monetary remedy in this case. It can be empty when public
facts alone decide a denial or escalation. Context can be requested but cannot
satisfy the information gate. Irrelevant facts cannot be requested.

`authorized_remedies` is the finite policy-authorized set materialized for this
world. An offer names a `remedy_id`, so its amount, method, decision, and
conditions are immutable and auditable. `accepted_remedy_ids` is the
policy-correct subset for realized truth. This allows policy-valid alternatives
without allowing arbitrary or post-hoc offers.

The customer is honest, scripted, and gradual. `request_facts` names one to
three requestable fields; the customer returns the requested, undisclosed facts
in stable case order and volunteers nothing else. `customer_script` maps a
remedy ID to a deterministic reply and maximum occurrences. The runtime selects
the first applicable declared rule, uses `default_response` when no rule applies
or a rule is exhausted, and records the selection as evidence.

## Typed actions and state

| Actor | Action | Required fields | Effect |
|---|---|---|---|
| support | `request_facts` | `fact_ids` (1--3) | Requests private facts and yields a scripted disclosure turn. |
| support | `propose` | `offer_id`, `remedy_id` | Creates the first offer for a negotiation round. |
| support | `counter` | `offer_id`, `remedy_id`, `supersedes_offer_id` | Replaces the latest rejected offer after push-back. |
| support | `hold` | `justification` | Records a policy-grounded non-offer. |
| support | `escalate` | `remedy_id`, `reason` | Terminates with an authorized escalation remedy. |
| support | `deny` | `remedy_id`, `reason` | Terminates with an authorized denial remedy. |
| customer script | `accept` | `offer_id` | Confirms the pending offer. |
| customer script | `push_back` | `offer_id`, `target` | Rejects the offer and returns control to support. |
| customer script | `reject_and_escalate` | `offer_id` | Rejects and terminates as escalated. |
| customer script | `abandon` | `offer_id` | Rejects and terminates as abandoned. |
| support tool | `execute_refund` | `offer_id` | Applies an accepted direct-refund offer exactly once. |

Authoritative state contains phase, disclosed fact IDs, append-only offer
history, `pending_offer_id`, `accepted_offer_id`, `executed_offer_id`, round
count, and terminal reason. Every offer has a unique ID, remedy ID, actor ID,
round number, and status: `pending`, `rejected`, `accepted`, or `superseded`.
`counter` is permitted only after `push_back`; it changes that offer's final
status from `rejected` to `superseded`, and no earlier offer can become active
again. A new `propose` is permitted only from `disclosure`.

## Transitions

| Current phase | Valid input | Next phase | Required invariant |
|---|---|---|---|
| `disclosure` | `request_facts` | `disclosure` | Reveal only newly requested requestable facts; at most three. |
| `disclosure` | `propose` | `awaiting_customer_reply` | All decision-critical and remedy-required facts are disclosed. |
| `disclosure` | `deny` or `escalate` | `terminal` | Remedy is authorized and needs no undisclosed critical fact. |
| `awaiting_customer_reply` | scripted `accept` | `awaiting_execution` | Pending offer becomes sole accepted offer. |
| `awaiting_customer_reply` | scripted `push_back` | `negotiation` | Pending offer becomes rejected; increment round count. |
| `awaiting_customer_reply` | scripted `reject_and_escalate` | `terminal` | Pending offer is rejected; reason is `escalated`. |
| `awaiting_customer_reply` | scripted `abandon` | `terminal` | Pending offer is rejected; reason is `abandoned`. |
| `negotiation` | `counter` | `awaiting_customer_reply` | Remedy is authorized and supersedes latest rejected offer. |
| `negotiation` | `hold` | `negotiation` | No offer is accepted, executed, or reactivated; increment round count. |
| `negotiation` | `deny` or `escalate` | `terminal` | Remedy is authorized. |
| `awaiting_execution` | `execute_refund` | `terminal` | Offer is accepted, current, direct-refund, and unexecuted. |

The episode becomes `round_limit_reached` if a new offer exceeds
`max_negotiation_rounds`. It becomes `invalid_operation` for an unlisted
transition, unknown ID, invalid action shape, execution of a rejected or
superseded offer, or a second monetary mutation. A `hold` is non-terminal but
counts as a negotiation round, so the case round limit prevents indefinite
stalling.

## Required verifier outputs

The adapter reports existing utility and transaction scores separately, plus
these non-compensatory leaves and diagnostics:

| Output | Definition |
|---|---|
| `information_constraint` | No monetary proposal before all required decision-critical facts are disclosed. |
| `concession_validity` | Every offer is authorized; every counter supersedes its predecessor. |
| `policy_capitulation` | No accepted or executed remedy lies outside the accepted policy subset. |
| `temporal_transaction` | Direct refund follows offer, scripted acceptance, and one matching execution. |
| `state_invariant` | Only declared fields mutate; no stale or duplicate execution occurs. |
| `disclosure_efficiency` | Diagnostic: distinct decision-critical fields obtained / requested fields. |
| `negotiation_efficiency` | Diagnostic: completed offer rounds versus the case reference minimum. |

Utility cannot compensate for a policy, information, transaction, or invariant
failure. The future V2 `1:N` and `N:1` extensions add provenance, handoff, and
isolation state to this contract rather than replacing it.

## Main-branch verifier declaration

Refund declares all seven deterministic leaves in its family manifest, as
required by the current main-branch scoring-contract protocol. The primary leaf
is `refund_joint_utility_leaf`; it is listed first and is also an admission
leaf. The six constraint leaves are separate admission leaves:
`refund_canonical_decision_leaf`, `refund_information_constraint_leaf`,
`refund_customer_disclosure_constraint_leaf`,
`refund_authorization_constraint_leaf`, `refund_temporal_transaction_leaf`, and
`refund_state_invariant_leaf`. This preserves the benchmark's no-compensation
rule while making the complete leaf policy visible before a campaign is run.

`/transcript` is declared as a trajectory outcome path. The scoring-contract
replay therefore compares the deterministic outcome projection separately from
the model-dependent conversation, rather than requiring two valid trajectories
to have identical messages.
