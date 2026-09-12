# tau3 retail pipeline proof

This bundle records one unscored route canary and a frozen five-case panel spanning the five predeclared tau3 retail pilot strata. All cases ran sequentially through the shared runner and replayed their receipts.

The bundle predates the shared-runner fix in PR #101 that accumulates every
model round in multi-round turns. Its published `total_cost_usd` is therefore
a historical lower bound and should not be interpreted as the complete cost
of the panel.
