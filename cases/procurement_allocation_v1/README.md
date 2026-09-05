# Procurement allocation v1

This family tests an interactive buyer that must acquire and negotiate supplier
information before allocating an electronics BOM. Marketplace listings and verbal
claims are provisional. Only environment-issued formal offers and verified sample
records are eligible for a final award.

The primary measurement is buyer contribution margin against a deterministic,
full-information upper bound. The objective accounts for completed on-time kits,
landed cost, verified yield, supplier return/refund recovery, working-capital cost,
information-acquisition cost, and shortfall penalties. Deferring remains an explicit
outside option.

The development set uses synthetic supplier identities and economics calibrated to
exercise the intended trade-offs. It does not represent live supplier commitments.
The six-case variance panel selects component families from the frozen 231-project
grounding snapshot, whose BOM counts remain demand proxies rather than production
forecasts.

## Interaction contract

The buyer gets ten turns and can ask a supplier for verbal confirmation, request a
formal quote, counter a quote, request an exact-variant sample, submit an award, or
defer. Verbal replies remain `verbal_claim` records. Only environment-issued
`formal_offer` and `verified_sample` records can satisfy the award gate, so natural
conversation is useful for discovery without becoming transaction authority.

Supplier counters can change unit price, MOQ, payment terms, refund window, and the
return-freight payer within deterministic private limits. Quote, counter, inquiry,
and sample actions consume declared time and information cost.

## Verifier family

This is an `objective_reference` case. Its primary estimand is buyer contribution
margin in USD and its reference is a deterministic full-information upper bound. The
enumerator knows which terms to acquire but still charges every quote, sample, and
counter action required to reach an award. The reference therefore removes search
uncertainty without making qualification free.

The frozen grounding case remains a separate `claim_reference` evaluation, and the
refund/return cases remain the home of constraint and exact-state verification. The
three verifier families are reported separately rather than collapsed into one score.

## Runner

`aeread_families.procurement_allocation.runner` exposes offline scripted and
OpenRouter setup builders. Its module CLI accepts a JSON array containing one action
object per turn and writes normal AERead evidence plus a replayable evaluation
receipt:

```bash
python -m aeread_families.procurement_allocation \
  --script /path/to/actions.json \
  --run-root /tmp/procurement-allocation-run
```

## Fixed-model qualification

The model campaign holds AERead Minimal Chat fixed as transport and evaluates
GLM 5.3 Flash on the procurement objective. Harness choice is not an estimand.
The recorded outcomes are feasibility, completed kits, contribution margin,
regret to the deterministic upper bound, violations, and the public action
trace. Without `--execute` the command prints the frozen plan and spends
nothing:

```bash
python -m aeread_families.procurement_allocation.model_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm_morph_case_variance_v2/qualification_attempt_001
```

After loading `OPENROUTER_API_KEY`, execute the declared six-case by three-seed
model qualification with:

```bash
python -m aeread_families.procurement_allocation.model_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm_morph_case_variance_v2/qualification_attempt_001 \
  --replicates 3 \
  --max-spend-usd 0.30 \
  --execute
```

Use `--resume` only after an interrupted invocation. Existing completed or
failed rows are digest-checked and never retried; only trajectories without a
result row run. Operational failures remain missingness rather than zero-margin
procurement outcomes. The pinned Morph route is preflighted before any missing
trajectory runs, SDK retries are disabled, and the conservative three-seed
spend ceiling is checked before execution.

### Evidence locations

The explicit run root is operational state and must remain under ignored
`runs/`. It contains the frozen model plan, digest-bound result rows, sealed
provider events, receipts, replay artifacts, locks, and resumable failure state.
The campaign rejects any live output root under an `evidence` directory.

If a run is promoted for review, publish only a compact sanitized record under
`evidence/<publication_id>/`. That tracked bundle binds to
the raw plan, result, receipt, and summary digests, but excludes provider
payloads, full prompts, event logs, locks, and raw artifact stores. `docs/`
contains explanatory material only; it is not an evidence location.

Promotion is a separate, provider-free step:

```bash
python -m aeread_families.procurement_allocation.model_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm_morph_case_variance_v2/qualification_attempt_001 \
  --publish-only \
  --publication-root \
  evidence/procurement_allocation_glm_morph_case_variance_v2
```

This qualification uses six distinct synthetic procurement worlds. Three
inference seeds per world measure stochastic reliability; the six distinct BOM and
economic configurations provide the declared minimum for a case-variance pilot.
The result remains a bounded diagnostic on this curated panel, not a
population-level model ranking.

## Targeted opaque Qwen holdout

`qwen_holdout_v1/opaque/` contains six new economic worlds frozen after the
constraint-ledger V2 development result. Four require a capacity-limited split,
including one dual-component split and one multi-unit BOM. Two require an exact
18-kit minimum-service allocation because either total qualified capacity or the
cash budget prevents the 20-kit target. Supplier identifiers are deterministic
opaque hashes and listing order is deterministically shuffled.

The panel is held out from model execution but targeted using observed residual
failure modes, so it supports a transfer diagnostic rather than a population claim.
Every case has a positive full-information award, a public-action-reachable oracle,
at most ten required actions, a new case digest, and a new economic-world digest
relative to the development, confirmatory, and risk-gate panels. Regenerate it with:

```bash
python -m aeread_families.procurement_allocation.qwen_holdout_case_matrix --write
```

The paired campaign holds the Qwen3 235B Google route, Minimal Chat harness,
structured action contract, verifier, retry policy, cases, and three inference seeds
fixed while comparing the unscaffolded prompt with frozen constraint-ledger V2. Its
36 scored trajectories and two unscored canaries have a $0.94704 conservative total
ceiling and a $1.14 hard ceiling. Print the sealed no-spend plan with:

```bash
python -m aeread_families.procurement_allocation.qwen_holdout_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_qwen3_235b_google_holdout_v1/qualification_attempt_001
```

Execution advances six sequential rows per invocation. Continue a failure-free
checkpoint with `--execute --resume`; never replace a failed arm or inspect efficacy
to decide whether to continue. Publication requires all 36 rows to complete and
receipt-replay with exact accounting. Favorable and unfavorable integrity-qualified
results are both publishable.

The qualified live run completed and replayed all 36 rows with zero operational
failures and $0.1125104706 total spend including both canaries. The preregistered
residual-capability support rule was not met. V2 removed malformed actions but did
not produce a feasible purchase award or a single submitted multi-offer split; its
only feasible terminal row was an explicit defer. See the campaign document and
tracked evidence bundle for the paired effects and typed failure breakdown.

## Blinded supplier-label mirror

`blinded_v3/` contains a deterministic paired mirror of the six generated cases.
Only supplier identifiers, neutral display names, and listing order change; the
economics, objectives, policies, substantive listing claims, world seeds, and solver
upper bounds remain fixed. Regenerate it with:

```bash
python -m aeread_families.procurement_allocation.case_matrix \
  --panel blinded-v3 --write
```

Print the no-spend paired plan, or execute it after loading `OPENROUTER_API_KEY`:

```bash
python -m aeread_families.procurement_allocation.blinded_invariance \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm_morph_blinded_invariance_v3/qualification_attempt_001

python -m aeread_families.procurement_allocation.blinded_invariance \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm_morph_blinded_invariance_v3/qualification_attempt_001 \
  --max-spend-usd 0.30 \
  --execute
```

The comparator pairs v3 rows to the frozen v2 campaign by case slug and inference
seed. A behavior or score change remains a valid finding; missing or unreplayed rows,
route drift, changed upper bounds, or digest failures block qualification.

Every fresh execution first runs one unscored request-shape admission canary. A
provider rejection stops before the panel; a later operational failure seals that
cell and aborts the remaining queue. Do not resume such an aborted attempt—use a new
attempt root so transient provider availability cannot selectively replace rows.

The qualified v3 run is stored operationally at
`runs/procurement_allocation/procurement_allocation_glm_morph_blinded_invariance_v3/qualification_attempt_004`.
Its sanitized, digest-bound review bundle is
`evidence/procurement_allocation_glm_morph_blinded_invariance_v3/`.

## Paired open-source model comparison

The Mistral Small 4 follow-up holds the six v2 cases, three inference seeds, action
budget, Minimal Chat transport, and objective verifier fixed while changing the
model route. It compares each Mistral row with the qualified GLM baseline row sharing
the exact case ID and inference seed. Print the no-spend plan with:

```bash
python -m aeread_families.procurement_allocation.model_comparison \
  --run-root \
  runs/procurement_allocation/procurement_allocation_mistral_small4_case_variance_v1/qualification_attempt_001
```

Add `--execute` only after loading `OPENROUTER_API_KEY`. Execution is sequential,
starts with an unscored exact-request admission canary, aborts after the first
operational failure, and defaults to a $0.35 scored-run ceiling. Model effects use
paired deltas and exact six-world cluster-bootstrap intervals; they remain a bounded
panel diagnostic rather than a general model ranking.

The first two fresh Mistral attempts each admitted the exact request canary and then
returned an empty response on their first scored call. Both stopped with zero
completed trajectories and 17 unattempted trajectories. This is a route-admission
rejection, not a procurement score. Reproduce the sanitized audit projection with:

```bash
python -m aeread_families.procurement_allocation.model_comparison \
  --audit-attempt-root runs/procurement_allocation/procurement_allocation_mistral_small4_case_variance_v1/qualification_attempt_001 \
  --audit-attempt-root runs/procurement_allocation/procurement_allocation_mistral_small4_case_variance_v1/qualification_attempt_002 \
  --publication-root evidence/procurement_allocation_mistral_small4_case_variance_v1
```

## Deterministic public-observation policy baselines

`policy_baselines` runs four local policies through the same scheduler, environment,
measurement leaf, and receipt-replay path as the model campaigns:

- `defer` establishes the explicit outside option;
- `displayed_price_greedy` qualifies the cheapest visible listing first;
- `listing_claim_fit` prioritizes overlap with the required variant claim; and
- `semantic_hint` additionally uses suggestive supplier identifiers and names.

The adaptive policies can inspect only the public observation serialized in each
provider request. They request formal offers and exact-variant samples, use newly
visible capacity, MOQ, lead time, quality, and landed-cost terms, and either submit a
service-feasible award or explicitly defer. They never receive `private_terms` or the
case object.

The campaign pairs each policy across the labeled v2 and opaque/reordered v3 panels.
Planning is offline and execution has zero provider cost:

```bash
python -m aeread_families.procurement_allocation.policy_baselines \
  --run-root runs/procurement_allocation/procurement_allocation_public_policy_baselines_v1/qualification_attempt_001

python -m aeread_families.procurement_allocation.policy_baselines \
  --run-root runs/procurement_allocation/procurement_allocation_public_policy_baselines_v1/qualification_attempt_001 \
  --publication-root evidence/procurement_allocation_public_policy_baselines_v1 \
  --execute
```

These policies are diagnostic floors, not oracle substitutes. The deterministic
full-information bound remains the certified reference.

The qualified run completed and replayed all 48 rows at zero provider cost. Both
displayed-price and listing-claim policies were feasible in 6/6 worlds on each
surface, with 19.6667 mean completed kits and $58.0359 mean contribution margin.
Their blinded-minus-labeled outcome deltas were exactly zero. The semantic-hint
policy changed outcomes in three worlds and improved by $4.0138 after names became
opaque, showing that suggestive labels are not uniformly helpful.

Against GLM after averaging its three seeds within each world, displayed-price greedy
had +$28.4986 mean margin on labeled/original cases and +$54.9200 on
opaque/reordered cases. The associated six-world cluster intervals exclude zero, so
this panel is not saturated by the qualified GLM route. The tracked evidence is at
`evidence/procurement_allocation_public_policy_baselines_v1/`.

## Strategy-scaffold treatment

The next model intervention keeps the GLM revision, provider route, Minimal Chat
transport, action schema, six economic worlds, and three paired inference seeds
fixed. It changes only the buyer instructions by adding a public-evidence decision
procedure: ignore supplier names, conserve the action budget, qualify a minimal
supplier set with formal quotes and samples, check capacity/service/cash constraints,
and award only on evidence-qualified terms.

Print the sealed 36-trajectory plan without provider calls:

```bash
python -m aeread_families.procurement_allocation.strategy_scaffold \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm_morph_strategy_scaffold_v3/qualification_attempt_001
```

After loading `OPENROUTER_API_KEY`, add `--execute`, a direct
`evidence/procurement_allocation_glm_morph_strategy_scaffold_v3` publication root,
and a total spend ceiling of at least $0.5088. Execution defaults to one cell at a
time because route reliability, rather than local throughput, is the current
bottleneck. It checkpoints after six completed trajectories; continue the same root
with `--resume` only after a failure-free checkpoint. An unscored exact-request
canary runs once, and any operational failure stops the remaining queue and
permanently disqualifies that attempt root.

To seal the same treatment to an alternate endpoint, add either
`--candidate-id glm53_flash_reka` or
`--candidate-id glm53_flash_cloudflare` and use the route-specific campaign root
printed by the dry-run plan. Each conservative treatment ceiling is $0.5700.
Publication also requires new unscaffolded labeled and opaque controls from that
same route; the runner deliberately rejects cross-provider controls.

The analysis reports scaffold-minus-control effects separately on labeled/original
and opaque/reordered cases after averaging seeds within each world. It also reports
the change in the opaque-minus-labeled effect. Positive absolute surface-gap
reduction means the scaffold mitigated presentation sensitivity; the campaign does
not assume that outcome in advance.

This is an adaptive development treatment. In the first v1 probe, one labeled
trajectory reached an award in six actions but selected formally late suppliers and
completed zero kits; the next row then hit a provider rate limit. V2 made deadline
feasibility a hard pre-price and pre-sample gate. It completed and replayed 14 labeled
rows before another typed 429, including feasible 19-kit outcomes on all three
deadline seeds. However, all three MOQ/capacity seeds submitted quantities above the
selected offers' capacities. V3 adds the explicit split-capacity rule and failure-free
batch checkpoints. Neither incomplete attempt is a treatment-effect estimate, and a
held-out panel is still required for a confirmatory claim.

## Confirmatory v1 holdout

`confirmatory_v1/` contains twelve economic worlds created only after the V4
strategy prompt was frozen. The labeled and opaque directories are paired mirrors:
supplier identifiers, display names, and listing order change, while objectives,
interaction costs, substantive listings, private terms, world seeds, and certified
upper bounds remain invariant. No development world seed or case digest is reused.

The holdout varies landed freight and duty, quality/refund tails, capacity and order
steps, budget-gated counters, exact-variant decoys, borderline service, sample lead
time, refund negotiation, financing terms, delivery reliability, multi-unit BOM
arithmetic, and negotiated MOQ. Component families still come from the frozen
231-project grounding snapshot; supplier economics remain synthetic.

Regenerate and verify the manifests without provider calls:

```bash
python -m aeread_families.procurement_allocation.confirmatory_case_matrix \
  --surface labeled --write
python -m aeread_families.procurement_allocation.confirmatory_case_matrix \
  --surface opaque --write
```

These cases become confirmatory evidence only under a separately frozen execution
and analysis plan. Inspecting the oracle during case qualification is allowed;
changing the V4 prompt or the outcome rule after live treatment results are visible
requires a new campaign identity.

Print the no-spend frozen execution plan with:

```bash
python -m aeread_families.procurement_allocation.confirmatory_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v1/qualification_attempt_001
```

Live execution is sequential, checkpoints after 12 new rows, and runs both controls
before either treatment. Add `--execute --max-spend-usd 2.30` for the first batch and
`--resume` for later failure-free checkpoints. An operational failure seals the
attempt. Publication is a separate `--publish-only` invocation targeting one direct
`evidence/procurement_allocation_glm53_flash_parasail_strategy_confirmatory_v1/`
bundle.

## Held-out risk-gate factorial

`risk_gates_v1/` contains six additional economic worlds created after the
confirmatory V2 result was analyzed. Three isolate sample-schedule reasoning and
three isolate landed-cash arithmetic. Each has a labeled and opaque/reordered
surface with identical economics, and no development or confirmatory seed or case
digest is reused.

The sample-timing cases allow an explicit verbal `sample_logistics` inquiry. It
reveals sample turnaround and cost but does not issue a formal offer, verify quality,
or authorize an award. The landed-cash cases make low-sticker allocations exceed
budget after freight, duty, or MOQ rounding while preserving a positive feasible
alternative.

Regenerate the cases without provider calls:

```bash
python -m aeread_families.procurement_allocation.risk_gate_case_matrix \
  --surface labeled --write
python -m aeread_families.procurement_allocation.risk_gate_case_matrix \
  --surface opaque --write
```

The corresponding V2 campaign is an adaptive 2x2 prompt factorial, not a new
confirmation of V4. Its four conditions are frozen V4, sample-schedule gate only,
landed-cash gate only, and both gates together. V2 preserves the V1 scientific
contract and adds slower bounded retry pacing after V1 was invalidated by repeated
provider rate limits.

## Regret decomposition of published GLM rows

`regret_decomposition` replays every tracked GLM evidence row through the
deterministic environment without provider calls and splits each feasible award's
regret into exact additive term gaps against the full-information plan. All 216 rows
across the development, blinded, scaffold, and confirmatory bundles replay exactly.
Working-capital cost is 61% of feasible-award regret and traces to the payment-terms
counter the oracle uses in 67 of 101 feasible rows and the model used in 7. See
`docs/families/procurement-allocation/campaign.md` and
`evidence/procurement_allocation_glm_regret_decomposition_v1/`.

```bash
python -m aeread_families.procurement_allocation.regret_decomposition \
  --publish \
  --publication-root evidence/procurement_allocation_glm_regret_decomposition_v1
```

## Negotiation-worksheet treatment

`negotiation_worksheet_campaign` appends a working-capital worksheet to the frozen V4
prompt and pairs 72 new GLM Parasail rows against the sealed confirmatory V2 V4 arm
by case and seed. Print the no-spend plan, execute in twelve-row checkpoints, and
publish separately:

```bash
python -m aeread_families.procurement_allocation.negotiation_worksheet_campaign \
  --run-root \
  runs/procurement_allocation/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v1/qualification_attempt_001 \
  --execute --max-spend-usd 2.19
```

The qualified run (attempt 004, after a timeout-sealed and a 429-sealed attempt)
completed and replayed all 72 rows for $0.1993. The preregistered rule was not met:
worksheet-minus-V4 regret was -$3.82 per world with interval [-$12.69, $4.48]. The
payment-terms lever transferred as intended, cutting that world's regret from $48.63
to $10.68, but counters displaced the sample step on three rows and produced
unverified-sample failures. See the campaign document and
`evidence/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v1/`.

`negotiation_worksheet_v2_campaign` reorders the worksheet so a verified sample
precedes any counter or award line. Its qualified run completed all 72 rows for
$0.2065. The rule was again not met: regret -$0.28 per world ([-$7.37, $7.23]) and
feasibility -0.014 ([-0.083, 0.042]). Counter-induced sample skips disappeared and
the labeled payment-terms result held, but opaque ids hid which supplier would accept
longer terms, and two opaque negotiated-MOQ rows awarded below minimum service after
countering MOQ down. See
`evidence/procurement_allocation_glm53_flash_parasail_negotiation_worksheet_v2/`.

## Pre-award check

The buyer can now send `check_award` with the exact lines it intends to submit and
receive the verifier's own projection: feasibility, violations, completed kits,
margin, and cash spend, computed by the same `evaluate_award` as the terminal score
on the current formal offers and verified samples. A check costs one action and
nothing else and never ends the episode. `pre_award_check_campaign` freezes a
treatment that adds a mandatory clean check before any award to the worksheet V2
procedure, paired against the sealed confirmatory V4 rows.

