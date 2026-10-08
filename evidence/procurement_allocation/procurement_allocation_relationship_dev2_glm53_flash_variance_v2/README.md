# procurement_allocation_relationship_dev2_glm53_flash_variance_v2

Descriptive single-route run of the procurement repeated-sourcing worlds (`interaction.periods`, design §4): one live buyer route on the committed worlds, every seed re-sealed into the world's delivery draws, scored against the exact four-period bound with the myopic, loyal and shopping references beside it. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

- Route: `z-ai/glm-5.3-flash` (`z-ai/glm-5.3-flash-20260826` via Parasail), reasoning effort low, temperature 1.0
- Seeds: 75001, 75002, 75003, 75004, 75005; worlds: 12; cells: 60, completed 59, failed 1, not attempted 0
- Cost: $0.6443 reported; 3743880 input and 188403 output tokens
- Mean regret to the bound over worlds: 86.1146588 (95% world-clustered bootstrap 68.30571088 to 104.5185515)
- Mean margin against the myopic reference: -60.13072164 (95% -78.06214179 to -42.95884771)
- Periods awarded: 212 of 236; counters 24; inquiries 90; switches 17

Seeds reach the buyer only through delivery history from period two on; where the route is deterministic the seeds of a world are repeats, and the independent unit is the world (incident P-D-01). The six worlds are curated and were tuned against the admission screen; this is a development panel.

- Paired against `procurement_allocation_relationship_dev2_gemini38_flash_variance_v2` (`google/gemini-3.8-flash`): regret delta 52.39286628 (95% 34.04983331 to 71.82909014), 59 paired cells; descriptive, no ranking.

Files: `reports/plan.json` (the frozen plan and source pins), `reports/summary.json` (every cell row and the per-world summary), `tables/cells.jsonl` (one row per cell), `tables/periods.jsonl` (one row per cell and period), `receipts/receipts.jsonl` (the receipt projection of every sealed cell), `trajectories/sanitized.jsonl` (the kernel trajectory grain), and `reports/replay.json` (the re-audit from disk). Raw prompts, observations, provider text and failure messages stay in the ignored run root.
