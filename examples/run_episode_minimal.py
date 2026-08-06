#!/usr/bin/env python3
"""Smallest possible AERead loop: one seeded episode, one score.

Runs the seat under test on any OpenAI-compatible endpoint against the
case's frozen panel, and prints the per-episode AER. This is the same
episode core every integration builds on.

    export OPENAI_API_KEY=...            # OpenRouter key in the default setup
    python examples/run_episode_minimal.py \
        --case configs/exchange_economy/cases_v0/case01_visible_bilateral_ir.json \
        --seed 1200 --model deepseek/deepseek-v4-flash
"""
from __future__ import annotations

import argparse
import json
import os

from aeread.integrations.rllm_flow import run_episode


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True)
    ap.add_argument("--seed", type=int, default=1200)
    ap.add_argument("--model", default="deepseek/deepseek-v4-flash")
    ap.add_argument("--base-url",
                    default=os.environ.get("OPENAI_BASE_URL",
                                           "https://openrouter.ai/api/v1"))
    args = ap.parse_args()

    # API key resolves from env: AEREAD_GATEWAY_API_KEY or OPENAI_API_KEY.
    result = run_episode(args.case, args.seed, base_url=args.base_url,
                         model=args.model)
    print(json.dumps({k: result[k] for k in
                      ("status", "aer", "w_real", "denominator")}, indent=1))
    print(f"turns: {len(result['turns'])}")


if __name__ == "__main__":
    main()
