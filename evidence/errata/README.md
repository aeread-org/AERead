# Errata records

One sealed `ERR-YYYY-MM-DD-NNN.json` per finding recorded *after* the
evidence it concerns was published. Records are append-only: never edited,
never deleted; a wrong or outdated record is superseded by a new one that
names it in `superseded_by`.

Each record selects the affected evidence by identity (campaign ids, plan
digests, receipt digests, implementation-pin digests, family ids). The derived
register under `../errata_register/` and the `ERRATA.md` sidecars next to
affected bundles are regenerated from these records with
`aeread errata --write-notes`; see `docs/operations/errata.md`.
