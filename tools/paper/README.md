# Paper analyses

Scripts behind numbers in the environment paper's §5 and its appendices that are not produced by a
case's own derived analysis. Each is read-only with respect to its inputs and writes beside itself.
`run_all.sh` rebuilds the first two; its header lists the inputs.

| Folder or file | Produces | Inputs |
|---|---|---|
| `hl_d_07/` | the HL-D-07 rescoring of Housing v14 (`hl_d_07_results.json`); superseded for later use by `price_reply_posterior` and the derived analysis `evidence/housing/housing_lemons_price_v14_reply_conditioned/` on `codex/housing-lemons-outside-demand`, which reproduce it | sealed v14 run roots |
| `failure_taxonomy/` | Table 5.5 and Appendix E.5 (`summary.md`, `taxonomy.json`, per-case JSON); class rules in `definitions.md` | Housing v14 and procurement pay-or-test run roots (sealed, not yet published as bundles); the published data-center agreement bundles; the published Refund V2.1 gap bundle |
| `housing_controls_v14.py` | Table 5.2, model minus the inspect-then-sign tenant under both measures (`housing_controls_v14.json`) | published tables only |

Each class's amounts sum to the published shortfall of its case (checked in every script); the
declared-measure control contrasts reproduce the controls bundle. Two inputs are sealed run roots
rather than published bundles; until they are published, those numbers can be checked against the
run roots but not independently from `evidence/`.
