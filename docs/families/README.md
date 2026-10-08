# Benchmark family documents

Every document under `docs/families/`, one section per family directory. The
[documentation index](../README.md) links the entry points; this page is the
complete list, and `tests/test_docs_layout.py` fails when a document is added
without a link here or there.

Directory names are the kebab-case family names; the package under
`src/aeread_families/` is given beside each. Review trails are point-in-time
records: each says what was examined at one commit, and the disposition is
only meaningful next to the findings it answers.

[Versioned campaign modules](campaign_modules.md) lists, for each campaign a
family has revised, which module is current and which are frozen earlier
versions. The repository-wide family table is in the
[root README](../../README.md#every-family).

## AgenticPay

Directory `agenticpay-bilateral/`, package `agenticpay_bilateral`.

- [Adapter specification](agenticpay-bilateral/adapter_spec.md)
- [Adapter status](agenticpay-bilateral/adapter_status.md)
- [Scoring-contract migration plan](agenticpay-bilateral/migration_plan.md)
- [Scoring-contract migration review](agenticpay-bilateral/migration_review.md)
- Review trail: [Claude review](agenticpay-bilateral/reviews/agenticpay_review_claude.md), [Codex review](agenticpay-bilateral/reviews/agenticpay_review_codex.md), [Codex triage](agenticpay-bilateral/reviews/agenticpay_codex_triage.md), [disposition](agenticpay-bilateral/reviews/agenticpay_review_disposition.md)

## Alympics WAC

Directory `alympics-wac/`, package `alympics_wac`.

- [Adapter specification](alympics-wac/adapter_spec.md)
- [Adapter status](alympics-wac/adapter_status.md)
- [Scoring-contract migration plan](alympics-wac/migration_plan.md)
- [Scoring-contract migration review](alympics-wac/migration_review.md)
- Review trail: [Claude review](alympics-wac/reviews/alympics_review_claude.md), [Codex review](alympics-wac/reviews/alympics_review_codex.md), [Codex triage](alympics-wac/reviews/alympics_codex_triage.md), [disposition](alympics-wac/reviews/alympics_review_disposition.md), [fix verification](alympics-wac/reviews/alympics_fix_verification.md)

## AmazonHistoryPrice

Directory `amazonbarg/`, package `amazonbarg`.

- [Adapter specification](amazonbarg/adapter_spec.md)
- [Adapter status](amazonbarg/adapter_status.md)
- [Scoring-contract migration plan](amazonbarg/migration_plan.md)
- [Scoring-contract migration review](amazonbarg/migration_review.md)
- Review trail: [Claude review](amazonbarg/reviews/amazonbarg_review_claude.md), [Codex review](amazonbarg/reviews/amazonbarg_review_codex.md), [Codex triage](amazonbarg/reviews/amazonbarg_codex_triage.md), [disposition](amazonbarg/reviews/amazonbarg_review_disposition.md), [fix verification](amazonbarg/reviews/amazonbarg_fix_verification.md)

## AucArena

Directory `aucarena/`, package `aucarena`.

- [Adapter specification](aucarena/adapter_spec.md)
- [Adapter status](aucarena/adapter_status.md)
- [Scoring-contract migration plan](aucarena/migration_plan.md)
- [Scoring-contract migration review](aucarena/migration_review.md)
- Review trail: [Claude review](aucarena/reviews/aucarena_review_claude.md), [Codex review](aucarena/reviews/aucarena_review_codex.md), [Codex triage](aucarena/reviews/aucarena_codex_triage.md), [disposition](aucarena/reviews/aucarena_review_disposition.md), [fix verification](aucarena/reviews/aucarena_fix_verification.md)

## Algorithmic collusion

Directory `collusion/`, package `collusion`.

- [Adapter specification](collusion/adapter_spec.md)
- [Adapter status](collusion/adapter_status.md)
- [Scoring-contract migration review](collusion/migration_review.md)
- Review trail: [Claude review](collusion/reviews/collusion_review_claude.md), [Codex review](collusion/reviews/collusion_review_codex.md), [Codex triage](collusion/reviews/collusion_codex_triage.md), [disposition](collusion/reviews/collusion_review_disposition.md), [fix verification](collusion/reviews/collusion_fix_verification.md)

## Data-center development

Directory `datacenter/`, package `datacenter_development`.

- [QC profile](datacenter/qc.md)
- [Data-center negotiation family: design findings](datacenter/design_findings_2026-09.md)
- [Data-center development negotiation implementation plan](datacenter/development_negotiation_implementation_plan.md)
- [The V2 full-stack case as a walk-away problem](datacenter/v2_walk_away_analysis.md)

## EconAgent

Directory `econagent/`, package `econagent_v1`.

- [Adapter specification](econagent/adapter_spec.md)
- [Adapter status](econagent/adapter_status.md)
- [Scoring-contract migration plan](econagent/migration_plan.md)
- [Scoring-contract migration review](econagent/migration_review.md)
- Review trail: [Claude review](econagent/reviews/econagent_review_claude.md), [Codex review](econagent/reviews/econagent_review_codex.md), [Codex triage](econagent/reviews/econagent_codex_triage.md), [disposition](econagent/reviews/econagent_review_disposition.md), [fix verification](econagent/reviews/econagent_fix_verification.md)

## EconEvals

Directory `econevals/`, package `econevals`.

- [Adapter specification](econevals/adapter_spec.md)
- [Adapter status](econevals/adapter_status.md)
- [econevals first live campaign (issue #90)](econevals/campaign.md)
- [econevals first-light: incident ledger](econevals/incidents.md)
- Review trail: [Claude review](econevals/reviews/econevals_review_claude.md), [Codex review](econevals/reviews/econevals_review_codex.md), [disposition](econevals/reviews/econevals_review_disposition.md)

## GovSim

Directory `govsim/`, package `govsim`.

- [Adapter specification](govsim/adapter_spec.md)
- [Adapter status](govsim/adapter_status.md)
- [GovSim live campaign (#91): scoping, and the one decision it needs](govsim/campaign_scoping.md)
- [govsim live campaigns: incident ledger](govsim/incidents.md)
- Review trail: [Claude review](govsim/reviews/govsim_review_claude.md), [Codex review](govsim/reviews/govsim_review_codex.md), [Codex triage](govsim/reviews/govsim_codex_triage.md), [disposition](govsim/reviews/govsim_review_disposition.md), [fix verification](govsim/reviews/govsim_fix_verification.md)

## Housing

Directory `housing/`, package `housing`.

- [Case contract](housing/case.md)
- [QC profile](housing/qc.md)

## NegotiationArena

Directory `negarena/`, package `negarena`.

- [Adapter specification](negarena/adapter_spec.md)
- [Adapter status](negarena/adapter_status.md)
- [Scoring-contract migration plan](negarena/migration_plan.md)
- [Scoring-contract migration review](negarena/migration_review.md)
- Review trail: [Claude review](negarena/reviews/negarena_review_claude.md), [Codex review](negarena/reviews/negarena_review_codex.md), [Codex triage](negarena/reviews/negarena_codex_triage.md), [disposition](negarena/reviews/negarena_review_disposition.md), [fix verification](negarena/reviews/negarena_fix_verification.md)

## Procurement allocation

Directory `procurement-allocation/`, package `procurement_allocation`.

- [QC profile](procurement-allocation/qc.md)
- [Procurement allocation campaign](procurement-allocation/campaign.md)
- [Procurement allocation v1: design review](procurement-allocation/design_review.md)
- [Procurement failure analysis](procurement-allocation/failure_analysis.md)
- [Procurement allocation: positioning and scope](procurement-allocation/positioning.md)
- [Approved recovery confirmation](procurement-allocation/unified_recovery_proposal.md)
- [Approved recovery: complete 36-row confirmation](procurement-allocation/unified_recovery_results.md)
- [Unified continuous procurement execution plan](procurement-allocation/unified_run_plan.md)
- [Unified regret campaign: observed execution](procurement-allocation/unified_run_results.md)
- [Procurement over periods: the award as a relationship](procurement-allocation/relationship_design.md)
- [Hidden-information case: judging a supplier from its record](procurement-allocation/hidden_information_case.md)
- [Procurement case cards](procurement-allocation/case_cards.md)

## Refund

Directory `refund/`, package `refund`.

- [Case contract](refund/case.md)
- [Refund V1.3 DeepSeek V4 Flash Evaluation](refund/deepseek_v4_profiles_2026-09-11.md)
- [Refund V1.3 disclosure and negotiation state machine](refund/negotiation_state_machine_v1_3.md)
- [Refund reasoning experiment](refund/reasoning_experiment.md)
- [Refund V2.1 1:N Pilot](refund/refund_v2_1n_design.md)
- [Refund V2.1 1:N Controlled Experiment Protocol](refund/refund_v2_1n_experiment_protocol.md)
- [Refund V2.1 1:N Selectable-Agent Pilot](refund/refund_v2_1n_pr_draft.md)
- [Refund V1.3 worked trajectories](refund/worked_transcripts_v1_3.md)

## STEER

Directory `steer/`, package `steer`.

- [Adapter specification](steer/adapter_spec.md)
- [Adapter status](steer/adapter_status.md)
- [Scoring-contract migration plan](steer/migration_plan.md)
- [Scoring-contract migration review](steer/migration_review.md)
- Review trail: [Claude review](steer/reviews/steer_review_claude.md), [Codex review](steer/reviews/steer_review_codex.md), [Codex triage](steer/reviews/steer_codex_triage.md), [disposition](steer/reviews/steer_review_disposition.md), [fix verification](steer/reviews/steer_fix_verification.md)

## Tau3 retail

Directory `tau3-retail/`, package `tau3_retail`.

- [Adapter specification](tau3-retail/adapter_spec.md)
- [Adapter status](tau3-retail/adapter_status.md)
- [Refund external-benchmark integration plan](tau3-retail/refund_external_benchmark_integration.md)
- [`receipts/`](tau3-retail/receipts/): checked-in receipts

## TERMS-Bench

Directory `termsbench/`, package `termsbench`.

- [Adapter specification](termsbench/adapter_spec.md)
- [Adapter status](termsbench/adapter_status.md)
- [TERMS-Bench live campaign (#92): what is done, and the blocker](termsbench/campaign_scoping.md)
- Review trail: [Claude review](termsbench/reviews/termsbench_review_claude.md), [Codex review](termsbench/reviews/termsbench_review_codex.md), [Codex triage](termsbench/reviews/termsbench_codex_triage.md), [disposition](termsbench/reviews/termsbench_review_disposition.md)
