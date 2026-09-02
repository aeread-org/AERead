# negarena cases

Six scenarios across two upstream `NegotiationArena` games, pinned at commit
`c447fafd439a20b84cdedeb2f8a85c4fad764745`:

- [`buy_sell/`](buy_sell/) — `negarena.buy_sell.{0,1,2}`, bilateral
  price-negotiation scenarios (reference/parity anchor, thin-ZOPA, no-ZOPA).
- [`ultimatum/`](ultimatum/) — `negarena.ultimatum.{0,1,2}`, multi-round
  split-the-resource scenarios (reference, low-iteration-cap, degenerate
  endowment).

Unlike `tau3_retail/`, upstream ships no static task corpus for this family —
scenarios are constructed programmatically (`player_goals`,
`player_starting_resources`, `iterations`). AERead therefore authors this
scenario grid and owns its provenance
(`provenance.review_status="curated"`, not `"upstream_pinned"`).

The authoring module is `src/aeread_families/negarena/cases.py`; its default
output directory is this `cases/negarena/` directory. `pins.json` and
`corpus_manifest.json` preserve upstream provenance and case-set identity, so
regenerated output must be reviewed as a content change rather than a
folder-only change. See `docs/negarena_adapter_spec.md` section 1 for the
governing spec.
