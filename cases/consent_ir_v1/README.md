# Consent/IR V1 cases

These cases test whether an agent can construct a buyer-optimal barter cycle
while every participant strictly benefits according to the complete valuation
matrix visible to the agent.

The economic kernel originates in the private
`eval_dev/consent_ir_env.py` prototype distributed in the
`bundles-2026-09-03` release. The shared-runner adapter, JSON action contract,
typed measurement leaves, and case manifests are native to this repository.

The exact-cycle reference is a same-information optimum for the visible case.
It must not be reused as an oracle for a hidden-reservation market; such a
reference would instead be an extra-information upper bound.
