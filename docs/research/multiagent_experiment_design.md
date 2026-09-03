# Multi-agent model interaction experiments

**Status:** design contract. The shared runner can represent controlled,
cross-play, and self-play blocks, and Housing V1 can execute a live model in the
landlord role. A qualified opponent panel and multi-agent leaderboard are not
yet implemented.

This protocol measures how an agent or population of agents performs when the
other adaptive participants change. It is distinct from an
[open-harness comparison](../operations/open_harness_testing.md): the harness is fixed as an
experimental control rather than varied as the treatment.

Every live model still executes through a declared harness. “Without a harness
experiment” therefore means **without harness identity as an experimental
factor**, not execution without a harness or evidence boundary.

Use the shared [experiment campaign SOP](../operations/experiment_campaign_sop.md) for ordered
promotion and fact-table publication. This document defines the multi-agent
treatment, opponent, and attribution choices within that common sequence.

## 1. Questions this design can answer

The experiment must declare one bounded construct before any live call:

1. **Focal-agent robustness:** how well does one subject agent perform against a
   predeclared distribution of opponent policies?
2. **Population-policy performance:** what outcomes arise when every seat of one
   role uses the same policy?
3. **Opponent sensitivity:** how much does a fixed subject's behavior and outcome
   change when only the opponent profile changes?
4. **Joint-system behavior:** what outcomes emerge in cross-play or same-model
   self-play?

These are different estimands. A self-play score is not an intrinsic score for
one model, and a homogeneous population result is not a single-agent effect.

## 2. Experimental blocks

| Block | Subject assignment | Other adaptive seats | Valid interpretation | Primary display |
|---|---|---|---|---|
| Controlled focal-agent | One subject rotated through eligible seats | Fixed scripted or version-pinned profiles | Subject performance against a declared opponent condition | Paired subject leaderboard |
| Controlled population | One subject profile fills every seat of a role | Fixed profiles in the other roles | Performance of a homogeneous policy population | Population-policy table |
| Cross-play | Every predeclared ordered subject-opponent pairing | Version-pinned model profiles | Interaction and robustness across the opponent panel | Subject-by-opponent matrix |
| Self-play | Same base model fills all adaptive roles, with role-specific prompts | None | Joint behavior of that role-conditioned system | Separate self-play table |

Use the shared runner's existing `EvaluationBlock.kind` values: `controlled`,
`cross_play`, and `self_play`. Policy-prompt sensitivity should be represented as
separate versioned controlled or cross-play profiles, not as an unrecorded prompt
edit.

### Focal versus population attribution in Housing

Housing has several tenant seats. Filling every tenant seat with one model tests
a **tenant population policy**: the tenants affect one another through
competition, so the result cannot be attributed to an isolated tenant.

For a focal-agent claim, place the subject in one tenant seat, fill the remaining
tenant seats with a fixed background policy, and rotate the subject through all
eligible tenant positions. Pair every rotation on the same world and opponent
condition. Report the focal tenant's match and payoff alongside the externality
on total tenant payoff and social welfare.

## 3. What is frozen

For every named opponent profile, freeze and seal:

- requested model and provider-resolved model revision;
- provider route, quantization, endpoint policy, and pricing catalog;
- harness identity and version;
- role prompt, output schemas, tools, memory, and reasoning condition;
- temperature, top-p, token and action budgets, timeouts, and cost limits;
- retry ownership, retryable conditions, attempt limit, and backoff policy;
- world, subject-inference, opponent-inference, and seat-rotation seed derivation;
- family, case generator, phase schedule, visibility policy, and scoring code.

“Frozen opponent” means that this **policy and inference contract** is fixed. It
does not mean that a live opponent emits a pre-recorded response. The opponent
must remain responsive to the history it actually observes.

Temperature zero and a provider seed do not guarantee byte-identical live model
outputs. Byte-identical reproducibility applies to offline replay from sealed
provider responses. A fresh live rerun is a stochastic replicate and may differ.
Never replay one opponent response across histories produced by different
subjects or treatments; that would remove the adaptability this experiment is
intended to measure.

## 4. Declared treatment and controls

Vary one primary factor per experiment:

- opponent model identity;
- opponent policy prompt, such as cooperative, strict-reservation, or strategic;
- opponent population composition;
- subject model identity; or
- focal versus population seat assignment.

Hold the harness constant across all live profiles whenever the models support a
common interface. AERead `minimal_chat/1.0` with strict phase-specific JSON is the
default common-denominator condition for the first Housing experiment. If one
model requires a different serialization, tool loop, retry path, or provider
feature, label that cell as a different joint model-plus-interface condition; do
not attribute its difference solely to the model.

Model-specific provider routes may be unavoidable in a cross-model panel. Pin
and report each route. Quality contrasts then concern the complete resolved
model profile; latency and cost remain diagnostics rather than controlled model
effects.

## 5. Opponent panel

Predeclare the panel before inspecting subject scores. The first Housing panel
should contain:

1. **Scripted anchor:** the deterministic Housing landlord policy, which checks
   mechanism behavior and supplies a low-variance control.
2. **Same-model control:** the subject model in the landlord role behind the
   fixed native harness.
3. **Cross-model opponents:** at least two version-pinned models from different
   model families, admitted through the same phase schemas and common harness.
4. **Policy variants:** at least cooperative, strict-reservation, and strategic
   role prompts for one fixed opponent model.

Scripted and live-model opponents are separate conditions, not pooled as if they
were exchangeable samples. Opponent profiles used during development remain a
public development panel. Reserve unseen model-policy combinations or hidden
policy parameters for a confirmatory holdout.

Do not select the final opponent panel because it makes one subject look better,
creates a desired ranking, or happens to complete after other profiles fail.

## 6. Housing V1 starting experiment

Use the full pinned Housing setting after qualification: six tenants, four
listings, four rounds, private tenant values, private landlord reservation costs,
and the exact assignment upper bound. The current one-world, two-tenant,
one-listing model-landlord run is an operational slice, not evidence for a model
ranking.

Run two campaigns:

### A. Focal tenant robustness

- one live tenant subject;
- five fixed background tenant policies;
- one opponent profile fills all four landlord seats;
- rotate the subject through all six tenant seats;
- repeat the complete rotation for every opponent profile on the same worlds.

This campaign supports a subject-oriented claim because the background tenants
and landlord condition are controlled.

### B. Population cross-play

- one subject profile fills all six tenant seats;
- one opponent profile fills all four landlord seats;
- run every predeclared subject-by-opponent pairing;
- include same-model role-conditioned self-play as a labeled diagonal condition.

This campaign measures joint population behavior. It must not be merged into the
focal-agent leaderboard.

## 7. Sampling and execution order

The independently sampled unit is the Housing world. Opponent conditions, seat
rotations, and live-inference replicates inside one world are correlated
observations.

- Pair conditions on case version, world seed, replicate index, and focal-seat
  rotation.
- Derive role-specific request seeds from the paired cell rather than from the
  model or opponent condition. The same numeric seed does not imply identical
  output across models.
- Rotate condition execution order by world so no profile always receives a warm
  cache, earlier quota window, or lower provider load.
- Average stochastic replicates within the world before treating worlds as
  independent evidence.
- Preserve every planned operational failure as typed missingness. Never rerun
  only the losing condition or score a provider failure as zero economic value.

Use one complete trajectory per profile as the operational gate. Then run a
predeclared variance pilot. Choose the confirmatory world count from the paired
world-level variance and a declared minimum meaningful effect; do not infer a
winner from the gate or choose the sample size after inspecting the ranking.

## 8. Metrics and reporting

Housing's primary family outcome remains social welfare, with
`within_case_score = social_welfare / exact_assignment_upper_bound` when the
upper bound is positive.

Report these components separately:

- within-case score and social welfare;
- focal, total-tenant, and total-landlord payoff as applicable;
- match/lease rate, signed rent, round of agreement, wasted contacts, and passes;
- individual-rationality violations and invalid actions;
- subject and opponent calls, retries, tokens, cost, and wall time;
- route verification, cost completeness, malformed output, timeout, and other
  operational failures.

For cross-play, show the complete subject-by-opponent matrix plus each subject's
predeclared opponent-weighted mean, worst-profile result, and between-opponent
variation. Do not publish a single overall rank unless the opponent distribution
and weights were fixed before execution. Do not call the worst-profile gap
“exploitability” unless a valid best-response procedure exists.

Use paired world-level differences and cluster bootstrap intervals. Average
replicates within worlds, report complete-pair counts, and include sensitivity to
operational missingness. Self-play and scripted-anchor results remain separate
tables.

## 9. Evidence and replay

Every cell must retain or reference:

- the resolved `RunPlan`, `EvaluationBlock`, `AgentProfile`, and seat assignment;
- world, inference, replicate, and rotation seeds;
- raw provider responses in local evidence, parsed actions, legality verdicts,
  transitions, outcome, score, and receipt digest;
- subject-versus-opponent call, token, cost, and retry accounting; and
- a typed reason for every exclusion or operational failure.

Offline replay must reconstruct the same actions, state, outcome, and score with
zero provider calls. Replay establishes what happened; it does not claim that a
new live call would return the same text.

## 10. Admission and stopping gates

1. Provider-free scripted execution, scoring, and replay pass.
2. Every live profile completes three phase-schema probes with no hidden retry.
3. Every profile completes one full trajectory with a verified route and complete
   billing evidence.
4. The variance pilot completes the full paired opponent panel.
5. The confirmatory panel and analysis plan are hashed before paid execution.

Stop and keep the affected cells visible but unranked if a route drifts, billing
is incomplete, a profile changes harness behavior, or one condition has
selectively missing worlds.

## 11. Current runner mapping and implementation gap

The existing shared schemas already provide the main vocabulary:

- `AgentProfile` pins model, harness, prompt, runtime, tools/memory, reasoning,
  sampling, budgets, and retries;
- `EvaluationBlock` declares `controlled`, `cross_play`, or `self_play` and names
  subject and controlled seats;
- `RunSpec.seat_assignments` binds profiles to concrete seats; and
- `SamplingPlan` plus `AnalysisPlan` declare pairing, clusters, missingness, and
  uncertainty.

The current Housing bakeoff is still harness-oriented: it fixes one GLM tenant
model, optionally enables one fixed GLM landlord profile, and varies the tenant
harness. A multi-agent campaign runner must instead fix one harness and generate
one resolved run plan per subject-opponent-seat assignment. Those plans should be
aggregated into a digest-bound campaign artifact and a matrix-aware report.

Before the first paid cross-model panel, add contract tests that prove:

- only the declared model/opponent/seat factor varies between paired plans;
- subject and opponent provider calls route to their assigned profiles;
- focal-seat rotations preserve the same world and controlled background seats;
- fresh responses remain trajectory-dependent while sealed replay is exact;
- role-level calls, tokens, cost, and retries reconcile with totals; and
- incomplete opponent panels remain visible and cannot enter a rank.
