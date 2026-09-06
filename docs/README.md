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
- [Errata: flagging published evidence after the fact](operations/errata.md)

## Benchmark families

- Housing: [case contract](families/housing/case.md) and [QC profile](families/housing/qc.md)
- Procurement allocation: [case and campaign design](families/procurement-allocation/campaign.md)
- Tau3 retail: [adapter specification](families/tau3-retail/adapter_spec.md), [implementation status](families/tau3-retail/adapter_status.md), and [refund integration plan](families/tau3-retail/refund_external_benchmark_integration.md)
- Data-center development: [negotiation implementation plan](families/datacenter/development_negotiation_implementation_plan.md)

## Research and measurement

- [Verifier taxonomy](research/verifier_taxonomy.md)
- [Verifier-to-case mapping](research/verifier_case_mapping.md)
- [Problem-to-bound case audit](research/problem_bound_case_audit.md)
- [Benchmark saturation](research/benchmark_saturation.md)
- [Reasoning conditions and diagnostics](research/reasoning_condition_and_diagnostics.md)
- [Multi-agent experiment design](research/multiagent_experiment_design.md)

Generated evidence belongs under [`evidence/`](../evidence/). Checked-in family-specific
receipts that document adapter parity remain beside the corresponding family documentation.
