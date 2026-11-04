# Agreement v2 addendum: the declared analysis on 86 deal worlds

The contrasts of `docs/families/datacenter/agreement_v2_screened_out_addendum.md` (Section 4), computed once by
`tools/cli_subjects/agreement_v2_screened_out_analysis.py` from the sealed receipts of
`datacenter_agreement_v2_screened_out_opus` and `..._sol`, published beside this directory, and the world values of the
72 kept worlds read unchanged from `agreement_confirmatory_v2_analysis/reports/analysis.json`. The write-up is
`docs/families/datacenter/agreement_v2_screened_out_results.md`.

| | Contrast | Deal worlds | Estimate ($k) | 95% interval | p | Holm α | Reading |
|---|---|---:|---:|---|---:|---:|---|
| A1 | P3a: Sol as integrator − `price_only` | 86 | +13.3 | [0.0, 26.6] | 0.050 | 0.025 | not found |
| A2 | P3b: Opus as integrator − `price_only` | 86 | −9.2 | [−24.7, 6.3] | 0.24 | 0.05 | not found |
| A3 | P1: Sol − Opus as integrator | 86 | +22.5 | [7.1, 38.0] | 0.005 | 0.017 | found |
| P2 | head to head, carried from v2 | 72 | +128.8 | [96.8, 160.8] | 1.5e-11 | 0.0125 | found |

`reports/analysis.json` holds every world value of the 14, the 14-world and 72-world estimates (no claim), the
intervals at 95% and 1 − 0.05/4, and the world bootstrap. Rebuild from the run roots:

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_v2_screened_out_analysis.py \
      --opus runs/v2_screened_out_opus --sol runs/v2_screened_out_sol OUT.json
