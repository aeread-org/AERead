"""Pay or test version 3 under brief v3.1, played by isolated CLI subjects, and a comprehension check (diagnostic, no claim).

    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v31_cli.py \\
        --subject codex_sol61 --run-root runs/procurement_allocation/pay_or_test_v31_confirm_cli_codex_sol61 --execute
    PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/pay_or_test_v31_cli.py \\
        --subject claude_opus55 --comprehension runs/procurement_allocation/pay_or_test_v31_comprehension_claude_opus55.json

Declared in ``docs/families/procurement-allocation/pay_or_test_v31_brief_plan.md``. Everything is
``pay_or_test_v3_cli``'s, imported unchanged (its bytes and the plans of every sealed v3 run stay as they are), except
three things this driver adds for this process: the v3.1 brief as a new prompt arm, so the campaign and profile
identities are new; an arm keyed by pack and brief, so a v3.1 run on the confirmatory pack is stamped a diagnostic and
never inherits arm A's confirmatory status; and the comprehension check, which asks each subject three questions about
three confirmatory worlds before any action and plays nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pay_or_test_v3_cli as v3_cli
from pay_or_test_v3_cli import base, iso, v3
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.task.execution import ProviderFailure, ProviderRequest
from aeread_families.procurement_allocation import pay_or_test_v3_reference as reference
from aeread_families.procurement_allocation import pay_or_test_v31_prompt
from aeread_families.procurement_allocation.pay_or_test_reference import (
    GOOD_ON_TIME, GOOD_YIELD, POOR_YIELD, QUOTED, SAMPLED)
from aeread_families.procurement_allocation.pay_or_test_v2_reference import SHOWN_POOR
from aeread_families.procurement_allocation.pay_or_test_v3_environment import PayOrTestV3Plugin

PACK, PROMPT = v3.CONFIRM_PACK_ID, "v31_brief_v1"
ARM = {"replicates": 2, "claim_status": "development_diagnostic", "claim_scope": (
    "diagnostic declared in pay_or_test_v31_brief_plan.md: the confirmatory worlds under brief v3.1, two plays a world, "
    "paired by world with the sealed v3 runs; no claim and no model ranking")}

base.PROMPTS[PROMPT] = {"prompt_id": pay_or_test_v31_prompt.PROMPT_ID, "text": pay_or_test_v31_prompt.PAY_OR_TEST_V31_PROMPT,
                        "treatment_id": pay_or_test_v31_prompt.TREATMENT_ID}
base.PACKS[PACK]["prompts"] = (*base.PACKS[PACK]["prompts"], PROMPT)
_v3_model_plan = base.model_plan


def model_plan(subject, panel, runtime, pack=PACK, prompt=PROMPT):
    """The base plan with this arm's plays a world, status and scope; any other arm is the v3 driver's, unchanged."""
    if (pack, prompt) != (PACK, PROMPT):
        return _v3_model_plan(subject, panel, runtime, pack, prompt)
    base.CONTROLS["replicates"] = ARM["replicates"]
    plan = dict(v3_cli._model_plan(subject, panel, runtime, pack, prompt))
    plan.pop("plan_sha256")
    plan["claim_scope"] = ARM["claim_scope"]
    if panel == "panel":
        plan["claim_status"] = ARM["claim_status"]
    plan["plan_sha256"] = hashlib.sha256(canonical_json_bytes(plan)).hexdigest()
    return plan


base.model_plan = model_plan

# --- the comprehension check ----------------------------------------------------------------------------------------

#: The paper's worked example, then the first two other confirmatory worlds in slug order with a kind of two or more
#: new listings; in each, ``target`` is that kind's cheapest new listing and ``probe`` the cheapest sample among the rest.
COMPREHENSION_WORLDS = 3
WORKED_EXAMPLE = "myopic_pays__3"
TOLERANCE = 0.05
#: Probability only (plan amendment 2): asked also for its working, Opus 5.5's safeguards refused every ask (P-O-04).
ANSWER_SCHEMA = {"type": "object", "properties": {"probability": {"type": "number"}},
                 "required": ["probability"], "additionalProperties": False}


def _worlds() -> list[tuple[str, dict]]:
    found = {}
    for path in v3.case_paths(split=PACK):
        case = json.loads(path.read_text())
        found[case["case_id"].rsplit(".", 1)[1]] = case["payload"]
    rest = [slug for slug in sorted(found, key=lambda s: int(s.split("__")[1])) if slug != WORKED_EXAMPLE]
    chosen = [WORKED_EXAMPLE]
    for slug in rest:
        if len(chosen) == COMPREHENSION_WORLDS:
            break
        if any(len(group) >= 2 for group in reference.Reference(found[slug]).groups):
            chosen.append(slug)
    return [(slug, found[slug]) for slug in chosen]


def questions() -> list[dict]:
    """Each world's three questions and their exact answers from the version 3 reference."""
    out = []
    for slug, payload in _worlds():
        ref = reference.Reference(payload)
        group = next(g for g in ref.groups if len(g) >= 2)
        target = min(group, key=lambda i: (ref.price[i], ref.ids[i]))
        probe = min((i for i in group if i != target), key=lambda i: (ref.sample[i][0], ref.price[i], ref.ids[i]))
        seen, _, _ = ref.start()

        def after(state, kind, supplier, shown):
            return next(s for p, s in ref.outcomes(state, kind, supplier) if s[supplier] == shown)

        sound = lambda state: round(ref.type_odds(state, target)[0], 4)
        t, p = ref.ids[target], ref.ids[probe]
        quoted = after(seen, "request_quote", target, QUOTED)
        out += [
            {"world": slug, "id": "sound_sample_alone", "exact": sound(after(seen, "request_sample", probe, SAMPLED)),
             "question": f"Before any request, suppose you sample {p} and its sample states a yield of {GOOD_YIELD} "
                         f"(it does not fail inspection). What is then the probability that {t} is sound?"},
            {"world": slug, "id": "clean_quote_then_sound_sample",
             "exact": sound(after(quoted, "request_sample", probe, SAMPLED)),
             "question": f"Before any request, suppose you request a quote from {t}; it answers and states an on-time "
                         f"rate of {GOOD_ON_TIME} (it is not unreliable on delivery). Then you sample {p} and its sample "
                         f"states a yield of {GOOD_YIELD}. What is then the probability that {t} is sound?"},
            {"world": slug, "id": "failing_sample", "exact": sound(after(seen, "request_sample", probe, SHOWN_POOR)),
             "question": f"Before any request, suppose you sample {p} and its sample states a yield of {POOR_YIELD} "
                         f"(it fails inspection). What is then the probability that {t} is sound?"},
        ]
    return out


def _observation(slug: str) -> dict:
    payload = dict(_worlds())[slug]
    plugin = PayOrTestV3Plugin()
    case = plugin.validate_payload(payload)
    return plugin.observe(case, plugin.initial_state(case, None), "buyer", None)


async def comprehension(subject: str, out: Path, repeats: int = 2) -> dict:
    """Ask each question ``repeats`` times through the run's own isolated client, effort and brief; play nothing.

    A provider refusal is typed missingness with its failure text and the check goes on, and the record is rewritten
    after every ask (plan amendment 1; incident P-O-04, where one refusal aborted the check and kept nothing).
    """
    found = await v3_cli.probe(subject)
    if found["violations"]:
        raise SystemExit(f"isolation probe refuses the check: {found['violations']}")
    client = await base.discover(subject)
    spec = base.SUBJECTS[subject]
    answers: list[dict] = []
    record = {"plan": "docs/families/procurement-allocation/pay_or_test_v31_brief_plan.md, Section 5 and amendments 1 and 2",
              "subject": subject, "model": spec["model"], "reasoning_effort": base.CONTROLS["reasoning_effort"],
              "brief": {"prompt_id": pay_or_test_v31_prompt.PROMPT_ID,
                        "sha256": hashlib.sha256(pay_or_test_v31_prompt.PAY_OR_TEST_V31_PROMPT.encode()).hexdigest()},
              "isolation": found, "tolerance": TOLERANCE, "answers": answers}
    out.parent.mkdir(parents=True, exist_ok=True)

    def write() -> None:
        answered = [a for a in answers if not a["refused"]]
        record.update(asked=len(answers), answered=len(answered), refused=len(answers) - len(answered),
                      correct=sum(a["correct"] for a in answered))
        out.write_text(json.dumps(record, indent=1, default=str) + "\n")

    for item in questions():
        text = json.dumps({"observation": _observation(item["world"]), "question": item["question"],
                           "answer": "Give the probability as a number between 0 and 1."}, sort_keys=True)
        for repeat in range(repeats):
            request = ProviderRequest(
                provider_call_id=f"comprehension_{item['world']}_{item['id']}_{repeat}", provider=spec["provider"],
                base_url=None, model=spec["model"], revision=spec["model"],
                instructions=pay_or_test_v31_prompt.PAY_OR_TEST_V31_PROMPT, input_text=text, temperature=None,
                top_p=None, max_output_tokens=8000, reasoning_effort=base.CONTROLS["reasoning_effort"],
                timeout_seconds=300.0, request_sha256="", max_cost_usd=0.5 if spec["provider"] == "claude_code" else None,
                output_schema=ANSWER_SCHEMA, provider_metadata=dict(client.runtime_metadata),
            ).with_computed_hash()
            try:
                result = await client.complete(request)
            except ProviderFailure as failure:
                answers.append({**item, "repeat": repeat, "request_sha256": request.request_sha256, "refused": True,
                                "failure": str(failure)[:400], "correct": None})
                write()
                continue
            reply = json.loads(result.output_text)
            answers.append({**item, "repeat": repeat, "request_sha256": request.request_sha256, "refused": False,
                            "probability": reply["probability"],
                            "correct": abs(float(reply["probability"]) - item["exact"]) <= TOLERANCE,
                            "cost_usd_list": result.cost_usd})
            write()
    write()
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subject", choices=("claude_opus55", "codex_sol61"), required=True)
    parser.add_argument("--panel", choices=("gate", "panel"), default="panel")
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--comprehension", type=Path, help="write the comprehension check's record here; plays nothing")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.comprehension:
        record = asyncio.run(comprehension(args.subject, args.comprehension))
        print(json.dumps({k: record[k] for k in ("subject", "correct", "answered", "refused", "asked")}))
        return 0
    if not args.execute:
        print(json.dumps(model_plan(args.subject, args.panel, {"runtime_version": "plan-only"}), indent=1, default=str)[:3000])
        return 0
    found = asyncio.run(v3_cli.probe(args.subject))
    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "isolation_probe.json").write_text(json.dumps(found, indent=1, default=str))
    if found["violations"]:
        print(f"isolation probe refuses the run: {found['violations']}", file=sys.stderr)
        return 2
    base.CONTROLS["replicates"] = ARM["replicates"]
    artifact = asyncio.run(base.run(args.subject, args.panel, args.run_root, resume=args.resume, pack=PACK, prompt=PROMPT))
    print(json.dumps({"halted": artifact["halted"], "summary": {k: artifact["summary"].get(k) for k in
                                                                ("completed_trajectories", "planned_trajectory_count")}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
