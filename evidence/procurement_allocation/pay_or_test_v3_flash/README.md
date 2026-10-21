# Pay or test v3: Gemini 3.8 Flash and GPT-6 Luna on the declared worlds

Declared in `docs/families/procurement-allocation/pay_or_test_v3_flash_plan.md` (`f3daae61`, before any play), driver
`tools/cli_subjects/pay_or_test_v3_openrouter.py`. Each model played the 20 declared worlds twice (seeds 87001, 87002)
under the v3 brief, through version 1's pinned OpenRouter routes. All 80 plays completed, and each receipt replayed in-run.
The read-outs re-drive every trace to the recorded margin. Charged by OpenRouter: $0.39 (Gemini) and $0.04 (Luna).
Played from the tree carrying the registry row that awaits kernel-lane review.

- `reports/readout_<model>.json`: every play, priced action by action by the v3 reference.
- `reports/runs.json`: the plan and summary digests, receipt digests, resolved models and charges.
