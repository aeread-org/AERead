# Agreement case: free baselines on the admitted pack and its pilot

Step 2 of `docs/families/datacenter/agreement_confirmatory_plan.md` ("Before the confirmatory runs"), no model called. The counterpart in every world and seat is the
scripted negotiator in the style drawn from the public world and its seat (`drawn_public_v1`, arm F's counterpart).
A stand-in that knows both true types plays the other seat: `first_offer` signs the first offer worth signing;
`best_plan` is its best reply on a grid of asks, a ceiling against this script, not an attainable target.
Earnings are the seat's surplus over its own outside option, $k, redline fees deducted. Means over deal worlds.

| Pack | Deal worlds | Seat | First offer | Best plan | Best less first | First offer signed |
|---|---:|---|---:|---:|---:|---:|
| agreement_admitted_v1 | 45 of 60 | integrator | 113.25 | 192.98 | 79.74 | 44 |
| agreement_admitted_v1 | 45 of 60 | client | 66.76 | 137.94 | 71.18 | 35 |
| agreement_admitted_pilot_v1 | 12 of 12 | integrator | 133.18 | 213.04 | 79.86 | 11 |
| agreement_admitted_pilot_v1 | 12 of 12 | client | 82.9 | 175.59 | 92.69 | 9 |

Rebuild: `python -m aeread_families.datacenter_development.agreement_admitted_baselines --check` (per world and seat in `reports/baselines.json`).
