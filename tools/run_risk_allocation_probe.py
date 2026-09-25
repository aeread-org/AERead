"""Probe: can a model negotiate who carries which risk? (integrator-client case)

A diagnostic, not a campaign. It plays the dev pack of the risk-allocation case
(both seats of every world) against live models through OpenRouter, every move
through the environment plugin, and grades each decision against the best play
on the model's own information. Nothing here is a published claim.

    python tools/run_risk_allocation_probe.py prepare runs/risk_allocation_probe_v1
    python tools/run_risk_allocation_probe.py execute runs/risk_allocation_probe_v1 [--route reference]
    python tools/run_risk_allocation_probe.py grade   runs/risk_allocation_probe_v1

``prepare`` freezes the plan (pack digests, routes, sampling, every limit) with
source digests; ``execute`` refuses a plan whose sources or cases changed,
writes one record per call and never reruns an episode; ``grade`` reads only the
records. ``--route reference`` plays the reference through the same path with
no network, which must grade zero regret everywhere. Raw provider records stay
under ignored ``runs/``.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeread.shared_runner.task.execution import CanonicalResponse  # noqa: E402
from aeread.shared_runner.task.scheduler import ActionEnvelope  # noqa: E402
from aeread_families.datacenter_development import risk_allocation as ra  # noqa: E402
from aeread_families.datacenter_development import risk_allocation_pack as rp  # noqa: E402
from aeread_families.datacenter_development.risk_allocation_environment import (  # noqa: E402
    ACTION_JSON_SCHEMA,
    RiskAllocationPlugin,
    game_of,
    grade,
    seen_of,
)

# On this network Python's urllib tries IPv6 first and each attempt hangs about
# 150 s before falling back (P-T-10). Prefer IPv4 for this tool only.
_getaddrinfo = socket.getaddrinfo


def _prefer_ipv4(host, *args, **kwargs):  # type: ignore[no-untyped-def]
    found = _getaddrinfo(host, *args, **kwargs)
    return [r for r in found if r[0] == socket.AF_INET] or found


socket.getaddrinfo = _prefer_ipv4

API = "https://openrouter.ai/api/v1/chat/completions"
PROBE_ID = "risk_allocation_probe_v1"
PACK = "risk_allocation_dev_v1"

# The same routes as the supplier-judgment probe.
ROUTES = {
    "gemini38_flash": {"model": "google/gemini-3.8-flash", "provider": "Google AI Studio"},
    "glm53_flash": {"model": "z-ai/glm-5.3-flash", "provider": "Parasail"},
}

# Every limit that can end or change a run is here and frozen into the plan.
LIMITS = {
    "temperature": 1.0,
    "reasoning_effort": "low",
    "max_output_tokens": 4000,
    "timeout_seconds": 180,
    "max_attempts": 3,  # retries only on 429 and 5xx, which cost nothing
    "max_cost_usd_total": 3.0,
    "runs_per_case": 1,
    "workers": 6,
}

SOURCES = (
    "src/aeread_families/datacenter_development/risk_allocation.py",
    "src/aeread_families/datacenter_development/risk_allocation_environment.py",
    "src/aeread_families/datacenter_development/risk_allocation_pack.py",
    "tools/run_risk_allocation_probe.py",
)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def source_digests() -> dict[str, str]:
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}


def system_prompt(seat: str) -> str:
    return (
        f"You are negotiating a contract on behalf of the {seat}. Each turn, read the brief and the negotiation so far, "
        "then reply with exactly one JSON object and nothing else:\n"
        '{"action": "propose" | "accept" | "walk", '
        '"package": {"warranty": "none|fix|fix_and_delay", "readiness": "client|integrator", '
        '"consequential": "excluded|included", "deposit": "at_signing|on_delivery"} or null, '
        '"price": <number in $ thousands> or null, "reason": "<one or two sentences>"}\n'
        "A proposal always states the full package. Use price null to ask the other side for its price for that package "
        "without committing. For accept and walk, package and price are null. Accept takes the standing offer as it stands."
    )


def user_prompt(obs: dict[str, Any]) -> str:
    lines = [obs["brief"], "", f"Round {obs['round']} of {obs['rounds']}."]
    if obs["history"]:
        lines.append("So far:")
        for h in obs["history"]:
            price = "no price (asked for theirs)" if h["your_price"] is None else f"{h['your_price']:,.1f}"
            pkg = "/".join(h["you_proposed"][k] for k in ra.TERMS)
            lines.append(f"- Round {h['round']}: you proposed {pkg} at {price}; they {h['answer']}.")
    if obs["standing_offer"]:
        pkg = "/".join(obs["standing_offer"]["package"][k] for k in ra.TERMS)
        lines.append(f"Standing offer: {pkg} (warranty/readiness/consequential/deposit) at {obs['standing_offer']['price']:,.1f}.")
    else:
        lines.append("There is no standing offer.")
    if obs["final"]:
        lines.append("This was their last answer: you may only accept it or walk.")
    lines.append(f"Allowed actions now: {', '.join(obs['allowed_actions'])}. Reply with one JSON object.")
    return "\n".join(lines)


def episodes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for world in manifest["worlds"]:
        for seat, s in world["seats"].items():
            for run in range(LIMITS["runs_per_case"]):
                out.append({"episode_id": f"{s['case_id'].rsplit('.', 1)[-1]}_r{run}", "case_id": s["case_id"], "seat": seat,
                            "cell": world["cell"], "slug": world["slug"], "run": run})
    return out


def prepare(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=False)
    manifest, cases = rp.load(PACK)
    plan = {
        "probe_id": PROBE_ID,
        "claim_status": "diagnostic",
        "pack": PACK,
        "pack_manifest_sha256": digest(manifest),
        "case_sha256": {k: v["content_sha256"] for k, v in sorted(cases.items())},
        "routes": ROUTES,
        "limits": LIMITS,
        "action_schema": ACTION_JSON_SCHEMA,
        "system_prompts": {seat: system_prompt(seat) for seat in ra.SEATS},
        "sources": source_digests(),
        "episodes": episodes(manifest),
    }
    plan["plan_sha256"] = digest(plan)
    (directory / "plan.json").write_text(json.dumps(plan, indent=1))
    n = len(plan["episodes"])
    print(f"prepared {n} episodes x {len(ROUTES)} routes = {n * len(ROUTES)} (at most {n * len(ROUTES) * 3} calls) -> {directory}/plan.json")


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
        "response_format": {"type": "json_schema", "json_schema": {"name": "move", "strict": False, "schema": ACTION_JSON_SCHEMA}},
        "usage": {"include": True},
    }
    last: dict[str, Any] = {}
    for attempt in range(1, limits["max_attempts"] + 1):
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=limits["timeout_seconds"]) as resp:
                return {"ok": True, "attempts": attempt, "response": json.loads(resp.read().decode())}
        except urllib.error.HTTPError as exc:
            last = {"ok": False, "attempts": attempt, "status": exc.code, "error": exc.read().decode()[:500]}
            if exc.code != 429 and exc.code < 500:
                return last
        except (urllib.error.URLError, TimeoutError) as exc:
            return {"ok": False, "attempts": attempt, "status": None, "error": str(exc)[:500]}
        time.sleep(2 * attempt)
    return last


def _reference_text(payload: dict[str, Any], state: dict[str, Any]) -> str:
    game, _ = game_of(payload)
    a = ra.reference_policy(game)(seen_of(payload, state))
    if a.kind != "propose":
        return json.dumps({"action": a.kind, "package": None, "price": None, "reason": "reference"})
    return json.dumps({"action": "propose", "package": a.package.as_dict(), "price": None if a.price == ra.PRICE_IT else a.price, "reason": "reference"})


def play(ep: dict[str, Any], raw: dict[str, Any], route_id: str, key: str | None, budget: Budget, out: Path) -> dict[str, Any]:
    plugin = RiskAllocationPlugin()
    payload = plugin.validate_payload(raw["payload"])
    seat = payload["seat"]
    phase = plugin.phases(payload)[0]
    state = plugin.initial_state(payload, None)
    turns: list[dict[str, Any]] = []
    status = "completed"
    while not state["finished"]:
        if len(turns) >= raw["episode"]["max_logical_actions"]:
            status = "action_cap"  # cannot happen under the phase contract; recorded if it does
            break
        obs = plugin.observe(payload, state, seat, phase)
        user = user_prompt(obs)
        if route_id == "reference":
            rec, text, cost = {"ok": True, "attempts": 0}, _reference_text(payload, state), 0.0
        else:
            if budget.exhausted():
                status = "not_attempted_budget"
                break
            rec = call(ROUTES[route_id], system_prompt(seat), user, LIMITS, key)
            cost = float(((rec.get("response") or {}).get("usage") or {}).get("cost") or 0.0)
            budget.add(cost)
            if not rec.get("ok"):
                turns.append({"user": user, "record": rec, "cost_usd": cost})
                status = "provider_failure"
                break
            try:
                text = rec["response"]["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                text = ""
        response = CanonicalResponse(text, "stop", not text, False, (), (), 0, 0, 0, cost)
        parsed = plugin.parse_action(payload, state, seat, phase, response)
        legality = plugin.legal(payload, state, seat, phase, parsed.action) if parsed.ok else None
        envelope = ActionEnvelope(seat, bool(parsed.ok and legality.legal), parsed.action if parsed.ok else None, parsed, legality)
        turns.append({"user": user, "record": rec, "text": text, "parse_error": parsed.error_code,
                      "illegal": None if legality is None or legality.legal else legality.reason, "cost_usd": cost})
        state = plugin.step(payload, state, phase, {seat: envelope}).state
    result = {**ep, "route_id": route_id, "status": status, "turns": turns, "final_state": state}
    (out / "episodes" / f"{route_id}__{ep['episode_id']}.json").write_text(json.dumps(result, indent=1))
    return result


def load_key() -> str:
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    for line in (Path(os.environ.get("AEREAD_ENV_FILE", "/Users/chenyusu/AERead/.env"))).read_text().splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("OPENROUTER_API_KEY not found in .env")


def _check_plan(directory: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    plan = json.loads((directory / "plan.json").read_text())
    if plan["sources"] != source_digests():
        raise SystemExit("sources changed since prepare; prepare a new probe directory")
    manifest, cases = rp.load(plan["pack"])
    if digest(manifest) != plan["pack_manifest_sha256"] or {k: v["content_sha256"] for k, v in sorted(cases.items())} != plan["case_sha256"]:
        raise SystemExit("pack differs from the frozen plan")
    return plan, cases


def execute(directory: Path, route: str | None) -> None:
    plan, cases = _check_plan(directory)
    (directory / "episodes").mkdir(exist_ok=True)
    routes = [route] if route else list(plan["routes"])
    key = None if routes == ["reference"] else load_key()
    budget = Budget(plan["limits"]["max_cost_usd_total"])
    jobs = [(ep, r) for ep in plan["episodes"] for r in routes if not (directory / "episodes" / f"{r}__{ep['episode_id']}.json").exists()]
    with cf.ThreadPoolExecutor(plan["limits"]["workers"]) as pool:
        futs = [pool.submit(play, ep, cases[ep["case_id"]], r, key, budget, directory) for ep, r in jobs]
        for f in cf.as_completed(futs):
            res = f.result()
            print(f"{res['route_id']:<15} {res['seat']:<10} {res['cell']:<24} {res['status']:<18} {res['final_state']['termination']}")
    print(f"spent ${budget.spent:.4f} of ${budget.cap:.2f}")


def grade_all(directory: Path) -> None:
    plan, cases = _check_plan(directory)
    manifest, _ = rp.load(plan["pack"])
    rows = []
    for path in sorted((directory / "episodes").glob("*.json")):
        ep = json.loads(path.read_text())
        g = grade(cases[ep["case_id"]]["payload"], ep["final_state"])
        cost = sum(t.get("cost_usd", 0.0) for t in ep["turns"])
        rows.append({**{k: ep[k] for k in ("route_id", "seat", "cell", "slug", "episode_id", "status")}, **g, "cost_usd": cost,
                     "reasons": [(json.loads(t["text"]).get("reason") if t.get("text") and t["text"].strip().startswith("{") else None) for t in ep["turns"]]})
    (directory / "graded.json").write_text(json.dumps(rows, indent=1))
    table: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    missing: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        if r["status"] != "completed" or not r["valid"]:
            missing[(r["route_id"], r["seat"])] += 1
            continue
        table[(r["route_id"], r["seat"])][r["cell"]].append(r["decision_regret"])
    cells = list(ra.CELLS)
    print("mean decision regret, $k (valid episodes; missing = invalid or provider failure)")
    print(f"{'route/seat':<32}" + "".join(f"{c[:14]:>16}" for c in cells) + f"{'all':>10}{'missing':>9}")
    for key in sorted(set(table) | set(missing)):
        vals = table[key]
        allv = [v for c in cells for v in vals.get(c, [])]
        line = f"{key[0] + '/' + key[1]:<32}" + "".join(f"{(sum(vals[c]) / len(vals[c])) if vals.get(c) else float('nan'):>16.1f}" for c in cells)
        print(line + f"{(sum(allv) / len(allv)) if allv else float('nan'):>10.1f}{missing[key]:>9}")
    print("rule regret over the prior, $k, from pack.json:")
    for seat in ra.SEATS:
        names = list(manifest["worlds"][0]["seats"][seat]["rule_regret_prior"])
        for name in names:
            per = {c: [w["seats"][seat]["rule_regret_prior"][name] for w in manifest["worlds"] if w["cell"] == c] for c in cells}
            allv = [v for c in cells for v in per[c]]
            print(f"{seat + '/' + name:<32}" + "".join(f"{sum(per[c]) / len(per[c]):>16.1f}" for c in cells) + f"{sum(allv) / len(allv):>10.1f}")
    print(f"cost ${sum(r['cost_usd'] for r in rows):.4f}; terminations: "
          + ", ".join(f"{k}={v}" for k, v in sorted(defaultdict(int, {t: sum(1 for r in rows if r['termination'] == t) for t in {r['termination'] for r in rows}}).items(), key=lambda kv: str(kv[0]))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["prepare", "execute", "grade"])
    ap.add_argument("directory", type=Path)
    ap.add_argument("--route", choices=[*ROUTES, "reference"])
    args = ap.parse_args()
    if args.command == "prepare":
        prepare(args.directory)
    elif args.command == "execute":
        execute(args.directory, args.route)
    else:
        grade_all(args.directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
