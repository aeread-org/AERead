# steer cases

The pinned pilot corpus imported from `narunraman/STEER` (commit
`d66673c8277b9112fc5e39751524ccda6d852446`, no license file). One directory
per taxonomy branch (`utility_theory/`, `game_theory/`, `social_choice/`,
`mechanism_design/`), each holding case files for its 2 declared elements.
`pins.json` and `corpus_manifest.json` sit alongside the branch directories.

The corpus has no repo license: no question, option, or explanation text is
committed here. Every case's `payload` carries only `element`, `question_id`,
`options_count`, `source_sha256`, and the shared `pins` record. The real text
is cached outside version control at `bridges/steer-data/`, keyed by
`source_sha256`.

The importer is `src/aeread_families/steer/cases.py`; its default output
directory is this `cases/steer/` directory. Regenerating it requires the
pandas bridge (`tools/steer_bridge/`) and the pinned upstream checkout;
regenerated output must be reviewed as a content change, since `pins.json`
and `corpus_manifest.json` preserve upstream provenance and case-set
identity.

Scoring is not implemented yet -- see `docs/steer_adapter_spec.md` section 2.
