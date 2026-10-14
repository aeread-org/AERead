# housing_lemons_refusal_v2_gemini38_flash

Descriptive single-route pilot of the Housing lemons world (refusal under adverse selection): one live tenant route on a frozen pack of gate-admitted worlds, with the three scripted tenant policies run through the same runner on the same pack as controls. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

The route fills all 6 tenant seats, so each cell is a market of that model's tenants; landlords are the scripted policy, and a lemon's landlord reserves on the sound-equivalent cost so its reply does not reveal quality (HL-D-01). Temperature 1.0.

- Route: `google_gemini_38_flash` (`google/gemini-3.8-flash-20260902` via Google AI Studio)
- Pack: 25 worlds from seed 100000 by the declared selection rule; 48 pilot cells, 48 completed, 0 operational failures, 0 not attempted
- Cost: $4.1748 for the pilot stage (exact)
- Primary endpoint, tenant net payoff, mean over worlds: 327.834 (95% 248.775 to 405.352)
- Live minus inspect-then-sign reference: -26.327 (95% -93.529 to 21.860)
- Abstention correctness: 1.000 (95% 1.000 to 1.000)
- Cells that signed an uninspected lemon: 2 of 48

Files: `reports/design.json` (sealed design), `reports/full_trajectory.json` and `reports/variance_pilot.json` (gate summaries with every cell row), `reports/analysis.json` (the predeclared analysis), `qc/` (provider-free validation and profile admission), `tables/cells.jsonl` (live cells), `tables/scripted_controls.jsonl` (the bracket on the same pack), and `trajectories/sanitized.jsonl` (the kernel trajectory grain). `publication_manifest.json` digests every file and binds the bundle to its source receipts. Raw responses, prompts, reasoning and failure messages stay in the ignored run root.
