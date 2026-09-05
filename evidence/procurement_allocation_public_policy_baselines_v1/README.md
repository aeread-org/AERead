# Procurement allocation public-policy baselines v1

This bundle is the sanitized, digest-bound review projection for four deterministic
public-observation policies on the labeled/original and opaque/reordered procurement
panels.

All 48 planned policy trajectories completed and receipt-replayed. Solver upper
bounds remained invariant and provider cost was zero. The displayed-price and
listing-claim policies were feasible in all six worlds under both surfaces, averaged
19.6667 completed kits and $58.0359 contribution margin, and had zero paired outcome
change after blinding/reordering.

The semantic-hint policy was feasible in all worlds but changed outcomes in three.
Removing suggestive names improved its mean completed kits by 3.3333 and contribution
margin by $4.0138. Supplier labels were therefore not a uniformly beneficial shortcut.

`reports/glm_context.json` compares the primary displayed-price policy with the two
qualified GLM campaigns after averaging GLM's three inference seeds within each of
the six economic worlds. The policy-minus-GLM mean contribution-margin difference is
+$28.4986 on labeled/original cases and +$54.9200 on opaque/reordered cases. These
six-world cluster intervals and effects describe this curated panel only; they are
not population estimates or a general model ranking.

Raw observations, prompts, event logs, provider fixtures, and replay stores remain
under the ignored `runs/` tree. Published rows contain public actions, outcomes,
usage-free request digests, and receipt/result hashes, never private supplier terms.
