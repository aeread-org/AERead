# Pay or test v3: design note

**Status:** a design note, 2026-10-19, written at the owner's request ("Procurement v3 design note") after the v2
pilot stopped at sizing ([`pay_or_test_v2_results.md`](pay_or_test_v2_results.md), P-D-27). Nothing here is declared
or run; a plan follows only after the owner picks a route.

## What went wrong in v2

The v2 pack does what it was built to do: on every world the one-step rule loses at least $10 to the best informed
policy ($30.09 a world on average), so a subject that plans past one test can show it. The subjects never reached
that decision. In 48 pilot plays Gemini 3.8 Flash never quoted or sampled a newcomer and played the pay-the-premium
rule to within half a cent; GPT-6 Luna touched a newcomer in 1 of 24 plays. Contrast P1 therefore measured whether a
subject tests at all, and its spread (Luna's one voided award alone is $39.47 of its $43.47 excess over the rule)
needs 326 to 3,464 worlds against a cap of 96.

The case is not the bottleneck; the first test is. Two things put it there: paying the premium is a safe, visible
default, and the decision the case scores (whether to test a second newcomer after the first) only exists after a
first test that a cautious subject never takes.

## Routes

| Route | What changes | Answers the v2 question? | Cost | Risk |
|---|---|---|---|---|
| **A. Subjects that test** | v2's pack, prompt and reference unchanged; the subjects are Opus 5.5 and Sol 6.1 through their CLIs, isolated as the data-center v2 plan's amendments 1 and 2 require | yes, if they take the first test: in v1 both tested in 13 of 14 worlds where testing paid | about $5 list on subscriptions, no OpenRouter; a v2 CLI driver | both may be near the ceiling as in v1 (P-D-22), which sizing would show |
| **B. First test already taken** | each world shows one newcomer with a prior sample in its record (25 units inspected, its defectives drawn from that newcomer's type); the reference conditions on it; admission is recomputed on that state, so the one-step rule still loses at least $10 | yes, directly: every play starts at the decision v2 could not reach | a new pack module and scan (about 6 minutes, as v2's), no environment edit: records already pass through untouched | a revealed failure of one kind tells the subject about the others of that kind, which is the point; the stated `same_source_probability` must make the right second move non-obvious |
| C. Make testing obviously pay | the recorded supplier is sometimes unavailable or dearer, so paying is not a safe default | partly: it raises how often subjects test, but the contrast still mixes "tests at all" with "plans past one test" | new pack | moves the question rather than answering it |
| D. Several orders a world | each world holds 3 to 5 orders in sequence; per-order loss averaged | no on its own; it cuts variance once subjects test | larger pack and longer episodes | an order's test informs the next, so orders are not independent |

Not routes: hiding the stated odds (makes testing less attractive still), and more worlds with the flash models
(their P1 SD of $54 to $177 needs hundreds to thousands of worlds for a $10 effect).

## Recommendation

**A first, then B if A fails, with D only as a variance fix.** A changes nothing in the case and costs no OpenRouter
credit, so it is the cheapest way to learn whether the v2 question is answerable by subjects that test. Its decision
rule, to be declared in an amendment of the v2 plan before any CLI play:

1. A 12-world, two-play pilot of each CLI subject on v2's pilot split (48 negotiations of each, as the v2 pilot ran).
2. Continue to a confirmatory under a new identity only if each subject quotes or samples a newcomer in at least 75%
   of the plays where the best policy tests, and the sized world count at v2's settings ($10 effect, power 0.8,
   alpha 0.05/3, 5% attrition) is at most 96.
3. Otherwise build B: same subjects, the first test given, admission on the post-reveal state, and the flash models
   as a secondary arm that now starts where v2 needed them to.

Work A needs: `pay_or_test_v2` support in `procurement_cli.py` (it plays the v1 pack and prompts today) through
`cli_isolation`, with the freeze probe sealed, and v2's report reading CLI run roots. The decision-loss reference
still cannot be a plan pin (P-D-26), so the report stays the declared measure, as in v2.

## Probe, 2026-10-19: do subjects that test take a probe worth only its option value?

Owner request: build out the correlated-information design ("a cheap preliminary test whose one-step value is below
the default while its planned value is above it") and run a probe. Measured offline first, on v2's 12 pilot worlds
(`pay_or_test_v2_pilot`), with v2's exact reference: in all 6 `myopic_pays` worlds the best first move is a $2 quote
of a newcomer, whose planned value beats paying the premium by $10 to $47 a world, while the one-step rule's best
test is worth less than paying (Q*(probe) > Q*(default) > Q1(best test)); in none of the 6 `myopic_tests` worlds does
that hold. So v2's pack already contains the design; v2 failed because its flash subjects never took a first test
(P-D-27). This probe is route A of the note above, run on the pilot worlds, development only, no claim:

- **Subjects:** Opus 5.5 through Claude Code and Sol 6.1 through Codex, isolated as the data-center v2 plan's
  amendments 1 and 2 require (`tools/cli_subjects/cli_isolation.py`, copied byte for byte), effort low, one play per
  world, v2's prompt (`procurement_allocation_pay_or_test_shared_source_v1`).
- **Read, in this order:** on the 6 criterion worlds, how often the subject's first information request is to a
  newcomer, and how often it is the reference's own best first move; then each world's decision loss against the best
  policy (v2's reference prices every action), beside the one-step rule's and the pay-the-premium rule's; the 6
  `myopic_tests` worlds as the contrast where one test ahead suffices.
- **What it decides:** if both subjects probe in most criterion worlds, v3 builds on v2's mechanism with the
  parameter changes of `pay_or_test_v3_parameters.md` and sizes a declared run on these subjects; if they pay the
  premium there too, the first test needs a stronger prompt or design before anything else.
