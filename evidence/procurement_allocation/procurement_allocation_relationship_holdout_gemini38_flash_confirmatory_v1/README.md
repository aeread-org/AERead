# procurement_allocation_relationship_holdout_gemini38_flash_confirmatory_v1

Descriptive single-route run of the procurement repeated-sourcing worlds (`interaction.periods`, design §4): one live buyer route on the committed worlds, every seed re-sealed into the world's delivery draws, scored against the exact four-period bound with the myopic, loyal and shopping references beside it. Claim status: `confirmatory`. The claims are the pre-registered outcomes in `reports/confirmatory_vs_*.json` and nothing beyond them; no winner and no statement about the models in general.

- Route: `google/gemini-3.8-flash` (`google/gemini-3.8-flash-20260902` via Google AI Studio), reasoning effort low, temperature 1.0
- Seeds: 76001, 76002, 76003, 76004, 76005; worlds: 12; cells: 60, completed 60, failed 0, not attempted 0
- Cost: $2.8188 reported; 3208924 input and 117486 output tokens
- Mean regret to the bound over worlds: 32.36351596 (95% world-clustered bootstrap 27.00671792 to 37.95298903)
- Mean margin against the myopic reference: -7.33807839 (95% -12.92216195 to -2.30037362)
- Periods awarded: 240 of 240; counters 0; inquiries 8; switches 7

Seeds reach the buyer only through delivery history from period two on; where the route is deterministic the seeds of a world are repeats, and the independent unit is the world (incident P-D-01). The six worlds are curated and were tuned against the admission screen; this is a development panel.

- Paired against `procurement_allocation_relationship_holdout_glm53_flash_confirmatory_v1` (`z-ai/glm-5.3-flash`): regret delta -33.23438176 (95% -50.85606399 to -17.77858157), 60 paired cells; descriptive, no ranking.

Files: `reports/plan.json` (the frozen plan and source pins), `reports/summary.json` (every cell row and the per-world summary), `tables/cells.jsonl` (one row per cell), `tables/periods.jsonl` (one row per cell and period), `receipts/receipts.jsonl` (the receipt projection of every sealed cell), `trajectories/sanitized.jsonl` (the kernel trajectory grain), and `reports/replay.json` (the re-audit from disk). Raw prompts, observations, provider text and failure messages stay in the ignored run root.
