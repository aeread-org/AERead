# Figure 5.1: shortfall by case

The main-text figure visualizes the unchanged v8 accounting estimates. The
exact-value table is now Table E.10 in Appendix E.8. Classification rules are
in E.5; descriptive intervals and distributions remain in Table E.9.

Rebuild from the draft folder:

```sh
uv run --with matplotlib python figures/plot_shortfalls.py
uv run --with markdown --with beautifulsoup4 --with pypdf python build.py
```

Outputs: `shortfall_by_case.svg` for sharp vector reuse and
`shortfall_by_case.png` for previews and slides. The SVG is also copied to
`source/figures/` so the editable Markdown's relative image link works.

`FIGURE_CHECKS.json` binds the exact input file and both images by SHA-256,
lists every plotted component and total, and records the ten component-sum
checks. The PDF builder verifies these inputs and all 44 table values.
Unrounded source amounts determine bar lengths; bar-end labels use one decimal.
No new score, interval, hypothesis test or model run was introduced.

Reading the figure:

- Each panel starts at zero and uses its own native units and scale.
- Housing uses corrected reply-conditioned v14 estimates on 260 complete main
  worlds for each of Gemini, GLM and Luna (Gemini's refused cells from the
  declared fill). GLM adds a procedure-or-format segment; its inspection cost
  (-0.2) is negative and is not drawn. The v14 brief omitted the landlord
  pricing rule, so “contrary to info” does not establish that the tenant knew
  how to interpret the reply; the paper preserves this limitation beside the
  figure and in the appendix.
- Procurement now shows all four retained development subjects: Sol 6.1 through Codex, Opus 5.5 through Claude Code, GPT-6 Luna and Gemini 3.8 Flash. All use 24 worlds and the same best-policy reference. The v11 addition changes coverage, not estimates.
- Data center uses confirmatory joint losses against the firm population,
  averaging two focal roles within each of all 60 worlds. Harmful agreements
  and missed deals are distinct; missed deals use a hatch as well as a lighter
  tone. The bar is a joint outcome of both parties, not the model's individual
  earnings. Below-walk-away signings remain a separate measure.
- Refund uses V2.1's six fixed cases, averaging 20 cells within each case.
- Colors indicate observed accounting classes, not experimentally established
  causes. These panels do not support a single cross-case model ranking.

The original v8 analysis and its documents are retained unchanged in
`analysis_evidence/shortfall_panels/`. Historical references there to Table 5.5
refer to its v8 numbering; the same numeric table is E.10 in v9.

## Figure 4.1: architecture

Rebuild: `uv run --with matplotlib python figures/plot_architecture.py`.
The vector overview connects case definitions, the shared runtime and drivers,
seat observation/action flow, sealed execution, replay and headline analysis.
Campaign QC is shown across the workflow, without claiming all gates passed.
`ARCHITECTURE_CHECKS.json` binds the paper contracts used for the labels and
both output images. It records provenance, not an independent runtime audit.
The PDF builder checks the source and figure hashes before rendering.
