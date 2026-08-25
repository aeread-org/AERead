# Problem-to-bound audit: 23 papers and five AERead cases

**Status:** design audit, 2026-08-23  
**Corpus:** the 23-row benchmark survey, which contains **22 external papers plus the AERead paper**, checked alongside AERead's five pilot-v0 case families  
**Evidence:** PDF-checked against the survey source corpus; AERead cases checked against
the paper and current case specifications

## Audit question and routing rule

This audit asks a narrower question than “does the paper have a metric?” For every
published benchmark or AERead case, it asks what kind of object is measured and what
comparison or optimality evidence is actually available.

1. `property_or_answer` needs an answer key, feasibility test, axiom, or equilibrium
   validator. It does not need an artificial policy optimum.
2. `optimizable_outcome` needs a declared objective, feasible policy class, information
   set, horizon, and opponent condition. For maximization, typed bounds obey
   `V_LB <= V* <= V_UB`.
3. `comparative_or_human_judged` needs a named comparison system, policy, or rater. It
   does not support optimality language without a separate model.

For optimization, `exact_solved`, `epsilon_solved`, `bracketed`,
`lower_bound_only`, `baseline_only`, and `descriptive_only` describe the strongest
supported claim. `property_verified` marks a non-optimization task with an exact
validator. A feasible policy witnesses `optimum_lower_bound`; it is not an outcome floor.
`comparison_baseline` is kept separate even when the same executable policy supplies the
lower-bound witness. True `outcome_support_min` and `outcome_support_max` values must
bound every admissible realized outcome before they are used for [0,1] normalization.

## The 23-paper survey

The paper is the audit unit here. Papers containing heterogeneous sub-benchmarks receive
a `mixed` result and must be routed again at scenario or estimand level during ingestion.
The corresponding semantic verifier routes are enumerated in
[`verifier_case_mapping.md`](verifier_case_mapping.md).

| ID | Paper and case structure | Measurement kind | Strongest justified reference status | Consequence for AERead ingestion |
|---|---|---|---|---|
| P01 | **Alympics**: repeated sealed-bid water-allocation challenge with survival pressure | optimizable, strategic and opponent-dependent | `baseline_only`; survival has natural support, but the paper does not solve the policy game | Retain survival and strategy diagnostics; do not equate survival 1 with a solved optimum. |
| P02 | **AERead**: the five exchange families summarized below | optimizable welfare plus private/distributional diagnostics | `bracketed` for welfare: executable policies give a lower bound and the full-information planner gives an upper bound | Replace “attainable denominator” language with a typed full-information upper bound unless an information-feasible oracle is supplied. |
| P03 | **AgenticPay**: 111 bilateral, one-to-many, and many-to-many buyer-seller tasks | comparative negotiation with bounded ex-post utility geometry | `baseline_only` for the published composite; ZOPA/support bounds exist for some submetrics | Preserve matching, negotiation, and efficiency components separately; the weighted GlobalScore is not an optimum. |
| P04 | **Algorithmic Collusion by LLMs**: repeated Bertrand pricing, with an auction extension | optimizable joint profit and strategic dynamics | `mixed`: analytic Nash/monopoly stage references exist, but no exact long-run policy optimum against an endogenous rival | Store stage-game reference values and opponent condition; do not turn a monopoly benchmark into an agent-attainable policy oracle. |
| P05 | **Bayesian Teaching**: simulated flight/hotel recommendation plus web shopping | mixed answer/policy optimization | `mixed`: exact Bayesian references in finite simulated tasks; learned-model reference in web shopping | Split by subtask; exact simulated cases can be `exact_solved`, while web shopping remains comparative. |
| P06 | **GovSim / Cooperate or Collapse**: repeated common-pool fishery, pasture, and pollution dilemmas | optimizable, multi-agent and opponent-dependent | `baseline_only`; survival/efficiency/equality endpoints are not solved policies | A natural maximum score is not a certified policy upper bound. |
| P07 | **TERMS-Bench**: bilateral hidden-type price negotiation against a fixed simulator across six families | optimizable against a controlled counterpart | `bracketed`: executable policies provide lower bounds and the oracle-cue dynamic program provides a simulator-relative upper bound with extra information | Record oracle information scope explicitly; it supports bound gaps, not a same-information exact optimum. |
| P08 | **EconEvals**: procurement, scheduling/matching, and pricing in basic/medium/hard variants | optimizable, single-agent | `exact_solved` for the declared task objective; exact instance solutions and greedy baselines are provided | This is the clearest template for exact `V_LB = V_UB` receipts. |
| P09 | **Economic Rationality under Specialization**: budget/risk choices scored by GARP violations | property/compliance, lower-is-better | `property_verified`; zero violations is a rationality target, not a discovered policy optimum | Route through a property validator and store direction; the survey's higher-is-better saturation code is invalid here. |
| P10 | **Economy of Minds**: auctions/payments coordinate subagents on math, finance, and software tasks | task-specific answer or benchmark quality; economic coordination mechanism | `mixed`; some external tasks have exact answers, others only benchmarks | Flag **Economic task versus economic coordination mechanism**: it is relevant to runner architecture but is not itself one economic decision environment. |
| P11 | **FinanceBench**: 150 expert-authored financial question-answering cases | property/answer | `property_verified` against reference answers | Useful for verifier design, out of scope for an interactive economic-policy case. |
| P12 | **GDPval**: 1,320 work-product tasks judged head-to-head by experts | comparative/human-judged | `baseline_only`; expert win rate has no fixed optimum | Store rater protocol, reference system, ties, and uncertainty; no saturation claim from a high win rate alone. |
| P13 | **GTBench**: ten canonical complete/incomplete-information, deterministic/stochastic, static/dynamic games | mixed property and optimizable game outcomes | `mixed`; exact solvers/equilibrium checks exist for some games, relative advantage for others | Ingest per game and estimand, never as one cross-game optimum. |
| P14 | **Game-theoretic LLM**: normal-form, sequential, and incomplete-information negotiation workflows | mixed property and strategic optimization | `mixed`: finite complete-information solutions can be exact; incomplete-information negotiation is information-relative | Bind every solution reference to game form and information set. |
| P15 | **GAMA-Bench**: eight classic games, including public goods, auctions, coordination, and bargaining | mixed property and strategic outcome | `mixed`; game-specific Nash or rule-derived ideals, not one universal `V*` | Keep the game-specific scoring vector and validators; do not pool “distance to ideal” without a defended mapping. |
| P16 | **Hierarchical Text Generation and Planning for Strategic Dialogue**: Deal-or-No-Deal item-split negotiation | optimizable terminal allocation against learned opponents | `baseline_only` or `lower_bound_only`; terminal feasible allocations are enumerable, but the evaluated opponent-conditioned policy optimum is not solved | Also flag corpus scope: this is a 2017 non-LLM benchmark paper, not a 2024-26 LLM-economic-agent case. |
| P17 | **NegotiationArena**: resource exchange, multi-turn ultimatum, and price negotiation | comparative, opponent-dependent | `baseline_only`; utilities are known but win/gain depends on the paired opponent | Treat opponent identity and pairing as part of the estimand and cluster/block design. |
| P18 | **MERIT / AGORABench**: nine vanilla, deceptive, monopoly, installment, and perception bargaining regimes | comparative/human-aligned composite | `baseline_only`; MERIT weights consumer surplus, negotiation power, and acquisition similarity using human preferences | Preserve the components and learned normative weights; do not label the composite an oracle. |
| P19 | **Market-Bench**: partially observable procurement, retail pricing, marketing, inventory, and balance-sheet management | optimizable long-horizon profit in an endogenous market | `baseline_only` or `lower_bound_only`; no policy oracle is supplied | Report profit against named agents/policies and retain the full market condition. |
| P20 | **Measuring Bargaining Abilities of LLMs**: bilateral Amazon-product buyer/seller bargaining | optimizable outcome plus comparative opponent play | `bracketed` only for ex-post outcome geometry; no hidden-information policy optimum against an LLM opponent | ZOPA/list/cost/WTP can bound terminal deals, but not the strategic policy without an information model. |
| P21 | **AucArena**: long-horizon multi-item open ascending auctions with budgets and private goals | comparative, strategic and opponent-dependent | `baseline_only` or `lower_bound_only`; profit and TrueSkill do not solve the auction policy game | Record bidder field and pairing; no universal score or saturation conclusion. |
| P22 | **STEER**: generated multiple-choice special cases in utility, games, social choice, and mechanism design | property/answer | `property_verified` against generated rational answers | Treat as rationality/knowledge validation, not an interactive policy optimum. |
| P23 | **Vending-Bench**: long-horizon ordering, inventory, and pricing with simulated customers | optimizable single-agent business outcome | `baseline_only` or `lower_bound_only`; human and agent results are references, not a solved dynamic program | Net worth remains in native units unless a case-specific bound is later certified. |

## The five AERead pilot-v0 cases

For all five families, the current `W*` computation optimizes terminal social welfare
with full world information. The evaluated policy controls one seat against a fixed or
version-pinned panel and, in cases 03-05, faces information, consent, or intertemporal
constraints. The AERead paper explicitly states that the multi-agent Bayesian-Nash
frontier is intractable. Therefore the planner is a valid declared
`optimum_upper_bound` for social welfare, but it is not generally an attainable
same-information ceiling for the evaluated seat.

| ID | AERead family | Added pressure | Social-welfare route | Private/distributional route |
|---|---|---|---|---|
| A01 | visible bilateral IR | full visibility; bilateral settlement; frozen panel | `bracketed`: scripted feasible policy supplies `V_LB`; full-information `W*` supplies `V_UB`; case may be empirically compressed | observed seat gains and IR diagnostics; bargaining references only for valid bilateral fixed-deal subsets |
| A02 | multiparty clearing | bundle composition, partial clearing, settlement-row limits | `bracketed`: executable bilateral/multiparty policies below a full-information allocation bound | observed gains; core/Shapley claims wait for coalition values and a genuine multiparty settlement subset |
| A03 | hidden discovery | limited contacts, solicitation, hidden allocations | `bracketed`, with the widest information wedge: feasible discovery policy below a full-information planner bound | observed gains and discovery/inaction decomposition; no universal capture optimum |
| A04 | consent under hidden information | private information and private sign-off | `bracketed`: full-information welfare is an upper bound; information- and incentive-feasible optimum is unresolved | report principal and counterparty gains plus IR/consent; any Nash reference must declare feasible set and disagreement values |
| A05 | deferred settlement | pay-first credit, one transfer row per round, no atomic swap | `bracketed`: full-information terminal welfare is an upper bound, while the attainable policy value depends on trust and panel behavior | observed gains, counterparty harm, and defection/trust diagnostics; realized-joint-gain capture ratios are unstable when harm drives the denominator toward zero |

## Findings and implementation consequences

1. **There is no 28-case universal denominator.** Exact answers, equilibrium-property
   checks, human comparisons, opponent-conditioned games, and policy optimization are
   different estimand types.
2. **The survey's `computes_optimum` flag is too coarse.** A metric maximum, equilibrium
   reference, full-information relaxation, and same-information policy optimum are not
   interchangeable. P09 is also lower-is-better, and P10's extracted score column mixes
   task-specific units, so automated saturation must not trust the extracted table
   without case metadata.
3. **Only a minority are clean exact-optimization templates.** EconEvals is the clearest;
   finite games, exact-answer tasks, and simulated Bayesian tasks are exact only within
   their declared subproblem.
4. **Negotiation and multi-agent markets are usually opponent- and information-relative.**
   They generally support baselines, feasible witnesses, or relaxed upper bounds—not an
   oracle for the tested policy.
5. **AERead's five cases are coherent under typed brackets.** Their full-information
   planner remains useful, but the paper and runner must call it an upper bound and
   report the bound gap separately from the executable comparison baseline.
6. **Saturation requires certified remaining headroom.** A case is `ceiling_exhausted`
   only when the best result is within a predeclared epsilon of a valid upper bound under
   the same estimand and the cluster-level interval supports that conclusion. A tight
   score frontier without such evidence is `compressed_undecidable`.

## Corpus cautions

The 23-row survey is useful for architectural coverage, but it is not yet a clean set of
23 comparable economic-agent benchmarks. It includes AERead itself, a 2017 strategic
dialogue paper, exact-answer QA, work-product evaluation, and an economic coordination
mechanism whose downstream tasks are not primarily economic decisions. The next corpus
revision should retain these as tagged architectural precedents while defining a narrower
external economic-agent comparison set for paper claims.
