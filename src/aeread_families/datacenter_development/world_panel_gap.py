"""Why the world panel's developer falls short of the scripted reference.

A derived analysis in the Tier 1 sense: it reads the two frozen world-panel
confirmatories under ``evidence/datacenter_development/`` (``tables/cells.jsonl``,
``trajectories/sanitized.jsonl``, ``reports/summary.json``), their contracts,
and the committed world packs whose digests those bundles publish (each world
file must match the ``case_sha256`` of its cells; the packs themselves
regenerate byte for byte from their master seeds, which
``tests/test_datacenter_holdout_pack.py`` and
``tests/test_datacenter_interface3_confirmatory.py`` check), and it
regenerates byte-identical output (``--check``).

**Endpoint.** Developer equity NPV as each campaign ranks it
(``world_campaign._economic_value``): an admitted stack scores
``outcome.developer_equity_npv_cents``; a valid walk or a negotiation that ran
out of rounds scores the same field, which is then the outside option; an
invalid action, or an executed stack that fails admission, scores
``outside_option_developer_equity_npv_cents``. The reference is the world's
scripted developer, ``scripted_baseline_developer_equity_npv_cents``, which is
the world payload's ``baseline`` and is re-simulated here from the scripted
terms (every world reproduces it, admitted). Each cell is reported as the model
minus the reference on its world, the leaderboard's "Delta vs scripted", in
millions of USD; the reference's own cells are zero by construction.

The score leaf ``scores.developer_equity_npv`` is *not* the endpoint: it
carries an executed stack's simulated NPV even when the stack fails admission,
which the ranking basis replaces with the walk-away value because such a stack
delivers no project. ``reconciliation`` in each report states both figures.

**Decomposition.** A cell's gap belongs to exactly one part, chosen by how the
episode ended:

- ``ended_on_unparseable_action`` (format): the developer's output did not
  parse (``malformed_json``, ``malformed_datacenter_stack_action``);
- ``ended_on_refused_action`` (procedure): a well-formed action the rules
  refuse; here every one is an amendment that changes nothing;
- ``ended_by_walk_or_round_limit`` (decision): a valid walk, a counterparty
  rejection, or a negotiation that ran out of rounds;
- ``stack_failed_admission`` (decision): every agreement signed, but a
  cross-agreement check or the financing fails;
- ``admitted_terms`` (decision): the stack is admitted, and its NPV differs
  from the reference's by the terms signed.

The first four score the walk-away value, so their part is the outside option
minus the reference. The last is split by agreement: the terms of each signed
agreement replace the reference's in the order they were negotiated (land,
power, EPC, service, land amendment, loan), and the change in simulated NPV at
each replacement is that agreement's row. The rows telescope to the cell's gap
exactly. The land amendment is replayed as the set of fields it changes on the
executed land agreement, so the land row carries the original purchase and the
amendment row carries what the amendment (or its decline) changed.

**Checks.** The sealed cell rows publish ``constraint_checks: null`` and
``agreements_executed: []`` for every cell (DC-T-14), so which check a failed
stack fails is re-derived: each executed stack is rebuilt from the terms its
trajectory signed and re-simulated on the committed world, and must reproduce
the published developer NPV, admission flag and default reasons.

**Unit.** The world. The three inference seeds of a world run on one world
(one case digest); they vary the model's sampling, not the case, so they are
averaged within the world and the 24 worlds are resampled by a world-clustered
percentile bootstrap with each campaign's predeclared seed and draw count.

The reports follow ``aeread.gap_decomposition/0.1`` with the model on the left
and the reference on the right (``reference_side: "right"``).

    python -m aeread_families.datacenter_development.world_panel_gap --write
    python -m aeread_families.datacenter_development.world_panel_gap --check
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
from pathlib import Path
from typing import Any, Mapping, Sequence

from aeread.shared_runner.run.resolver import case_content_sha256

from . import world_campaign
from .cashflow import ProjectFacts
from .stack_cashflow import DevelopmentStackOutcome, simulate_development_stack
from .stack_environment import COUNTERPART_BY_KEY, SCOPE_CONFIG, _term_values, _terms
from .stack_worlds import _executed, load_pack_manifest

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / "evidence" / "datacenter_development"
OUT = EVIDENCE / "datacenter_development_v2_world_panel_gap"
REPORTS: tuple[tuple[str, str], ...] = (
    ("interface2", "datacenter_development_v2_world_panel_confirmatory_v1"),
    ("interface3", "datacenter_development_v2_world_panel_interface3_confirmatory_v1"),
)
SEQUENCE: tuple[str, ...] = tuple(SCOPE_CONFIG["v2"]["sequence"])
MILLION = 100 * 1_000_000  # cents in a million USD

COMPONENTS: tuple[tuple[str, str, str, str], ...] = (
    ("ended_on_unparseable_action", "ended on output the parser refused", "format",
     "The developer's action did not parse (not JSON, or JSON the action parser rejects); the episode ends "
     "and the cell scores the walk-away value."),
    ("ended_on_refused_action", "ended on an action the rules refuse", "procedure",
     "A well-formed action the environment refuses; in these runs every one is a land amendment that changes "
     "nothing, which interface 2 types as the developer's invalid action. The cell scores the walk-away value."),
    ("ended_by_walk_or_round_limit", "walked, or ran out of rounds", "decision",
     "A valid walk, a counterparty rejection, or a negotiation that exhausted its rounds; no stack executes "
     "and the cell scores the walk-away value."),
    ("stack_failed_admission", "signed a stack that fails admission", "decision",
     "Every agreement signed, but a cross-agreement check or the financing fails, so the stack delivers no "
     "project and the cell scores the walk-away value instead of its simulated NPV."),
    ("admitted_terms", "admitted, on different terms", "decision",
     "An admitted stack's NPV minus the reference's, split by agreement: each signed agreement's terms "
     "replace the reference's in negotiation order, and the NPV change at each replacement is its row."),
)
COMPONENT_KEYS = tuple(key for key, *_ in COMPONENTS)

AGREEMENT_WORDS = {"land": "land purchase", "power": "power agreement", "epc": "EPC contract",
                   "service": "service agreement", "land_amendment": "land amendment", "loan": "loan"}

#: Engine check -> (class key, label, the agreement whose signature carries it).
CHECKS: dict[str, tuple[str, str, str]] = {
    "power_capacity_covers_lease": ("fails_power_capacity_covers_lease", "executed stack: contracted power is below the leased capacity", "power"),
    "site_control_holds_through_operations": ("fails_site_control_holds_through_operations", "executed stack: site control does not reach commercial operation", "land_amendment"),
    "financing_funded": ("fails_financing_funded", "executed stack: the loan does not fund the project", "loan"),
    "no_default": ("fails_no_default", "executed stack: the project defaults", "loan"),
    "epc_conditions_precedent_met": ("fails_epc_conditions_precedent_met", "executed stack: the EPC's conditions precedent are not met at notice to proceed", "epc"),
    "power_conditions_precedent_met": ("fails_power_conditions_precedent_met", "executed stack: the power agreement's conditions precedent are not met at energization", "power"),
    "epc_capacity_covers_lease": ("fails_epc_capacity_covers_lease", "executed stack: the EPC guarantees less than the leased capacity", "epc"),
}
CHECK_WORDS = {"power_capacity_covers_lease": "power capacity covers the lease",
               "site_control_holds_through_operations": "site control holds through operations",
               "financing_funded": "the loan funds the project", "no_default": "the project avoids default",
               "epc_conditions_precedent_met": "the EPC's conditions precedent are met",
               "power_conditions_precedent_met": "the power agreement's conditions precedent are met",
               "epc_capacity_covers_lease": "EPC capacity covers the lease"}
GAP_BASIS = "the cell's gap to the reference, USD M; a cell can carry several classes, so amounts overlap"
CLASSES: dict[str, dict[str, str]] = {
    "malformed_json": {"group": "format", "label": "the developer's output was not valid JSON", "amount": GAP_BASIS},
    "parser_rejected_action": {
        "group": "format",
        "label": "the action parser rejected a JSON action (malformed_datacenter_stack_action); its text is not published",
        "amount": GAP_BASIS},
    "amendment_changes_nothing": {"group": "procedure", "label": "re-proposed the executed land terms as the amendment", "amount": GAP_BASIS},
    "declined_land_amendment": {"group": "decision", "label": "declined the land amendment (possible only under interface 3)", "amount": GAP_BASIS},
    "walked_away": {"group": "decision", "label": "walked away", "amount": GAP_BASIS},
    "negotiation_rounds_exhausted": {"group": "decision", "label": "a negotiation ran out of rounds", "amount": GAP_BASIS},
    **{key: {"group": "decision", "label": label, "amount": GAP_BASIS} for key, label, _ in CHECKS.values()},
    "admitted_below_reference": {"group": "outcome", "label": "admitted, below the reference's NPV", "amount": "the admitted cell's gap to the reference, USD M"},
}
PARSE_FAILURES = {"malformed_json", "malformed_action", "noncanonical_response", "malformed_datacenter_stack_action", "unknown_phase"}
CLASS_OF_CODE = {"malformed_json": "malformed_json", "malformed_datacenter_stack_action": "parser_rejected_action",
                 "amendment_changes_nothing": "amendment_changes_nothing"}


# --------------------------------------------------------------------------
# Published inputs
# --------------------------------------------------------------------------


def _contract(campaign: str) -> dict[str, Any]:
    return json.loads((ROOT / "configs" / f"{campaign}.json").read_text(encoding="utf-8"))


def _cells(campaign: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in (EVIDENCE / campaign / "tables" / "cells.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(row["status"] != "completed" or row["inclusion_status"] != "included" for row in rows):
        raise ValueError(f"{campaign}: a cell is not completed and included; this analysis covers complete panels only")
    return rows


def with_rounds(steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Steps in order, each with ``round_index``: how many times the episode's first phase has started, from 0."""

    ordered = sorted((dict(step) for step in steps), key=lambda s: s["step_index"])
    first = ordered[0]["phase_id"] if ordered else None
    current, seen = -1, set()
    for step in ordered:
        if step["phase_id"] == first and step["phase_instance_id"] not in seen:
            current += 1
        seen.add(step["phase_instance_id"])
        step["round_index"] = max(current, 0)
    return ordered


def _steps(campaign: str) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for line in (EVIDENCE / campaign / "trajectories" / "sanitized.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by[row["source_receipt_sha256"]].append(row)
    return {receipt: with_rounds(rows) for receipt, rows in by.items()}


def _pack(contract: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    root = ROOT / "cases" / "datacenter_development_v1" / str(contract["pack_split"])
    manifest = load_pack_manifest(root)
    if manifest["pack_id"] != contract["pack_id"] or manifest["artifact_sha256"] != contract["expected_pack_sha256"]:
        raise ValueError(f"the committed pack at {root.name} is not the one {contract['campaign_id']} froze")
    return root, manifest


def _world(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """The committed world a cell ran on, checked against the case digest the bundle publishes."""

    document = json.loads((root / (str(row["case_id"]).rsplit(".", 1)[-1] + ".json")).read_text(encoding="utf-8"))
    if not (document["case_id"] == row["case_id"] and document["content_sha256"] == row["case_sha256"] == case_content_sha256(document)):
        raise ValueError(f"{row['case_id']}: the committed world does not match the published case digest")
    return document["payload"]


# --------------------------------------------------------------------------
# Stack replay
# --------------------------------------------------------------------------


def land_changes(land: Mapping[str, Any], amendment: Mapping[str, Any] | None) -> dict[str, Any]:
    """The fields an amendment changes on the executed land agreement, with their new values."""

    if amendment is None:
        return {}
    before, after = _term_values(_terms("land", land)), _term_values(_terms("land", amendment))
    if set(before) != set(land) or set(after) != set(amendment):
        raise ValueError("land terms carry fields the land agreement does not parse")
    return {field: amendment[field] for field in sorted(before) if before[field] != after[field]}


def simulate(payload: Mapping[str, Any], terms: Mapping[str, Any]) -> DevelopmentStackOutcome:
    """Simulate a V2 stack: ``terms`` holds power, epc, service, loan, the land purchase and the amendment's changes."""

    land = {**terms["land"], **terms["land_amendment"]}
    return simulate_development_stack(
        ProjectFacts.from_dict(payload["project_facts"]),
        service_agreement=_executed("service", terms["service"]),
        loan_agreement=_executed("loan", terms["loan"]),
        power_agreement=_executed("power", terms["power"]),
        epc_agreement=_executed("epc", terms["epc"]),
        land_agreement=_executed("land", land),
    )


def reference_terms(payload: Mapping[str, Any]) -> dict[str, Any]:
    scripted = payload["scripted_developer"]
    terms = {key: scripted[f"{key}_terms"] for key in SEQUENCE if key != "land_amendment"}
    terms["land_amendment"] = land_changes(scripted["land_terms"], scripted["land_amendment_terms"])
    if sorted(terms["land_amendment"]) != sorted(scripted["land_amendment_fields"]):
        raise ValueError("the scripted amendment changes other fields than it declares")
    return terms


def _key(phase_id: str) -> str:
    return next(key for key in sorted(SEQUENCE, key=len, reverse=True) if phase_id.startswith(f"{key}_"))


def signed(steps: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per agreement, the terms the developer signed and the step that signed (or declined) it."""

    offers: dict[str, Mapping[str, Any]] = {}
    out: dict[str, Any] = {"terms": {}, "at": {}, "declined": None}
    for step in steps:
        if (step.get("outcome") or {}).get("valid") is not True:
            continue
        action = step["action"] or {}
        key = _key(step["phase_id"])
        if step["phase_id"].endswith("_offer") and action.get("decision") == "offer":
            offers[key] = action["terms"]
        elif step["phase_id"].endswith("_offer") and action.get("decision") == "decline":
            out["declined"] = step
            out["at"][key] = step
        elif step["phase_id"].endswith("_commit") and action.get("decision") == "sign":
            out["terms"][key] = offers[key]
            out["at"][key] = step
    return out


def model_terms(record: Mapping[str, Any]) -> dict[str, Any]:
    terms = {key: record["terms"][key] for key in SEQUENCE if key != "land_amendment"}
    terms["land_amendment"] = land_changes(record["terms"]["land"], record["terms"].get("land_amendment"))
    return terms


# --------------------------------------------------------------------------
# One cell
# --------------------------------------------------------------------------


def _usd(cents: int | float) -> str:
    value = cents / MILLION
    return f"{'-' if value < 0 else '+'}${abs(value):,.1f}M"


def _words(field: str) -> str:
    """A term's name in words: ``delay_liquidated_damages_cents_per_month`` reads "delay liquidated damages per month"."""

    field = field.replace("_cents", "").replace("_bps", "")
    if field.endswith("_kw") and not field.endswith("_per_kw"):
        field = field[: -len("_kw")]
    return field.replace("_", " ")


def _listed(items: Sequence[str], limit: int = 4) -> str:
    items = list(items)
    if len(items) > limit:
        items = items[:limit] + [f"{len(items) - limit} more"]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _quote(text: Any, limit: int = 110) -> str:
    text = " ".join(str(text or "").split())
    return f"\"{text[:limit].rstrip()}{'...' if len(text) > limit else ''}\""


def _at(step: Mapping[str, Any]) -> dict[str, Any]:
    return {"step_index": int(step["step_index"]), "round_index": int(step["round_index"]),
            "phase_id": step["phase_id"], "seat_id": step["seat_id"]}


def _check_note(check: str, stack: DevelopmentStackOutcome, terms: Mapping[str, Any], declined: bool) -> str:
    service, power, epc = terms["service"], terms["power"], terms["epc"]
    if check == "power_capacity_covers_lease":
        return f"contracted {power['contracted_capacity_kw']:,} kW of power against a {service['committed_capacity_kw']:,} kW lease"
    if check == "epc_capacity_covers_lease":
        return f"the EPC guarantees {epc['guaranteed_capacity_kw']:,} kW against a {service['committed_capacity_kw']:,} kW lease"
    if check == "site_control_holds_through_operations":
        land = {**terms["land"], **terms["land_amendment"]}
        extension = f" plus a {land['extension_option_months']}-month extension" if land["extension_option_months"] else " with no extension"
        cod = stack.project.cod_month
        operation = ("the project never reaches commercial operation within the horizon" if cod is None
                     else f"commercial operation comes in month {cod}")
        how = "after declining the amendment, " if declined else ""
        return f"{how}site control runs to month {land['site_control_expiry_month']}{extension}; {operation}"
    if check in ("financing_funded", "no_default"):
        reasons = ", ".join(stack.project.default_reasons) or "no default reason recorded"
        return f"the loan does not fund the project ({reasons})" if check == "financing_funded" else f"the project defaults ({reasons})"
    if check == "epc_conditions_precedent_met":
        return f"the EPC's conditions precedent ({', '.join(epc['conditions_precedent'])}) are not all met by notice to proceed in month {epc['notice_to_proceed_month']}"
    if check == "power_conditions_precedent_met":
        return f"the power agreement's conditions precedent ({', '.join(power['conditions_precedent'])}) are not all met by energization in month {power['energization_month']}"
    raise ValueError(f"unknown engine check {check}")


def analyse_cell(row: Mapping[str, Any], steps: Sequence[Mapping[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
    """A cell's part (in cents), the rows that make it, its classes, and its re-simulated checks."""

    outcome = row["outcome"]
    reference = int(row["scripted_baseline_developer_equity_npv_cents"])
    outside = int(row["outside_option_developer_equity_npv_cents"])
    economic = world_campaign._economic_value(row)
    if economic is None or economic != int(economic):
        raise ValueError(f"{row['cell_key']}: no integral ranking-basis value")
    gap = int(economic) - reference
    parts = {key: 0 for key in COMPONENT_KEYS}
    rows: list[dict[str, Any]] = []
    found: list[dict[str, Any]] = []
    record = signed(steps)
    declined = record["declined"]
    if declined is not None:
        found.append({**_at(declined), "class": "declined_land_amendment", "amount": gap,
                      "note": f"declined the land amendment: {_quote((declined['action'] or {}).get('message'))}"})
    last = steps[-1]
    checks: dict[str, bool] | None = None
    if outcome["project_completed"] and not outcome["temporal_violations"]:
        terms = model_terms(record)
        stack = simulate(payload, terms)
        if (stack.developer_equity_npv_cents != outcome["developer_equity_npv_cents"]
                or stack.negotiated_constraints_satisfied != outcome["project_constraints_satisfied"]
                or list(stack.project.default_reasons) != list(outcome["default_reasons"])):
            raise ValueError(f"{row['cell_key']}: the signed terms do not re-simulate to the published outcome")
        checks = dict(stack.constraint_checks)
        final = record["at"][SEQUENCE[-1]]
        if final is not last:
            raise ValueError(f"{row['cell_key']}: the stack's last signature is not the episode's last step")
        if world_campaign._admitted(row):
            if not all(checks.values()):
                raise ValueError(f"{row['cell_key']}: admitted, but a re-simulated check fails")
            ref = reference_terms(payload)
            mixed = dict(ref)
            before = simulate(payload, mixed).developer_equity_npv_cents
            if before != reference:
                raise ValueError(f"{row['cell_key']}: the reference does not re-simulate to its published NPV")
            for key in SEQUENCE:
                mixed[key] = terms[key]
                after = simulate(payload, mixed).developer_equity_npv_cents
                step = record["at"][key]
                if key == "land_amendment":
                    ref_fields = [_words(f) for f in ref[key]]
                    what = (f"declined the land amendment, where the reference's amendment changes {_listed(ref_fields)}"
                            if step is declined else
                            f"signed a land amendment changing {_listed([_words(f) for f in terms[key]]) if terms[key] else 'nothing'}"
                            f" (the reference's changes {_listed(ref_fields)})")
                else:
                    differ = [_words(f) for f in ref[key] if ref[key][f] != terms[key].get(f)]
                    what = (f"signed the {AGREEMENT_WORDS[key]} on the reference's terms" if not differ else
                            f"signed the {AGREEMENT_WORDS[key]}, which differs from the reference's in {_listed(differ)}")
                rows.append({**_at(step), "component": "admitted_terms", "agreement_key": key, "amount": after - before,
                             "note": f"{what}; put in place of the reference's after the agreements before it, it moves developer NPV by {_usd(after - before)}"})
                before = after
            if before != outcome["developer_equity_npv_cents"]:
                raise ValueError(f"{row['cell_key']}: the attribution does not end at the published NPV")
            parts["admitted_terms"] = gap
            if gap < 0:
                found.append({**_at(final), "class": "admitted_below_reference", "amount": gap,
                              "note": f"admitted at {_usd(gap)} against the reference"})
        else:
            failing = [check for check, ok in checks.items() if not ok]
            parts["stack_failed_admission"] = gap
            rows.append({**_at(final), "component": "stack_failed_admission", "agreement_key": SEQUENCE[-1], "amount": gap,
                         "note": f"signed the loan, executing a stack that fails the checks that {_listed([CHECK_WORDS[c] for c in failing])}; "
                                 f"the cell scores the walk-away value, {_usd(gap)} against the reference"})
            for check in failing:
                key, _, carrier = CHECKS[check]
                step = record["at"].get(carrier) or record["at"]["land"]
                found.append({**_at(step), "class": key, "amount": gap,
                              "note": _check_note(check, stack, terms, declined is not None)})
    elif outcome["temporal_violations"]:
        code = str(outcome["temporal_violations"][0])
        failure = last.get("outcome") or {}
        if failure.get("valid") is not False or failure.get("failure_code") != code or outcome["termination_reason"] != "invalid_action":
            raise ValueError(f"{row['cell_key']}: the published violation is not the trajectory's last, rejected step")
        agreement = AGREEMENT_WORDS[_key(last["phase_id"])]
        if code == "malformed_json":
            response = (last["attempts"][-1] if last.get("attempts") else {}).get("response") or {}
            cut = response.get("truncated") is True or response.get("finish_reason") == "length"
            what = f"the {agreement} offer was not valid JSON{', cut off at the output-token cap' if cut else ''}"
        elif code == "malformed_datacenter_stack_action":
            what = f"the parser rejected the {agreement} action; its text is not published"
        elif code == "amendment_changes_nothing":
            what = f"re-proposed the executed land terms as the amendment: {_quote((last['action'] or {}).get('message'))}"
        else:
            what = f"the {agreement} action was refused ({code})"
        component = "ended_on_unparseable_action" if code in PARSE_FAILURES else "ended_on_refused_action"
        parts[component] = gap
        rows.append({**_at(last), "component": component, "agreement_key": _key(last["phase_id"]), "amount": gap,
                     "note": f"{what}; the episode ends and the cell scores the walk-away value, {_usd(gap)} against the reference"})
        found.append({**_at(last), "class": CLASS_OF_CODE.get(code, code), "amount": gap, "note": what})
    elif world_campaign._no_agreement(row):
        reason = str(outcome["termination_reason"])
        if reason.endswith("_negotiation_rounds_exhausted"):
            key = reason[: -len("_negotiation_rounds_exhausted")]
            offers = [s for s in steps if s["phase_id"] == f"{key}_developer_offer" and (s["action"] or {}).get("decision") == "offer"]
            at, cls = offers[-1], "negotiation_rounds_exhausted"
            what = (f"made its last {AGREEMENT_WORDS[key]} offer; the {COUNTERPART_BY_KEY[key]} countered it and the "
                    f"{len(offers)} rounds ran out")
        else:
            at = last
            action = at["action"] or {}
            if at["seat_id"] != "developer" or action.get("decision") != reason.rsplit("_", 1)[-1]:
                raise ValueError(f"{row['cell_key']}: the published termination is not the trajectory's last action")
            cls = "walked_away"
            what = f"walked at the {AGREEMENT_WORDS[_key(at['phase_id'])]}: {_quote(action.get('message'))}"
        parts["ended_by_walk_or_round_limit"] = gap
        rows.append({**_at(at), "component": "ended_by_walk_or_round_limit", "agreement_key": _key(at["phase_id"]), "amount": gap,
                     "note": f"{what}; no stack executes and the cell scores the walk-away value, {_usd(gap)} against the reference"})
        found.append({**_at(at), "class": cls, "amount": gap, "note": what})
    else:
        raise ValueError(f"{row['cell_key']}: an episode this analysis cannot place")
    if economic != (outcome["developer_equity_npv_cents"] if world_campaign._admitted(row) or world_campaign._no_agreement(row) else outside):
        raise ValueError(f"{row['cell_key']}: the ranking basis disagrees with its own rule")
    unknown = [i["class"] for i in found if i["class"] not in CLASSES]
    if unknown:
        raise ValueError(f"{row['cell_key']}: classes this analysis does not declare: {unknown}")
    sums = collections.Counter()
    for item in rows:
        sums[item["component"]] += item["amount"]
    component = next(key for key in COMPONENT_KEYS if any(r["component"] == key for r in rows))
    leaf = row["scores"]["developer_equity_npv"]["value"]
    if leaf != int(leaf) or int(leaf) != outcome["developer_equity_npv_cents"]:
        raise ValueError(f"{row['cell_key']}: the score leaf is not the outcome's developer NPV")
    return {"component": component, "parts": parts, "gap": gap, "residual": gap - sum(parts.values()),
            "contribution_residual": max(abs(parts[k] - sums[k]) for k in COMPONENT_KEYS),
            "contributions": rows, "instances": found, "checks": checks,
            "score_leaf": int(leaf)}


# --------------------------------------------------------------------------
# One report
# --------------------------------------------------------------------------


def _boot(values: Sequence[int], rng: random.Random, draws: int, scale: int) -> list[float] | None:
    """Percentile interval of the mean of ``values / scale``, resampling the values (one per world).

    The values are integer cents summed over a world's cells, so every resampled total is exact and the one
    division is correctly rounded: the bytes do not depend on how an interpreter sums floats (DC-T-05)."""

    if len(values) < 2:
        return None
    means = sorted(sum(rng.choice(values) for _ in values) / (len(values) * scale) for _ in range(draws))
    return [round(means[int(0.025 * draws)], 6), round(means[min(draws - 1, int(0.975 * draws))], 6)]


def _m(cents: float) -> float:
    return round(cents / MILLION, 8)


def _report(label: str, campaign: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contract = _contract(campaign)
    seeds = list(contract["inference_seeds"])
    model = next(iter(contract["models"].values()))
    root, manifest = _pack(contract)
    cells, steps = _cells(campaign), _steps(campaign)
    summary = json.loads((EVIDENCE / campaign / "reports" / "summary.json").read_text(encoding="utf-8"))
    worlds: dict[int, dict[str, Any]] = {}
    analysed: list[dict[str, Any]] = []
    for row in cells:
        world = int(row["world_seed"])
        payload = _world(root, row)
        if world not in worlds:
            ref = simulate(payload, reference_terms(payload))
            if (ref.developer_equity_npv_cents != row["scripted_baseline_developer_equity_npv_cents"]
                    or ref.developer_equity_npv_cents != payload["baseline"]["developer_equity_npv_cents"]
                    or not ref.negotiated_constraints_satisfied):
                raise ValueError(f"{row['case_id']}: the scripted reference does not re-simulate to the published baseline, admitted")
            worlds[world] = {"case_sha256": row["case_sha256"], "stratum": row["stratum"], "case_id": row["case_id"],
                             "reference": int(row["scripted_baseline_developer_equity_npv_cents"]),
                             "outside": int(row["outside_option_developer_equity_npv_cents"]), "cells": []}
        entry = worlds[world]
        if (entry["case_sha256"], entry["reference"], entry["outside"]) != (row["case_sha256"], row["scripted_baseline_developer_equity_npv_cents"], row["outside_option_developer_equity_npv_cents"]):
            raise ValueError(f"{row['case_id']}: the seeds of one world disagree on the world")
        result = analyse_cell(row, steps[row["receipt_sha256"]], payload)
        cell = {"side": "left", "campaign_id": campaign, "receipt_sha256": row["receipt_sha256"], "world_seed": world,
                "replicate_index": seeds.index(int(row["inference_seed"])), "stratum": row["stratum"], **result}
        entry["cells"].append(cell)
        analysed.append(cell)
    order = sorted(worlds)
    right_id = str(contract["pack_id"])
    rng = random.Random(int(contract["analysis"]["bootstrap_seed"]))
    draws = int(contract["analysis"]["bootstrap_draws"])

    seeds_per_world = {len(worlds[w]["cells"]) for w in order}
    if len(seeds_per_world) != 1:
        raise ValueError(f"{campaign}: worlds carry different numbers of cells")
    scale = seeds_per_world.pop() * MILLION  # a world's summed cents over this is its seed mean in USD M

    def per_world(pick) -> list[int]:
        """Per world, the pick summed over its cells in integer cents."""

        return [sum(int(pick(c)) for c in worlds[w]["cells"]) for w in order]

    def mean(pick) -> float:
        return sum(per_world(pick)) / (len(order) * scale)

    def block(pick) -> dict[str, Any]:
        value = round(mean(pick), 6)
        return {"left": value, "right": 0.0, "difference": value, "difference_ci": _boot(per_world(pick), rng, draws, scale)}

    realized = block(lambda c: c["gap"])
    components = [{"key": key, "label": lab, "group": grp, "description": desc, "cells": sum(c["component"] == key for c in analysed),
                   **block(lambda c, key=key: c["parts"][key])} for key, lab, grp, desc in COMPONENTS]
    classes = []
    for key, meta in CLASSES.items():
        amounts = block(lambda c, key=key: sum(i["amount"] for i in c["instances"] if i["class"] == key))
        classes.append({"key": key, "group": meta["group"], "label": meta["label"], "amount_basis": meta["amount"],
                        "left_count": sum(1 for c in analysed for i in c["instances"] if i["class"] == key), "right_count": 0,
                        "left_amount_per_market": amounts["left"], "right_amount_per_market": 0.0,
                        "amount_difference": amounts["difference"], "amount_difference_ci": amounts["difference_ci"]})
    where = lambda c: {"side": "left", "campaign_id": campaign, "receipt_sha256": c["receipt_sha256"],
                       "world_seed": c["world_seed"], "replicate_index": c["replicate_index"]}
    instances = [{**where(c), **i, "amount": _m(i["amount"])} for c in analysed for i in c["instances"]]
    table = [{**where(c), **r, "amount": _m(r["amount"])} for c in analysed for r in c["contributions"]]
    by_agreement = {key: round(mean(lambda c, key=key: sum(r["amount"] for r in c["contributions"]
                                                           if r["agreement_key"] == key and r["component"] == "admitted_terms")), 6)
                    for key in SEQUENCE}
    lead = summary["leaderboard"][0]
    model_mean = mean(lambda c: c["gap"] + worlds[c["world_seed"]]["reference"])
    reference_mean = mean(lambda c: worlds[c["world_seed"]]["reference"])
    outside_mean = mean(lambda c: worlds[c["world_seed"]]["outside"])
    leaf = mean(lambda c: c["score_leaf"] - worlds[c["world_seed"]]["reference"])
    if abs(realized["left"] - lead["mean_delta_from_baseline_cents"] / MILLION) > 1e-6 or abs(model_mean - lead["mean_developer_equity_npv_cents"] / MILLION) > 1e-6:
        raise ValueError(f"{campaign}: the realized gap does not reproduce the published leaderboard")
    published = {**summary["model_summaries"][0]["exclusion_reasons"], **summary["model_summaries"][0]["no_agreement_reasons"],
                 "admitted": summary["model_summaries"][0]["admitted_cells"]}
    if sum(published.values()) != len(analysed) or sum(c["component"] == "admitted_terms" for c in analysed) != published["admitted"]:
        raise ValueError(f"{campaign}: the published reasons do not cover the cells")
    residual = max(abs(c["residual"]) for c in analysed)
    contribution_residual = max(c["contribution_residual"] for c in analysed)
    executed = [c for c in analysed if c["checks"] is not None]
    report = {
        "schema_version": "aeread.gap_decomposition/0.1",
        "family": "datacenter_development", "world_kind": f"v2_world_panel_{label}",
        "title": "Why it falls short of the reference",
        "left": campaign, "right": right_id, "reference_side": "right",
        "left_model": model["canonical_model"],
        "right_model": "scripted developer reference (each world's scripted terms, payload.baseline)",
        "right_label": "reference",
        "endpoint": ("developer equity NPV as the campaign ranks it (an admitted stack earns its NPV; a walk, an invalid action "
                     "or a stack that fails admission scores the walk-away value), minus the scripted reference's on the same "
                     "world: the leaderboard's delta vs scripted"),
        "unit": "millions of USD per world, the three seeds of a world averaged first",
        "unit_label": "world", "per_label": "world", "amount_label": "USD M/world",
        "class_heading": "what happened (diagnostic, overlapping; engine checks re-derived by re-simulation)",
        "direction": "higher", "claim_status": "descriptive_single_route_confirmatory",
        "winner_claim_allowed": False, "inferential_model_ranking_allowed": False,
        "paired_worlds": len(order), "cells": {"left": len(analysed), "right": len(order)},
        "bootstrap": {"seed": int(contract["analysis"]["bootstrap_seed"]), "draws": draws, "interval": "percentile_95", "unit": "world_seed",
                      "stream": "one random.Random(seed), the campaign's predeclared seed and draws: realized, then components in declared order, then classes in declared order"},
        "intervals": None,
        "realized": realized,
        "components": components,
        "accounting_check": {"max_abs_residual_per_cell": residual / MILLION,
                             "statement": "each cell's gap to the reference (ranking basis minus scripted baseline, integer cents) is exactly one part",
                             "max_abs_contribution_residual": contribution_residual / MILLION,
                             "contribution_statement": "per cell, the contribution rows of each part sum to that cell's part in integer cents; an admitted cell's six agreement rows telescope from the reference's NPV to its own"},
        "levels": {"left_mean_developer_equity_npv": round(model_mean, 6),
                   "right_mean_developer_equity_npv": round(reference_mean, 6),
                   "mean_outside_option": round(outside_mean, 6),
                   "statement": "per world, USD M: the model's ranking-basis NPV, the reference's, and the walk-away value both could take"},
        "reconciliation": {
            "leaderboard_mean_developer_equity_npv": round(lead["mean_developer_equity_npv_cents"] / MILLION, 6),
            "leaderboard_mean_delta_from_baseline": round(lead["mean_delta_from_baseline_cents"] / MILLION, 6),
            "score_leaf_mean_delta_from_baseline": round(leaf, 6),
            "score_leaf_minus_ranking_basis": round(leaf - realized["left"], 6),
            "statement": ("the realized gap is the published leaderboard's delta vs scripted; the score leaf "
                          "scores.developer_equity_npv credits a stack that fails admission with its simulated NPV, which the "
                          "ranking basis replaces with the walk-away value, so a gap read off the leaf is smaller by the last figure "
                          "(DC-T-14); outcome.agreements_executed is empty and outcome.constraint_checks null in every published row, "
                          "so executed stacks are identified by project_completed and their failing checks re-derived by re-simulation")},
        "reference": {"source": f"tables/cells.jsonl scripted_baseline_developer_equity_npv_cents, equal to payload.baseline of each world in pack {right_id} (manifest {manifest['artifact_sha256']})",
                      "replay_check": {"worlds": len(order), "mismatches": 0, "admitted": len(order),
                                       "statement": "the scripted terms re-simulate to every world's published baseline, and every reference stack passes every engine check"},
                      "receipt_sha256_is": "the world's case digest (case_sha256 in tables/cells.jsonl); the scripted reference has no receipt or trajectory in the bundle"},
        "stack_replay": {"executed_stacks": len(executed), "reproduced": len(executed),
                         "statement": "every executed stack, rebuilt from the terms its trajectory signed on the committed world, reproduces the published developer NPV, admission flag and default reasons"},
        "admitted_terms_by_agreement": {"values": by_agreement, "order": list(SEQUENCE),
                                        "statement": "the admitted-terms part split by agreement, USD M per world; each agreement's terms replace the reference's in this order"},
        "published_reasons": {"reasons": sorted(published), "left": dict(sorted(published.items())), "right": {k: 0 for k in sorted(published)},
                              "statement": "the campaign summary's own labels; constraint_failure:unfinanced names a stack the engine funded (DC-T-15)"},
        "classes": classes,
        "instances": sorted(instances, key=lambda i: (i["class"], i["world_seed"], i["replicate_index"], i["step_index"])),
        "cell_parts": sorted([{**where(c), "stratum": c["stratum"], "parts": {k: _m(v) for k, v in c["parts"].items()}} for c in analysed]
                             + [{"side": "right", "campaign_id": right_id, "receipt_sha256": worlds[w]["case_sha256"], "world_seed": w,
                                 "replicate_index": 0, "stratum": worlds[w]["stratum"], "parts": {k: 0.0 for k in COMPONENT_KEYS}} for w in order],
                             key=lambda c: (c["side"], c["world_seed"], c["replicate_index"])),
        "contributions": {"table": f"tables/contributions_{label}.jsonl", "rows": len(table),
                          "fields": ["side", "campaign_id", "receipt_sha256", "world_seed", "replicate_index", "step_index", "round_index",
                                     "phase_id", "seat_id", "component", "agreement_key", "amount", "note"]},
        "source_manifest_sha256": {campaign: hashlib.sha256((EVIDENCE / campaign / "publication_manifest.json").read_bytes()).hexdigest()},
    }
    return report, sorted(table, key=lambda r: (r["world_seed"], r["replicate_index"], r["step_index"], r["component"]))


def pairing() -> dict[str, Any]:
    """Whether the two confirmatories ran on the same worlds, which a by-world pairing of the interfaces needs."""

    a, b = (_cells(campaign) for _, campaign in REPORTS)
    return {"shared_world_seeds": len({r["world_seed"] for r in a} & {r["world_seed"] for r in b}),
            "shared_case_digests": len({r["case_sha256"] for r in a} & {r["case_sha256"] for r in b}),
            "worlds_each": len({r["world_seed"] for r in a}),
            "statement": "interface 2 and interface 3 ran on different held-out packs (different master seeds); with no world in common they are not paired by world"}


def analyse() -> dict[str, tuple[dict[str, Any], list[dict[str, Any]]]]:
    shared = pairing()
    out = {}
    for label, campaign in REPORTS:
        report, table = _report(label, campaign)
        out[label] = ({**report, "interface_pairing": shared}, table)
    return out


# --------------------------------------------------------------------------
# README and files
# --------------------------------------------------------------------------


def _table_bytes(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def _readme(reports: Mapping[str, tuple[dict[str, Any], list]]) -> str:
    (l2, (r2, _)), (l3, (r3, _)) = reports.items()
    fmt = lambda b: f"{b['difference']:,.1f} ({b['difference_ci'][0]:,.1f} to {b['difference_ci'][1]:,.1f})"
    parts = [f"| **developer NPV minus the reference's** | **{fmt(r2['realized'])}** | **{fmt(r3['realized'])}** |"]
    parts += [f"| {a['label']} ({a['group']}; {a['cells']} / {b['cells']} cells) | {fmt(a)} | {fmt(b)} |"
              for a, b in zip(r2["components"], r3["components"])]
    classes = [f"| `{a['key']}`: {a['label']} | {a['left_count']} | {b['left_count']} | {a['left_amount_per_market']:,.1f} | {b['left_amount_per_market']:,.1f} |"
               for a, b in zip(r2["classes"], r3["classes"])]
    agreements = [f"| {AGREEMENT_WORDS[k]} | {r2['admitted_terms_by_agreement']['values'][k]:,.2f} | {r3['admitted_terms_by_agreement']['values'][k]:,.2f} |"
                  for k in SEQUENCE]
    rec2, rec3 = r2["reconciliation"], r3["reconciliation"]
    lv2, lv3 = r2["levels"], r3["levels"]
    return "\n".join([
        f"# {OUT.name}",
        "",
        "Why the world panel's developer (Gemini 3.8 Flash, one route) falls short of the scripted reference on the same "
        "held-out worlds, once per frozen confirmatory: interface 2 "
        f"(`{r2['left']}`) and interface 3 (`{r3['left']}`). Derived from the two published bundles and the committed "
        "world packs whose digests they publish by `python -m aeread_families.datacenter_development.world_panel_gap`; "
        "`--check` regenerates these bytes. Descriptive only: one route, no winner, no ranking.",
        "",
        "**Endpoint.** Developer equity NPV as each campaign ranks it (`world_campaign._economic_value`): an admitted "
        "stack earns `outcome.developer_equity_npv_cents`; a walk or a round-out earns the same field, which is then the "
        "outside option; an invalid action, or an executed stack that fails admission, scores "
        "`outside_option_developer_equity_npv_cents`. The reference is `scripted_baseline_developer_equity_npv_cents`, "
        "each world's `payload.baseline`, re-simulated here from the scripted terms (24 of 24 worlds in each pack, every "
        "reference stack admitted). Each cell is the model minus the reference on its world, the leaderboard's *delta vs "
        "scripted*, in USD millions, averaged over a world's three seeds and then over 24 worlds. Mean NPV per world: model "
        f"{lv2['left_mean_developer_equity_npv']:,.1f} against reference {lv2['right_mean_developer_equity_npv']:,.1f} "
        f"(interface 2), {lv3['left_mean_developer_equity_npv']:,.1f} against {lv3['right_mean_developer_equity_npv']:,.1f} "
        f"(interface 3); walking away is worth {lv2['mean_outside_option']:,.1f} and {lv3['mean_outside_option']:,.1f}.",
        "",
        f"**Reconciliation.** The realized gap reproduces the leaderboard ({rec2['leaderboard_mean_delta_from_baseline']:,.1f} "
        f"and {rec3['leaderboard_mean_delta_from_baseline']:,.1f}). A gap read off the score leaf "
        f"`scores.developer_equity_npv` is smaller ({rec2['score_leaf_mean_delta_from_baseline']:,.1f} and "
        f"{rec3['score_leaf_mean_delta_from_baseline']:,.1f}) because the leaf credits a stack that fails admission with its "
        "simulated NPV, which the ranking basis replaces with the walk-away value. The cell rows publish "
        "`agreements_executed: []` and `constraint_checks: null` for every cell (DC-T-14), so executed stacks are "
        "identified by `project_completed` and their failing checks are re-derived: each executed stack is rebuilt from the "
        f"terms its trajectory signed and re-simulated on the committed world ({r2['stack_replay']['reproduced']} and "
        f"{r3['stack_replay']['reproduced']} stacks, all reproducing the published NPV, admission flag and default reasons).",
        "",
        "Each cell's gap is exactly one part, chosen by how the episode ended (largest residual "
        f"{max(r2['accounting_check']['max_abs_residual_per_cell'], r3['accounting_check']['max_abs_residual_per_cell']):g}). "
        "USD M per world, 95% world-clustered bootstrap (each campaign's predeclared seed and 10,000 draws); the "
        "reference's own parts are zero:",
        "",
        "| part (cells, interface 2 / 3) | interface 2 | interface 3 |",
        "|---|---|---|",
        *parts,
        "",
        "The admitted part by agreement, each agreement's terms put in place of the reference's in negotiation order "
        "(USD M per world):",
        "",
        "| agreement | interface 2 | interface 3 |",
        "|---|---|---|",
        *agreements,
        "",
        "What happened, counted over all 72 cells of each run (diagnostic and overlapping, not parts of the sum; the "
        "amount is the gap of the cells carrying the class, USD M per world). The `fails_*` classes are the engine's own "
        "checks on each executed stack, re-derived as above:",
        "",
        "| class | interface 2 cells | interface 3 cells | interface 2 per world | interface 3 per world |",
        "|---|---|---|---|---|",
        *classes,
        "",
        "Every class instance and every part's contribution rows name the step that decided them "
        "(`step_index`, `phase_id`, `seat_id` in `trajectories/sanitized.jsonl`, and `round_index`, the 0-based count of "
        "land-offer phases started). Reports: `reports/gap_decomposition_interface2.json`, "
        "`reports/gap_decomposition_interface3.json`; rows: `tables/contributions_<interface>.jsonl` "
        f"({r2['contributions']['rows']} and {r3['contributions']['rows']} rows; per cell, a part's rows sum to it exactly).",
        "",
        "**Unit.** The world: 24 distinct worlds per pack, each run on three inference seeds that share its case digest, "
        "so the seeds vary the model's sampling, not the case. The reference's cells are one per world, identified by the "
        "world's case digest in `receipt_sha256` because the scripted reference has no receipt in the bundle. Every "
        "world file read here matches the `case_sha256` its cells publish, and both packs regenerate byte for byte from "
        "their master seeds (`tests/test_datacenter_holdout_pack.py`, `tests/test_datacenter_interface3_confirmatory.py`).",
        "",
        f"**Limits.** The two packs share {r2['interface_pairing']['shared_world_seeds']} of "
        f"{r2['interface_pairing']['worlds_each']} world seeds and {r2['interface_pairing']['shared_case_digests']} case "
        "digests (different master seeds), so interface 2 and interface 3 are not paired world by world. The parser keeps no text for a "
        "rejected action, so what the 12 `parser_rejected_action` cells of interface 2 said is not derivable here "
        "(DC-D-08 and DC-D-10 read them from the unpublished run root as walks with a stated reason). The summaries' "
        "label `constraint_failure:unfinanced` names stacks the engine funded (DC-T-15); this bundle names each failing "
        "check instead. The by-agreement split depends on the declared order.",
        "",
    ])


def write() -> None:
    reports = analyse()
    (OUT / "reports").mkdir(parents=True, exist_ok=True)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    for label, (report, table) in reports.items():
        (OUT / "reports" / f"gap_decomposition_{label}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        (OUT / "tables" / f"contributions_{label}.jsonl").write_text(_table_bytes(table))
    (OUT / "README.md").write_text(_readme(reports))
    print(f"wrote {OUT.relative_to(ROOT)}")


def check() -> bool:
    reports = analyse()
    ok = (OUT / "README.md").exists() and (OUT / "README.md").read_text() == _readme(reports)
    for label, (report, table) in reports.items():
        rp, tp = OUT / "reports" / f"gap_decomposition_{label}.json", OUT / "tables" / f"contributions_{label}.jsonl"
        ok = ok and rp.exists() and rp.read_text() == json.dumps(report, indent=2, sort_keys=True) + "\n"
        ok = ok and tp.exists() and tp.read_text() == _table_bytes(table)
    print("world-panel gap analysis regenerates to the committed bytes" if ok else "world-panel gap analysis differs from its generator")
    return ok


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.write:
        write()
        return 0
    if args.check:
        return 0 if check() else 1
    for label, (report, _) in analyse().items():
        print(label, report["realized"]["difference"], {c["key"]: c["difference"] for c in report["components"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
