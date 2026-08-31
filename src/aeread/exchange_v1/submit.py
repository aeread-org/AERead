"""Frozen-panel submission harness (D10) — run a foreign agent over a case-set.

The yardstick's exam pipeline: take one submitted agent, seat it in every case's
`under_test` role (the env supplies the frozen panel per the case's `roles`
block), run each case `live_frozen`, optionally verify each run by immediate
replay byte-diff, and emit one submission directory:

    submissions/<id>/
      cases/                    the case configs actually run (under_test seat
                                rewritten to kind "submitted")
      runs/<case>/              one self-contained run dir per case (+ __verify
                                replay dirs when --verify-replay)
      submission_report.json    per-case numbers + scorer tier + verification +
                                per-seat cost split + the aggregate

Guarantees:
- **Paired evaluation:** cases pin their seeds, so every submission faces
  byte-identical worlds, hidden values, and panel; the report carries a
  case-set content hash — two reports are comparable iff the hashes match.
- **Reproducibility:** strict funnel mode is on; panel pins are enforced;
  `--verify-replay` proves each run replays byte-identically with the foreign
  agent absent (its actions are served from the recorded snapshots).
- **Honest scoring tiers:** each case row states which scorer produced its
  number — `d15` (C's official AER scorer, used when importable),
  `welfare_ratio_provisional` otherwise. Tiers are never silently mixed into
  one aggregate: the aggregate is labeled with the tier set it came from.

Submitted-agent contract (v0, in-process; the text boundary survives a future
container/endpoint upgrade): an object with

    act(observation: str, phase: str) -> str

where observation is exactly the prompt an LLM seat would receive (own private
state + public transcript only) and phase is one of communication / proposal /
response / finalization / private_acceptance.

Usage:
    python -m aeread.exchange_v1.submit --cases case_a.json case_b.json \
        --agent mypkg.myagent:MyAgent --out submissions/ [--no-verify-replay]
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aeread.exchange_v1.roles import KIND_SUBMITTED  # noqa: E402
from aeread.exchange_v1.runner import (  # noqa: E402
    InferenceOptions,
    RunnerError,
    run_v1,
)

SUBMISSION_SCHEMA_VERSION = "1.0"

SCORER_TIER_D15 = "d15"
SCORER_TIER_PROVISIONAL = "welfare_ratio_provisional"


def load_agent(spec: str) -> Any:
    """Instantiate a submitted agent from a ``module:attr`` entry point."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise RunnerError(f"agent spec must be 'module:Class', got {spec!r}")
    obj = getattr(importlib.import_module(module_name), attr)
    return obj() if isinstance(obj, type) else obj


def _score_run(run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    """Tiered scoring hook — the D15 seam, not the scorer.

    Tier 1: C's official AER scorer (D15), used the moment it lands upstream.
    Tier 2: welfare_ratio from the run summary, explicitly labeled provisional.
    """
    try:
        from aeread.exchange_v1.scoring import score_run as d15_score_run  # C's D15, when it lands

        result = d15_score_run(run_dir)
        return {"tier": SCORER_TIER_D15, **result}
    except ImportError:
        return {
            "tier": SCORER_TIER_PROVISIONAL,
            "score": summary.get("welfare_ratio"),
            "note": "welfare_ratio vs W*; replace with the D15 AER scorer when available",
        }


def _validate_case(case_path: Path, agent_label: str) -> dict[str, Any]:
    """Load one case and validate its rewritten seat table. Returns the raw dict.

    Raises RunnerError with a per-case message; run_submission aggregates these
    across the whole case-set BEFORE anything runs, so a malformed case costs
    zero API spend and leaves no partial submission directory behind.
    """
    from aeread.exchange_v1.roles import parse_role_table

    if not case_path.is_file():
        raise RunnerError(f"{case_path}: case file not found")
    try:
        raw = json.loads(case_path.read_text())
    except json.JSONDecodeError as err:
        raise RunnerError(f"{case_path}: not valid JSON ({err})") from err
    roles = raw.get("roles") if isinstance(raw, dict) else None
    if not isinstance(roles, dict) or "under_test" not in roles:
        raise RunnerError(
            f"{case_path}: no roles.under_test — every submission case must "
            "declare a seat table (D9)"
        )
    roles["under_test"]["policy"] = {"kind": KIND_SUBMITTED, "name": agent_label}
    try:
        parse_role_table(roles, int(raw.get("num_agents", 0)))
    except Exception as err:  # RoleConfigError and friends — surface per case
        raise RunnerError(f"{case_path}: invalid roles block ({err})") from err
    return raw


def _prepare_case(case_path: Path, cases_dir: Path, agent_label: str) -> Path:
    """Write the validated, seat-rewritten case into the submission dir."""
    raw = _validate_case(case_path, agent_label)
    prepared = cases_dir / case_path.name
    prepared.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    return prepared


def _caseset_hash(case_paths: list[Path]) -> str:
    """Content hash over the prepared cases — reports are comparable iff equal."""
    digest = hashlib.sha256()
    for path in sorted(case_paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_submission(
    case_paths: list[str | Path],
    agent: Any,
    *,
    agent_label: str = "submitted",
    out_root: str | Path = "submissions",
    options: Optional[InferenceOptions] = None,
    verify_replay: bool = True,
    submission_id: Optional[str] = None,
    quiet: bool = False,
) -> Path:
    """Run the full exam; returns the submission directory."""
    if not case_paths:
        raise RunnerError("a submission needs at least one case")

    # Pre-flight: validate EVERY case before creating anything or spending
    # anything — one malformed case fails the whole submission up front, with
    # all defects listed, rather than mid-exam after money is spent.
    defects = []
    for path in case_paths:
        try:
            _validate_case(Path(path), agent_label)
        except RunnerError as err:
            defects.append(str(err))
    if defects:
        raise RunnerError(
            "submission refused — invalid case(s):\n  " + "\n  ".join(defects)
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    submission_id = submission_id or f"{agent_label.replace('/', '-')}__{stamp}"
    submission_dir = Path(out_root) / submission_id
    if submission_dir.exists():
        raise RunnerError(f"submission dir already exists: {submission_dir}")
    cases_dir = submission_dir / "cases"
    cases_dir.mkdir(parents=True)

    prepared = [_prepare_case(Path(p), cases_dir, agent_label) for p in case_paths]
    caseset_hash = _caseset_hash(prepared)

    rows: list[dict[str, Any]] = []
    all_verified = True
    for case_path in prepared:
        case_name = case_path.stem
        row: dict[str, Any] = {"case": case_name, "status": "ok", "verified_replay": None}
        try:
            outcome = run_v1(
                case_path,
                mode="live_frozen",
                out_root=submission_dir / "runs",
                options=options,
                run_id=case_name,
                quiet=quiet,
                strict=True,  # an unreplayable exam run is no exam run
                under_test_agent=agent,
            )
        except BaseException as err:  # noqa: BLE001 — a RUNTIME failure must never
            # sink the submission (static case defects were already rejected in
            # the pre-flight, before any spend)
            if isinstance(err, KeyboardInterrupt):
                raise
            row["status"] = "harness_error"
            row["error"] = f"{type(err).__name__}: {err}"
            rows.append(row)
            all_verified = False
            if not quiet:
                print(f"[submit] HARNESS ERROR {case_name}: {row['error']}")
            continue

        summary = outcome.summary
        row["run_dir"] = str(outcome.run_dir)
        row["seed"] = summary.get("protocol", {}).get("visibility_seed")  # informational
        row["score"] = _score_run(outcome.run_dir, summary)
        row["welfare_ratio"] = summary.get("welfare_ratio")
        row["applied_mechanisms"] = summary.get("applied_mechanisms")
        row["ir_violations"] = summary.get("ir_violations")
        row["seat_costs"] = (summary.get("manifest_totals") or {}).get("by_seat")

        if verify_replay:
            try:
                replay = run_v1(
                    mode="replay",
                    replay_from=outcome.run_dir,
                    out_root=submission_dir / "runs",
                    run_id=f"{case_name}__verify",
                    quiet=True,
                )
                identical = (
                    (outcome.run_dir / "trace.jsonl").read_bytes()
                    == (replay.run_dir / "trace.jsonl").read_bytes()
                )
                row["verified_replay"] = identical
                if not identical:
                    row["status"] = "failed_verification"
            except BaseException as err:  # noqa: BLE001
                if isinstance(err, KeyboardInterrupt):
                    raise
                row["verified_replay"] = False
                row["status"] = "failed_verification"
                row["error"] = f"{type(err).__name__}: {err}"
            if row["verified_replay"] is not True:
                all_verified = False
                if not quiet:
                    print(f"[submit] VERIFICATION FAILED {case_name}")
        rows.append(row)
        if not quiet and row["status"] == "ok":
            print(
                f"[submit] ok {case_name} welfare_ratio={row['welfare_ratio']:.3f} "
                f"scorer={row['score']['tier']} verified={row['verified_replay']}"
            )

    ok_rows = [r for r in rows if r["status"] == "ok"]
    tiers = sorted({r["score"]["tier"] for r in ok_rows})
    scores = [r["score"]["score"] for r in ok_rows if r["score"].get("score") is not None]
    # v2 headline aggregate: pooled ratio of sums per DENOMINATOR tier over the
    # d15-scored cases (carve-out §1); denominator tiers are never pooled together.
    d15_ok = [
        r["score"]
        for r in ok_rows
        if r["score"]["tier"] == SCORER_TIER_D15 and r["score"].get("status") == "ok"
    ]
    pooled: dict[str, Any] = {}
    for dt in sorted({s["denominator_tier"] for s in d15_ok}):
        sub = [s for s in d15_ok if s["denominator_tier"] == dt]
        sum_d = sum(s["denominator"] for s in sub)
        pooled[dt] = (sum(s["w_real"] for s in sub) / sum_d) if sum_d > 1e-9 else None
    report = {
        "submission_schema_version": SUBMISSION_SCHEMA_VERSION,
        "submission_id": submission_id,
        "agent_label": agent_label,
        "caseset_hash": caseset_hash,
        "cases_total": len(rows),
        "cases_ok": len(ok_rows),
        "all_verified": all_verified if verify_replay else None,
        "scorer_tiers": tiers,
        "aggregate": {
            # the v2 headline: pooled sum(W_real)/sum(denominator) per denominator tier
            "pooled_aer_by_denominator_tier": pooled or None,
            # secondary view: unweighted mean over scored cases (raw, negatives preserved)
            "score_mean": (sum(scores) / len(scores)) if scores else None,
            "tier": tiers[0] if len(tiers) == 1 else f"mixed:{'+'.join(tiers)}",
            "note": "provisional until the D15 AER scorer lands" if tiers != [SCORER_TIER_D15] else None,
        },
        "cases": rows,
    }
    (submission_dir / "submission_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n"
    )
    if not quiet:
        print(
            f"[submit] report: {submission_dir / 'submission_report.json'} | "
            f"{len(ok_rows)}/{len(rows)} cases ok | aggregate={report['aggregate']['score_mean']}"
        )
    return submission_dir


def verify_submission(submission_dir: str | Path, *, quiet: bool = True) -> dict[str, Any]:
    """Re-verify an existing submission: replay every case and byte-diff traces.

    The audit tool for a submission at rest — detects post-hoc tampering with
    run dirs or snapshots (a mutated snapshot replays to a DIFFERENT trace; a
    deleted one raises ReplayCacheMiss). Returns {case: verified_bool}.
    """
    submission_dir = Path(submission_dir)
    report_path = submission_dir / "submission_report.json"
    if not report_path.is_file():
        raise RunnerError(f"no submission_report.json in {submission_dir}")
    report = json.loads(report_path.read_text())
    results: dict[str, Any] = {}
    for row in report["cases"]:
        if row["status"] != "ok" or not row.get("run_dir"):
            results[row["case"]] = None
            continue
        run_dir = Path(row["run_dir"])
        try:
            replay = run_v1(
                mode="replay",
                replay_from=run_dir,
                out_root=submission_dir / "reverify",
                run_id=f"{row['case']}__reverify_{datetime.now(timezone.utc).strftime('%H%M%S%f')}",
                quiet=quiet,
            )
            results[row["case"]] = (
                (run_dir / "trace.jsonl").read_bytes()
                == (replay.run_dir / "trace.jsonl").read_bytes()
            )
        except BaseException as err:  # noqa: BLE001
            if isinstance(err, KeyboardInterrupt):
                raise
            results[row["case"]] = False
            if not quiet:
                print(f"[verify] {row['case']}: {type(err).__name__}: {err}")
    return results


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cases", nargs="+", required=True, help="case configs with roles blocks")
    ap.add_argument("--agent", required=True, help="submitted agent entry point, module:Class")
    ap.add_argument("--agent-label", default=None, help="label for the report (default: the spec)")
    ap.add_argument("--out", default="submissions")
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument(
        "--no-verify-replay",
        action="store_true",
        help="skip the per-case replay byte-diff (verification is the default)",
    )
    args = ap.parse_args(argv)

    for case in args.cases:
        if not Path(case).is_file():
            raise RunnerError(f"case not found: {case}")
    agent = load_agent(args.agent)
    run_submission(
        args.cases,
        agent,
        agent_label=args.agent_label or args.agent,
        out_root=args.out,
        options=InferenceOptions(max_tokens=args.max_tokens),
        verify_replay=not args.no_verify_replay,
    )


if __name__ == "__main__":
    main()
