# Representative trajectory analysis

**Reviewer:** Yuchen Fang  
**Delivery target:** 2026-09-05–06  
**Scope:** Published AERead trajectories on GitHub `main`, plus Housing V12–V15 evidence in open stacked PRs [#61](https://github.com/aeread-org/AERead/pull/61) and [#68](https://github.com/aeread-org/AERead/pull/68)
**Status:** Review artifact

## Bottom line

The repository's `main` branch publishes 74 sanitized trajectory records: 52 completed and 22 typed operational failures. The open V12–V15 stack adds 52 attempted records—4 V13 completions and 48 V15 attempts, of which 43 completed and 5 are typed operational failures. This review therefore covers a 126-record public evidence surface while keeping merged and open-PR evidence explicitly separate.

The most important conclusion is methodological:

> The public trajectories reveal decisions/actions in aggregate, execution status, and terminal outcomes. They do not include ordered seat observations, task-visible belief records, raw responses, or hidden reasoning. Moreover, the Housing campaigns all use a declared low-reasoning condition rather than a paired reasoning intervention. Therefore the public evidence can locate **reasoning-sensitive links** in the chain, but it cannot show that changing reasoning caused a behavioral change.

Claims below are consequently labeled as **observed**, **candidate interpretation**, or **undetermined**. No belief is presented as fact merely because it is compatible with an action.

## Evidence census

| Publication | Completed | Operational failure | Use in this review |
|---|---:|---:|---|
| Housing population cross-play V0 | 2 | 1 | Selected upper/lower outcomes and empty-provider failure |
| Housing model sensitivity V7 | 7 | 0 | Completed comparison trajectories |
| Housing model sensitivity V8 | 11 | 1 | Full one-world matrix and timeout failure |
| Housing Morph V10 | 31 | 17 | Multi-world extrema, retries, and failure classes |
| Housing V12 pacing gate (open PR) | 0 | 0 | Admission blocked execution; pacing and timeout diagnosis |
| Housing V13 cooldown gate (open PR) | 4 | 0 | Successful one-world route promotion gate |
| Housing V14 variance pilot (open PR) | 0 | 0 | Admission blocked execution despite cooldown |
| Housing V15 variance pilot (open PR) | 43 | 5 | Multi-world extrema, visible retries, and residual GLM-route failures |
| Commercial-state variance V1 | 1 | 3 | Non-Housing requirement-tracking case and early infrastructure failures |
| Housing V9 and V11 | 0 | 0 | Admission blocked execution; no trajectories to interpret |

Primary files:

- [Housing population selected trajectories](https://github.com/aeread-org/AERead/blob/main/evidence/housing_population_crossplay_v0/trajectories/selected_2026-09-02.json)
- [Housing V7 selected trajectories](https://github.com/aeread-org/AERead/blob/main/evidence/housing_model_sensitivity_openrouter_alt_v7/trajectories/selected.json)
- [Housing V8 attempted trajectories](https://github.com/aeread-org/AERead/blob/main/evidence/housing_model_sensitivity_openrouter_alt_v8/trajectories/attempted.json)
- [Housing Morph V10 attempted trajectories](https://github.com/aeread-org/AERead/blob/main/evidence/housing_model_sensitivity_openrouter_morph_v10/trajectories/attempted.json)
- [Housing V12 PR](https://github.com/aeread-org/AERead/pull/61)
- [Housing V13 attempted trajectories](https://github.com/aeread-org/AERead/blob/codex/housing-v13-cooldown-full-trajectory/evidence/housing_model_sensitivity_openrouter_friendli_v13/trajectories/attempted.json)
- [Housing V14 attempted trajectories](https://github.com/aeread-org/AERead/blob/codex/housing-v13-cooldown-full-trajectory/evidence/housing_model_sensitivity_openrouter_friendli_v14/trajectories/attempted.json)
- [Housing V15 attempted trajectories](https://github.com/aeread-org/AERead/blob/codex/housing-v13-cooldown-full-trajectory/evidence/housing_model_sensitivity_openrouter_friendli_v15/trajectories/attempted.json)
- [Commercial-state sanitized trajectories](https://github.com/aeread-org/AERead/blob/main/evidence/commercial_state_openweight_variance_v1/trajectories/sanitized.jsonl)

## Why these examples are designed and selected

The purpose of a representative trajectory set is not to collect memorable success and failure stories. It is to distinguish **where** an agent pipeline succeeds or breaks and to test whether the benchmark's interpretation remains valid under different cases, counterparts, and operational conditions. A terminal score alone cannot make those distinctions.

The selected examples serve seven complementary purposes:

| Design purpose | Question being tested | Representative examples | What the comparison prevents |
|---|---|---|---|
| Basic competence | Can the agents complete the native protocol and reach a valid outcome? | Population upper case; V10 near-oracle case; V13 4/4 gate | Treating inability to use the interface as an economic or strategic result |
| Information use and adaptation | Does behavior change productively after a new board, inbox, offer, or hold? | Population upper/lower contrast; V8 multi-round low case | Inferring adaptation from a terminal allocation without examining the path |
| Objective and constraint tracking | Do agents pursue welfare/payoff while preserving legality, privacy, feasibility, and individual rationality? | V10 lowest case with an IR violation; commercial-state partial-completeness case | Letting a plausible final answer hide a violated constraint or omitted requirement |
| Commitment and execution | Do offers and intermediate agreements become valid final commitments? | V10 high/low extrema; population malformed-response/commit contrast | Conflating a good intention or proposal with successful execution |
| Behavioral versus operational failure | Is a bad result caused by the agent's policy or by rate limits, empty output, timeout, or transport? | Population empty-response case; V8 timeout; V10 failures; V12/V14 gate blocks; V15 typed failures | Scoring infrastructure failure as poor reasoning or zero utility |
| Counterpart sensitivity | Does the same tested policy behave differently against scripted, self-play, or cross-play counterparts? | Housing self-play and cross-play cells | Claiming an intrinsic model capability from performance against one favorable opponent |
| Generalization and path dependence | Does the result persist across worlds, and can different paths lead to the same endpoint? | V7/V8 terminal-equivalent pair; four-world V10 and V15 pilots | Treating one world as general evidence or terminal equivalence as process equivalence |

These examples should therefore be read as a **diagnostic panel**, not as independent anecdotes or a leaderboard. Together they provide positive controls, valid-but-poor outcomes, process contrasts, and typed operational failures. No single trajectory can establish all of these properties.

For Refund, the same design logic would require simple competence cases, missing-information cases, policy-boundary and adversarial cases, proposal/confirmation/exactly-once transaction cases, scripted-customer controls, LLM-customer cross-play, and multiple generated worlds. Each verifier leaf should remain separate so utility cannot compensate for an incorrect policy decision, missing confirmation, duplicate execution, privacy violation, or collateral state change.

## Chain used for review

1. **Observation:** information made visible to the acting seat.
2. **Belief:** the seat's representation or prediction of state and counterpart behavior.
3. **Decision:** selected objective, target, price, response, commitment, or claim.
4. **Action:** emitted and parsed schema object.
5. **Execution:** legality check, retry/tool result, state transition, or commitment.
6. **Outcome:** terminal allocation/state, welfare or task score, validity, cost, and reliability.

In the current public projections, observation and belief are normally absent; decision and action are aggregated; execution and outcome are best preserved. That asymmetry determines how strongly each trajectory can be interpreted.

## Representative reviews

### A. Housing population: upper completed cross-play

`episode_attempt_d7593a79be37fcbebf6c`, DeepSeek tenants versus GLM landlords:

- **Observed:** two `contact → respond → commit` cycles; 29 logical actions; 11 offers, 4 accepts, 2 reject-all responses, 4 signs, 7 passes, and 1 malformed response.
- **Execution:** four signs produced four assignments; replay passed; no individual-rationality violation.
- **Outcome:** welfare `816.63`, equal to the comparison baseline; oracle `1059.10`; score `0.7711`; 7 wasted contacts.
- **Reasoning-sensitive point:** target selection after the first board update and sign/walk choice after holds. These are where beliefs about congestion, availability, and payoff could affect behavior.
- **Verdict:** successful but non-optimal allocation is observed. Whether adaptation or merely compatible independent choices produced it is **undetermined** without ordered observations/actions.

### B. Housing population: lower completed cross-play

`episode_attempt_62dbf844bf462de83d9b`, GLM tenants versus DeepSeek landlords:

- **Observed:** four cycles and 46 actions, including 17 passes, 4 malformed commits, and 5 malformed responses.
- **Execution:** only three signs/assignments; replay passed; no individual-rationality violation.
- **Outcome:** welfare `255.56`; score `0.2413`; 9 wasted contacts.
- **Contrast with A:** +17 actions, +10 passes, +8 malformed outputs, one fewer assignment, and `561.07` less welfare.
- **Reasoning-sensitive point:** the degradation is visible between decision and execution—many opportunities did not become valid, productive commitments. The trace could reflect weak strategic modeling, failure to track action constraints, schema execution difficulty, or all three.
- **Verdict:** poorer decision/action/execution behavior is observed; the underlying belief error is **undetermined**.

### C. Housing population: empty provider response

`episode_attempt_d55d01488206a77c4ff8`:

- **Observed:** three offers were produced, then a fourth provider call returned empty content during the first contact phase.
- **Execution:** receipt status became `invalid_measurement`; no score or welfare was assigned.
- **Chain break:** observation may have been delivered, but no usable action crossed the model/provider boundary.
- **Verdict:** this is operational missingness, not evidence of refusal, poor strategy, or low welfare. The benchmark correctly prevents infrastructure failure from masquerading as reasoning failure.

### D. Housing V7 and V8: same outcome, different action path

The moderate DeepSeek-versus-GLM cross-play cell appears in both campaigns:

- **V7 observed path:** 23 actions—8 offers, 4 accepts, 1 reject-all, 4 signs, and 6 passes; 4 wasted contacts.
- **V8 observed path:** 23 actions—9 offers, 4 accepts, 1 reject-all, 4 signs, and 5 passes; 5 wasted contacts.
- **Shared execution/outcome:** the same four assignments, welfare `1989.59`, oracle `2004.29`, and score `0.9927`.
- **Reasoning-sensitive point:** one additional offer and one fewer pass changed the path but not the terminal allocation.
- **Verdict:** terminal equivalence does not imply trajectory equivalence. An outcome-only verifier would miss different interaction costs and choices. This pair does **not** identify a reasoning effect because campaign execution is not a randomized reasoning-condition contrast.

### E. Housing V8: low completed trajectory

`episode_attempt_8ca23827fb61cff17a34`, severe GLM self-play:

- **Observed:** two cycles; 24 actions; 10 offers, 3 accepts, 1 reject-all, 3 signs, and 7 passes.
- **Execution:** three assignments; no IR violation; 7 wasted contacts.
- **Outcome:** welfare `784.97`, below baseline `1029.74`; oracle `1175.77`; score `0.6676`.
- **Reasoning-sensitive point:** repeated offers/passes and failure to reach the baseline allocation make target selection and response/commit timing the primary review points.
- **Verdict:** valid but poor economic behavior. The projection cannot determine whether congestion beliefs, objective selection, or counterpart interaction caused the loss.

### F. Housing V8: mid-trajectory timeout

`episode_attempt_96d1dd074e35e9a75eae`, mild GLM self-play:

- **Observed before failure:** one full cycle; 6 offers, 1 accept, 1 counter, 2 reject-all responses, and 1 sign.
- **Execution:** the episode timed out after `160.64` seconds; no terminal score was fabricated.
- **Chain break:** partial valid decisions/actions exist, but execution never reaches a complete outcome.
- **Verdict:** do not compare the partial allocation with completed cells. Timeout belongs to reliability/coverage, not economic quality.

### G. Housing V10: near-oracle completion

`episode_attempt_058893b1b915597d36f2`, severe DeepSeek self-play, world `1460378342`:

- **Observed:** one cycle; 6 offers, 3 accepts, 3 signs, and 3 passes; no retry.
- **Execution:** all three available assignments were completed immediately; no IR violation; 3 wasted contacts.
- **Outcome:** welfare `1767.11` against oracle `1769.31`; score `0.9988`, above baseline `1395.41`.
- **Reasoning-sensitive point:** the first target/price choices and landlord selections are the likely efficiency-producing decisions because no later adaptation was needed.
- **Verdict:** near-optimal coordination is observed, but the projection cannot establish whether explicit strategic beliefs caused it.

### H. Housing V10: lowest completed trajectory

`episode_attempt_4290c28eb5699e64ed12`, moderate GLM self-play, world `123194022`:

- **Observed:** two cycles; 11 offers, 7 counters, 9 walks, and only 2 signs.
- **Execution:** two assignments and one IR violation; 9 wasted contacts.
- **Outcome:** welfare `48.28` against baseline `1049.32` and oracle `1188.05`; score `0.0406`.
- **Reasoning-sensitive point:** landlord counter prices and tenant walk/sign decisions are the clearest inflection. Many offers progressed to counters but almost none became welfare-preserving commitments.
- **Verdict:** this is the strongest public candidate for event-level belief analysis. Possible mechanisms include overly aggressive landlord pricing, tenant rejection of viable holds, poor target selection, or constraint/objective confusion. Their relative roles remain **undetermined** without seat-level events.

### I. Housing V10: equal retry burden, different outcomes

Two completed cells each required seven effective retries:

- **High outcome:** `episode_attempt_9ab740afff5186f2f547`, DeepSeek versus GLM—3 assignments, score `0.9563`, 6 wasted contacts.
- **Low outcome:** `episode_attempt_e2a7b3e2aed4431341bc`, GLM self-play—2 assignments, score `0.3452`, 9 wasted contacts.
- **Reasoning-sensitive point:** both endured the same retry count, yet their commitment patterns and outcomes differ sharply.
- **Verdict:** retry volume is not a measure of reasoning quality. It is a reliability/execution covariate. These cells also differ in condition and therefore cannot isolate model reasoning.

### J. Housing V10: failure classes

V10 records 11 rate limits, 5 timeouts, and 1 transport failure:

- **Early rate limit:** may prevent the first usable action; the chain stops at provider execution.
- **Late timeout:** can occur after several valid phases; partial behavior exists but terminal outcome is missing.
- **Transport failure:** similarly blocks completion independently of economic decision quality.
- **Verdict:** failure location matters. All three must remain typed operational missingness, while reports separately show how much of a trajectory occurred before failure.

### K. Commercial-state: partially complete requirement tracking

The Mistral `payment-release-reconcile` trajectory is the only completed commercial-state record:

- **Decision/action:** it correctly reported combined total `476000` and remaining balance `224800`; asserted both required claims; cited all four evidence IDs; attempted no unauthorized external action.
- **Execution/outcome:** hard gate passed; amount accuracy and evidence coverage were `1.0`; state accuracy was `0.667`; required-action recall was `0.5`; total score `0.8333`.
- **Reasoning-sensitive point:** the missing state/action component lies between evidence integration and complete action selection. The model reached a broadly correct belief/decision but omitted one required operational consequence.
- **Verdict:** this is compatible with incomplete constraint tracking or action planning, but the actual belief state is not published. Three other models failed before usable output and cannot be interpreted behaviorally.

### L. Housing V12 and V14: pre-trajectory gate failures

Neither version contains a Housing trajectory, but both explain why later examples exist:

- **V12 observation/execution boundary:** the start-to-start pacer imposed a 15-second interval, but a DeepInfra/GLM admission call lasted `147.14` seconds. The next call therefore began without another wait and returned HTTP 429. Admission passed 17/18 probes and correctly blocked all four planned trajectories. The event also exposed that admission did not enforce the declared 120-second timeout.
- **V14 observation/execution boundary:** V14 carried V13's successful routes and completion-based cooldown into a 48-cell design. Friendli/GLM passed only 6/9 admission probes because three calls returned HTTP 429; Parasail/DeepSeek passed 9/9. All 48 trajectories remained unstarted.
- **Reasoning-sensitive point:** none. These failures occur before a valid task trajectory can test observation, belief, or economic decision-making.
- **Verdict:** pacing and admission policy are measurement controls. Their failure must be diagnosed separately from model reasoning, and blocked cells must not become zero Housing scores.

### M. Housing V13: successful route-promotion gate

V13 changed GLM's route to Friendli, replaced start-to-start pacing with a 10-second completion-to-next-start cooldown, and enforced the 120-second timeout during admission. All 18 admission probes and all four frozen trajectories passed.

- **Observed range:** all four cells use one moderate world (`227922569`) and complete two rounds with two signed assignments. Scores range from `0.8331` to `0.9331`; no trajectory has an IR violation.
- **Path-equivalent outcome:** DeepSeek self-play and GLM self-play both assign `(0,3)` and `(2,2)`, producing welfare `955.21` and score `0.9331`. DeepSeek uses 11 offers, 9 passes, 7 accepts, and 2 signs; GLM uses 8 offers, 5 passes, 1 accept, 2 counters, 3 reject-all responses, 5 walks, and 2 signs.
- **Observation → belief:** not published. The differing response and commitment paths are observable only in aggregate, so beliefs about congestion, pricing, or holds remain undetermined.
- **Decision → action → execution:** both paths eventually select the same two matches and replay exactly, despite substantially different intermediate actions.
- **Outcome:** the gate establishes route/harness completion and replay, not strategy superiority. Four completions on one world do not support a ranking.
- **Verdict:** V13 strengthens the earlier V7/V8 finding that terminal equivalence can hide different reasoning-sensitive paths.

### N. Housing V15: completed extrema

V15 applies the V13 routes and cooldown to four new worlds, three difficulty configurations, and four self/cross-play conditions. Its two completed extrema share the same DeepSeek-subject/GLM-opponent direction and each records two retries, but occur in different worlds and configurations.

**Lowest completion:** `episode_attempt_46ee5db15f4828c3b427`, moderate world `264284765`:

- **Decision/action:** 12 offers, 11 passes, 6 reject-all responses, only 1 accept and 1 sign across two rounds.
- **Execution:** one assignment, no IR violation, and 11 wasted contacts.
- **Outcome:** welfare `218.94` versus baseline `718.89` and oracle `1128.13`; score `0.1941`.
- **Interpretation:** the visible bottleneck is offer/response conversion into commitments. Whether this reflects bad congestion beliefs, excessive rejection, poor offer quality, or counterpart policy is undetermined.

**Highest completion:** `episode_attempt_36a4753218e012636d46`, severe world `366965770`:

- **Decision/action:** 6 offers, 3 accepts, 3 signs, and 3 passes in one round.
- **Execution:** all three available matches complete; no IR violation; 3 wasted contacts.
- **Outcome:** welfare equals the oracle at `1074.66`; score `1.0`.
- **Interpretation:** first-round target and acceptance choices suffice for the optimal allocation, but the projection cannot establish the beliefs that generated them.

**Verdict:** equal retry count does not explain the outcome gap. The observable difference lies primarily in decision/action patterns and commitment conversion, while world/configuration differences prevent a controlled causal comparison.

### O. Housing V15: visible retries and resilience

- Admission allowed up to four receipt-visible attempts with recorded `2/4/8`-second backoff, although all 18 admission probes passed on their first attempt.
- During trajectories, retry-heavy completion remained possible. `episode_attempt_17151019d972e19a7653` records 13 effective retries yet completes three assignments with score `0.9507`.
- **Chain implication:** retries sit at the action → execution boundary. They affect latency, cost, and missingness but are not a measure of belief quality or reasoning effort.
- **Verdict:** V15 provides stronger evidence than V10 that explicit retry accounting can preserve valid trajectories without hiding provider instability. Capability reports must still show retries and operational coverage beside outcome scores.

### P. Housing V15: residual operational failures and incomplete inference

V15 attempted all 48 frozen cells: 43 completed and 5 became typed missingness. Four failures exhausted repeated Friendli/GLM rate limits and one Friendli/GLM call timed out; all five trajectories contain a GLM seat. Parasail/DeepSeek had zero failures across 623 calls.

- **Early breaks:** two failures stop during `contact` or `respond`, before a complete commitment cycle.
- **Late breaks:** other failures contain one or two completed phase cycles and partial valid actions but no terminal score.
- **Execution → outcome:** partial task behavior cannot be promoted to a comparable terminal economic observation.
- **Inference consequence:** every world is missing at least one required GLM-subject cell. The paired-world count is therefore zero, so the planned GLM-minus-DeepSeek variance contrast is not estimable.
- **Verdict:** completion improved from V10's 31/48 to V15's 43/48, but routes, worlds, and controls changed, so this is a descriptive reliability improvement rather than a controlled capability gain. V15 remains non-rankable exploratory evidence.

## Cross-trajectory findings

### Where the chain changes observably

| Boundary | Evidence across trajectories | Interpretation |
|---|---|---|
| Observation → belief | Public projections contain neither ordered observations nor belief records. | No direct conclusion; requires sealed event projection or declared structured decision record. |
| Belief → decision | Different offer/counter/sign/walk patterns imply different selected policies. | Candidate strategic/objective differences, but beliefs cannot be recovered uniquely from actions. |
| Decision → action | Malformed responses/commits and missing required commercial actions expose failures here. | Strong evidence for execution or constraint-tracking diagnostics; not automatically poor strategy. |
| Action → execution | Retries, empty content, timeout, rate limit, and transport failures interrupt otherwise possible actions. | Infrastructure reliability must remain separate from capability. |
| Execution → outcome | Assignment count and identity change welfare dramatically; the same terminal assignment can arise from different paths. | Outcome verification is necessary but insufficient for process claims. |

### What the representative set teaches

1. **Commitment is the decisive Housing bottleneck.** High trajectories convert available offers/holds into three or four signs; the weakest V10 trajectory produces many counters and walks but only two signs.
2. **More activity is not better reasoning.** The population lower case uses 46 actions and four cycles yet performs far worse than the 29-action upper case.
3. **The same outcome can hide different reasoning-sensitive paths.** V7/V8 reach identical assignments with different offer/pass patterns.
4. **Operational effort is not cognition.** Equal retry counts coexist with very different scores; provider failure must not be treated as a decision.
5. **Terminal welfare does not diagnose the mechanism.** It reveals allocation quality but not whether the cause was objective selection, strategic modeling, constraint tracking, or schema execution.
6. **A second family shows a different bottleneck.** The commercial-state trajectory gets amounts and evidence right but misses part of state/action completeness, suggesting requirement integration rather than market coordination.
7. **A successful promotion gate is not a performance result.** V13 proves that the frozen route/harness can complete and replay one four-cell matrix; it does not establish model superiority.
8. **Pacing semantics matter.** V12's start-to-start pacing failed after a long call, whereas V13's completion-to-next-start cooldown passed its gate. V14 and V15 then show that cooldown alone cannot eliminate shared-pool rate limits.
9. **Reliability improvements do not guarantee estimability.** V15 completes 43/48 cells, yet strategically placed missing cells leave zero complete paired worlds and no estimable primary contrast.
10. **Visible retries protect attribution.** V15 can distinguish a retry-heavy valid completion from exhausted rate limits, preventing hidden provider repair from being mistaken for agent competence.

## Answer to “where reasoning changes the chain”

The public evidence identifies four places where better reasoning **could** change behavior:

1. **After a new Housing board/inbox observation:** update beliefs about availability, congestion, acceptable price, and counterpart response.
2. **Before offer or response selection:** choose a target and price that maximize the declared objective while respecting private information and constraints.
3. **Before sign/walk:** integrate hold terms, own payoff, scarcity, and remaining rounds into a commitment decision.
4. **Before a commercial-state action list:** integrate every relevant evidence item into a complete set of required states, claims, and actions.

But none of the published trajectories demonstrates that a **change in reasoning configuration** caused a change at these points. A causal answer requires the same model, route, case/world, counterpart, prompt, budgets, and seed under paired predeclared reasoning conditions. The current files use low reasoning and omit reasoning content.

## Construct-validity cross-review

**Verdict:** The trajectories are valid descriptive evidence for allocation/state outcomes, action/execution diagnostics, typed missingness, and replay. They are not sufficient for causal reasoning attribution or model ranking.

Review safeguards:

- Keep observed action facts separate from inferred beliefs.
- Require event IDs for claims about adaptation between rounds.
- Never interpret empty/timeout/rate-limit/transport outcomes as economic choices.
- Report welfare, IR violations, assignment count, wasted contacts, action validity, retries, latency, and coverage separately.
- Keep cross-play, self-play, scripted controls, worlds, and campaign versions separate.
- Treat world seed as the independent cluster, not actions, seats, or turns.
- Use `undetermined` when objective selection, strategic modeling, constraint tracking, and execution remain observationally equivalent.
- Do not let a convincing rationale rescue an invalid action or let an optimal outcome prove a faithful rationale.

## Evidence needed for a true event-level review

For the strongest next analysis, publish a sanitized ordered projection for the population upper/lower pair, V10 extrema, V13 terminal-equivalent paths, and V15 extrema containing:

- event ID, round, phase, and acting seat;
- exact permitted observation or a review-safe projection of it;
- parsed action, legality verdict, retries, and finish status;
- hold creation/expiration and pre/post-state diff;
- outcome contribution and counterfactual legal alternatives; and
- optional task-visible structured decision record, if predeclared.

The structured record may name selected objective, key state beliefs, binding constraints, anticipated response, chosen action, and rejected alternative. It should be treated as secondary self-report—not hidden or necessarily faithful chain-of-thought.

## Related-work outline

1. **BDI and control-loop models:** motivate separation of observations, beliefs, intentions/decisions, actions, and environmental execution.
2. **ReAct and interactive agents:** compare interleaved rationale/action interfaces with AERead's phase-governed multi-agent environment.
3. **Process versus outcome supervision:** explain why trajectory diagnostics complement but cannot replace verified terminal outcomes.
4. **Rationale faithfulness:** cover post-hoc explanations and motivate structured, versioned decision records plus deterministic event predicates.
5. **Tool-agent benchmarks:** contrast terminal task/database correctness with process constraints, retries, and replay.
6. **Economic mechanism design:** separate allocation welfare from rent distribution, individual rationality, fairness, and strategic incentives.
7. **Multi-agent evaluation:** motivate scripted anchors, self-play, cross-play, frozen counterpart panels, and cluster-level inference.
8. **Construct validity and missingness:** show why beatable baselines, shortcut checks, typed infrastructure failure, and coverage are necessary for interpretable capability claims.
