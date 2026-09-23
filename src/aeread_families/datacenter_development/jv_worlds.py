"""Seeded V3 joint-venture worlds: a sampled feeder over every sealed V2 world.

Six curated cases show that the coalition can discriminate; they cannot say
how often a subject gets it wrong. This generator takes every world of the
sealed interface-3 pack (`cases/datacenter_development_v1/worlds_v3/`, the
same 24 worlds the confirmatory ran on) and lays a joint venture over it:

- the partner's capacity is a sampled multiple of the developer's contracted
  power, so the fair share is a computation and never a halving;
- the feeder's cost is a sampled multiple of the utility's solo interconnection
  price, so the coalition is worth a sampled amount, and sometimes nothing;
- the partner is one of the five types, its record of earlier feeders is a
  sampled length of truthful history (what that type announces, what it
  funds), and the joint offer runs for one round or three.

Every drawn layer goes through the plugin's own construct guard (the reference
must dominate the outside option by the margin, every price band must be
two-sided, and the solo stack must trail the reference by the margin or fail
admission). The pack keeps the first admitted layer per base world and the
manifest records how many draws that took and why the others were refused, so
the guard's admission rate is measured across seeds rather than asserted.
Regenerated, never edited: ``python -m
aeread_families.datacenter_development.jv_worlds --check`` must find the
committed pack byte for byte.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest

from .stack_environment import (
    FAMILY_ID,
    DEFAULT_COVERAGE_PRIOR_BPS,
    JV_PARTNER_CONDUCT,
    JV_PARTNER_POLICIES,
    SCOPE_CONFIG,
    DataCenterStackPlugin,
    record_best_response_share_bps,
)
from .stack_worlds import load_pack_manifest

GENERATOR_ID = "datacenter_v3_jv_world_generator"
GENERATOR_VERSION = "1.0.0"
PACK_ID = "datacenter_development_v3_jv_worlds_v1"
MASTER_SEED = 20260921
SCOPE_VERSION = "v3"
SPLIT = "worlds_v3_jv"
SEQUENCE = tuple(SCOPE_CONFIG[SCOPE_VERSION]["sequence"])
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CASES_ROOT = REPOSITORY_ROOT / "cases" / "datacenter_development_v1"
DEFAULT_BASE_ROOT = CASES_ROOT / "worlds_v3"
DEFAULT_OUTPUT_ROOT = CASES_ROOT / SPLIT
MAX_DRAWS_PER_WORLD = 16
#: The partner's capacity as a share of the developer's contracted power.
PARTNER_CAPACITY_RATIOS_BPS = (5_000, 7_500, 12_500, 15_000, 20_000, 30_000)
#: The feeder's cost as a multiple of the utility's solo interconnection price:
#: two sites share one feeder that costs more than one site's connection and
#: less than two, and at the top of the range the developer's share can exceed
#: the solo price, which is the layer the guard refuses as inert.
FEEDER_COST_RATIOS_BPS = (13_000, 15_000, 17_000, 19_000, 21_000, 24_000)
#: A record of one feeder can only be all or nothing, so it cannot separate a
#: developer that reads the frequency from one that checks whether a record
#: exists at all; every non-empty length here can be mixed.
RECORD_LENGTHS = (0, 2, 3, 4)
#: Joint ventures drawn over each base world. Two makes the pack a panel of 48
#: rather than 24, which halves the sampling noise in the aggregate the
#: reference has to win (DC-D-20).
LAYERS_PER_WORLD = 2
#: The partner's propensity to fund whatever is left, drawn per world. Its
#: record and its conduct here are independent draws from it, so the declared
#: estimator is the best response to the process that produced the world and no
#: constant policy can beat the reference in aggregate (DC-D-20). The grid's
#: mean is the declared prior an empty record falls back to.
COVERAGE_PROPENSITIES_BPS = (0, 2_500, 5_000, 7_500, 10_000)
#: Which types announce full coverage, by conduct.
TYPES_BY_COVERAGE = {True: ("generous", "posturing"), False: ("pro_rata", "conditional", "bluffing")}
JV_ROUNDS = (1, 3)
SEATS = (
    {"id": "developer", "role": "developer"},
    {"id": "partner", "role": "partner"},
    {"id": "landowner", "role": "landowner"},
    {"id": "utility", "role": "utility"},
    {"id": "contractor", "role": "contractor"},
    {"id": "customer", "role": "customer"},
    {"id": "lender", "role": "lender"},
)
VISIBILITY_POLICY = "datacenter_v2_public_terms_private_thresholds_explicit_amendments_v1"


def _round_hundred(value: int) -> int:
    return (value + 50) // 100 * 100


def _capacity_share_bps(own_kw: int, other_kw: int) -> int:
    return own_kw * 10_000 // (own_kw + other_kw)


def _record(policy: str, covered: list[bool], partner_share_bps: int) -> list[dict[str, int]]:
    """The partner's history: one entry per earlier feeder it built here.

    Each entry is an independent draw from the partner's coverage propensity,
    as its conduct on this feeder is, so a record is evidence and not a label.
    A pack whose records always matched the conduct could not tell a developer
    that reads the frequency from one that checks whether a record exists at
    all, and a record-follower could never be wrong, which is what makes the
    endpoint falsifiable on the subject's side rather than only on the
    controls'.
    """

    announced = 10_000 if policy in {"generous", "bluffing"} else partner_share_bps
    return [
        {"announced_share_bps": announced, "funded_share_bps": 10_000 if full else partner_share_bps}
        for full in covered
    ]


def draw_layer(base_payload: Mapping[str, Any], rng: random.Random) -> dict[str, Any]:
    """Sample one joint-venture layer for a base world; the guard judges it."""

    power = base_payload["scripted_developer"]["power_terms"]
    developer_kw = int(power["contracted_capacity_kw"])
    solo_cents = int(power["interconnection_cost_cents"])
    ratio = rng.choice(PARTNER_CAPACITY_RATIOS_BPS)
    partner_kw = _round_hundred(developer_kw * ratio // 10_000)
    feeder_kw = developer_kw + partner_kw
    cost_ratio = rng.choice(FEEDER_COST_RATIOS_BPS)
    feeder_cents = _round_hundred(solo_cents * cost_ratio // 10_000)
    # The partner's propensity, then its history and its conduct here as
    # independent draws from it; the type is whichever one has that conduct.
    propensity = rng.choice(COVERAGE_PROPENSITIES_BPS)
    length = rng.choice(RECORD_LENGTHS)
    covered = [rng.randrange(10_000) < propensity for _ in range(length)]
    covers_here = rng.randrange(10_000) < propensity
    policy = rng.choice(TYPES_BY_COVERAGE[covers_here])
    rounds = rng.choice(JV_ROUNDS)
    developer_fair = _capacity_share_bps(developer_kw, partner_kw)
    partner_fair = 10_000 - developer_fair
    package = {
        "conditions_precedent": list(base_payload["policies"]["power"]["required_conditions"][:1]) or ["site_control"],
        "developer_capacity_kw": developer_kw,
        "partner_capacity_kw": partner_kw,
        "feeder_capacity_kw": feeder_kw,
        "feeder_cost_cents": feeder_cents,
    }
    return {
        "package": package,
        "counter_shares": {"developer_share_bps": developer_fair, "partner_share_bps": partner_fair},
        "partner": {"policy": policy, "record": _record(policy, covered, partner_fair)},
        "rounds": rounds,
        "knobs": {
            "partner_capacity_ratio_bps": ratio,
            "feeder_cost_ratio_bps": cost_ratio,
            "partner_type": policy,
            "partner_conduct": JV_PARTNER_CONDUCT[policy],
            "record_length": length,
            "record_feeders_funded_in_full": sum(covered),
            "coverage_propensity_bps": propensity,
            "jv_rounds": rounds,
            "developer_capacity_share_bps": developer_fair,
            "developer_share_cost_cents": feeder_cents * developer_fair // 10_000,
            "solo_interconnection_cents": solo_cents,
        },
    }


def apply_layer(base: Mapping[str, Any], layer: Mapping[str, Any], *, index: int, master_seed: int, split: str, layer_index: int = 1) -> dict[str, Any]:
    """The V3 case document for a base world and a layer; validated, or raises."""

    payload = copy.deepcopy(dict(base["payload"]))
    payload["scope_version"] = SCOPE_VERSION
    slug = f"{base['case_id'].rsplit('.', 1)[1]}_jv{layer_index}"
    payload["scenario_id"] = f"datacenter_v3_jv_world_{slug}"
    package = layer["package"]
    payload["policies"]["jv"] = {
        "counter_terms": {**package, **layer["counter_shares"]},
        "maximums": {"developer_share_bps": 10_000, "partner_share_bps": 10_000},
        "minimums": {"developer_share_bps": 0, "partner_share_bps": 0},
        "required_conditions": list(package["conditions_precedent"]),
    }
    payload["negotiation"]["max_rounds"]["jv"] = int(layer["rounds"])
    payload["scripted_partner"] = copy.deepcopy(layer["partner"])
    licensed = record_best_response_share_bps(payload)
    payload["scripted_developer"]["jv_terms"] = {
        **package,
        "developer_share_bps": licensed,
        "partner_share_bps": 10_000 - licensed,
    }
    payload["construct_controls"]["developer_interface"] = 3
    # The coalition decision is judged against the developer's objective, so
    # the prompt states it (Housing D-21; DC-D-18).
    payload["construct_controls"]["developer_objective_stated"] = True
    # The prior is public because the rule uses it whenever the record is
    # empty; a number only the scorer knows cannot be a best response.
    payload["construct_controls"]["partner_coverage_prior_bps"] = DEFAULT_COVERAGE_PRIOR_BPS
    plugin = DataCenterStackPlugin(SCOPE_VERSION)
    # The baseline is what the engine says it is; the guard runs inside.
    try:
        plugin.validate_payload(payload)
    except ValueError as error:
        message = str(error)
        if "differs from stack simulation" not in message:
            raise
        payload["baseline"] = json.loads(message.split("differs from stack simulation: ", 1)[1].replace("'", '"'))
        plugin.validate_payload(payload)
    document = {
        "spec_version": CaseManifest.SPEC_VERSION,
        "case_id": f"{FAMILY_ID}.{split}.{slug}",
        "family_id": FAMILY_ID,
        "family_version": SCOPE_CONFIG[SCOPE_VERSION]["family_version"],
        "split": split,
        "world_seed": master_seed + index,
        "seats": [dict(seat) for seat in SEATS],
        "episode": {
            # Every agreement at its full allowance plus the joint venture's
            # two proposers per offer and per commit.
            "max_logical_actions": len(SEQUENCE) * (2 * 3 + 1) + 2 * 3 + 2,
            "termination": list(base["episode"]["termination"]),
        },
        "visibility_policy": VISIBILITY_POLICY,
        "payload": payload,
        "provenance": {
            "generator_id": GENERATOR_ID,
            "generator_version": GENERATOR_VERSION,
            "review_status": "generated",
        },
        "content_sha256": "0" * 64,
    }
    document["content_sha256"] = case_content_sha256(document)
    CaseManifest.from_dict(document)
    return document


def _refusal(error: ValueError) -> str:
    message = str(error)
    if "joint venture is inert" in message:
        return "inert_joint_venture"
    if "is a tie at coverage probability" in message:
        return "coalition_choice_is_a_tie"
    if "does not strictly dominate" in message or "below the declared minimum" in message:
        return "baseline_margin"
    if "not acceptable" in message:
        return "scripted_terms_refused"
    return "other"


def generate_pack(
    master_seed: int = MASTER_SEED,
    *,
    base_root: Path | str = DEFAULT_BASE_ROOT,
    split: str = SPLIT,
    pack_id: str = PACK_ID,
) -> dict[str, Any]:
    base_manifest = load_pack_manifest(base_root)
    rng = random.Random(master_seed)
    cases: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    refused: Counter[str] = Counter()
    draws_total = 0
    index = 0
    for base_entry in base_manifest["worlds"]:
        base = json.loads((Path(base_root) / base_entry["file"]).read_text(encoding="utf-8"))
        world_rng = random.Random(rng.getrandbits(64))
        for layer_index in range(1, LAYERS_PER_WORLD + 1):
            document = None
            draws = 0
            for _attempt in range(MAX_DRAWS_PER_WORLD):
                layer = draw_layer(base["payload"], world_rng)
                draws += 1
                try:
                    document = apply_layer(
                        base, layer, index=index, master_seed=master_seed, split=split, layer_index=layer_index
                    )
                except ValueError as error:
                    refused[_refusal(error)] += 1
                    continue
                break
            draws_total += draws
            if document is None:
                raise ValueError(
                    f"no admitted joint-venture layer for {base['case_id']} in {MAX_DRAWS_PER_WORLD} draws"
                )
            cases.append(document)
            entries.append(
                {
                    "case_id": document["case_id"],
                    "file": f"{document['case_id'].rsplit('.', 1)[1]}.json",
                    "content_sha256": document["content_sha256"],
                    "world_seed": document["world_seed"],
                    "base_case_id": base["case_id"],
                    "base_content_sha256": base["content_sha256"],
                    "base_stratum": base_entry.get("stratum"),
                    "layer": layer_index,
                    "draws": draws,
                    "knobs": layer["knobs"],
                    "record_best_response_share_bps": document["payload"]["scripted_developer"]["jv_terms"]["developer_share_bps"],
                    "baseline_developer_equity_npv_cents": document["payload"]["baseline"]["developer_equity_npv_cents"],
                }
            )
            index += 1
    manifest = {
        "schema_version": "aeread.datacenter_jv_world_pack/0.1",
        "pack_id": pack_id,
        "generator_id": GENERATOR_ID,
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "master_seed": master_seed,
        "scope_version": SCOPE_VERSION,
        "base_pack_id": base_manifest["pack_id"],
        "base_pack_sha256": base_manifest["artifact_sha256"],
        "world_count": len(entries),
        "layers_per_world": LAYERS_PER_WORLD,
        # The construct guard measured across seeds: every draw either became
        # a world or was refused for a named reason.
        "admission": {
            "draws": draws_total,
            "admitted": len(entries),
            "refused": dict(sorted(refused.items())),
            "admission_rate_bps": len(entries) * 10_000 // draws_total,
        },
        "strata": {
            "partner_type": dict(sorted(Counter(e["knobs"]["partner_type"] for e in entries).items())),
            "record_length": {str(k): v for k, v in sorted(Counter(e["knobs"]["record_length"] for e in entries).items())},
            "jv_rounds": {str(k): v for k, v in sorted(Counter(e["knobs"]["jv_rounds"] for e in entries).items())},
            "free_ride_licensed": sum(e["record_best_response_share_bps"] == 0 for e in entries),
            # A record that neither always nor never funded in full: the
            # stratum where "is there a record" and "what does it say" differ.
            "mixed_record": sum(
                0 < e["knobs"]["record_feeders_funded_in_full"] < e["knobs"]["record_length"]
                for e in entries
            ),
            # The partner's conduct here against what its record suggested:
            # where these differ, a developer that read the evidence correctly
            # can still be worse off than one that guessed.
            "record_contradicted_by_conduct": sum(
                (e["knobs"]["partner_conduct"] == "generous") != (e["record_best_response_share_bps"] == 0)
                for e in entries
            ),
            "coverage_propensity_bps": {
                str(value): sum(e["knobs"]["coverage_propensity_bps"] == value for e in entries)
                for value in COVERAGE_PROPENSITIES_BPS
            },
        },
        "worlds": entries,
    }
    manifest["artifact_sha256"] = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    return {"cases": cases, "manifest": manifest}


def _dump(value: Mapping[str, Any]) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def write_pack(output_root: Path | str = DEFAULT_OUTPUT_ROOT, *, master_seed: int = MASTER_SEED, base_root: Path | str = DEFAULT_BASE_ROOT, split: str = SPLIT, pack_id: str = PACK_ID) -> dict[str, Any]:
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    pack = generate_pack(master_seed, base_root=base_root, split=split, pack_id=pack_id)
    for document, entry in zip(pack["cases"], pack["manifest"]["worlds"]):
        (root / entry["file"]).write_text(_dump(document), encoding="utf-8")
    (root / "manifest.json").write_text(_dump(pack["manifest"]), encoding="utf-8")
    return pack["manifest"]


def check_pack(output_root: Path | str = DEFAULT_OUTPUT_ROOT, *, master_seed: int = MASTER_SEED, base_root: Path | str = DEFAULT_BASE_ROOT, split: str = SPLIT, pack_id: str = PACK_ID) -> dict[str, Any]:
    """The committed pack equals a fresh generation, world for world; the generator's own digest is reported apart."""

    root = Path(output_root)
    pack = generate_pack(master_seed, base_root=base_root, split=split, pack_id=pack_id)
    drift: list[str] = []
    for document, entry in zip(pack["cases"], pack["manifest"]["worlds"]):
        path = root / entry["file"]
        if not path.is_file() or path.read_text(encoding="utf-8") != _dump(document):
            drift.append(entry["file"])
    manifest_path = root / "manifest.json"
    generator_drift = False
    if not manifest_path.is_file():
        drift.append("manifest.json")
    else:
        on_disk = json.loads(manifest_path.read_text(encoding="utf-8"))
        fresh = pack["manifest"]
        generator_drift = on_disk.get("generator_sha256") != fresh["generator_sha256"]
        mask = ("generator_sha256", "artifact_sha256")
        if {k: v for k, v in on_disk.items() if k not in mask} != {k: v for k, v in fresh.items() if k not in mask}:
            drift.append("manifest.json")
    return {"pack_id": pack_id, "drift": drift, "reproducible": not drift, "generator_drift": generator_drift}


def load_jv_pack_manifest(output_root: Path | str = DEFAULT_OUTPUT_ROOT) -> dict[str, Any]:
    return load_pack_manifest(output_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE_ROOT, help="the sealed V2 pack to lay the joint venture over")
    parser.add_argument("--master-seed", type=int, default=MASTER_SEED)
    parser.add_argument("--split", default=SPLIT)
    parser.add_argument("--pack-id", default=PACK_ID)
    parser.add_argument("--check", action="store_true", help="verify instead of write")
    arguments = parser.parse_args(argv)
    options = {"master_seed": arguments.master_seed, "base_root": arguments.base, "split": arguments.split, "pack_id": arguments.pack_id}
    if arguments.check:
        result = check_pack(arguments.output, **options)
        print(canonical_json_bytes(result).decode("utf-8"))
        return 0 if result["reproducible"] else 1
    manifest = write_pack(arguments.output, **options)
    print(canonical_json_bytes({k: manifest[k] for k in ("pack_id", "world_count", "admission", "strata", "artifact_sha256")}).decode("utf-8"))
    return 0


__all__ = ["DEFAULT_OUTPUT_ROOT", "GENERATOR_ID", "MASTER_SEED", "PACK_ID", "check_pack", "draw_layer", "generate_pack", "load_jv_pack_manifest", "main", "write_pack"]


if __name__ == "__main__":
    raise SystemExit(main())
