"""Compatibility CLI for the Refund V2.1 shared-runner campaign."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .v2_environment import validate_active_agents
from .v2_runner import run as run_shared


def _load_env(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def run(
    *,
    seeds: tuple[int, ...],
    output: Path,
    model: str,
    revision: str | None,
    reasoning_effort: str | None,
    max_output_tokens: int,
    timeout: float,
    env_file: Path | None,
    active_agents: tuple[str, ...] = ("policy",),
    evaluation_kind: str = "controlled",
) -> dict:
    del timeout
    _load_env(env_file)
    if not os.environ.get("ARENA_API_KEY"):
        raise RuntimeError("ARENA_API_KEY must be set, directly or through --env-file")
    return await run_shared(
        output=output,
        provider="arena",
        model=model,
        revision=revision or model,
        world_seeds=seeds,
        active_agents=validate_active_agents(active_agents),
        evaluation_kind=evaluation_kind,
        max_output_tokens=max_output_tokens,
        reasoning_effort=reasoning_effort,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-seeds", default="1,2,3,4,5")
    parser.add_argument("--model", default="deepseek-v4-flash-0731")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--active-agents", default="policy")
    parser.add_argument("--evaluation-kind", choices=("controlled", "self_play"), default="controlled")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    seeds = tuple(int(item.strip()) for item in args.world_seeds.split(",") if item.strip())
    report = asyncio.run(
        run(
            seeds=seeds,
            output=args.output,
            model=args.model,
            revision=args.revision,
            reasoning_effort=args.reasoning_effort,
            max_output_tokens=args.max_output_tokens,
            timeout=args.timeout,
            env_file=args.env_file,
            active_agents=tuple(item.strip() for item in args.active_agents.split(",") if item.strip()),
            evaluation_kind=args.evaluation_kind,
        )
    )
    print(json.dumps({key: report[key] for key in ("planned_cases", "completed_cases", "operational_failures")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
