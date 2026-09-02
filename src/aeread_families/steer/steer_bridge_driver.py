#!/usr/bin/env python
"""Subprocess driver for the ``steer`` adapter's ``SteerBridge`` (see
``steer_bridge.py``).

This script runs under a SEPARATE, already-provisioned Python interpreter
with pandas installed (see ``tools/steer_bridge/provision.sh``). It exists
so ``cases.py`` -- which runs inside AERead's own interpreter, which
deliberately does not carry pandas -- can unpickle the pinned upstream
STEER corpus (``narunraman/STEER`` @
``d66673c8277b9112fc5e39751524ccda6d852446``) without pandas becoming a
runtime or test-time dependency (docs/steer_adapter_spec.md section 3,
section 6's last stated limit).

This file must not import anything from the ``aeread`` package: it is
invoked as a standalone script under a *different* Python interpreter that
does not have ``aeread`` on its path.

Protocol -- exactly one JSON object read from stdin, exactly one JSON object
written to stdout:

  {"op": "flatten", "element": str, "head_n": int}
      -> {"ok": true, "element": str,
          "file_hashes": {"questions": sha256, "options": sha256,
                          "answers": sha256, "questions_metadata": sha256},
          "counts": {"total": int, "exactly_one_correct": int,
                     "zero_correct": int, "multi_correct": int},
          "admitted": [{"question_id": str, "question_text": str,
                        "options": [{"option_id": int, "option_text": str},
                                    ...],
                        "correct_option_id": int, "source_sha256": str},
                       ...],  # first head_n admitted rows, original frame
                              # order; counts above cover the FULL corpus,
                              # never truncated
          "excluded": [{"question_id": str,
                        "reason": "zero_correct" | "multi_correct"}, ...],
                       # EVERY excluded question_id and why, covering the
                       # full corpus (never truncated by head_n) -- not
                       # just an aggregate count plus one sample (a
                       # critical review finding, docs/steer_codex_triage.md
                       # finding 6)
          "zero_correct_sample_question_id": str | null}
      -- requires ``bridges/steer-data/<element>/*.pkl`` to already be
         cached (see the "fetch" op below); never fetches over the network
         itself. Verifies every cached file's sha256 against the git-LFS
         ``oid`` recorded in the pinned checkout's own pointer file before
         touching pandas. Probes ``answers`` for either a ``correct`` or a
         ``correct_answer`` column -- never assumes one (the schema-drift
         finding in docs/steer_adapter_spec.md's Governing facts). Admits
         only question_ids with exactly one truthy row; zero- and
         multi-correct question_ids are excluded, never coerced or
         silently dropped.

  {"op": "fetch", "element": str}
      -> {"ok": true, "element": str, "fetched": [str, ...]}
      -- downloads any of the element's 4 files missing from
         ``bridges/steer-data/<element>/`` from
         ``media.githubusercontent.com``, verifies each download's sha256
         against the pinned pointer's ``oid`` before keeping it (mismatch is
         a hard failure, the file is not written). This is the ONLY
         network-touching op in this driver; never invoked automatically by
         ``cases.py``, the environment plugin, or any test.

  {"op": "raw_answer_rows", "element": str, "question_id": str}
      -> {"ok": true, "element": str, "question_id": str,
          "rows": [{"option_id": int, "correct_repr": str}, ...]}
      -- the RAW ``answers`` frame rows for exactly one question_id, sorted
         by ``option_id``, with the correct/correct_answer cell rendered via
         ``repr()`` -- never coerced, filled, or classified. Exists so a
         caller can independently re-derive ground truth from a genuinely
         different code path than the "flatten" op's own admission
         classification (a critical review finding, tests/test_steer_cases.py's
         ``test_golden_1s_gold_option_is_independently_verified_against_the_raw_upstream_frame``).

  else -> {"ok": false, "error_type": "bad_request", "message": str}

Any raised exception is caught at the top level and reported as
``{"ok": false, "error_type": str, "message": str}`` with exit code 1 --
mirroring ``aeread_families/tau3_retail/tau2_bridge_driver.py``'s identical
convention.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

FILES: tuple[str, ...] = ("questions", "options", "answers", "questions_metadata")
BASE_URL = "https://media.githubusercontent.com/media/narunraman/STEER/main"


def _verify_upstream_commit(upstream_root: Path, expected_commit: str) -> None:
    """Refuse an ``upstream_root`` that is not really checked out at
    ``expected_commit`` -- the real upstream git state, read here for the
    first time in this adapter, never merely re-compared against the
    constant that produced it (a critical review finding:
    ``docs/steer_codex_triage.md`` finding 2). Mirrors
    ``aeread_families.tau3_retail.environment``'s identical
    ``rev-parse``/``status --porcelain`` check, run here instead because this
    driver -- not the runtime environment plugin -- is the one place in this
    adapter that ever touches the real checkout.
    """
    revision = subprocess.run(
        ["git", "-C", str(upstream_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if revision.returncode != 0:
        raise ValueError(
            f"upstream_root {upstream_root} is not a readable git checkout: "
            f"{revision.stderr.strip()}"
        )
    if revision.stdout.strip() != expected_commit:
        raise ValueError(
            "upstream checkout revision mismatch: "
            f"expected {expected_commit}, got {revision.stdout.strip()}"
        )
    status = subprocess.run(
        ["git", "-C", str(upstream_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0 or status.stdout:
        raise ValueError(f"upstream checkout at {upstream_root} must be clean")


def _read_pointer_oid(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("oid sha256:"):
            return line.split(":", 1)[1].strip()
    raise ValueError(f"no git-lfs 'oid sha256:' line found in {path}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _op_fetch(upstream_root: Path, cache_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    element = request["element"]
    element_dir = cache_root / element
    element_dir.mkdir(parents=True, exist_ok=True)
    fetched: list[str] = []
    for name in FILES:
        pointer_path = upstream_root / "elements" / element / f"{name}.pkl"
        declared_oid = _read_pointer_oid(pointer_path)
        dest = element_dir / f"{name}.pkl"
        if dest.is_file() and _sha256_file(dest) == declared_oid:
            continue
        url = f"{BASE_URL}/elements/{element}/{name}.pkl"
        http_request = urllib.request.Request(
            url, headers={"User-Agent": "aeread-steer-bridge"}
        )
        with urllib.request.urlopen(http_request, timeout=120) as response:
            data = response.read()
        actual_oid = hashlib.sha256(data).hexdigest()
        if actual_oid != declared_oid:
            raise ValueError(
                f"fetched {element}/{name}.pkl sha256 {actual_oid} does not match "
                f"the pinned git-lfs oid {declared_oid}; refusing to cache it"
            )
        dest.write_bytes(data)
        fetched.append(name)
    return {"ok": True, "element": element, "fetched": fetched}


def _verify_and_load_frames(
    upstream_root: Path, cache_root: Path, element: str
) -> tuple[dict[str, Any], dict[str, str]]:
    import pandas as pd

    frames: dict[str, Any] = {}
    file_hashes: dict[str, str] = {}
    for name in FILES:
        pointer_path = upstream_root / "elements" / element / f"{name}.pkl"
        cached_path = cache_root / element / f"{name}.pkl"
        if not pointer_path.is_file():
            raise FileNotFoundError(f"pinned upstream pointer file missing: {pointer_path}")
        if not cached_path.is_file():
            raise FileNotFoundError(
                f"cached bytes missing for {element}/{name}.pkl at {cached_path}; "
                "run the 'fetch' op first (see tools/steer_bridge/README.md)"
            )
        declared_oid = _read_pointer_oid(pointer_path)
        actual_oid = _sha256_file(cached_path)
        if actual_oid != declared_oid:
            raise ValueError(
                f"sha256 mismatch for {element}/{name}.pkl: pinned git-lfs oid "
                f"{declared_oid}, cached bytes hash to {actual_oid}"
            )
        file_hashes[name] = actual_oid
        frames[name] = pd.read_pickle(cached_path)
    return frames, file_hashes


def _correct_column(answers: Any) -> str:
    # Schema-drift finding (docs/steer_adapter_spec.md Governing facts):
    # upstream's own README documents a single `correct: bool` column, but
    # the real per-element dtype is not uniform. Probe for either name;
    # never assume one.
    if "correct" in answers.columns:
        return "correct"
    if "correct_answer" in answers.columns:
        return "correct_answer"
    raise ValueError(
        "answers frame has neither a 'correct' nor a 'correct_answer' column: "
        f"{list(answers.columns)!r}"
    )


def _op_raw_answer_rows(
    upstream_root: Path, cache_root: Path, request: dict[str, Any]
) -> dict[str, Any]:
    """Return one question_id's RAW answers-frame rows, unclassified.

    Exists so a caller can independently re-derive "is this question's gold
    option really correct" from a genuinely different code path than
    ``_op_flatten``'s own admission classification -- a critical review
    finding (``docs/steer_codex_triage.md`` finding 4): golden 1/2 only ever
    checked the pipeline's self-agreement with whatever ``correct_option_id``
    the (possibly-buggy) flatten classification already wrote into the
    cache, never an independent ground truth. ``correct_repr`` is
    ``repr()`` of the raw cell value -- never coerced, filled, or classified
    here -- so the caller decides for itself what counts as truthy.
    """
    element = request["element"]
    question_id = request["question_id"]
    frames, _file_hashes = _verify_and_load_frames(upstream_root, cache_root, element)
    answers = frames["answers"]
    correct_column = _correct_column(answers)
    matching = answers[answers["question_id"] == question_id]
    rows = [
        {
            "option_id": int(row.option_id),
            "correct_repr": repr(getattr(row, correct_column)),
        }
        for row in matching.itertuples(index=False)
    ]
    rows.sort(key=lambda row: row["option_id"])
    return {"ok": True, "element": element, "question_id": question_id, "rows": rows}


def _op_flatten(upstream_root: Path, cache_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    element = request["element"]
    head_n = request["head_n"]
    if not isinstance(head_n, int) or isinstance(head_n, bool) or head_n <= 0:
        raise ValueError("head_n must be a positive integer")

    frames, file_hashes = _verify_and_load_frames(upstream_root, cache_root, element)
    questions, options, answers = frames["questions"], frames["options"], frames["answers"]

    correct_column = _correct_column(answers)
    # A NaN placeholder in an object-dtype column must never count as
    # truthy: pandas' own `.astype(bool)` applies Python's `bool(float(
    # "nan")) is True` element-wise on object columns, so a bare
    # `.astype(bool)` silently marks every "unknown" row correct (verified
    # against `pure_nash`'s own `correct` column, the only declared
    # element whose Answers frame mixes real bool values with NaN). Fill
    # NaN with False first so only a genuine True/1 row is ever admitted.
    truthy = answers[correct_column].fillna(False).astype(bool)
    correct_rows = answers[truthy]
    per_question_correct_count = correct_rows.groupby("question_id").size()

    options_by_question: dict[str, list[tuple[int, str]]] = {}
    for row in options.itertuples(index=False):
        options_by_question.setdefault(row.question_id, []).append(
            (int(row.option_id), row.option_text)
        )
    for question_id in options_by_question:
        options_by_question[question_id].sort(key=lambda pair: pair[0])

    gold_option_by_question: dict[str, int] = {}
    for row in correct_rows.itertuples(index=False):
        gold_option_by_question.setdefault(row.question_id, int(row.option_id))

    text_by_question = dict(zip(questions["question_id"], questions["question_text"]))

    seen: set[str] = set()
    ordered_question_ids: list[str] = []
    for question_id in questions["question_id"]:
        if question_id not in seen:
            seen.add(question_id)
            ordered_question_ids.append(question_id)

    total = len(ordered_question_ids)
    exactly_one_correct = 0
    zero_correct = 0
    multi_correct = 0
    admitted: list[dict[str, Any]] = []
    # Per-question exclusion ledger (docs/steer_codex_triage.md finding 6):
    # every excluded question_id and the exact reason it was excluded, never
    # just an aggregate count plus one arbitrary sample.
    excluded: list[dict[str, Any]] = []
    zero_correct_sample_question_id: str | None = None

    for question_id in ordered_question_ids:
        correct_count = int(per_question_correct_count.get(question_id, 0))
        if correct_count == 0:
            zero_correct += 1
            excluded.append({"question_id": question_id, "reason": "zero_correct"})
            if zero_correct_sample_question_id is None:
                zero_correct_sample_question_id = question_id
            continue
        if correct_count > 1:
            multi_correct += 1
            excluded.append({"question_id": question_id, "reason": "multi_correct"})
            continue
        exactly_one_correct += 1

        option_rows = options_by_question.get(question_id, [])
        expected_option_ids = list(range(len(option_rows)))
        actual_option_ids = [option_id for option_id, _ in option_rows]
        if actual_option_ids != expected_option_ids:
            raise ValueError(
                f"{element}/{question_id}: option_id is not a dense 0-based "
                f"range: {actual_option_ids!r}"
            )

        question_text = text_by_question[question_id]
        option_texts = [option_text for _, option_text in option_rows]
        correct_option_id = gold_option_by_question[question_id]
        source_sha256 = hashlib.sha256(
            _canonical_json_bytes(
                {
                    "question_text": question_text,
                    "options": option_texts,
                    "correct_option_id": correct_option_id,
                }
            )
        ).hexdigest()
        admitted.append(
            {
                "question_id": question_id,
                "question_text": question_text,
                "options": [
                    {"option_id": option_id, "option_text": option_text}
                    for option_id, option_text in option_rows
                ],
                "correct_option_id": correct_option_id,
                "source_sha256": source_sha256,
            }
        )

    if exactly_one_correct + zero_correct + multi_correct != total:
        raise AssertionError(
            f"{element}: exactly_one_correct + zero_correct + multi_correct "
            f"({exactly_one_correct + zero_correct + multi_correct}) != total "
            f"question_id count ({total})"
        )

    return {
        "ok": True,
        "element": element,
        "file_hashes": file_hashes,
        "counts": {
            "total": total,
            "exactly_one_correct": exactly_one_correct,
            "zero_correct": zero_correct,
            "multi_correct": multi_correct,
        },
        "admitted": admitted[:head_n],
        "excluded": excluded,
        "zero_correct_sample_question_id": zero_correct_sample_question_id,
    }


def _dispatch(upstream_root: Path, cache_root: Path, request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "flatten":
        return _op_flatten(upstream_root, cache_root, request)
    if op == "fetch":
        return _op_fetch(upstream_root, cache_root, request)
    if op == "raw_answer_rows":
        return _op_raw_answer_rows(upstream_root, cache_root, request)
    return {
        "ok": False,
        "error_type": "bad_request",
        "message": f"unknown op: {op!r}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream-root",
        required=True,
        type=Path,
        help="path to the pinned narunraman/STEER checkout (commit "
        "d66673c8277b9112fc5e39751524ccda6d852446)",
    )
    parser.add_argument(
        "--cache-root",
        required=True,
        type=Path,
        help="directory holding bridges/steer-data/<element>/*.pkl, outside "
        "version control per the corpus's no-license constraint",
    )
    parser.add_argument(
        "--expected-commit",
        default=None,
        help="if given, refuse to run any op unless --upstream-root is a "
        "clean git checkout at exactly this commit (docs/steer_adapter_spec.md's "
        "pinned d66673c8277b9112fc5e39751524ccda6d852446)",
    )
    args = parser.parse_args(argv)
    try:
        if args.expected_commit is not None:
            _verify_upstream_commit(args.upstream_root, args.expected_commit)
        request = json.loads(sys.stdin.read())
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        response = _dispatch(args.upstream_root, args.cache_root, request)
    except Exception as error:  # noqa: BLE001 - reported as a structured infra failure
        response = {
            "ok": False,
            "error_type": type(error).__name__,
            "message": str(error),
        }
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
