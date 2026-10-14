# Pay or test v2: results

**Status:** in progress, 2026-10-14. The campaign follows
[`pay_or_test_v2_confirmatory_plan.md`](pay_or_test_v2_confirmatory_plan.md);
this note is written as each step finishes, and departures from the plan are
listed at the end.

## Gate (step 3)

One world per subject, the pilot pack's first in its own order
(`myopic_pays__tight__1`), request seed 87001, through
`tools/cli_subjects/pay_or_test_v2_openrouter.py` (commit 9f5adc81).

| Subject | Identity | Status | Actions | Decision loss | Cost | Offline replay |
|---|---|---|---:|---:|---:|---|
| Gemini 3.8 Flash | `..._gemini38_flash_gate_v1` | completed | 3 | $16.3 | $0.0120 | verified, `state_and_score` |
| GPT-6 Luna | `..._gpt6_luna_gate_v1` | completed | 3 | $16.3 | $0.0009 | verified, `state_and_score` |

Both quoted and sampled the recorded supplier and awarded it, which is what the
one-step rule does in this cell; its exact expected loss here is $16.28. The
gate shows the route, the schema and the replay work; it is not a result.
