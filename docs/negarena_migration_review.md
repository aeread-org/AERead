Source: independent adversarial review, delivered verbatim to this migration for
disposition. Each finding re-verified against the code directly before any action was taken.

--- BEGIN REVIEW ---
1. `src/aeread_families/negarena/measurement.py:508-510,539-548` — The scorer accepts an independent `evidence_refs` argument and propagates it instead of using `scoring_input.evidence_refs`. Calling it with populated scoring input but omitting the keyword produces both leaves with empty provenance; passing unrelated refs fabricates provenance. This violates the requirement that provenance equal `FamilyScoringInput.evidence_refs` verbatim.

2. `tests/test_shared_runner_scoring_contract.py:1492-1499,2350-2352,2710-2713,2720-2749` — NegArena is counted as enrolled unconditionally, but its only behavioral protocol test skips when the external bridge is unavailable. Consequently, a normal run without the bridge can pass catalog closure while never checking NegArena's returned leaf set, determinism, provenance, or terminal-state isolation. The separate opt-in skip gate does not make this protocol coverage unconditional.

FINDINGS: 2
--- END REVIEW ---
