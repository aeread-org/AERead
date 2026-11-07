# Agreement case v2: the confirmatory analysis

The declared contrasts of `docs/families/datacenter/agreement_confirmatory_v2_plan.md` (Sections 4 and 5, amendments
1 to 3), computed once by `tools/cli_subjects/agreement_confirmatory_v2_analysis.py analyze` from the sealed receipts
of `datacenter_agreement_v2_integrator_firm` (IF), `..._head_to_head` (HH) and `..._client_firm` (CF), all published
beside this directory, and the free baselines in `agreement_admitted_v2_free_baselines`. The write-up is
`docs/families/datacenter/agreement_confirmatory_v2_results.md`.

| | Contrast | Deal worlds | Estimate | 95% interval | Holm p | Reading |
|---|---|---:|---:|---|---:|---|
| P1 | integrator vs the firm client, Codex − Opus | 72 | +23.1 | [5.4, 40.8] | 0.022 | found; not shown to reach 40 |
| P2 | head to head, Codex − Opus, seat-averaged | 72 | +128.8 | [96.8, 160.8] | 6.1e-11 | found; not shown to reach 100 |
| P3a | Codex as integrator − `price_only` | 72 | +22.6 | [8.1, 37.1] | 0.008 | found; not shown to reach 40 |
| P3b | Opus as integrator − `price_only` | 72 | −0.5 | [−17.1, 16.1] | 0.95 | not found |

`reports/analysis.json` holds every world value, the intervals at 95% and 1 − 0.05/4, the world bootstrap, the
missingness bounds (equal to the estimates: no world missing), the campaigns' status, cost and wall time, and the
secondary measures (no claim). Rebuild from the run roots:

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/agreement_confirmatory_v2_analysis.py analyze OUT.json \
      --if runs/datacenter_agreement_v2_IF --hh runs/datacenter_agreement_v2_HH --cf runs/datacenter_agreement_v2_CF
