# tau3 retail failure register

This Tier 1 register is derived from the sealed tau3 retail attempt roots for
campaigns v14 through v18. It preserves the four earlier operational failures,
the three v18 cap exclusions, and the v18 malformed structured response. The
checkpoint is the immutable source artifact; where earlier checkpoints only
carry the generic `execution_failure` label, the register deliberately keeps
that limitation instead of inventing a more specific condition.

The v18 cap exclusions cost 0.29196660 USD in total and the malformed response
cost 0.07782174 USD. The v18 campaign continued after each typed exclusion and
completed one included case; it did not silently score the excluded cases. The
v19 attempt is also retained: its admission canary was rejected before any
billable call because `ARENA_API_KEY` was unavailable in the execution
environment.
