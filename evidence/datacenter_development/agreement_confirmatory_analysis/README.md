# Agreement case: the confirmatory analysis

The declared contrasts of `docs/families/datacenter/agreement_confirmatory_plan.md`, computed by
`tools/cli_subjects/agreement_confirmatory_analysis.py analyze` from the sealed receipts of
`datacenter_agreement_confirm_head_to_head_v1` (H), `..._firm_population_v1` (F) and
`..._adversarial_v1` (A), all published beside this directory. The write-up is
`docs/families/datacenter/agreement_confirmatory_results_2026-10.md`.

| | Contrast | Worlds | Estimate | 95% interval | Holm p | Reading |
|---|---|---:|---:|---|---:|---|
| P1 | head to head, Codex less Opus, seat-averaged | 45 | 190.1 | [148.0, 232.1] | 3.2e-11 | rejects 0 |
| P2 | against the firm population, Codex less Opus, seat-averaged | 45 | 26.4 | [10.5, 42.4] | 0.0017 | a gap is claimed; no gap of 50 or more |
| P3 | client signs below its walk-away point, Opus 27 vs Codex 3 of 60 | 60 | 24 discordant, all Opus | | 2.4e-7 | rejects 0 |

`reports/analysis.json` holds every world value, the intervals at 95% and 1 - 0.05/3, the world
bootstrap, the missingness bounds, the campaigns' status, cost and wall time, and the secondary
measures (no claim). Rebuild from the run roots:

    PYTHONPATH=src python tools/cli_subjects/agreement_confirmatory_analysis.py analyze \
      --h runs/datacenter_agreement_confirm_head_to_head_v1 --f runs/datacenter_agreement_confirm_firm_population_v1 \
      --a runs/datacenter_agreement_confirm_adversarial_v1 OUT.json
