"""Exchange V1 runner (Part A): run-dir completeness, determinism, offline policy.

All tests are keyless (no API): `--mode offline` uses the scripted deterministic
policy, so these run in CI. Determinism is defined on trace.jsonl BYTES — same
(config, seed) must reproduce the identical file.
"""
from __future__ import annotations

import itertools

import dataclasses
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from aeread import exchange_economy as ex  # noqa: E402
from aeread import exchange_subgame_oracles as sg  # noqa: E402
from aeread import exchange_v1_runner as runner  # noqa: E402
from aeread import llm_agent  # noqa: E402

FAKE_MODEL = "test/fake-model"
FAKE_RESOLVED_MODEL = "test-fake-model-2026-01-15"


def _write_config(tmp_path: Path, name: str, **overrides) -> Path:
    payload = {
        "name": name,
        "description": "test fixture",
        "num_agents": 3,
        "num_resources": 3,
        "units_per_home_resource": 10,
        "seed": 3,
        "rounds": 2,
        "controllers": [1],
        "utility_mode": "linear",
        "protocol": {"name": "test_protocol"},
    }
    payload.update(overrides)
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


@pytest.fixture
def procedural_config(tmp_path):
    return _write_config(tmp_path, "test_procedural")


@pytest.fixture
def ring_cycle_config(tmp_path):
    return _write_config(
        tmp_path, "test_ring_k3", world_type="ring_cycle", cycle_length=3
    )


@pytest.fixture
def money_config(tmp_path):
    return _write_config(tmp_path, "test_with_money", with_money=True)


def _offline(config_path, tmp_path, run_id, **kwargs):
    return runner.run_v1(
        config_path,
        mode="offline",
        out_root=tmp_path / "runs",
        run_id=run_id,
        quiet=True,
        **kwargs,
    )


# ---------------------------------------------------------------
# Run-directory completeness + provenance
# ---------------------------------------------------------------


def test_offline_run_dir_is_complete(procedural_config, tmp_path):
    outcome = _offline(procedural_config, tmp_path, "r1")
    d = outcome.run_dir
    for artifact in ("run_meta.json", "config_snapshot.json", "trace.jsonl", "summary.json"):
        assert (d / artifact).is_file(), f"missing {artifact}"

    meta = json.loads((d / "run_meta.json").read_text())
    assert meta["schema_version"] == runner.RUN_SCHEMA_VERSION
    assert meta["status"] == "complete"
    assert meta["mode"] == "offline"
    assert meta["seed"] == 3
    assert meta["models"] is None
    assert len(meta["config"]["file_sha256"]) == 64
    assert meta["git"]["commit"], "git commit must be recorded"
    assert meta["usage"]["calls"] == 0

    snapshot = json.loads((d / "config_snapshot.json").read_text())
    assert snapshot["name"] == "test_procedural"
    assert snapshot["seed"] == 3

    summary = json.loads((d / "summary.json").read_text())
    assert summary["mode"] == "offline"
    assert summary["rounds"] == 2
    assert summary["cost_line"].startswith("llm calls: 0")

    rows = [json.loads(line) for line in (d / "trace.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    expected_keys = {
        "round_index", "controller_id", "communication_texts", "proposal_text",
        "response_texts", "final_text", "compiled_mechanism",
        "verified_before_private_acceptance", "verified_mechanism", "event",
    }
    assert expected_keys.issubset(rows[0].keys())


def test_offline_requires_no_api_key(procedural_config, tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    outcome = _offline(procedural_config, tmp_path, "r_nokey")
    assert outcome.summary["usage"]["calls"] == 0


def test_seed_override_lands_in_meta_and_snapshot(procedural_config, tmp_path):
    outcome = _offline(procedural_config, tmp_path, "r_seed", seed=77)
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    snapshot = json.loads((outcome.run_dir / "config_snapshot.json").read_text())
    assert meta["seed"] == 77
    assert meta["overrides"]["seed"] == 77
    assert snapshot["seed"] == 77


def test_existing_run_dir_is_refused(procedural_config, tmp_path):
    _offline(procedural_config, tmp_path, "dup")
    with pytest.raises(runner.RunnerError, match="already exists"):
        _offline(procedural_config, tmp_path, "dup")


# ---------------------------------------------------------------
# Determinism (the reproducibility contract)
# ---------------------------------------------------------------


def test_same_config_seed_gives_byte_identical_trace(procedural_config, tmp_path):
    a = _offline(procedural_config, tmp_path, "det_a")
    b = _offline(procedural_config, tmp_path, "det_b")
    assert (a.run_dir / "trace.jsonl").read_bytes() == (b.run_dir / "trace.jsonl").read_bytes()


def test_different_seed_changes_trace(procedural_config, tmp_path):
    a = _offline(procedural_config, tmp_path, "seed_a", seed=1)
    b = _offline(procedural_config, tmp_path, "seed_b", seed=2)
    assert (a.run_dir / "trace.jsonl").read_bytes() != (b.run_dir / "trace.jsonl").read_bytes()


# ---------------------------------------------------------------
# Offline policy across the three world types
# ---------------------------------------------------------------


def test_procedural_world_applies_ir_swaps(procedural_config, tmp_path):
    outcome = _offline(procedural_config, tmp_path, "proc")
    assert outcome.result.applied_mechanisms > 0
    assert outcome.result.final_welfare > outcome.result.initial_welfare
    assert outcome.result.ir_violations == 0
    for event in outcome.result.history:
        if event.applied:
            assert event.individually_rational is True


def test_ring_cycle_k3_offline_noops_cleanly(ring_cycle_config, tmp_path):
    """k>=3 ring worlds have NO mutually-IR bilateral swap; the scripted policy
    must produce explicit no-ops, never a crash or a welfare change."""
    outcome = _offline(ring_cycle_config, tmp_path, "ring")
    assert outcome.result.applied_mechanisms == 0
    assert outcome.result.final_welfare == pytest.approx(outcome.result.initial_welfare)
    rows = [json.loads(l) for l in (outcome.run_dir / "trace.jsonl").read_text().splitlines()]
    for row in rows:
        assert row["compiled_mechanism"]["mechanism_label"] == "scripted_noop"
        assert row["compiled_mechanism"]["transfers"] == []


def test_with_money_world_runs(money_config, tmp_path):
    outcome = _offline(money_config, tmp_path, "money")
    # with_money appends one numeraire good to the resource set
    assert outcome.summary["resources"] == 4
    assert outcome.result.final_welfare >= outcome.result.initial_welfare


# ---------------------------------------------------------------
# Scripted policy unit checks
# ---------------------------------------------------------------


def test_found_swap_is_feasible_and_strictly_ir_for_both():
    world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=3)
    policy = runner.ScriptedBilateralIRPolicy()
    mechanism = policy._find_bilateral_ir_swap(world, 1)
    assert mechanism is not None
    assert ex.compiled_mechanism_feasible(world, mechanism)
    participants = {t.from_agent for t in mechanism.transfers} | {
        t.to_agent for t in mechanism.transfers
    }
    assert len(participants) == 2
    for agent_id in participants:
        assert ex.utility_delta_for_mechanism(world, mechanism, agent_id) > 0
    assert sorted(mechanism.consenting_agents) == sorted(participants)


def test_search_is_deterministic():
    policy = runner.ScriptedBilateralIRPolicy()
    world_a = ex.make_exchange_world(num_agents=3, num_resources=3, seed=3)
    world_b = ex.make_exchange_world(num_agents=3, num_resources=3, seed=3)
    m_a = policy._find_bilateral_ir_swap(world_a, 1)
    m_b = policy._find_bilateral_ir_swap(world_b, 1)
    assert dataclasses.asdict(m_a) == dataclasses.asdict(m_b)


def test_ring_k3_search_returns_none():
    world = ex.make_ring_cycle_world(num_agents=3, cycle_length=3)
    policy = runner.ScriptedBilateralIRPolicy()
    assert policy._find_bilateral_ir_swap(world, 1) is None


# ---------------------------------------------------------------
# Realized-draw full-information panels (max_joint / max_own) — a rational
# counterparty that reads the true world state and, over the SAME mutually-IR
# candidate set as first_ir, selects the surplus-maximizing swap instead of the
# first one. Benevolent (max_joint -> W*) and self-interested (max_own -> the
# panel's own captured surplus) variants of the D9 scripted panel.
# ---------------------------------------------------------------


def _participants(mechanism):
    return {t.from_agent for t in mechanism.transfers} | {t.to_agent for t in mechanism.transfers}


def _joint_gain(world, mechanism):
    return sum(ex.utility_delta_for_mechanism(world, mechanism, a) for a in _participants(mechanism))


def test_max_joint_never_worse_than_first_ir_and_strictly_better_somewhere():
    first = runner.ScriptedBilateralIRPolicy()
    opt = runner.ScriptedBilateralIRPolicy(selection="max_joint")
    strict_improvements = 0
    for seed in range(24):
        world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=seed)
        m_first = first._find_bilateral_ir_swap(world, 1)
        m_opt = opt._find_bilateral_ir_swap(world, 1)
        if m_first is None:
            assert m_opt is None  # same candidate set -> empty for both
            continue
        assert ex.compiled_mechanism_feasible(world, m_opt)
        # still a rational panel: both sides strictly IR
        for a in _participants(m_opt):
            assert ex.utility_delta_for_mechanism(world, m_opt, a) > 0
        j_first, j_opt = _joint_gain(world, m_first), _joint_gain(world, m_opt)
        assert j_opt >= j_first - 1e-9
        if j_opt > j_first + 1e-9:
            strict_improvements += 1
    assert strict_improvements > 0  # proves the selection actually optimizes, not relabels


def test_max_own_maximizes_the_panel_seat_own_surplus():
    first = runner.ScriptedBilateralIRPolicy()
    extract = runner.ScriptedBilateralIRPolicy(selection="max_own")
    strict_improvements = 0
    for seed in range(24):
        world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=seed)
        m_first = first._find_bilateral_ir_swap(world, 1)
        m_ex = extract._find_bilateral_ir_swap(world, 1)
        if m_first is None:
            assert m_ex is None
            continue
        # partner must still accept (strictly IR); the panel maximizes its OWN gain
        for a in _participants(m_ex):
            assert ex.utility_delta_for_mechanism(world, m_ex, a) > 0
        own_first = ex.utility_delta_for_mechanism(world, m_first, 1)
        own_ex = ex.utility_delta_for_mechanism(world, m_ex, 1)
        assert own_ex >= own_first - 1e-9
        if own_ex > own_first + 1e-9:
            strict_improvements += 1
    assert strict_improvements > 0


def test_optimal_selection_is_deterministic():
    for selection in ("max_joint", "max_own"):
        p = runner.ScriptedBilateralIRPolicy(selection=selection)
        wa = ex.make_exchange_world(num_agents=3, num_resources=3, seed=5)
        wb = ex.make_exchange_world(num_agents=3, num_resources=3, seed=5)
        assert dataclasses.asdict(p._find_bilateral_ir_swap(wa, 1)) == dataclasses.asdict(
            p._find_bilateral_ir_swap(wb, 1)
        )


def test_first_ir_default_is_unchanged_by_the_refactor():
    # the refactor must preserve the exact scan-order-first behavior (regression guard)
    default = runner.ScriptedBilateralIRPolicy()
    explicit = runner.ScriptedBilateralIRPolicy(selection="first_ir")
    for seed in range(8):
        world = ex.make_exchange_world(num_agents=3, num_resources=3, seed=seed)
        md, me = default._find_bilateral_ir_swap(world, 1), explicit._find_bilateral_ir_swap(world, 1)
        if md is None:
            assert me is None
            continue
        assert dataclasses.asdict(md) == dataclasses.asdict(me)


def test_unknown_selection_is_rejected():
    with pytest.raises(ValueError):
        runner.ScriptedBilateralIRPolicy(selection="not_a_mode")


# ---------------------------------------------------------------
# Downstream compatibility (C's subgame extraction reads the trace as-is)
# ---------------------------------------------------------------


def test_subgame_extraction_reads_emitted_trace(procedural_config, tmp_path):
    outcome = _offline(procedural_config, tmp_path, "subgame")
    rows = [json.loads(l) for l in (outcome.run_dir / "trace.jsonl").read_text().splitlines()]
    episodes = sg.extract_subgame_episodes(rows, trace_id="test_run")
    assert episodes, "applied bilateral trades must yield subgame episodes"
    for episode in episodes:
        assert episode.to_dict()["trace_id"] == "test_run"


# ---------------------------------------------------------------
# live_frozen + replay against a fake provider (no network, no key)
# ---------------------------------------------------------------
#
# The fake replaces the OpenAI SDK client INSIDE llm_agent, so everything
# downstream of the funnel — response parsing, disk cache, observer, manifest
# recording, replay snapshots — is the real production code path.

_CANNED_RESPONSE = {
    # tolerated by every role: agents read it as text; parse_compiled_mechanism
    # and the verifier parser both .get() their keys and ignore the rest.
    "mechanism_label": "fake_noop",
    "summary": "no trade this round",
    "transfers": [],
    "consenting_agents": [],
    "confidence": 1.0,
    "verifier_ok": True,
    "reason": "ok",
}


class _FakeRawResponse:
    def __init__(self, body: dict):
        self.text = json.dumps(body)


class _FakeCompletions:
    class with_raw_response:  # noqa: N801 — mirrors the SDK attribute
        @staticmethod
        def create(**kwargs):
            user = kwargs["messages"][1]["content"]
            content = dict(_CANNED_RESPONSE)
            # prompt-dependent marker => distinct responses => replay must map
            # each prompt to ITS recorded response, not just any response.
            content["summary"] = f"no trade this round [{runner._sha256_bytes(user.encode())[:8]}]"
            return _FakeRawResponse(
                {
                    # providers echo the RESOLVED model version here, not the
                    # request string — that is what resolved_model must capture
                    "model": FAKE_RESOLVED_MODEL,
                    "choices": [{"message": {"content": json.dumps(content)}}],
                    "usage": {
                        "prompt_tokens": len(user) // 4,
                        "completion_tokens": 25,
                        "total_tokens": len(user) // 4 + 25,
                    },
                }
            )


class _FakeClient:
    class chat:  # noqa: N801
        completions = _FakeCompletions


@pytest.fixture
def fake_provider(monkeypatch, tmp_path):
    """Route llm_agent's OpenRouter path to a deterministic in-process fake."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-or-test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_VERTEX", raising=False)
    monkeypatch.setattr(llm_agent, "_get_client", lambda: _FakeClient())
    cache_dir = tmp_path / "fake_llm_disk_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(llm_agent, "_cache_path", lambda _dir, key: cache_dir / f"{key}.json")
    return cache_dir


def _live(config_path, tmp_path, run_id):
    return runner.run_v1(
        config_path,
        mode="live_frozen",
        out_root=tmp_path / "runs",
        run_id=run_id,
        options=runner.InferenceOptions(model=FAKE_MODEL),
        quiet=True,
    )


def test_live_frozen_manifest_is_complete(procedural_config, tmp_path, fake_provider):
    outcome = _live(procedural_config, tmp_path, "live1")
    d = outcome.run_dir
    manifest_rows = [
        json.loads(line) for line in (d / "inference_manifest.jsonl").read_text().splitlines()
    ]
    assert manifest_rows, "live run must record LLM calls"

    required = {
        "call_id", "round_index", "role", "agent_id", "model", "batched", "cached",
        "params", "system", "prompt", "response", "prompt_sha256", "response_sha256",
        "replay_key", "usage", "estimated_cost_usd", "cost_note",
    }
    for row in manifest_rows:
        assert required.issubset(row.keys())
        assert row["model"] == FAKE_MODEL
        assert row["resolved_model"] == FAKE_RESOLVED_MODEL
        assert len(row["prompt_sha256"]) == 64
        assert row["usage"]["output_tokens"] == 25

    # every phase role reaches the manifest (agents + compiler + verifier)
    roles = {row["role"] for row in manifest_rows}
    assert {"communication", "proposal", "response", "finalization", "compiler", "verifier"} <= roles

    # natural join key: EVERY manifest row (incl. compiler/verifier, whose call
    # sites don't thread round_index) points at a real trace round
    assert all(row["round_index"] is not None for row in manifest_rows)
    trace_rounds = {
        json.loads(line)["round_index"] for line in (d / "trace.jsonl").read_text().splitlines()
    }
    assert {row["round_index"] for row in manifest_rows} <= trace_rounds

    # funnel check: observer == policy records == manifest rows
    meta = json.loads((d / "run_meta.json").read_text())
    assert meta["funnel_check"]["ok"] is True
    assert meta["funnel_check"]["manifest_rows"] == len(manifest_rows)

    # replay snapshots exist for every distinct replay key
    snapshot_keys = {p.stem for p in (d / "llm_cache").glob("*.json")}
    assert {row["replay_key"] for row in manifest_rows} == snapshot_keys


def test_batch_fallback_records_each_call_exactly_once(
    procedural_config, tmp_path, fake_provider
):
    """batch=True on a non-gemini model takes call_llm_batch's sequential tail;
    the mixin's rows_before heuristic must record each call once (as batched)."""
    outcome = runner.run_v1(
        procedural_config,
        mode="live_frozen",
        out_root=tmp_path / "runs",
        run_id="live_batch",
        options=runner.InferenceOptions(model=FAKE_MODEL, batch=True),
        quiet=True,
    )
    rows = [
        json.loads(line)
        for line in (outcome.run_dir / "inference_manifest.jsonl").read_text().splitlines()
    ]
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    assert meta["funnel_check"]["ok"] is True, meta["funnel_check"]
    call_ids = [row["call_id"] for row in rows]
    assert len(call_ids) == len(set(call_ids)), "a call was recorded twice"
    # multi-agent phases really went through the batch path
    assert any(row["batched"] for row in rows)


def test_adversarial_policy_composes_with_manifest(tmp_path, fake_provider):
    config = _write_config(
        tmp_path,
        "test_adversarial",
        protocol={"name": "test_protocol", "defection_rate": 0.5, "defection_seed": 1},
    )
    from aeread import exchange_economy_adversarial as adv

    outcome = runner.run_v1(
        config,
        mode="live_frozen",
        out_root=tmp_path / "runs",
        run_id="live_adv",
        options=runner.InferenceOptions(model=FAKE_MODEL),
        quiet=True,
    )
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    assert meta["funnel_check"]["ok"] is True
    assert (outcome.run_dir / "inference_manifest.jsonl").is_file()
    # the factory really produced the adversarial base under the manifest mixin
    policy = runner.build_policy(
        "live_frozen",
        runner.resolve_config(config),
        runner.InferenceOptions(model=FAKE_MODEL),
    )
    assert isinstance(policy, adv.AdversarialCounterpartyPolicy)


def test_replay_reproduces_live_trace_with_zero_provider_calls(
    procedural_config, tmp_path, fake_provider, monkeypatch
):
    live = _live(procedural_config, tmp_path, "live_rt")

    def _refuse():
        raise AssertionError("provider client touched during replay")

    monkeypatch.setattr(llm_agent, "_get_client", _refuse)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # empty the disk cache too: the replay leg must be served by the run's
    # llm_cache snapshots alone, not by leftover live-cache files
    empty_cache = tmp_path / "empty_disk_cache"
    empty_cache.mkdir()
    monkeypatch.setattr(llm_agent, "_cache_path", lambda _dir, key: empty_cache / f"{key}.json")

    replay = runner.run_v1(
        mode="replay",
        replay_from=live.run_dir,
        out_root=tmp_path / "runs",
        run_id="replay_rt",
        quiet=True,
    )
    assert (replay.run_dir / "trace.jsonl").read_bytes() == (
        live.run_dir / "trace.jsonl"
    ).read_bytes()

    rows = [
        json.loads(line)
        for line in (replay.run_dir / "inference_manifest.jsonl").read_text().splitlines()
    ]
    assert rows and all(row["cached"] for row in rows)
    # resolved model version survives the snapshot round-trip into the replay manifest
    assert all(row["resolved_model"] == FAKE_RESOLVED_MODEL for row in rows)
    meta = json.loads((replay.run_dir / "run_meta.json").read_text())
    assert meta["funnel_check"]["ok"] is True
    assert meta["mode"] == "replay"
    assert meta["replay_from"] == str(live.run_dir)


def test_replay_hard_fails_on_missing_snapshot(
    procedural_config, tmp_path, fake_provider, monkeypatch
):
    live = _live(procedural_config, tmp_path, "live_miss")
    victim = sorted((live.run_dir / "llm_cache").glob("*.json"))[0]
    victim.unlink()
    monkeypatch.setattr(llm_agent, "_get_client", lambda: pytest.fail("provider touched"))
    with pytest.raises(llm_agent.ReplayCacheMiss, match="replay miss"):
        runner.run_v1(
            mode="replay",
            replay_from=live.run_dir,
            out_root=tmp_path / "runs",
            run_id="replay_miss",
            quiet=True,
        )
    # the failed run dir must say so (harness failure, not an economic result)
    meta = json.loads((tmp_path / "runs" / "replay_miss" / "run_meta.json").read_text())
    assert meta["status"] == "failed"
    assert "ReplayCacheMiss" in meta["error"]


def test_replay_requires_source_dir(tmp_path):
    with pytest.raises(runner.RunnerError, match="replay_from"):
        runner.run_v1(mode="replay", out_root=tmp_path, quiet=True)
    with pytest.raises(runner.RunnerError, match="run_meta"):
        runner.run_v1(mode="replay", replay_from=tmp_path, out_root=tmp_path / "r", quiet=True)


def test_snapshot_content_matches_live_cache_shape(tmp_path):
    response = llm_agent.LLMResponse(
        model=FAKE_MODEL,
        text="hello",
        cached=False,
        usage={"input_tokens": 5, "cached_input_tokens": 0, "output_tokens": 2,
               "total_tokens": 7, "reasoning_tokens": 0},
        estimated_cost_usd=0.001,
        cost_note="test",
    )
    path = llm_agent.write_response_snapshot(tmp_path / "snap", "abc123", response)
    payload = json.loads(path.read_text())
    # exact same content keys the live on-disk cache writes in call_llm
    assert set(payload.keys()) == {
        "model", "text", "usage", "estimated_cost_usd", "cost_note", "resolved_model",
    }
    assert payload["text"] == "hello"


# ---------------------------------------------------------------
# strict mode: a funnel mismatch must fail loudly, not just warn
# ---------------------------------------------------------------


@pytest.fixture
def leaky_recorder(monkeypatch):
    """Simulate a call bypassing the manifest: drop the first recorded row."""
    original = runner.ManifestRecorder.record
    dropped = {"done": False}

    def record_with_leak(self, **kwargs):
        if not dropped["done"]:
            dropped["done"] = True
            return None  # this call reaches the model but never lands in the manifest
        return original(self, **kwargs)

    monkeypatch.setattr(runner.ManifestRecorder, "record", record_with_leak)


def test_strict_mode_raises_on_funnel_mismatch(
    procedural_config, tmp_path, fake_provider, leaky_recorder
):
    with pytest.raises(runner.RunnerError, match="funnel check failed"):
        runner.run_v1(
            procedural_config,
            mode="live_frozen",
            out_root=tmp_path / "runs",
            run_id="strict_leak",
            options=runner.InferenceOptions(model=FAKE_MODEL),
            quiet=True,
            strict=True,
        )
    # artifacts still on disk, honestly labeled — strict raises AFTER writing
    meta = json.loads((tmp_path / "runs" / "strict_leak" / "run_meta.json").read_text())
    assert meta["status"] == "manifest_incomplete"
    assert meta["funnel_check"]["ok"] is False


def test_non_strict_mode_completes_with_incomplete_status(
    procedural_config, tmp_path, fake_provider, leaky_recorder
):
    outcome = runner.run_v1(
        procedural_config,
        mode="live_frozen",
        out_root=tmp_path / "runs",
        run_id="soft_leak",
        options=runner.InferenceOptions(model=FAKE_MODEL),
        quiet=True,
        strict=False,
    )
    meta = json.loads((outcome.run_dir / "run_meta.json").read_text())
    assert meta["status"] == "manifest_incomplete"
    assert meta["funnel_check"]["ok"] is False


# --- health circuit breaker (2026-08-01 mute audit) -------------------------

class _Resp:
    """Minimal llm_agent.LLMResponse stand-in for recorder tests."""

    def __init__(self, text: str):
        self.text = text
        self.model = "m"
        self.resolved_model = "m"
        self.cached = False
        self.usage = None
        self.estimated_cost_usd = 0.0
        self.cost_note = ""


_REC_SEQ = itertools.count()


def _rec_call(recorder, text: str, origin: str = "llm") -> None:
    # distinct prompt per call: identical prompts with differing responses trip
    # the (pre-existing, correct) replay-key collision guard first
    recorder.record(
        role="proposal", agent_id=1, round_index=0, system="s",
        prompt=f"p{next(_REC_SEQ)}",
        response=_Resp(text), model="m",
        params={"max_tokens": 100, "temperature": 0.0, "sample": 0},
        batched=False, seat="under_test", origin=origin,
    )


def test_mute_circuit_breaker_trips_on_chunk_boundary(tmp_path):
    import pytest
    rec = runner.ManifestRecorder(
        tmp_path, health_min_calls=4, health_chunk=2, health_max_empty_rate=0.5)
    for _ in range(3):
        _rec_call(rec, "")           # below min_calls (4): no check yet
    assert rec.empty_rows == 3       # counted, not yet judged
    # the 4th call reaches the chunk boundary: 3/4 = 75% empty > 50% -> trips
    with pytest.raises(runner.RunHealthError, match="EMPTY"):
        _rec_call(rec, "spoken")


def test_mute_circuit_breaker_quiet_when_healthy(tmp_path):
    rec = runner.ManifestRecorder(
        tmp_path, health_min_calls=2, health_chunk=1, health_max_empty_rate=0.5)
    for _ in range(10):
        _rec_call(rec, "real content")
    assert rec.empty_rows == 0
    assert rec.totals()["empty_rows"] == 0


def test_mute_circuit_breaker_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AEREAD_HEALTH_OFF", "1")
    rec = runner.ManifestRecorder(tmp_path, health_min_calls=1, health_chunk=1)
    for _ in range(6):
        _rec_call(rec, "")           # 100% empty, breaker disabled
    assert rec.empty_rows == 6
    assert rec.empty_llm_rows == 6


def test_sweep_circuit_breaker_consecutive_and_rate():
    import pytest
    cb = runner.SweepCircuitBreaker(max_consecutive=3, max_failure_rate=0.5,
                                    min_jobs=4)
    cb.record(True)
    cb.record(False)
    cb.record(False)
    with pytest.raises(runner.SweepAbort, match="consecutive"):
        cb.record(False)

    cb2 = runner.SweepCircuitBreaker(max_consecutive=99, max_failure_rate=0.5,
                                     min_jobs=4)
    for ok in (True, False, True, False):
        last = ok
    cb2.record(True); cb2.record(False); cb2.record(False)
    with pytest.raises(runner.SweepAbort, match="failure rate"):
        cb2.record(False)          # 3/4 = 75% > 50% at min_jobs


def test_submitted_agent_silence_never_trips_the_breaker(tmp_path):
    """The no-op baseline is silent BY DESIGN — policy, not provider failure."""
    rec = runner.ManifestRecorder(
        tmp_path, health_min_calls=2, health_chunk=1, health_max_empty_rate=0.1)
    for _ in range(12):
        _rec_call(rec, "", origin="submitted")
    assert rec.empty_rows == 12          # diagnostic still counts it
    assert rec.empty_llm_rows == 0       # breaker basis excludes it
