# housing_lemons_price_pack_v2: the v15 pack, its scan log and its controls

Built by `src/aeread_families/housing/price_pack_v2.py` exactly as `docs/families/housing/price_confirmatory_v15_plan.md`
Section 2 declares, and amendment 1 fixes the development stream at 20 worlds (15 and 5). Regenerate and compare
bytes (about 35 minutes at 3 processes):

    PYTHONPATH=src python -m aeread_families.housing.price_pack_v2 --check --processes 3

- `reports/pack.json`: every stream's seeds by stratum, its scan counts, the declared rules, and a digest of all of it
  (`sha256`).
- `tables/scan.jsonl`: every seed scanned, in order, with its status and the numbers that decided it: structure, the
  ceilings, both policies' measure-v2 nets in both arms, and the averaged headroom.
- `tables/controls.jsonl`: one row for every admitted world and arm. Each row has the ceiling, then
  `pass`, `sign_anything`, `inspect_then_sign`, `inspect_lowball` and the best-informed tenant (`pricing`), each
  played at its stream's rate under `net_realized`, `primary_v1` and `primary_v2`.

| Stream | Seeds | Scanned | Admitted (lemon / sound) | Failed the headroom screen | $0 ceiling | Structure | Over quota |
|---|---|---:|---|---:|---:|---:|---:|
| main (0.5) | 500,000–500,436 | 437 | 260 (200 / 60) | 119 | 6 | 7 | 45 |
| holdout (0.3) | 520,000–520,076 | 77 | 40 (30 / 10) | 22 | 4 | 0 | 11 |
| development (0.5) | 540,000–540,043 | 44 | 20 (15 / 5) | 15 | 2 | 0 | 7 |

No two admitted worlds are near duplicates (every listing's ask, value if sound and sound floor within $10).

Mean seat-0 net under measure v2, per world and arm ($):

| Stream | Best-informed tenant | `inspect_lowball` | `inspect_then_sign` | `sign_anything` | Ceiling |
|---|---:|---:|---:|---:|---:|
| main | 307.4 | 293.2 | 152.0 | −92.6 | 370.9 |
| holdout | 336.9 | 313.6 | 183.6 | −86.1 | 383.6 |
| development | 312.6 | 303.3 | 137.1 | −57.9 | 376.8 |

The screen guarantees at least $25 of headroom over `inspect_then_sign`, the plan's beatability baseline. It does not
guarantee that over `inspect_lowball`, the v14 reference rule, which comes within $14 of the best-informed tenant on
the main pack.
