# procurement_allocation_relationship_glm53_flash_variance_v3

Descriptive single-route run of the procurement repeated-sourcing worlds (`interaction.periods`, design §4): one live buyer route on the committed worlds, every seed re-sealed into the world's delivery draws, scored against the exact four-period bound with the myopic, loyal and shopping references beside it. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

- Route: `z-ai/glm-5.3-flash` (`z-ai/glm-5.3-flash-20260826` via Parasail), reasoning effort low, temperature 0.0
- Seeds: 73201, 73202, 73203; worlds: 6; cells: 18, completed 18, failed 0, not attempted 0
- Cost: $0.1978 reported; 1181601 input and 45040 output tokens
- Mean regret to the bound over worlds: 109.0162262 (95% world-clustered bootstrap 73.38036858 to 144.47898022)
- Mean margin against the myopic reference: -84.87873362 (95% -120.50345301 to -49.66875047)
- Periods awarded: 62 of 72; counters 4; inquiries 34; switches 6

Seeds reach the buyer only through delivery history from period two on; where the route is deterministic the seeds of a world are repeats, and the independent unit is the world (incident P-D-01). The six worlds are curated and were tuned against the admission screen; this is a development panel.

- Paired against `procurement_allocation_relationship_gemini38_flash_variance_v1` (`google/gemini-3.8-flash`): regret delta 73.20195619 (95% 40.6552108 to 106.53406429), 18 paired cells; descriptive, no ranking.

Files: `reports/plan.json` (the frozen plan and source pins), `reports/summary.json` (every cell row and the per-world summary), `tables/cells.jsonl` (one row per cell), `tables/periods.jsonl` (one row per cell and period), `receipts/receipts.jsonl` (the receipt projection of every sealed cell), `trajectories/sanitized.jsonl` (the kernel trajectory grain), and `reports/replay.json` (the re-audit from disk). Raw prompts, observations, provider text and failure messages stay in the ignored run root.
