# Quality control (draft section of the AERead environment paper)

**Author:** Chenyu Li. **Status:** working draft, 2026-10-13. The main-text section; the
checklist, tools, statistical controls, defect table and checklist assessment are in
[Appendix F](paper_appendix_details.md). It follows the
[benchmark QC standard](../operations/benchmark_qc.md), the
[campaign SOP](../operations/experiment_campaign_sop.md) and the
[incident log](../operations/incident_log.md). The companion section is
[Case studies](paper_case_studies.md).

---

## 6. Quality control

The defects that mattered in the four cases were properties of the distribution, the brief, the
counterpart or the analysis, and every world was individually correct when they were found: a
seat-number tie-break that decided who signed the good listing (HL-D-04), a prompt that pointed
every subject at the right supplier in half the worlds and the wrong one in the other half
(P-D-15), a hidden type tied to the pack cell so that comparisons by type compared worlds
(DC-D-33). Reading one world at a time passes all three. Quality control is therefore organised
around populations of worlds, declared analyses and recorded failures, and the same process is
the checklist a contributed case goes through.

**Gates.** Benchmark QC qualifies a case in six gates recorded in the family's QC profile: a
profile exists (0); the worlds are valid, distinct, split and leave headroom (1); actions change
the intended state and every score is rebuilt from sealed evidence (2); a better-informed policy
does better and shortcuts lose (3); the result supports the attribution it claims (4); and the
comparison was sized, frozen and executed without tuning on outcomes (5). Campaign gates qualify
one experiment on a qualified case, from a design contract to publication. Each gate is typed
`passed`, `failed`, `partial`, `not_run` or `not_applicable`, and only `passed` promotes. A
contributed case also needs closed schemas, declared resource ceilings, a provider-free
conformance report and a human approval that binds the exact contribution (Table F.1).

**The reference is played on every world.** Before a pack is frozen its reference plays every
admitted world through the real environment and verifier, with no model, and must reach its
declared result; a test on the committed pack enforces it. The Housing reference and a
full-information tenant reproduce the published values in all 600 v14 cells; Procurement's best
policy equals the environment's average over its 27 type profiles in all 24 worlds; the
data-center oracle pair loses nothing in all 116 worlds of both packs; Refund's release requires
full credit on every case. Each test is shown to fail when the reference or the grade is wrong.

**Shortcuts, statistics and declared tests.** Named shortcut policies must lose a declared
margin, worlds a public-information rule already solves are screened out, and the brief is
audited for instructions that decide the outcome. Uncertainty is computed over worlds, claims
name their counterparts, an A/A arm runs through the whole pipeline, and a pattern found by
looking back becomes a result only through a test declared before its runs. A model-driven
exploit agent is designed but not built.

**What it found.** Every failure is written down when it happens, in a machine register derived
from published evidence and a judgment log of design, operational, tooling and judgment rows that
are never deleted (48, 49, 82 and 9 rows for the four cases). Of the 19 defects that changed a
case's design, 12 were invisible in any single world, and the 7 that were visible were found by
reading code or sealed bytes, or by tracing a single case, not by playing a panel (Table F.5).
The same checks corrected statements of our own while this paper was written (P-J-05, HL-J-12).

**Where it falls short.**

- Each current design has a typed status per gate, and none is qualified: Housing v14 is
  `partial`; Procurement's pay-or-test pack fails Gates 1 and 3, because a rule reading only what
  the buyer sees reaches the best policy to within $0.06 a world; the data-center agreement fails
  Gate 1, because its packs are not admitted by its own rules; Refund fails Gate 3 for want of a
  lower control.
- Only Housing ran a declared confirmatory campaign.
- No practitioner has set or reviewed the prices, fees and odds, and no human has played.
- Contributed cases cannot yet be admitted without the maintainers: trusted conformance runs,
  enforced resource ceilings and authenticated approval remain open.

### References

- [ABC] Zhu, Y., et al. *Establishing Best Practices for Building Rigorous Agentic Benchmarks.* arXiv:2507.02825, 2025.

### Sources for the numbers in this section

| Claim | Source |
|---|---|
| Gate definitions, sampling-plan table, reliability formula, counterpart scope, A/A arm | the benchmark QC standard and campaign SOP; the newest rule text on branch `codex/methods-design` (draft PR #288), whose `aeread.design` package computes Table 6.3 |
| Rows in §6.0, Tables 6.1 and @5 | the incident log on branches `codex/housing-lemons-outside-demand`, `codex/procurement-pay-or-test` and `codex/datacenter-agreement`; the procurement and data-center QC profiles |
| Table 6.4 | row ids carrying each prefix, collected from `docs/operations/incident_log.md` on every remote branch, 2026-10-13 |
| Reference checks (§6.2) | Housing case contract (v14 branch), `price_reference.py`; `tests/test_procurement_pay_or_test.py` on branch `codex/procurement-pay-or-test`; the agreement controls run on branch `codex/datacenter-agreement` |
| Data-center measurement facts (§6.5) | `agreement_results_2026-10.md` on branch `codex/datacenter-agreement`, section "What the runs showed about measurement" |
| Summary-setting check | one-pager `housing_summary_on_off_experiment.pdf`, run root `summary_experiment_20261009_v2` |
| Examiner checklist counts | the Examiner's triage build of 2026-10-13 (private repository, branch `qc-triage`) |
| Table 6.5 items | [ABC], Figures 2 to 4 |
