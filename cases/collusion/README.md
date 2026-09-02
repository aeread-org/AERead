# collusion cases

[`duopoly_pilot/`](duopoly_pilot/) is the 6-cell pilot corpus for the repeated
Bertrand-logit duopoly of Fish, Gonczarowski, and Shorrer, *Algorithmic
Collusion by Large Language Models* (arXiv 2404.00806v6). There is no
upstream code to import from -- every case's `gold_reference` (closed-form
Nash and joint-monopoly prices/profits) is computed by this adapter's own
deterministic bisection solver, never delegated to or transcribed from an
executable artifact.

The builder is `src/aeread_families/collusion/cases.py`; its default output
directory is this `duopoly_pilot/` directory. See
[`docs/collusion_adapter_spec.md`](../../docs/collusion_adapter_spec.md) for
the governing enumeration, build procedure, and stated limits. Regenerated
output must be reviewed as a content change (a solver change moves
`content_sha256`) rather than a folder-only change.

Milestones 1-3 (all landed on this branch) ship the cases, the environment
plugin (`src/aeread_families/collusion/environment.py`), the four declared
measurement leaves and five QC Gate-2 goldens
(`src/aeread_families/collusion/measurement.py`), the scripted-policy
harness (`src/aeread_families/collusion/harness.py`), and zero-provider-call
replay (`src/aeread_families/collusion/replay.py`). No live-agent (LLM) run
exists yet for this family, at any milestone (`docs/collusion_adapter_status.md`).
