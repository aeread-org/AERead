# AERead replication note

This note maps the formulas, rules and reported procedures of the AERead paper to their implementation: Appendices A–D first, then Appendices E–G, then Sections 1–4, 6, 7 and Appendix H. Paths are
relative to the AERead repository (https://github.com/aeread-org/AERead); line numbers refer to the revisions used
for the reported runs. It holds detail that was moved out of the paper's prose.

## Housing

Housing (`src/aeread_families/housing/`): world `environment.py`:108–241,
`lemons.py`:49–171; phases `environment.py`:408–787; expected value and stated odds
`environment.py`:41–54, 797–823; history `runner.py`:1136–1360; prompt `runner.py`:249–267 and
`price_outside_demand.py`:64–70, 163–168, 343–357; landlord `price_bargaining.py`:21–40; outside
demand `price_outside_demand.py`:54–122; references `price_reference.py`:39–147, `lemons.py`:245–316;
best-informed tenant `price_best_informed.py`:51–226; measure `price_endpoint.py`:42–109,
`price_publication.py`:42–185; pack `lemons_design.py`:231–305.

## Procurement

Procurement (`src/aeread_families/procurement_allocation/`): constants and listings `pay_or_test_case_matrix.py`:94–236; types and prior
`pay_or_test_reference.py`:39–64; margin `environment.py`:581–740; actions `environment.py`:52–62,
1377–1606; recursion `pay_or_test_reference.py`:111–225; rules 285–371; decision loss 401–460;
cells and admission `pay_or_test_case_matrix.py`:302–399; prompts `pay_or_test_prompt.py`:17–93.

## Data center

Data center (`src/aeread_families/datacenter_development/`): agreement, protocol and grading `agreement.py`:45–268; clause costs, events and
outside options `risk_allocation_contracts.py`:57–217, 299–308; constants `risk_allocation.py`:
145–148, 660–672; parsing and legality `agreement_environment.py`:48–203; negotiator
`agreement_negotiator.py`:45–254; prober `agreement_prober.py`:110–162; readers
`agreement_reader.py`:39–102; stand-ins `agreement_negotiator_check.py`:27–115; packs
`agreement_pack.py`:31–55.

## Moved from the paper's prose

- Appendix A.2: the earlier Procurement evaluation set is the pack `pay_or_test_v1`.
- Appendix A.2.1: the evaluation set reported in Section 5.1 is the pack `pay_or_test_v3`.
- Appendix B.3, item 1: the fixed style used by the signalling test is the style `firm`; the firm population is
  the style `drawn` (Table B.1).
- Appendix D.1: the corrected measure is implemented as `price_reply_posterior`.
- House terms replaced in Appendices A–D: "pack" is now "evaluation set", "admission" is "inclusion criterion",
  "cell" is "episode" (or "stratum" for the data-center case's eleven outside-option situations), "identity" is
  "frozen configuration", "declared" (of a test or analysis) is "pre-registered", "confirmatories" is "confirmatory
  runs", "development worlds" is "development set" and "brief" is "task prompt". Code and file names keep the old
  words.

## Appendices E–G

Identifiers, file paths, commit hashes and incident codes moved out of the prose of Appendices E–G
(`paper_appendix_details.md`) during the 2026-10-21 style pass, keyed by the passage they belonged to.

### E.4 Procurement
- "The earlier evaluation set": the evaluation set's identifier is `pay_or_test_v1`.

### E.5 Rules per case
- Housing: the v15 class rules are v14's, implemented in `tools/paper/failure_taxonomy/housing_v15.py` at commit 5522d543
  (Sol and Opus, addendum B, added at 2443c035).

### E.7 Shortfall panels
- The component-level intervals, distributions, per-world amounts and input digests are in
  `analysis_evidence/shortfall_panels/panels.json`; the reproduction script is
  `analysis_evidence/shortfall_panels/derive_panels.py`.

### E.9 Fee sensitivity
- The supplied analysis, its reproduced outputs, input hashes and the single redline discussed in the text are in
  `analysis_evidence/datacenter_fee_sensitivity/`.

### F.5 Agreement v1 review
- The sealed sizing record was produced by `aeread.design.sizing`.

### Appendix G. Artifacts
- Evidence bundles are under `evidence/` in the repository. Procurement's pre-registered read-outs (Table 5.3) were
  committed under `evidence/procurement_allocation/pay_or_test_v3_*` on the case's branch.
- The paper analyses (corrected Housing measure, failure taxonomy of §5.2, control contrasts of Table 5.2) are in
  `tools/paper/`.
- Headline verification: the Housing reply-conditioned analysis is `analysis_evidence/housing_reply_conditioned/` and
  the Procurement reanalysis is `analysis_evidence/procurement_reanalysis/`, run by `pay_or_test_reanalysis`.

## Sections 1–4, 6 and 7 and Appendix H

Implementation detail moved out of the paper's prose during the style pass of 21 October 2026. Paths are relative to
the AERead repository (https://github.com/aeread-org/AERead) unless stated.

### Appendix H. Runtime contract and experimental coverage

- Full record definitions, adapter inventory and review history: `technical_supplement/runtime_technical_reference.html`
  in the editable artifact package.
- Replay modes recorded on receipts: completed scored executions carry `state_and_score`; operational-failure receipts
  carry `none` and are verified as exclusions.
- Reviewer command at the October baseline:

  ```
  aeread verify-replay BUNDLE --run-root R \
    --setup MODULE:CALLABLE
  ```

- Executor digest prefixes: October `607a79ce`, September `3cd3278c`.
- Housing seat attribution: the driver-side seat router is `SeatRouterClient`; the corrected seat-0 measure is the
  `price_reply_posterior` analysis.
- Procurement decision loss: the original report replayed an `action_trace` copied into an unsealed result row through
  an unpinned `pay_or_test_reference`; the 16 October audit and recomputation is `pay_or_test_reanalysis`.

#### Table H.1 (CLI controls)

- Claude Code / Opus 5.5: kernel client `ClaudeCodePrintClient`; binary digest `97a01e5b`.
- Codex CLI / Sol 6.1: external client `CodexExecClient`; binary digest `112fae7a`; adapter digest `3f254873`.

#### Table H.2 (execution paths)

- Housing v14: October executor `607a79ce`.
- Housing CLI: October executor `607a79ce`; driver `housing_cli.py`.
- Procurement CLI: October executor `607a79ce`; driver `procurement_cli.py`.
- Procurement flash: driver `pay_or_test_openrouter.py`, digest `f5ec607c`.
- Data-center agreement: development on September executor `3cd3278c` with `agreement_cli.py`; confirmatory v1
  `agreement_confirmatory_cli.py`; confirmatory v2 `agreement_confirmatory_v2_cli.py` with isolation probes from
  `cli_isolation.py`.
- Refund V2.1: the V2 runner is `v2_runner`; published projections carry `state_and_score`; the V2 gap figures
  regenerate with `v2_gap --check`.

## Refund V2.5 calibration and release (ported from the Refund revision, 2026-10-21)

- Source: Yuchen Fang's Refund revision of working draft 15.36, its LaTeX source and his data record
  `refund_v25.json` (in the paper package at `analysis_evidence/refund_v25/`), which binds the SHA-256 digests of
  his frozen configuration, merged measurements, analysis and audit. Figure 5.3 is his original figure, built by his
  `scripts/build_refund_figures.py` from that record. `policy_seat_panel.json` holds the counts behind Figure 5.2(d)
  and Table E.10(d), and the panel derivation asserts that they equal the data record's. The per-episode records are
  in his experiment repository, not yet in AERead (issue #309).
- Bootstrap: 20,000 stratified paired template-bootstrap draws with seed 20261011.
- Release: draft PR #269 (`codex/refund-v25-shared-runner`), synced to main 1dd48cf5; documents
  `docs/families/refund/refund_v2_5_release.md` and `refund_v2_5_v71_port.md`; panels `v71_intake` and `v71_customer`;
  `python -m aeread_families.refund.v2_5_release --panel all --seed 301`.
- Payment-unit contract version 5.1: `src/aeread_families/refund/v2_5_payment_units_v51.py`.
