# Refund V2.1 1:N Pilot

Refund V2 begins with one customer and three support seats: intake, policy, and payments. V1.3 remains the 1:1 baseline and is not modified.

The intake seat collects only the required facts and hands the case to policy. The policy seat records one authorized proposal. The customer confirms or rejects that proposal. The payments seat is the only seat allowed to mutate the order ledger. Every handoff records its source, destination, case identifier, and proposal or fact provenance.

The pilot deliberately separates four measurements, in the following reporting
priority:

- `policy_compliance`: whether the proposed resolution follows the declared policy;
- `transaction_score`: authorization, confirmation, exactly-once execution, amount, method, and denial invariants;
- `coordination_score`: required handoff chain and proposal provenance;
- `utility_score`: holistic economic outcome, reported last as a Refund-specific diagnostic and not used as a cross-family scalar.

V2.1 expands the panel to six deterministic scenarios: full apparel refund,
liquid-damage denial, partial software refund, an apparel day-30 boundary case,
a conflicting electronics claim, and a perishable-goods denial caused by missing
evidence. The four product categories remain represented. All scenarios use
gradual disclosure: the customer begins with only a generic claim, and the policy
agent must request bounded fact batches before resolving the case.

The deterministic baseline and provider-backed runner write shared-runner
`RunPlan`, sealed `EvaluationReceipt`, and evidence records. The reproducible
Refund publication command runs `aeread export-tables` into a private analysis
directory, publishes only vetted canonical tables and sanitized trajectory
rows, and seals a standard publication manifest. The provider-backed runner
accepts `--active-agents` to replace any subset of the intake, customer, and
policy seats with LLMs while keeping the remaining seats scripted. The default
is `policy`, preserving the original V2.1 pilot; single-seat, pairwise, and
all-three-active configurations are available under the same cases and seeds.
The customer LLM receives private facts, but the verifier only accepts fields
explicitly requested by intake or policy, preserving gradual disclosure. The
policy observation excludes authorization fields, semantic scenario labels, and
scenario-bearing case identifiers.
Payments remains scripted and cannot be replaced by this version. This isolates
seat-specific behavior before studying model-model interaction effects. N:1
and N:M remain deferred until capacity, matching, shared waiting costs, and a
global welfare oracle are specified.
