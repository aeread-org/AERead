"""Publish Housing v15 addendum B (Sol 6.1 and Opus 5.5 through their CLIs), and the replay factory its bundles name.

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/housing_v15_cli_publication.py runs/housing_v15 \\
        evidence/housing/housing_lemons_price_v15_cli_addendum [--admission]
    PYTHONPATH=src:tools/cli_subjects aeread verify-replay <bundle> --run-root runs/housing_v15/<campaign_id> \\
        --setup housing_v15_cli_publication:replay_setup

As ``price_v15_publication`` publishes addendum A: per-cell seat-0 numbers, receipt projections, the contracts and the
declared rows, sealed apart from v15's bundle. ``price_publication.replay_setup`` rebuilds plans from committed
contracts under ``configs/``. A CLI identity's plan is the v15 plan with the tenant's model block replaced
(``housing_v15_cli.cli_setup``), and its contract carries the CLI's runtime, so this module rebuilds those plans from
the contract each run root holds. Nothing hashed is edited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import housing_v15_cli as cli
from aeread.shared_runner.run.publication import assert_public_payload, atomic_publish, jsonl, seal_publication_manifest
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread_families.housing.price_v15_publication import rows_and_projections

MAIN = ("housing_lemons_price_v15_cli_codex_sol61", "housing_lemons_price_v15_cli_claude_opus55")
ADMISSION = ("housing_lemons_price_v15_cli_admission_codex_sol61", "housing_lemons_price_v15_cli_admission_claude_opus55")
PUBLICATION_ID = "housing_lemons_price_v15_cli_addendum"
ADMISSION_ID = "housing_lemons_price_v15_cli_addendum_admission"
ANALYSIS = cli.REPOSITORY / "evidence/housing/housing_lemons_price_v15_cli_addendum_analysis/reports/analysis.json"
_SETUPS: dict[str, Any] = {}


def _subject(campaign_id: str) -> str:
    return next(s for s in cli.SUBJECTS if campaign_id.endswith(s))


def _contract(run_root: Path, campaign_id: str) -> dict[str, Any]:
    return json.loads((run_root / campaign_id / "contract.json").read_text())


def replay_setup(receipt: Mapping[str, Any]) -> Any:
    """The setup whose plan the receipt names, rebuilt from the contract in its run root (either CLI, either kind)."""
    if not _SETUPS:
        for campaign_id in (*MAIN, *ADMISSION):
            path = cli.RUNS / campaign_id / "contract.json"
            if not path.exists():
                continue
            contract = json.loads(path.read_text())
            subject = _subject(campaign_id)
            cli.register(subject, "admission" if "admission" in campaign_id else "main")
            runtime = contract["cli"]["provider_runtime"]
            for holdout_rate in (False, True) if "holdout" in contract else (False,):
                for arm in contract["arms"]:
                    setup = cli.cli_setup(contract, arm, subject, runtime, holdout_rate=holdout_rate)
                    _SETUPS[setup.plan.run_plan_id] = setup
    setup = _SETUPS.get(receipt.get("run_plan_id"))
    if setup is None:
        raise ValueError(f"no addendum-B plan has run_plan_id {receipt.get('run_plan_id')!r}")
    return setup


def _readme(analysis: Mapping[str, Any] | None, rows: list[dict], admission: bool) -> str:
    done = sum(r["status"] == "completed" for r in rows)
    lines = [f"# {ADMISSION_ID if admission else PUBLICATION_ID}", "",
             "Housing v15 addendum B (`docs/families/housing/price_v15_addendum_b_cli_plan.md`): Sol 6.1 through Codex and "
             "Opus 5.5 through Claude Code as seat 0, on v15's market, reported beside v15 and outside its Holm family.", "",
             f"{done} of {len(rows)} cells completed; every receipt replayed when written. Costs are list prices on "
             "subscription logins, not charges.", ""]
    if admission:
        lines += ["Development evidence: each CLI's one-world admission (development world 540003, both arms). Never "
                  "analysed with the addendum's rows.", ""]
    else:
        lines += ["- `reports/analysis.json`: the declared rows (`tools/housing/price_v15_addendum_b_analysis.py`, "
                  "committed with the plan before any cell).", ""]
    lines += ["Replay: `PYTHONPATH=src:tools/cli_subjects aeread verify-replay <bundle> --run-root "
              "runs/housing_v15/<campaign_id> --setup housing_v15_cli_publication:replay_setup`, one run root per "
              "identity.", ""]
    return "\n".join(lines)


def publish(run_root: Path, bundle: Path, *, admission: bool) -> dict[str, Any]:
    if bundle.exists() and any(bundle.iterdir()):
        raise SystemExit(f"{bundle} is not empty; a published bundle is never edited")
    identities = ADMISSION if admission else MAIN
    contracts = [_contract(run_root, i) for i in identities]
    rows, projections = [], []
    for contract in contracts:
        r, p = rows_and_projections(contract, run_root)
        rows += r
        projections += p
    files = {
        "tables/cells.jsonl": jsonl(rows),
        "receipts/projections.jsonl": jsonl(projections),
        "reports/contracts.json": canonical_json_bytes({c["campaign_id"]: c for c in contracts}) + b"\n",
    }
    analysis = None if admission else json.loads(ANALYSIS.read_text())
    if analysis is not None:
        files["reports/analysis.json"] = canonical_json_bytes(analysis) + b"\n"
    files["README.md"] = _readme(analysis, rows, admission).encode("utf-8")
    bundle.mkdir(parents=True, exist_ok=True)
    for relative, payload in files.items():
        assert_public_payload(relative, payload)
        path = bundle / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_publish(path, payload)
    publication_id = ADMISSION_ID if admission else PUBLICATION_ID
    return seal_publication_manifest(
        bundle, publication_id=publication_id, campaign_id=publication_id,
        privacy_boundary={"included": "contracts, per-cell seat-0 numbers and typed failures, receipt projections, "
                                      "receipt digests" + ("" if admission else ", the declared rows"),
                          "excluded": "raw provider responses, model text, complete receipts and events, failure "
                                      "messages, the isolation probes (they stay in the run roots)"},
        source_bindings={"contract_sha256s": {c["campaign_id"]: hashlib.sha256(canonical_json_bytes(c)).hexdigest()
                                              for c in contracts},
                         **({} if admission else {"analysis_sha256": hashlib.sha256(ANALYSIS.read_bytes()).hexdigest()}),
                         "source_receipt_sha256s": sorted(r["receipt_sha256"] for r in rows if r.get("receipt_sha256")),
                         "run_root_layout": "runs/housing_v15/<campaign_id>/live/[holdout_]world_<seed>__<arm>[_evidence]",
                         "replay_setup": "housing_v15_cli_publication:replay_setup (PYTHONPATH src:tools/cli_subjects)"},
        claim_status="development" if admission else "confirmatory_addendum", winner_claim_allowed=False,
        inferential_model_ranking_allowed=False,
        cost_qualifier="list_price_on_subscription", total_cost_usd=round(sum(r["cost_usd"] for r in rows), 6),
        cost_basis="every cell of the addendum's " + ("admissions" if admission else "two identities")
                   + "; list prices of the tokens on subscription logins, not charges",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_root", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--admission", action="store_true")
    args = parser.parse_args(argv)
    manifest = publish(args.run_root, args.bundle, admission=args.admission)
    print(json.dumps({"publication_id": manifest.get("publication_id"), "manifest_sha256": manifest.get("manifest_sha256")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
