"""Lockstep pilot driver: agents x cases x seeds through the D9/D10/D15 pipeline.

Runs every (case, agent, seed) job concurrently (one thread per in-flight run;
`inference.llm_agent` uses context-local per-run hook state, so runs cannot cross-contaminate
manifests). On the AI-Studio key path all live gemini calls funnel through one
GeminiBatchPool — Batch API pricing (50%) with batch size == run concurrency. On
the Vertex path the pool is disabled and runs make plain concurrent calls.

Per job:
  - submitted agents (noop / random)   -> submit.run_submission
    (replay-verified inside the harness)
  - seat agents (greedy / model names) -> runner.run_v1 live_frozen
    + explicit replay byte-diff, scored by scoring

Outputs under --out:
  results.jsonl   one row per job (status, verified, w_real, denominator, score)
  summary.json    per (case, agent): pooled AER = sum(w_real)/sum(denominator)
                  over ok seeds + seeded bootstrap CI; plus per-agent pooled row
  cases/          the seeded case configs actually run

Usage:
  python -m aeread.exchange_v1.pilot \
      --cases cases/exchange_v1/v0/*.json \
      --agents noop random greedy google/gemini-2.5-flash \
      --seeds 30 --workers 24 --out runs/pilot_v0 [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

from aeread.exchange_v1 import runner as runner  # noqa: E402
from aeread.exchange_v1 import scoring as scoring  # noqa: E402
from aeread.exchange_v1 import submit as submit  # noqa: E402
from aeread.exchange_v1.candidates import NoOpCandidate, RandomCandidate  # noqa: E402
from aeread.inference.gemini_batch_pool import GeminiBatchPool  # noqa: E402

EPS = 1e-9
SUBMITTED_AGENTS = ("noop", "random")


def agent_seat_policy(agent: str) -> dict:
    """Seat policy for a non-submitted agent spec.

    ``greedy`` -> the scripted floor. A model id may carry a stochasticity
    suffix ``@t<temp>:s<sample>`` (e.g. ``google/gemini-2.5-flash@t0.7:s2``)
    for the E-arm: temperature/sample land in the seat spec, which
    _build_seat_policy honors for non-frozen llm kinds (both are folded into
    the response-cache key, so distinct samples are distinct live draws)."""
    if agent == "greedy":
        return {"kind": "scripted_bilateral_ir"}
    model, _, suffix = agent.partition("@")
    policy: dict = {"kind": "llm", "model": model}
    for part in suffix.split(":"):
        if part.startswith("t"):
            policy["temperature"] = float(part[1:])
        elif part.startswith("s"):
            policy["sample"] = int(part[1:])
    return policy


def _safe(agent: str) -> str:
    return agent.replace("/", "-").replace("@", "_").replace(":", "_")


def seeded_case(case_path: Path, seed: int, cases_dir: Path, agent: str,
                seat_policy: Optional[dict] = None) -> Path:
    raw = json.loads(case_path.read_text())
    raw["seed"] = seed
    if seat_policy is not None:
        raw["roles"]["under_test"]["policy"] = seat_policy
    # the agent tag keeps concurrent jobs from racing on one filename (greedy vs
    # model seat configs share a stem but differ in content)
    out = cases_dir / f"{case_path.stem}__s{seed}__{_safe(agent)}.json"
    out.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    return out



_MUTE_FLOOR_LADDER = (4096, 8192, 16384, 32768)


def _next_mute_floor() -> Optional[int]:
    """Next rung of the completion-budget ladder after a mute-breaker trip.

    The 2026-08-01 breaker stops a run whose funnel calls are coming back
    empty — but aborting alone DROPS the episode, and dropping the hardest
    episodes biases the pool upward (measured: minimax lost 12 of 150 dev
    episodes, exactly its most-muting ones). So a trip escalates the budget
    and re-runs; only an exhausted ladder gives up, and the give-up is
    recorded rather than silently missing.
    """
    cur = os.environ.get("OPENROUTER_MIN_COMPLETION_TOKENS")
    try:
        cur_v = int(cur) if cur else 0
    except ValueError:
        cur_v = 0
    for rung in _MUTE_FLOOR_LADDER:
        if rung > cur_v:
            return rung
    return None


def run_job(case_path: Path, agent: str, seed: int, out_root: Path,
            max_tokens: int, _mute_retry: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {"case": case_path.stem, "agent": agent, "seed": seed}
    cases_dir = out_root / "cases"
    try:
        if agent in SUBMITTED_AGENTS:
            candidate = NoOpCandidate() if agent == "noop" else RandomCandidate(seed=seed)
            prepared = seeded_case(case_path, seed, cases_dir, agent)
            sub_dir = submit.run_submission(
                [prepared], candidate, agent_label=agent,
                out_root=out_root / "submissions",
                submission_id=f"{agent}__{case_path.stem}__s{seed}",
                options=runner.InferenceOptions(max_tokens=max_tokens),
                quiet=True)
            rep = json.loads((sub_dir / "submission_report.json").read_text())
            case_row = rep["cases"][0]
            row["status"] = case_row["status"]
            row["verified"] = case_row.get("verified_replay")
            row["score_row"] = case_row.get("score")
            if case_row["status"] != "ok":
                row["error"] = case_row.get("error")
        else:
            policy = agent_seat_policy(agent)
            prepared = seeded_case(case_path, seed, cases_dir, agent, seat_policy=policy)
            safe = _safe(agent)
            outcome = runner.run_v1(
                prepared, mode="live_frozen", out_root=out_root / "runs",
                run_id=f"{safe}__{case_path.stem}__s{seed}",
                options=runner.InferenceOptions(max_tokens=max_tokens),
                quiet=True, strict=True)
            # score the PAID live run first — a replay-side hiccup must never
            # discard an already-produced result (mirrors exchange_v1_submit)
            row["status"] = "ok"
            row["score_row"] = scoring.score_run(outcome.run_dir)
            u = outcome.summary.get("usage") or {}
            row["tokens"] = {
                "in": u.get("input_tokens"), "out": u.get("output_tokens")}
            try:
                replay = runner.run_v1(
                    mode="replay", replay_from=outcome.run_dir,
                    out_root=out_root / "runs",
                    run_id=f"{safe}__{case_path.stem}__s{seed}__verify", quiet=True)
                row["verified"] = (
                    (outcome.run_dir / "trace.jsonl").read_bytes()
                    == (replay.run_dir / "trace.jsonl").read_bytes())
            except BaseException as err:  # noqa: BLE001 - verification-only failure
                if isinstance(err, KeyboardInterrupt):
                    raise
                row["verified"] = False
                row["verify_error"] = f"{type(err).__name__}: {err}"
    except BaseException as err:  # noqa: BLE001 - one bad job never sinks the pilot
        if isinstance(err, KeyboardInterrupt):
            raise
        # A tripped health breaker is NOT an ordinary harness error: the run was
        # producing degenerate output (2026-08-01 mute audit). First try to
        # RECOVER it at a higher completion budget — dropping the episode would
        # bias the pool by removing exactly the hardest worlds.
        if type(err).__name__ == "RunHealthError" and _mute_retry:
            nxt = _next_mute_floor()
            if nxt is not None:
                prev = os.environ.get("OPENROUTER_MIN_COMPLETION_TOKENS")
                os.environ["OPENROUTER_MIN_COMPLETION_TOKENS"] = str(nxt)
                try:
                    retry = run_job(case_path, agent, seed, out_root, max_tokens,
                                    _mute_retry=False)
                finally:
                    if prev is None:
                        os.environ.pop("OPENROUTER_MIN_COMPLETION_TOKENS", None)
                    else:
                        os.environ["OPENROUTER_MIN_COMPLETION_TOKENS"] = prev
                retry["mute_retry_floor"] = nxt
                return retry
        row["status"] = ("mute_abort" if type(err).__name__ == "RunHealthError"
                         else "harness_error")
        row["error"] = f"{type(err).__name__}: {err}"
    return row


def pooled(rows: list[dict], *, n_boot: int = 2000, boot_seed: int = 7) -> dict[str, Any]:
    """v2 aggregate over seed-episodes: sum(w_real)/sum(denominator) + bootstrap CI."""
    ok = [r["score_row"] for r in rows
          if r.get("status") == "ok" and (r.get("score_row") or {}).get("status") == "ok"]
    pairs = [(s["w_real"], s["denominator"]) for s in ok]
    out: dict[str, Any] = {
        "n_ok": len(ok),
        "n_verified": sum(1 for r in rows if r.get("verified") is True),
        "n_error": sum(1 for r in rows if r.get("status") != "ok"),
    }
    sum_d = sum(d for _, d in pairs)
    if not pairs or sum_d <= EPS:
        out.update(pooled_aer=None, ci=None)
        return out
    out["pooled_aer"] = sum(w for w, _ in pairs) / sum_d
    boot = random.Random(boot_seed)
    samples = []
    for _ in range(n_boot):
        pick = [pairs[boot.randrange(len(pairs))] for _ in pairs]
        sd = sum(d for _, d in pick)
        if sd > EPS:
            samples.append(sum(w for w, _ in pick) / sd)
    samples.sort()
    out["ci"] = (
        (samples[int(0.025 * len(samples))], samples[int(0.975 * len(samples))])
        if samples else None)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", nargs="+", required=True)
    ap.add_argument("--agents", nargs="+", required=True,
                    help="noop | random | greedy | <model id for the llm seat>")
    ap.add_argument("--seeds", type=int, default=30, help="number of seeds (base+i)")
    ap.add_argument("--seed-base", type=int, default=1200)
    ap.add_argument("--seed-list", type=int, nargs="*", default=None,
                    help="explicit seed list (overrides --seeds/--seed-base)")
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--max-tokens", type=int, default=1200)
    ap.add_argument("--out", required=True)
    ap.add_argument("--flush-interval", type=float, default=20.0)
    ap.add_argument("--batch-pool", action="store_true",
                    help="OPT-IN: cross-run Batch API funnel. Parked until the "
                         "upstream inline-response ordering bug is resolved "
                         "(see gemini_batch_pool.py) — the pool itself refuses "
                         "to start without GEMINI_BATCH_ORDERING_VERIFIED=1.")
    ap.add_argument("--max-error-rate", type=float, default=0.25,
                    help="abort the sweep when the error fraction exceeds this "
                         "after --min-jobs-before-abort jobs (money guard)")
    ap.add_argument("--min-jobs-before-abort", type=int, default=8)
    ap.add_argument("--no-abort-on-verify-fail", action="store_true",
                    help="by default ANY replay-verification failure aborts the "
                         "sweep (an unreplayable exam run means something is wrong)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    seeds = a.seed_list if a.seed_list else [a.seed_base + i for i in range(a.seeds)]
    cases = [Path(c) for c in a.cases]
    jobs = [(c, agent, s) for c in cases for agent in a.agents for s in seeds]
    print(f"[pilot] {len(jobs)} jobs = {len(cases)} cases x {len(a.agents)} agents x {len(seeds)} seeds")
    if a.dry_run:
        for c, agent, s in jobs[:10]:
            print(f"  {c.stem} / {agent} / seed {s}")
        print(f"  ... ({len(jobs)} total)")
        return 0

    out_root = Path(a.out)
    (out_root / "cases").mkdir(parents=True, exist_ok=True)
    results_path = out_root / "results.jsonl"
    write_lock = threading.Lock()
    rows: list[dict] = []
    abort = threading.Event()
    abort_reason: list[str] = []
    stop_file = out_root / "STOP"   # `touch <out>/STOP` interrupts from outside

    def _trip(reason: str) -> None:
        if not abort.is_set():
            abort_reason.append(reason)
            abort.set()
            print(f"[pilot] ABORT: {reason}", flush=True)

    def _guards() -> None:
        done = len(rows)
        errors = sum(1 for r in rows if r.get("status") != "ok")
        if done >= a.min_jobs_before_abort and errors / done > a.max_error_rate:
            _trip(f"error rate {errors}/{done} exceeds {a.max_error_rate}")
        if not a.no_abort_on_verify_fail and any(r.get("verified") is False for r in rows):
            _trip("a run failed replay verification — results not trustworthy")

    def _one(job):
        c, agent, s = job
        if abort.is_set() or stop_file.exists():
            if stop_file.exists():
                _trip("STOP file present")
            row = {"case": c.stem, "agent": agent, "seed": s, "status": "skipped_abort"}
            with write_lock:
                rows.append(row)
            return row
        row = run_job(c, agent, s, out_root, a.max_tokens)
        with write_lock:
            rows.append(row)
            with results_path.open("a") as fh:
                fh.write(json.dumps(row, default=str) + "\n")
            done = len(rows)
            _guards()
        print(f"[pilot] {done}/{len(jobs)} {row['case']}/{row['agent']}/s{row['seed']}: "
              f"{row['status']} v={row.get('verified')}", flush=True)
        return row

    use_pool = (a.batch_pool and os.environ.get("GEMINI_API_KEY")
                and not os.environ.get("GEMINI_VERTEX"))
    pool = GeminiBatchPool(flush_interval=a.flush_interval) if use_pool else None
    try:
        if pool is not None:
            ctx = pool.activated()
            ctx.__enter__()
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            list(ex.map(_one, jobs))
    finally:
        if pool is not None:
            ctx.__exit__(None, None, None)
            print(f"[pilot] batch pool stats: {pool.stats}")

    summary: dict[str, Any] = {"jobs": len(jobs), "pool_stats": pool.stats if pool else None,
                               "aborted": abort.is_set(),
                               "abort_reason": abort_reason[0] if abort_reason else None,
                               "skipped": sum(1 for r in rows if r.get("status") == "skipped_abort"),
                               "by_case_agent": {}, "by_agent": {}}
    for c in cases:
        for agent in a.agents:
            sel = [r for r in rows if r["case"] == c.stem and r["agent"] == agent]
            summary["by_case_agent"][f"{c.stem}|{agent}"] = pooled(sel)
    for agent in a.agents:
        summary["by_agent"][agent] = pooled([r for r in rows if r["agent"] == agent])
    (out_root / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"[pilot] summary -> {out_root / 'summary.json'}")
    for agent, agg in summary["by_agent"].items():
        print(f"  {agent:32s} pooled_aer={agg.get('pooled_aer')} ci={agg.get('ci')} "
              f"ok={agg['n_ok']} verified={agg['n_verified']} err={agg['n_error']}")
    if abort.is_set():
        print(f"[pilot] SWEEP ABORTED: {abort_reason[0] if abort_reason else 'unknown'} "
              f"({summary['skipped']} jobs skipped)")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
