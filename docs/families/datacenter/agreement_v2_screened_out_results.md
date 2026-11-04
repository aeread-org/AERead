# Agreement v2 addendum: results on the 14 worlds the headroom screen dropped

Declared in [`agreement_v2_screened_out_addendum.md`](agreement_v2_screened_out_addendum.md) (0bbeaf1c) before any
call. Computed once by `tools/cli_subjects/agreement_v2_screened_out_analysis.py` from the two campaigns' sealed
receipts and the published v2 world values; the record is
`evidence/datacenter_development/agreement_v2_screened_out_analysis/reports/analysis.json`.

**Section 4's reading applies its second branch: A1 is not found, so the published P3a finding depends on the
screen.** On the 86 deal worlds Sol's lead over `price_only` is +13.3 [+0.0, +26.6] ($k a deal world), p 0.0496,
above its Holm threshold of 0.025. On the 14 dropped worlds both subjects earn less than the rule.

| Contrast ($k a deal world, 95% interval) | 72 kept (published) | 14 dropped (new) | 86 (declared) | Holm |
|---|---:|---:|---:|---|
| A1, P3a: Sol − `price_only` | +22.6 [8.1, 37.1] | −34.6 [−55.5, −13.8] | +13.3 [0.0, 26.6], p 0.050 | not found |
| A2, P3b: Opus − `price_only` | −0.5 [−17.1, 16.1] | −54.2 [−92.5, −15.8] | −9.2 [−24.7, 6.3], p 0.24 | not found |
| A3, P1: Sol − Opus | +23.1 [5.4, 40.8] | +19.5 [−11.5, 50.5] | +22.5 [7.1, 38.0], p 0.005 | found |
| P2, head to head (carried) | +128.8 | | | found |

On the 14 worlds the rule earns $145.2k, Sol $110.5k and Opus $91.0k a deal world. None of A1 to A3 is shown to
reach its minimum effect of 40. The 14-world and 72-world rows are reported without a claim, as declared.

## Runs

| Campaign | Plan | Negotiations | Replayed | List price | Wall |
|---|---|---:|---:|---:|---:|
| `datacenter_agreement_v2_screened_out_dry` (scripted, no model) | | 28 | 28 | $0 | |
| `datacenter_agreement_v2_screened_out_opus` (Claude Code 2.1.316) | 54e14e6c9cbb | 28 | 28 | $5.11 (ceiling $4.70) | 9.1 min |
| `datacenter_agreement_v2_screened_out_sol` (Codex 0.166.0) | b1f49548c2e3 | 28 | 28 | $1.53 (ceiling $2.44) | 11.3 min |

Every negotiation is valid; none is missing. Replay ran through the main command line with
`--setup agreement_v2_screened_out_replay:setup_for_receipt`. Opus's overrun is in-flight negotiations finishing after
the ceiling stop, which only blocks new starts; its last start came at $4.10 (DC-O-24). Sol froze after Codex's usage
limit reset (DC-O-23).

## Comparability with the 72

The 14 worlds were played two weeks after the 72 under newer CLI versions, a difference the plan declared and cannot
separate from the worlds.

| Per call, arm IF | v2 (72 + 8 worlds) | Addendum (14 worlds) |
|---|---:|---:|
| Sol: output tokens, mean | 678 | 662 |
| Sol: reasoning tokens, mean | 579 | 564 |
| Sol: seconds | 26.9 | 32.7 |
| Opus: output tokens, mean | 874 | 2,538 |
| Opus: seconds | 13.8 | 29.8 |

Sol's play is comparable: the same output and reasoning per call, with slower responses. Opus's is not shown to be:
its output per call rose 2.9 times with the same model identifier and effort, and the v2 worlds do not explain it
(DC-O-24). A2 and A3 carry this confound; A1, which the reading turns on, does not.

## What this changes

- The paper reports that Sol's published lead over the price-only rule depends on the screen, with A1's estimate
  beside it.
- Gate 3 for the integrator seat is re-read: the best-informed integrator still beats every scripted shortcut and
  the models still separate (A3), but on the unscreened 86 worlds neither model is shown to beat the price-only
  rule, and on the 14 the rule beats both. Gate 3 becomes partial.
- P1, P2 and the sealed v2 bundles are unchanged.
