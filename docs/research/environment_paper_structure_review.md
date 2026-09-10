# Environment-paper structure review for AERead

**Purpose:** working literature map for drafting an AERead environment paper and
rehearsing a research-engineering discussion. This is not a systematic review.

**Source check:** 2026-09-06. The section maps below are condensed paraphrases, not
verbatim tables of contents. Full texts were checked for the principal templates:
Terminal-Bench, AppWorld, AgentGym, tau2-bench, and SidConArena. Harbor and
Harbor-Index are cited as software/documentation and a release article, respectively.

**Clarification on Harbor:** the relevant Harbor project is the software framework from
the creators of Terminal-Bench. Its current citation is a software citation, not a
standalone environment paper found in the official references checked. The closest paper-level description is the Terminal-Bench
2.0 paper, which includes Harbor as the execution harness. Papers named HARBOR about
robot RL automation or persona dynamics are unrelated homonyms.

## 1. How adjacent papers are organized

| Work | Paper argument | Main section sequence | Most useful lesson for AERead |
|---|---|---|---|
| [AppWorld](https://arxiv.org/html/2407.18901v1) | A controllable app ecosystem supports complex tasks and evaluation over legitimate alternative solutions. | Introduction; environment engine; benchmark construction; experiments; related work; conclusion; limitations; ethics. | Best overall template: separate the reusable engine from the tasks and their validation. State-change tests and collateral-change checks matter alongside task completion. |
| [Terminal-Bench 2.0](https://arxiv.org/abs/2601.11868) + [Harbor](https://github.com/harbor-framework/harbor) | Realistic outcome-driven terminal tasks require curated tasks, executable verification, and a portable harness. | Introduction; task formulation; dataset construction; verification; composition; experimental setup; agents/models; Harbor; results; cost/performance; trajectory- and command-level error analysis; limitations. | Separate the environment/harness contribution from benchmark construction, then demonstrate both through executable verification and failure analysis. |
| [τ-bench](https://arxiv.org/abs/2406.12045) | Tool agents must be evaluated through interaction with users, policies, APIs, and mutable state. | Motivation; domains and policies; user simulator; agent tools; state-based evaluation; experiments; pass^k reliability; error analysis. | Define success in terminal state rather than one reference trajectory, and measure consistency across stochastic trials. |
| [τ²-bench](https://arxiv.org/abs/2506.07982) | Single-control simulations miss settings where both sides act on a shared world. | Introduction; related work; Dec-POMDP formalization; domain and compositional task creation; task evaluation; experiments; ablations; conclusion. | This is AERead's closest structural precedent: formalize multi-party control, explain the generator, prove verifiability, and separate reasoning from coordination failures. |
| [WorkArena and BrowserGym](https://arxiv.org/abs/2403.07718) | Knowledge-work agents require a reproducible enterprise application plus a reusable browser-agent environment. | Motivation; benchmark environment; task definitions; BrowserGym observations/actions; evaluation; baselines; results and failure analysis. | Clearly distinguish the reusable environment API from the particular benchmark/task suite instantiated on top of it. |
| [OSWorld](https://arxiv.org/abs/2404.07972) | Agents should operate in real computer environments with controllable initial states and execution-based evaluators. | Introduction; environment; task definition; infrastructure; initial-state setup; execution-based evaluation; observation/action spaces; benchmark construction; human performance; model baselines; analysis. | Put observation space, action space, initialization, and evaluator functions in the main paper, not only in an appendix. Include human feasibility evidence where possible. |
| [AgentBench](https://arxiv.org/abs/2308.03688) | A common evaluation package can compare LLM agents across heterogeneous interactive environments. | Agent definition; environment composition and taxonomy; unified evaluation; results; cross-environment analysis; related work. | Breadth is credible only when the shared interface and the meaning of cross-domain comparison are explicit. AERead should not imply that unlike family metrics form one universal score. |
| [SOTOPIA](https://arxiv.org/abs/2310.11667) | Open-ended social interaction needs a scenario space, episode model, and holistic evaluator. | Interaction environment; task space; episodes; evaluation framework; human validation of the evaluator; experiments; model-human comparison. | When deterministic verification is impossible, validate the evaluator against humans. AERead can use this as a contrast for why deterministic economic state and constraint checks should remain separate from judged qualities. |
| [TheAgentCompany](https://arxiv.org/abs/2412.14161) | Consequential workplace tasks require a self-contained organizational environment with realistic tools and communication. | Benchmark desiderata; comparison; environment setup; task structure; metrics and workflow; task creation and manual curation; baselines; results; common failures; implications. | State benchmark desiderata early, explain task curation/QC, and include common failures rather than presenting only aggregate performance. |
| [AgentGym](https://arxiv.org/html/2406.04151v1) | Shared environments, an evaluation suite, and trajectory data enable studying general agent learning. | Introduction; formal preliminaries; platform/benchmark/data; learning method; experiments; related work; conclusion. | Keep infrastructure, benchmark instances, and learning interventions distinct. A training algorithm is a separate contribution; AERead need not lead with RLVR. |
| [SidConArena](https://arxiv.org/html/2606.27397v1) | A partially observed economy measures negotiation, production, and auction decisions through executable outcomes. | Introduction; related work; formal problem; framework; experimental setup; results; conclusion; limitations; ethics. | The closest economic comparator found: state, information, incentives, and dynamics precede model results; self-play and mixed-model tournaments answer different questions. Economic simulation plus verifiable outcomes alone is not a novelty claim. |

### 1.1 What the closest papers actually ask the reader to trust

- **AppWorld:** the app engine behaves consistently; reference solutions solve the tasks;
  state-based checks accept alternative legitimate outcomes; experiments diagnose why
  agents fail. Consult Sections 2–4 of the linked full text.
- **Terminal-Bench:** the tasks are difficult and well specified; reference solutions,
  human review, automated checks, and exploit attempts validate them; controlled agent
  runs and failure analysis make the benchmark informative. Harbor appears in Section
  3.4; the QC appendix supplies implementation detail.
- **tau2-bench:** the formal interaction matches the intended task; compositional task
  generation yields verifiable instances; centralized-control ablations test coordination
  costs; separate simulator audits test whether the apparatus itself is reliable.
- **AgentGym:** a common platform supports multiple environments; the benchmark/data
  artifacts are distinct from the learning method; ablations evaluate the latter.
- **SidConArena:** structured actions and deterministic economic execution ground an
  interactive game; homogeneous and mixed-model evaluation expose different behavior.

These are five different evidentiary arguments. Their shared lesson is to attach an
experiment to each principal contribution rather than make the architecture diagram
carry the whole paper.

### 1.2 Current Harbor QC precedent

The [Harbor-Index release](https://harbor-index.org/) is useful methodological reading,
although it is not a standalone environment paper. It describes difficulty filtering,
automated audits, human review, task repair, and repeated evaluation. It also explicitly
investigates infrastructure failures and verifier false positives/negatives. AERead
therefore cannot claim that task QC or separating model failures from broken tasks is
unique. Its economic measurement and multi-agent protocol must supply the specific
contribution.

## 2. Recurring sections across strong environment papers

The shared pattern is:

```text
Motivating construct and defect in existing evaluation
    -> environment/world model
    -> observations, actions, tools, and control boundaries
    -> task construction and task distribution
    -> verification and metrics
    -> harness and reproducibility
    -> experimental protocol and baselines
    -> results and uncertainty
    -> failure analysis and validity threats
    -> limitations and release
```

For AERead, make task construction and evaluator validation explicit before reporting
model scores. A gate specification establishes intended behavior; an empirical study
is needed to establish that the gates catch the relevant measurement defects.

## 3. Recommended AERead paper architecture

Use **AppWorld for engine-versus-benchmark organization**, **tau2-bench for interaction
formalization and evaluator validation**, **Terminal-Bench for QC and failure analysis**,
and **SidConArena as the economic comparison that the novelty argument must survive**.

For an initial 8–10 page main text, compress the detailed manuscript into this layout.
Page allocations are planning estimates, not venue requirements.

| Section | Approximate space | What the section must establish | Rehearsal challenge |
|---|---:|---|---|
| 1. Introduction and related work | 1–1.5 pages | The specific measurement gap and three bounded contributions | What does AERead add beyond existing environments? |
| 2. Economic interaction and the environment | 1.5 pages | State, private information, roles, actions, transitions, utilities; concrete Housing example | Whose decision changes what, and what counts as a good outcome? |
| 3. Task construction and verifier validation | 1.5 pages | Case distribution, feasibility witnesses, reference domains, QC and independent review | Why trust both the case and the checker? |
| 4. Evaluation protocol and implementation | 1–1.5 pages | Focal policies, opponent populations, pairing, operational failures, replay, and controls | What exactly is being compared? |
| 5. Validation experiments and findings | 2–2.5 pages | Claim-linked validity, portability, attribution, and diagnosis evidence | Which experiment could falsify the contribution? |
| 6. Limitations and conclusion | 0.5–1 page | Coverage, incomplete validation, sampling and protocol caveats | What does the evidence not establish? |

Move full schemas, gate enumerations, incident histories, prompts, and detailed run
indexes to appendices. Keep one environment interaction figure, a compact verifier
table, and the principal result/qualification figure in the main text. RLVR is an
optional diagnosis case study rather than the opening contribution.

The following expanded outline maps to the current working manuscript:

1. **Introduction and bounded claim.** Economic-agent evaluation needs both
   outcome-verifiable worlds and governed evidence because policy behavior,
   counterparty behavior, invalid actions, and infrastructure failure otherwise collapse
   into one score.
2. **Design desiderata.** Economic construct fidelity, explicit private information,
   multiple interacting seats, path- or state-scoped verification, replayability,
   statistical identifiability, and typed operational missingness.
3. **Environment and execution model.** Family-owned state/observations/actions and a
   shared runner that owns scheduling, budgets, retries, evidence, and receipts.
4. **Verification model.** Canonical-reference, rule/constraint,
   objective-reference, comparative, and rater/judge leaves; admissibility and
   statistical estimation as separate layers.
5. **Case construction and QC.** Generator parameters, case admission, oracle and
   invariant checks, adversarial mutations, expert review, and contamination controls.
6. **Multi-agent experimental design.** Controlled focal-agent blocks, population
   blocks, cross-play, self-play, role rotation, opponent panels, and independent world
   clusters.
7. **Campaign governance and artifacts.** Immutable plans, append-only attempts,
   explicit failure records, ordered promotion gates, freezes, invalidations, and
   sanitized publication bundles.
8. **Implemented families.** Use a compact table; avoid giving every family equal
   narrative weight.
9. **Housing case study.** Show case admission, route qualification, exploratory
   variance evidence, withheld ranking, and the frozen confirmatory design.
10. **Interoperability and post-training.** Explain how AERead can export to Harbor/ATIF,
    rLLM, or RL systems without allowing an adapter to redefine benchmark truth.
11. **Limitations and validity threats.** Construct validation, opponent-population
    dependence, generator coverage, provider drift, remaining judge calibration, and
    the absence of a universal cross-family score.

## 4. Minimum figures and tables

### Figures

1. **Measurement chain:** construct to re-evaluation, with evidence and validity gates.
2. **Environment boundary:** evaluator-only world state, role-specific observations,
   actions, transitions, and verifier scopes.
3. **Execution/evidence lifecycle:** campaign, run, task, attempt, call, receipt, and
   publication.
4. **Multi-agent design matrix:** controlled focal evaluation versus cross-play and
   self-play.
5. **Housing campaign funnel:** planned, attempted, valid, paired, and claim-eligible
   units.

### Tables

1. Comparison with adjacent environments.
2. Case-family coverage and maturity.
3. Verifier families and claim boundaries.
4. Reproducibility and QC guarantees.
5. Housing pilot facts and permitted interpretations.
6. Threats to validity and corresponding controls.

## 5. Claims to avoid until additional evidence exists

- “AERead measures general economic intelligence.” Current families cover a declared
  subset of economic and stateful decision capabilities.
- “Deterministic verifiers make the benchmark valid.” They make declared checks
  reproducible; construct validity still requires generator, expert, and empirical
  evidence.
- “The Housing pilot ranks models.” The current pilot supports a variance estimate and
  campaign design, not a leaderboard.
- “Self-play measures a model's intrinsic capability.” It measures a joint system under
  a declared population and role assignment.
- “All AERead families are numerically comparable.” The framework intentionally retains
  typed, case-native metrics rather than a default universal score.
- “Harbor compatibility is implemented.” The architecture treats Harbor/ATIF as an
  export target, but the adapter is currently planned unless executable evidence is
  added.
- “Economic multi-agent simulation with verifiable outcomes is new.” SidConArena and
  related work already cover much of this ground; establish the narrower contract and
  protocol contribution through comparison and validation.
- “The current Housing primary contrast isolates the focal model.” The incident log
  records a mixed self-play/cross-play aggregate and an absent scripted anchor. Those
  limitations must remain visible until a separately frozen study addresses them.

## 6. Experiments that turn the draft into a paper

| Research question | Design to write before running | Evidence to report | Current position |
|---|---|---|---|
| Does the environment preserve its rules and information boundaries? | Gold executions, small-instance solver checks, deliberate action/state/visibility mutations, and upstream parity where applicable | Per-mutation detection, false rejection on valid alternatives, state/reward agreement, coverage | Housing goldens and tau retail parity provide a starting point; broader adversarial coverage is unfinished |
| Do tasks exercise the intended economic decisions? | Predeclared generator slices; naive/adaptive/oracle controls; an independent expert sample | Baseline separation, degenerate-case exclusions, reviewer disagreement and adjudication | Provider-free sweep exists; independent construct validation remains open |
| Can we distinguish focal-policy behavior from opponent compatibility? | Fixed scripted anchor plus frozen live panel; balanced roles; paired worlds; repeats within worlds; self-play reported separately | Paired contrasts and intervals, per-role utilities, interaction effects, operational missingness by cell | Housing pilot estimates development variability; it does not complete this attribution study |
| Does the evidence protocol detect misleading evaluation outcomes? | Freeze a defect corpus; inject hidden retries, stale receipts, wrong bounds, and absent calls into copies; compare declared controls | Detection/false-alarm rates and changes in admissible conclusions | Incident histories motivate this study; no comparative gate-effectiveness result is claimed |
| Does a diagnosis support a useful intervention? | One frozen change, a control, and held-out worlds with feasibility guardrails | Mechanism-specific improvement and regressions by slice | Procurement offers a candidate intervention result; Qwen RLVR remains supporting historical evidence pending provenance review |

As rehearsal, draft the environment and verification sections first, then the
experimental protocol. Write the abstract last, using only the contributions for
which the experiment section actually contains evidence.

## References

- Harbor Framework Team. [Harbor: a framework for evaluating and optimizing agents and models in container environments](https://github.com/harbor-framework/harbor), 2026.
- [Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces](https://arxiv.org/abs/2601.11868), 2026.
- Yao et al. [τ-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains](https://arxiv.org/abs/2406.12045), 2024.
- Barres et al. [τ²-bench: Evaluating Conversational Agents in a Dual-Control Environment](https://arxiv.org/abs/2506.07982), 2025.
- Drouin et al. [WorkArena: How Capable Are Web Agents at Solving Common Knowledge Work Tasks?](https://arxiv.org/abs/2403.07718), 2024.
- Xie et al. [OSWorld: Benchmarking Multimodal Agents for Open-Ended Tasks in Real Computer Environments](https://arxiv.org/abs/2404.07972), 2024.
- Liu et al. [AgentBench: Evaluating LLMs as Agents](https://arxiv.org/abs/2308.03688), 2023.
- Zhou et al. [SOTOPIA: Interactive Evaluation for Social Intelligence in Language Agents](https://arxiv.org/abs/2310.11667), 2023.
- Xu et al. [TheAgentCompany: Benchmarking LLM Agents on Consequential Real World Tasks](https://arxiv.org/abs/2412.14161), 2024.
- Trivedi et al. [AppWorld: A Controllable World of Apps and People for Benchmarking Interactive Coding Agents](https://arxiv.org/html/2407.18901v1), 2024.
- [AgentGym: Evolving Large Language Model-based Agents across Diverse Environments](https://arxiv.org/html/2406.04151v1), 2024.
- [SidConArena](https://arxiv.org/html/2606.27397v1), 2026.
- Harbor team. [Introducing Harbor-Index](https://harbor-index.org/), 2026. Release article; not a peer-reviewed paper.
