"""Probe: can a model negotiate who carries which risk? (integrator-client case)

A diagnostic, not a campaign. It plays the dev pack of the risk-allocation case
(both seats of every world) against live models through OpenRouter, every move
through the environment plugin, and grades each decision against the best play
on the model's own information. Nothing here is a published claim.

    python tools/run_risk_allocation_probe.py prepare runs/<arm> --arm <arm>
    python tools/run_risk_allocation_probe.py execute runs/<arm> [--route reference]
    python tools/run_risk_allocation_probe.py grade   runs/<arm>
    python tools/run_risk_allocation_probe.py smoke   runs/<smoke dir> --arm <arm>

Each arm is a probe identity (:data:`ARMS`) and changes one thing from v1.
``smoke`` sends a few first-round prompts per route with a large output limit
and records reply lengths, from which an arm's output limit is sized by the
declared rule (DC-O-08: v1's limit truncated 11 of GLM's 32 episodes).

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
import http.client
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
    ACTION_JSON_SCHEMA_ALTERNATES,
    RiskAllocationPlugin,
    alternates_of,
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

# Output limits for v2 arms come from `smoke` by this rule, per route and arm.
CAP_RULE = "twice the longest smoke reply (completion tokens, reasoning included), rounded up to 1,000, at least 4,000"

# One probe identity per arm. v1 is kept as run. A reasoning effort of None
# declares no reasoning setting at all: on GLM 5.3 any declared reasoning value
# acts as a switch, so the provider's default deliberation needs nothing sent.
ARMS: dict[str, dict[str, Any]] = {
    "risk_allocation_probe_v1": {"pack": PACK, "limits": LIMITS},
    # Smoke 2026-09-25 (runs/risk_allocation_smoke_v2): Gemini's longest reply 13,365 tokens, all 6
    # finished; GLM hit the 32,000-token smoke limit in 3 of 6, so its length is censored and GLM
    # is sized by a longer smoke under its own identity below.
    "risk_allocation_probe_v2_default_reasoning": {
        "pack": PACK,
        "routes": ["gemini38_flash"],
        "changes_from_v1": "no reasoning setting declared; output limit from smoke; Gemini only (GLM's smoke was censored)",
        "limits": {**LIMITS, "reasoning_effort": None, "max_output_tokens": {"gemini38_flash": 27000},
                   "max_cost_usd_total": 6.0, "timeout_seconds": 420},
    },
    "risk_allocation_probe_v2_default_reasoning_glm": {
        "pack": PACK,
        "routes": ["glm53_flash"],
        "changes_from_v1": "no reasoning setting declared; output limit from a 131,072-token smoke; GLM only",
        # Long smoke 2026-09-25 (runs/risk_allocation_smoke_v2_glm_long): all 6 finished, 13,530-46,228
        # tokens, 217-923 s. Limit by the rule: 93,000; timeout about twice the slowest reply.
        "limits": {**LIMITS, "reasoning_effort": None, "max_output_tokens": {"glm53_flash": 93000},
                   "max_cost_usd_total": 6.0, "timeout_seconds": 2000, "workers": 8},
    },
    # Smoke 2026-09-25 at low effort: Gemini's longest 1,742, GLM's 5,701, all finished.
    # Superseded as run: its system prompt dropped "price null on accept" (DC-D-24), and GLM's
    # 12,000 limit truncated 3 episodes (DC-O-09). Its plan.json keeps the prompts it sent.
    "risk_allocation_probe_v2_two_prices": {
        "superseded_by": "risk_allocation_probe_v2b_two_prices",
        "pack": "risk_allocation_two_prices_dev_v1",
        "changes_from_v1": "a price request may name an alternate package; output limit per route from smoke",
        "limits": {**LIMITS, "max_output_tokens": {"gemini38_flash": 4000, "glm53_flash": 12000}, "timeout_seconds": 300},
    },
    # The same arm with the accept instruction restored (DC-D-24), provider error bodies typed as
    # provider failures (DC-T-12), and GLM's limit at 32,000: its low-effort replies outran the
    # smoke's 5,701 by more than twice in the run, and 32,000 is the smoke limit no low-effort
    # reply reached.
    "risk_allocation_probe_v2b_two_prices": {
        "pack": "risk_allocation_two_prices_dev_v1",
        "changes_from_v1": "a price request may name an alternate package; output limit per route from smoke and the v2 run",
        "limits": {**LIMITS, "max_output_tokens": {"gemini38_flash": 4000, "glm53_flash": 32000}, "timeout_seconds": 600},
    },
}
SMOKE_OUTPUT_TOKENS = 32000
SMOKE_TIMEOUT_SECONDS = 1800

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


def system_prompt(seat: str, alternates: bool = False) -> str:
    pkg = ('{"warranty": "none|fix|fix_and_delay", "readiness": "client|integrator", '
           '"consequential": "excluded|included", "deposit": "at_signing|on_delivery"}')
    if not alternates:  # v1's prompt, byte for byte
        return (
            f"You are negotiating a contract on behalf of the {seat}. Each turn, read the brief and the negotiation so far, "
            "then reply with exactly one JSON object and nothing else:\n"
            '{"action": "propose" | "accept" | "walk", '
            f'"package": {pkg} or null, '
            '"price": <number in $ thousands> or null, "reason": "<one or two sentences>"}\n'
            "A proposal always states the full package. Use price null to ask the other side for its price for that package "
            "without committing. For accept and walk, package and price are null. Accept takes the standing offer as it stands."
        )
    return (
        f"You are negotiating a contract on behalf of the {seat}. Each turn, read the brief and the negotiation so far, "
        "then reply with exactly one JSON object and nothing else:\n"
        '{"action": "propose" | "accept" | "walk", '
        f'"package": {pkg} or null, '
        '"price": <number in $ thousands> or null, '
        f'"alternate": {pkg} or null, "reason": "<one or two sentences>"}}\n'
        "A proposal always states the full package. Use price null to ask the other side for its price for that package "
        "without committing; with price null you may also name an alternate package, and the answer prices both. "
        "For walk, package, price and alternate are null. Accept takes a standing offer as it stands, so its price and "
        "alternate are null: when there are two standing offers, put the one you accept in package; otherwise package is null."
    )


def user_prompt(obs: dict[str, Any]) -> str:
    lines = [obs["brief"], "", f"Round {obs['round']} of {obs['rounds']}."]
    if obs["history"]:
        lines.append("So far:")
        for h in obs["history"]:
            price = "no price (asked for theirs)" if h["your_price"] is None else f"{h['your_price']:,.1f}"
            pkg = "/".join(h["you_proposed"][k] for k in ra.TERMS)
            if h.get("alternate") is None:
                lines.append(f"- Round {h['round']}: you proposed {pkg} at {price}; they {h['answer']}.")
            else:
                alt = "/".join(h["alternate"][k] for k in ra.TERMS)
                lines.append(f"- Round {h['round']}: you proposed {pkg} at {price} with alternate {alt}; they {h['answer']}, and {h['alternate_answer']}.")
    if obs["standing_offer"]:
        pkg = "/".join(obs["standing_offer"]["package"][k] for k in ra.TERMS)
        lines.append(f"Standing offer: {pkg} (warranty/readiness/consequential/deposit) at {obs['standing_offer']['price']:,.1f}.")
        if obs.get("alternate_offer"):
            alt = "/".join(obs["alternate_offer"]["package"][k] for k in ra.TERMS)
            lines.append(f"Second standing offer: {alt} at {obs['alternate_offer']['price']:,.1f}. An accept must name the package it takes.")
    else:
        lines.append("There is no standing offer.")
    if obs["final"]:
        lines.append("This was their last answer: you may only accept it or walk.")
    lines.append(f"Allowed actions now: {', '.join(obs['allowed_actions'])}. Reply with one JSON object.")
    return "\n".join(lines)


def episodes(manifest: dict[str, Any], limits: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for world in manifest["worlds"]:
        for seat, s in world["seats"].items():
            for run in range(limits["runs_per_case"]):
                out.append({"episode_id": f"{s['case_id'].rsplit('.', 1)[-1]}_r{run}", "case_id": s["case_id"], "seat": seat,
                            "cell": world["cell"], "slug": world["slug"], "run": run})
    return out


def prepare(directory: Path, arm: str) -> None:
    spec = ARMS[arm]
    if spec.get("superseded_by"):
        raise SystemExit(f"{arm} is superseded by {spec['superseded_by']}; prepare that instead")
    directory.mkdir(parents=True, exist_ok=False)
    manifest, cases = rp.load(spec["pack"])
    alternates = any(alternates_of(c["payload"]) for c in cases.values())
    plan = {
        "probe_id": arm,
        "claim_status": "diagnostic",
        "changes_from_v1": spec.get("changes_from_v1", "none: this is v1"),
        "cap_rule": CAP_RULE if isinstance(spec["limits"]["max_output_tokens"], dict) else None,
        "pack": spec["pack"],
        "pack_manifest_sha256": digest(manifest),
        "case_sha256": {k: v["content_sha256"] for k, v in sorted(cases.items())},
        "routes": {r: ROUTES[r] for r in spec.get("routes", ROUTES)},
        "limits": spec["limits"],
        "alternates": alternates,
        "action_schema": ACTION_JSON_SCHEMA_ALTERNATES if alternates else ACTION_JSON_SCHEMA,
        "system_prompts": {seat: system_prompt(seat, alternates) for seat in ra.SEATS},
        "sources": source_digests(),
        "episodes": episodes(manifest, spec["limits"]),
    }
    plan["plan_sha256"] = digest(plan)
    (directory / "plan.json").write_text(json.dumps(plan, indent=1))
    n, k = len(plan["episodes"]), len(plan["routes"])
    print(f"prepared {n} episodes x {k} routes = {n * k} (at most {n * k * 3} calls) -> {directory}/plan.json")


class Budget:
    def __init__(self, cap: float) -> None:
        self.cap, self.spent, self.lock = cap, 0.0, threading.Lock()

    def add(self, cost: float) -> None:
        with self.lock:
            self.spent += cost

    def exhausted(self) -> bool:
        with self.lock:
            return self.spent >= self.cap


def call(route_id: str, system: str, user: str, limits: dict[str, Any], key: str, schema: dict[str, Any] = ACTION_JSON_SCHEMA,
         max_tokens: int | None = None) -> dict[str, Any]:
    route = ROUTES[route_id]
    cap = limits["max_output_tokens"]
    body = {
        "model": route["model"],
        "provider": {"order": [route["provider"]], "allow_fallbacks": False, "require_parameters": True},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": limits["temperature"],
        "max_tokens": max_tokens or (cap[route_id] if isinstance(cap, dict) else cap),
        "response_format": {"type": "json_schema", "json_schema": {"name": "move", "strict": False, "schema": schema}},
        "usage": {"include": True},
    }
    if limits["reasoning_effort"] is not None:
        body["reasoning"] = {"effort": limits["reasoning_effort"], "exclude": True}
    last: dict[str, Any] = {}
    for attempt in range(1, limits["max_attempts"] + 1):
        req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=limits["timeout_seconds"]) as resp:
                obj = json.loads(resp.read().decode())
            if obj.get("error") and not obj.get("choices"):
                # HTTP 200 carrying a provider error (e.g. "Gemini blocked the response", code 502):
                # a provider failure, not the model's move (DC-T-12).
                code = obj["error"].get("code")
                last = {"ok": False, "attempts": attempt, "status": code, "error": json.dumps(obj["error"])[:500]}
                if not (isinstance(code, int) and (code == 429 or code >= 500)):
                    return last
                time.sleep(2 * attempt)
                continue
            return {"ok": True, "attempts": attempt, "response": obj}
        except urllib.error.HTTPError as exc:
            last = {"ok": False, "attempts": attempt, "status": exc.code, "error": exc.read().decode()[:500]}
            if exc.code != 429 and exc.code < 500:
                return last
        except (urllib.error.URLError, TimeoutError) as exc:
            return {"ok": False, "attempts": attempt, "status": None, "error": str(exc)[:500]}
        except (http.client.IncompleteRead, http.client.RemoteDisconnected, ConnectionError, ValueError) as exc:
            # The provider closed the connection mid-reply (seen on GLM's 20-30k-token
            # replies, DC-T-11). Not retried: the reply may already be billed. Typed as
            # a provider failure, which the plan records as missingness.
            return {"ok": False, "attempts": attempt, "status": None, "error": f"connection_dropped: {type(exc).__name__}: {str(exc)[:300]}"}
        time.sleep(2 * attempt)
    return last


def _reference_text(payload: dict[str, Any], state: dict[str, Any]) -> str:
    game, _ = game_of(payload)
    a = ra.reference_policy(game)(seen_of(payload, state))
    move: dict[str, Any] = {"action": a.kind, "package": None, "price": None}
    if a.kind == "accept" and a.package is not None:
        move["package"] = a.package.as_dict()
    if a.kind == "propose":
        move.update(package=a.package.as_dict(), price=None if a.price == ra.PRICE_IT else a.price)
        if a.alternate is not None:
            move["alternate"] = a.alternate.as_dict()
    return json.dumps({**move, "reason": "reference"})


def play(ep: dict[str, Any], raw: dict[str, Any], route_id: str, key: str | None, budget: Budget, out: Path, plan: dict[str, Any]) -> dict[str, Any]:
    plugin = RiskAllocationPlugin()
    payload = plugin.validate_payload(raw["payload"])
    seat = payload["seat"]
    limits = plan["limits"]
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
            rec = call(route_id, plan["system_prompts"][seat], user, limits, key, plan["action_schema"])
            cost = float(((rec.get("response") or {}).get("usage") or {}).get("cost") or 0.0)
            budget.add(cost)
            if not rec.get("ok"):
                turns.append({"user": user, "record": rec, "cost_usd": cost})
                status = "provider_failure"
                break
            try:
                choice = rec["response"]["choices"][0]
                text = choice["message"]["content"] or ""
            except (KeyError, IndexError, TypeError):
                choice, text = {}, ""
            if choice.get("finish_reason") == "error":
                # The provider failed mid-generation (seen on GLM after 12k and 52k tokens): a
                # provider failure, not the model's move (DC-T-12, second route).
                turns.append({"user": user, "record": rec, "text": text, "cost_usd": cost})
                status = "provider_failure"
                break
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


GRADING_SOURCES = SOURCES[:3]  # the code that decides the score; the driver's own display code is not among them


def _check_plan(directory: Path, *, grading: bool = False) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    plan = json.loads((directory / "plan.json").read_text())
    now = source_digests()
    if grading:
        # Grading reads only records. It needs the scoring code unchanged, not the
        # driver: a display fix after the run is recorded, not refused (DC-T-10).
        if any(plan["sources"][p] != now[p] for p in GRADING_SOURCES):
            raise SystemExit("the scoring sources changed since prepare; grade with the frozen sources")
    elif plan["sources"] != now:
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
        futs = [pool.submit(play, ep, cases[ep["case_id"]], r, key, budget, directory, plan) for ep, r in jobs]
        for f in cf.as_completed(futs):
            res = f.result()
            print(f"{res['route_id']:<15} {res['seat']:<10} {res['cell']:<24} {res['status']:<18} {res['final_state']['termination']}")
    print(f"spent ${budget.spent:.4f} of ${budget.cap:.2f}")


def _reason(text: str | None) -> str | None:
    if not text:
        return None
    try:
        value = json.loads(text[text.index("{"): text.rindex("}") + 1])
    except ValueError:
        return None  # truncated or not JSON; the plugin already typed the move
    return value.get("reason") if isinstance(value, dict) else None


def grade_all(directory: Path) -> None:
    plan, cases = _check_plan(directory, grading=True)
    manifest, _ = rp.load(plan["pack"])
    driver = "tools/run_risk_allocation_probe.py"
    if plan["sources"][driver] != source_digests()[driver]:
        print(f"note: the driver changed after the run ({plan['sources'][driver][:12]} -> {source_digests()[driver][:12]}); scoring sources unchanged")
    rows = []
    for path in sorted((directory / "episodes").glob("*.json")):
        ep = json.loads(path.read_text())
        g = grade(cases[ep["case_id"]]["payload"], ep["final_state"])
        last = (ep["turns"][-1]["record"].get("response") or {}) if ep["turns"] else {}
        if ep["status"] == "completed" and ((last.get("choices") or [{}])[0].get("finish_reason") == "error"):
            # Runs recorded before the driver typed this: the provider failed mid-generation.
            ep["status"] = "provider_failure"
        cost = sum(t.get("cost_usd", 0.0) for t in ep["turns"])
        rows.append({**{k: ep[k] for k in ("route_id", "seat", "cell", "slug", "episode_id", "status")}, **g, "cost_usd": cost,
                     "reasons": [_reason(t.get("text")) for t in ep["turns"]]})
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


def smoke(directory: Path, arm: str, per_seat: int = 3, routes: list[str] | None = None, limit: int = SMOKE_OUTPUT_TOKENS) -> None:
    """First-round prompts from the first worlds of the arm's pack, each route, with a large
    output limit: how long does a reply run under this arm's reasoning setting?"""
    directory.mkdir(parents=True, exist_ok=True)
    spec = ARMS[arm]
    manifest, cases = rp.load(spec["pack"])
    alternates = any(alternates_of(c["payload"]) for c in cases.values())
    schema = ACTION_JSON_SCHEMA_ALTERNATES if alternates else ACTION_JSON_SCHEMA
    key = load_key()
    rows = []
    picks = [(w, seat) for seat in ra.SEATS for w in manifest["worlds"][::5][:per_seat]]
    routes = routes or list(ROUTES)
    smoke_limits = {**spec["limits"], "timeout_seconds": SMOKE_TIMEOUT_SECONDS}
    for route_id in routes:
        for world, seat in picks:
            raw = cases[world["seats"][seat]["case_id"]]
            plugin = RiskAllocationPlugin()
            payload = plugin.validate_payload(raw["payload"])
            phase = plugin.phases(payload)[0]
            state = plugin.initial_state(payload, None)
            user = user_prompt(plugin.observe(payload, state, seat, phase))
            began = time.monotonic()
            rec = call(route_id, system_prompt(seat, alternates), user, smoke_limits, key, schema, limit)
            elapsed = round(time.monotonic() - began, 1)
            resp = rec.get("response") or {}
            choice = (resp.get("choices") or [{}])[0]
            usage = resp.get("usage") or {}
            text = (choice.get("message") or {}).get("content") or ""
            parsed = plugin.parse_action(payload, state, seat, phase, CanonicalResponse(text, "stop", not text, False, (), (), 0, 0, 0, 0.0))
            row = {"route_id": route_id, "seat": seat, "world": world["slug"], "ok": rec.get("ok"), "finish": choice.get("finish_reason"),
                   "completion_tokens": usage.get("completion_tokens"), "cost_usd": usage.get("cost"), "parsed": parsed.ok,
                   "seconds": elapsed, "error": None if rec.get("ok") else rec.get("error", "")[:200]}
            rows.append(row)
            print(json.dumps(row), flush=True)
    (directory / f"smoke__{arm}.json").write_text(json.dumps({"arm": arm, "limit_used": limit, "rows": rows}, indent=1))
    for route_id in routes:
        toks = [r["completion_tokens"] or 0 for r in rows if r["route_id"] == route_id and r["ok"]] or [0]
        cap = max(4000, -(-2 * max(toks) // 1000) * 1000)
        print(f"{route_id}: longest {max(toks)}, mean {sum(toks) / len(toks):.0f}; cap by rule {cap}; "
              f"cost/call ${sum(r['cost_usd'] or 0 for r in rows if r['route_id'] == route_id) / len(toks):.4f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["prepare", "execute", "grade", "smoke"])
    ap.add_argument("directory", type=Path)
    ap.add_argument("--route", choices=[*ROUTES, "reference"])
    ap.add_argument("--arm", choices=list(ARMS), default="risk_allocation_probe_v1")
    ap.add_argument("--smoke-routes", nargs="*")
    ap.add_argument("--smoke-limit", type=int, default=SMOKE_OUTPUT_TOKENS)
    args = ap.parse_args()
    if args.command == "smoke":
        smoke(args.directory, args.arm, routes=args.smoke_routes, limit=args.smoke_limit)
    elif args.command == "prepare":
        prepare(args.directory, args.arm)
    elif args.command == "execute":
        execute(args.directory, args.route)
    else:
        grade_all(args.directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
