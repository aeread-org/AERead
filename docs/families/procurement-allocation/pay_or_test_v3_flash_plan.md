# Pay or test v3: the flash models on the declared worlds (declared, descriptive)

**Status:** declared 2026-10-20, before any play, at the owner's go ("ok go"). The paper reports Procurement on one
pack, the 20 worlds of the declared test. Sol and Opus have played them; this adds Gemini 3.8 Flash and GPT-6 Luna, so
that Table 5.3, Figure 5.1, the failure classes of Section 5.2 and Figure 5.2 can all use that pack. No hypothesis is
tested here, and no model is ranked.

## What runs

- **Worlds:** `pay_or_test_v3_confirm`, the 20 declared worlds (committed in `e67df11d`).
- **Subjects:** Gemini 3.8 Flash (Google AI Studio route, reasoning minimal) and GPT-6 Luna, on version 1's pinned
  OpenRouter routes with only the profile ids changed.
- **Plays:** two a world, request seeds 87001 and 87002, under the v3 brief (`procurement_allocation_pay_or_test_v3_brief_v1`)
  that Sol and Opus played.
- **Driver:** `tools/cli_subjects/pay_or_test_v3_openrouter.py`. Version 1's controls carry over: the credit floor
  and catalog check before any run root exists, the retry policy, $0.30 a cell, and the halt rule.
- **Action schema:** version 3's actions, tightened as version 1's OpenRouter schema is. Its one residual is an
  award with null lines, which is scored as walking away.
- **Ceilings:** $2.00 (Gemini) and $1.50 (Luna). A failed cell is typed missingness and is never rerun.
- **Run tree:** the tree carrying the registry row, as every v3 run.

## Read-out

- `tools/cli_subjects/pay_or_test_v3_pilot_report.py` gives each subject's per-world share of the pay-to-best gap
  closed, with a 95% t interval over the 20 worlds, on the basis Table 5.3 uses.
- It also gives plays touching a newcomer, and the first information request.
- Failure classes come from `tools/paper/failure_taxonomy/procurement_pay_or_test_v3.py` on
  `docs/paper-case-studies-qc` (`51e9bfd3`). It was fixed before these plays, and on Sol and Opus it reproduces the
  published losses.
