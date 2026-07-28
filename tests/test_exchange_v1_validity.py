"""Offline validity checks for v1 exchange-economy ablations."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_v1_validity as v1  # noqa: E402


CONTROL_CONFIG = ROOT / "configs" / "exchange_economy" / "core_atomic_ir_clean.json"
SOLICITED_CONFIG = ROOT / "configs" / "exchange_economy" / "treatment_public_solicitation_solicited.json"
VISIBILITY_GAP_CONTROL_CONFIG = (
    ROOT / "configs" / "exchange_economy" / "treatment_public_solicitation_visibility_gap_control.json"
)
VISIBILITY_GAP_TREATMENT_CONFIG = (
    ROOT / "configs" / "exchange_economy" / "treatment_public_solicitation_visibility_gap.json"
)
VISIBILITY_GAP_RESPONSE_FINALIZATION_CONFIG = (
    ROOT
    / "configs"
    / "exchange_economy"
    / "treatment_public_solicitation_visibility_gap_response_finalization.json"
)


def test_public_solicitation_pair_is_single_conceptual_knob():
    control = ex.load_experiment_config(CONTROL_CONFIG)
    treatment = ex.load_experiment_config(SOLICITED_CONFIG)

    check = v1.compare_paired_ablation_configs(
        control,
        treatment,
        conceptual_knob="public_solicitation_path",
    )

    assert check.passed is True
    assert check.conceptual_knob == "public_solicitation_path"
    assert check.expected_diffs == {
        "name": ("core_atomic_ir_clean", "treatment_public_solicitation_solicited"),
        "description": (control.description, treatment.description),
        "protocol.name": ("core_atomic_ir_clean", "treatment_public_solicitation_solicited"),
        "protocol.public_broadcast": (False, True),
        "protocol.response_scope": ("visible_only", "solicited_public"),
    }
    assert check.unexpected_diffs == {}
    assert check.shared_fields["seed"] == 23
    assert check.shared_fields["controllers"] == [1, 3, 5]
    assert check.shared_fields["protocol.visibility_seed"] == 911


def test_paired_validity_report_records_ordering_before_llm_calls():
    report = v1.evaluate_paired_public_solicitation_validity(
        CONTROL_CONFIG,
        SOLICITED_CONFIG,
        rounds=2,
        random_samples=2,
        random_seed=7,
    )

    assert report.paired_ablation.passed is True
    assert report.control.config_name == "core_atomic_ir_clean"
    assert report.treatment.config_name == "treatment_public_solicitation_solicited"
    assert report.treatment.information_constrained_gain >= report.treatment.stronger_heuristic_gain
    assert report.treatment.hidden_discovery_gain == pytest.approx(
        report.treatment.information_constrained_gain - report.treatment.stronger_heuristic_gain
    )
    assert set(report.environment_ordering) == {
        "random_lt_greedy",
        "greedy_lt_stronger_heuristic",
        "stronger_heuristic_lt_information_constrained",
    }
    for inequality in report.environment_ordering.values():
        assert inequality.left_metric
        assert inequality.right_metric
        assert inequality.left_value >= 0.0
        assert inequality.right_value >= 0.0
    assert report.llm_calls == 0


def test_visibility_gap_pair_is_clean_and_has_hidden_discovery_pressure():
    report = v1.evaluate_paired_public_solicitation_validity(
        VISIBILITY_GAP_CONTROL_CONFIG,
        VISIBILITY_GAP_TREATMENT_CONFIG,
        rounds=3,
        random_samples=2,
        random_seed=7,
    )

    assert report.paired_ablation.passed is True
    assert report.control.hidden_discovery_gain == pytest.approx(0.0)
    assert report.treatment.hidden_discovery_gain > 0.0
    assert (
        report.treatment.information_constrained_gain
        > report.treatment.stronger_heuristic_gain
    )


def test_response_finalization_arm_only_changes_settlement_timing_knob():
    atomic = ex.load_experiment_config(VISIBILITY_GAP_TREATMENT_CONFIG)
    response_finalization = ex.load_experiment_config(VISIBILITY_GAP_RESPONSE_FINALIZATION_CONFIG)

    check = v1.compare_paired_ablation_configs(
        atomic,
        response_finalization,
        conceptual_knob="response_aware_partial_finalization",
        allowed_diffs={
            "name",
            "description",
            "protocol.name",
            "protocol.atomic_commit",
            "protocol.partial_clearing",
        },
    )

    assert check.passed is True
    assert check.expected_diffs["protocol.atomic_commit"] == (True, False)
    assert check.expected_diffs["protocol.partial_clearing"] == (False, True)


def test_trace_summary_detects_hidden_solicitation_conversion(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                '{"round_index": 1, "controller_id": 1, '
                '"communication_texts": {"1": "PUBLIC ACTION\\nADDRESSEES:\\nall agents\\nMESSAGE:\\nAnyone with r6 should respond.\\nRESPONSE REQUEST:\\nall agents opt in with offers\\nSETTLEMENT:\\nnone\\nCONSENT CONDITIONS:\\nnone\\nPUBLIC STATE UPDATE:\\nnone\\nNO-TRANSFER FALLBACK:\\nNo transfer."}, '
                '"proposal_text": "PUBLIC ACTION\\nADDRESSEES:\\na6\\nMESSAGE:\\nI propose trading with hidden responder a6.\\nRESPONSE REQUEST:\\na6\\nSETTLEMENT:\\na1 | a6 | r1 | 1\\na6 | a1 | r6 | 1\\nCONSENT CONDITIONS:\\na1 and a6\\nPUBLIC STATE UPDATE:\\nnone\\nNO-TRANSFER FALLBACK:\\nNo transfer.", '
                '"response_texts": {"4": "visible contact response", "6": "hidden responder accepts"}, '
                '"verified_before_private_acceptance": {"transfers": [{"from": 1, "to": 6, "resource": "r1", "quantity": 1}, {"from": 6, "to": 1, "resource": "r6", "quantity": 1}]}, '
                '"event": {"applied": true}}',
                '{"round_index": 2, "controller_id": 3, '
                '"communication_texts": {"3": "PUBLIC ACTION\\nADDRESSEES:\\na2\\nMESSAGE:\\nVisible-only note.\\nRESPONSE REQUEST:\\na2\\nSETTLEMENT:\\nnone\\nCONSENT CONDITIONS:\\nnone\\nPUBLIC STATE UPDATE:\\nnone\\nNO-TRANSFER FALLBACK:\\nNo transfer."}, '
                '"proposal_text": "PUBLIC ACTION\\nADDRESSEES:\\na2\\nMESSAGE:\\nvisible trade only\\nRESPONSE REQUEST:\\na2\\nSETTLEMENT:\\nnone", '
                '"response_texts": {"2": "visible response"}, '
                '"verified_before_private_acceptance": {"transfers": []}, '
                '"event": {"applied": false}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    summary = v1.summarize_public_solicitation_trace(
        trace_path,
        VISIBILITY_GAP_TREATMENT_CONFIG,
    )

    assert summary.rounds == 2
    assert summary.public_solicitation_activated_rounds == 1
    assert summary.hidden_responder_rounds == 1
    assert summary.hidden_responder_count == 1
    assert summary.hidden_responder_used_in_proposal_rounds == 1
    assert summary.applied_trades == 1
    assert summary.applied_trades_with_hidden_responders == 1


def test_trace_summary_does_not_count_final_only_public_text_as_response_activation(tmp_path):
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(
        '{"round_index": 1, "controller_id": 1, '
        '"communication_texts": {"1": "PUBLIC ACTION\\nADDRESSEES:\\na4\\nMESSAGE:\\nVisible only.\\nRESPONSE REQUEST:\\na4\\nSETTLEMENT:\\nnone"}, '
        '"proposal_text": "PUBLIC ACTION\\nADDRESSEES:\\na4\\nMESSAGE:\\nVisible proposal.\\nRESPONSE REQUEST:\\na4\\nSETTLEMENT:\\nnone", '
        '"response_texts": {"4": "visible response"}, '
        '"final_text": "PUBLIC ACTION\\nADDRESSEES:\\nall agents\\nMESSAGE:\\nFinal notice to everyone.\\nRESPONSE REQUEST:\\nall agents respond with offers or opt in\\nSETTLEMENT:\\nnone", '
        '"verified_before_private_acceptance": {"transfers": []}, '
        '"event": {"applied": false}}\n',
        encoding="utf-8",
    )

    summary = v1.summarize_public_solicitation_trace(
        trace_path,
        VISIBILITY_GAP_TREATMENT_CONFIG,
    )

    assert summary.public_solicitation_activated_rounds == 0
    assert summary.hidden_responder_rounds == 0


# --- generic single-knob ablation validity (any mechanism, not just solicitation) ---
#
# The oracle scoring (evaluate_config_validity) is exponential for full-visibility
# multiparty substrates, so these unit-test the *new* wrapper wiring with the oracle
# stubbed out. The real oracle path stays covered by the public-solicitation tests
# above (which use a fast limited-contact substrate).

PARTIAL_CLEARING_CONTROL = (
    ROOT / "configs" / "exchange_economy" / "mech_partial_clearing_control.json"
)
PARTIAL_CLEARING_TREATMENT = (
    ROOT / "configs" / "exchange_economy" / "mech_partial_clearing_treatment.json"
)


def _fake_validity_result(name: str) -> "v1.ConfigValidityResult":
    # monotone increasing gains so the expected oracle ordering passes
    return v1.ConfigValidityResult(
        config_name=name,
        rounds=2,
        no_op_gain=0.0,
        random_mean_gain=1.0,
        greedy_gain=5.0,
        stronger_heuristic_gain=8.0,
        information_constrained_gain=12.0,
        hidden_discovery_gain=0.0,
        greedy_applied_rounds=2,
        stronger_heuristic_applied_rounds=2,
        information_constrained_applied_rounds=2,
    )


def test_generic_paired_validity_threads_allowed_diffs(monkeypatch):
    monkeypatch.setattr(
        v1, "evaluate_config_validity", lambda config, **kw: _fake_validity_result(config.name)
    )
    report = v1.evaluate_paired_validity(
        PARTIAL_CLEARING_CONTROL,
        PARTIAL_CLEARING_TREATMENT,
        conceptual_knob="partial_clearing",
        allowed_diffs={
            "name",
            "description",
            "protocol.name",
            "protocol.partial_clearing",
        },
        rounds=2,
        random_samples=2,
        random_seed=1,
    )

    assert report.paired_ablation.passed is True
    assert report.paired_ablation.conceptual_knob == "partial_clearing"
    assert report.paired_ablation.unexpected_diffs == {}
    assert report.paired_ablation.expected_diffs["protocol.partial_clearing"] == (
        False,
        True,
    )
    # provider-free; oracle ordering built from the (stubbed) treatment metrics
    assert report.llm_calls == 0
    assert report.environment_ordering["random_lt_greedy"].passed is True
    assert report.environment_ordering["greedy_lt_stronger_heuristic"].passed is True


def test_generic_paired_validity_flags_unexpected_diff_when_allowed_set_too_narrow(monkeypatch):
    monkeypatch.setattr(
        v1, "evaluate_config_validity", lambda config, **kw: _fake_validity_result(config.name)
    )
    report = v1.evaluate_paired_validity(
        PARTIAL_CLEARING_CONTROL,
        PARTIAL_CLEARING_TREATMENT,
        conceptual_knob="partial_clearing",
        allowed_diffs={"name", "description", "protocol.name"},
        rounds=2,
        random_samples=2,
        random_seed=1,
    )

    assert report.paired_ablation.passed is False
    assert "protocol.partial_clearing" in report.paired_ablation.unexpected_diffs
