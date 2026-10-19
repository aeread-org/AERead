
## 2026-10-17 — paper Table 5.5 refresh

| id | defect | detection | cost | disposition |
|---|---|---|---|---|
| RES-J-05 | working draft v7 Table 5.1 labels Data-center confirmatory joint loss 126.8 / 77.5 as per deal world, but the source analysis averages all 60 worlds; the earnings contrast separately uses the 45 deal worlds | checking the per-cell decomposition and the confirmatory analysis aggregation while rebuilding Table 5.5 | one denominator mislabeled in a local review draft; no new model call | fixed in local working draft v8: Table 5.1 states all 60 worlds and labels role assignments; Table 5.5 and Appendix E.7 are checked against bundled source data; v7 is retained unchanged |
| RES-T-01 | the new offline Table 5.5 audit initially asserted the Housing arm name `responsive`; the retained campaign uses `true_cost`. A preliminary source read also used `housing_v14.json` rather than `housing_v14_taxonomy.json` | the audit stopped on its explicit arm-set assertion; the earlier read raised FileNotFoundError | local analysis stopped before emitting results; no model call or evidence mutation | corrected the input filename and checked arm labels directly from the retained evidence; the audit keeps the exact two-arm identity check |
