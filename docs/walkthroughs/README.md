# Architecture walkthroughs

- [`shared_runner_architecture_roadmap.md`](shared_runner_architecture_roadmap.md) —
  source-grounded Exchange V1 execution trace, canonical shared-runner taxonomy,
  current-to-planned architecture map, danger zones, invariants, and gated build roadmap.
- [`shared_runner_r1_validation_and_registry.md`](shared_runner_r1_validation_and_registry.md) —
  exact R1 trace from an authored Housing family mapping through strict immutable validation,
  trusted plugin admission, exact identity resolution, failure branches, and the R2/R3 boundary.
- [`shared_runner_r2_plan_resolution.md`](shared_runner_r2_plan_resolution.md) —
  exact R2 trace from reconciled R1 records through content and implementation pins, deterministic
  cell expansion, canonical plan sealing, durable publication, and the R3/R4 boundary.
- [`shared_runner_r3_phase_scheduler.md`](shared_runner_r3_phase_scheduler.md) —
  exact R3 trace through phase-graph preflight, simultaneous observation isolation, sequential
  transitions, typed invalid actions, deterministic execution IDs, and the R4 evidence boundary.
- [`shared_runner_r4_execution_and_evidence.md`](shared_runner_r4_execution_and_evidence.md) —
  complete R1-R4 trace through sealed-plan publication, explicit attempts and provider/tool
  side effects, canonical event/artifact evidence, retries, cost, and the OpenAI-ready and
  Claude-live model-call paths.
