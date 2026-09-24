"""Probe: can a model judge a supplier from its record? (hidden-information draft)

A diagnostic, not a campaign. It plays the four-cell pack of
``supplier_profiles`` against live models through OpenRouter and grades every
decision against the best policy on the buyer's information. Nothing here is a
published claim.

    python tools/run_supplier_judgment_probe.py prepare runs/supplier_judgment_probe_v1
    python tools/run_supplier_judgment_probe.py execute runs/supplier_judgment_probe_v1
    python tools/run_supplier_judgment_probe.py grade   runs/supplier_judgment_probe_v1

``prepare`` freezes the plan (pack, routes, sampling, every limit) with source
digests; ``execute`` refuses a plan whose sources changed, writes one record per
call and never reruns a failed episode; ``grade`` reads only the records.
Raw provider records stay under ignored ``runs/``.
"""

from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import math
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeread_families.procurement_allocation import supplier_profiles as sp  # noqa: E402

API = "https://openrouter.ai/api/v1/chat/completions"
PROBE_ID = "supplier_judgment_probe_v1"

# Same routes and sampling as the repeated-sourcing confirmatory.
ROUTES = {
    "gemini38_flash": {"model": "google/gemini-3.8-flash", "provider": "Google AI Studio"},
    "glm53_flash": {"model": "z-ai/glm-5.3-flash", "provider": "Parasail"},
}

# Every limit that can end or change a run is here and frozen into the plan.
LIMITS = {
    "temperature": 1.0,
    "reasoning_effort": "low",
    "max_output_tokens": 1800,
    "timeout_seconds": 120,
    "max_attempts": 3,  # retries only on 429 and 5xx, which cost nothing
    "max_cost_usd_total": 2.0,
    "seeds_per_cell": 3,
    "base_seed": 2440000,
    "workers": 6,
}

SOURCES = ("src/aeread_families/procurement_allocation/supplier_profiles.py", "tools/run_supplier_judgment_probe.py")

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["action", "supplier_id", "p_bad", "reason"],
    "properties": {
        "action": {"type": "string", "enum": ["sample", "buy"]},
        "supplier_id": {"type": "string"},
        "p_bad": {
            "type": "object",
            "description": "your probability, 0 to 1, that each supplier is a bad supplier, keyed by supplier_id",
            "additionalProperties": {"type": "number"},
        },
        "reason": {"type": "string", "description": "one or two sentences"},
    },
}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_digests() -> dict[str, str]:
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}


def system_prompt(econ: dict[str, Any]) -> str:
    return (
        "You are a procurement buyer sourcing one component, a display module, for "
        f"{econ['periods']} purchase periods of {econ['lot_units']} units each. Each unit goes into a kit that "
        f"sells for ${econ['revenue_per_unit']:.0f}; a defective unit loses its kit. Two suppliers offer the same "
        "part at fixed quoted unit prices. Your goal is to maximise total value over all periods: "
        "revenue lost to defects plus what you pay (for units and samples) should be as small as possible.\n\n"
        "Each period you may first order one sample from one supplier (at most one sample per period, and a "
        f"supplier can be sampled only once): {econ['sample_units']} units, tested, and you see how many are "
        f"defective. A sample costs ${econ['sample_cost']:.2f}. Then you buy the period's whole lot from one "
        "supplier. You can buy from a supplier without sampling it. When a lot is delivered you see its defects, "
        "and that shows for certain which kind of supplier it is.\n\n"
        "What is known about this marketplace:\n" + sp.market_facts_text() + "\n\n"
        "Reply with JSON: action ('sample' or 'buy'), supplier_id, p_bad (your probability that each supplier "
        "is a bad supplier, for both suppliers), and a one- or two-sentence reason."
    )


def world_text(world: dict[str, Any], history: list[str], period: int, sampled_this_period: bool) -> str:
    econ = world["economics"]
    prices = {}
    for role, prof in world["profiles_in_listing_order"].items():
        prices[prof["supplier_id"]] = econ["incumbent_price"] if role == "I" else econ["challenger_price"]
    lines = ["Suppliers (you have bought from neither before this order):"]
    for role, text in world["profile_text"].items():
        sid = world["profiles_in_listing_order"][role]["supplier_id"]
        lines.append(f"- {text}. Quoted unit price ${prices[sid]:.3f}.")
    lines.append("")
    lines.append("What has happened so far:" if history else "Nothing has happened yet.")
    lines += [f"- {h}" for h in history]
    lines.append("")
    if sampled_this_period:
        lines.append(f"Period {period} of {econ['periods']}: you have taken this period's sample; now choose the supplier to buy the lot from (action 'buy').")
    else:
        lines.append(f"Period {period} of {econ['periods']}: sample one supplier first (action 'sample'), or buy the lot now (action 'buy').")
    return "\n".join(lines)


def build_worlds(plan: dict[str, Any]) -> list[dict[str, Any]]:
    pack = sp.build_pack(plan["limits"]["seeds_per_cell"], plan["limits"]["base_seed"])
    worlds = []
    for i, w in enumerate(pack):
        wid = f"{w['cell']}_{w['seed']}" + ("_twin" if "twin_of" in w else "")
        worlds.append({**w, "world_id": wid, "index": i})
    return worlds


def draws(world: dict[str, Any]) -> dict[str, Any]:
    """Common random numbers: every model sees the same sample and lot outcomes."""
    rng = random.Random(f"{world['world_id']}|outcomes")
    econ, out = world["economics"], {"sample": {}, "lot": {}}
    for role in ("I", "C"):
        d = sp.MARKET["type"][world["hidden"][role]]["defect_rate"]
        out["sample"][role] = sum(rng.random() < d for _ in range(econ["sample_units"]))
        out["lot"][role] = [sum(rng.random() < d for _ in range(econ["lot_units"])) for _ in range(econ["periods"])]
    return out


def prepare(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    plan = {
        "probe_id": PROBE_ID,
        "claim_status": "diagnostic",
        "routes": ROUTES,
        "limits": LIMITS,
        "market": sp.MARKET,
        "market_sha256": digest(sp.MARKET),
        "schema": SCHEMA,
        "sources": source_digests(),
    }
    worlds = build_worlds(plan)
    plan["worlds"] = [{"world_id": w["world_id"], "cell": w["cell"], "hidden": w["hidden"]} for w in worlds]
    plan["pack_sha256"] = digest([{k: v for k, v in w.items() if k != "index"} for w in worlds])
    plan["plan_sha256"] = digest(plan)
    (directory / "plan.json").write_text(json.dumps(plan, indent=1, default=str))
    print(f"prepared {len(worlds)} worlds x {len(ROUTES)} routes -> {directory}/plan.json")


class Budget:
    def __init__(self, cap: float) -> None:
        self.cap, self.spent, self.lock = cap, 0.0, threading.Lock()

    def add(self, cost: float) -> None:
        with self.lock:
            self.spent += cost

    def exhausted(self) -> bool:
        with self.lock:
            return self.spent >= self.cap


def call(route: dict[str, str], system: str, user: str, limits: dict[str, Any], key: str) -> dict[str, Any]:
    body = {
        "model": route["model"],
        "provider": {"order": [route["provider"]], "allow_fallbacks": False, "require_parameters": True},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": limits["temperature"],
        "max_tokens": limits["max_output_tokens"],
        "reasoning": {"effort": limits["reasoning_effort"], "exclude": True},
        "response_format": {"type": "json_schema", "json_schema": {"name": "decision", "strict": False, "schema": SCHEMA}},
        "usage": {"include": True},
    }
    last: dict[str, Any] = {}
    for attempt in range(1, limits["max_attempts"] + 1):
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=limits["timeout_seconds"]) as resp:
                obj = json.loads(resp.read().decode())
            return {"ok": True, "attempts": attempt, "response": obj}
        except urllib.error.HTTPError as exc:
            last = {"ok": False, "attempts": attempt, "status": exc.code, "error": exc.read().decode()[:500]}
            if exc.code != 429 and exc.code < 500:
                return last
        except (urllib.error.URLError, TimeoutError) as exc:
            last = {"ok": False, "attempts": attempt, "status": None, "error": str(exc)[:500]}
            return last
        time.sleep(2 * attempt)
    return last


def parse(obj: dict[str, Any]) -> dict[str, Any] | None:
    try:
        content = obj["choices"][0]["message"]["content"]
        start, end = content.index("{"), content.rindex("}") + 1
        return json.loads(content[start:end])
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def play(world: dict[str, Any], route_id: str, plan: dict[str, Any], key: str, budget: Budget, out: Path) -> dict[str, Any]:
    econ = world["economics"]
    ids = {role: world["profiles_in_listing_order"][role]["supplier_id"] for role in ("I", "C")}
    role_of = {v: k for k, v in ids.items()}
    outcome = draws(world)
    system = system_prompt(econ)
    history: list[str] = []
    sampled: set[str] = set()
    decisions: list[dict[str, Any]] = []
    status = "completed"
    for period in range(1, econ["periods"] + 1):
        sampled_now = False
        while True:
            if budget.exhausted():
                status = "not_attempted_budget"
                break
            user = world_text(world, history, period, sampled_now)
            rec = call(ROUTES[route_id], system, user, plan["limits"], key)
            cost = float(((rec.get("response") or {}).get("usage") or {}).get("cost") or 0.0)
            budget.add(cost)
            parsed = parse(rec["response"]) if rec.get("ok") else None
            entry = {"period": period, "after_sample": sampled_now, "user": user, "record": rec, "parsed": parsed, "cost_usd": cost}
            if parsed is None:
                entry["invalid"] = "provider_failure" if not rec.get("ok") else "unparseable"
                decisions.append(entry)
                status = "failed_" + entry["invalid"]
                break
            action, sid = parsed.get("action"), parsed.get("supplier_id")
            role = role_of.get(sid)
            invalid = None
            if role is None:
                invalid = "unknown_supplier"
            elif action == "sample" and (sampled_now or role in sampled):
                invalid = "sample_not_allowed"
            elif action not in ("sample", "buy"):
                invalid = "unknown_action"
            entry.update({"action": action, "role": role, "invalid": invalid})
            decisions.append(entry)
            if invalid:
                status = "failed_" + invalid
                break
            if action == "sample":
                sampled.add(role)
                sampled_now = True
                d = outcome["sample"][role]
                history.append(f"Period {period}: sampled {sid} for ${econ['sample_cost']:.2f}; {d} of {econ['sample_units']} units defective.")
                continue
            d = outcome["lot"][role][period - 1]
            kind = world["hidden"][role]
            history.append(f"Period {period}: bought the lot from {sid}; {d} of {econ['lot_units']} units defective, so {sid} is a {kind} supplier.")
            break
        if status != "completed":
            break
    result = {"world_id": world["world_id"], "route_id": route_id, "status": status, "decisions": decisions,
              "ids": ids, "outcome_draws": outcome}
    path = out / "episodes" / f"{route_id}__{world['world_id']}.json"
    path.write_text(json.dumps(result, indent=1))
    return result


def load_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    for line in (Path(os.environ.get("AEREAD_ENV_FILE", "/Users/chenyusu/AERead/.env"))).read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("OPENROUTER_API_KEY not found in .env")


def execute(directory: Path) -> None:
    plan = json.loads((directory / "plan.json").read_text())
    if plan["sources"] != source_digests():
        raise SystemExit("sources changed since prepare; prepare a new probe directory")
    worlds = build_worlds(plan)
    if digest([{k: v for k, v in w.items() if k != "index"} for w in worlds]) != plan["pack_sha256"]:
        raise SystemExit("pack differs from the frozen plan")
    (directory / "episodes").mkdir(exist_ok=True)
    key = load_key()
    budget = Budget(plan["limits"]["max_cost_usd_total"])
    jobs = [(w, r) for w in worlds for r in ROUTES if not (directory / "episodes" / f"{r}__{w['world_id']}.json").exists()]
    with cf.ThreadPoolExecutor(plan["limits"]["workers"]) as pool:
        futs = {pool.submit(play, w, r, plan, key, budget, directory): (w["world_id"], r) for w, r in jobs}
        for f in cf.as_completed(futs):
            res = f.result()
            print(f"{res['route_id']:<15} {res['world_id']:<32} {res['status']}")
    print(f"spent ${budget.spent:.4f} of ${budget.cap:.2f}")


def beliefs_along(world: dict[str, Any], episode: dict[str, Any]) -> list[tuple[dict[str, Any], float, float, set[str]]]:
    """Replay the buyer's exact beliefs at each decision from the records."""
    bI, bC = world["posterior_bad"]["I"], world["posterior_bad"]["C"]
    econ = world["economics"]
    sampled: set[str] = set()
    out = []
    for dec in episode["decisions"]:
        out.append((dec, bI, bC, set(sampled)))
        if dec.get("invalid") or dec.get("role") is None:
            break
        role = dec["role"]
        if dec["action"] == "sample":
            d = episode["outcome_draws"]["sample"][role]
            nb = sp._update(bI if role == "I" else bC, econ["sample_units"], d, sp.MARKET)
            sampled.add(role)
        else:
            nb = 1.0 if world["hidden"][role] == "bad" else 0.0
        bI, bC = (nb, bC) if role == "I" else (bI, nb)
    return out


def grade(directory: Path) -> None:
    plan = json.loads((directory / "plan.json").read_text())
    worlds = {w["world_id"]: w for w in build_worlds(plan)}
    rows = []
    for path in sorted((directory / "episodes").glob("*.json")):
        ep = json.loads(path.read_text())
        w = worlds[ep["world_id"]]
        econ = sp.Economics(**w["economics"])
        loss, first, brier, belief_gap, n_beliefs = 0.0, None, 0.0, 0.0, 0
        for dec, bI, bC, sampled in beliefs_along(w, ep):
            if dec.get("invalid"):
                continue
            left = econ.periods - dec["period"] + 1
            sub = sp.Economics(**{**asdict(econ), "periods": left})
            q = sp._state_values(sub, bI, bC, "I" in sampled, "C" in sampled, sp.MARKET, buy_only=dec["after_sample"])
            chosen = f"{dec['action']}_{dec['role']}"
            loss += max(q.values()) - q[chosen]
            if first is None:
                first = chosen
                for role, b in (("I", bI), ("C", bC)):
                    stated = (dec["parsed"].get("p_bad") or {}).get(ep["ids"][role])
                    if isinstance(stated, (int, float)) and 0 <= stated <= 1:
                        belief_gap += abs(stated - b)
                        brier += (stated - (1.0 if w["hidden"][role] == "bad" else 0.0)) ** 2
                        n_beliefs += 1
        cost = sum(d.get("cost_usd", 0.0) for d in ep["decisions"])
        rows.append({
            "route": ep["route_id"], "world": ep["world_id"], "cell": w["cell"], "status": ep["status"],
            "first_action": first, "intended": sp.CELLS[w["cell"]]["intended"],
            "decision_regret_usd": round(loss, 2) if ep["status"] == "completed" else None,
            "first_belief_gap": round(belief_gap / n_beliefs, 3) if n_beliefs else None,
            "first_brier": round(brier / n_beliefs, 3) if n_beliefs else None,
            "posterior_C": round(w["posterior_bad"]["C"], 3), "cost_usd": round(cost, 5),
        })
    (directory / "graded.json").write_text(json.dumps(rows, indent=1))
    by: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault((r["route"], r["cell"]), []).append(r)
    print(f"{'route':<15} {'cell':<18} {'n':>2} {'done':>4} {'first=best':>10} {'regret $ mean':>13} {'|p-post|':>8} cost")
    for (route, cell), rs in sorted(by.items()):
        done = [r for r in rs if r["status"] == "completed"]
        hit = sum(r["first_action"] == r["intended"] for r in rs if r["first_action"])
        reg = [r["decision_regret_usd"] for r in done]
        gap = [r["first_belief_gap"] for r in rs if r["first_belief_gap"] is not None]
        print(f"{route:<15} {cell:<18} {len(rs):>2} {len(done):>4} {hit:>6}/{len(rs):<3} {sum(reg)/len(reg) if reg else float('nan'):>13.2f} "
              f"{sum(gap)/len(gap) if gap else float('nan'):>8.3f} ${sum(r['cost_usd'] for r in rs):.4f}")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("prepare", "execute", "grade"):
        print(__doc__)
        return 2
    directory = Path(sys.argv[2])
    {"prepare": prepare, "execute": execute, "grade": grade}[sys.argv[1]](directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
