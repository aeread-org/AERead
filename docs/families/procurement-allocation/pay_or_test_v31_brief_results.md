# Pay or test v3 under brief v3.1: results (2026-10-19)

Plan: [pay_or_test_v31_brief_plan.md](pay_or_test_v31_brief_plan.md) (`e7b94f91`, before any play; amendments 1 and 2
before any answer was seen). Evidence: [`evidence/procurement_allocation/pay_or_test_v31_brief/`](../../../evidence/procurement_allocation/pay_or_test_v31_brief/).
A diagnostic with no claim; v3's results and the paper's Table 5.3 are unchanged.

**Correcting the brief changed neither subject, and both read the sharing rule exactly when asked. Opus can do the
inference the case needs and still never tests: what it fails at is planning to use it.**

On the 20 confirmatory worlds, two plays a world, each world the mean of its plays, paired with the sealed v3 runs:

| | Sol 6.1, v3 | Sol 6.1, v3.1 | Opus 5.5, v3 | Opus 5.5, v3.1 |
|---|---:|---:|---:|---:|
| Share of the pay-to-best gap closed | 35.3% | 43.1% | 0.0% | −6.9% |
| Change, v3.1 minus v3 (95% t interval) | | +7.8 points [−5.6, +21.2] | | −6.9 points [−21.2, +7.5] |
| Plays touching a new listing | 26 of 40 | 25 of 40 | 0 of 40 | 0 of 40 |
| Plays touching two or more new listings | 7 | 11 | 0 | 0 |
| Plays with a lookup / settling a kind | 4 / 3 | 5 / 5 | 0 / 0 | 0 / 0 |
| Comprehension check, answers correct | | 18 of 18 | | 18 of 18 |

The kind-blind shortcut closes 33.4% on these worlds.

**Readings, as declared.**
- **Opus** touched a new listing in 0 of 40 plays under v3.1 (rule: at most 2), so the brief's defects are not why it
  never tests. Its −6.9 points is one play that ordered 60 units instead of 55; every other play quoted, sampled and
  awarded the recorded supplier, as under v3. Its stated reasons mention a shared source in 4 turns under v3, each as
  risk, and in none under v3.1.
- **Sol**'s change includes zero, so no change is shown. It touched two or more new listings in 11 plays against 7;
  this was not tested.
- **Comprehension.** Both subjects answered all 18 asks within 0.05, most to four decimals (`myopic_pays__3`: 0.553,
  0.944, 0.010), so both read the rule. Opus, which reads it and never tests, fails at planning to use it, which is
  the construct the case measures; the failure is not in the brief and not in the rule.

**What else happened.**
- Opus's comprehension check was refused twice before it ran (P-O-04). The first attempt aborted on one refusal and kept
  nothing; under amendment 1 all 18 asks were refused with the same safeguards text. Two diagnostic calls outside the
  check showed the trigger was the schema's request for the model's working; amendment 2 asked for the probability
  alone, and all 18 were answered. No answer to a measured question was seen before either amendment.
- The read-out first counted stated reasons from the summary rows, which do not keep them (P-T-21); it now reads them
  from the sealed replies. Sol's `reason` field is empty in every turn; the text counted for Sol is its messages.
- Claude Code's runtime moved from 2.1.303 (v3) to 2.1.304 (v3.1) between the runs; Codex stayed at 0.162.1.

**Next.** The comprehension result moves the open question from "does Opus understand the rule" to "why does it not plan
with it". A brief that states what a test of one listing tells about another would give the answer away and change the
construct; a version of the case that wants this measured should instead vary the stake of the information, which v3's
admission screen holds small (10% to 23%).
