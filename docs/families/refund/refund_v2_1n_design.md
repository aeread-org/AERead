# Refund V2 1:N Pilot

Refund V2 begins with one customer and three support seats: intake, policy, and payments. V1.3 remains the 1:1 baseline and is not modified.

The intake seat collects only the required facts and hands the case to policy. The policy seat records one authorized proposal. The customer confirms or rejects that proposal. The payments seat is the only seat allowed to mutate the order ledger. Every handoff records its source, destination, case identifier, and proposal or fact provenance.

The pilot deliberately separates three measurements:

- `utility_score`: bilateral economic outcome, including the cost of an incorrect resolution;
- `transaction_score`: authorization, confirmation, exactly-once execution, amount, method, and denial invariants;
- `coordination_score`: required handoff chain and proposal provenance.

The first fixtures cover a positive apparel refund and a denial caused by liquid damage. Both use gradual disclosure: the customer begins with only a generic claim, and intake requests the required facts before routing.

The pilot is provider-free and deterministic. The next experiment replaces one scripted seat at a time with an LLM while keeping the remaining seats scripted. This isolates coordination failures from model-model interaction effects. N:1 and N:M remain deferred until capacity, matching, shared waiting costs, and a global welfare oracle are specified.
