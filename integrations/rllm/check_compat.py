#!/usr/bin/env python3
"""CI-only check: assert ``compat.json`` matches what actually ran.

The required pinned-rLLM integration job (see ``.github/workflows/ci.yml``)
calls this after its test steps, passing the Python version and rLLM
revision it actually used. A workflow edit that quietly drifts from the
recorded compatibility record -- a bumped Python version, a re-pinned rLLM
SHA that forgot to update ``compat.json`` -- fails loudly here instead of
aging out of date unnoticed.

    python integrations/rllm/check_compat.py \\
        --python-version 3.12 \\
        --rllm-revision 1d1109a655e291b3001d8526d7c9ecc5b9328226
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


COMPAT_PATH = Path(__file__).with_name("compat.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-version", required=True,
        help="the Python version (e.g. 3.12) the calling job used",
    )
    parser.add_argument(
        "--rllm-revision", required=True,
        help="the rLLM commit SHA actually checked out by the calling job",
    )
    args = parser.parse_args(argv)

    compat = json.loads(COMPAT_PATH.read_text(encoding="utf-8"))
    problems: list[str] = []

    if args.rllm_revision != compat["rllm_revision"]:
        problems.append(
            f"tested rLLM revision {args.rllm_revision!r} != recorded "
            f"rllm_revision {compat['rllm_revision']!r}"
        )
    if args.rllm_revision != compat["model_gateway"]["revision"]:
        problems.append(
            f"tested rLLM revision {args.rllm_revision!r} != recorded "
            f"model_gateway.revision {compat['model_gateway']['revision']!r}"
        )
    if args.python_version not in compat["python_versions"]:
        problems.append(
            f"tested Python {args.python_version!r} is not one of the "
            f"recorded python_versions {compat['python_versions']!r}"
        )
    if args.python_version != compat["integration_tested_python_version"]:
        problems.append(
            f"tested Python {args.python_version!r} != recorded "
            "integration_tested_python_version "
            f"{compat['integration_tested_python_version']!r}"
        )
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    if running != args.python_version:
        problems.append(
            f"--python-version {args.python_version!r} does not match the "
            f"interpreter actually running this check ({running!r})"
        )

    if problems:
        for problem in problems:
            print(f"compat.json mismatch: {problem}", file=sys.stderr)
        return 1
    print(f"{COMPAT_PATH} matches the tested revisions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
