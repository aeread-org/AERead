# Data-center family failure register

Every failure the family has recorded, in one append-only place, deduplicated on the sealed receipt so rebuilding it never inflates the count.

- `tables/failures.csv` is one row per incident.
- `reports/summary.json` carries the counts, the defects and the digests.
- `reports/failure_register.md` renders the summary for reading.

Rebuild with `python -m aeread_families.datacenter_development.failure_register`.
