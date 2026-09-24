"""Case cards for the examiner: the family's cards, and each check evaluated on every published cell.

    python3 build_case_cards.py <out dir> <AERead checkout> [receipt_index.json]

Reads `docs/families/*/case_cards/*.json` (generated world cards) and
`docs/families/*/case_cards.md` (stratum prose), and for every evidence bundle
whose `tables/cells.jsonl` rows name a carded world, evaluates the card's
diagnostic checks from `tables/cells.jsonl` and `tables/periods.jsonl`. Writes
`data/case_cards.json`. Families without cards are untouched.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

EXECUTION_VIOLATIONS = ("sample_not_verified", "over_capacity", "malformed_procurement_action", "episode_ended_before_period")


def sections(markdown: str) -> dict[str, dict[str, list[str]]]:
    """`## heading` sections as paragraphs and bullets, for the page's inline renderer."""
    out: dict[str, dict[str, list[str]]] = {}
    for block in re.split(r"^## ", markdown, flags=re.M)[1:]:
        heading, _, body = block.partition("\n")
        paragraphs, bullets, current = [], [], []
        for line in body.splitlines():
            if line.startswith("- "):
                bullets.append(line[2:].strip())
            elif line.startswith("  ") and bullets:
                bullets[-1] += " " + line.strip()
            elif line.startswith("|"):
                continue  # tables stay in the repository copy
            elif line.strip():
                current.append(line.strip())
            elif current:
                paragraphs.append(" ".join(current))
                current = []
        if current:
            paragraphs.append(" ".join(current))
        out[heading.strip()] = {"paragraphs": paragraphs, "bullets": bullets}
    return out


def negotiation_events(attempt_dir: Path) -> dict | None:
    """Counter-offers, the ones a supplier accepted, and whether an award used an accepted offer."""
    events = attempt_dir / "events.jsonl"
    if not events.exists():
        return None

    def payload(ref: str) -> dict:
        digest = ref.split(":")[-1].split("/")[-1]
        path = attempt_dir / "artifacts" / "sha256" / digest[:2] / digest
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    sent = accepted = used = 0
    accepted_offers: set[str] = set()
    pending = False
    for line in events.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["event_type"] == "action_parsed":
            action = (payload(event["payload_ref"]).get("parse_result") or {}).get("action") or {}
            pending = action.get("action") == "counter_offer"
            sent += pending
            if action.get("action") == "submit_award":
                used += sum(1 for row in action.get("award_lines") or [] if row.get("offer_id") in accepted_offers)
        elif event["event_type"] == "transition_applied" and pending:
            consequences = (payload(event["payload_ref"]).get("transition") or {}).get("consequences") or {}
            if consequences.get("accepted") and consequences.get("offer_id"):
                accepted += 1
                accepted_offers.add(consequences["offer_id"])
            pending = False
    return {"sent": sent, "accepted": accepted, "award_lines_on_negotiated_offers": used}


def evaluate(card: dict, cell: dict, periods: list[dict], negotiation: dict | None = None) -> dict:
    reference = card["reference_solution"]["per_period"]
    checks = {check["id"]: check for check in card["diagnostic_checks"]}
    violations = cell.get("violations") or []
    by_period = {int(row["period"]): row for row in periods}
    result: dict[str, dict] = {}

    first = by_period.get(1)
    latest = checks["D1_orders_in_time"]["reference"]["latest_order_day"]
    if first is None:
        result["D1"] = {"verdict": "not evaluable", "why": "no period-1 row"}
    else:
        short = any("minimum_service_not_met" in v for v in first.get("violations") or [])
        ok = first["decision"] == "award" and not short
        result["D1"] = {
            "verdict": "pass" if ok else "fail",
            "why": f"period 1 {first['decision']} on day {first['elapsed_days']} (latest {latest})"
            + ("; minimum service missed" if short else ""),
        }

    mismatched = []
    for ref in reference:
        row = by_period.get(ref["period"])
        chosen = sorted(row.get("awarded_supplier_ids") or []) if row else []
        if chosen != ref["suppliers"]:
            mismatched.append(f"p{ref['period']}: {', '.join(s.split('_')[-1] for s in chosen) or 'none'}")
    result["D2"] = {
        "verdict": "pass" if not mismatched else "fail",
        "why": "same suppliers as the reference every period" if not mismatched else "differs in " + "; ".join(mismatched),
    }

    if negotiation is None:
        # The tables carry only the count; whether a counter was accepted and used lives in the sealed events.
        result["D3"] = {
            "verdict": "not evaluable" if cell.get("counters") else "fail",
            "why": f"counters sent {cell.get('counters', 0)}; no sealed event log on this machine"
            if cell.get("counters")
            else "no counter-offer sent",
        }
    else:
        result["D3"] = {
            "verdict": "pass" if negotiation["award_lines_on_negotiated_offers"] else "fail",
            "why": f"{negotiation['sent']} counter-offers, {negotiation['accepted']} accepted, "
            f"{negotiation['award_lines_on_negotiated_offers']} award lines on a negotiated offer",
        }

    # A period never played delivers nothing, so it misses minimum service too.
    short = [v for v in violations if "minimum_service_not_met" in v or "episode_ended_before_period" in v]
    result["D4"] = {"verdict": "fail" if short else "pass", "why": ", ".join(short) or "every period met minimum service"}
    bad = [v for v in violations if any(code in v for code in EXECUTION_VIOLATIONS)]
    result["D5"] = {"verdict": "fail" if bad else "pass", "why": ", ".join(bad) or "no invalid action or award"}

    competent = checks["D6_beats_competent_rule"]["reference"]["deadline_aware_regret_usd"]
    regret = float(cell["regret_to_upper_bound_usd"])
    result["D6"] = {
        "verdict": "pass" if regret < competent else "fail",
        "why": f"regret {regret:.1f} vs deadline_aware {competent:.1f}",
    }
    return {"world_case_id": card["case_id"], "regret": regret, "checks": result, "periods": [
        {"period": p, "suppliers": sorted(by_period[p].get("awarded_supplier_ids") or []),
         "prices": {a["supplier_id"]: a["unit_price_usd"] for a in by_period[p].get("awarded") or []},
         "decision": by_period[p]["decision"], "day": by_period[p].get("elapsed_days")}
        for p in sorted(by_period)
    ]}


def main(out: Path, checkout: Path, receipt_index: Path | None = None) -> None:
    index = json.loads(receipt_index.read_text(encoding="utf-8")) if receipt_index and receipt_index.exists() else {}
    cards: dict[str, dict] = {}
    prompts: dict[str, dict] = {}
    for path in sorted(checkout.glob("docs/families/*/case_cards/*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        if pack.get("prompt"):
            prompts[pack["pack"]] = pack["prompt"]
        for card in pack["worlds"]:
            cards[card["case_id"]] = card
    prose: dict[str, dict] = {}
    for path in sorted(checkout.glob("docs/families/*/case_cards.md")):
        prose.update(sections(path.read_text(encoding="utf-8")))
    evaluations: dict[str, dict] = {}
    bundles = 0
    for cells_path in sorted(checkout.glob("evidence/**/tables/cells.jsonl")):
        rows = [json.loads(line) for line in cells_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any(row.get("world_case_id") in cards for row in rows):
            continue
        bundles += 1
        periods_path = cells_path.with_name("periods.jsonl")
        periods: dict[str, list[dict]] = {}
        if periods_path.exists():
            for line in periods_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    periods.setdefault(row["case_id"], []).append(row)
        for row in rows:
            card = cards.get(row.get("world_case_id"))
            if card is None or row.get("status") != "completed" or not row.get("receipt_sha256"):
                continue
            dirs = index.get(row["receipt_sha256"]) or []
            negotiation = negotiation_events(Path(dirs[0])) if dirs else None
            evaluations[row["receipt_sha256"]] = evaluate(card, row, periods.get(row["case_id"], []), negotiation)
    data = {
        "cards": cards,
        "strata": {key: value for key, value in prose.items() if "-" in key and key.replace("-", "_") in {c["stratum"] for c in cards.values()}},
        "common": {key: value for key, value in prose.items() if key in ("How to read a cell", "Common to every world", "Known limits")},
        "evaluations": evaluations,
        "prompts": prompts,
    }
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "data" / "case_cards.json").write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    print(f"case cards: {len(cards)} worlds, {len(data['strata'])} strata, {len(evaluations)} cells evaluated in {bundles} bundles")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
