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

This milestone ships cases and the environment plugin
(`src/aeread_families/collusion/environment.py`) only; the three declared
measurement leaves are a later milestone (spec section 2 / section 5's
milestone note).
