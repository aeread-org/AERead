# Data-center development negotiation cases

This family is staged by negotiated agreement stack. Results from different
stages must not be pooled without an analysis plan that explicitly conditions
on the family version.

| Scope | Family version | Negotiated agreements | Scripted actions |
|---|---:|---|---:|
| V0 | `1.0.0` | service, construction loan | 6 |
| V1 | `1.1.0` | power, EPC, service, construction loan | 12 |
| V2 | `2.0.0` | land, power, EPC, service, land amendment, construction loan | 18 |
| V2 objective calibration | `2.1.0` | V2 with an objective-visible developer and exact-package controlled counterparties | 18 |

Run the provider-free admission fixtures from the repository root:

```bash
PYTHONPATH=src python -m aeread_families.datacenter_development --scope v0 --run-root /tmp/datacenter-v0
PYTHONPATH=src python -m aeread_families.datacenter_development --scope v1 --run-root /tmp/datacenter-v1
PYTHONPATH=src python -m aeread_families.datacenter_development --scope v2 --run-root /tmp/datacenter-v2
```

Each command executes the real shared harness, seals five independent verifier
leaves, and performs state-and-score replay. These curated provider-free cases
are development fixtures, not live-model benchmark results.

Run the frozen V2 interaction campaign after its provider-free and profile
admission gates:

```bash
PYTHONPATH=src python -m aeread_families.datacenter_development.stack_campaign
```

The campaign pairs three inference seeds across two open-source routes and two
conditions: a live developer with scripted counterparties, and homogeneous
model-to-model negotiation across all six seats. It disables response caching,
allows only one active trajectory per route provider, and has a $1.50 campaign
ceiling. Because both conditions use the same single curated project, results
remain diagnostic and do not support population inference, a model winner, or
a causal condition-effect claim.

The `v2/objective_bounded_001.json` case is a separate calibration identity.
It exposes the developer objective and outside option, bounds every numeric
counterparty term, and uses complete-package equality in its controlled runner.
Its exact-optimum reference therefore applies only to that controlled condition;
it must not be reused for model-to-model negotiation.

The objective-grounding campaigns retain separate identities because route and
adapter changes alter the delivered treatment. V1 and V2 are preserved as
all-excluded provider-compatibility evidence. V3 uses the versioned
parameter-compatible adapter and produced the first included live-model
trajectories:

```bash
PYTHONPATH=src python -m aeread_families.datacenter_development.objective_campaign_v3
PYTHONPATH=src python -m aeread_families.datacenter_development.objective_publication_v3
```

All three are single-project diagnostics. In particular, their seed replicates
measure inference variability on one curated case rather than independent
project variation.

The separate [`datacenter_counteroffer_adoption_v1`](../datacenter_counteroffer_adoption_v1/)
family reuses the objective-bounded project by content hash to diagnose exact
written-counteroffer adoption at three nested agreement depths. Its partial
prefixes are not assigned project cash-flow meaning.
