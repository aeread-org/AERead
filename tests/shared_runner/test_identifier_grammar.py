"""Identifiers that leave the repository, and the reasoning condition.

The colon rule is not stylistic. rLLM composes an episode id as
``f"{task_id}:{rollout_idx}"`` and recovers the task with ``id.split(":")[0]``,
so a colon inside a row id silently returns the first fragment and collapses
every training group into one. That happened, in a real run, and the symptom
was a grouping metric of 1 rather than an error.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aeread.sdk.v1 import (
    CaseManifest,
    ReasoningCondition,
    is_exportable_id,
)


@pytest.mark.parametrize(
    "value",
    [
        "housing_v1",
        "housing-v1-e0-seed7-two-tenant-two-listing",
        "housing_v1__dev__000001",
        "tau3.retail.base",
        "a",
        "case1",
    ],
)
def test_ordinary_identifiers_are_exportable(value: str) -> None:
    assert is_exportable_id(value)


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("aeread:integration-v1:case:s7", "a colon truncates an rLLM task id"),
        ("housing v1", "a space breaks file names and row keys"),
        ("Housing_V1", "upper case collides on case-insensitive filesystems"),
        ("_leading", "leading punctuation sorts and globs badly"),
        ("trailing-", "trailing punctuation sorts and globs badly"),
        ("", "an empty id names nothing"),
        ("case/01", "a slash is a path separator"),
        ("case#1", "a hash is a fragment marker in a URL"),
    ],
)
def test_unsafe_identifiers_are_refused(value: str, why: str) -> None:
    assert not is_exportable_id(value), why


def test_a_case_cannot_be_authored_with_a_colon_in_its_id() -> None:
    with pytest.raises(ValidationError):
        CaseManifest.from_content(
            case_id="housing:dev:1",
            family_id="housing_v1",
            family_version="1.0.0",
            split="dev",
            world_seed=1,
            seats=({"seat_id": "tenant_0", "role_id": "tenant"},),
            max_logical_actions=1,
            terminal_reasons=("done",),
            visibility_policy="housing_private_types_v1",
            payload={},
            provenance={"source_kind": "curated", "review_status": "curated"},
        )


# ---------------------------------------------------------------------------
# Reasoning is an experimental condition, not a flag.
# ---------------------------------------------------------------------------


def _condition(**overrides: object) -> ReasoningCondition:
    base: dict[str, object] = {
        "reasoning_condition_id": "provider_default_v1",
        "mode": "provider_default",
        "output_token_budget": 1200,
    }
    return ReasoningCondition(**{**base, **overrides})


def test_provider_default_is_a_condition_of_its_own() -> None:
    condition = _condition()
    assert condition.mode == "provider_default"
    assert condition.reasoning_effort is None
    # It is emphatically not "disabled": nothing here claims reasoning is off.
    assert condition.mode != "disabled"


def test_a_disabled_condition_cannot_also_ask_for_effort() -> None:
    with pytest.raises(ValidationError, match="reasoning effort"):
        _condition(mode="disabled", reasoning_effort="high")


def test_a_provider_without_a_switch_is_not_a_control_arm() -> None:
    condition = _condition(mode="unsupported_control")
    assert condition.reasoning_effort is None
    with pytest.raises(ValidationError, match="reasoning budget"):
        _condition(mode="unsupported_control", reasoning_token_budget=4096)


def test_a_total_budget_must_contain_the_budgets_inside_it() -> None:
    with pytest.raises(ValidationError, match="total_completion_budget"):
        _condition(
            mode="enabled",
            reasoning_effort="high",
            reasoning_token_budget=8000,
            output_token_budget=2000,
            total_completion_budget=4000,
        )
    ok = _condition(
        mode="enabled",
        reasoning_effort="high",
        reasoning_token_budget=8000,
        output_token_budget=2000,
        total_completion_budget=10000,
    )
    assert ok.total_completion_budget == 10000


def test_a_visible_rationale_needs_a_declared_protocol() -> None:
    with pytest.raises(ValidationError, match="declared protocol"):
        _condition(rationale_visibility="provider_summary")
    with pytest.raises(ValidationError, match="visibility"):
        _condition(rationale_protocol_id="decision_record_v1")
    ok = _condition(
        rationale_visibility="task_visible_decision_record",
        rationale_protocol_id="decision_record_v1",
    )
    assert ok.rationale_protocol_id == "decision_record_v1"


def test_private_chain_of_thought_is_never_retained() -> None:
    with pytest.raises(ValidationError):
        _condition(reasoning_content_retained=True)


def test_the_condition_is_part_of_the_hashed_agent_configuration() -> None:
    """Two runs differing only in reasoning are different configurations."""

    from aeread.sdk.v1 import content_sha256

    from tests.shared_runner.fakes import fake_agent_profile

    baseline = fake_agent_profile("candidate")
    high = baseline.model_copy(
        update={
            "execution_config": baseline.execution_config.model_copy(
                update={
                    "reasoning": _condition(
                        reasoning_condition_id="provider_reasoning_high_v1",
                        mode="enabled",
                        reasoning_effort="high",
                    )
                }
            )
        }
    )
    assert content_sha256(baseline) != content_sha256(high)


def test_a_reasoning_default_cannot_smuggle_an_explicit_setting() -> None:
    """`provider_default` means nothing was configured, so nothing was."""

    with pytest.raises(ValidationError, match="reasoning effort"):
        _condition(mode="provider_default", reasoning_effort="high")
    with pytest.raises(ValidationError, match="reasoning budget"):
        _condition(mode="provider_default", reasoning_token_budget=5000)


def test_a_disabled_condition_cannot_reintroduce_reasoning_through_provider_parameters() -> (
    None
):
    """The side channel is the same claim by another route."""

    with pytest.raises(ValidationError, match="provider_parameters"):
        _condition(
            mode="disabled",
            provider_parameters={"reasoning_effort": "high", "thinking_budget": 20000},
        )
    # An unrelated provider parameter is still fine.
    ok = _condition(mode="disabled", provider_parameters={"top_p": 0.9})
    assert dict(ok.provider_parameters) == {"top_p": 0.9}


def test_an_exchange_case_id_obeys_the_same_grammar() -> None:
    """The colon rule was closed in one commit and reopened in the next."""

    from aeread.families.exchange_v1 import (
        ExchangeCompatibilityError,
        ExchangeV1EnvironmentPlugin,
    )

    plugin = ExchangeV1EnvironmentPlugin()
    with pytest.raises(ExchangeCompatibilityError, match="exportable identifier"):
        plugin.validate_case(
            {
                "case_id": "aeread:integration-v1:case:s7",
                "config_path": (
                    "configs/exchange_economy/cases_v0/case01_visible_bilateral_ir.json"
                ),
                "seed": 7,
            }
        )
