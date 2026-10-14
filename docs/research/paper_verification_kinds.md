# Kinds of verifier (draft text for the paper's verification section, §4)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. Moved out of the case-study section,
which now refers to it; it describes the runner's measurement layer and belongs with the
earlier sections of the paper. It restates the repository's
[verifier taxonomy](verifier_taxonomy.md) under plain names.

---

A verifier compares what happened with something. We classify a verifier by what it compares
against, because that decides what a score can claim and how the verifier itself must be checked:

- **Answer.** The outcome is compared with an answer key: did the resolution match? The key must
  be shown correct.
- **Rule.** The outcome or the path is checked against declared rules: was a rule broken, and how
  often? The rules must be stated to the subject.
- **Value.** The outcome is priced in the case's own units against the best policy or a bound:
  how many dollars short? The reference must agree with the environment.
- **Relative.** The outcome is compared with another agent or a population of them: how much more
  did it keep than its counterpart? A claim covers only the counterparts named.
- **Rubric.** A rater scores the artifact against a rubric. The rater must be calibrated against
  people.

Two labels go on every check. Its **output** is pass or fail, a count, or an amount. Its
**scope** is the outcome or the path that led to it; a play can reach the right outcome by a
path the case forbids, and a case says which it scores. The five kinds are the repository's
taxonomy (canonical reference, rule and constraint, objective reference, comparative, rater and
judge); a case keeps its checks as a vector, and a rubric score is reported beside computed ones,
never folded into them.
