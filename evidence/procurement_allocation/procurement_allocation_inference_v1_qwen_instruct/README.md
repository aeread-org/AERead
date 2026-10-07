# procurement_allocation_inference_v1_qwen_instruct

Claim status: `development_qualification`. Descriptive single-route run of the procurement inference panel (`cases/procurement_allocation_v1/inference_v1`, labeled surface): one live buyer route, Qwen3-Next 80B A3B instruct on Google, on the 18 worlds in which one visible listing attribute predicts supplier quality in a direction that differs by world and the binding risk varies unlabelled, at 2 inference seeds per world, under the strategy-scaffold prompt v3 with a 1,800-token output cap per action and a 10-action budget. 36 trajectories planned, 36 completed, 4 of them ended on an unparseable action; $0.0832. Descriptive: no winner and no model ranking.

Published 2026-10-07 from the run root `runs/procurement_allocation/inference_v1_qwen_instruct` (receipts on this machine, backed up with digests on 2026-10-07); the run was played in September 2026 as a development pilot and read in `docs/families/procurement-allocation/design_review.md` §26-29 and `docs/families/procurement-allocation/failure_analysis.md`. Those readings predate this publication and are not re-derived here.

Sanitized, digest-bound review evidence for the declared procurement allocation panel. Raw prompts, provider payloads, event logs, and replay stores remain under the ignored `runs/` tree.
