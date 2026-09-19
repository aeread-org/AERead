# Phase 2 offline admission package

This package contains **zero live model observations and zero paid calls**. The
new family is not yet admitted for paid execution: no human approval has been
recorded. The exact contribution digest is in `review_manifest.json`.

Review [`phase2_plan.md`](../../../../../docs/families/procurement-allocation/phase2_plan.md)
for the measurement contract and its limits. The case files are in
`cases/procurement_allocation_phase2_v1/panel_v1/`.

- `offline_screen.json`: all 8 worlds × 24 noise seeds × 4 public policies,
  including failures of negative controls and the old classifier's actual verdicts.
- `provider_free_conformance.json`, test logs and JUnit XML: actual local validation,
  source pins and test coverage. Upstream bridge skips are recorded; this is not an
  upstream-fidelity certification.
- `contribution_contract.json`: closed action/observation schemas, resource limits,
  and content-addressed conformance. This is the contract a human must approve.
- `execution_contract.json`: fixed cases, prompts, route, seeds, gate criteria,
  economic scoring, power limitations and the new $0.45 total cap. The confirmation
  freeze will be created only after a successful operational pilot.

Recompute the bundle and source digests, offline screen, case bytes and test results:

```sh
PYTHONPATH=src python evidence/procurement_allocation/procurement_phase2_economic_epistemics_v1/qc/verify_review.py
```

The 64-episode deterministic provider test validates orchestration, budget guards,
receipt replay and the null comparison. It is not evidence about GLM or Gemini.
Paid execution must load a genuine digest-bound `human_qc_approval.json` through
`phase2_admission.load_contribution`. Test approval fixtures stay in temporary test
folders and are never admitted here.

`aeread errata` is not available on this repository revision. This offline package
and its manifest are a scoped review record, not a claim that global errata ran.
