# Housing v15, addendum B: Sol 6.1 through Codex and Opus 5.5 through Claude Code

**Status:** declared 2026-10-20, after v15's analysis and addendum A, before any cell of its own, at the owner's
request that Table 5.2 carry the command-line subjects the other cases report ("housing should have cli results in the
table in 5.1"). These are new identities, so the addendum is reported beside v15, as addendum A is. It never changes
v15's declared results, its Holm family or its readings ([plan](price_confirmatory_v15_plan.md), amendment 5).

## 1. Subjects and transport

- **Sol 6.1 through Codex** (`codex_sol61`, model `gpt-6.1-sol`) and **Opus 5.5 through Claude Code**
  (`claude_opus55`, model `claude-opus-5-5`), each at reasoning effort `low`, with no tools. These are the subjects
  of the Procurement and Data-center comparisons. One CLI subprocess per action (Claude Code's `ClaudeCodePrintClient`;
  Codex's `codex_exec_client.CodexExecClient`), on the subscription logins. A cost is the list price of the tokens,
  not a charge.
- **Isolation** as in the Data-center v2 and Procurement v3 confirmatories (`tools/cli_subjects/cli_isolation.py`):
  - Claude Code runs `--safe-mode` in a fresh empty neutral directory;
  - Codex runs with a fresh `HOME` and `CODEX_HOME` that hold only the login, and a neutral working directory;
  - before any world, each CLI is probed under the run's exact flags, and any isolation violation refuses the run;
  - the probe is written to the run root.
- **What a CLI cannot do, declared:** no seed, no temperature, no output cap. The tenant profile seals `seed: null`
  and `sampling_controls: unavailable`. A CLI reports no reasoning tokens.

## 2. Worlds, brief and scoring: v15's

- The v15 pack's 260 main worlds and its 40-world holdout, both landlord arms, one play a cell: 520 main cells and 80
  holdout cells per subject.
- The market, the scripted landlords, the outside demand (0.5 a round on the main pack, 0.3 on the holdout), notice v5
  (the main brief, and on the holdout the brief stating 0.3), and the seat-0 scorer (`price_seat0.build_v15_setup`)
  are v15's.
- Only the deciding tenant's model block and transport differ. The driver builds each v15 plan as the confirmatory
  does, replaces the tenant profile's model block, and resolves the plan again from the same families, cases, pins and
  run spec. No hashed module is edited.

## 3. Identities, ceilings and stops

- **Admission (Section 7 of the v15 plan), both parts.** `housing_lemons_price_v15_cli_admission_<subject>` is one
  full trajectory on the first development world in each arm, which also measures seconds and list cost a cell. The
  isolation probe is the one-call part.
- **Main.** `housing_lemons_price_v15_cli_<subject>`: the 260 main and 40 holdout worlds, claim status
  `confirmatory_addendum`.
- **Ceilings.** Per cell at list price: $1.00 for Sol and $2.00 for Opus, as in the earlier Housing CLI probe. Each
  admission's total is $4.00. Each main identity's total ceiling is set from its admission by v15's amendment-3 rule:
  twice the measured cost a cell times 600, plus one cell's ceiling. It is recorded in an amendment below before that
  main run.
- **Wall-time gate.** Before a main run, project its wall time from the admission's seconds a cell at the declared
  parallelism of 3 cells. If it exceeds 6 hours, stop and ask.
- **Stops,** v15's halt rule:
  - a failed cell is typed missingness and never rerun;
  - no new cell starts after 3 consecutive failed cells in execution order, after a cell over its ceiling, or when the
    next cells could pass the total ceiling;
  - an isolation violation refuses the run.
  - One sealed attempt an action (`max_action_attempts` 1); the CLI's own reconnects are its own.

## 4. Rows, declared now, all descriptive and outside v15's Holm family

Computed once by `tools/housing/price_v15_addendum_b_analysis.py`, committed with this plan, with
`price_v15_analysis`'s own functions on seat 0's measure-v2 primary, each world the mean of its two arms. Per subject,
as addendum A's rows:

| Row | What |
|---|---|
| share | the main-pack mean as a share of the best-informed tenant's ($307.43); the same within each stratum (favourite a lemon, sound), and on the holdout against its own best-informed mean |
| B | subject − `inspect_then_sign`, 95% and 1 − 0.05/3 intervals; it "beats the baseline" when the lower end at 1 − 0.05/3 is above $0, as addendum A reads B3 |
| G | subject − the best-informed tenant, 95% |
| R | subject − `inspect_lowball`, 95% and 1 − 0.05/3 |
| pairs | subject − Gemini, subject − Luna, subject − GLM (addendum A), and Sol − Opus, 95%, descriptive |

Also reported: blind signings, invalid actions, cells completed and cost. A contrast that loses more than 10% of its
worlds is inconclusive (v15's rule).

## 5. Publication

The bundles are published as addendum A's, with `aeread verify-replay` on every published cell and the prohibited-text
scan. A results note goes beside this plan. Runs play from a tree carrying the family's registry row, as v15 did.

## Amendment 1, 2026-10-20 (after both admissions, before either main run)

Both admissions passed. Each CLI's isolation probe found no violation, and each played the first development world
(540003) in both arms, 2 of 2 cells completed, with every receipt replayed in-run.

| | List cost (2 cells) | A cell | Seconds a cell | Main ceiling by the rule | Projected wall time, 600 cells at 3 |
|---|---:|---:|---:|---:|---:|
| Sol 6.1 (Codex) | $0.126802 | $0.0634 | 43.7 and 52.2 | 2 × 0.0634 × 600 + $1.00 = **$77.08** | about 2.7 hours |
| Opus 5.5 (Claude Code) | $0.240608 | $0.1203 | 42.1 and 50.2 | 2 × 0.1203 × 600 + $2.00 = **$146.36** | about 2.6 hours |

Both projections are under the 6-hour gate, so both main runs start. The ceilings are list prices on subscription
logins, not charges.

## Amendment 2, 2026-10-20 (both main runs started; no cell read)

The owner waived the 6-hour wall-time stop ("run them", relayed 2026-10-20). Both main runs had already started under
it: the projections above (about 2.7 and 2.6 hours) were under the gate, so the waiver changes nothing that ran. Every
other stop stands as declared: an isolation violation refuses a run; the cost ceilings of amendment 1; v15's halt rule
of 3 consecutive failed cells (stricter than the 5 the relay named, and kept as declared); a failed cell is typed
missingness and never rerun.
