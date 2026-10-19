"""Pay or test v2's pilot worlds played by isolated CLI subjects: the v3 probe (development only, no claim).

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v2_cli.py \\
        --subject claude_opus55 --run-root runs/procurement_allocation/pay_or_test_v2_probe_cli_opus55 --execute

Declared in ``docs/families/procurement-allocation/pay_or_test_v3_design_note.md`` ("Probe, 2026-10-19"). This module
changes nothing in ``procurement_cli.py``, whose bytes earlier plans seal: it adds one pack and one prompt to that
driver's tables and routes both CLIs through ``cli_isolation`` (copied byte for byte from the data-center branch):
Claude Code runs each call in a fresh neutral directory, Codex with a fresh ``HOME``, ``CODEX_HOME`` and working
directory. Before any world, each CLI's context is probed and the run refuses on any violation; the probe is written
into the run root.

- pack ``pay_or_test_v2_pilot``: v2's 12 pilot worlds (6 where the best first move is a probe worth only its option
  value, 6 where one test ahead suffices), gate world ``myopic_pays__tight__3``;
- prompt ``shared_source_v1``: ``pay_or_test_v2_prompt.PAY_OR_TEST_V2_PROMPT``, the brief v2's subjects read.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import cli_isolation as iso
import procurement_cli as base
from aeread_families.procurement_allocation import pay_or_test_v2_case_matrix as v2
from aeread_families.procurement_allocation import pay_or_test_v2_prompt

PACK, PROMPT = "pay_or_test_v2_pilot", "shared_source_v1"
base.PACKS[PACK] = {
    "paths": lambda: sorted(p for p in (base.REPOSITORY / "cases/procurement_allocation_v1" / PACK).glob("*.json")
                            if p.name != "pack.json"),
    "gate_world": "myopic_pays__tight__3",
    "prompts": (PROMPT,),
    "total_cost_ceiling_usd": {"claude_opus55": {"gate": 1.0, "panel": 12.0}, "codex_sol61": {"gate": 1.0, "panel": 8.0}},
}
base.PROMPTS[PROMPT] = {"prompt_id": pay_or_test_v2_prompt.PROMPT_ID, "text": pay_or_test_v2_prompt.PAY_OR_TEST_V2_PROMPT,
                        "treatment_id": pay_or_test_v2_prompt.TREATMENT_ID}


async def _isolated_claude_runner(arguments, standard_input):
    """The base driver's runner (the CLI's refusal reason carried to stderr), in a fresh neutral directory."""
    returncode, stdout, stderr = await iso.isolated_command_runner(arguments, standard_input)
    if returncode != 0 and not stderr.strip():
        try:
            payload = json.loads(stdout)
            stderr = f"{payload.get('result')} (api_error_status {payload.get('api_error_status')})".encode("utf-8")
        except (ValueError, AttributeError):
            stderr = stdout[-400:]
    return returncode, stdout, stderr


base._claude_runner = _isolated_claude_runner
iso.install_codex_isolation()


async def probe(subject: str) -> dict:
    client = await base.discover(subject)
    if base.SUBJECTS[subject]["provider"] == "claude_code":
        found = await iso.probe_claude(client, client._executable, model=base.SUBJECTS[subject]["model"],
                                       reasoning_effort=base.CONTROLS["reasoning_effort"], runner=_isolated_claude_runner)
    else:
        found = await iso.probe_codex(client, model=base.SUBJECTS[subject]["model"],
                                      reasoning_effort=base.CONTROLS["reasoning_effort"])
    return {"probe": found, "violations": iso.isolation_violations(found), "declaration": dict(iso.DECLARATION)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", choices=("claude_opus55", "codex_sol61"), required=True)
    parser.add_argument("--panel", choices=("gate", "panel"), default="panel")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(base.model_plan(args.subject, args.panel, {"runtime_version": "plan-only"}, PACK, PROMPT), indent=1, default=str)[:2000])
        return 0
    found = asyncio.run(probe(args.subject))
    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "isolation_probe.json").write_text(json.dumps(found, indent=1, default=str))
    if found["violations"]:
        print(f"isolation probe refuses the run: {found['violations']}", file=sys.stderr)
        return 2
    artifact = asyncio.run(base.run(args.subject, args.panel, args.run_root, resume=args.resume, pack=PACK, prompt=PROMPT))
    print(json.dumps({"halted": artifact["halted"], "summary": {k: artifact["summary"].get(k) for k in
                                                                ("completed_trajectories", "planned_trajectory_count")}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
