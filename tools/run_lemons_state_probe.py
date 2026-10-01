"""Same-state probe: give each lemons v2 model the other model's exact decision states.

Diagnostic, not a claim and not a campaign. The v2 cells are markets of one
model's six tenants, so a difference between the routes mixes each model's
policy with the histories and competition its own copies produced. This probe
removes the history: it takes decision states recorded in the sealed run roots
(the exact instructions, observation and action schema each tenant was sent),
sends the same state to both models, and compares what they decide.

Three sets, fixed before any call and written to ``plan.json``:

- ``sign_or_walk``: every commit state of a published completed pilot cell in
  which the tenant held an uninspected listing it had a nonzero chance of being
  a lemon, from both routes' runs;
- ``inspect_before_blind``: the inspect state of the same tenant and round for
  every such hold the tenant then signed;
- ``offer``: 40 contact states per route, drawn by a seeded sample.

Each state goes to each model ``--repeats`` times at the campaign's own sampling
(temperature, reasoning, output cap and route pin copied from that model's
recorded requests), with a seed fixed by state, model and repeat. One retry on a
timeout or transport failure; anything else is recorded as a failure. Results go
to ``runs/lemons_state_probe_v1/`` (ignored); ``--summarize`` prints the tables.

    PYTHONPATH=src python tools/run_lemons_state_probe.py --plan
    PYTHONPATH=src python tools/run_lemons_state_probe.py --run
    PYTHONPATH=src python tools/run_lemons_state_probe.py --summarize
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import glob
import hashlib
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeread_families.housing import lemons_comparison as comparison  # noqa: E402

OUT = ROOT / "runs" / "lemons_state_probe_v1"
MODELS = {"gemini": comparison.LEFT, "glm": comparison.RIGHT}
OFFER_SAMPLE = 40
SAMPLE_SEED = 20260927
TIMEOUT_SECONDS = 150.0
CONCURRENCY = 6
ROUTING_FIELDS = ("provider", "base_url", "model", "revision", "provider_metadata", "reasoning_effort",
                  "reasoning_token_budget", "max_output_tokens", "temperature", "top_p", "timeout_seconds", "max_cost_usd")


def _requests(bundle: str) -> tuple[dict, dict]:
    """Per published receipt, the first tenant request per (phase, round, seat); and one routing template."""
    published = {json.loads(l)["receipt_sha256"]: json.loads(l) for l in (comparison.EVIDENCE / bundle / "tables" / "cells.jsonl").read_text().splitlines()
                 if l.strip() and json.loads(l).get("stage") == "variance_pilot" and json.loads(l)["status"] == "completed"}
    states, template = {}, None
    for path in glob.glob(str(ROOT / "runs" / bundle / "variance_pilot" / "**" / "evaluation_receipt.json"), recursive=True):
        receipt = json.loads(Path(path).read_text()).get("receipt_sha256")
        if receipt not in published:
            continue
        folder = os.path.dirname(path)
        per = {}
        for line in open(os.path.join(folder, "events.jsonl")):
            event = json.loads(line)
            if event["event_type"] != "provider_call_started":
                continue
            request = json.load(open(os.path.join(folder, event["payload_ref"])))["request"]
            try:
                body = json.loads(request["input_text"])
            except (TypeError, ValueError):
                continue
            key = (body["phase_id"], int(body["observation"]["round_index"]), body["seat_id"])
            per.setdefault(key, request)
            template = template or request
        states[receipt] = (published[receipt], per)
    return states, template


def build_plan() -> dict:
    sets = []
    templates = {}
    rng = random.Random(SAMPLE_SEED)
    for source, bundle in MODELS.items():
        states, template = _requests(bundle)
        templates[source] = {k: template[k] for k in ROUTING_FIELDS}
        offers = []
        for receipt, (cell, per) in sorted(states.items()):
            world = comparison._world(int(cell["world_seed"]))
            for d in cell["commit_decisions"]:
                t, l = int(d["tenant_id"]), int(d["listing_id"])
                if d["informed"]:
                    continue
                p = (world.values_if_sound[t][l] - float(d["expected_value"])) / world.lemon_loss
                if p <= 1e-9:
                    continue
                meta = {"source": source, "receipt_sha256": receipt, "world_seed": cell["world_seed"], "replicate_index": cell["replicate_index"],
                        "round_index": int(d["round_index"]), "tenant_id": t, "listing_id": l, "rent": float(d["rent"]),
                        "expected_value": float(d["expected_value"]), "lemon_probability": round(p, 6), "quality": d["quality"],
                        "source_decision": d["decision"], "ask": float(world.ask[l]), "value_if_sound": float(world.values_if_sound[t][l])}
                commit = per.get(("commit", int(d["round_index"]), f"tenant_{t}"))
                if commit:
                    sets.append({"set": "sign_or_walk", **meta, "request": {k: commit[k] for k in ("instructions", "input_text", "output_schema")}})
                inspect = per.get(("inspect", int(d["round_index"]), f"tenant_{t}"))
                if inspect and d["decision"] == "sign":
                    sets.append({"set": "inspect_before_blind", **meta, "request": {k: inspect[k] for k in ("instructions", "input_text", "output_schema")}})
            for (phase, rnd, seat), request in sorted(per.items()):
                if phase == "contact":
                    offers.append({"set": "offer", "source": source, "receipt_sha256": receipt, "world_seed": cell["world_seed"],
                                   "replicate_index": cell["replicate_index"], "round_index": rnd, "tenant_id": int(seat.split("_")[1]),
                                   "request": {k: request[k] for k in ("instructions", "input_text", "output_schema")}})
        sets.extend(rng.sample(offers, min(OFFER_SAMPLE, len(offers))))
    for i, state in enumerate(sets):
        state["state_id"] = f"s{i:04d}_{state['set']}_{state['source']}"
    instructions = {s["request"]["instructions"] for s in sets}
    return {"schema_version": "aeread.lemons_state_probe/0.1", "created": "2026-09-25",
            "models": {k: {"campaign_id": v, "route": templates[k]} for k, v in MODELS.items()},
            "repeats": None, "timeout_seconds": TIMEOUT_SECONDS, "retries": "one retry on timeout or transport failure",
            "distinct_instructions": len(instructions), "states": sets}


def _seed(state_id: str, target: str, repeat: int) -> int:
    return int(hashlib.sha256(f"{state_id}|{target}|{repeat}".encode()).hexdigest()[:8], 16) % (2 ** 31)


async def run(plan: dict, repeats: int) -> None:
    from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderRequest

    client = OpenRouterChatClient()
    done = set()
    results_path = OUT / "results.jsonl"
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            r = json.loads(line)
            done.add((r["state_id"], r["target"], r["repeat"]))
    sem = asyncio.Semaphore(CONCURRENCY)
    fields = set(ProviderRequest.__dataclass_fields__)

    async def one(state, target, repeat):
        if (state["state_id"], target, repeat) in done:
            return
        route = plan["models"][target]["route"]
        spec = {**route, **state["request"], "seed": _seed(state["state_id"], target, repeat),
                "provider_call_id": f"probe_{hashlib.sha256((state['state_id'] + target + str(repeat)).encode()).hexdigest()[:20]}",
                "request_sha256": ""}
        request = ProviderRequest(**{k: v for k, v in spec.items() if k in fields and k not in ("messages", "tools")}).with_computed_hash()
        record = {"state_id": state["state_id"], "set": state["set"], "source": state["source"], "target": target, "repeat": repeat}
        async with sem:
            for attempt in range(2):
                start = time.time()
                try:
                    result = await asyncio.wait_for(client.complete(request), TIMEOUT_SECONDS)
                    try:
                        action = json.loads(result.output_text)
                    except (TypeError, ValueError):
                        action = None
                    record.update({"status": "ok", "action": action, "cost_usd": result.cost_usd, "seconds": round(time.time() - start, 2),
                                   "attempts": attempt + 1})
                    break
                except Exception as error:  # a probe records its failures; they are never scored
                    kind = type(error).__name__
                    record.update({"status": "failed", "failure": f"{kind}: {str(error)[:160]}", "seconds": round(time.time() - start, 2),
                                   "attempts": attempt + 1})
                    transient = isinstance(error, asyncio.TimeoutError) or "transport" in str(error).lower() or "timeout" in str(error).lower()
                    if not transient:
                        break
        with results_path.open("a") as handle:
            handle.write(json.dumps(record) + "\n")

    jobs = [one(s, t, r) for s in plan["states"] for t in plan["models"] for r in range(repeats)]
    await asyncio.gather(*jobs)


def summarize(plan: dict) -> dict:
    states = {s["state_id"]: s for s in plan["states"]}
    rows = [json.loads(l) for l in (OUT / "results.jsonl").read_text().splitlines() if l.strip()]
    ok = [r for r in rows if r["status"] == "ok" and isinstance(r.get("action"), dict)]
    out: dict = {"calls": len(rows), "ok": len(ok), "failed": len(rows) - len(ok),
                 "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 4), "tables": {}}

    def rate(xs):
        return {"n": len(xs), "rate": round(sum(xs) / len(xs), 3) if xs else None}

    table = collections.defaultdict(dict)
    for target in plan["models"]:
        mine = [r for r in ok if r["target"] == target]
        sw = [r for r in mine if r["set"] == "sign_or_walk"]
        good = [r for r in sw if states[r["state_id"]]["expected_value"] >= states[r["state_id"]]["rent"]]
        bad = [r for r in sw if states[r["state_id"]]["expected_value"] < states[r["state_id"]]["rent"]]
        table["sign_or_walk"][target] = {
            "sign_when_worth_it": rate([r["action"].get("decision") == "sign" for r in good]),
            "sign_when_not_worth_it": rate([r["action"].get("decision") == "sign" for r in bad]),
            **{f"sign_on_{src}_states": rate([r["action"].get("decision") == "sign" for r in sw if r["source"] == src]) for src in plan["models"]},
        }
        ins = [r for r in mine if r["set"] == "inspect_before_blind"]
        table["inspect_before_blind"][target] = {
            "inspects": rate([r["action"].get("decision") == "inspect" for r in ins]),
            "inspects_the_listing_later_signed_blind": rate([r["action"].get("decision") == "inspect" and r["action"].get("listing_id") == states[r["state_id"]]["listing_id"] for r in ins]),
        }
        offers = [r for r in mine if r["set"] == "offer"]
        gaps = []
        for r in offers:
            a = r["action"]
            if a.get("decision") != "offer":
                continue
            board = json.loads(states[r["state_id"]]["request"]["input_text"])["observation"]["board"]
            asks = {row["listing_id"]: float(row["rent_asked"]) for row in board}
            if a.get("listing_id") in asks and isinstance(a.get("rent"), (int, float)):
                gaps.append(float(a["rent"]) - asks[a["listing_id"]])
        table["offer"][target] = {"offers": rate([r["action"].get("decision") == "offer" for r in offers]),
                                  "offer_above_ask": rate([g > 0 for g in gaps]),
                                  "mean_offer_minus_ask": round(sum(gaps) / len(gaps), 2) if gaps else None}
    out["tables"] = table
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--summarize", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    plan_path = OUT / "plan.json"
    if args.plan:
        plan = build_plan()
        plan["repeats"] = args.repeats
        plan_path.write_text(json.dumps(plan, indent=1, sort_keys=True))
        counts = collections.Counter((s["set"], s["source"]) for s in plan["states"])
        print(json.dumps({"states": {f"{a}/{b}": n for (a, b), n in sorted(counts.items())},
                          "calls": len(plan["states"]) * len(plan["models"]) * args.repeats,
                          "distinct_instructions": plan["distinct_instructions"],
                          "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest()}, indent=1))
    if args.run:
        plan = json.loads(plan_path.read_text())
        asyncio.run(run(plan, plan["repeats"]))
    if args.summarize:
        print(json.dumps(summarize(json.loads(plan_path.read_text())), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
