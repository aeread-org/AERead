# tau3 retail failure register

This Tier 1 register is derived from the sealed tau3 retail attempt roots for
campaigns v14 through v19. It preserves the four earlier operational failures,
the three v18 cap exclusions, and the five v19 malformed structured responses.
The checkpoint is the immutable source artifact; where earlier checkpoints
only carry the generic `execution_failure` label, the register deliberately
keeps that limitation instead of inventing a more specific condition.

The v18 cap exclusions cost 0.29196660 USD in total and the malformed response
cost 0.07782174 USD. The v19 panel's five malformed-response exclusions cost
0.04093374 USD in sealed successful provider rounds, plus a 0.00028088 USD
admission canary. The v19 campaign continued after each typed exclusion and did
not silently score the excluded cases. The v19 checkpoint records use the
`v19-paid4` run root, where the configured Arena credential admitted the route.
