# Procurement v3 mechanism study: protocol 0.2

Status (2026-10-27): the engineering gates listed at the end of draft 0.1 are complete (runner tests, isolation preflight, loss replay, cost manifest; see ENGINEERING_RESULTS.md). The P0 work below amends 0.1; where they conflict, 0.2 and the frozen `p0/*/protocol.json` files govern. This document does not supersede historical Procurement campaigns or modify v3.

## Amendments in 0.2 (P0)

1. **Assistance is bounded against the unrestricted optimum (PM-D-01).** `p0/assistance_gap.py` computes, at the checkpoint, the buy-now value B, the unrestricted optimum V and the best restricted-format policy over every newcomer sample S. P and PV now supply the best candidate over all samples, not the cheapest sample. The primary panel admits a world only if V-B >= $5, S-B >= $5 and V-S <= $5. Unscreened worlds are reported separately with their gap. In 300 fresh structures the median gap among worlds with material investigation value was $19.4 and only 20 of 206 were within $5.
2. **The primary claim is the stage ladder, not dependence (PM-D-02).** Shared sources change investigation value in 7 of 300 structures, so the dependence-by-assistance interaction cannot be powered with this generator. The primary claim locates lost value at deliberation (D to E), policy construction (E to P), valuation (P to PV) and action selection (residual PV loss). Dependence twins are dropped. Dependence is secondary.
3. **Development variance pilot, executed** (`p0/pilot/`, protocol `5ebdda6b…`): Opus 5.5, 12 gap-bounded and 12 unscreened worlds, 4 arms, 2 private draws; 192/192 completed, $32.82. Sol 6.1 was not run because the Codex CLI hit its usage limit (PM-O-01).
4. **Sizing.** The planned $5 minimum effect would need 2,000–12,000 worlds at the pilot's world-level SDs (largest SD $170, driven by a single $981 commitment). The confirmatory minimum effect is $25, with two primary hypotheses: H1, elicitation minus direct is non-zero; H2, supplied policy minus elicitation is equivalent within ±$25. Holm is applied over both. Resampling the pilot's single-draw contrasts gives 81% power for H1 at 100 worlds and over 99% for H2. Valuation (PV−P) is secondary.
5. **Held-out confirmation** (`p0/confirm/`, protocol `f35aece8…`): 100 gap-bounded worlds screened from seed 11,000,000 (2,539 scanned), disjoint from every development range; one private draw per world; four arms; 400 episodes; $100 cap; no retries.

The text below is draft 0.1, retained for its definitions.

## Question and scope

When agents leave value unrealized, is the observable deficit in constructing an adaptive information policy, valuing that policy, or selecting and executing actions consistent with its value? The current contingent probe motivates policy construction as the leading hypothesis, not an established cognitive mechanism. Accurate prompted posterior answers do not establish spontaneous use of dependence.

Use the pinned pay_or_test_v3 source in ../source_evidence.zip. Preserve the information-constrained reference, fees, time, action budget, and award accounting. No v4 and no broad model ranking. Initially use the same Opus route and effort as the exploratory probes, with runtime metadata recorded; aliases are not immutable weight revisions.

## Two linked panels

1. **Mechanism panel (primary):** reset every condition to the same public checkpoint after the familiar supplier's quote and sample. Sunk costs and elapsed time remain in the environment. Observe an initial diagnostic/action and then continue the full episode. This identifies effects conditional on that checkpoint, not effects on initial supplier discovery.
2. **Natural-start panel (secondary):** ordinary baseline episodes from the original initial state. Decompose loss at first inquiry, subsequent investigation, and commitment. Do not pool with checkpoint results. Match public structures across panels but retain separate estimands.

An optional forced-sample panel is a later diagnostic: execute the fixed candidate sample and let the model continue, averaging over the correct outcome law, not only favorable results. Keep forced fees in payoff and distinguish the forced action's loss from subsequent agent loss. Do not silently add this panel to primary tests.

## Matched economic conditions and sampling

For each public structure construct correlated (original rho) and independent (rho=0) versions. Preserve listings, marginal type rates, prices, fees, lead times, deadlines, budgets and response process. Regenerate private types/factory identities under each law. Identical hidden outcomes across dependence conditions are neither required nor generally correct. Across assistance arms within a condition reuse the same private outcome/response-seed draw. Block and randomize execution order within public structure.

Maintain two separately reported sampling frames:

- A contiguous, unscreened generator-seed sample: conclusions apply to this generator distribution, not real procurement prevalence.
- A diagnostic challenge sample: screen using reference values before inference, retaining all acceptance/rejection counts. Challenge selection does not produce representative estimates.

At the checkpoint define B = best immediate award/defer value; V = unrestricted reference value; U = maximum exact restricted value allowing only one newcomer. Strata: no profitable investigation if V-B <= numerical tolerance; one-newcomer profitable if U-B > tolerance; multistage-only if V-B > tolerance and U-B <= tolerance. Separately report materiality (proposed $5) and multistage gap V-U. A profitable one-newcomer world may still have substantial multistage value. Classify each dependence condition separately; preserve both counterparts even if their strata differ.

Validation seeds 10,600,000–10,600,007 and historical regression seeds 10,500,014/27 are development-only. Reserve disjoint confirmatory seeds after the pilot. Validate stratum coverage before deciding quotas; never describe an empty stratum as tested.

## Assistance conditions

D: direct action, ordinary public observation and original action interface.

E: elicit a complete contingent policy and its expected values, then request the action. No reference policy or values supplied.

P: supply a concrete feasible policy and buy-now alternative without numerical reference values; elicit their valuation, then request the action.

PV: supply the identical policy and alternatives with exact expected values under the stated policy execution contract; elicit a compact interpretation, then request the action.

All E/P/PV use the same candidate sample, contract, structured fields, maximum deliberation budget, and action handoff. Choose the candidate deterministically by public sample fee, price, then supplier ID; it is a candidate, not a recommendation. In P/PV supply the best policy in the existing restricted format for that candidate, but do not call it optimal or recommend it. Allow the agent to reject it or use any legal action. Present the alternatives in randomized, paired order and disclose neutral provenance as an externally computed candidate in both P and PV.

The existing format specifies pass/fail branches, one subsequent supplier, quote/sample order, retry cap, purchase quantities, fallback and feasibility guards. Its best policy may be unprofitable or substantially inferior to unrestricted planning. Retain those cases in the unscreened panel and report the format gap; only a separately labeled diagnostic subset may require a small gap. Do not assert that supplying this policy necessarily removes the planning bottleneck.

D differs in deliberation and task framing; D–E is a bundled elicitation effect. P–E measures the effect of supplying a computed policy, including its salience and computational assistance. PV–P measures adding reference values, including authority/salience effects. None uniquely identifies internal cognition. Equal token ceilings do not imply equal computation; record actual usage. A matched neutral deliberation control is a pilot sensitivity check, not an unannounced extra primary contrast.

After the first action, all checkpoint arms use identical continuation instructions and the original legal-action interface, retain their respective initial assistance in context, and receive no new oracle assistance. This measures persistence of one checkpoint intervention, not continual oracle coaching. Store plans before actions. Never substitute a reference continuation for a model episode.

## Primary estimands and analysis

Primary endpoint: mean cumulative action-level Bellman loss over each completed checkpoint continuation. For action a at public belief state s, d=V*(s)-Q*(s,a). Record raw precision and numerical tolerance. Sum conditional losses along the observed history; this is not a pathwise identity with optimal expected value minus one realized payoff. Its expectation has the policy-regret interpretation under correct transitions. Report realized net contribution margin separately.

Two primary assistance contrasts in the unscreened panel, averaged equally over the paired dependence conditions: P minus E and PV minus P in dollar loss (negative favors assistance). Report effect estimates and 95% world-clustered intervals, with Holm adjustment for the two primary tests. Dependence-by-assistance interactions, diagnostic strata, D–E, and the natural-start panel are secondary. A mechanism claim specifically about dependence requires the interaction evidence; a main assistance effect alone is insufficient.

Independent sampling unit: public structure seed. Repeats, dependence twins, assistance arms, and hidden draws are nested observations. Compute within-world contrasts before aggregation and resample whole worlds keeping pairs together. Report challenge and unscreened panels separately. If worlds are sampled within strata, report stratum estimates; use population weights only when their sampling probabilities are known. No pseudo-replication by counting tool calls as independent subjects.

## Diagnostic breakdown

- Inference: prompted prior/posterior error in a separate diagnostic so it does not contaminate direct episodes.
- Planning: best restricted policy value minus exact value of the described policy, plus restricted-to-unrestricted gap after the same candidate action.
- Valuation: signed and absolute error in plan advantage over buying now; absolute payoff-level errors separately.
- Aggregation: total estimate minus sample-fee-adjusted weighted sum of the model's own branch estimates.
- Choice: action inconsistent with the model's stated ranking, using a predeclared materiality threshold; report uncertainty notes, not inferred thoughts.
- Continuation: subsequent losses, deviations from stated plans, and action stage. Branch evaluations are hypothetical unless the policy is actually followed.
- Reliability: malformed plans, illegal actions, timeout/provider errors, budget exhaustion and episode completion, by condition.

No composite score across these stages. The same episode can exhibit several deficits; categories are not mutually exclusive.

## Missingness, budgets and stopping

Retain every scheduled cell and all raw calls. No selective retries, replacements or imputation with oracle behavior. Illegal actions follow the original environment's terminal semantics. Provider failures remain missing economic outcomes; report coverage and reason-specific counts. Show complete-pair estimates with sensitivity bounds using verifier-derived attainable payoff bounds before making claims if missingness differs by arm. An interrupted run is incomplete, not a completed experiment.

Freeze per-call, per-episode and total cost/time ceilings before any pilot or confirmatory calls. Halt at a cap or a systemic harness failure; preserve partial results. No efficacy-driven early stopping. Confirmatory analysis begins only after the fixed scheduled run ends or is explicitly reported incomplete.

## Pilot and sample size

First validate matched cases and prompt information boundaries without providers. Then implement and test the full-episode arm runner and loss aggregation using scripted policies. Only after these pass freeze a development pilot: proposed 12 distinct structures spanning feasible strata, two hidden draws/model repeats, both dependence conditions and four arms (192 checkpoint episodes). This is a planning target, not an executed or approved-cost manifest; a smaller engineering smoke run must precede it. Estimate cost from actual episode call counts, not the earlier one-action probes.

Use pilot world-level paired contrast SDs to plan sample size for a proposed minimum meaningful $5 loss reduction and 80% power, controlling the two primary comparisons. Start with a conservative normal approximation N ≈ ((z_(1-alpha/4)+z_0.8)*SD/5)^2, then verify using simulation of the paired clustered design and a small-sample sensitivity range. Assess precision of interaction/stratum estimates separately; increase world coverage or label those analyses underpowered. Do not use two curated worlds to estimate confirmatory power or choose N from whether a pilot p-value is favorable. Fix budget and N before confirmation and use new seeds.

## Release gates and artifacts

Completed in this design step: provider-free case-pair validation, hidden-draw invariance, exact supplied-policy valuation cross-checks, and a review notebook. Inspect validation.json for actual status and coverage.

Remaining before live pilot: executable prompt payloads/schema boundary checks, scripted full-trajectory runner tests (including invalid/timeout/terminal paths), independent spot-check of loss aggregation, model isolation preflight, cost manifest, and frozen pilot identity. These are concrete engineering gates, not claims of completed validation.

Remaining before confirmation: pilot variance/cost results, powered N and precision targets, disjoint world manifests, exact prompts and budget, scorer/runtime hashes, randomized schedule and dated preregistration if desired.

Final results notebook: protocol/flow and exclusions; primary paired effects and uncertainty; economic strata and dependence interactions; per-stage loss decomposition; explicit-policy errors; representative and counterexample traces; operational reliability/cost; exact artifact hashes. Clearly separate current exploratory findings, pilot estimates and confirmatory results.
