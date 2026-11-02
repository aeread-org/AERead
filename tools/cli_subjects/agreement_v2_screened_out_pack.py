"""Write the pack of the 14 worlds v2's headroom screen dropped: the v2 generator's own cases for those seeds.

    PYTHONPATH=src python tools/cli_subjects/agreement_v2_screened_out_pack.py --write
    PYTHONPATH=src python tools/cli_subjects/agreement_v2_screened_out_pack.py --check

Declared in ``docs/families/datacenter/agreement_v2_screened_out_addendum.md``. No model is called and no hashed v2 module
is edited; each case keeps its v2 case id, so a world here is the world the v2 screen looked at.
"""

from __future__ import annotations

import argparse
import json
from multiprocessing import Pool
from pathlib import Path
from typing import Any

from aeread_families.datacenter_development import agreement_admitted_pack as aap
from aeread_families.datacenter_development import agreement_admitted_pack_v2 as pv2
from aeread_families.datacenter_development import agreement_pack as ap

PACK = "agreement_v2_screened_out_v1"
SOURCE_PACK = pv2.ADMITTED.pack
PLAN = "docs/families/datacenter/agreement_v2_screened_out_addendum.md"


def dropped_seeds() -> list[tuple[int, float]]:
    """(seed, logged headroom) of every world the v2 screen refused, in scan order."""
    log = json.loads((ap.CASES_ROOT / SOURCE_PACK / "scan.json").read_text())
    status, headroom = pv2.LOG_FIELDS.index("status"), pv2.LOG_FIELDS.index("headroom")
    return [(row[0], row[headroom]) for row in log if row[status] == "headroom_under_margin"]


def one(job: tuple[int, float]) -> dict[str, Any]:
    seed, logged = job
    r = aap.screen(seed)
    raw = pv2.case_of(seed, r["world"].cw, pv2.ADMITTED)
    h = pv2.headroom(raw)
    if not h["deal"] or abs(h["headroom"] - logged) > 1e-3:
        raise RuntimeError(f"seed {seed}: headroom {h} does not match the scan log's {logged}")
    row = aap.index_row(r, raw)
    row.update(brief_version=pv2.BRIEF_VERSION, status="headroom_under_margin",
               integrator_headroom={"ceiling": h["ceiling"], "rule": h["rule"], "headroom": h["headroom"]})
    return {"raw": raw, "row": row}


def files() -> dict[str, str]:
    with Pool(8) as pool:
        built = pool.map(one, dropped_seeds())
    manifest = {
        "pack": PACK, "family_id": aap.FAMILY_ID, "family_version": aap.FAMILY_VERSION, "plan": PLAN,
        "source_pack": SOURCE_PACK, "source_generator": pv2.generator_spec(pv2.ADMITTED),
        "claim_status": "the worlds agreement_admitted_v2's headroom screen dropped; a declared addendum to the v2 confirmatory",
        "worlds": [b["row"] for b in built],
    }
    out = {f"{b['raw']['case_id'].rsplit('.', 1)[-1]}.json": aap._dump(b["raw"]) for b in built}
    out["pack.json"] = aap._dump(manifest)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root: Path = ap.CASES_ROOT / PACK
    written = files()
    if args.write:
        root.mkdir(parents=True, exist_ok=True)
        for name, text in written.items():
            (root / name).write_text(text)
    if args.check:
        wrong = [n for n, text in written.items() if (root / n).read_text() != text]
        if wrong:
            raise SystemExit(f"pack differs from its generator: {wrong}")
    print(f"{PACK}: {len(written) - 1} worlds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
