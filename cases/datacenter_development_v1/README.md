# Data-center development negotiation cases

This family is staged by negotiated agreement stack. Results from different
stages must not be pooled without an analysis plan that explicitly conditions
on the family version.

| Scope | Family version | Negotiated agreements | Scripted actions |
|---|---:|---|---:|
| V0 | `1.0.0` | service, construction loan | 6 |
| V1 | `1.1.0` | power, EPC, service, construction loan | 12 |
| V2 | `2.0.0` | land, power, EPC, service, land amendment, construction loan | 18 |

Run the provider-free admission fixtures from the repository root:

```bash
PYTHONPATH=src python -m aeread_families.datacenter_development --scope v0 --run-root /tmp/datacenter-v0
PYTHONPATH=src python -m aeread_families.datacenter_development --scope v1 --run-root /tmp/datacenter-v1
PYTHONPATH=src python -m aeread_families.datacenter_development --scope v2 --run-root /tmp/datacenter-v2
```

Each command executes the real shared harness, seals five independent verifier
leaves, and performs state-and-score replay. These curated provider-free cases
are development fixtures, not live-model benchmark results.
