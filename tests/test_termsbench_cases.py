"""Tests for the termsbench generator foundation stage: draws, digests, pilot.

There is no upstream corpus (the paper's own repository link is dead), so
Gate 1 check #1's "source" re-resolution target is our own deterministic
generator: regenerating from the same ``(generator_version, world_seed)``
must be byte-identical. See docs/termsbench_adapter_spec.md section 1.
"""
from __future__ import annotations

import copy

import pytest

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import AuthoringValidationError, CaseManifest, is_exportable_id
from aeread_families.termsbench import cases as tb_cases
from aeread_families.termsbench import kernel as k


# ---------------------------------------------------------------------------
# Generator determinism (Gate 1 check #1).
# ---------------------------------------------------------------------------


def test_generate_payload_is_byte_identical_across_two_calls() -> None:
    first = tb_cases.generate_payload("candid", "overlap", 1000046)
    second = tb_cases.generate_payload("candid", "overlap", 1000046)
    assert first == second


def test_generate_payload_differs_across_seeds() -> None:
    first = tb_cases.generate_payload("candid", "overlap", 1000046)
    second = tb_cases.generate_payload("candid", "overlap", 1000047)
    assert first != second


def test_build_case_is_byte_identical_across_two_calls() -> None:
    first = tb_cases.build_case("expressive", "nodeal", 1210007)
    second = tb_cases.build_case("expressive", "nodeal", 1210007)
    assert first == second


@pytest.mark.parametrize("family", k.FAMILIES)
@pytest.mark.parametrize("regime", tb_cases.REGIMES)
def test_build_case_round_trips_through_the_strict_r1_grammar(family: str, regime: str) -> None:
    case = tb_cases.build_case(family, regime, 1000046)
    manifest = CaseManifest.from_dict(case)
    assert manifest.case_id == case["case_id"]
    assert manifest.family_id == tb_cases.FAMILY_ID
    assert manifest.upstream_task_id is None
    assert manifest.provenance.review_status == "generated"


def test_case_content_sha256_matches_the_kernel_resolver_computation() -> None:
    case = tb_cases.build_case("candid", "overlap", 1000046)
    assert case_content_sha256(case) == case["content_sha256"]

    mutated = copy.deepcopy(case)
    mutated["payload"]["t_b"]["kappa_b"] = 0.999999
    assert case_content_sha256(mutated) != case["content_sha256"]


# ---------------------------------------------------------------------------
# Case identifiers never contain a colon (a colon once collapsed GRPO
# grouping downstream).
# ---------------------------------------------------------------------------


def test_case_id_grammar_forbids_colons() -> None:
    case = tb_cases.build_case("taciturn", "nodeal", 1110003)
    assert ":" not in case["case_id"]
    assert is_exportable_id(case["case_id"])
    assert case["case_id"] == f"termsbench.taciturn.nodeal.1110003"


def test_case_id_grammar_rejects_a_naive_colon_joined_id() -> None:
    with pytest.raises(AuthoringValidationError, match="valid identifier"):
        CaseManifest.from_dict(
            {
                "spec_version": "aeread.case/0.1",
                "case_id": "termsbench:candid:overlap:7",
                "family_id": "termsbench",
                "family_version": "0.1.0",
                "split": "candid",
                "world_seed": 7,
                "seats": [{"id": "agent", "role": "agent"}],
                "episode": {"max_logical_actions": 1, "termination": ["timeout"]},
                "visibility_policy": "x",
                "payload": {},
                "provenance": {
                    "generator_id": "g",
                    "generator_version": "0.1.0",
                    "review_status": "generated",
                },
                "content_sha256": "0" * 64,
            }
        )


# ---------------------------------------------------------------------------
# Gate 1 check #3: difficulty is computed only from pre-interaction
# properties, never from realized play.
# ---------------------------------------------------------------------------


def test_difficulty_score_is_a_pure_function_of_the_generator_draw() -> None:
    payload_a = tb_cases.generate_payload("candid", "overlap", 1000046)
    payload_b = tb_cases.generate_payload("candid", "overlap", 1000046)
    assert payload_a["difficulty_score"] == payload_b["difficulty_score"]
    # generate_payload never touches an episode/trajectory object at all --
    # there is no "realized play" input it could depend on even accidentally.
    import inspect

    source = inspect.getsource(tb_cases.generate_payload)
    assert "state" not in source and "outcome" not in source and "terminal" not in source


def test_difficulty_score_is_unaffected_by_an_actually_completed_production_episode() -> None:
    """Behavioral companion to the substring check above (Codex review
    finding 5): that check only greps ``generate_payload``'s own source text
    for ``state``/``outcome``/``terminal`` -- it would miss impurity hidden
    behind an innocuously-named helper (e.g. one that reads a module-level
    cache a real episode run populated), and would false-fail on an
    unrelated local variable that happens to share one of those names.

    This drives a real ``(state, outcome, terminal)`` triple into existence
    through the actual production scheduler -- ``run_episode`` +
    ``TermsBenchPlugin`` + ``ScriptedTermsBenchHarness``, exactly the path
    every other termsbench test exercises, not a re-derivation of
    ``generate_payload``'s own logic -- and confirms regenerating the same
    ``(family, regime, world_seed)`` payload afterwards is still
    byte-identical to before that episode ever ran. A regression that
    computed ``difficulty_score`` from a post-episode global/cached
    trajectory would change the second value even though generate_payload's
    only formal inputs are unchanged.
    """
    import asyncio
    from types import MappingProxyType

    from aeread.shared_runner.registry import PluginRegistry
    from aeread.shared_runner.run.resolver import PlanCell
    from aeread.shared_runner.task.scheduler import run_episode
    from aeread_families.termsbench.environment import register_plugin
    from aeread_families.termsbench.harness import ScriptedTermsBenchHarness

    family, regime, world_seed = "candid", "overlap", 1000046
    before = tb_cases.generate_payload(family, regime, world_seed)

    case = CaseManifest.from_dict(tb_cases.build_case(family, regime, world_seed))
    assert case.payload["chi"] == "counterpart_opens"  # round 1 is the counterpart's opening offer
    cell = PlanCell(
        spec_version="aeread.run_plan/0.1",
        cell_id="cell_termsbench_cases_purity",
        case_id=case.case_id,
        case_sha256=case.content_sha256,
        family_id=case.family_id,
        family_version=case.family_version,
        suite_id="suite_termsbench_cases_purity",
        suite_version="0.1.0",
        block_id="block_termsbench_cases_purity",
        sampling_plan_id="sampling_termsbench_cases_purity",
        analysis_plan_id="analysis_termsbench_cases_purity",
        world_seed=case.world_seed,
        sampling_seed=case.world_seed,
        block_repetition=0,
        sampling_replicate=0,
        replicate_index=0,
        cluster_id="cluster_termsbench_cases_purity",
        cluster_level="case",
        observations_per_cluster=1,
        pair_id=None,
        paired_fields=MappingProxyType({}),
        panel_mode="independent",
        profile_by_seat=MappingProxyType(
            {"agent": "scripted_agent", "counterpart": "termsbench_counterpart_kernel_v1"}
        ),
        execution_mode="evaluate",
        case_max_logical_actions=case.episode.max_logical_actions,
    )
    registry = PluginRegistry()
    plugin = register_plugin(registry)
    harness = ScriptedTermsBenchHarness(
        world_seed=case.world_seed,
        script=[{"decision": "reject", "price": None, "message": "no deal"}],
    )
    result = asyncio.run(run_episode(cell=cell, case=case, plugin=plugin, response_source=harness))
    # Sanity: a real state/outcome/terminal triple genuinely came into
    # existence for this exact world_seed.
    assert result.terminal["reason"] == "agent_reject"
    assert result.outcome["termination_reason"] == "agent_reject"
    # Round 1 was the counterpart's opening offer (chi=counterpart_opens);
    # the agent's Reject is its round-2 response.
    assert result.final_state["round"] == 2

    after = tb_cases.generate_payload(family, regime, world_seed)
    assert after == before
    assert after["difficulty_score"] == before["difficulty_score"]


def test_overlap_difficulty_increases_as_zopa_narrows() -> None:
    wide = k.overlap_difficulty(delta=100.0, price_range=200.0, kappa_agent=0.5, kappa_counterpart=0.5, eta_b="neutral")
    narrow = k.overlap_difficulty(delta=20.0, price_range=200.0, kappa_agent=0.5, kappa_counterpart=0.5, eta_b="neutral")
    assert narrow > wide


def test_nodeal_difficulty_increases_as_gap_shrinks_toward_zero() -> None:
    near_feasible = k.nodeal_difficulty(delta=-1.0, sigma_scale=200.0, cue_channel="accurate", eta_b="neutral")
    far_infeasible = k.nodeal_difficulty(delta=-100.0, sigma_scale=200.0, cue_channel="accurate", eta_b="neutral")
    assert near_feasible > far_infeasible


# ---------------------------------------------------------------------------
# Pilot manifest (30 = 3 families x 2 regimes x 5 difficulty bins).
# ---------------------------------------------------------------------------


def test_pilot_cells_enumerate_30_unique_stratified_seeds() -> None:
    cells = tb_cases.pilot_cells()
    assert len(cells) == 30
    seeds = [seed for *_rest, seed in cells]
    assert len(set(seeds)) == 30, "Gate 1 check #5: world_seed must be unique per case"

    strata = [(family, regime, difficulty_bin) for family, regime, difficulty_bin, _seed in cells]
    assert len(set(strata)) == 30, "Gate 1 check #5: one case per (family, regime, difficulty_bin) stratum"

    families = {family for family, _r, _b, _s in cells}
    regimes = {regime for _f, regime, _b, _s in cells}
    bins = {difficulty_bin for _f, _r, difficulty_bin, _s in cells}
    assert families == set(k.FAMILIES)
    assert regimes == set(tb_cases.REGIMES)
    assert bins == set(range(5))


def test_pilot_cell_difficulty_bins_are_ascending_in_difficulty_score() -> None:
    for family in k.FAMILIES:
        for regime in tb_cases.REGIMES:
            scores = []
            for difficulty_bin in range(5):
                seed = tb_cases.select_pilot_cell_seed(family, regime, difficulty_bin)
                payload = tb_cases.generate_payload(family, regime, seed)
                scores.append(payload["difficulty_score"])
            assert scores == sorted(scores), f"{family}/{regime} bins are not ascending: {scores}"


def test_select_pilot_cell_seed_picks_first_rank_not_smallest_seed_within_a_bin(monkeypatch) -> None:
    """``select_pilot_cell_seed`` returns the seed at the *first rank*
    (lowest ``difficulty_score``) whose computed bin matches -- not the
    numerically smallest seed among every candidate that lands in that bin.
    Rigged scores make the two readings diverge (offset 1 gets the lower
    score but is the larger seed) so a regression to "smallest seed in the
    bin" would be caught here."""
    family, regime = "candid", "overlap"
    base = tb_cases._candidate_seed_base(family, regime)
    pool_size = 8
    # offsets {0, 1} are the two lowest scores (both bin 0, since
    # rank*5//8 == 0 for rank in {0, 1}), but the lower-scored offset (1) is
    # the larger seed -- the opposite of "smallest seed in the bin".
    scores = {0: 1.0, 1: 0.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0, 6: 6.0, 7: 7.0}

    def fake_score(fam: str, reg: str, world_seed: int) -> float:
        assert (fam, reg) == (family, regime)
        return scores[world_seed - base]

    monkeypatch.setattr(tb_cases, "_difficulty_score_only", fake_score)
    seed = tb_cases.select_pilot_cell_seed(family, regime, difficulty_bin=0, pool_size=pool_size)
    assert seed == base + 1  # first rank (lowest score), not base + 0 (smallest seed in the bin)


def test_build_pilot_manifest_has_30_cases_and_stable_hash() -> None:
    cases = tb_cases.build_pilot_cases()
    assert len(cases) == 30
    manifest = tb_cases.build_pilot_manifest(cases)
    assert manifest["family_id"] == tb_cases.FAMILY_ID
    assert len(manifest["case_ids"]) == 30
    assert len(set(manifest["case_ids"])) == 30
    assert len(manifest["content_sha256"]) == 64
    int(manifest["content_sha256"], 16)

    manifest_again = tb_cases.build_pilot_manifest(cases)
    assert manifest_again == manifest


def test_pilot_manifest_hash_changes_if_the_case_id_list_changes() -> None:
    cases = tb_cases.build_pilot_cases()
    manifest = tb_cases.build_pilot_manifest(cases)
    mutated = dict(manifest)
    mutated["case_ids"] = list(manifest["case_ids"][:-1]) + ["termsbench.candid.overlap.999999999"]
    mutated_digest = tb_cases._pilot_content_sha256(mutated)
    assert mutated_digest != manifest["content_sha256"]


def test_build_pilot_manifest_raises_on_unresolved_pilot_id() -> None:
    with pytest.raises(ValueError, match="not found"):
        tb_cases.build_pilot_manifest({})


# ---------------------------------------------------------------------------
# P1 -- generation determinism: two generator runs must be byte-identical.
# ---------------------------------------------------------------------------


def test_run_generate_is_byte_identical_across_two_runs(tmp_path) -> None:
    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    tb_cases.run_generate(out_a)
    tb_cases.run_generate(out_b)

    files_a = sorted(p.relative_to(out_a) for p in out_a.rglob("*.json"))
    files_b = sorted(p.relative_to(out_b) for p in out_b.rglob("*.json"))
    assert files_a == files_b
    # 30 case files + pilot_manifest.json
    assert len(files_a) == 31

    for rel in files_a:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes(), f"{rel} differs across two runs"


def test_run_generate_writes_the_committed_pilot_corpus(tmp_path) -> None:
    out_dir = tmp_path / "run"
    tb_cases.run_generate(out_dir)
    case_files = sorted(out_dir.glob("termsbench.*.json"))
    assert len(case_files) == 30
    pilot = __import__("json").loads((out_dir / "pilot_manifest.json").read_text(encoding="utf-8"))
    assert len(pilot["case_ids"]) == 30
