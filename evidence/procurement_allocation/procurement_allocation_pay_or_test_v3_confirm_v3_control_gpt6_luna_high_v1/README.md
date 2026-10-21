# procurement_allocation_pay_or_test_v3_confirm_v3_control_gpt6_luna_high_v1

Pay or test version 3, pack `pay_or_test_v3_confirm`, subject `gpt6_luna_high`, 60 plays; claim status `declared_diagnostic`. A kernel-standard bundle of the run's receipts, published so that `aeread verify-replay` can recompute every score from the sealed evidence in the local run root:

    PYTHONPATH=src:tools/cli_subjects aeread verify-replay evidence/procurement_allocation/procurement_allocation_pay_or_test_v3_confirm_v3_control_gpt6_luna_high_v1 \
        --run-root <run root of procurement_allocation_pay_or_test_v3_confirm_v3_control_gpt6_luna_high_v1> --setup pay_or_test_v3_replay:setup_for_receipt

- `reports/campaign.json`: the run's identity, plan digest, pack, prompt, model, CLI runtime or route, seeds and driver, from its sealed plan.
- `receipts/projections.jsonl`: each receipt's public projection.
- `tables/cells.jsonl`: one row a play.
- `trajectories/sanitized.jsonl`: the kernel's sanitized trajectory grain.

The run's results and declared analysis are in the read-out bundles and results notes listed in `docs/families/procurement-allocation/qc.md` section 8.2.
