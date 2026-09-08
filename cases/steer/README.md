# steer cases

The pinned pilot corpus imported from `narunraman/STEER` (commit
`d66673c8277b9112fc5e39751524ccda6d852446`, no license file). One directory
per taxonomy branch (`utility_theory/`, `game_theory/`, `social_choice/`,
`mechanism_design/`), each holding case files for its 2 declared elements.
`pins.json` and `corpus_manifest.json` sit alongside the branch directories.

The corpus has no repo license: no question, option, or explanation text is
committed here. Every case's `payload` carries only `element`, `question_id`,
`options_count`, `source_sha256`, and the shared `pins` record. The real text
is cached outside version control at `bridges/steer-data/<element>/cases.jsonl`,
scanned linearly for a matching `question_id` at runtime (not keyed/indexed by
`source_sha256` -- `source_sha256` is the runtime integrity check against that
row's own content, recomputed from it, never the cache's lookup key).

The importer is `src/aeread_families/steer/cases.py`; its default output
directory is this `cases/steer/` directory. Regenerating it requires the
pandas bridge (`tools/steer_bridge/`) and the pinned upstream checkout;
regenerated output must be reviewed as a content change, since `pins.json`
and `corpus_manifest.json` preserve upstream provenance and case-set
identity.

Scoring is implemented: `src/aeread_families/steer/measurement.py` declares
the one `canonical_point` leaf per case (spec section 2) and
`SteerPlugin.build_scorer` wires it to the cached row; see
`tests/test_steer_goldens.py` for the five QC Gate-2 goldens that score real
scripted episodes end to end.
