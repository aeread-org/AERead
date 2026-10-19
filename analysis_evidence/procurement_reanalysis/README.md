# Pay-or-test v1: verified headline reanalysis

Retrospective derivation of paper Table 5.3 and the earlier-brief comparison in Appendix E.4 from all 144 original sealed executions (96 final-brief, 48 earlier-brief). Each receipt is audited through state and score replay before parsed buyer actions and their validity are extracted. The pinned reference prices those actions; all 144 losses equal the earlier report. No model is called and no original receipt is modified.

`PYTHONPATH=src python -m aeread_families.procurement_allocation.pay_or_test_reanalysis --check` checks source pins and reconstructs the headline from the included projection. Add `--cli-runs DIR --flash-runs DIR` to audit original receipts and re-extract the projection. `DIR` is each group's parent run directory, not an individual run.

Public data includes parsed economic fields, recorded action validity, case/receipt/evidence digests and outcomes needed by this analysis. It omits free-text messages, provider responses and complete receipts. Full provenance audit still needs the retained run roots. These scores were not leaves of the historical receipts, and this analysis does not make the campaigns preregistered or qualified.
