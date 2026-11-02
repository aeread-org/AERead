# Matched Sol–Opus mechanism comparison

## Completed matched result

**Both runs completed 32/32 episodes.** Sol used 134 subject calls plus three preflight calls. Every request, trajectory, terminal outcome, paired input and token total passed the offline audit. These are four development worlds, not a powered model comparison.

Mean cumulative loss in the **direct-action condition**, dollars per episode:

| Development frame | Opus 5.5 | Sol 6.1 |
|---|---:|---:|
| Two unscreened worlds and their dependence twins | 46.81 | 0.00 |
| Two selected challenge worlds and their dependence twins | 11.37 | 0.49 |

### Mechanism evidence

- **Policy construction:** Sol produced the best policy in the restricted format in all eight elicitation conditions; Opus did so in five. These conditions include unprofitable cases with simple fallback policies, so 8/8 is not eight independently difficult planning successes.
- **Relative valuation:** Sol's maximum absolute error in the elicited policy's gain over buying now was **$0.0089**. Opus's was **$1.67**. Thus valuation alone did not explain Opus's larger decision losses.
- **Ranking to action:** Sol had **zero** episodes that reported a gain above $5 and immediately committed to the familiar supplier; Opus had **three**, including one given exact values. This is an observable action mismatch, not a unique diagnosis of risk preferences or internal reasoning.
- **Continuation:** Sol's direct and elicitation episodes had zero loss throughout the two unscreened worlds, including long investigations in the profitable world. In the challenge worlds, residual losses were confined to the first action.
- **Assistance can constrain a capable policy:** in the profitable correlated unscreened world, Sol lost $0 under direct/elicitation, $34.03 with a supplied policy, and $56.48 with policy plus values. Its exact-values episode faithfully followed the restricted policy. These losses must not be attributed automatically to failed execution or numeracy.

**Conclusion:** the Opus failure patterns are not universal across these two model/runtime runs. Sol demonstrates that the relevant policy construction, valuation and adaptive action are achievable on these cases. A defensible research claim should remain model- and condition-specific, and distinguish policy-format limitations from agent failures. This does not establish why Opus chose differently or generalize to other worlds, efforts, model revisions or real procurement.

### Usage and resource continuation

Codex reported **1,693,257 input tokens and 28,195 output tokens**, including preflight; dollar cost is **unreported**, not zero. Opus's $4.48 was CLI-reported usage valuation, not a verified API bill. No monetary efficiency comparison is made.

The original Codex run reached its 1.5M input-token stop after 28 completed episodes. A separately frozen resource-only extension raised that aggregate threshold to 2M to finish the same 32 cells. It reused **118 saved responses exactly** and made **16 new subject calls**. The interrupted original evidence remains intact; there were no model resamples, substitutions or changed per-call settings. The extension also retained the original overall wall-time deadline conservatively.


Open `../procurement_v3_codex_comparison.ipynb` for all paired tables and full trajectories. Original Codex protocol: `77a68746ac1057625cb361fa00c6022ffbb13933ab7f29d6991a7bfc576cf3c5`; resource-extension protocol: `55fd435096da8a43a60c1b43f5f09d2af5343863a878fce8536cba9752d6c472`.
