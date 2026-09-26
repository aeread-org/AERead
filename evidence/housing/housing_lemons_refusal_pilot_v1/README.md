# housing_lemons_refusal_pilot_v1

Descriptive single-route pilot of the Housing lemons world (refusal under adverse selection): one live tenant route on a frozen pack of gate-admitted worlds, with the three scripted tenant policies run through the same runner on the same pack as controls. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

- Route: `google_gemini_38_flash` (`google/gemini-3.8-flash-20260902` via Google AI Studio)
- Pack: 25 worlds from seed 100000 by the declared selection rule; 48 pilot cells, 48 completed, 0 operational failures, 0 not attempted
- Cost: $4.1677 for the pilot stage (exact)
- Primary endpoint, tenant net payoff, mean over worlds: 328.546 (95% 247.961 to 405.753)
- Live minus inspect-then-sign reference: -25.615 (95% -95.384 to 23.082)
- Abstention correctness: 0.993 (95% 0.979 to 1.000)
- Cells that signed an uninspected lemon: 2 of 48

Files: `reports/design.json` (sealed design), `reports/full_trajectory.json` and `reports/variance_pilot.json` (gate summaries with every cell row), `reports/analysis.json` (the predeclared analysis), `qc/` (provider-free validation and profile admission), `tables/cells.jsonl` (live cells), `tables/scripted_controls.jsonl` (the bracket on the same pack), and `trajectories/sanitized.jsonl` (the kernel trajectory grain). `publication_manifest.json` digests every file and binds the bundle to its source receipts. Raw responses, prompts, reasoning and failure messages stay in the ignored run root.
