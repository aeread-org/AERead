"""Provider-failure census across run roots, with transport telemetry when given.

``aeread provider-failures --runs RUN_ROOT... [--telemetry DIR...] [--json OUT]``
counts failed provider calls by failure condition, HTTP status, route, hour and
seat, lists hang candidates (calls stuck before their first delta) and finds
processes that used one credential at overlapping times (HL-O-07 style hangs
were explained by hand-tallied incident rows; this replaces the tally).

Read-only. It reads every ``attempts/*/events.jsonl`` with its own diagnostic
reader instead of ``task/spend.py``'s, because that one raises on a torn line
and a census must survive the logs an interrupted run leaves.  It keeps the
payload checks of the spend reader: a payload must exist, match its event's
``payload_sha256`` and parse as JSON.  A seal alone never makes a log audited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model_call.transport_telemetry import HIDDEN_DIRNAME, stalled_phase

REPORT_SCHEMA = "aeread.provider_failures/0.1"

_FAILURE_EVENTS = frozenset({"provider_call_failed", "provider_call_outcome_unknown"})
_SEAL_NAME = "events.jsonl.sealed.json"


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Valid prefix of a JSON-lines file and the first problem found, if any.

    A final line without a newline that does not parse is a torn tail
    (`truncated_tail`); any other unparseable or non-object line is `corrupt`.
    Reading stops at the first problem: later lines cannot be trusted to follow
    the prefix.  An unreadable file is `corrupt`.
    """

    try:
        data = path.read_bytes()
    except OSError:
        return [], "corrupt"
    records: list[dict[str, Any]] = []
    lines = data.split(b"\n")
    torn_candidate = lines.pop() if lines and lines[-1] != b"" else None
    if lines and lines[-1] == b"" and torn_candidate is None:
        lines.pop()
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            return records, "corrupt"
        if not isinstance(record, dict):
            return records, "corrupt"
        records.append(record)
    if torn_candidate is not None:
        try:
            record = json.loads(torn_candidate)
        except ValueError:
            return records, "truncated_tail"
        if not isinstance(record, dict):
            return records, "corrupt"
        records.append(record)
    return records, None


def _payload_of(root: Path, event: Mapping[str, Any]) -> tuple[Any, str | None]:
    ref, digest = event.get("payload_ref"), event.get("payload_sha256")
    if not isinstance(ref, str) or not isinstance(digest, str):
        return None, "payload_missing"
    path = root / ref
    if path.is_symlink() or not path.is_file():
        return None, "payload_missing"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, "payload_missing"
    if hashlib.sha256(raw).hexdigest() != digest:
        return None, "payload_digest_mismatch"
    try:
        return json.loads(raw), None
    except ValueError:
        return None, "payload_corrupt"


def _attempt_logs(run_root: Path) -> Iterator[Path]:
    for directory, subdirs, files in os.walk(run_root):
        subdirs[:] = sorted(d for d in subdirs if d != "artifacts")
        here = Path(directory)
        if "events.jsonl" in files and here.parent.name == "attempts":
            yield here / "events.jsonl"


def _hour(occurred_at: Any) -> str:
    return occurred_at[:13] + "Z" if isinstance(occurred_at, str) and len(occurred_at) >= 13 else "unknown"


def _read_attempt(log: Path, failures: list[dict[str, Any]]) -> dict[str, Any]:
    root = log.parent
    events, problem = read_jsonl(log)
    issues: list[str] = [problem] if problem else []
    seats: dict[str, str] = {}
    routes: dict[str, str] = {}
    pending: list[dict[str, Any]] = []
    for event in events:
        payload, payload_problem = _payload_of(root, event)
        if payload_problem:
            # The event is left out of the counts; the attempt is incomplete.
            issues.append(payload_problem)
            continue
        kind = event.get("event_type")
        if kind == "logical_action_started" and isinstance(payload, Mapping):
            request = payload.get("request")
            action = event.get("logical_action_id")
            if isinstance(request, Mapping) and isinstance(request.get("seat_id"), str) and action:
                seats[action] = request["seat_id"]
        elif kind == "provider_call_started" and isinstance(payload, Mapping):
            request = payload.get("request")
            call = event.get("provider_call_id")
            if isinstance(request, Mapping) and call:
                routes[call] = f"{request.get('provider')}/{request.get('model')}"
        elif kind in _FAILURE_EVENTS and isinstance(payload, Mapping):
            pending.append({"event": event, "payload": payload})
    for item in pending:
        event, payload = item["event"], item["payload"]
        status = payload.get("status_code")
        failures.append(
            {
                "failure_condition": payload.get("failure_condition") or "unknown",
                "status": status if isinstance(status, int) and not isinstance(status, bool) else None,
                "route": routes.get(event.get("provider_call_id"), "unknown"),
                "hour": _hour(event.get("occurred_at")),
                "seat": seats.get(event.get("logical_action_id")),
            }
        )
    sealed = os.path.lexists(root / _SEAL_NAME)
    labels = sorted(
        ({"unaudited"} if not sealed else set())
        | ({"incomplete"} if issues else set())
    )
    return {
        "attempt": str(log.parent),
        "sealed": sealed,
        "labels": labels,
        "issues": sorted(set(issues)),
    }


def _telemetry_base(directory: Path) -> Path:
    hidden = directory / HIDDEN_DIRNAME
    return hidden if hidden.is_dir() else directory


def _read_telemetry(directory: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Call records, process records and per-file issues from one telemetry dir."""

    base = _telemetry_base(directory)
    calls: list[dict[str, Any]] = []
    process: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.jsonl")):
        if path.name == "process.jsonl":
            target = process
        elif path.name.endswith(".transport.jsonl"):
            target = calls
        else:
            continue
        records, problem = read_jsonl(path)
        target.extend(r for r in records if "event" in r)
        if problem:
            files.append({"file": str(path), "issue": problem})
    return calls, process, files


def _call_key(record: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("session_id")),
        str(record.get("execution_id")),
        str(record.get("provider_call_id")),
    )


def _judge_call(key: tuple[str, str, str], records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A hang candidate (or progress-unknown stall) for one call, else None."""

    names = [str(r["event"]) for r in records]
    phase = stalled_phase(names)
    if phase is None:
        return None
    delta_seen = unobservable = False
    for name, record in zip(names, records):
        if name.startswith("first_delta."):
            delta_seen = True
            break
        if name == "delta_marks" and str(record.get("delta_marks", "")).startswith("unobservable"):
            unobservable = True
    if delta_seen:
        return None
    anchor = next(
        (r for r in reversed(records) if r["event"] == phase), records[-1]
    )
    try:
        duration = round(float(records[-1]["mono"]) - float(anchor["mono"]), 3)
    except (KeyError, TypeError, ValueError):
        duration = None
    return {
        "session_id": key[0],
        "execution_id": key[1],
        "provider_call_id": key[2],
        "cell_id": records[0].get("cell_id"),
        "phase": phase,
        "duration_seconds": duration,
        "status": "stalled_progress_unknown" if unobservable else "stalled_before_first_delta",
    }


def _parse_wall(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _sessions(process: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Session intervals: session_start to session_end, else to the last record."""

    sessions: dict[str, dict[str, Any]] = {}
    for record in process:
        session = sessions.setdefault(
            str(record.get("session_id")),
            {"start": None, "end": None, "ended": False, "fps": set()},
        )
        when = _parse_wall(record.get("wall"))
        if when is None:
            continue
        event = record.get("event")
        if event == "session_start" and (session["start"] is None or when < session["start"]):
            session["start"] = when
        if event in ("session_start", "heartbeat", "session_end") and (
            session["end"] is None or when > session["end"]
        ):
            session["end"] = when
        if event == "session_end":
            session["ended"] = True
        fps = record.get("credential_fps")
        if isinstance(fps, list):
            session["fps"].update(str(fp) for fp in fps)
    return sessions


def _overlaps(sessions: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_fp: dict[str, list[tuple[str, datetime, datetime]]] = {}
    for session_id, info in sessions.items():
        if info["start"] is None or info["end"] is None:
            continue
        for fp in info["fps"]:
            by_fp.setdefault(fp, []).append((session_id, info["start"], info["end"]))
    result = []
    for fp in sorted(by_fp):
        entries = sorted(by_fp[fp])
        pairs = [
            [a[0], b[0]]
            for index, a in enumerate(entries)
            for b in entries[index + 1 :]
            if a[1] <= b[2] and b[1] <= a[2]
        ]
        if pairs:
            result.append({"credential_fp": fp, "session_pairs": pairs})
    return result


def build_report(runs: Sequence[Path], telemetry: Sequence[Path]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    attempts = [
        _read_attempt(log, failures)
        for root in runs
        for log in _attempt_logs(root)
    ]
    attempts.sort(key=lambda a: a["attempt"])
    call_records: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    process: list[dict[str, Any]] = []
    telemetry_issues: list[dict[str, Any]] = []
    for directory in telemetry:
        calls, proc, issues = _read_telemetry(directory)
        for record in calls:
            if record.get("provider_call_id") is not None:
                call_records.setdefault(_call_key(record), []).append(record)
        process.extend(proc)
        telemetry_issues.extend(issues)
    hangs = [
        found
        for key, records in sorted(call_records.items())
        if (found := _judge_call(key, records)) is not None
    ]

    def counted(field: str) -> dict[str, int]:
        counter = Counter(str(f[field]) for f in failures if f[field] is not None)
        return dict(sorted(counter.items()))

    return {
        "schema": REPORT_SCHEMA,
        "attempts": attempts,
        "failures_total": len(failures),
        "by_failure_condition": counted("failure_condition"),
        "by_status": counted("status"),
        "by_route": counted("route"),
        "by_hour": counted("hour"),
        "by_seat": counted("seat"),
        "calls_traced": len(call_records),
        "hang_candidates": hangs,
        "telemetry_issues": sorted(telemetry_issues, key=lambda i: i["file"]),
        "credential_overlaps": _overlaps(_sessions(process)),
    }


def render_text(report: Mapping[str, Any]) -> str:
    lines = [f"provider failures: {report['failures_total']} across {len(report['attempts'])} attempt logs"]
    for title, key in (
        ("failure_condition", "by_failure_condition"),
        ("http status", "by_status"),
        ("route", "by_route"),
        ("hour", "by_hour"),
        ("seat", "by_seat"),
    ):
        lines.append(f"by {title}:")
        lines.extend(f"  {name:40s} {count}" for name, count in report[key].items())
    flagged = [a for a in report["attempts"] if a["labels"]]
    lines.append(f"attempt logs with labels: {len(flagged)}")
    for attempt in flagged:
        lines.append(
            f"  {attempt['attempt']}: {','.join(attempt['labels'])}"
            + (f" ({','.join(attempt['issues'])})" if attempt["issues"] else "")
        )
    lines.append(f"hang candidates: {len(report['hang_candidates'])} of {report['calls_traced']} traced calls")
    for hang in report["hang_candidates"]:
        lines.append(
            f"  {hang['status']} {hang['session_id']}/{hang['execution_id']}/{hang['provider_call_id']}"
            f" phase={hang['phase']} duration={hang['duration_seconds']}s"
        )
    for issue in report["telemetry_issues"]:
        lines.append(f"telemetry {issue['issue']}: {issue['file']}")
    lines.append(f"credential overlaps: {len(report['credential_overlaps'])}")
    for overlap in report["credential_overlaps"]:
        lines.append(f"  {overlap['credential_fp']}: {overlap['session_pairs']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aeread provider-failures",
        description="count provider failures across run roots and find hang candidates",
    )
    parser.add_argument("--runs", type=Path, nargs="+", required=True, help="run roots holding attempts/*/events.jsonl")
    parser.add_argument("--telemetry", type=Path, nargs="*", default=[], help="transport telemetry directories")
    parser.add_argument("--json", type=Path, help="write the report here instead of printing a table")
    args = parser.parse_args(argv)
    report = build_report(args.runs, args.telemetry)
    if args.json is not None:
        args.json.write_bytes(
            (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf-8")
        )
    else:
        print(render_text(report))
    return 0


__all__ = ["REPORT_SCHEMA", "build_report", "main", "read_jsonl", "render_text"]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
