"""Developer interface 4: the parser's relational rules, stated (DC-D-11).

GLM 5.3 composed its own service package and was refused as a malformed
action because its ramp began before service commencement; nothing it saw
said that rule existed, since a JSON schema cannot relate one field to
another. Interface 4 changes nothing the environment enforces: it adds the
rules to the prompt, in the parser's words. Interfaces 2 and 3 keep their
prompts byte for byte.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aeread_families.datacenter_development.contracts import ContractValidationError
from aeread_families.datacenter_development.stack_environment import (
    DEVELOPER_INTERFACES,
    DataCenterStackPlugin,
    _terms,
    developer_interface,
)
from aeread_families.datacenter_development.stack_runner import (
    AMENDMENT_DECLINE_NOTE,
    DEVELOPER_PROMPT,
    MONTH_INDEXING_NOTE,
    RELATIONAL_RULES_NOTE,
    developer_prompt,
    load_stack_case,
    stack_developer_output_schemas,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASES = REPOSITORY_ROOT / "cases" / "datacenter_development_v1" / "v2"
CASE_003 = CASES / "full_stack_amendment_003.json"
CASE_004 = CASES / "full_stack_amendment_004.json"


def test_interface_four_is_the_v3_prompt_plus_the_rules_and_nothing_else() -> None:
    assert DEVELOPER_INTERFACES == (2, 3, 4)
    three, four = load_stack_case("v2", CASE_003), load_stack_case("v2", CASE_004)
    assert developer_interface(three.payload) == 3 and developer_interface(four.payload) == 4
    assert developer_prompt(three.payload, "v2") == ("datacenter_v2_developer_prompt_v3", DEVELOPER_PROMPT + MONTH_INDEXING_NOTE + AMENDMENT_DECLINE_NOTE)
    assert developer_prompt(four.payload, "v2") == ("datacenter_v2_developer_prompt_v4", DEVELOPER_PROMPT + MONTH_INDEXING_NOTE + AMENDMENT_DECLINE_NOTE + RELATIONAL_RULES_NOTE)
    # Same phase graph and legality; the schema differs only by the parser's
    # basis-point ceilings, which interface 4 carries and interface 3 did not.
    s3, s4 = stack_developer_output_schemas(three), stack_developer_output_schemas(four)
    loan3 = s3["datacenter_loan_offer_v1"]["properties"]["terms"]["anyOf"][0]["properties"]
    loan4 = s4["datacenter_loan_offer_v1"]["properties"]["terms"]["anyOf"][0]["properties"]
    assert "maximum" not in loan3["maximum_loan_to_value_bps"]
    assert loan4["maximum_loan_to_value_bps"]["maximum"] == 10_000 and loan4["spread_bps"]["maximum"] == 100_000
    assert loan4["maximum_commitment_cents"].get("maximum") is None  # only basis-point terms have ceilings
    stripped = json.loads(json.dumps(s4).replace(', "maximum": 10000', "").replace(', "maximum": 100000', ""))
    assert stripped == s3
    plugin = DataCenterStackPlugin("v2")
    a, b = plugin.validate_payload(three.payload), plugin.validate_payload(four.payload)
    assert [p.next_phases for p in plugin.phases(a)] == [p.next_phases for p in plugin.phases(b)]
    payload = json.loads(CASE_004.read_text())["payload"]
    payload["construct_controls"]["developer_interface"] = 5
    with pytest.raises(ValueError, match="developer_interface"):
        plugin.validate_payload(payload)


def test_the_note_states_every_relational_rule_the_parsers_raise() -> None:
    """Each rule in the note is a rule the parser enforces, shown by a term set
    that breaks only it; the GLM probe's own service package is the first."""

    service = json.loads(CASE_004.read_text())["payload"]["scripted_developer"]["service_terms"]
    glm = {
        **service,
        "service_commencement_month": 4,
        "ramp_schedule": [{"capacity_kw": 500, "month": 3}, {"capacity_kw": service["committed_capacity_kw"], "month": 4}],
    }
    with pytest.raises(ContractValidationError, match="ramp_schedule cannot begin before service commencement"):
        _terms("service", glm)
    assert "ramp_schedule cannot begin before service_commencement_month" in RELATIONAL_RULES_NOTE

    checks = {
        "capacity non-decreasing": {**service, "ramp_schedule": [{"capacity_kw": service["committed_capacity_kw"], "month": service["service_commencement_month"]}, {"capacity_kw": 1, "month": service["service_commencement_month"] + 1}]},
        "final capacity must equal committed_capacity_kw": {**service, "ramp_schedule": [{"capacity_kw": 1, "month": service["service_commencement_month"]}]},
        "cannot precede service commencement or follow the initial term": {**service, "customer_termination_option_month": service["service_commencement_month"] - 1},
    }
    for phrase, terms in checks.items():
        with pytest.raises(ContractValidationError):
            _terms("service", terms)
        assert phrase in RELATIONAL_RULES_NOTE, phrase
    epc = json.loads(CASE_004.read_text())["payload"]["scripted_developer"]["epc_terms"]
    with pytest.raises(ContractValidationError, match="must equal contract_price_cents"):
        _terms("epc", {**epc, "payment_schedule": [{"amount_cents": 1, "month": epc["notice_to_proceed_month"] + 1}]})
    assert "sum exactly to contract_price_cents" in RELATIONAL_RULES_NOTE
    loan = json.loads(CASE_004.read_text())["payload"]["scripted_developer"]["loan_terms"]
    with pytest.raises(ContractValidationError, match="maturity_month cannot precede draw_start_month"):
        _terms("loan", {**loan, "draw_start_month": loan["maturity_month"] + 1})
    assert "maturity_month cannot precede draw_start_month" in RELATIONAL_RULES_NOTE
