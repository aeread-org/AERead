# housing_lemons_refusal_v2_glm53_flash

Descriptive single-route pilot of the Housing lemons world (refusal under adverse selection): one live tenant route on a frozen pack of gate-admitted worlds, with the three scripted tenant policies run through the same runner on the same pack as controls. Claim status: `development_qualification`. No winner and no model ranking may be read from this bundle.

The route fills all 6 tenant seats, so each cell is a market of that model's tenants; landlords are the scripted policy, and a lemon's landlord reserves on the sound-equivalent cost so its reply does not reveal quality (HL-D-01). Temperature 1.0.

**Incomplete pack.** The variance-pilot gate failed: 47 of 48 cells completed in the newest attempt, and `world_100021__rep_1` is typed missingness (operational failure), never a zero score. Published by the owner's decision: the owner decided on 2026-09-25 to publish rather than re-run the one cell that hung in all five campaign-root attempts (HL-O-04 to HL-O-07). Endpoints are over completed cells; a world's mean uses the seeds it completed.

- Route: `parasail_glm_53_flash` (`z-ai/glm-5.3-flash-20260826` via Parasail)
- Pack: 25 worlds from seed 100000 by the declared selection rule; 48 pilot cells, 47 completed, 1 operational failures, 0 not attempted
- Cost: $0.3823 for the pilot stage (lower_bound)
- Primary endpoint, tenant net payoff, mean over worlds: 133.950 (95% -0.420 to 271.312)
- Live minus inspect-then-sign reference: -220.211 (95% -335.955 to -103.812)
- Abstention correctness: 0.927 (95% 0.888 to 0.962)
- Cells that signed an uninspected lemon: 10 of 47

Files: `reports/design.json` (sealed design), `reports/full_trajectory.json` and `reports/variance_pilot.json` (gate summaries with every cell row), `reports/analysis.json` (the predeclared analysis), `qc/` (provider-free validation and profile admission), `tables/cells.jsonl` (live cells), `tables/scripted_controls.jsonl` (the bracket on the same pack), and `trajectories/sanitized.jsonl` (the kernel trajectory grain). `publication_manifest.json` digests every file and binds the bundle to its source receipts. Raw responses, prompts, reasoning and failure messages stay in the ignored run root.
