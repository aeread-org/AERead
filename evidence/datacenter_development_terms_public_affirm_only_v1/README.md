# Public five-cluster affirm-only replication v1

This sanitized campaign tests one frozen candidate-selection instruction across
five independent public SEC filing clusters: include only action and claim labels
the analyst affirms as supported and omit labels it rejects. Each treatment case
preserves its baseline evidence, hidden oracle, title, authority, cutoff, source
cluster, and world seed. The visible split and case ID are changed to a neutral
derived identity. Baselines are hash-bridged from the prior two-model campaign
and GPT-OSS add-on; they were not rerun.

The treatment panel uses the same three exact Apache-2.0 open-weight
model/provider routes and the same three inference seeds as the baselines.
Forty-one of 45 treatment cells completed, were included, route-verified, and
replayed. Four Mistral/DeepInfra calls were rate-limited and remain operational
exclusions without retry. Successful-call cost is a $0.0070164666 lower bound.

Forty-one of 45 baseline-treatment pairs are reportable. The intervention
produced four hard-gate rescues and no regressions. GPT-OSS improved from 80% to
100% hard-gate passage across 15 pairs, including all three integrated Denton
cases, with mean score delta +0.2707. Qwen improved from 73.3% to 80%, with one
rescue and mean delta +0.0133, but still selected two forbidden actions in every
integrated Denton treatment seed. Mistral had 11 reportable pairs, 100% hard-gate
passage in both conditions, mean delta 0, and four missing pairs.

Effects vary by filing cluster. Mean score delta was positive for the ground
lease, phased-colocation, and linked land/power/construction cases, but negative
for credit-facility and large-load cases. The sentence is therefore a useful
model- and case-dependent guardrail, not a universal quality improvement.

Five source clusters improve replication over the single-cluster mechanism
probe, but this remains an exploratory fixed-case diagnostic. It does not
establish a population causal effect, project generalization, an inferential
model ranking, or a winner. Raw prompts, provider payloads, reasoning, complete
receipts, and failure messages remain in ignored local run state.
