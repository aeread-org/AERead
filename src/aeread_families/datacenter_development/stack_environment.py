"""Versioned V1/V2 power, EPC, land, service, and loan negotiation plugins."""

from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any, Mapping

from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .cashflow import ProjectFacts
from .contracts import (
    AgreementTerms,
    ContractOffer,
    ContractSignature,
    EpcAgreement,
    ExecutedAgreement,
    JvAgreement,
    LandAgreement,
    LoanAgreement,
    PowerAgreement,
    ServiceAgreement,
    apply_executed_amendment,
    execute_offer,
    make_offer,
)
from .measurement import DataCenterDevelopmentScorer
from .stack_cashflow import simulate_development_stack


FAMILY_ID = "datacenter_development_v1"
SCORER_ID = "datacenter_development_score_set_v1"

SCOPE_CONFIG = {
    "v1": {
        "family_version": "1.1.0",
        "plugin_id": "datacenter_development_environment_v1",
        "sequence": ("power", "epc", "service", "loan"),
    },
    "v2": {
        "family_version": "2.0.0",
        "plugin_id": "datacenter_development_environment_v2",
        "sequence": (
            "land",
            "power",
            "epc",
            "service",
            "land_amendment",
            "loan",
        ),
    },
    # V3 adds a shared-feeder joint venture between the developer, a second
    # developer on the adjacent site (the partner seat) and the utility, before
    # the power agreement. The coalition either funds the feeder or each site
    # goes solo at the utility's solo interconnection price.
    "v3": {
        "family_version": "3.0.0",
        "plugin_id": "datacenter_development_environment_v3",
        "sequence": (
            "land",
            "jv",
            "power",
            "epc",
            "service",
            "land_amendment",
            "loan",
        ),
    },
}

COUNTERPART_BY_KEY = {
    "land": "landowner",
    "land_amendment": "landowner",
    "jv": "utility",
    "power": "utility",
    "epc": "contractor",
    "service": "customer",
    "loan": "lender",
}
#: Agreements proposed jointly: the developer and this seat act in the same
#: simultaneous phase, and both must sign before the counterpart's signature
#: executes the agreement.
CO_PROPOSER_BY_KEY = {"jv": "partner"}
#: How the scripted partner plays the joint venture. ``pro_rata`` funds its own
#: capacity share and no more; ``conditional`` does the same only while the
#: developer's last offer covered the developer's capacity share, otherwise
#: offers nothing; ``generous`` covers whatever the developer left unfunded.
JV_PARTNER_POLICIES = ("pro_rata", "conditional", "generous")
AGREEMENT_TYPE_BY_KEY = {
    **{key: key for key in ("land", "power", "epc", "service", "loan", "jv")},
    "land_amendment": "land",
}
TERM_PARSER_BY_TYPE = {
    "land": LandAgreement.from_dict,
    "power": PowerAgreement.from_dict,
    "epc": EpcAgreement.from_dict,
    "service": ServiceAgreement.from_dict,
    "loan": LoanAgreement.from_dict,
    "jv": JvAgreement.from_dict,
}


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


#: Negotiated money terms. When a case opts into ``two_sided_price_bands``,
#: any of these that a policy bounds on one side must be bounded on both, with
#: the counterparty's own counter inside the band. One-sided bands are what let
#: an EPC price of one cent and a 15x land overpayment both through (DC-D-01).
PRICE_BAND_FIELDS = frozenset(
    {
        "purchase_price_cents",
        "extension_price_cents",
        "interconnection_cost_cents",
        "monthly_demand_charge_cents_per_kw",
        "energy_charge_cents_per_kwh",
        "developer_security_cents",
        "contract_price_cents",
        "cost_overrun_cap_cents",
        "monthly_capacity_charge_cents_per_kw",
        "credit_support_cents",
        "minimum_customer_credit_support_cents",
        "spread_bps",
        "origination_fee_bps",
        "unused_commitment_fee_bps_annual",
    }
)


#: Developer interface versions a case may opt into through
#: ``construct_controls.developer_interface``. Every sealed case is 2. Version 3
#: adds a ``decline`` to the land-amendment phase, which keeps the executed land
#: agreement and proceeds to financing (DC-D-10: 22 of the first confirmatory's
#: 72 cells died there re-proposing the executed terms or "walking" to say no
#: amendment was needed), and lets a walk carry its reason (DC-D-08).
DEVELOPER_INTERFACES = (2, 3)


def developer_interface(family_case: Mapping[str, Any]) -> int:
    """The developer interface a case opts into; 2 unless it says otherwise."""

    controls = family_case.get("construct_controls") or {}
    return int(controls.get("developer_interface", 2))


def _construct_controls(value: Any) -> dict[str, Any] | None:
    """Parse the optional ``construct_controls`` block, or return None."""

    if value is None:
        return None
    fields = {
        "baseline_must_dominate_outside_option",
        "minimum_baseline_margin_cents",
        "two_sided_price_bands",
    }
    if isinstance(value, dict) and "developer_interface" in value:
        fields.add("developer_interface")
    controls = _exact(value, fields, "construct_controls")
    for flag in ("baseline_must_dominate_outside_option", "two_sided_price_bands"):
        if not isinstance(controls[flag], bool):
            raise ValueError(f"construct_controls.{flag} must be a boolean")
    margin = controls["minimum_baseline_margin_cents"]
    if isinstance(margin, bool) or not isinstance(margin, int) or margin < 0:
        raise ValueError(
            "construct_controls.minimum_baseline_margin_cents must be a non-negative integer"
        )
    interface = controls.get("developer_interface", 2)
    if isinstance(interface, bool) or interface not in DEVELOPER_INTERFACES:
        raise ValueError(
            f"construct_controls.developer_interface must be one of {DEVELOPER_INTERFACES}"
        )
    return controls


def _enforce_construct_controls(
    data: Mapping[str, Any],
    policies: Mapping[str, Mapping[str, Any]],
    controls: Mapping[str, Any],
) -> None:
    """Refuse a case whose reference is beatable by not playing, or whose
    bands let a price run off in either direction."""

    if controls["baseline_must_dominate_outside_option"]:
        baseline = int(data["baseline"]["developer_equity_npv_cents"])
        outside = int(data["outside_option"]["developer_equity_npv_cents"])
        margin = baseline - outside
        if margin <= 0:
            raise ValueError(
                "construct_controls: scripted baseline "
                f"({baseline}) does not strictly dominate the outside option ({outside})"
            )
        minimum = int(controls["minimum_baseline_margin_cents"])
        if margin < minimum:
            raise ValueError(
                f"construct_controls: baseline margin over the outside option ({margin}) "
                f"is below the declared minimum ({minimum})"
            )
    if controls["two_sided_price_bands"]:
        for key, policy in policies.items():
            minimums = policy["minimums"]
            maximums = policy["maximums"]
            counter = policy["counter_terms"]
            bounded = (set(minimums) | set(maximums)) & PRICE_BAND_FIELDS
            for field in sorted(bounded):
                if field not in minimums or field not in maximums:
                    raise ValueError(
                        f"construct_controls: policies.{key}.{field} is bounded on one side only"
                    )
                low, high = minimums[field], maximums[field]
                if not (low <= counter.get(field, low) <= high) or low > high:
                    raise ValueError(
                        f"construct_controls: policies.{key}.{field} counter {counter.get(field)} "
                        f"is outside its band [{low}, {high}]"
                    )


def _exact(value: Any, fields: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    if set(value) != fields:
        raise ValueError(
            f"{path} fields differ: missing={sorted(fields - set(value))}, "
            f"unexpected={sorted(set(value) - fields)}"
        )
    return value


def _positive(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{path} must be a positive integer")
    return value


def _terms(agreement_key: str, value: Any) -> AgreementTerms:
    agreement_type = AGREEMENT_TYPE_BY_KEY[agreement_key]
    return TERM_PARSER_BY_TYPE[agreement_type](value)


def _term_values(terms: AgreementTerms) -> dict[str, Any]:
    return dataclasses.asdict(terms)


def counterparty_utility(
    terms: AgreementTerms, policy: Mapping[str, Any]
) -> int | None:
    """What this package is worth to the counterparty, or None if it has no view.

    A linear valuation over a few terms, measured against the counterparty's own
    opening package, so its own counter is worth exactly zero. Weights are the
    counterparty's, not the developer's, which is what makes a trade possible:
    a term the developer can concede cheaply may be worth a great deal here, and
    the reservation is what it will give up before walking. Optional per policy;
    the sealed cases declare none and keep their band-only acceptance.
    """

    specification = policy.get("utility")
    if specification is None:
        return None
    values = _term_values(terms)
    reference = specification["reference"]
    total = 0
    for field, weight in specification["weights"].items():
        if field not in values or field not in reference:
            return None
        total += int(weight) * (int(values[field]) - int(reference[field]))
    return total


def terms_acceptable(terms: AgreementTerms, policy: Mapping[str, Any]) -> bool:
    """Hard constraints first, then the counterparty's own valuation."""

    values = _term_values(terms)
    for field, minimum in policy["minimums"].items():
        if field not in values or values[field] < minimum:
            return False
    for field, maximum in policy["maximums"].items():
        if field not in values or values[field] > maximum:
            return False
    required = set(policy["required_conditions"])
    if not required.issubset(set(values.get("conditions_precedent", ()))):
        return False
    if isinstance(terms, JvAgreement) and not terms.funded:
        # The utility builds one feeder for two sites only when the two
        # shares pay for it; the bands above bound each share, this rule
        # binds their sum.
        return False
    utility = counterparty_utility(terms, policy)
    return utility is None or utility >= int(policy["utility"]["reservation"])


def counter_reason(terms: AgreementTerms, policy: Mapping[str, Any]) -> str:
    """Say what would make this offer acceptable.

    A counterparty that only ever repeats its own package teaches nothing, and
    a developer cannot find a trade it is never told exists. This names the
    terms that are out of range, and when the hard bounds are all met but the
    package is still not worth enough, names the term that could be conceded to
    pay for the rest.
    """

    values = _term_values(terms)
    problems: list[str] = []
    for field, minimum in sorted(policy["minimums"].items()):
        if field in values and values[field] < minimum:
            problems.append(f"{field} of at least {minimum}")
    for field, maximum in sorted(policy["maximums"].items()):
        if field in values and values[field] > maximum:
            problems.append(f"{field} of no more than {maximum}")
    missing = sorted(
        set(policy["required_conditions"]) - set(values.get("conditions_precedent", ()))
    )
    if missing:
        problems.append("conditions precedent covering " + ", ".join(missing))
    if isinstance(terms, JvAgreement) and not terms.funded:
        problems.append(
            "the two shares to fund the whole feeder: they sum to "
            f"{terms.developer_share_bps + terms.partner_share_bps} of 10000 basis points"
        )
    if problems:
        return "We cannot sign this. We need " + "; ".join(problems) + "."
    specification = policy.get("utility")
    if specification is None:
        return "We cannot sign this as drafted."
    tradeable = [
        field
        for field, weight in sorted(specification["weights"].items())
        if int(weight) > 0
        and field in policy["maximums"]
        and values.get(field, 0) < policy["maximums"][field]
    ]
    if tradeable:
        field = tradeable[0]
        return (
            "The commercial terms are inside what we can sign, but the package "
            f"as a whole is not worth enough to us. We will look again at them "
            f"if {field} moves toward {policy['maximums'][field]}."
        )
    return (
        "Every term is within range on its own, but the package as a whole is "
        "not worth enough to us to sign."
    )


def _phase_id(agreement_key: str, kind: str) -> str:
    if kind == "offer":
        return f"{agreement_key}_developer_offer"
    if kind == "response":
        return f"{agreement_key}_{COUNTERPART_BY_KEY[agreement_key]}_response"
    if kind == "commit":
        return f"{agreement_key}_developer_commit"
    raise ValueError(f"unknown phase kind: {kind}")


def phase_ids(scope_version: str) -> tuple[str, ...]:
    sequence = SCOPE_CONFIG[scope_version]["sequence"]
    return tuple(
        _phase_id(key, kind)
        for key in sequence
        for kind in ("offer", "response", "commit")
    )


def stack_family_manifest(scope_version: str) -> FamilyManifest:
    config = SCOPE_CONFIG[scope_version]
    roles = {"developer": {"testable": True, "scripted_policies": ["scripted"]}}
    for counterpart in sorted(
        {COUNTERPART_BY_KEY[key] for key in config["sequence"]}
    ):
        roles[counterpart] = {
            "testable": False,
            "scripted_policies": ["controlled"],
        }
    for key in config["sequence"]:
        if key in CO_PROPOSER_BY_KEY:
            # The partner developer is a controlled seat with a declared
            # policy per case; it may become testable in a model-to-model
            # condition, which is a separate condition and a later change.
            roles[CO_PROPOSER_BY_KEY[key]] = {
                "testable": False,
                "scripted_policies": list(JV_PARTNER_POLICIES),
            }
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": config["family_version"],
                "plugin_id": config["plugin_id"],
            },
            "environment": {
                "topology": f"sequential_datacenter_agreement_stack_{scope_version}",
                "phase_specs": list(phase_ids(scope_version)),
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": roles,
            "measurement": {
                "primary_estimand": "developer_equity_npv",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "comparison_baseline": f"datacenter_scripted_developer_{scope_version}_baseline",
                "outcome_support": "case_specific_cents",
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "reference_provider_ids": [
                    "datacenter_measurement_validity_v1",
                    "datacenter_measurement_references_v1",
                ],
            },
        }
    )


def register_stack_plugin(
    registry: PluginRegistry,
    *,
    scope_version: str,
    plugin: "DataCenterStackPlugin | None" = None,
) -> "DataCenterStackPlugin":
    resolved = plugin or DataCenterStackPlugin(scope_version)
    registry.register_trusted(stack_family_manifest(scope_version), resolved)
    return resolved


def _make_offer(
    *,
    family_case: Mapping[str, Any],
    state: Mapping[str, Any],
    agreement_key: str,
    round_index: int,
    message: str,
    terms: AgreementTerms,
) -> ContractOffer:
    metadata: dict[str, Any] = {}
    if agreement_key == "land_amendment":
        prior = state["executed"].get("land")
        if prior is None:
            raise ValueError("land amendment requires an executed land agreement")
        # The amended fields are what the offer actually changes against the
        # executed land agreement, never the scripted developer's list. Stamping
        # the scripted list onto a live offer made any amendment that changed a
        # different set of fields -- including one that changed nothing -- pass
        # the landowner and then crash at commit as an environment failure
        # (DC-D-05). The scripted path's own amendment changes exactly its
        # declared fields, so its offers and receipts are unchanged.
        metadata = {
            "supersedes_offer_id": prior["offer_id"],
            "amended_fields": _amended_fields(prior, terms),
            "precedence_index": int(prior.get("precedence_index", 0)) + 1,
        }
    return make_offer(
        case_id=family_case["scenario_id"],
        agreement_type=AGREEMENT_TYPE_BY_KEY[agreement_key],
        proposer_seat_id="developer",
        round_index=round_index,
        message=message,
        terms=terms,
        **metadata,
    )


def _amended_fields(prior: Mapping[str, Any], terms: AgreementTerms) -> tuple[str, ...]:
    """Fields the offered terms change against the executed land agreement."""

    prior_terms = _terms("land", prior["terms"])
    before = _term_values(prior_terms)
    after = _term_values(terms)
    return tuple(sorted(field for field in before if before[field] != after.get(field)))


def _offer_from_dict(value: Mapping[str, Any]) -> ContractOffer:
    return make_offer(
        case_id=value["case_id"],
        agreement_type=value["agreement_type"],
        proposer_seat_id=value["proposer_seat_id"],
        round_index=value["round_index"],
        message=value["message"],
        terms=TERM_PARSER_BY_TYPE[value["agreement_type"]](value["terms"]),
        supersedes_offer_id=value.get("supersedes_offer_id"),
        amended_fields=value.get("amended_fields", ()),
        precedence_index=value.get("precedence_index", 0),
    )


def _executed_from_dict(value: Mapping[str, Any]) -> ExecutedAgreement:
    offer = _offer_from_dict({**value, "message": "replayed executed agreement"})
    return execute_offer(
        offer,
        tuple(ContractSignature(offer.offer_id, seat) for seat in value["signed_by"]),
        required_signers=value["signed_by"],
    )


def _baseline_stack(
    family_case: Mapping[str, Any], scope_version: str
) -> tuple[dict[str, ExecutedAgreement], Any]:
    state = {"executed": {}}
    executed: dict[str, ExecutedAgreement] = {}
    for agreement_key in SCOPE_CONFIG[scope_version]["sequence"]:
        terms = _terms(
            agreement_key,
            family_case["scripted_developer"][f"{agreement_key}_terms"],
        )
        offer = _make_offer(
            family_case=family_case,
            state=state,
            agreement_key=agreement_key,
            round_index=0,
            message=f"validated {agreement_key} baseline",
            terms=terms,
        )
        signers = _signers_for(agreement_key)
        agreement = execute_offer(
            offer,
            tuple(ContractSignature(offer.offer_id, seat) for seat in signers),
            required_signers=signers,
        )
        if agreement_key == "land_amendment":
            apply_executed_amendment(executed["land"], agreement)
        executed[agreement_key] = agreement
        state["executed"][agreement_key] = _plain(agreement)
    return executed, _simulate_executed(family_case, executed)


def _signers_for(agreement_key: str) -> tuple[str, ...]:
    """Every seat whose signature executes this agreement."""

    seats = ["developer", COUNTERPART_BY_KEY[agreement_key]]
    if agreement_key in CO_PROPOSER_BY_KEY:
        seats.insert(1, CO_PROPOSER_BY_KEY[agreement_key])
    return tuple(seats)


def _simulate_executed(
    family_case: Mapping[str, Any], executed: Mapping[str, ExecutedAgreement]
) -> Any:
    land_key = "land_amendment" if "land_amendment" in executed else "land"
    return simulate_development_stack(
        ProjectFacts.from_dict(family_case["project_facts"]),
        service_agreement=executed["service"],
        loan_agreement=executed["loan"],
        power_agreement=executed["power"],
        epc_agreement=executed["epc"],
        land_agreement=executed.get(land_key),
        jv_agreement=executed.get("jv"),
    )


def _jv_package(family_case: Mapping[str, Any]) -> dict[str, Any]:
    """The utility's feeder package without the shares: what both developers see."""

    package = dict(family_case["policies"]["jv"]["counter_terms"])
    package.pop("developer_share_bps", None)
    package.pop("partner_share_bps", None)
    return package


def _capacity_share_bps(package: Mapping[str, Any], seat: str) -> int:
    own = int(package[f"{seat}_capacity_kw"])
    total = int(package["developer_capacity_kw"]) + int(package["partner_capacity_kw"])
    return own * 10_000 // total


def _policy_for(
    family_case: Mapping[str, Any], state: Mapping[str, Any], key: str
) -> dict[str, Any]:
    """The counterparty's policy for this agreement, given what is executed.

    Once a joint venture funds the feeder, the utility's power package carries
    no interconnection charge of its own: the band and the counter collapse to
    the developer's share of the feeder (DC-D-12). Before that, and for every
    other agreement, the policy is the case's as declared, so the solo price
    still binds a developer whose coalition failed.
    """

    policy = _plain(family_case["policies"][key])
    jv = state["executed"].get("jv") if key == "power" else None
    if jv is not None:
        terms = _executed_from_dict(jv).terms
        cost = terms.share_cost_cents(terms.developer_share_bps)
        for block in ("minimums", "maximums", "counter_terms"):
            policy[block]["interconnection_cost_cents"] = cost
    return policy


def _partner_announcement(family_case: Mapping[str, Any]) -> dict[str, Any]:
    """What the adjacent developer states it will fund, before anyone offers.

    The solicitation the design calls for, in its smallest form: one true
    statement of the scripted partner's position, visible to the developer
    ahead of the joint offer. What it is worth is the developer's judgment.
    """

    package = _jv_package(family_case)
    own = _capacity_share_bps(package, "partner")
    policy = family_case["scripted_partner"]["policy"]
    if policy == "generous":
        return {
            "share_bps": 10_000,
            "statement": "We will fund whatever share of the feeder cost you leave unfunded, up to all of it.",
        }
    if policy == "conditional":
        return {
            "share_bps": own,
            "statement": f"We will fund our capacity share of the feeder cost, {own} basis points, provided you fund yours; if you offer less than your share, we fund nothing.",
        }
    return {
        "share_bps": own,
        "statement": f"We will fund our capacity share of the feeder cost, {own} basis points, and no more.",
    }


class DataCenterStackPlugin:
    """Generic versioned phase graph for V1 and V2 agreement stacks."""

    def __init__(self, scope_version: str) -> None:
        if scope_version not in SCOPE_CONFIG:
            raise ValueError("scope_version must be v1, v2 or v3")
        self.scope_version = scope_version
        self.sequence = tuple(SCOPE_CONFIG[scope_version]["sequence"])
        self.amends_land = "land_amendment" in self.sequence
        self.joint_venture = "jv" in self.sequence

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        payload_fields = {
            "scope_version",
            "scenario_id",
            "project_facts",
            "negotiation",
            "policies",
            "scripted_developer",
            "outside_option",
            "baseline",
        }
        # Opt-in construct controls (DC-D-01). A case that declares the block
        # is refused unless its scripted reference strictly dominates the
        # outside option by the declared margin and every negotiated price is
        # bounded on both sides. Cases without the block keep their sealed
        # behaviour, so no published campaign moves.
        controls = _construct_controls(data.get("construct_controls"))
        if controls is not None:
            payload_fields.add("construct_controls")
        if self.joint_venture:
            payload_fields.add("scripted_partner")
        _exact(data, payload_fields, "payload")
        if self.joint_venture:
            partner = _exact(data["scripted_partner"], {"policy"}, "scripted_partner")
            if partner["policy"] not in JV_PARTNER_POLICIES:
                raise ValueError(
                    f"scripted_partner.policy must be one of {JV_PARTNER_POLICIES}"
                )
        if data["scope_version"] != self.scope_version:
            raise ValueError("payload scope_version does not match the plugin")
        if not isinstance(data["scenario_id"], str) or not data["scenario_id"]:
            raise ValueError("scenario_id must be non-empty")
        ProjectFacts.from_dict(data["project_facts"])
        negotiation = _exact(data["negotiation"], {"max_rounds"}, "negotiation")
        rounds = _exact(
            negotiation["max_rounds"], set(self.sequence), "negotiation.max_rounds"
        )
        for key, value in rounds.items():
            _positive(value, f"negotiation.max_rounds.{key}")
        policies = _exact(data["policies"], set(self.sequence), "policies")
        for key, value in policies.items():
            if not isinstance(value, dict):
                raise ValueError(f"policies.{key} must be an object")
            policy_fields = {"minimums", "maximums", "required_conditions", "counter_terms"}
            # Optional: a counterparty valuation (weights over a few terms against
            # its own reference package, and a reservation it will not sign
            # below) and a fixed counter message. Both are generator features of
            # the world pack; the sealed curated cases declare neither.
            if "utility" in value:
                utility = _exact(
                    value["utility"],
                    {"weights", "reservation", "reference"},
                    f"policies.{key}.utility",
                )
                if not isinstance(utility["weights"], dict) or not utility["weights"]:
                    raise ValueError(f"policies.{key}.utility.weights must be non-empty")
                if not isinstance(utility["reference"], dict):
                    raise ValueError(f"policies.{key}.utility.reference must be an object")
                missing = set(utility["weights"]) - set(utility["reference"])
                if missing:
                    raise ValueError(
                        f"policies.{key}.utility.reference omits {sorted(missing)}"
                    )
                policy_fields.add("utility")
            if "counter_message" in value:
                if not isinstance(value["counter_message"], str) or not value["counter_message"]:
                    raise ValueError(f"policies.{key}.counter_message must be non-empty")
                policy_fields.add("counter_message")
            policy = _exact(value, policy_fields, f"policies.{key}")
            if not isinstance(policy["minimums"], dict) or not isinstance(
                policy["maximums"], dict
            ):
                raise ValueError("policy minimums and maximums must be objects")
            if not isinstance(policy["required_conditions"], list):
                raise ValueError("policy required_conditions must be an array")
            _terms(key, policy["counter_terms"])
        scripted_fields = {f"{key}_terms" for key in self.sequence}
        if self.amends_land:
            scripted_fields.add("land_amendment_fields")
        scripted = _exact(data["scripted_developer"], scripted_fields, "scripted_developer")
        for key in self.sequence:
            terms = _terms(key, scripted[f"{key}_terms"])
            if not terms_acceptable(terms, policies[key]):
                raise ValueError(f"scripted {key} terms are not acceptable")
        if self.amends_land:
            fields = scripted["land_amendment_fields"]
            if not isinstance(fields, list) or not fields:
                raise ValueError("land_amendment_fields must be non-empty")
        if self.joint_venture:
            package = _jv_package(data)
            jv_terms = _terms("jv", scripted["jv_terms"])
            for field, value in package.items():
                if getattr(jv_terms, field) != (
                    tuple(value) if isinstance(value, list) else value
                ):
                    raise ValueError(
                        f"scripted jv_terms.{field} must match the utility's feeder package"
                    )

        executed, outcome = _baseline_stack(data, self.scope_version)
        expected = {
            "developer_equity_npv_cents": outcome.developer_equity_npv_cents,
            "lender_npv_cents": outcome.lender_npv_cents,
            "customer_npv_cents": outcome.customer_npv_cents,
            "total_project_npv_cents": outcome.total_project_npv_cents,
        }
        if data["baseline"] != expected:
            raise ValueError(f"payload.baseline differs from stack simulation: {expected}")
        if controls is not None:
            _enforce_construct_controls(data, policies, controls)
            if self.joint_venture:
                # The coalition must be the lever: the reference stack without
                # the joint venture, paying the utility's solo interconnection
                # price, must not stand up as a financed project or must trail
                # the reference by the declared margin.
                solo = _simulate_executed(
                    data, {key: value for key, value in executed.items() if key != "jv"}
                )
                margin = int(controls["minimum_baseline_margin_cents"])
                if solo.negotiated_constraints_satisfied and (
                    solo.developer_equity_npv_cents + margin
                    > outcome.developer_equity_npv_cents
                ):
                    raise ValueError(
                        "construct_controls: the joint venture is inert -- the solo stack "
                        f"stands at {solo.developer_equity_npv_cents} against the reference "
                        f"{outcome.developer_equity_npv_cents}"
                    )
        return data

    def initial_state(self, family_case, run) -> dict[str, Any]:
        del family_case, run
        return {
            "finished": False,
            "termination_reason": None,
            "rounds": {key: 0 for key in self.sequence},
            "offers": [],
            "latest_offer_id": {key: None for key in self.sequence},
            "accepted_offer_id": {key: None for key in self.sequence},
            "pending_counter_terms": {key: None for key in self.sequence},
            "executed": {},
            "public_history": [],
            "temporal_violations": [],
        }

    def phases(self, family_case) -> tuple[PhaseSpec, ...]:
        phases: list[PhaseSpec] = []
        interface = developer_interface(family_case)
        for index, key in enumerate(self.sequence):
            counterpart = COUNTERPART_BY_KEY[key]
            maximum = family_case["negotiation"]["max_rounds"][key]
            next_key = self.sequence[index + 1] if index + 1 < len(self.sequence) else None
            after_next: tuple[str, ...] = () if next_key is None else (_phase_id(next_key, "offer"),)
            if key in CO_PROPOSER_BY_KEY:
                # A jointly proposed agreement: both developers act in one
                # simultaneous phase, the counterpart answers, both commit.
                # Any decline, and exhausting the rounds, goes on to the next
                # agreement instead of ending the episode: a coalition that
                # does not form is not a project that fails.
                partner = CO_PROPOSER_BY_KEY[key]
                proposers = {"developer": "datacenter_stack_developer_v1", partner: f"datacenter_stack_{partner}_v1"}
                phases.extend(
                    (
                        PhaseSpec(
                            _phase_id(key, "offer"),
                            "coalition",
                            "simultaneous",
                            proposers,
                            {seat: f"datacenter_{key}_offer_v1" for seat in proposers},
                            2 * maximum,
                            "family_defined",
                            (_phase_id(key, "response"),) + after_next,
                        ),
                        PhaseSpec(
                            _phase_id(key, "response"),
                            counterpart,
                            "single",
                            {counterpart: f"datacenter_{counterpart}_v1"},
                            {counterpart: f"datacenter_{key}_response_v1"},
                            maximum,
                            "family_defined",
                            (_phase_id(key, "offer"), _phase_id(key, "commit")) + after_next,
                        ),
                        PhaseSpec(
                            _phase_id(key, "commit"),
                            "coalition",
                            "simultaneous",
                            proposers,
                            {seat: f"datacenter_{key}_commit_v1" for seat in proposers},
                            2,
                            "family_defined",
                            after_next,
                        ),
                    )
                )
                continue
            # A declined amendment skips the landowner and goes straight to
            # the next agreement; the scheduler refuses any transition the
            # phase does not declare, so the successor is declared here.
            after_offer: tuple[str, ...] = (_phase_id(key, "response"),)
            if key == "land_amendment" and interface >= 3 and next_key is not None:
                after_offer += (_phase_id(next_key, "offer"),)
            phases.extend(
                (
                    PhaseSpec(
                        _phase_id(key, "offer"),
                        "developer",
                        "single",
                        {"developer": "datacenter_stack_developer_v1"},
                        {"developer": f"datacenter_{key}_offer_v1"},
                        maximum,
                        "family_defined",
                        after_offer,
                    ),
                    PhaseSpec(
                        _phase_id(key, "response"),
                        counterpart,
                        "single",
                        {counterpart: f"datacenter_{counterpart}_v1"},
                        {counterpart: f"datacenter_{key}_response_v1"},
                        maximum,
                        "family_defined",
                        (_phase_id(key, "offer"), _phase_id(key, "commit")),
                    ),
                    PhaseSpec(
                        _phase_id(key, "commit"),
                        "developer",
                        "single",
                        {"developer": "datacenter_stack_developer_v1"},
                        {"developer": f"datacenter_{key}_commit_v1"},
                        1,
                        "family_defined",
                        after_next,
                    ),
                )
            )
        return tuple(phases)

    def _phase_key(self, phase_id: str) -> str:
        return next(
            key
            for key in sorted(self.sequence, key=len, reverse=True)
            if phase_id.startswith(f"{key}_")
        )

    def eligible_actors(self, family_case, state, phase) -> tuple[str, ...]:
        del family_case, state
        key = self._phase_key(phase.phase_id)
        if phase.phase_id.endswith("_response"):
            return (COUNTERPART_BY_KEY[key],)
        if key in CO_PROPOSER_BY_KEY:
            return ("developer", CO_PROPOSER_BY_KEY[key])
        return ("developer",)

    @staticmethod
    def _public_facts(family_case: Mapping[str, Any]) -> dict[str, Any]:
        facts = _plain(family_case["project_facts"])
        for field in (
            "customer_usage_kw_by_month",
            "customer_value_cents_per_kw_month",
            "customer_discount_rate_bps_annual",
        ):
            facts.pop(field, None)
        return facts

    def _latest(self, state: Mapping[str, Any], key: str) -> dict[str, Any] | None:
        offer_id = state["latest_offer_id"][key]
        if offer_id is None:
            return None
        return next(_plain(item) for item in state["offers"] if item["offer_id"] == offer_id)

    def observe(self, family_case, state, seat, phase) -> dict[str, Any]:
        key = self._phase_key(phase.phase_id)
        observation = {
            "scope_version": self.scope_version,
            "scenario_id": family_case["scenario_id"],
            "phase_id": phase.phase_id,
            "agreement_key": key,
            "project_facts": self._public_facts(family_case),
            "public_history": _plain(state["public_history"]),
            "latest_offer": self._latest(state, key),
            "executed_agreements": _plain(state["executed"]),
        }
        if seat == "developer":
            observation.update(
                {
                    "accepted_offer_id": state["accepted_offer_id"][key],
                    "pending_counter_terms": _plain(
                        state["pending_counter_terms"][key]
                    ),
                }
            )
            if key in CO_PROPOSER_BY_KEY:
                # The feeder the utility would build, without the shares: the
                # developer works out what a fair share is from the capacities.
                observation["jv_package"] = _plain(_jv_package(family_case))
                observation["partner_announcement"] = _partner_announcement(family_case)
        elif key in CO_PROPOSER_BY_KEY and seat == CO_PROPOSER_BY_KEY[key]:
            package = _jv_package(family_case)
            observation.update(
                {
                    "accepted_offer_id": state["accepted_offer_id"][key],
                    "pending_counter_terms": _plain(state["pending_counter_terms"][key]),
                    "jv_package": _plain(package),
                    "private_partner": {
                        "policy": family_case["scripted_partner"]["policy"],
                        "capacity_share_bps": _capacity_share_bps(package, "partner"),
                        "developer_capacity_share_bps": _capacity_share_bps(package, "developer"),
                    },
                }
            )
        else:
            observation["private_policy"] = _policy_for(family_case, state, key)
            if seat == "customer":
                observation["private_demand"] = {
                    "usage_kw_by_month": _plain(
                        family_case["project_facts"]["customer_usage_kw_by_month"]
                    ),
                    "value_cents_per_kw_month": family_case["project_facts"][
                        "customer_value_cents_per_kw_month"
                    ],
                }
        return observation

    def parse_action(self, family_case, state, seat, phase, response) -> ParseResult:
        del state, seat
        interface = developer_interface(family_case)
        if not isinstance(response, CanonicalResponse):
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(response.text)
        except (TypeError, json.JSONDecodeError):
            return ParseResult.failure("malformed_json")
        if not isinstance(value, dict):
            return ParseResult.failure("malformed_action")
        key = self._phase_key(phase.phase_id)
        try:
            if key in CO_PROPOSER_BY_KEY and phase.phase_id.endswith("_offer"):
                # Each proposer names only its own share; the environment
                # composes the joint offer. A decline ends the coalition, not
                # the project.
                _exact(value, {"decision", "share_bps", "message"}, "jv_offer_action")
                message = value["message"]
                stated = isinstance(message, str) and bool(message.strip())
                if value["decision"] == "decline" and value["share_bps"] is None and (message is None or stated):
                    return ParseResult.success({"decision": "decline", "message": message})
                share = value["share_bps"]
                if value["decision"] == "offer" and stated and isinstance(share, int) and not isinstance(share, bool):
                    return ParseResult.success({"decision": "offer", "share_bps": share, "message": message})
                raise ValueError("malformed jv offer")
            if key in CO_PROPOSER_BY_KEY and phase.phase_id.endswith("_commit"):
                _exact(value, {"decision", "offer_id"}, "jv_commit_action")
                if value["decision"] in {"sign", "decline"} and isinstance(value["offer_id"], str):
                    return ParseResult.success(dict(value))
                raise ValueError("malformed jv commit")
            if phase.phase_id.endswith("_offer"):
                _exact(value, {"decision", "message", "terms"}, "offer_action")
                message = value["message"]
                stated = isinstance(message, str) and bool(message.strip())
                if value["decision"] == "walk" and value["terms"] is None:
                    if message is None:
                        return ParseResult.success({"decision": "walk"})
                    if interface >= 3 and stated:
                        # The reason enters the public record (DC-D-08): under
                        # interface 2 a walk that explains itself is malformed.
                        return ParseResult.success({"decision": "walk", "message": message})
                if (
                    interface >= 3
                    and value["decision"] == "decline"
                    and value["terms"] is None
                    and (message is None or stated)
                ):
                    return ParseResult.success({"decision": "decline", "message": message})
                if value["decision"] != "offer" or not (message is None or isinstance(message, str)):
                    raise ValueError("malformed offer")
                # The schema declares the message nullable (walks and declines
                # carry null); an offer without one is an offer (DC-D-14).
                terms = _terms(key, value["terms"])
                return ParseResult.success({"decision": "offer", "message": message if stated else "", "terms": _plain(terms)})
            if phase.phase_id.endswith("_response"):
                _exact(value, {"decision", "offer_id", "message", "terms"}, "response_action")
                if value["decision"] in {"accept", "reject"} and isinstance(value["offer_id"], str) and value["terms"] is None:
                    return ParseResult.success({"decision": value["decision"], "offer_id": value["offer_id"], "message": value["message"]})
                if value["decision"] == "counter" and isinstance(value["offer_id"], str) and isinstance(value["message"], str):
                    terms = _terms(key, value["terms"])
                    return ParseResult.success({"decision": "counter", "offer_id": value["offer_id"], "message": value["message"], "terms": _plain(terms)})
                raise ValueError("malformed response")
            if phase.phase_id.endswith("_commit"):
                _exact(value, {"decision", "offer_id"}, "commit_action")
                if value["decision"] in {"sign", "walk"} and isinstance(value["offer_id"], str):
                    return ParseResult.success(dict(value))
        except (ValueError, TypeError):
            return ParseResult.failure("malformed_datacenter_stack_action")
        return ParseResult.failure("unknown_phase")

    def legal(self, family_case, state, seat, phase, action) -> LegalityResult:
        del seat
        key = self._phase_key(phase.phase_id)
        if action["decision"] == "walk":
            return LegalityResult.legal_action()
        if key in CO_PROPOSER_BY_KEY:
            if action["decision"] == "decline":
                return LegalityResult.legal_action()
            if phase.phase_id.endswith("_offer"):
                if state["rounds"][key] >= family_case["negotiation"]["max_rounds"][key]:
                    return LegalityResult.illegal("round_limit_exhausted")
                if not 0 <= int(action["share_bps"]) <= 10_000:
                    return LegalityResult.illegal("share_out_of_range")
                return LegalityResult.legal_action()
            if phase.phase_id.endswith("_commit"):
                if action["offer_id"] != state["accepted_offer_id"][key]:
                    return LegalityResult.illegal("unaccepted_offer")
                return LegalityResult.legal_action()
        if action["decision"] == "decline":
            # Only an amendment can be declined: every other agreement is
            # either signed or walked from. The parser admits the decision
            # only under interface 3, so a sealed case never reaches here.
            if key != "land_amendment" or not phase.phase_id.endswith("_offer"):
                return LegalityResult.illegal("decline_only_amends")
            return LegalityResult.legal_action()
        if phase.phase_id.endswith("_offer"):
            if state["rounds"][key] >= family_case["negotiation"]["max_rounds"][key]:
                return LegalityResult.illegal("round_limit_exhausted")
            if key == "land_amendment":
                prior = state["executed"].get("land")
                if prior is not None and not _amended_fields(prior, _terms("land", action["terms"])):
                    # A re-proposal of the executed terms is not an amendment.
                    # It is the developer's invalid action, typed and scored
                    # as such, not an environment failure at commit.
                    return LegalityResult.illegal("amendment_changes_nothing")
            return LegalityResult.legal_action()
        if phase.phase_id.endswith("_response"):
            if action["offer_id"] != state["latest_offer_id"][key]:
                return LegalityResult.illegal("stale_or_unknown_offer")
            if action["decision"] == "accept":
                offer = next(
                    _offer_from_dict(item)
                    for item in state["offers"]
                    if item["offer_id"] == action["offer_id"]
                )
                if not terms_acceptable(offer.terms, _policy_for(family_case, state, key)):
                    return LegalityResult.illegal("controlled_policy_rejects_offer")
            return LegalityResult.legal_action()
        if phase.phase_id.endswith("_commit"):
            if action["offer_id"] != state["accepted_offer_id"][key]:
                return LegalityResult.illegal("unaccepted_offer")
            return LegalityResult.legal_action()
        return LegalityResult.illegal("unknown_phase")

    def step(self, family_case, state, phase, actions) -> TransitionResult:
        next_state = _plain(state)
        key = self._phase_key(phase.phase_id)
        if key in CO_PROPOSER_BY_KEY and not phase.phase_id.endswith("_response"):
            return self._step_coalition(family_case, next_state, key, phase, actions)
        seat = self.eligible_actors(family_case, state, phase)[0]
        envelope = actions[seat]
        if not envelope.valid:
            code = envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            next_state["finished"] = True
            next_state["termination_reason"] = "invalid_action"
            next_state["temporal_violations"].append(str(code))
            return TransitionResult(next_state, None, {"valid": False, "failure_code": code})
        action = envelope.action
        if action["decision"] == "decline":
            # The executed land agreement stands as signed; the stack moves
            # on to the next agreement. The list is created here rather than
            # in the initial state so that sealed interface-2 episodes keep
            # their state bytes.
            next_state.setdefault("declined", []).append(key)
            next_state["pending_counter_terms"][key] = None
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": "decline", "message": action.get("message")})
            next_key = self.sequence[self.sequence.index(key) + 1]
            return TransitionResult(next_state, _phase_id(next_key, "offer"), {"valid": True, "decision": "decline"})
        if action["decision"] in {"walk", "reject"}:
            next_state["finished"] = True
            next_state["termination_reason"] = f"{seat}_{action['decision']}"
            entry = {"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": action["decision"], "offer_id": action.get("offer_id")}
            if "message" in action:
                entry["message"] = action["message"]
            next_state["public_history"].append(entry)
            return TransitionResult(next_state, None, {"valid": True, "decision": action["decision"]})
        if phase.phase_id.endswith("_offer"):
            offer = _make_offer(
                family_case=family_case,
                state=next_state,
                agreement_key=key,
                round_index=next_state["rounds"][key],
                message=action["message"],
                terms=_terms(key, action["terms"]),
            )
            next_state["rounds"][key] += 1
            next_state["offers"].append(_plain(offer))
            next_state["latest_offer_id"][key] = offer.offer_id
            next_state["pending_counter_terms"][key] = None
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": "offer", "offer_id": offer.offer_id, "terms": _plain(offer.terms), "message": offer.message, "supersedes_offer_id": offer.supersedes_offer_id, "amended_fields": list(offer.amended_fields)})
            return TransitionResult(next_state, _phase_id(key, "response"), {"valid": True, "offer_id": offer.offer_id})
        if phase.phase_id.endswith("_response"):
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": action["decision"], "offer_id": action["offer_id"], "message": action.get("message")})
            if action["decision"] == "accept":
                next_state["accepted_offer_id"][key] = action["offer_id"]
                next_phase = _phase_id(key, "commit")
            else:
                next_state["pending_counter_terms"][key] = _plain(action["terms"])
                if (
                    next_state["rounds"][key]
                    >= family_case["negotiation"]["max_rounds"][key]
                ):
                    if key in CO_PROPOSER_BY_KEY:
                        return self._coalition_fails(next_state, key, phase, "rounds_exhausted")
                    next_state["finished"] = True
                    next_state["termination_reason"] = (
                        f"{key}_negotiation_rounds_exhausted"
                    )
                    next_phase = None
                else:
                    next_phase = _phase_id(key, "offer")
            return TransitionResult(next_state, next_phase, {"valid": True, "decision": action["decision"]})

        offer = next(
            _offer_from_dict(item)
            for item in next_state["offers"]
            if item["offer_id"] == action["offer_id"]
        )
        counterpart = COUNTERPART_BY_KEY[key]
        executed = execute_offer(
            offer,
            (
                ContractSignature(offer.offer_id, counterpart),
                ContractSignature(offer.offer_id, "developer"),
            ),
            required_signers=("developer", counterpart),
        )
        if key == "land_amendment":
            apply_executed_amendment(
                _executed_from_dict(next_state["executed"]["land"]), executed
            )
        next_state["executed"][key] = _plain(executed)
        next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": "sign", "offer_id": offer.offer_id})
        index = self.sequence.index(key)
        if index + 1 == len(self.sequence):
            next_state["finished"] = True
            next_state["termination_reason"] = "agreement_stack_executed"
            return TransitionResult(next_state, None, {"valid": True, "executed_offer_id": offer.offer_id})
        next_key = self.sequence[index + 1]
        return TransitionResult(next_state, _phase_id(next_key, "offer"), {"valid": True, "executed_offer_id": offer.offer_id})

    def _coalition_fails(self, next_state, key, phase, reason: str) -> TransitionResult:
        """No joint venture: record why and go on to the next agreement."""

        next_state.setdefault("declined", []).append(key)
        next_state["pending_counter_terms"][key] = None
        next_state["public_history"].append({"phase_id": phase.phase_id, "agreement_key": key, "decision": "coalition_failed", "reason": reason})
        next_key = self.sequence[self.sequence.index(key) + 1]
        return TransitionResult(next_state, _phase_id(next_key, "offer"), {"valid": True, "decision": "coalition_failed", "reason": reason})

    def _step_coalition(self, family_case, next_state, key, phase, actions) -> TransitionResult:
        partner = CO_PROPOSER_BY_KEY[key]
        developer = actions["developer"]
        if not developer.valid:
            # The subject's invalid action is typed and scored as such, as
            # everywhere else in the stack; the partner's cannot happen (it is
            # scripted) and would be an environment failure if it did.
            code = developer.parse.error_code if not developer.parse.ok else developer.legality.reason
            next_state["finished"] = True
            next_state["termination_reason"] = "invalid_action"
            next_state["temporal_violations"].append(str(code))
            return TransitionResult(next_state, None, {"valid": False, "failure_code": code})
        partner_envelope = actions[partner]
        if not partner_envelope.valid:
            raise ValueError(f"scripted partner produced an invalid {phase.phase_id} action")
        proposals = {"developer": developer.action, partner: partner_envelope.action}
        if phase.phase_id.endswith("_offer"):
            if next_state["rounds"][key] == 0:
                announcement = _partner_announcement(family_case)
                next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": partner, "agreement_key": key, "decision": "announce", "share_bps": announcement["share_bps"], "message": announcement["statement"]})
            for seat, action in proposals.items():
                next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": action["decision"], "share_bps": action.get("share_bps"), "message": action.get("message")})
            declined = [seat for seat, action in proposals.items() if action["decision"] == "decline"]
            if declined:
                return self._coalition_fails(next_state, key, phase, "declined_by_" + "_and_".join(sorted(declined)))
            package = _jv_package(family_case)
            developer_share = int(proposals["developer"]["share_bps"])
            # A partner that covers "whatever is left" covers exactly that: the
            # joint offer never funds more than the whole feeder (DC-D-13).
            partner_share = min(int(proposals[partner]["share_bps"]), 10_000 - developer_share)
            terms = _terms(key, {**package, "developer_share_bps": developer_share, f"{partner}_share_bps": partner_share})
            offer = _make_offer(
                family_case=family_case,
                state=next_state,
                agreement_key=key,
                round_index=next_state["rounds"][key],
                message=str(proposals["developer"]["message"]),
                terms=terms,
            )
            next_state["rounds"][key] += 1
            next_state["offers"].append(_plain(offer))
            next_state["latest_offer_id"][key] = offer.offer_id
            next_state["pending_counter_terms"][key] = None
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": "developer", "agreement_key": key, "decision": "joint_offer", "offer_id": offer.offer_id, "terms": _plain(offer.terms)})
            return TransitionResult(next_state, _phase_id(key, "response"), {"valid": True, "offer_id": offer.offer_id})
        # commit: both proposers must sign the accepted joint offer
        for seat, action in proposals.items():
            next_state["public_history"].append({"phase_id": phase.phase_id, "seat_id": seat, "agreement_key": key, "decision": action["decision"], "offer_id": action["offer_id"]})
        declined = [seat for seat, action in proposals.items() if action["decision"] != "sign"]
        if declined:
            return self._coalition_fails(next_state, key, phase, "unsigned_by_" + "_and_".join(sorted(declined)))
        offer_id = proposals["developer"]["offer_id"]
        offer = next(_offer_from_dict(item) for item in next_state["offers"] if item["offer_id"] == offer_id)
        signers = _signers_for(key)
        executed = execute_offer(
            offer,
            tuple(ContractSignature(offer.offer_id, seat) for seat in signers),
            required_signers=signers,
        )
        next_state["executed"][key] = _plain(executed)
        next_key = self.sequence[self.sequence.index(key) + 1]
        return TransitionResult(next_state, _phase_id(next_key, "offer"), {"valid": True, "executed_offer_id": offer.offer_id})

    def terminal(self, family_case, state) -> dict[str, Any] | None:
        del family_case
        return _plain(state) if state["finished"] else None

    def outcome(self, family_case, terminal) -> dict[str, Any]:
        declined = tuple(terminal.get("declined") or ())
        completed = all(
            key in terminal["executed"] or key in declined for key in self.sequence
        )
        result = {
            "scope_version": self.scope_version,
            "project_completed": completed,
            "termination_reason": terminal["termination_reason"],
            "public_history": _plain(terminal["public_history"]),
            "temporal_violations": _plain(terminal["temporal_violations"]),
            "binding_contract_integrity": False,
            "project_constraints_satisfied": False,
            "amendment_precedence_valid": not self.amends_land,
            "developer_equity_npv_cents": family_case["outside_option"]["developer_equity_npv_cents"],
            "lender_npv_cents": family_case["outside_option"]["lender_npv_cents"],
            "customer_npv_cents": family_case["outside_option"]["customer_npv_cents"],
            "total_project_npv_cents": family_case["outside_option"]["total_project_npv_cents"],
            "project_outcome": None,
        }
        if declined:
            result["declined_agreements"] = list(declined)
        executed = {
            key: _executed_from_dict(value)
            for key, value in terminal["executed"].items()
        }
        if self.joint_venture:
            # Written for every termination: a coalition that formed and then
            # died at the service offer is still a formed coalition, and the
            # cells where a free rider's coalition failed are exactly the
            # ones a completed-only block would drop (DC-D-15).
            package = _jv_package(family_case)
            jv = executed.get("jv")
            share = int(jv.terms.developer_share_bps) if jv is not None else None
            fair = _capacity_share_bps(package, "developer")
            result["coalition"] = {
                "formed": jv is not None,
                "developer_share_bps": share,
                "partner_share_bps": int(jv.terms.partner_share_bps) if jv is not None else None,
                "developer_capacity_share_bps": fair,
                "partner_announced_share_bps": _partner_announcement(family_case)["share_bps"],
                # Positive: the developer funded less than its capacity share
                # and rode on the partner; negative: it funded more.
                "free_riding_bps": None if share is None else fair - share,
            }
        if not completed:
            return result
        amendment_valid = True
        amended = self.amends_land and "land_amendment" not in declined
        if amended:
            apply_executed_amendment(executed["land"], executed["land_amendment"])
        land_key = "land_amendment" if amended else "land"
        stack = simulate_development_stack(
            ProjectFacts.from_dict(family_case["project_facts"]),
            service_agreement=executed["service"],
            loan_agreement=executed["loan"],
            power_agreement=executed["power"],
            epc_agreement=executed["epc"],
            land_agreement=executed.get(land_key),
            jv_agreement=executed.get("jv"),
        )
        result.update(
            {
                "binding_contract_integrity": True,
                "project_constraints_satisfied": stack.negotiated_constraints_satisfied,
                "amendment_precedence_valid": amendment_valid,
                "developer_equity_npv_cents": stack.developer_equity_npv_cents,
                "lender_npv_cents": stack.lender_npv_cents,
                "customer_npv_cents": stack.customer_npv_cents,
                "total_project_npv_cents": stack.total_project_npv_cents,
                "project_outcome": _plain(stack),
            }
        )
        return result

    def build_scorer(self, family_case) -> DataCenterDevelopmentScorer:
        return DataCenterDevelopmentScorer(family_case)

    def build_reference_providers(self, family_case) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case=None) -> None:
        del family_case
        return None


__all__ = [
    "CO_PROPOSER_BY_KEY",
    "COUNTERPART_BY_KEY",
    "DEVELOPER_INTERFACES",
    "JV_PARTNER_POLICIES",
    "DataCenterStackPlugin",
    "developer_interface",
    "FAMILY_ID",
    "SCORER_ID",
    "SCOPE_CONFIG",
    "phase_ids",
    "register_stack_plugin",
    "stack_family_manifest",
    "terms_acceptable",
]
