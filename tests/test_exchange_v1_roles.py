"""D9 per-role policy seam: seat-table validation, routing, pins, replay.

Keyless: LLM seats run against the same in-process fake provider as the runner
tests (real llm_agent parsing/cache/observer path, no network). The core claim
under test: with a `roles` block, each engine call lands on its assigned seat's
policy, everything is recorded per seat, and the run replays byte-identically.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_v1_roles as roles_mod  # noqa: E402
from aeread import exchange_v1_runner as runner  # noqa: E402
from aeread import llm_agent  # noqa: E402
from test_exchange_v1_runner import (  # noqa: E402
    FAKE_RESOLVED_MODEL,
    _FakeClient,
    _write_config,
)

MODEL_A = "test/candidate-model"
MODEL_B = "test/panel-model"
MODEL_ENV = "test/env-model"


def _roles_block(**overrides) -> dict:
    block = {
        "under_test": {"agents": [1], "policy": {"kind": "llm", "model": MODEL_A}},
        "panel": [
            {"agents": [2], "policy": {"kind": "frozen_llm", "model": MODEL_B}},
            {"agents": [3], "policy": {"kind": "scripted_bilateral_ir"}},
        ],
        "compiler": {"policy": {"kind": "frozen_llm", "model": MODEL_ENV}},
        "verifier": {"policy": {"kind": "frozen_llm", "model": MODEL_ENV}},
    }
    block.update(overrides)
    return block


@pytest.fixture
def fake_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_VERTEX", raising=False)
    monkeypatch.setattr(llm_agent, "_get_client", lambda: _FakeClient())
    cache_dir = tmp_path / "fake_llm_disk_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(llm_agent, "_cache_path", lambda _dir, key: cache_dir / f"{key}.json")
    return cache_dir


def _roles_config(tmp_path, name="test_roles", roles=None, **config_overrides):
    return _write_config(tmp_path, name, roles=roles or _roles_block(), **config_overrides)


def _run(config_path, tmp_path, run_id, **kwargs):
    return runner.run_v1(
        config_path,
        mode="live_frozen",
        out_root=tmp_path / "runs",
        run_id=run_id,
        quiet=True,
        **kwargs,
    )


# ---------------------------------------------------------------
# seat-table validation: refuse to run, never mis-run
# ---------------------------------------------------------------


def _parse(block, num_agents=3):
    return roles_mod.parse_role_table(block, num_agents)


def test_valid_table_parses_and_summarizes():
    table = _parse(_roles_block())
    assert table.under_test_agents == (1,)
    assert {g.seat for g in table.groups} == {"under_test", "panel", "compiler", "verifier"}
    summary = table.summary()
    assert summary["roles_schema_version"] == roles_mod.ROLES_SCHEMA_VERSION
    assert any(s["pin_resolved_model"] is None for s in summary["seats"])


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda b: b.pop("under_test"), "under_test"),
        (lambda b: b.pop("compiler"), "compiler"),
        (lambda b: b["panel"][0]["agents"].append(1), "assigned to both"),
        (lambda b: b["panel"].pop(1), "no seat"),  # drop agent 3's group entirely
        (lambda b: b["under_test"]["policy"].update(kind="nonsense"), "unknown policy kind"),
        (lambda b: b["under_test"]["policy"].pop("model"), "requires a 'model'"),
        (lambda b: b.update(extra_seat={}), "unknown keys"),
        (lambda b: b["compiler"]["policy"].update(kind="scripted_bilateral_ir"), "no standalone"),
        (lambda b: b["compiler"]["policy"].update(kind="scripted_bilateral_optimal"), "no standalone"),
        (lambda b: b["under_test"].update(agents=[99]), "1..3"),
    ],
)
def test_malformed_tables_are_refused(mutation, message):
    block = _roles_block()
    mutation(block)
    with pytest.raises(roles_mod.RoleConfigError, match=message):
        _parse(block)


def test_optimal_and_extract_panel_kinds_dispatch_to_the_right_selection():
    # the full-info panels are D9 seat kinds mapping onto the selection modes
    opt = runner._build_seat_policy({"kind": "scripted_bilateral_optimal"}, None, None)
    ext = runner._build_seat_policy({"kind": "scripted_bilateral_extract"}, None, None)
    assert opt.selection == runner.ScriptedBilateralIRPolicy.SELECTION_MAX_JOINT
    assert ext.selection == runner.ScriptedBilateralIRPolicy.SELECTION_MAX_OWN


def test_full_info_panel_parses_in_a_panel_seat():
    block = _roles_block(
        panel=[
            {"agents": [2], "policy": {"kind": "frozen_llm", "model": MODEL_B}},
            {"agents": [3], "policy": {"kind": "scripted_bilateral_optimal"}},
        ]
    )
    table = _parse(block)
    assert {g.seat for g in table.groups} == {"under_test", "panel", "compiler", "verifier"}


def test_live_learning_parses_but_refuses_to_run(tmp_path, fake_provider):
    block = _roles_block()
    block["under_test"]["policy"] = {"kind": "live-learning"}
    table = _parse(block)  # parsing must succeed: today's cases stay valid for L3
    assert table.under_test_agents == (1,)
    config = _roles_config(tmp_path, roles=block)
    with pytest.raises(runner.RunnerError, match="live-learning"):
        _run(config, tmp_path, "l3_refused")


# ---------------------------------------------------------------
# routing: every call lands on its assigned seat
# ---------------------------------------------------------------


def test_composite_routes_by_seat_and_records_per_seat(tmp_path, fake_provider):
    config = _roles_config(tmp_path)
    outcome = _run(config, tmp_path, "roles_e2e")
    rows = [
        json.loads(line)
        for line in (outcome.run_dir / "inference_manifest.jsonl").read_text().splitlines()
    ]
    by_agent_model = {(r["agent_id"], r["model"]) for r in rows if r["agent_id"] is not None}
    # agent 1 only ever driven by the candidate model, agent 2 only by the panel model
    assert all(m == MODEL_A for a, m in by_agent_model if a == 1)
    assert all(m == MODEL_B for a, m in by_agent_model if a == 2)
    # agent 3 is scripted: zero LLM rows
    assert not any(a == 3 for a, _ in by_agent_model)
    # seats recorded on every row; env rows exist (compiler/verifier)
    assert {r["seat"] for r in rows} == {"under_test", "panel", "env"}
    assert all(r["model"] == MODEL_ENV for r in rows if r["seat"] == "env")

    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    assert meta["funnel_check"]["ok"] is True
    assert meta["roles"]["seats"][0]["seat"] == "under_test"
    by_seat = meta["manifest_totals"]["by_seat"]
    assert set(by_seat) == {"under_test", "panel", "env"}
    assert sum(bucket["rows"] for bucket in by_seat.values()) == len(rows)


def test_composite_exposes_exactly_the_intended_surface():
    """A future plural batch method on the composite would silently flip the
    engine onto a batch path — pin the exposed surface."""
    composite = roles_mod.CompositePolicy({}, object(), object())
    for forbidden in ("communication_texts", "response_texts"):
        assert not hasattr(composite, forbidden)
    for required in (
        "communication_text", "propose_text", "respond_text", "finalize_text",
        "compile_transcript", "verify_compilation", "private_acceptance_texts",
        "protocol", "call_records", "usage_summary",
    ):
        assert hasattr(composite, required)


def test_protocol_fans_out_to_sub_policies():
    class _Sub:
        def __init__(self):
            self.protocol = None

    a, b = _Sub(), _Sub()
    composite = roles_mod.CompositePolicy({1: a}, b, b)
    sentinel = object()
    composite.protocol = sentinel
    assert a.protocol is sentinel and b.protocol is sentinel


# ---------------------------------------------------------------
# replay + pinning
# ---------------------------------------------------------------


def test_roles_run_replays_byte_identically(tmp_path, fake_provider, monkeypatch):
    config = _roles_config(tmp_path)
    live = _run(config, tmp_path, "roles_live")
    # replay must re-derive the seat table from the snapshot, with no provider
    monkeypatch.setattr(
        llm_agent, "_get_client", lambda: pytest.fail("provider touched during replay")
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    empty_cache = tmp_path / "empty_disk_cache"
    empty_cache.mkdir()
    monkeypatch.setattr(llm_agent, "_cache_path", lambda _dir, key: empty_cache / f"{key}.json")
    replay = runner.run_v1(
        mode="replay",
        replay_from=live.run_dir,
        out_root=tmp_path / "runs",
        run_id="roles_replay",
        quiet=True,
    )
    assert (replay.run_dir / "trace.jsonl").read_bytes() == (
        live.run_dir / "trace.jsonl"
    ).read_bytes()
    meta = json.loads((replay.run_dir / "run_meta.json").read_text())
    assert meta["roles"] is not None
    assert meta["funnel_check"]["ok"] is True


def test_matching_pin_passes_and_is_recorded(tmp_path, fake_provider):
    block = _roles_block()
    block["panel"][0]["policy"]["pin_resolved_model"] = FAKE_RESOLVED_MODEL
    outcome = _run(_roles_config(tmp_path, roles=block), tmp_path, "pin_ok")
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    assert meta["pin_check"]["ok"] is True
    assert meta["pin_check"]["pins"][0]["observed"] == [FAKE_RESOLVED_MODEL]
    assert meta["status"] == "complete"


def test_violated_pin_fails_the_run_as_panel_drift(tmp_path, fake_provider):
    block = _roles_block()
    block["panel"][0]["policy"]["pin_resolved_model"] = "panel-model-2025-01-01"
    config = _roles_config(tmp_path, roles=block)
    with pytest.raises(runner.RunnerError, match="panel drift"):
        _run(config, tmp_path, "pin_drift")
    meta = json.loads((tmp_path / "runs" / "pin_drift" / "run_meta.json").read_text())
    assert meta["status"] == "panel_drift"
    assert meta["pin_check"]["ok"] is False


def test_pin_evidence_isolated_per_seat_and_model(tmp_path, fake_provider):
    """Two panel groups share manifest_seat='panel' but use different models —
    a correct pin on one must not be polluted by a violated pin on the other,
    and the drift entry must name the right model."""
    block = _roles_block()
    block["panel"] = [
        {
            "agents": [2],
            "policy": {
                "kind": "frozen_llm",
                "model": MODEL_B,
                "pin_resolved_model": FAKE_RESOLVED_MODEL,  # matches the fake provider
            },
        },
        {
            "agents": [3],
            "policy": {
                "kind": "frozen_llm",
                "model": "test/other-panel-model",
                "pin_resolved_model": "other-panel-2025-01-01",  # violated
            },
        },
    ]
    config = _roles_config(tmp_path, roles=block)
    with pytest.raises(runner.RunnerError, match="panel drift"):
        _run(config, tmp_path, "pin_iso")
    meta = json.loads((tmp_path / "runs" / "pin_iso" / "run_meta.json").read_text())
    entries = {e["model"]: e for e in meta["pin_check"]["pins"]}
    assert entries[MODEL_B]["ok"] is True  # untouched by the other group's drift
    assert entries["test/other-panel-model"]["ok"] is False
    assert entries["test/other-panel-model"]["observed"] == [FAKE_RESOLVED_MODEL]


def test_pin_with_zero_observations_is_unverifiable_not_a_pass():
    """A pinned seat whose model produced no resolved versions yields ok=None
    (unverifiable) — never a crash, never a silent pass, never a drift."""
    block = _roles_block()
    block["panel"][0]["policy"]["pin_resolved_model"] = "pinned-version"
    table = roles_mod.parse_role_table(block, 3)
    recorder = runner.ManifestRecorder.__new__(runner.ManifestRecorder)
    recorder.resolved_models = {}  # zero observations recorded
    pin_check = runner.check_pins(table, recorder)
    assert pin_check["pins"][0]["ok"] is None
    assert pin_check["pins"][0]["observed"] == []
    assert pin_check["ok"] is True  # unverifiable does not fail the run


# ---------------------------------------------------------------
# legacy path untouched
# ---------------------------------------------------------------


def test_config_without_roles_uses_single_policy_path(tmp_path, fake_provider):
    config = _write_config(tmp_path, "test_legacy")
    outcome = _run(
        config, tmp_path, "legacy", options=runner.InferenceOptions(model=MODEL_A)
    )
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    assert meta["roles"] is None
    assert meta["pin_check"] is None
    rows = [
        json.loads(line)
        for line in (outcome.run_dir / "inference_manifest.jsonl").read_text().splitlines()
    ]
    assert {r["seat"] for r in rows} == {"env"}  # single-policy rows default to env


# ---------------------------------------------------------------
# review fixes: honest run_meta models + scripted-seat IR consent
# ---------------------------------------------------------------

from aeread import exchange_economy as ex  # noqa: E402


def test_run_meta_models_are_roles_driven_not_harness_defaults(tmp_path, fake_provider):
    """A roles-based run must not report the harness default model as its models.

    Regression: meta["models"] was built unconditionally from InferenceOptions,
    so every submission run reported the default gemini string for agents/
    compiler/verifier regardless of the roles block actually driving the run.
    """
    config = _roles_config(tmp_path)
    outcome = _run(config, tmp_path, "roles_meta")
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    blob = json.dumps(meta["models"])
    assert "gemini" not in blob  # the unused harness default must not appear
    for model in (MODEL_A, MODEL_B, MODEL_ENV):
        assert model in blob  # the actual per-seat models must


def _swap_world():
    return ex.ExchangeWorld(
        allocation=[[1, 0], [0, 1]],
        preferences=[[1.0, 4.0], [4.0, 1.0]],
    )


def _swap_mechanism():
    return ex.CompiledMechanism(
        proposer_id=1,
        label="swap",
        summary="mutually positive swap",
        transfers=[
            ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1),
            ex.Transfer(from_agent=2, to_agent=1, resource=2, quantity=1),
        ],
        consenting_agents=[1, 2],
        confidence=1.0,
    )


def test_scripted_policy_gives_truthful_ir_consent():
    """Scripted seats must emit a real, audit-clean private-acceptance decision.

    Regression: scripted seats abstained from private_acceptance_texts; under
    llm_structured the empty text parsed as malformed -> fail-open silent
    approval; under llm_structured_strict -> unconditional rejection.
    """
    world = _swap_world()
    swap = _swap_mechanism()
    policy = runner.ScriptedBilateralIRPolicy()
    for aid in (1, 2):
        text = policy.private_acceptance_text(world, aid, None, swap, None)
        audit = ex.audit_private_acceptance_decision(world, swap, aid, text)
        assert audit.approve is True
        assert audit.error_family == "none"


def test_scripted_policy_rejects_value_destroying_mechanism():
    world = _swap_world()
    give_away = ex.CompiledMechanism(
        proposer_id=2,
        label="one_way",
        summary="agent 1 gives its good away for nothing",
        transfers=[ex.Transfer(from_agent=1, to_agent=2, resource=1, quantity=1)],
        consenting_agents=[1, 2],
        confidence=1.0,
    )
    policy = runner.ScriptedBilateralIRPolicy()
    text = policy.private_acceptance_text(world, 1, None, give_away, None)
    audit = ex.audit_private_acceptance_decision(world, give_away, 1, text)
    assert audit.approve is False
    assert audit.error_family == "none"  # a clean, correctly-parsed rejection


def test_composite_routes_private_acceptance_to_scripted_seats():
    world = _swap_world()
    swap = _swap_mechanism()
    composite = roles_mod.CompositePolicy(
        {1: runner.ScriptedBilateralIRPolicy()}, object(), object()
    )
    texts = composite.private_acceptance_texts(world, [1], None, swap, None)
    assert 1 in texts
    audit = ex.audit_private_acceptance_decision(world, swap, 1, texts[1])
    assert audit.approve is True and audit.error_family == "none"


def test_scripted_responder_explicitly_accepts_the_concrete_proposal():
    """A scripted panel responder must echo the specific proposed swap, not emit
    a generic conditional consent — the frozen-LLM compiler cannot turn
    'I consent to any trade that improves my utility' into concrete transfers,
    so it compiles a no-op (the 2026-07-20 scripted-panel-collapse diagnosis).
    """
    world = _swap_world()  # a1 holds r1 & wants r2; a2 holds r2 & wants r1
    policy = runner.ScriptedBilateralIRPolicy()
    proposal = "PUBLIC ACTION\na1 gives 1 r1 to a2 for 1 r2"
    transcript = ex.RoundTranscript(
        round_index=1, controller_id=1, proposal_text=proposal,
        response_texts={}, final_text="", communication_texts={})
    # a2 gains from this swap -> explicit acceptance echoing the concrete terms
    text = policy.respond_text(world, 2, transcript, None)
    assert "ACCEPT" in text.upper()
    assert "r1" in text and "r2" in text        # the concrete swap, not a generic phrase
    assert "any trade" not in text.lower()      # the old conditional phrasing is gone


def test_defection_rate_engages_on_the_composite_roles_path():
    """A5 wiring fix (2026-07-23): protocol.defection_rate was dead code under D9 —
    build_policy returned the composite BEFORE the defection branch, so ablation
    outcomes were byte-identical across 0/0.25/0.50. With the fix, a seeded
    fraction of PANEL seats (never under_test, never env) become decliners."""
    from aeread import exchange_v1_runner as runner
    from aeread import exchange_economy as ex

    config = ex.load_experiment_config(ROOT / "configs/exchange_economy/cases_v0/case01_visible_bilateral_ir.json")
    import dataclasses
    proto = dataclasses.replace(config.protocol, defection_rate=0.5, defection_seed=46)
    config = dataclasses.replace(config, protocol=proto)
    raw_roles = {
        "under_test": {"agents": [1], "policy": {"kind": "llm", "model": "google/gemini-2.5-flash"}},
        "panel": [{"agents": [2, 3, 4, 5], "policy": {"kind": "frozen_llm", "model": "google/gemini-2.5-flash"}}],
        "compiler": {"policy": {"kind": "frozen_llm", "model": "google/gemini-2.5-flash"}},
        "verifier": {"policy": {"kind": "frozen_llm", "model": "google/gemini-2.5-flash"}},
    }
    table = roles_mod.parse_role_table(raw_roles, config.num_agents)
    policy = runner.build_policy("live_frozen", config, runner.InferenceOptions(), role_table=table)

    world = ex.make_world_from_config(config)
    defectors = [a for a in range(1, 6) if getattr(policy._agent_policies[a], "is_defector_seat", False)]
    assert 1 not in defectors, "the agent under test must never be scripted into defection"
    assert len(defectors) == 2, f"rate 0.5 over 4 panel seats -> 2 defectors, got {defectors}"
    # defector responses are scripted declines — NO network dispatch
    txt = policy.respond_text(world, defectors[0], _dummy_transcript(), [])
    assert "decline" in txt.lower()
    pa = policy.private_acceptance_texts(world, defectors, _dummy_transcript(), None, [])
    assert all('"approve": false' in t for t in pa.values())
    # funnel accounting: the wrapper must carry its OWN empty call_records —
    # delegating to the shared panel policy double-counts in the strict funnel
    wrapper = policy._agent_policies[defectors[0]]
    assert wrapper.call_records == [] and wrapper.call_records is not wrapper._inner.call_records
    # rate 0 -> no defector seats
    p0 = runner.build_policy("live_frozen", dataclasses.replace(
        config, protocol=dataclasses.replace(proto, defection_rate=0.0)),
        runner.InferenceOptions(), role_table=table)
    assert not any(getattr(p, "is_defector_seat", False) for p in p0._agent_policies.values())


def _dummy_transcript():
    from aeread import exchange_economy as ex
    return ex.RoundTranscript(round_index=1, controller_id=1, communication_texts={},
                              proposal_text="PUBLIC ACTION\nMESSAGE: hi\nSETTLEMENT: none",
                              response_texts={}, final_text="")
