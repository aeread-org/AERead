from __future__ import annotations

import pytest

from aeread.shared_runner.parity import (
    ParityContractError,
    ParityField,
    ParitySpec,
    compare_projections,
)


def test_refund_parity_compares_components_not_only_the_aggregate_reward() -> None:
    upstream = {
        "initial_db": {"order_1": {"status": "paid"}},
        "trajectory": {
            "tool_calls": ["get_order", "refund_order"],
            "tool_results": [{"status": "paid"}, {"status": "refunded"}],
        },
        "final_db": {"order_1": {"status": "refunded"}},
        "reward": {"db": 1.0, "communicate": 1.0, "aggregate": 1.0},
        "judge_artifact_sha256": "a" * 64,
    }
    adapted = {
        "state": {
            "initial": {"order_1": {"status": "paid"}},
            "final": {"order_1": {"status": "refunded"}},
        },
        "evidence": {
            "tools": ["get_order", "refund_order"],
            "results": [{"status": "paid"}, {"status": "refunded"}],
        },
        "scores": {"db": 1.0, "communication": 1.0, "upstream": 1.0},
        "judge": {"artifact_sha256": "a" * 64},
    }
    spec = ParitySpec(
        parity_id="tau3_retail_adapter_parity",
        parity_version="1.0.0",
        fields=(
            ParityField("initial_state", ("initial_db",), ("state", "initial")),
            ParityField(
                "ordered_tool_calls",
                ("trajectory", "tool_calls"),
                ("evidence", "tools"),
            ),
            ParityField(
                "ordered_tool_results",
                ("trajectory", "tool_results"),
                ("evidence", "results"),
            ),
            ParityField("final_state", ("final_db",), ("state", "final")),
            ParityField("db_reward", ("reward", "db"), ("scores", "db")),
            ParityField(
                "communication_reward",
                ("reward", "communicate"),
                ("scores", "communication"),
            ),
            ParityField(
                "judge_artifact",
                ("judge_artifact_sha256",),
                ("judge", "artifact_sha256"),
            ),
            ParityField(
                "aggregate_reward",
                ("reward", "aggregate"),
                ("scores", "upstream"),
            ),
        ),
    )

    report = compare_projections(upstream, adapted, spec)

    assert report.status == "match"
    assert report.mismatched_fields == ()
    assert len(report.field_results) == 8
    assert len(report.report_sha256) == 64


def test_supply_chain_parity_can_map_different_record_shapes() -> None:
    upstream = {
        "inventory": {"widget": 12},
        "orders": ["po_1", "po_2"],
        "fulfilled_value_minus_cost": 302.0000001,
    }
    adapted = {
        "terminal_state": {"stock": {"widget": 12}, "purchase_orders": ["po_1", "po_2"]},
        "measurement": {"objective": 302.0},
    }
    spec = ParitySpec(
        parity_id="supply_chain_adapter_parity",
        parity_version="1.0.0",
        fields=(
            ParityField("inventory", ("inventory",), ("terminal_state", "stock")),
            ParityField("orders", ("orders",), ("terminal_state", "purchase_orders")),
            ParityField(
                "objective",
                ("fulfilled_value_minus_cost",),
                ("measurement", "objective"),
                comparison="numeric_tolerance",
                absolute_tolerance=1e-6,
            ),
        ),
    )

    assert compare_projections(upstream, adapted, spec).status == "match"


def test_a_derived_field_match_is_marked_so_it_reads_as_dependent_confirmation() -> None:
    spec = ParitySpec(
        parity_id="refund_derived_fixture",
        parity_version="1.0.0",
        fields=(
            ParityField("db_reward", ("reward", "db"), ("scores", "db")),
            ParityField(
                "communication_reward",
                ("reward", "communicate"),
                ("scores", "communication"),
            ),
            ParityField(
                "aggregate_reward",
                ("reward", "aggregate"),
                ("scores", "aggregate"),
                derived_from=("db_reward", "communication_reward"),
            ),
        ),
    )

    report = compare_projections(
        {"reward": {"db": 1.0, "communicate": 1.0, "aggregate": 1.0}},
        {"scores": {"db": 1.0, "communication": 1.0, "aggregate": 1.0}},
        spec,
    )

    assert report.status == "match"
    by_id = {result.field_id: result for result in report.field_results}
    assert by_id["aggregate_reward"].matched is True
    assert by_id["aggregate_reward"].derived is True
    assert by_id["aggregate_reward"].derived_from == (
        "db_reward",
        "communication_reward",
    )
    assert by_id["db_reward"].derived is False
    assert by_id["db_reward"].derived_from == ()
    assert by_id["communication_reward"].derived is False


def test_derived_from_must_reference_other_declared_fields() -> None:
    with pytest.raises(ParityContractError, match="derived_from"):
        ParitySpec(
            parity_id="bad_reference_fixture",
            parity_version="1.0.0",
            fields=(
                ParityField("db_reward", ("db",), ("db",)),
                ParityField(
                    "aggregate_reward",
                    ("aggregate",),
                    ("aggregate",),
                    derived_from=("undeclared_field",),
                ),
            ),
        )
    with pytest.raises(ParityContractError, match="derived_from"):
        ParitySpec(
            parity_id="self_reference_fixture",
            parity_version="1.0.0",
            fields=(
                ParityField("db_reward", ("db",), ("db",)),
                ParityField(
                    "aggregate_reward",
                    ("aggregate",),
                    ("aggregate",),
                    derived_from=("aggregate_reward",),
                ),
            ),
        )


def test_a_derived_from_cycle_is_rejected_as_it_leaves_no_independent_field() -> None:
    with pytest.raises(ParityContractError, match="cycle"):
        ParitySpec(
            parity_id="cycle_fixture",
            parity_version="1.0.0",
            fields=(
                ParityField("db_reward", ("db",), ("db",), derived_from=("aggregate_reward",)),
                ParityField(
                    "aggregate_reward",
                    ("aggregate",),
                    ("aggregate",),
                    derived_from=("db_reward",),
                ),
            ),
        )


def test_parity_report_still_accepts_the_pre_unavailable_positional_signature() -> None:
    from aeread.shared_runner.parity import ParityReport

    report = ParityReport(
        "legacy_fixture",
        "1.0.0",
        "match",
        (),
        (),
        "a" * 64,
        "b" * 64,
        "c" * 64,
    )
    assert report.unavailable_fields == ()
    assert report.report_sha256 == "c" * 64


def test_a_missing_field_yields_a_typed_unavailable_verdict_not_a_dead_report() -> None:
    spec = ParitySpec(
        parity_id="refund_partial_fixture",
        parity_version="1.0.0",
        fields=(
            ParityField("final_state", ("final",), ("state",)),
            ParityField("db_reward", ("db_reward",), ("score",)),
            ParityField("judge_artifact", ("judge_sha256",), ("judge", "sha256")),
        ),
    )

    report = compare_projections(
        {
            "final": {"status": "refunded"},
            "db_reward": 1.0,
            "judge_sha256": "a" * 64,
        },
        # judge is entirely absent on the adapted side; db_reward disagrees.
        {"state": {"status": "refunded"}, "score": 0.0},
        spec,
    )

    assert report.status == "mismatch"
    assert report.mismatched_fields == ("db_reward",)
    assert report.unavailable_fields == ("judge_artifact",)
    assert len(report.field_results) == 3
    by_id = {result.field_id: result for result in report.field_results}
    assert by_id["final_state"].matched is True
    assert by_id["judge_artifact"].status == "unavailable"
    assert by_id["judge_artifact"].matched is False
    assert by_id["judge_artifact"].unavailable_sides == ("adapted",)
    assert by_id["judge_artifact"].upstream_sha256 is not None
    assert by_id["judge_artifact"].adapted_sha256 is None


def test_an_unavailable_field_never_lets_the_report_claim_match() -> None:
    spec = ParitySpec(
        parity_id="refund_unavailable_fixture",
        parity_version="1.0.0",
        fields=(
            ParityField("final_state", ("final",), ("state",)),
            ParityField("db_reward", ("db_reward",), ("score",)),
        ),
    )

    report = compare_projections(
        {"final": {"status": "refunded"}},
        {"state": {"status": "refunded"}, "score": 1.0},
        spec,
    )

    assert report.status == "unavailable"
    assert report.mismatched_fields == ()
    assert report.unavailable_fields == ("db_reward",)
    by_id = {result.field_id: result for result in report.field_results}
    assert by_id["db_reward"].unavailable_sides == ("upstream",)
    assert by_id["db_reward"].upstream_sha256 is None
    assert by_id["db_reward"].adapted_sha256 is not None


def test_zero_tolerance_compares_exactly_beyond_float_precision() -> None:
    spec = ParitySpec(
        parity_id="exact_numeric_fixture",
        parity_version="1.0.0",
        fields=(
            ParityField(
                "settlement_total",
                ("total",),
                ("total",),
                comparison="numeric_tolerance",
                absolute_tolerance=0.0,
            ),
        ),
    )

    differing = compare_projections({"total": 2**53}, {"total": 2**53 + 1}, spec)
    assert differing.status == "mismatch"
    assert differing.mismatched_fields == ("settlement_total",)
    assert differing.field_results[0].absolute_error == 1.0

    equal = compare_projections({"total": 2**53}, {"total": 2**53}, spec)
    assert equal.status == "match"


def test_parity_report_names_each_mismatch_instead_of_hiding_it_in_one_boolean() -> None:
    spec = ParitySpec(
        parity_id="refund_failure_fixture",
        parity_version="1.0.0",
        fields=(
            ParityField("final_state", ("final",), ("state",)),
            ParityField("db_reward", ("db_reward",), ("score",)),
        ),
    )

    report = compare_projections(
        {"final": {"status": "refunded"}, "db_reward": 1.0},
        {"state": {"status": "paid"}, "score": 0.0},
        spec,
    )

    assert report.status == "mismatch"
    assert report.mismatched_fields == ("final_state", "db_reward")
    assert all(result.upstream_sha256 != result.adapted_sha256 for result in report.field_results)
