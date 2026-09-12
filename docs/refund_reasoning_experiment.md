# Refund reasoning experiment

`aeread.shared_runner.refund_experiment` is the Refund analogue of the
Housing reporting controller. It fixes the panel before execution, uses
`world_seed` as the independent cluster, nests repeated episodes within each
seed, and writes every planned cell as either `included` or an explicit
`excluded` operational failure. It does not silently replace failed calls.

Run a provider-free rehearsal:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund_experiment \
  --provider fake --model refund-fixed-v1 --revision 1.0.0 \
  --conditions none,low --world-seeds 41001,41002,41003 \
  --replicates 3 --output /tmp/aeread_refund_experiment
```

For a live model, replace `--provider` and `--model`, pin `--revision`, and
use a fresh output directory. The controller emits
`refund_experiment_summary.json` and `refund_experiment_report.md`. Like the
Housing report, these include the locked design, model and route evidence,
run-plan hashes, admission status, evidence and receipt coverage, paired
world-cluster analysis, bootstrap and paired-t intervals, operational failures,
retries, reasoning tokens, known and unknown costs, secondary policy and
disclosure diagnostics, a raw-evidence inventory, and claim boundaries. A
small run is an admission/rehearsal, not a confirmatory population estimate.

Use a disjoint admission panel for live measurements:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund_experiment \
  --provider arena --model deepseek-v4-flash-0731 \
  --revision deepseek-v4-flash-0731 --max-output-tokens 4096 \
  --admission-world-seeds 40001,40002,40003 \
  --world-seeds 41001,41002,41003 --replicates 3 \
  --output /tmp/aeread_refund_arena_deepseek_experiment
```

The two condition labels are part of the locked report contract. They are
reported separately and are not pooled. Provider-specific reasoning parameters
must be pinned by the provider adapter before interpreting `none` versus `low`
as a causal reasoning comparison; the current controller therefore treats
these labels as experimental metadata rather than inferring an effect from
model output alone. In particular, the current Arena adapter records but does
not transmit a provider reasoning-control parameter. Arena comparisons are
therefore explicitly marked descriptive and treatment-unverified.

## Live coverage pilot

The first 20-world Arena run is summarized in
[`evidence/refund_deepseek_arena_coverage20_2026-08-31.json`](evidence/refund_deepseek_arena_coverage20_2026-08-31.json).
It is a fixed-case instrumentation and behavioral-coverage pilot. It must not be
reported as a `none` versus `low` reasoning effect: both labels returned
reasoning tokens, 20 of 120 trajectories were operational exclusions, no
separate admission panel ran, and only eight worlds formed complete pairs.
