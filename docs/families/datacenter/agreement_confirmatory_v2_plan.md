# Negotiating into an agreement: confirmatory plan, v2

**Status:** declared on 2026-10-19, before the v2 pack, its modules or any v2 cell exist. The owner approved the design
on 2026-10-18. Every `campaign_plan.json` of this identity must be later than the commit that adds this file. A
changed control is a new identity; results go in a new results note listing every departure. The first confirmatory is
[agreement_confirmatory_plan.md](agreement_confirmatory_plan.md) and its results
[agreement_confirmatory_results_2026-10.md](agreement_confirmatory_results_2026-10.md).

## 1. Why a second confirmatory, and what changes

The 2026-10-18 design review of v1 found four problems that a new identity can fix and one it cannot.

| v1 problem | Evidence | v2 |
|---|---|---|
| The client seat measures arithmetic under nearly complete information (DC-D-35) | the client's best agreement is the same for every integrator type in 36 of 60 worlds; knowing the integrator's type is worth the client 3.9 a world (median 0); own-information scripts out-earn both models in the client seat (`even` 84.3 against Codex 59.5 and Opus 28.0) | the integrator seat is primary; the client seat is secondary |
| The brief hides the client's walk-away cost, so below-walk-away signing measured arithmetic | stating it cut Opus's below-walk-away signings from 15 of 60 to 1 of 60 in development | brief v2 (`brief_version: walkaway_stated_v1`) in every world's payload; below-walk-away signing becomes a manipulation check |
| Head to head mixes the opponent into the measure | as integrator, Codex − Opus is 21 against the firm population; seat-averaged head to head it is 190 | every claim names its counterpart; the firm population carries the primary model contrast |
| No reference level between the models and the ceiling | against the firm population the integrator's own-information best reply earns 179.3, the best fixed style (`price_only`) 101.9, Codex 114.0, Opus 92.6 | a primary contrast of each model against the `price_only` rule on the same world |
| One play a world; Codex's play-to-play spread dominates | Codex's two pilot plays differ by 92 a world as integrator, Opus's by 4.6 | two plays a model a world in the primary arm; world means first |

Standing limit, stated not fixed: against the firm script the integrator's inference is nearly free (the script's first
reply reveals the client's charge; knowing it is worth 1.4 a world), so the integrator seat measures pricing and
exploitation of a fixed counterpart, not inference. A counterpart that does not reveal its type is a separate
development study, as is a client-seat redesign that makes the integrator's charge private.

## 2. Pack: `agreement_admitted_v2`

- v1's admission rules unchanged (`agreement_admitted_pack.py`, imported, not edited), plus brief v2 in the payload.
- One added screen, computed offline before any cell: the integrator seat's full-information ceiling against the firm
  population minus the `price_only` rule's earnings is at least 25 ($k) on a deal world. This is the trivial ground of
  Gate 1; it reads no subject outcome.
- Seeds scanned upward from 8,000,000, disjoint from every earlier agreement pack; quotas 27 walk, 27 trade, 26
  hand-risk-over (80 worlds). If fewer than 56 deal worlds result, the scan continues with the same generator until 56
  deal worlds exist, before any cell runs.
- The pack, its scan log, the ceiling and the free baselines are published before the freeze. A new module
  `agreement_admitted_pack_v2.py` builds it and checks that no world overlaps the v1 admitted pack, the pilot or the
  development packs.

## 3. Subjects, counterpart and arms

Subjects: Opus 5.5 through Claude Code and Sol 6.1 through Codex, reasoning effort low, no tools, prompt variant v1,
the CLI versions recorded at the freeze as part of the identity (a version change means a refreeze). The integrator's
brief is byte-identical to v1's.

| Arm | Counterpart | Plays | Negotiations | Role |
|---|---|---:|---:|---|
| Integrator vs firm | the publicly drawn firm population | 2 a model a world | 320 | primary (P1, P3a, P3b) |
| Head to head | the other model, both seatings | 1 | 160 | primary (P2) |
| Client vs firm | the firm population | 1 a model a world | 160 | secondary |

The fee is frozen at $25k a paid redline after the free opening move, as the brief states.

## 4. Primary contrasts

On deal worlds; each model's plays are averaged within a world first; differences are paired by world; two-sided, Holm
across the four at α = 0.05. Earnings are $k above the seat's outside option at true costs, the quantity each agent is
told it is judged on.

| | Contrast | Minimum effect |
|---|---|---:|
| P1 | integrator earnings against the firm population, Codex − Opus | 40 |
| P2 | head-to-head earnings, Codex − Opus, averaged over the two seats | 100 |
| P3a | Codex's integrator earnings minus the `price_only` rule's, same world, firm population | 40 |
| P3b | Opus's integrator earnings minus the `price_only` rule's, same world, firm population | 40 |

A contrast is reported as found when Holm rejects zero; it is reported as at least its minimum effect only when the
lower 95% bound clears it. "No gap of 40 or more" in P1 would need about 232 deal worlds and is not a claim this plan
can make; it is a secondary reading at most.

## 5. Secondary, descriptive

- The client seat against the firm population, both models, with DC-D-35 stated beside it.
- Below-walk-away signings per model and seat (the manipulation check of brief v2). Expected 1 to 13 of 60 for Opus,
  because 13 of v1's 27 were at a price below the stated walk-away and lose only after the client's carried costs.
- The share of the rule-to-ceiling headroom each model captures.
- Joint loss, split into allocation, missed deals and fees.
- A fixed-action fee sensitivity at $0, $12.5k and $50k, replayed on the recorded actions (no new model calls).
- Gate 1's degenerate ground: how often a model's two plays of a world are identical.

## 6. Sizing

Power 0.8 at α = 0.0125 (the first Holm step), 5% attrition, SDs from the v1 runs:

| Contrast | SD a world | Deal worlds needed |
|---|---:|---:|
| P1, two plays | 62 to 73 | 32 to 44 |
| P2 | 140.6 (brief-v2 development run) | 27 |
| P3a, P3b | about 69 | 38 to 39 |

At 72 deal worlds with two plays, P1 detects about 25 to 30. The integrator's observation and counterpart are v1's, so
no new variance pilot is needed for P1; a 12-world pilot with both seatings runs first to check the v2 brief and the
drivers end to end, and its cells are not used in the analysis.

## 7. Stops and departures prevented

- List-price and wall-time ceilings at twice the estimate (about $90 list, 6 hours), declared in the campaign plan.
- The run halts after 5 consecutive operational failures; a failed cell is typed missingness and never rerun; a
  contrast that loses more than 10% of its worlds is reported inconclusive.
- No interim looks at outcomes.
- v1's departures, each closed in advance: the CLI versions are part of the identity; the wall-time stop is declared;
  the run-plan labels are the driver's declarations; the pack module is written and committed before this plan's
  campaign plans; the sizing calculation is a committed module; pilot plays are averaged within a world before
  pairing.

## 8. Modules (nothing hashed by v1 is edited)

- `agreement_admitted_pack_v2.py`: the pack (Section 2).
- `agreement_confirmatory_v2_cli.py`: a wrapper that imports v1's driver pieces (`build_setup`, `run_cells`, `Halt`,
  `dry_run_failures`) and declares the v2 arms.
- `agreement_confirmatory_v2_analysis.py`: the analysis above, with tests on fixture data.
- The full-information ceiling and the rule baselines as a committed module (currently a review script,
  `aeread-run-backups/design-reviews-2026-10-18/datacenter/`).

Before v2 runs, two v1 Gate 5 items are closed offline: the analysis-digest check (the pinned module reproduces v1's
published `analysis.json` except for P2's label string) and the one failure receipt's verification (DC-T-22).

## 9. Cost and time

About 640 negotiations, about $45 at list price (charged to the CLI subscriptions) and about 3 hours, plus about 45
minutes of offline preparation on 8 cores. The registry row for this case (03a7faef) needs a non-author kernel review
before any bundle is published on `main`; the runs do not wait for it.

## Amendment 1, 2026-10-19: subject isolation (before the pack, the modules or any cell)

The owner's question of 2026-10-18 found that v1's CLI subjects were not equally isolated from the owner's
customizations (CLI-D-01, CLI-D-02). Claude Code under `--safe-mode` loaded no CLAUDE.md, memory, skill listing,
hook, output style or MCP server, but its context named the run's working directory
(`.../AERead-worktrees/dc-agreement`) and the account's email. Codex, under `--ignore-user-config` with v1's
disabled features, still listed 8 of the owner's skills beside its 4 built-in ones, two of them described in
benchmark and evaluation terms. Every v1 Codex-versus-Opus contrast carries that asymmetry, unmeasured.

v2 adds these controls to Section 3, through `tools/cli_subjects/cli_isolation.py` (no hashed module edited):

- **Claude Code:** `--safe-mode` as in v1, and each call in a fresh empty directory under `/private/tmp` with a
  name that carries no project word. The account email remains: it comes with the subscription login.
- **Codex:** as in v1, and each call with `HOME` and `CODEX_HOME` set to a fresh directory that holds only a link
  to the login file, so no user skill, memory or AGENTS.md can load. Codex's 4 built-in skills and its built-in
  tool definitions remain; no switch in 0.162.1 removes them, and a call that uses a tool is refused, as in v1.
- **Probe sealed at the freeze:** each CLI is asked, under the run's exact flags and with no brief, for the skills
  and tools in its context and its working directory; for Claude Code the CLI's own init record supplies tools,
  MCP servers and output style. The probes go into the campaign plan. A violation (`isolation_violations`: any tool
  but StructuredOutput, any MCP server, a non-default output style, any skill beyond Codex's built-in four, a
  working directory naming the repository or the home directory) refuses the freeze; the probe repeats before each
  arm and a violation halts the run.

Checked live on 2026-10-19 through the module: Claude Code reported only StructuredOutput, no MCP server, the
default output style and a neutral working directory (1,155 input tokens with a one-line system prompt); Codex
listed only its 4 built-in skills.

v1 and v2 therefore differ in the subjects' context as well as in brief, seat and pack. A difference between a
model's v1 and v2 behavior is not attributable to any one of these.
