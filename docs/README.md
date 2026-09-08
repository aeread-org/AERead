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

## Benchmark families

- Housing: [case contract](families/housing/case.md) and [QC profile](families/housing/qc.md)
- Procurement allocation: [case and campaign design](families/procurement-allocation/campaign.md)
- Tau3 retail: [adapter specification](families/tau3-retail/adapter_spec.md), [implementation status](families/tau3-retail/adapter_status.md), and [refund integration plan](families/tau3-retail/refund_external_benchmark_integration.md)
- Data-center development: [negotiation implementation plan](families/datacenter/development_negotiation_implementation_plan.md)

## External benchmark adapters

Eleven external benchmarks are wrapped as shared-runner families. Each carries
an implementation specification (what is wrapped, at which pinned commit, with
which verifier shape), an implementation status (what is proven, what is a
stated limit), and a review trail (independent reviews, the triage of their
findings, the disposition, and the fix verification). The trail is kept because
the disposition is only meaningful next to the findings it answers.

| Adapter | Family package | Spec | Status | Disposition | Review trail |
|---|---|---|---|---|---|
| AgenticPay | `agenticpay_bilateral` | [spec](agenticpay_adapter_spec.md) | [status](agenticpay_adapter_status.md) | [disposition](agenticpay_review_disposition.md) | [claude](agenticpay_review_claude.md), [codex](agenticpay_review_codex.md), [triage](agenticpay_codex_triage.md) |
| Alympics WAC | `alympics_wac` | [spec](alympics_adapter_spec.md) | [status](alympics_adapter_status.md) | [disposition](alympics_review_disposition.md) | [claude](alympics_review_claude.md), [codex](alympics_review_codex.md), [triage](alympics_codex_triage.md), [fix verification](alympics_fix_verification.md) |
| AmazonHistoryPrice | `amazonbarg` | [spec](amazonbarg_adapter_spec.md) | [status](amazonbarg_adapter_status.md) | [disposition](amazonbarg_review_disposition.md) | [claude](amazonbarg_review_claude.md), [codex](amazonbarg_review_codex.md), [triage](amazonbarg_codex_triage.md), [fix verification](amazonbarg_fix_verification.md) |
| AucArena | `aucarena` | [spec](aucarena_adapter_spec.md) | [status](aucarena_adapter_status.md) | [disposition](aucarena_review_disposition.md) | [claude](aucarena_review_claude.md), [codex](aucarena_review_codex.md), [triage](aucarena_codex_triage.md), [fix verification](aucarena_fix_verification.md) |
| Algorithmic collusion | `collusion` | [spec](collusion_adapter_spec.md) | [status](collusion_adapter_status.md) | [disposition](collusion_review_disposition.md) | [claude](collusion_review_claude.md), [codex](collusion_review_codex.md), [triage](collusion_codex_triage.md), [fix verification](collusion_fix_verification.md) |
| EconAgent | `econagent_v1` | [spec](econagent_adapter_spec.md) | [status](econagent_adapter_status.md) | [disposition](econagent_review_disposition.md) | [claude](econagent_review_claude.md), [codex](econagent_review_codex.md), [triage](econagent_codex_triage.md), [fix verification](econagent_fix_verification.md) |
| EconEvals | `econevals` | [spec](econevals_adapter_spec.md) | [status](econevals_adapter_status.md) | [disposition](econevals_review_disposition.md) | [claude](econevals_review_claude.md), [codex](econevals_review_codex.md) |
| GovSim | `govsim` | [spec](govsim_adapter_spec.md) | [status](govsim_adapter_status.md) | [disposition](govsim_review_disposition.md) | [claude](govsim_review_claude.md), [codex](govsim_review_codex.md), [triage](govsim_codex_triage.md), [fix verification](govsim_fix_verification.md) |
| NegotiationArena | `negarena` | [spec](negarena_adapter_spec.md) | [status](negarena_adapter_status.md) | [disposition](negarena_review_disposition.md) | [claude](negarena_review_claude.md), [codex](negarena_review_codex.md), [triage](negarena_codex_triage.md), [fix verification](negarena_fix_verification.md) |
| STEER | `steer` | [spec](steer_adapter_spec.md) | [status](steer_adapter_status.md) | [disposition](steer_review_disposition.md) | [claude](steer_review_claude.md), [codex](steer_review_codex.md), [triage](steer_codex_triage.md), [fix verification](steer_fix_verification.md) |
| TERMS-Bench | `termsbench` | [spec](termsbench_adapter_spec.md) | [status](termsbench_adapter_status.md) | [disposition](termsbench_review_disposition.md) | [claude](termsbench_review_claude.md), [codex](termsbench_review_codex.md), [triage](termsbench_codex_triage.md) |

These files sit at the root of `docs/` today. Their home is
`families/<adapter>/` (`adapter_spec.md`, `adapter_status.md`, `reviews/`),
matching Tau3 retail; the move is deferred until the open adapter migration
stack lands, because every one of those pull requests edits these files. New
adapter documents go straight to `families/<adapter>/`. See §Placement.

## Kernel reviews and reports

Point-in-time reviews of the shared runner. Each records what was examined at
one commit and what was ruled; later rulings live in the issues they cite.

- [Kernel scoring-contract design critique](kernel_contract_design_critique.md)
- [Kernel scoring-contract conformance-gap review](kernel_contract_gap_review.md)
- [Kernel scoring-contract implementation review](kernel_contract_impl_review.md)
- [Kernel contract rebase review](kernel_contract_rebase_review.md)
- [Shared-runner kernel hardening report](runner_hardening_report.md) (nineteen ledger entries, branch `zeyu/runner-hardening`, #55)
- [CI cancellation-context diagnosis](ci_cancellation_context_diagnosis.md)

Their home is `architecture/reviews/`; same deferral as above.

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
documents so they survive moves.

## Research and measurement

- [Verifier taxonomy](research/verifier_taxonomy.md)
- [Verifier-to-case mapping](research/verifier_case_mapping.md)
- [Problem-to-bound case audit](research/problem_bound_case_audit.md)
- [Benchmark saturation](research/benchmark_saturation.md)
- [Reasoning conditions and diagnostics](research/reasoning_condition_and_diagnostics.md)
- [Multi-agent experiment design](research/multiagent_experiment_design.md)

Generated evidence belongs under [`evidence/`](../evidence/). Checked-in family-specific
receipts that document adapter parity remain beside the corresponding family documentation.
