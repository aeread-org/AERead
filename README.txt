AERead working draft v15 - 18 October 2026

Current version: 15.33 (21 October 2026). The number is printed under the paper's title and in the PDF's
Subject field; it lives in source/version.json and goes up by one on every push (sync_and_push.sh refuses
another push at the same number).

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
- Abstract (2026-10-19, owner asked why it was there): the TERMS-Bench clause is removed. The reimplementation
  orders two agents only, its levels differ from the paper's for reasons Section 5.3 names, and a reference paper is
  a template, not a comparison to lead with; Section 5.3 and Table 2.1 keep it. Abstract 263 words.

New results (2026-10-19, owner: "update the paper"; coordinated with the branch session)
- Housing: v15 replaces v14 as the reported comparison (Section 5.1, Table 5.2): Gemini - Luna +48.8 [34.9, 62.7],
  A/A -5.0, both beat inspect_then_sign (+90.0, +41.2), both below inspect_lowball and the best informed tenant;
  Gates 1, 2, 3 and 5 passed, 4 partial (probe after the freeze; reasoning tiers in effect). v14's table moves to
  Table E.13 with its text; Figure 5.1's Housing panel stays v14 and is labelled so. GLM addendum A named as running.
- Data center: Table 5.4 holds both confirmatories; v2 (isolated tools, walk-away stated) +128.8 head to head,
  +23.1 firm client, P3a +22.6, P3b -0.5; gate review pending. The best informed policy turn by turn (after the runs)
  is described in Section 5.1 and Appendix C.3 (integrator $196k on v2 deal worlds; Sol captures ~20% of headroom;
  knowing the type worth $0.1k-$2.7k).
- Abstract, introduction, Sections 6 and 7, Appendices A.1, E.2, E.3 (Table E.2), E.4, F.1, H, the comparison
  table and the sources tables follow. 52 pages.
- Layout (2026-10-19, owner: "don't need new page for each new section"): the forced page breaks before
  Sections 4, 5 and 7, the references, Appendices A and H and E.7 to E.9 are removed; headings still never end a
  page. 50 pages.
- Section 5.1 Procurement (2026-10-19, owner: "no need to mention"): the sentence giving the sourcing counts (231
  projects, 341 suppliers, 9 of 28 quoting, the 51-listing screen) is removed; the next sentence now refers to "our own
  sourcing on 1688". The sources table keeps the workbook as the provenance of "most requests went unanswered".
- Results as percentages (2026-10-19, owner: dollar amounts are not immediately understandable). Tables 5.2 to 5.4 and
  their sentences now state each result as a share of that case's own reference value: Housing against what the best
  informed tenant earns in the same worlds ($307 a world on the main pack), Procurement against the best policy's value
  ($451), Data center against the value available in a deal, the joint surplus of the best agreement ($322k a world in
  v1, $309k in v2). Differences are percentage points of that value; dollar bases are in the captions. The abstract,
  introduction and Section 7 give the counterpart example as 42% and 7% of the value available.
- Section 5.2 mechanisms (2026-10-19, owner: "explain clearly the mechanism, label it is not enough"). Each large
  shortfall segment now gets its causal chain in the world's terms, with numbers from analysis_evidence/shortfall_panels:
  Procurement Gemini never tests a newcomer (recorded supplier in 24/24 worlds; $113 a world lost in the 16 where a test
  was best); Housing v14 Gemini signs settled leases on worse terms (72% of its shortfall: listing choice 52%, rent
  above the landlord's floor 31%, inspection 17%); Housing v14 Luna signs a lemon the landlord's acceptance identified
  (56 of 520 cells, about $800 each, 60% of its shortfall); Refund Flash Lite re-asks a known fact and the case ends
  (80.8 of 98.3 points) or writes method null (16.7); Data center fees and harmful agreements (Opus 29.5%). 51 pages.
- Table 5.3 floor (2026-10-19, raised by the other session): share of the best policy's value hides the decision,
  because always paying the premium already keeps 83.3%. The table now shows that floor and the share of the
  premium-to-best gap each subject closes (Sol 98.6%, Opus 92.8%, Gemini 0.0%, Luna 1.1%).
- Section 5.1 Procurement pilot (2026-10-19, owner's go via the other session): a paragraph on the harder
  version's 12-world development pilot (shared sources, quotes answered a third of the time, recorded price gaps).
  Opus paid the premium in 24 of 24 plays; Sol tested in 20 of 24 and closed 50% [27, 71] of the premium-to-best
  gap in the six option-value worlds (one-step rule 0%) and 65% [46, 83] in the six one-test-ahead worlds (one-step
  rule 70%, same per-world basis). Labelled development; no ranking; worlds differ from Table 5.3's. Source
  f4a69caf on codex/procurement-pay-or-test. 52 pages.
- Section 5.1 Procurement confirmatory (2026-10-19, owner via the other session): the harder version's paragraph now
  reports the declared test (plan e67df11d before any play, results ff65a230): on 20 fresh option-value worlds Sol
  closed 35% [18, 52] of the premium-to-best gap, p = 0.0003, where the one-step rule closes none. The claim is Sol's
  alone; Opus, a control, paid the premium in 84 of 84 plays on this version, including 20 twins at the reported
  pack's odds; no cause given. Table 5.3 unchanged.

2026-10-19 (aeread-15), Procurement replaced in Section 5.1, at the owner's request ("change 5.1 directly as
current one saturated"):
- Section 5.1 Procurement now reports the harder pack (pay_or_test_v3): shared sources, unanswered quotes,
  a source lookup, prices from the sourcing record's price gaps; admission keeps worlds where a rule that
  plans one newcomer's test pays the premium and the best policy beats paying by 10%. Worked example from
  confirmatory world myopic_pays__3 (scout sample + lookups decide a $200 sample).
- New Table 5.3 (Sol 35% [18, 52] on 20 fresh worlds, declared; pilot 50% [27, 71]; Opus 0% in 84 plays;
  exact two-newcomer rule 82% and 84%) and new Figure 5.1 (figures/plot_procurement_v3.py; inputs pinned in
  analysis_evidence/procurement_v3/SOURCES.json; PROCUREMENT_V3_FIGURE_CHECKS.json; build.py asserts the
  script, SVG and input digests). The shortfall figure is renumbered Figure 5.2.
- The earlier pack's table moved to Appendix E.4 as Table E.14 with its discussion; Appendix A.2.1 and
  Table A.6 specify the harder pack; gate lines (Section 5.1 opening, F.1) give the harder pack's verdict
  (Gate 0 passed, Gates 1-5 partial: unreviewed kernel registration, code not on main); the introduction's
  admission example and the checklist row T.10 updated; six declared analyses, not five.
- figures/plot_architecture.py rerun only to refresh source digests after the introduction edit; its SVG
  is byte-identical.
- Follow-up: four references to the earlier pack that still said Table 5.3 (tab_case_paths.tex, app_runtime.tex,
  Appendix F.2 and G) now say Table E.14; architecture source digests refreshed, SVG byte-identical.
- Section 5.1 Housing: GLM addendum A finished (df81e28c, 600/600, replay-verified); the "is running" sentence now
  gives its declared rows in points of the $307.4 best-informed value (53.9% kept; does not beat inspect_then_sign at
  98.3%, +4.5 [-4.4, +13.3]; trails Luna 8.9 and Gemini 24.8, descriptive) and a sources row.
- Section 5.1 Procurement, checked against the v3 evidence (owner asked about the new addition): (1) the worked
  example's posterior was 0.96, the figure when the dear newcomer is fully qualified; the exact v3 reference gives
  0.94 after the cheap newcomer's clean quote and a sound sample of the dear one (0.55 on the sample alone), 0.01
  after a poor sample, so the text now says 0.94 in the policy's order. (2) Table 5.3 gains the screened shortcut
  "cheapest sample first, kinds ignored" (pack.json rule_loss): 33% of the gap on the declared 20 worlds (loss
  $33.46 vs Sol's $32.51), 8% on the 6 pilot worlds; descriptive, no comparison declared. (3) Section 6's
  reference-exactness sentence described only the earlier pack; it now states the harder pack's check (six pilot
  worlds, 400 plays within 4 SE; not the 20 confirmatory worlds), per the v3 Gate 2 row (bd9b9ba9).
  The text now carries the shortcut's consequence (aeread-15's point): the declared test shows Sol takes tests
  that pay only through what they reveal, not that it reasons about shared sources; "what both subjects miss" is
  now "the headroom left lies in planning one test beyond the one in hand". Figure 5.1's shortcut row follows
  from aeread-15.
- Figure 5.1 gains the kind-blind shortcut (cheapest sample first, exact) as a gray row on the 20 declared worlds
  (33% per world, beside Sol's 35%), matching Table 5.3's column; caption updated. Script rerun; checks refreshed.
- Section 5.1 Procurement (2026-10-20, owner's go "yes add" via aeread-c0): "why Opus never tests is untested" is
  replaced by the v3.1 diagnostic, labelled as not a declared test: under a brief corrected for the four wording
  defects of P-D-29 (none says whom to test) Opus tested no newcomer in 40 plays of the declared worlds; in a no-play
  check (a newcomer's chance of being sound after a kind-mate passes or fails a sample, with and without its own
  clean quote first; myopic_pays__3 and two other worlds, each asked twice) Opus and Sol each answered 18 of 18
  within 0.05; Sol shows no change (+7.8 [-5.6, +21.2]). Sources row added (plan e7b94f91, amendments 5abf28f3 and
  16421dce, results acd0c706, branch codex/procurement-v3-brief-v31, same registry-row caveat).
- Table 5.3's twins row filled (owner: "both"): Sol on the 20 odds twins, a declared diagnostic (2fb0140a, results
  87e67702): 59% [19, 100], median 83%, one walk-away; exact shortcut 62%, two-newcomer rule 90%, one-step rule 58%.
  One sentence in Section 5.1 and a sources row.
- Twins row checked against 87e67702 (2026-10-20): the declared read-out rerun on the sealed roots reproduces
  analysis.json byte for byte; the twin pack is unchanged since e67df11d; Opus 0% in all 20. The passage's flow was
  repaired: the Sol twins sentence now names itself a diagnostic declared before its plays, the v3.1 sentence says
  "A second declared diagnostic points to why Opus never tests", and world 10's play, whose trace ends in defer
  (margin -$956), "deferred and bought nothing" instead of "walked away with no supply". Numbers unchanged.
- Procurement reported on one pack (owner: "multiple version results reported without emphasis is just confusing").
  Gemini 3.8 Flash and GPT-6 Luna played the 20 declared worlds (declared f3daae61, results 47594ab8): 0% and
  -14%, neither touching a newcomer. Table 5.3 is now four models plus the exact rules on those worlds; Figure 5.1
  shows only those worlds (and no longer clamps negative per-world shares to zero, P-T-22). Figure 5.2's
  Procurement panel, Tables E.5, E.9, E.10 and the Section 5.2 paragraph move to the same worlds through a v3
  failure taxonomy fixed before the flash plays (51e9bfd3, ea9dcfdc), copied to
  analysis_evidence/shortfall_panels/ with derive_panels.py checking every world. The pilot, the odds twins, the
  corrected brief and the comprehension check move to Appendix E.4, Table E.15.
- Appendices A-D: every symbol and constant a NotebookLM audit (notebook d526c1f3) found undefined is now defined
  where it first appears, each checked against the code: a notation key before A.1 (indicator, U(a,b), expectation,
  D per case); A.2's 0.6, 15/365, 10/365 and A(p)'s 1817 and 53.79 (derived); A.3's B, 40, 1.5, 0.14, 13/52 and 10;
  C.1's p (now p_d) and 1050; C.2's f_i and c_E; D's v_true, second gap, strays, walking away, surplus before fees;
  MOQ, E, playbook, the 58 development worlds and the cell. No number changed.
- Procurement corrections from the paper session's check of c60e6204: Luna's loss beyond paying the premium is its
  15 orders of 50 units where 55 was best (not award checks), in Section 5.1, Figure 5.1's caption and Section 5.2;
  a note in Figure 5.2's caption and Table E.10 (b) that the declared classes file $6.33 a world of that under
  information not acquired (worse terms would be $6.85 split out); the comprehension questions described as asked
  (another newcomer's sample, with and without the target's own quote).
  Then the check's notes: Section 5.2 names award checks as the rest of the three models' loss and gives Luna's
  further $6.85; Table E.15 says Opus's earlier comprehension attempts (two) were refused; the flash sources row
  carries the registry-row caveat the other v3 rows have.
- Earlier-pack leftovers from the one-pack restructure: Appendix F.4's trivial agent is now always-pay on the declared
  worlds ($51.25, Table 5.3), its fixed-rules bullet labels the earlier pack and adds the harder pack's exact scores,
  F's evidence note says where the v3 read-outs live, and the panel README's Procurement bullet describes v3.
  No earlier-pack failure-class figure is displayed anywhere (checked for P-T-23).
- Data center on one version (2026-10-20, owner's "yes" to putting Housing and Data center on one version each, as
  Procurement now is): v2 is the main-text comparison. Table 5.4 keeps v2's four primaries; v1's rows, paragraph and
  pairing table move to Appendix E.4 (new Tables E.16, E.17). Figure 5.2c, Tables E.8-E.10 and Section 5.2's
  mechanism paragraph are re-derived from v2's published bundles (461c5d93; cell tables, summaries, manifests and the
  analysis copied to analysis_evidence/campaign_refresh/datacenter_v2/ and checked against the manifests and every
  pairing's published loss leaves): Opus 83.6, Sol 140.2 $k a world over all 80 worlds, seats averaged; fees 54% and
  59%, missed deals 34% and 35% (every one a client walk-away: the firm client walked from Sol 40 times in 144
  deal-world plays and from Opus 14; as client each model walked in 26 of 72), harmful agreements 0 (v1: 29.5% of
  Opus's loss). The fee paragraph now uses v2's declared fixed-action replay (without fees Sol still loses more,
  63.1 vs 42.5); v1's exploratory replay stays in E.9, labelled v1. Intro admission count is v2's (80 of 5,436
  scanned); E.2, E.3, E.7, E.10 note, F.2, F.5 and the case-paths table name v1 and v2 apart. derive_panels.py keeps
  v1 under datacenter_v1 for Table E.17. Housing follows.
- Housing on one version (2026-10-20, same go): Section 5.2's Housing paragraphs, Figure 5.2a and Tables E.5, E.9 and
  E.10(a) now use v15 (Table 5.2's 260 main worlds; Gemini and Luna, GLM from addendum A, labelled), not v14. Classes
  from tools/paper/failure_taxonomy/housing_v15.py (v14's rules and priority order on v15's seat-0 receipts and
  primary measure, against inspect_lowball; 5522d543, counts 313d70f8 on docs/paper-case-studies-qc), copied with the
  v15 and addendum analyses to analysis_evidence/{shortfall_panels,housing_v15}/; derive_panels.py reproduces the
  published differences (51.13, 99.92; GLM R3 127.32) and keeps v14 under housing_v14. The mechanism changed: the
  largest loss for both models is dropping a known lemon its landlord prices about $1,000 below a sound floor (the
  rule signs it in all 200 lemon-favourite worlds of that arm; Gemini offered on it in 4, Luna in 7); Luna's
  reply-proved lemon fell from 60% (v14) to 22% of its shortfall. Counts checked independently from the sealed
  trajectories (same favourite, offers, bucket splits and the 187-of-200 equality).
- Appendices A-C readability and two corrections (2026-10-20, owner's "yes" to the appendix agent's drafts in
  ~/analysis/aeread-paper/appendix_readability_drafts_20261020.md; each claim re-checked against the code first).
  Corrections: B.1 note 1 said the firm counterpart's style hashes the whole world including the client's hidden
  charge; true only of development runs, both confirmatories draw it from public facts (public_style, DC-D-32; the
  signalling test used fixed `firm`). A.1 said the prompt does not state the pricing rule or cost range; that is v14's
  prompt, and v15's brief states both ($25 margin, cost $20-$80 under the ask, >$55 below proves a lemon). Also: a
  glossary (world, pack, admission, seat, cell, identity, declared, gate); A.1 explains the two landlord kinds before
  they are used; A.2's cost and A.3's C_I and C_C as term-by-term tables; data-center symbols that meant two things
  renamed (a, s -> z_pre, z_site; services sigma -> Psi; outside option m -> O_I; owed O -> omega; script seat sigma ->
  j and surplus v -> g; stand-ins' share a -> h; reader intercept a, b -> b0, b1; mu-bar defined; CC -> C_C as in
  Section 5.1); B.3 defines V, the fee is 0 on move 1, and a price-only script keeps redlining (agreement_negotiator
  move()); C.1's two compressed sentences and C.2's "V counts only future spending" rewritten. No number changed.
- Version 15.27 (2026-10-20): a version number now prints under the title (source/version.json; the sync script
  refuses a push that does not raise it). Procurement's exactness check now covers all 20 declared worlds as well as
  all 12 pilot worlds (7ab8ff12 on codex/procurement-pay-or-test); Section 6 and A.2.1 say so, and Section 6's
  earlier "six pilot worlds" was wrong (the test covers 12). Section 6 also names the data-center oracle check as
  v1's pack and says v2's 80 worlds were checked only by a 12-negotiation kernel dry run.
- Version 15.28 (2026-10-20): Appendix E.4 (after Table E.15) and F.1 report the frozen-control diagnostic for
  Procurement's Gate 1 measured headroom (plan ec078a59, results 8fec9f68): GPT-6 Luna at high reasoning tests in 26
  of 60 plays but closes -34%; 3 worlds degenerate, 18 trivial (shortcut 14, one-step 4), 2 of 20 pass; the control is
  weaker than the shortcut (P-J-09); Sol's better play beats every screened rule in 11 of 20, descriptively. Sources
  row added (with exactness 7ab8ff12 and draft PRs #294, #295). Gate 1 stays partial.
- Version 15.29 (2026-10-20, owner: "finalize v2 review, do not report v1"): Section 5.1's gate sentence states the
  Data-center v2 review (docs/families/datacenter/agreement_confirmatory_v2_qc.md, 8bdc14f9 on codex/datacenter-agreement):
  Gate 3 passed for the integrator seat (pricing and bargaining against a fixed counterpart), Gates 0, 1, 2, 4 and 5
  partial (registry row unreviewed and code not on main, as for Procurement; no frozen-control screen; client seat
  DC-D-35); v1 is no longer named there. It says the case is not a test of inference. Table 5.4's caption, Table E.3's
  row and Appendix F.1 follow; a new test plays the full-information pair through all 80 v2 worlds (loses 0).
- Version 15.30 (2026-10-20): Procurement's registration (#294, owner override RN-O-03) and code (#295) are on main,
  so Section 5.1's gate sentence, the §5.1 Procurement passage and Appendix F.1 no longer say they await review or
  are off main; they say the registration merged without the independent review, and name what keeps Gates 1-5
  partial (control, replay through the CLI and baseline receipts under way, no seed). Data center's sentence drops
  "as for Procurement". Section 5.3: the declared TERMS-Bench reproduction was built and stopped at its first check
  (FC10 0.307 vs 0.266; code on main via #296/#297), and the scripted-seat runtime is on main.
- Version 15.31 (2026-10-20): Procurement v3 now passes Gates 0, 2, 3 and 5 and is partial at 1 and 4 (qc.md 8.2 on
  main after #298, 1dd48cf5): 12 bundles replay through main's CLI, 432 of 432 receipts incl. 100 scripted-baseline
  receipts (one bundle re-checked here: 40 of 40). Section 5.1, the Procurement passage, Appendix F.1 and Table F.1
  (Gates 2 and 5) say so; the registration merged on the owner's override is still stated. Sources row added.
- Version 15.32 (2026-10-20, owner: "housing should have cli results in the table in 5.1"): Table 5.2 gains Sol 6.1
  (Codex) and Opus 5.5 (Claude Code) from Housing v15 addendum B (plan 5515349e, results add1efdb, 600/600 cells each,
  replay-verified): Sol 90.4% (lemon 85.9%), +40.9 over inspect_then_sign, -5.0 vs inspect_lowball, holdout 88.0%;
  Opus 80.4% (71.2%), +30.9, -15.0, 80.1%; Sol - Opus +10.0 points; Opus vs Gemini +1.6 [-0.3, 3.6]. Outside v15's
  contrasts. Caption, a paragraph after the GLM sentence, a sources row and Table E.3's row.
- Version 15.33 (2026-10-21): Section 5.3 states what TERMS-Bench v2 (downloaded 2026-10-21, 80 pp.) specifies for the
  fixed-concession baselines (1%/10%/30% of the remaining distance per offer) and what it leaves out (how they open
  and accept). Appendix E.4: read as a control on its two plays, Sol would pass Procurement's headroom check in only
  9 of 20 worlds, so certifying headroom needs a pack screened by a well-testing control before freezing.
