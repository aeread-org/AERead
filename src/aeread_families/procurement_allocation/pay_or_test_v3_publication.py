"""Publish a pay-or-test version 3 run root as a kernel-standard bundle, for ``aeread verify-replay``.

    PYTHONPATH=src python -m aeread_families.procurement_allocation.pay_or_test_v3_publication RUN_ROOT [RUN_ROOT ...]

Each run root (a CLI subject's, an OpenRouter model's or the scripted baselines') becomes
``evidence/procurement_allocation/<campaign_id>/``:

- ``reports/campaign.json``: what the run was, read from its sealed ``model_plan.json``: identity, plan digest, pack,
  prompt, model, the CLI runtime or the OpenRouter route, request seeds or replicates, claim status and scope, and the
  driver that made it. ``tools/cli_subjects/pay_or_test_v3_replay.py`` rebuilds a receipt's evaluation setup from it.
- ``receipts/projections.jsonl``: each receipt's public projection (``publication.receipt_projection``).
- ``tables/cells.jsonl``: one row a play: case, replicate or request seed, status, decision, termination, margin,
  receipt digest, and the run-plan digest with the implementation pins the receipt was sealed under, so a reader can
  rebuild each receipt's plan from current source without the run root.
- ``trajectories/sanitized.jsonl``: the kernel trajectory grain (``publish_trajectories``).
- ``README.md`` and the kernel-sealed ``publication_manifest.json``.

The run evidence stays local, as every bundle's privacy boundary says; ``aeread verify-replay`` reads it from the run
root. The read-out directories published earlier (``pay_or_test_v3_{probe,pilot,confirmatory,...}``) are unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.publication import (
    assert_public_payload,
    atomic_publish,
    receipt_projection,
    seal_publication_manifest,
)
from aeread.shared_runner.run.publish_trajectories import publish_trajectory_grain
from aeread.shared_runner.run.resolver import canonical_json_bytes

REPOSITORY = Path(__file__).resolve().parents[3]
EVIDENCE = REPOSITORY / "evidence" / "procurement_allocation"
CAMPAIGN_SCHEMA = "aeread.procurement_pay_or_test_v3_campaign/0.1"
PUBLISHER_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
PRIVACY_BOUNDARY = {
    "included": "the run's identity and plan digest, each receipt's public projection, one row a play, and the kernel's "
                "sanitized trajectory grain",
    "excluded": "the sealed run evidence (provider requests and replies, prompts, model reasoning, failure text); it "
                "stays in the local run root, from which aeread verify-replay recomputes every published score",
}
#: The drivers whose plans these bundles describe, and how a campaign id names its subject.
CLI_SUBJECTS = {"codex_cli_sol61": "codex_sol61", "claude_code_opus55": "claude_opus55"}


def _subject_and_driver(campaign_id: str, plan: Mapping[str, Any]) -> tuple[str, str]:
    if plan.get("kind") == "scripted_baselines":
        return "scripted", "src/aeread_families/procurement_allocation/pay_or_test_v3_baselines.py"
    for tag, subject in CLI_SUBJECTS.items():
        if f"_v3_{tag}_" in campaign_id:
            return subject, "tools/cli_subjects/pay_or_test_v3_cli.py"
    if "_v3_control_" in campaign_id:
        return campaign_id.split("_v3_control_", 1)[1].removesuffix("_v1"), "tools/cli_subjects/pay_or_test_v3_control.py"
    if "_v3_openrouter_" in campaign_id:
        return campaign_id.split("_v3_openrouter_", 1)[1].removesuffix("_v1"), "tools/cli_subjects/pay_or_test_v3_openrouter.py"
    raise ValueError(f"no known version 3 driver names {campaign_id!r}")


def campaign_record(plan: Mapping[str, Any]) -> dict[str, Any]:
    """The public description of one run, from its sealed plan."""
    campaign_id = plan["campaign_id"]
    subject, driver = _subject_and_driver(campaign_id, plan)
    keep = ("plan_sha256", "claim_status", "claim_scope", "pack", "prompt", "model", "revision", "provider",
            "provider_runtime", "route", "inference_seeds", "inference_seed_meaning", "planned_trajectory_count",
            "phase", "driver", "rules")
    record = {"schema_version": CAMPAIGN_SCHEMA, "campaign_id": campaign_id, "subject": subject, "driver_path": driver,
              **{key: plan[key] for key in keep if key in plan}}
    return record


def _attempts(run_root: Path) -> dict[str, Path]:
    """Every sealed attempt under the run root, by receipt digest."""
    found: dict[str, Path] = {}
    for path in sorted(run_root.rglob("evaluation_receipt.json")):
        receipt = json.loads(path.read_bytes())
        found[receipt["receipt_sha256"]] = path.parent
    return found


def _jsonl(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) + b"\n" for row in rows)


def _readme(record: Mapping[str, Any], plays: int) -> bytes:
    text = (
        f"# {record['campaign_id']}\n\n"
        f"Pay or test version 3, pack `{record.get('pack')}`, subject `{record['subject']}`, {plays} plays; claim status "
        f"`{record.get('claim_status')}`. A kernel-standard bundle of the run's receipts, published so that "
        "`aeread verify-replay` can recompute every score from the sealed evidence in the local run root:\n\n"
        "    PYTHONPATH=src:tools/cli_subjects aeread verify-replay evidence/procurement_allocation/"
        f"{record['campaign_id']} \\\n"
        f"        --run-root <run root of {record['campaign_id']}> --setup pay_or_test_v3_replay:setup_for_receipt\n\n"
        "- `reports/campaign.json`: the run's identity, plan digest, pack, prompt, model, CLI runtime or route, seeds and "
        "driver, from its sealed plan.\n"
        "- `receipts/projections.jsonl`: each receipt's public projection.\n"
        "- `tables/cells.jsonl`: one row a play.\n"
        "- `trajectories/sanitized.jsonl`: the kernel's sanitized trajectory grain.\n\n"
        "The run's results and declared analysis are in the read-out bundles and results notes listed in "
        "`docs/families/procurement-allocation/qc.md` section 8.2.\n"
    )
    return text.encode("utf-8")


def publish_run(run_root: Path | str, *, evidence_root: Path = EVIDENCE) -> dict[str, Any]:
    """Publish one run root; refuse an incomplete or inconsistent one."""
    root = Path(run_root)
    plan = json.loads((root / "model_plan.json").read_bytes())
    summary = json.loads((root / "summary.json").read_bytes())
    if summary["plan"]["plan_sha256"] != plan["plan_sha256"]:
        raise ValueError(f"{root.name}: the summary's plan is not the sealed plan")
    record = campaign_record(plan)
    attempts = _attempts(root)
    rows = summary["rows"]
    if len(rows) != plan["planned_trajectory_count"]:
        raise ValueError(f"{root.name}: {len(rows)} rows against {plan['planned_trajectory_count']} planned")
    cells, projections, attempt_dirs = [], [], []
    for row in sorted(rows, key=lambda r: (str(r["case_id"]), int(r["inference_seed"]))):
        digest = row.get("receipt_sha256") or row.get("failure_receipt_sha256")
        if digest not in attempts:
            raise ValueError(f"{root.name}: no sealed attempt for {row['case_id']} seed {row['inference_seed']}")
        receipt = json.loads((attempts[digest] / "evaluation_receipt.json").read_bytes())
        if receipt["case_id"] != row["case_id"]:
            raise ValueError(f"{root.name}: receipt {digest[:12]} is not {row['case_id']}'s")
        slug = row["case_id"].rsplit(".", 1)[-1]
        key = f"{record['campaign_id']}:{slug}:{row['inference_seed']}"
        projections.append(receipt_projection(receipt, campaign_cell_key=key))
        cells.append({"campaign_cell_key": key, "case_id": row["case_id"], "slug": slug,
                      "inference_seed": row["inference_seed"], "status": row["status"],
                      "decision": row.get("decision"), "termination_reason": row.get("termination_reason"),
                      "contribution_margin_usd": row.get("contribution_margin_usd"), "receipt_sha256": digest,
                      "run_plan_sha256": receipt["run_plan_sha256"],
                      "plan_implementation_pins": receipt["plan_implementation_pins"]})
        attempt_dirs.append(attempts[digest])
    bundle = Path(evidence_root) / record["campaign_id"]
    payloads = {
        "README.md": _readme(record, len(cells)),
        "reports/campaign.json": canonical_json_bytes(record) + b"\n",
        "receipts/projections.jsonl": _jsonl(projections),
        "tables/cells.jsonl": _jsonl(cells),
    }
    for name, payload in payloads.items():
        assert_public_payload(name, payload)
        atomic_publish(bundle / name, payload)
    seal_publication_manifest(
        bundle, publication_id=record["campaign_id"], privacy_boundary=PRIVACY_BOUNDARY,
        campaign_id=record["campaign_id"],
        source_bindings={"run_plan_sha256": plan["plan_sha256"], "summary_artifact_sha256": summary["artifact_sha256"],
                         "publisher": {"path": "src/aeread_families/procurement_allocation/pay_or_test_v3_publication.py",
                                       "sha256": PUBLISHER_SHA256}},
    )
    _rows, manifest = publish_trajectory_grain(bundle, attempt_dirs)
    grain = (bundle / "trajectories" / "sanitized.jsonl").read_bytes()
    assert_public_payload("trajectories/sanitized.jsonl", grain)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_roots", nargs="+", type=Path)
    args = parser.parse_args(argv)
    for root in args.run_roots:
        manifest = publish_run(root)
        print(f"{manifest['publication_id']}: manifest_sha256={manifest['manifest_sha256']}")
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI
    raise SystemExit(main())
