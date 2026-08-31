# tau3 retail cases

[`base/`](base/) is the pinned public base split imported from tau2-bench. It
contains 114 task cases, `pins.json`, and `pilot_manifest.json`.

The importer is `src/aeread_families/tau3_retail/cases.py`; its default output
directory is this `base/` directory. The pins and manifest preserve upstream
provenance and case-set identity, so regenerated output must be reviewed as a
content change rather than a folder-only change.
