# Refund V2 1:N Pilot

This provider-free pilot evaluates one customer coordinating with intake,
policy, and payments agents. It covers 20 world seeds with one positive refund
and one denial case per seed: 40 planned and completed trajectories, with zero
operational failures.

The deterministic baseline scored transaction and coordination correctness on
every trajectory. Mean utility was zero because positive and denial fixtures
are intentionally balanced at `+2` and `-2`. The full JSON report is generated
locally at `/tmp/aeread_refund_v2_1n_pilot_20/refund_v2_1n_summary.json`.
