# Pay or test v3: a frozen control that tests (Gate 1, measured headroom)

Declared in `docs/families/procurement-allocation/pay_or_test_v3_control_plan.md` (ec078a59, before any play); driver
`tools/cli_subjects/pay_or_test_v3_control.py`, which imports the flash driver unchanged. Phase A: GPT-6 Luna and Gemini
3.8 Flash at reasoning effort high, one play of each of the 12 pilot worlds (seed 87101). Phase B: the selected control,
Luna-high, three plays of each of the 20 declared worlds (seeds 87201 to 87203). 84 of 84 plays completed, and each
receipt replayed in-run. OpenRouter charged $0.03 and $0.62 (Phase A) and $0.12 (Phase B). Played from the tree carrying
the registry row that awaits kernel-lane review.

- `reports/analysis.json`: the declared read-out (`pay_or_test_v3_control_analysis.py`): the selection, and per world the
  control's share at each seed, the degenerate and trivial grounds, and Sol 6.1's shares beside them.
- `reports/readout_<run>.json`: every play, priced action by action by the v3 reference.
- `reports/runs.json`: plan and summary digests, receipt digests, resolved models and charges.
