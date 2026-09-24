# procurement_allocation_relationship_dev2_gemini38_flash_variance_v2

Descriptive single-route run of the procurement repeated-sourcing worlds (`interaction.periods`, design §4): one live buyer route on the committed worlds, every seed re-sealed into the world's delivery draws, scored against the exact four-period bound with the myopic, loyal and shopping references beside it. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

- Route: `google/gemini-3.8-flash` (`google/gemini-3.8-flash-20260902` via Google AI Studio), reasoning effort low, temperature 1.0
- Seeds: 75001, 75002, 75003, 75004, 75005; worlds: 12; cells: 60, completed 60, failed 0, not attempted 0
- Cost: $2.8211 reported; 3171590 input and 126238 output tokens
- Mean regret to the bound over worlds: 33.72179252 (95% world-clustered bootstrap 27.46703742 to 40.11187679)
- Mean margin against the myopic reference: -7.73785537 (95% -15.0764731 to -0.23176701)
- Periods awarded: 239 of 240; counters 0; inquiries 4; switches 6

Seeds reach the buyer only through delivery history from period two on; where the route is deterministic the seeds of a world are repeats, and the independent unit is the world (incident P-D-01). The six worlds are curated and were tuned against the admission screen; this is a development panel.

- Paired against `procurement_allocation_relationship_dev2_glm53_flash_variance_v2` (`z-ai/glm-5.3-flash`): regret delta -52.39286628 (95% -71.83273274 to -34.04995419), 59 paired cells; descriptive, no ranking.

Files: `reports/plan.json` (the frozen plan and source pins), `reports/summary.json` (every cell row and the per-world summary), `tables/cells.jsonl` (one row per cell), `tables/periods.jsonl` (one row per cell and period), `receipts/receipts.jsonl` (the receipt projection of every sealed cell), `trajectories/sanitized.jsonl` (the kernel trajectory grain), and `reports/replay.json` (the re-audit from disk). Raw prompts, observations, provider text and failure messages stay in the ignored run root.
