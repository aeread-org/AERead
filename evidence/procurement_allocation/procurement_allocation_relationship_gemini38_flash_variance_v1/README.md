# procurement_allocation_relationship_gemini38_flash_variance_v1

Descriptive single-route run of the procurement repeated-sourcing worlds (`interaction.periods`, design §4): one live buyer route on the committed worlds, every seed re-sealed into the world's delivery draws, scored against the exact four-period bound with the myopic, loyal and shopping references beside it. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

- Route: `google/gemini-3.8-flash` (`google/gemini-3.8-flash-20260902` via Google AI Studio), reasoning effort low, temperature 0.0
- Seeds: 73201, 73202, 73203; worlds: 6; cells: 18, completed 18, failed 0, not attempted 0
- Cost: $0.7958 reported; 902146 input and 33933 output tokens
- Mean regret to the bound over worlds: 35.81427002 (95% world-clustered bootstrap 27.2352872 to 44.05865795)
- Mean margin against the myopic reference: -11.67677743 (95% -20.13665789 to -2.4014677)
- Periods awarded: 72 of 72; counters 0; inquiries 0; switches 2

Seeds reach the buyer only through delivery history from period two on; where the route is deterministic the seeds of a world are repeats, and the independent unit is the world (incident P-D-01). The six worlds are curated and were tuned against the admission screen; this is a development panel.

- Paired against `procurement_allocation_relationship_glm53_flash_variance_v3` (`z-ai/glm-5.3-flash`): regret delta -73.20195619 (95% -106.53406429 to -40.6552108), 18 paired cells; descriptive, no ranking.

Files: `reports/plan.json` (the frozen plan and source pins), `reports/summary.json` (every cell row and the per-world summary), `tables/cells.jsonl` (one row per cell), `tables/periods.jsonl` (one row per cell and period), `receipts/receipts.jsonl` (the receipt projection of every sealed cell), `trajectories/sanitized.jsonl` (the kernel trajectory grain), and `reports/replay.json` (the re-audit from disk). Raw prompts, observations, provider text and failure messages stay in the ignored run root.
