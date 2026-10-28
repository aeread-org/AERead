# Procurement v3 mechanism study: P0 results

**Status:** results, 2026-10-27. The code and run evidence are not in the repository yet: they sit in the maintainer's
untracked working tree under `notebooks/procurement_v3/mechanism_study/` (`PROTOCOL.md` 0.2, `p0/pilot/`,
`p0/confirm/`, analysis `p0/analyze.py`). Protocols are identified by digest: pilot `5ebdda6b…`, confirmatory
`f35aece8…`. This note records the result so it is not lost; publishing the bundles is still open.

## Readings that were revised

- [Pay or test v3](pay_or_test_v3_confirmatory_results.md) and the v3.1 brief rerun read Opus 5.5's 84/84 premium
  payments as a failure at planning. These results narrow that: on gap-bounded worlds, once Opus is asked to write and
  value a plan, it writes the best plan the format allows in 66 of 99 episodes, and a supplied best plan does no
  better than its own. It does not start planning when it acts directly, and after planning it often acts against its own
  valuation.
- Earlier assisted runs in development world 10,600,000 lost $34–$56; the supplied plan's format could not get within
  $80 of the optimum there, so part of that loss measured the format, not the agent (PM-D-01).

Opus 5.5 loses most of the available value at one step: it commits before it deliberates. Asking it to write and value a plan first removes $67 of loss per episode on 98 complete held-out worlds. Handing it the best plan the format can express adds nothing detectable beyond that: the 95% interval rules out more than about $8 either way. Handing it the plan's exact values removes a further $13, mainly because Opus otherwise buys immediately even after estimating that investigating is worth more than $5.

All four P0 items from the 2026-10-27 review are done. Model: `claude-opus-5-5`, low effort, through the Claude Code CLI (2.1.312, isolated, one process per call). Dollar figures for runs are the CLI's reported valuation, not an API invoice.

## P0-1: the supplied policy is bounded against the optimum

The restricted plan format usually cannot express the optimal policy. At the checkpoint, with B the value of buying now, V the unrestricted optimum and S the best plan the format can express (searching every newcomer as the first sample):

| 300 fresh structures | Count |
|---|---:|
| Investigation worth ≥ $5 (V − B) | 206 |
| …of which the format reaches within $5 of V | 20 |
| …of which the cheapest sample is the wrong candidate | 68 |
| Median V − S among those 206 | $19.4 |

In development world 10,600,000, correlated condition, where earlier assisted runs lost $34–$56, the format cannot get within $80 of V ($57 in its independent twin). Those losses partly measure the format, not the agent (PM-D-01).

**Fix:** P and PV now supply the best candidate over all samples, and the primary panel admits only worlds where V − B ≥ $5, S − B ≥ $5 and V − S ≤ $5. Code: `p0/assistance_gap.py`.

## P0-2: the primary claim is the stage ladder

Shared sources change investigation value in only 7 of 300 structures, and the mean correlated-minus-independent gain is $0.40. The two earlier challenge worlds (10,700,120 and 10,700,139) were picked for exactly that property, so their independent twins had zero investigation value: zero loss there could not have been otherwise. A dependence-by-assistance test cannot be powered on this generator (PM-D-02).

The primary claim is therefore where value disappears:

- **Deliberation:** direct to elicitation (D → E).
- **Policy construction:** elicitation to supplied policy (E → P).
- **Valuation:** supplied policy to policy plus values (P → PV).
- **Action selection:** whatever loss remains in PV.

Dependence is secondary. Protocol 0.2 is in `PROTOCOL.md`.

## P0-3: development variance pilot

Protocol `5ebdda6b…`. 12 gap-bounded and 12 unscreened worlds, 4 arms, 2 private draws each: 192/192 episodes completed, 555 calls replayed, $32.82.

Gap-bounded panel, world-level mean differences in loss per episode:

| Contrast | Mean | 95% CI |
|---|---:|---:|
| E − D | −$76.0 | [−118, −39] |
| P − E | +$1.3 | [−16, +18] |
| PV − P | +$27.8 | [−24, +117] |

The PV − P figure is driven by one episode. The quote showed the supplier delivers on time 55% of the time, which under the supplied policy means "fall back to the familiar supplier". Opus awarded 55 units to that supplier anyway, writing that the award "may well be void", and lost $981.

At the $5 minimum effect the protocol originally specified, these SDs would need 2,000–12,000 worlds. The confirmatory test was therefore sized at a $25 minimum effect on the two contrasts the pilot can measure. Resampling the pilot's contrasts gives 81% power for H1 at 100 single-draw worlds and over 99% for H2.

## P0-4: held-out confirmation

Protocol `f35aece8…`, frozen before any call. 100 gap-bounded worlds were screened from seed 11,000,000 (2,539 scanned), disjoint from every development range. One private draw per world, four arms. 393 of 400 scheduled episodes completed (397 started: 4 failed, 3 never started), 1,290 calls replayed, $88.95.

Seven cells are missing. One call hit the frozen $0.20 per-call cap (PM-O-02). A halt rule in my runner then mistook that cap for the campaign budget and stopped the run, costing six more cells (PM-T-01). None was rerun.

| Contrast (world-level, complete pairs) | Mean Δ loss | 95% CI | Holm p | Verdict |
|---|---:|---:|---:|---|
| **H1** E − D (98 worlds) | **−$67.14** | [−92.3, −46.7] | <0.0001 | elicitation reduces loss |
| **H2** P − E, equivalence ±$25 (97 worlds) | −$0.66 | [−8.3, +6.8] | <0.0001 | equivalent: a better plan adds nothing |
| PV − P (secondary) | −$13.31 | [−18.9, −8.3] | — | exact values reduce loss |
| PV − D (secondary) | −$81.55 | [−104.9, −62.8] | — | |

What each arm did:

| Arm (≈99 episodes each) | Mean loss | Bought immediately (% of episodes) | Plan on record shows gain > $5, then bought immediately (episodes) | Single action losing > $100 (episodes) |
|---|---:|---:|---:|---:|
| Direct | $84.72 | 64% | — | 32 |
| Elicitation | $18.34 | 28% | 25 | 2 |
| Supplied policy | $17.16 | 34% | 34 | 2 |
| Policy + values | $3.93 | 2% | 2 | 0 |

The other diagnostics:

- **Construction:** in the elicitation arm Opus wrote the best plan the format allows in 66 of 99 episodes.
- **Valuation:** its error in estimating its own plan's advantage reached $62.63.
- **The pilot's $981 commitment did not recur.**

**Missing-cell bounds.** If each missing cell is filled with the loss of buying now, or with the largest loss observed in that arm, both hypotheses still pass Holm. Under the adversarial fill of about $1,150 per cell (the most a world allows, never observed), H1 is p = 0.031 raw but fails after Holm, and H2 fails.

## What this supports

- **Confirmed (H1, H2).** On gap-bounded worlds, Opus 5.5 at low effort loses most of the value at the commit-or-investigate step when acting directly. Requiring a written, valued plan first recovers it. Policy construction is not the bottleneck on these worlds: supplying the best expressible plan does not beat Opus's own plan, with the interval ruling out effects beyond about $8. Part of the reason is that in 66 of 99 elicitation episodes Opus's own plan already was the best expressible one, so the contrast is decided by the remaining third. The ±$25 equivalence margin is wider than the elicitation arm's whole residual loss ($18.34), so the interval is the informative statement, not the equivalence verdict alone.
- **Secondary, not confirmatory.** The remaining gap closes when the exact values are supplied. With only its own estimates, Opus bought immediately in 34 of 99 supplied-policy episodes despite estimating that the plan beats buying by more than $5. With exact values it did so twice. Its own value estimates do not reliably drive its action; the supplied numbers do. This is consistent with discounting self-generated estimates. It does not identify the cause: authority, salience, accuracy and risk attitude remain confounded, which is what the P1 objective-wording diagnostic is for.

## What remains open

- One model, at one effort level, through one runtime. The Sol 6.1 replication waits for Codex credits (resetting 2026-11-01; PM-O-01).
- The panel covers only gap-bounded worlds, where the format is valid. That is 3.9% of generated structures, and it says nothing about procurement prevalence. The ladder may not transfer. In the unscreened pilot panel (12 worlds, development evidence only), E − D was −$42 with a CI spanning zero, P − E was −$21.6 [−46.5, −2.9], and PV − P was −$0.8. There the supplied plan, although format-limited, beat Opus's own plan, so construction mattered more.
- The P1 items: the objective-wording diagnostic, a neutral-deliberation control for D → E (elicitation adds both attention and computation), robustness checks, and related work.

Artifacts: `p0/pilot/` and `p0/confirm/` (inputs, requests, responses, episodes, `tables/report.json`, `tables/episodes.csv`), screens in `*/screen.json`, analysis in `p0/analyze.py`. Incident rows PM-O-01, PM-O-02, PM-D-01, PM-D-02 and PM-T-01 are in `docs/operations/incident_log.md`.
