# Housing reference: bounded independent checks

This package checks the representative-rent planner and demonstrates why it is not a certified full-distribution optimum. It does not change the solver, campaign values, or admission decisions.

From the AERead checkout, run:

```sh
.venv/bin/python output/pdf/aeread_working_draft_20261018_v15/analysis_evidence/housing_reference_validation/check_reference.py --source-root /Users/chenyusu/AERead-worktrees/housing-best-informed --output /tmp/housing-reference-checks.json
```

The source checkout must supply the Housing modules and their dependencies. `results.json` records the exact source and checker hashes used. The oracle itself is standard-library Python and uses `fractions.Fraction`. Only the comparison harness imports the production code. Each rerun writes the explicitly supplied output path; no campaigns or model providers are called.

The 168 fixture states are selected combinations, not a count of all reachable states. They exercise both 0.5 and 0.3 departure probabilities by temporarily setting the planner module's RATE during the check and restoring it afterward; this does not certify the separate holdout wrapper. Known-rent posterior fixtures use representative rents. Exact decimal-cent integration is of an idealized continuous uniform discount, not of Python's PRNG. The two-listing action reversal and one-listing quote-persistence examples are synthetic; neither measures losses in the published population.

Scope: support for the Bellman implementation on these bounded surrogate fixtures, plus a regression documenting full-price non-equivalence. The mathematical justification is conditional on a sufficient posterior state and the declared transitions; it is not a completed certification of the production reference against every admitted world.
