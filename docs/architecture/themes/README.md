# Redesign themes

**Status: proposed.** No maintainer has reviewed these documents yet. Each theme asks the owner for one theme-level ruling; a ruling is written into the document it answers, with its date and source.

## Why themes

Fixing open problems one ticket at a time has not converged: each fix sets a local rule, and the rules do not compose (the [T1 design](T1_call_outcome_design.md), section 1.2, shows three rules on missing usage in force at once). The open problems were therefore grouped by root cause, and each group gets one direction instead of a sequence of patches.

The grouping covered, as of 2026-10-21: 50 open issues, 96 open incident-log rows (from `main`, open pull requests and remote branches), and the 670 lines the Examiner checklist flagged across published bundles. Each item was assigned to one of 36 root-cause clusters, and the clusters to seven themes.

## The seven themes

| Theme | Root cause | Charter | Evidence ledger | Label |
|---|---|---|---|---|
| T1 Call-outcome contract | Each client and executor branch decides for itself what a provider call's outcome was, whether it is billed, who writes its terminal and whether it may be retried | [charter](T1_call_outcome_contract.md), [design](T1_call_outcome_design.md), [decision drafts](T1_call_outcome_decisions.md) | in the design | `theme:T1-call-outcome` |
| T2 Run-control contract | Ceilings, retry and replacement rules, halt, spend and concurrency are set per campaign driver, with no single declared block or admission check | [charter](T2_run_control_contract.md) | [ledger](ledgers/T2_ledger.md) | `theme:T2-run-control` |
| T3 Verifiable identity | Pins are chosen per family and per whole file: too coarse to survive an edit, too few to cover what decides the score; replay is optional | [charter](T3_verifiable_identity.md) | [ledger](ledgers/T3_ledger.md) | `theme:T3-identity` |
| T4 Publication and QC | Bundles do not carry the facts the Examiner and QC gates need, so every check guesses from report keys | [charter](T4_publication_and_qc.md) | [ledger](ledgers/T4_ledger.md) | `theme:T4-publication-qc` |
| T5 Statistical design | Sizing, intervals, missingness bounds, screens and controls are left to each campaign | [charter](T5_statistical_design.md) | [ledger](ledgers/T5_ledger.md) | `theme:T5-statistical-design` |
| T6 Case construct validity | No step when a case is written checks what each seat is shown against what is graded | [charter](T6_case_construct_validity.md) | [ledger](ledgers/T6_ledger.md) | `theme:T6-construct-validity` |
| T7 Other | No shared root cause; a disposition list | [charter](T7_other.md) | [ledger](ledgers/T7_ledger.md) | `theme:T7-other` |

Rulings and open questions that the charters cite are listed, with their sources, in the [rulings register](ledgers/rulings_register.md).

## How issues are classified

- Every open issue and pull request that belongs to a theme carries one `theme:` label. A new issue gets its label at triage.
- The [AERead board](https://github.com/orgs/aeread-org/projects/1) shows the same grouping: the "By theme" view has one column per theme, and the "Decisions" view lists every open decision, theme-level and issue-level, with who it waits on.
- A theme's charter lists its members. If an item's label and its charter disagree, the label is corrected and the charter's member list follows at its next revision.

## Reading a charter

Each charter has the same eight sections: problem and root cause, direction, scope, already decided, the theme ruling requested, the issue-level decisions that follow, delivery, and what was not verified. Evidence carries a label: `[read]` the source was read and says so, `[run]` it was reproduced in memory, `[row]` it is taken from an incident row or issue text without re-checking. Rulings carry `[owner]`, `[merged]`, `[on behalf]` (adopted on the owner's behalf) or `[record]` (an author's decision record, not a ruling). Line references are at `main` `1e2ae367`.
