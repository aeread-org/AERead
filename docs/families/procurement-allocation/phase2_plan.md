# Procurement Phase 2: economic search and walk-away decisions

This is a new campaign, `procurement_phase2_economic_epistemics_v1`, with a new
$0.45 total ceiling. It does not pool results or billing with PR #189. Implementation,
prompts, worlds, scoring and seeds are fixed before the pilot. A failed pilot stops
confirmation; changing the design requires a new campaign identity and review.

## What changes

Eight synthetic markets each expose eight suppliers for one bottleneck BOM component
in a 20-kit assembly. Other assembled components are sunk costs. Two markets require
splitting because every supplier has capacity 12, below minimum service 18. Two have
quality uncertainty, two require paying for timely delivery, and two make every
purchase infeasible. Ten actions allow at most four quote-and-sample qualifications
plus an award; repeat sampling, inquiry and negotiation consume the remaining budget.

Both arms receive identical observations, binomial sampling, economic formulas,
action schemas, cost limits and model settings. Treatment adds a prioritization,
evidence, splitting and cost-aware stopping procedure. Control chooses its own strategy.
`check_award` is absent from the schema and rejected at parsing, legality and execution.
Its legacy implementation used true hidden yield, so retaining it would defeat this
experiment's information boundary. Both arms retain the formal-offer, exact-variant,
verified-sample gate. This is a bundled prompt comparison, not an isolated tool ablation.

Historical quality estimates are imperfect priors about previous batches. In one
quality world the most promising prospect really yields 96%; in the other it yields
70%. Current samples contain 24 binomial trials, accumulate on repetition and expose
only observed yield. True yield determines terminal economic value. The offline
reference uses a declared 25% listing-price contingency, a two-day lead buffer and
a $0.05/unit shipping prior for unquoted prospects; formal terms supersede estimates. A quote and sample
each take one day; samples cost $0.65 and quotes $0.10. Research cannot be erased by
submitting an invalid award. No duty, financing or return recoveries complicate this
version's economic calculation.

## Trap contract and measurement

Every world exposes certified market-wide delivery and price floors, separately
labelled from nonbinding supplier claims. The validator checks these floors against
all reachable private and negotiated terms. One trap's delivery floor exceeds its
deadline; the other cannot afford minimum service even with perfect yield, free
research and no shipping. These are evidence-supported impossibility certificates.
They test recognizing a legitimate walk-away, not discovering eight hidden bad
suppliers. Discoverable traps without such certificates remain a future design.

The full-information optimum includes immediate `defer` at $0. The reference pays
necessary quote/sample costs for awards and respects ten actions. Deferral **after**
research has regret equal to research cost. Invalid purchases retain research costs
and a separate constraint failure; they do not cause an invented $50 inventory loss.
A zero-regret invalid trap award therefore cannot satisfy the validity guard.

Primary endpoint: treatment minus control regret, paired by environment/inference seed,
averaged across seeds within world, then equally across eight worlds. Report 50,000
paired world bootstrap resamples (seed 20260919), percentile 95% interval. A benefit
claim requires all planned observations replayed, finite consistent economics, no
treatment constraint violations, and an upper interval endpoint below zero. Failed
or missing episodes retain their planned cells and typed status. Never drop them to
obtain significance.

Secondary diagnostics: category and nontrap effects, explicit trap deferral and invalid
award rates, quote order, sampled suppliers, research costs, sample/qualification counts
and number of suppliers in awards. Traces permit inspection of post-sample continuation.
Behavior is observable; internal reasoning and Bayesian optimality are not established.

## Stages and cost control

1. **Offline:** author eight fixed worlds; screen 24 noise seeds per world against
   public-information reference, listing-price greedy, always-defer and invalid
   always-buy controls. Require at least 15% mean greedy/reference regret spread,
   divided by the certified positive bound, in six nontraps. Prove purchase
   infeasibility in both traps. Run focused and full provider-free tests.
2. **Admission:** register the new family through the shared runner's contribution
   contract, including closed action/observation schemas, source-bound conformance,
   explicit resource limits and actual human QC approval of the contribution digest.
   This gate is implemented in `PluginRegistry.register`; adding a trusted built-in
   identity or substituting fabricated reviewer evidence would bypass it.
3. **Canaries:** one unscored action per arm validates the actual pinned route and
   output contract. These requests and retries count toward $0.45.
4. **Pilot:** eight worlds × one seed (`52001`) × two arms = 16 episodes. Require
   completed replayed trajectories without invalid-action or exhausted-budget failures,
   at least one explicit trap defer, and at least one profitable valid nontrap award.
   Do not select on treatment advantage. One seed cannot identify within-world model
   variance. The shared gate named `variance_pilot` records this limitation explicitly.
5. **Confirmation:** seal a confirmation `plan_sha256` after the operational pilot;
   execute eight worlds × three seeds (`53001`–`53003`) × two arms = 48 episodes,
   once. Both arms share each supplier-specific binomial stream. Arm order alternates
   by world and seed. No outcome-based prompt or world changes are allowed.

An episode is **not one API call**: it may require ten actions and a bounded retry.
The fresh Phase 2 ledger reserves a conservative input-byte/output-token cost before
every request. Unknown charges retain their reservations. Only an explicit retryable
HTTP 429 can retry once, after at least 60 seconds and at most 180 seconds; all other
ambiguous outcomes stop dispatch. No performance-based retries. The implementation
caps output at 1,200 tokens/action and each trajectory at $0.025. Confirmation also
requires the pilot-based cost projection to fit the remaining total budget; the
per-request hard guard still applies even if that projection is wrong.

The initial route is the same pinned GLM-5.3-Flash/Parasail candidate as recovery,
subject to a fresh metadata preflight and canaries. Gemini helper calls are optional,
not benchmark substitutions, and would also count against the Phase 2 ceiling.
No helper calls have been made during authoring.

## Statistical limits and Phase 1 corrections

Eight paired clusters at two-sided alpha .05 have approximately 63.7% power at
standardized paired effect d=.95 under a noncentral-t model. Approximately d=1.156
is needed for 80% power under those assumptions. Three seeds reduce observation noise
but do not turn eight independent worlds into 48. These sensitivity calculations do
not establish bootstrap power or population representativeness. Report the fixed,
curated panel honestly even if no effect appears.

PR #189 used six suppliers and nine actions, not four and ten. Its recovery completed
36 replayed observations and reported a regret difference of -$5.02 (95% world-bootstrap
interval [-$9.77, -$0.86]). It did not isolate `check_award` in an ablation, so it cannot
prove that this tool alone eliminated panic.

`classify_world_continuous` is retained as a diagnostic. It asks whether a policy's
within-world noise spread and separation meet its thresholds, which differs from the
requested greedy-to-optimal gap. A `degenerate` diagnostic is reported as such; it is
not rewritten as `admit`. The explicit Phase 2 admission rule above uses actual
public-policy economic separation and trap infeasibility. Near-optimal deterministic
reference performance is not evidence of model performance.

## Review and reproduction

- `phase2_environment.py`: trap admission, certified floors, observation boundary,
  disabled checker, separately identified scorer and corrected feasible-award metric.
- `phase2_worlds.py`, `phase2_policies.py`, `phase2_campaign.py`: reproducible worlds,
  public-only reference, admission diagnostics, power sensitivity and clustered analysis.
- `phase2_runner.py`, `phase2_admission.py`, `phase2_budget.py`, `phase2_execution.py`:
  qualified registration, strict schemas, shared receipts, budget ledger and gates.
- `tests/test_procurement_phase2*.py`: negative controls, oracle constraints, stopping
  counterfactual, catalogue invariance, receipt replay, spending failures and full
  64-episode provider-fixture orchestration.

Run focused validation with `PYTHONPATH=src python -m pytest tests/test_procurement_phase2*.py -q`.
After actual digest-bound approval, execute once with an in-memory `OPENROUTER_API_KEY`:
`PYTHONPATH=src python -m aeread_families.procurement_allocation.phase2_execution --admission-root <review-directory> --run-root runs/procurement_allocation/procurement_phase2_economic_epistemics_v1`.
Raw run directories stay ignored. Publication must identify live versus fixture records,
retain source/case/plan digests and replay coverage, and reconcile both settled and
reserved provider costs before claiming completion.
