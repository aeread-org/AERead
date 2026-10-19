AERead working draft v15 - 18 October 2026

Based on v14 (the shareable copy, no internal codes). Restructured so the paper leads with what
distinguishes the environment. Not sent to anyone.

Changed:
- Abstract: rewritten as one argument (gap, idea, how the environment delivers it, findings,
  limits) instead of listing the seven properties; 256 words. Findings kept from the paper: $190k vs
  $26k by counterpart; Housing's gap concentrated where the favourite is a lemon; 14 of 25 defects
  invisible in any one world; the TERMS-Bench reimplementation orders two of that paper's agents
  as it reports. The full property list stays in the intro and Table 2.1.
- Introduction: the "three contributions" paragraph and the caveat paragraph are replaced by a
  numbered list of the seven properties, each with one demonstration from the paper, and a
  one-sentence caveat pointing to Section 7.
- New Figure 1.1 (figures/plot_evaluation_levels.py): the three levels of an evaluation (runtime
  hosting families; one case's population of admitted worlds; one world), linked by zoom lines
  meaning "contains", each panel labelled with the properties of its level. Data-center agreement
  as the example (Table 5.1, Section 5.1, F.2); dot pattern and score bar schematic. Replaces a
  first draft that drew the levels as a left-to-right pipeline with unexplained numbers.
- The intro list, the abstract and Table 2.1's columns are ordered by level: one world (reference,
  counterpart, typed shortfall), a case's population (generator with admission, QC), the runtime
  (recomputed scores, several activities).
- New Table 2.1 (source/comparison_table.json): the seven properties in Terminal-Bench, tau2-bench,
  GDPval, Agents' Last Exam, EconEvals, NegotiationArena, AgenticPay, TERMS-Bench and AERead. Every
  cell was read from the paper against written definitions (lower mark where borderline); each
  cell's page reference is kept in the JSON and shown as a tooltip in the HTML. TERMS-Bench has
  five of seven in full; EconEvals has a computed-optimum reference and three activities on one
  interface. The text therefore claims the combination, not each property.
- New Section 5.3 and Table 5.5: the TERMS-Bench reimplementation (three of six counterpart
  families) on the same runtime; two of the paper's agents ordered as the paper orders them; the
  reasoning-declaration harness effect (13/30 -> 2/30 reservation breaches). Sources in
  analysis_evidence/termsbench_reimplementation/ (fetched from the development branch at 8f820c5b).
- Credit: Related work and Appendix A now say the case specification follows TERMS-Bench's
  environment / protocol / counterpart-policy decomposition (citation added; v14 used it uncited).
- Section 3 and Section 4 open with the properties they deliver.
- Grounding (owner-confirmed 2026-10-18): Section 5.1 says where each case's structure comes from
  (Housing: informal rentals on platforms such as RedNote; Procurement: wholesale sourcing on 1688,
  with counts from the authors' own sourcing record, frozen in cases/procurement_grounding_v1:
  341 search-result suppliers, 236 requests to 28, 9 quoting; 51 listings screened, 1 accepted,
  20 conditional, 30 rejected; Data center: a real AI-infrastructure system-integration engagement)
  and that every parameter is set by the authors. Section 5.2 and Section 7 updated to match. An
  untracked walkthrough's "9 of 341 contacted" and yield claims were wrong and are not used.
- Section 5.3 corrected after the 2026-10-18 port review (TB-J-01, TB-D-06 to 09): the level shift
  is from four departures in our port (no stated payoff, different observation, malformed-move
  exclusion, wider geometry), not a thinner scaffold. Table 5.5 compares surplus efficiency with
  TERMS-Bench Table 16 (overlap, the three families played: 0.196 and 0.668) and states that
  GLM-5.1's values are over 12 of 15 cases.
- Title block: contact@aeread.org (email only).
- Section 4.2 states the three ways a seat is played, in prose (no table): a model through AERead's own
  harness (kernel minimal_chat/1.0: one call per action, no tools, no memory; Gemini, GLM, Luna,
  Refund, TERMS-Bench), a model through its vendor's CLI (Opus 5.5 / Claude Code, Sol 6.1 / Codex:
  one process per action, no seed/temperature/output limit), and scripted policies. Cross-path
  comparisons are named as agent-configuration comparisons. Build caption pattern now accepts
  Table 4.x. 49 pages.
- Figure 5.1 Housing panel and Table E.10(a) now show all three models (GLM 5.3 Flash added) on
  260 worlds each, with a procedure-or-format segment (GLM 5.1 a world). The figure script used to
  reject negative components, which is why GLM was absent: its inspection cost is -0.2 a world; it
  is now reported in the caption and table and not drawn. Stale "240 / 260" label fixed. Build:
  11 bars and 53 displayed means verified. Coordinated with session aeread-15 beforehand.
- Section 5.1 opens with each case's gate status instead of "None of the four cases yet passes
  Gates 1 to 5" (Data center partial at every gate, chiefly the client seat and the unbuilt
  best-informed turn policy; Housing v14 partial throughout; the reported Procurement pack fails
  Gates 1 and 3; Refund V2.5 fails Gate 3), from each family's QC profile.
- Procurement paragraph: two assumptions depart from the 1688 record by design (a premium for the
  recorded supplier; quotes always answered), from ~/analysis/aeread-paper/procurement_calibration/.
- Table 2.1 moved to the start of Section 2 with a one-sentence lead-in; at the end of the section
  its bottom rule stacked against the Section 3 heading rule.
- Section 7 rewritten as one argument: what AERead measures; three lessons from the cases; why
  they matter for deployment; the limits of the evidence (the former caveat paragraphs merged,
  every caveat kept); next steps that follow from those limits, and the conclusion.
- Housing v14 now includes Gemini's declared fill (all three models on 260 main-pack worlds):
  edited by session aeread-15, 21:10-21:20, in Table 5.2, E.4, E.5, E.9, E.10, the shortfall
  panels and Figure 5.1; recomputed by tools/paper/housing_v14_completed_panel.py on the
  paper-sections worktree. 48 pages.
- Section 7 gains a short Deployment paragraph: organizations stop agent pilots over unclear value
  and hard-to-control risk (Gartner press release, 25 June 2025), which a value score and typed
  losses address; small firms, short of staff (NFIB jobs report, 1 October 2026), leave such
  decisions to one person without specialized expertise or review. No adoption-speed claim: the
  Census Bureau's 2026 survey finds AI use higher in larger firms. 17 references (was 15).
- Table 5.1 rewritten as a plain overview (case, real setting, what the agent decides, who it
  faces, scored against). Removed: Status, Headroom and Verifiers columns and all dollar values.
  Headroom stays in each case's own units in Tables 5.2-5.4 and Figure 5.1 (a sentence under the
  table says so); verifier kinds are one sentence. Table 5.3's caption now states the best policy's
  $451 a world, the denominator of its share row, which Table 5.1 used to carry.
- Admission defined in Section 3.3 (a pre-run screen on each world, from the public world and the
  declared prior, before hidden types: simple shortcuts must fall short of the reference by a stated
  margin; reaching the reference is a separate check). Appendix E.2 now states the Data-center rule
  ($75k draft, $25k information, $75k per shortcut, $150k walk; fees excluded) and the Procurement v2
  rule ($10 per screened shortcut, pack mean one-step loss $15; 24 of 5,798), both read from the code.
  The intro, Section 5 and Table 2.1 now scope the claim: shortcut-screening admission holds in two
  cases; Housing admits on a structural condition and the reported Procurement pack had no shortcut
  screen, so AERead's Table 2.1 mark for admission is partial, by the same standard applied to
  TERMS-Bench.
- figures/ARCHITECTURE_CHECKS.json source hashes re-bound to the edited sec_opening.tex and
  sec_runtime.tex (the architecture figure itself is unchanged).

Unchanged: every number in Sections 5.1-5.2, 6 and the appendices; Figures 4.1 and 5.1; authors.
47 pages (v14: 44). Build checks: 1 case figure, 9 comparison rows, 10 bars, 44 means, 15
references, no missing links, no internal codes in the PDF text.
Not synced to the paper-sections worktree. Incident row RES-J-06 (overstated differentiators,
corrected) written to that worktree's incident log.

CLI isolation (2026-10-19, aeread-15 session)
- Table H.1 gains a "User customizations" row: Claude Code's --safe-mode kept every user customization
  out of the model's context, though the working directory and account email remained; Codex's
  --ignore-user-config still listed eight of the operator's skills beside its four built-in ones.
- Section 5.1 (after Table 5.4) states that every Sol-versus-Opus contrast carries this difference and
  that the declared second confirmatory removes it; Appendix E's CLI paragraph points to Table H.1.
- Evidence: a sealed v1 Codex request (7,735 input tokens under 0.160.0) replayed through the v1 client
  uses 7,758 tokens as v1 ran and 7,244 isolated; live probes of both CLIs in the data-center v2 plan,
  amendments 1 and 2 (branch codex/datacenter-agreement, a2a4b1cc). Incident rows CLI-D-01..03 in the
  paper-sections worktree's log.
- Section 4.2 (sec_runtime.tex, other session) states that neither CLI was fully isolated, with
  Table H.1 as reference: Claude Code in safe mode with only its working directory in context, Codex
  still listing eight of the operator's skills (not named). ARCHITECTURE_CHECKS.json re-bound.

Case cores (2026-10-19)
- Section 5.1 gives Housing, Procurement and Data center each a core of TERMS-Bench's size, in place
  of the earlier one- or two-sentence descriptions: what is hidden, what the agent chooses, one payoff
  line and one worked example (Housing: $400 listing, blind −$100 vs inspect +$175; Procurement:
  Appendix A.2's $65.90 test-vs-premium example; Data center: Appendix A.3's burn-in example,
  −41/+19/+64 by client risk charge). Every number is from Appendix A. 50 pages.

Circulation edits (2026-10-19, owner approved "yes go", after an external circulation review)
- Cover: "Research working paper · 18 October 2026 · Preliminary results; feedback and contributions welcome"
  (was "Working draft · Not for circulation").
- Abstract: one closing sentence (code open source; a new case supplies rules, worlds, reference and inherits
  runtime, replay and the QC standard). Repository is public, Apache-2.0 (github.com/aeread-org/AERead).
- Introduction: one extensibility sentence after the seven properties.
- Section 5 opening: cases framed as worked examples and starting points, pointing to Section 7.2, instead of
  "meant to grow through cases contributed by a wider community".
- Section 7 split into 7.1 "What the cases show" (the four earlier paragraphs) and 7.2 "Open research directions
  and contributions": four open questions (counterpart populations, with "none reversed in our runs"; validity
  of populations of worlds; information and judgment; new economic decisions), a ready-vs-not paragraph, then
  the earlier next-steps and conclusion paragraph. No disclosure removed. 51 pages.
