# AERead documentation

The root [README onboarding journey](../README.md#onboarding-journey) takes you
through one complete Housing task. Continue here to understand how that example
fits into the entire architecture. Read the core journey in order; branch into
the role-specific tracks only when you need them.

## Architecture reading journey

| Stage | Read | What you should understand before continuing |
|---|---|---|
| 1. Execute | [Quickstart](getting-started/quickstart.md) | How a case, profile, seed, and policy produce an execution. |
| 2. Name the records | [Core concepts](getting-started/concepts.md) | Why campaigns, runs, tasks, attempts, calls, receipts, and publications are separate records. |
| 3. See the kernel | [Shared-runner design](architecture/shared_runner_design.md) | How specifications resolve into scheduled phases, evidence, verification, and receipts. |
| 4. Find ownership | [Source package layout](architecture/source_layout.md) | Which responsibilities belong to the shared runner, a benchmark family, or an integration. |
| 5. Follow custody | [Run and publication artifact layout](architecture/artifact_layout.md) | Where raw run evidence lives, what may be published, and how hashes bind the two. |
| 6. Qualify claims | [Benchmark quality-control standard](operations/benchmark_qc.md) | Why successful execution alone is not sufficient benchmark evidence. |
| 7. Govern a study | [Experiment campaign SOP](operations/experiment_campaign_sop.md) | How promotion gates, freezes, invalidations, and publication form one campaign history. |
| 8. Ground it in a family | [Housing case contract](families/housing/case.md), then [Housing QC](families/housing/qc.md) | How the shared contracts become a concrete multi-agent environment and qualification plan. |

After stage 8, choose the track closest to your work:

- **Runner or harness author:** read the [portability contract](architecture/shared_runner_portability_contract.md),
  then the [architecture walkthroughs](walkthroughs/README.md).
- **Benchmark family author:** read the [verifier taxonomy](research/verifier_taxonomy.md),
  [verifier-to-case mapping](research/verifier_case_mapping.md), and
  [problem-to-bound case audit](research/problem_bound_case_audit.md).
- **Campaign operator:** continue with [open-harness testing](operations/open_harness_testing.md)
  and the relevant family QC profile.
- **Researcher:** continue with [multi-agent experiment design](research/multiagent_experiment_design.md),
  [benchmark saturation](research/benchmark_saturation.md), and
  [reasoning diagnostics](research/reasoning_condition_and_diagnostics.md).

The sections below are the reference catalog. They are grouped by ownership,
not intended as a second reading order.

## Getting started

- [Quickstart](getting-started/quickstart.md)
- [Core concepts](getting-started/concepts.md)
- [Submitting an agent](getting-started/submissions.md)
- [Reviewing a published trajectory](getting-started/reviewing_trajectories.md)

## Architecture reference

- [Shared-runner design](architecture/shared_runner_design.md)
- [Shared-runner portability contract](architecture/shared_runner_portability_contract.md)
- [Source package layout](architecture/source_layout.md)
- [Run and publication artifact layout](architecture/artifact_layout.md)
- [Receipt-derived research harness](architecture/research_runner_harness.md)
- [Architecture walkthroughs](walkthroughs/README.md)

## Operations

- [Benchmark quality-control standard](operations/benchmark_qc.md)
- [Experiment campaign SOP](operations/experiment_campaign_sop.md)
- [Open-harness testing and leaderboards](operations/open_harness_testing.md)
- [QC and SOP open items](operations/qc_sop_open_items.md)
- [Pull-request lanes and limits](operations/pr_lanes.md)
- [Incident log](operations/incident_log.md)
- [Moved documents](operations/moved_documents.md): where a cited path went

## Benchmark families

The [family index](families/README.md) lists every document under
`families/`; the entry points are below.

Browse the [evidence index by benchmark](../evidence/README.md#benchmark-index)
for published campaigns and registers, including the 17 preserved legacy paths.

- Housing: [case contract](families/housing/case.md) and [QC profile](families/housing/qc.md)
- Procurement allocation: [case and campaign design](families/procurement-allocation/campaign.md) and the [repeated-sourcing extension](families/procurement-allocation/relationship_design.md)
- Tau3 retail: [adapter specification](families/tau3-retail/adapter_spec.md), [implementation status](families/tau3-retail/adapter_status.md), and [refund integration plan](families/tau3-retail/refund_external_benchmark_integration.md)
- Data-center development: [negotiation implementation plan](families/datacenter/development_negotiation_implementation_plan.md) and [QC profile](families/datacenter/qc.md), and the [V2 walk-away analysis](families/datacenter/v2_walk_away_analysis.md) (decision tree, outcome ladders, the repair), and the [design findings](families/datacenter/design_findings_2026-09.md) recorded with the world pack

## External benchmark adapters

Eleven external benchmarks are wrapped as shared-runner families. Each carries
an implementation specification (what is wrapped, at which pinned commit, with
which verifier shape), an implementation status (what is proven, what is a
stated limit), and a review trail (independent reviews, the triage of their
findings, the disposition, and the fix verification). The trail is kept because
the disposition is only meaningful next to the findings it answers.

| Adapter | Family package | Spec | Status | Disposition | Review trail |
|---|---|---|---|---|---|
| AgenticPay | `agenticpay_bilateral` | [spec](families/agenticpay-bilateral/adapter_spec.md) | [status](families/agenticpay-bilateral/adapter_status.md) | [disposition](families/agenticpay-bilateral/reviews/agenticpay_review_disposition.md) | [claude](families/agenticpay-bilateral/reviews/agenticpay_review_claude.md), [codex](families/agenticpay-bilateral/reviews/agenticpay_review_codex.md), [triage](families/agenticpay-bilateral/reviews/agenticpay_codex_triage.md) |
| Alympics WAC | `alympics_wac` | [spec](families/alympics-wac/adapter_spec.md) | [status](families/alympics-wac/adapter_status.md) | [disposition](families/alympics-wac/reviews/alympics_review_disposition.md) | [claude](families/alympics-wac/reviews/alympics_review_claude.md), [codex](families/alympics-wac/reviews/alympics_review_codex.md), [triage](families/alympics-wac/reviews/alympics_codex_triage.md), [fix verification](families/alympics-wac/reviews/alympics_fix_verification.md) |
| AmazonHistoryPrice | `amazonbarg` | [spec](families/amazonbarg/adapter_spec.md) | [status](families/amazonbarg/adapter_status.md) | [disposition](families/amazonbarg/reviews/amazonbarg_review_disposition.md) | [claude](families/amazonbarg/reviews/amazonbarg_review_claude.md), [codex](families/amazonbarg/reviews/amazonbarg_review_codex.md), [triage](families/amazonbarg/reviews/amazonbarg_codex_triage.md), [fix verification](families/amazonbarg/reviews/amazonbarg_fix_verification.md) |
| AucArena | `aucarena` | [spec](families/aucarena/adapter_spec.md) | [status](families/aucarena/adapter_status.md) | [disposition](families/aucarena/reviews/aucarena_review_disposition.md) | [claude](families/aucarena/reviews/aucarena_review_claude.md), [codex](families/aucarena/reviews/aucarena_review_codex.md), [triage](families/aucarena/reviews/aucarena_codex_triage.md), [fix verification](families/aucarena/reviews/aucarena_fix_verification.md) |
| Algorithmic collusion | `collusion` | [spec](families/collusion/adapter_spec.md) | [status](families/collusion/adapter_status.md) | [disposition](families/collusion/reviews/collusion_review_disposition.md) | [claude](families/collusion/reviews/collusion_review_claude.md), [codex](families/collusion/reviews/collusion_review_codex.md), [triage](families/collusion/reviews/collusion_codex_triage.md), [fix verification](families/collusion/reviews/collusion_fix_verification.md) |
| EconAgent | `econagent_v1` | [spec](families/econagent/adapter_spec.md) | [status](families/econagent/adapter_status.md) | [disposition](families/econagent/reviews/econagent_review_disposition.md) | [claude](families/econagent/reviews/econagent_review_claude.md), [codex](families/econagent/reviews/econagent_review_codex.md), [triage](families/econagent/reviews/econagent_codex_triage.md), [fix verification](families/econagent/reviews/econagent_fix_verification.md) |
| EconEvals | `econevals` | [spec](families/econevals/adapter_spec.md) | [status](families/econevals/adapter_status.md) | [disposition](families/econevals/reviews/econevals_review_disposition.md) | [claude](families/econevals/reviews/econevals_review_claude.md), [codex](families/econevals/reviews/econevals_review_codex.md) |
| GovSim | `govsim` | [spec](families/govsim/adapter_spec.md) | [status](families/govsim/adapter_status.md) | [disposition](families/govsim/reviews/govsim_review_disposition.md) | [claude](families/govsim/reviews/govsim_review_claude.md), [codex](families/govsim/reviews/govsim_review_codex.md), [triage](families/govsim/reviews/govsim_codex_triage.md), [fix verification](families/govsim/reviews/govsim_fix_verification.md) |
| NegotiationArena | `negarena` | [spec](families/negarena/adapter_spec.md) | [status](families/negarena/adapter_status.md) | [disposition](families/negarena/reviews/negarena_review_disposition.md) | [claude](families/negarena/reviews/negarena_review_claude.md), [codex](families/negarena/reviews/negarena_review_codex.md), [triage](families/negarena/reviews/negarena_codex_triage.md), [fix verification](families/negarena/reviews/negarena_fix_verification.md) |
| STEER | `steer` | [spec](families/steer/adapter_spec.md) | [status](families/steer/adapter_status.md) | [disposition](families/steer/reviews/steer_review_disposition.md) | [claude](families/steer/reviews/steer_review_claude.md), [codex](families/steer/reviews/steer_review_codex.md), [triage](families/steer/reviews/steer_codex_triage.md), [fix verification](families/steer/reviews/steer_fix_verification.md) |
| TERMS-Bench | `termsbench` | [spec](families/termsbench/adapter_spec.md) | [status](families/termsbench/adapter_status.md) | [disposition](families/termsbench/reviews/termsbench_review_disposition.md) | [claude](families/termsbench/reviews/termsbench_review_claude.md), [codex](families/termsbench/reviews/termsbench_review_codex.md), [triage](families/termsbench/reviews/termsbench_codex_triage.md) |

Each adapter's documents live in `families/<adapter>/` (`adapter_spec.md`,
`adapter_status.md`, `reviews/`), matching Tau3 retail. The scoring-contract
migration plans and reviews sit beside them and are listed in the
[family index](families/README.md). Source and tests still cite the earlier
root-level paths (`docs/steer_adapter_spec.md`); those resolve through
[moved documents](operations/moved_documents.md).

## Kernel reviews and reports

Point-in-time reviews of the shared runner. Each records what was examined at
one commit and what was ruled; later rulings live in the issues they cite.

- [Kernel scoring-contract design critique](architecture/reviews/kernel_contract_design_critique.md)
- [Kernel scoring-contract conformance-gap review](architecture/reviews/kernel_contract_gap_review.md)
- [Kernel scoring-contract implementation review](architecture/reviews/kernel_contract_impl_review.md)
- [Kernel contract rebase review](architecture/reviews/kernel_contract_rebase_review.md)
- [Shared-runner kernel hardening report](architecture/reviews/runner_hardening_report.md) (nineteen ledger entries, branch `zeyu/runner-hardening`, #55)
- [CI cancellation-context diagnosis](architecture/reviews/ci_cancellation_context_diagnosis.md)
- [Kernel R9/R10 scoring-contract review and dispositions](architecture/reviews/kernel_r9r10_review.md)
- [Kernel ruling R12: seat context reaches the scorer](architecture/reviews/kernel_r12_seat_context.md)
- [Kernel ruling R13: case-conditional leaves](architecture/reviews/kernel_r13_conditional_leaves.md)

## Placement

Where a new document goes, so `docs/` stays navigable from this page:

| Kind | Location |
|---|---|
| How to run, submit, review | `getting-started/` |
| Kernel design, contracts, custody, package layout | `architecture/`; point-in-time kernel reviews and reports under `architecture/reviews/` |
| Standards and procedures (QC, campaign SOP, errata, PR lanes, incident log) | `operations/` |
| One family's case contract, QC profile, campaign design, adapter spec/status | `families/<family>/`; review trails under `families/<family>/reviews/`; checked-in parity receipts under `families/<family>/receipts/` |
| Cross-family research: taxonomies, audits, experiment design, trajectory analyses | `research/` |
| Ordered walkthroughs of the architecture | `walkthroughs/` |

The root of `docs/` holds this index only. Every document is linked from here
or from its section's `README.md`. Repository-root-style paths
(`docs/operations/benchmark_qc.md`) are used for cross-references inside
documents so they survive moves. `tests/test_docs_layout.py` enforces all
three, and that every cited `docs/…md` path exists or is listed in
[moved documents](operations/moved_documents.md). When a document moves, add
its row there in the same pull request: source files are hashed into sealed
identities, so their citations are redirected, not rewritten.

## Research and measurement

- [What we have measured, and whether it can sit beside the paper](research/measured_vs_published.md)
- [Verifier taxonomy](research/verifier_taxonomy.md)
- [Verifier-to-case mapping](research/verifier_case_mapping.md)
- [Problem-to-bound case audit](research/problem_bound_case_audit.md)
- [Benchmark saturation](research/benchmark_saturation.md)
- [Reasoning conditions and diagnostics](research/reasoning_condition_and_diagnostics.md)
- [Stratum splits: which carry signal, and what they cost](research/strata_audit_2026-09.md)
- [Multi-agent experiment design](research/multiagent_experiment_design.md)
- [Representative trajectory analysis, 2026-09-05](research/representative_trajectory_analysis_2026-09-05.md)
- [Full bibliography (BibTeX)](../references.bib)

Generated evidence belongs under [`evidence/`](../evidence/). Checked-in family-specific
receipts that document adapter parity remain beside the corresponding family documentation.
