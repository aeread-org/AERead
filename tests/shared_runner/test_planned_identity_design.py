from __future__ import annotations

from collections.abc import Callable
import hashlib
import json

import aeread.sdk.v1 as sdk_v1
import pytest
from pydantic import TypeAdapter, ValidationError

from aeread.sdk.v1 import (
    ArtifactRef,
    ClusterDesignSpec,
    ClusterMembershipSpec,
    EpisodeReplicationDesign,
    FixedPanelDesignSpec,
    ImplementationRef,
    PairingSpec,
    PanelDesignSpec,
    PlannedCoordinateField,
    SampledPanelDesignSpec,
    SamplingPopulationSpec,
    SeededEpisodeReplicationDesign,
    UnseededEpisodeReplicationDesign,
    content_sha256,
)


PLANNED_IDENTITY_EXPORTS = {
    "ClusterDesignSpec",
    "ClusterMembershipSpec",
    "EpisodeReplicationDesign",
    "FixedPanelDesignSpec",
    "PairingSpec",
    "PanelDesignSpec",
    "PlannedCoordinateField",
    "SampledPanelDesignSpec",
    "SamplingPopulationSpec",
    "SeededEpisodeReplicationDesign",
    "UnseededEpisodeReplicationDesign",
}


def _artifact(digit: str, *, media_type: str = "application/json") -> ArtifactRef:
    return ArtifactRef(
        sha256=digit * 64,
        media_type=media_type,
        size_bytes=128,
    )


def _population(**overrides: object) -> SamplingPopulationSpec:
    values: dict[str, object] = {
        "population_id": "declared-cases",
        "population_version": "1.0.0",
        "population_kind": "finite_declared_frame",
        "unit_schema_ref": "case-unit/1",
        "unit_ids": ("case-001", "case-002", "case-003"),
        "provenance_refs": (),
        "frame_artifact_ref": _artifact("a"),
    }
    values.update(overrides)
    return SamplingPopulationSpec.model_validate(values)


def _fixed_panel(**overrides: object) -> FixedPanelDesignSpec:
    values: dict[str, object] = {
        "panel_kind": "fixed_panel",
        "panel_design_id": "fixed-cases",
        "panel_design_version": "1.0.0",
        "selected_unit_ids": ("case-001", "case-002"),
        "inference_scope": "conditional_on_selected_panel",
    }
    values.update(overrides)
    return FixedPanelDesignSpec.model_validate(values)


def _sampled_panel(**overrides: object) -> SampledPanelDesignSpec:
    values: dict[str, object] = {
        "panel_kind": "sampled_panel",
        "panel_design_id": "sampled-cases",
        "panel_design_version": "1.0.0",
        "selection_algorithm": ImplementationRef(
            implementation_id="reference-srswor",
            version="1.0.0",
            content_sha256="b" * 64,
        ),
        "sampling_method": "simple_random_without_replacement",
        "selection_protocol_ref": _artifact("c"),
        "selection_seed": 41,
        "sample_size": 2,
        "replacement": "without_replacement",
        "target_inference_scope": (
            "declared_finite_population_under_probability_sampling"
        ),
    }
    values.update(overrides)
    return SampledPanelDesignSpec.model_validate(values)


def _cluster_design(**overrides: object) -> ClusterDesignSpec:
    values: dict[str, object] = {
        "cluster_design_id": "scenario-clusters",
        "cluster_design_version": "1.0.0",
        "cluster_level": "scenario",
        "memberships": (
            ClusterMembershipSpec(
                cluster_id="cluster-a",
                population_unit_ids=("case-001",),
            ),
            ClusterMembershipSpec(
                cluster_id="cluster-b",
                population_unit_ids=("case-002", "case-003", "case-004"),
            ),
            ClusterMembershipSpec(
                cluster_id="cluster-c",
                population_unit_ids=(
                    "case-005",
                    "case-006",
                    "case-007",
                    "case-008",
                    "case-009",
                    "case-010",
                    "case-011",
                ),
            ),
        ),
    }
    values.update(overrides)
    return ClusterDesignSpec.model_validate(values)


def _pairing(**overrides: object) -> PairingSpec:
    values: dict[str, object] = {
        "pairing_id": "candidate-vs-control",
        "pairing_version": "1.0.0",
        "pairing_kind": "paired",
        "subject_block_id": "candidate-block",
        "comparator_block_id": "control-block",
        "pair_key_fields": (
            "case_id",
            "repetition_index",
            "rollout_seed",
            "world_seed",
        ),
    }
    values.update(overrides)
    return PairingSpec.model_validate(values)


def _seeded_replication(**overrides: object) -> SeededEpisodeReplicationDesign:
    values: dict[str, object] = {
        "replication_mode": "seeded",
        "replication_id": "zipped-repetitions",
        "replication_version": "1.0.0",
        "repetition_count": 2,
        "rollout_seeds": (11, 22),
        "replicate_identity": "repetition_index_and_rollout_seed",
        "replay_seed_guarantee": "declared_seed_control",
    }
    values.update(overrides)
    return SeededEpisodeReplicationDesign.model_validate(values)


def _unseeded_replication(**overrides: object) -> UnseededEpisodeReplicationDesign:
    values: dict[str, object] = {
        "replication_mode": "upstream_unseeded",
        "replication_id": "opaque-upstream-repetitions",
        "replication_version": "1.0.0",
        "repetition_count": 5,
        "replicate_identity": "repetition_index",
        "replay_seed_guarantee": "none",
    }
    values.update(overrides)
    return UnseededEpisodeReplicationDesign.model_validate(values)


def test_planned_identity_public_surface_is_exactly_additive() -> None:
    assert PLANNED_IDENTITY_EXPORTS <= set(sdk_v1.__all__)
    assert all(
        value is not None
        for value in (
            ClusterDesignSpec,
            ClusterMembershipSpec,
            EpisodeReplicationDesign,
            FixedPanelDesignSpec,
            PairingSpec,
            PanelDesignSpec,
            PlannedCoordinateField,
            SampledPanelDesignSpec,
            SamplingPopulationSpec,
            SeededEpisodeReplicationDesign,
            UnseededEpisodeReplicationDesign,
        )
    )


def test_planned_identity_schema_hashes_are_frozen_after_green() -> None:
    def digest(model: type[object]) -> str:
        encoded = json.dumps(
            model.model_json_schema(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    assert {
        model.__name__: digest(model)
        for model in (
            SamplingPopulationSpec,
            FixedPanelDesignSpec,
            SampledPanelDesignSpec,
            ClusterMembershipSpec,
            ClusterDesignSpec,
            PairingSpec,
            SeededEpisodeReplicationDesign,
            UnseededEpisodeReplicationDesign,
        )
    } == {
        "SamplingPopulationSpec": "fc723b7b2af8be848f133105f7cd85abf3da8a2e6e81d02f312a5f809b3746d6",
        "FixedPanelDesignSpec": "5fe9b3b526d3d2c127fa24f6a3da513940f147e9f8fd191ccb5d370743530694",
        "SampledPanelDesignSpec": "5ff562e08b9982ff7166450fe4a50204c54d4c9c602f1a1accad8db74c2dba07",
        "ClusterMembershipSpec": "1400bee62c3d54ac304a6ecbc909a0acb36912e5a7c1acc1f64a1e04fa56c816",
        "ClusterDesignSpec": "e6467ab165aa1d758ccbdb49181a53f879d1ef4a53f32f760f78fc6e4940bd77",
        "PairingSpec": "50e51bdc580c30574c92ded4ad7a66ceb4a372d24658fae433f60557eeb2ad48",
        "SeededEpisodeReplicationDesign": "714529c5ace3b8c6039be086842b882e4b0d8e632c68db71b5a912381ccfcd67",
        "UnseededEpisodeReplicationDesign": "1f3a73d11972bf8389a7c2a1a8d5a6a7b833db6936f4035ba3a1cd5183b45a44",
    }


@pytest.mark.parametrize(
    ("factory", "extra_payload"),
    [
        (_population, {"unexpected": True}),
        (_fixed_panel, {"unexpected": True}),
        (_sampled_panel, {"unexpected": True}),
        (
            lambda **overrides: ClusterMembershipSpec.model_validate(
                {
                    "cluster_id": "cluster-a",
                    "population_unit_ids": ("case-001",),
                    **overrides,
                }
            ),
            {"unexpected": True},
        ),
        (_cluster_design, {"unexpected": True}),
        (_pairing, {"unexpected": True}),
        (_seeded_replication, {"unexpected": True}),
        (_unseeded_replication, {"unexpected": True}),
    ],
)
def test_concrete_planned_identity_records_are_strict_frozen_and_hashable(
    factory: Callable[..., object], extra_payload: dict[str, object]
) -> None:
    record = factory()
    assert record.spec_version == "aeread.sdk_record/1"
    assert record.model_json_schema()["additionalProperties"] is False
    assert content_sha256(record) == content_sha256(
        type(record).model_validate(
            dict(reversed(tuple(record.model_dump(mode="python").items())))
        )
    )
    with pytest.raises(ValidationError):
        record.spec_version = "aeread.sdk_record/1"
    with pytest.raises(ValidationError):
        factory(**extra_payload)


@pytest.mark.parametrize(
    ("factory", "identity_field", "version_field"),
    [
        (_population, "population_id", "population_version"),
        (_fixed_panel, "panel_design_id", "panel_design_version"),
        (_sampled_panel, "panel_design_id", "panel_design_version"),
        (_cluster_design, "cluster_design_id", "cluster_design_version"),
        (_pairing, "pairing_id", "pairing_version"),
        (_seeded_replication, "replication_id", "replication_version"),
        (_unseeded_replication, "replication_id", "replication_version"),
    ],
)
def test_planned_identity_rejects_blank_ids_and_non_exact_versions(
    factory: Callable[..., object], identity_field: str, version_field: str
) -> None:
    for bad_id in ("", "   ", True, 1, 1.0):
        with pytest.raises(ValidationError):
            factory(**{identity_field: bad_id})
    for bad_version in ("", "latest", "1", "1.0", True, 1, 1.0):
        with pytest.raises(ValidationError):
            factory(**{version_field: bad_version})


def test_sampling_population_requires_canonical_finite_frame_identity() -> None:
    assert _population(provenance_refs=()).provenance_refs == ()
    missing_frame = _population().model_dump(mode="python")
    missing_frame.pop("frame_artifact_ref")
    with pytest.raises(ValidationError):
        SamplingPopulationSpec.model_validate(missing_frame)
    for unit_ids in (
        (),
        ("case-001", "case-001"),
        ("case-002", "case-001"),
        ("case-001", " "),
    ):
        with pytest.raises(ValidationError):
            _population(unit_ids=unit_ids)

    for provenance_refs in (
        (_artifact("d"), _artifact("d")),
        (_artifact("e"), _artifact("d")),
        (
            {
                "sha256": "d" * 64,
                "media_type": " ",
                "size_bytes": 1,
            },
        ),
    ):
        with pytest.raises(ValidationError):
            _population(provenance_refs=provenance_refs)

    with pytest.raises(ValidationError):
        _population(unit_schema_ref=" ")
    with pytest.raises(ValidationError):
        _population(
            frame_artifact_ref={
                "sha256": "not-a-digest",
                "media_type": " ",
                "size_bytes": 1,
            }
        )


def test_fixed_panel_requires_nonempty_unique_canonical_selected_units() -> None:
    for unit_ids in (
        (),
        ("case-001", "case-001"),
        ("case-002", "case-001"),
        ("case-001", " "),
    ):
        with pytest.raises(ValidationError):
            _fixed_panel(selected_unit_ids=unit_ids)


def test_sampled_panel_pins_only_unrealized_srswor_design() -> None:
    panel = _sampled_panel()
    for later_owned_field in (
        "selected_unit_ids",
        "selection_artifact_ref",
        "selection_provenance",
        "resolved_selection_sha256",
    ):
        assert later_owned_field not in type(panel).model_fields
        assert later_owned_field not in panel.model_dump(mode="json")

    for required_field in ("selection_algorithm", "selection_protocol_ref"):
        missing_pin = panel.model_dump(mode="python")
        missing_pin.pop(required_field)
        with pytest.raises(ValidationError):
            SampledPanelDesignSpec.model_validate(missing_pin)

    for overrides in (
        {
            "selection_algorithm": ImplementationRef(
                implementation_id=" ", version="1.0.0", content_sha256="b" * 64
            )
        },
        {
            "selection_algorithm": ImplementationRef(
                implementation_id="selector", version="latest", content_sha256="b" * 64
            )
        },
        {"sampling_method": "deterministic_hard_case_selector"},
        {"selection_seed": -1},
        {"sample_size": 0},
        {"replacement": True},
        {
            "selection_protocol_ref": {
                "sha256": "bad",
                "media_type": " ",
                "size_bytes": 1,
            }
        },
    ):
        with pytest.raises(ValidationError):
            _sampled_panel(**overrides)

    for scalar in (True, 1.0, "1"):
        with pytest.raises(ValidationError):
            _sampled_panel(selection_seed=scalar)
        with pytest.raises(ValidationError):
            _sampled_panel(sample_size=scalar)


def test_panel_design_union_rejects_missing_unknown_and_mixed_discriminators() -> None:
    adapter = TypeAdapter(PanelDesignSpec)
    fixed = _fixed_panel().model_dump(mode="python")
    sampled = _sampled_panel().model_dump(mode="python")
    assert isinstance(adapter.validate_python(fixed), FixedPanelDesignSpec)
    assert isinstance(adapter.validate_python(sampled), SampledPanelDesignSpec)

    for payload in (
        {key: value for key, value in fixed.items() if key != "panel_kind"},
        {**fixed, "panel_kind": "adaptive_panel"},
        {**fixed, "sample_size": 2},
        {**sampled, "selected_unit_ids": ("case-001",)},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(payload)


def test_cluster_design_accepts_unequal_sizes_and_rejects_invalid_partition_declaration() -> (
    None
):
    cluster = _cluster_design()
    assert tuple(len(item.population_unit_ids) for item in cluster.memberships) == (
        1,
        3,
        7,
    )
    assert "parent_cluster_id" not in ClusterMembershipSpec.model_fields
    assert "parent_field" not in ClusterDesignSpec.model_fields

    with pytest.raises(ValidationError):
        ClusterMembershipSpec(cluster_id="cluster-a", population_unit_ids=())
    with pytest.raises(ValidationError):
        ClusterMembershipSpec(
            cluster_id="cluster-a", population_unit_ids=("case-002", "case-001")
        )
    with pytest.raises(ValidationError):
        ClusterMembershipSpec(
            cluster_id="cluster-a", population_unit_ids=("case-001", "case-001")
        )
    with pytest.raises(ValidationError):
        _cluster_design(memberships=())
    with pytest.raises(ValidationError):
        _cluster_design(memberships=(cluster.memberships[0], cluster.memberships[0]))
    with pytest.raises(ValidationError):
        _cluster_design(memberships=tuple(reversed(cluster.memberships)))
    with pytest.raises(ValidationError):
        _cluster_design(
            memberships=(
                cluster.memberships[0],
                ClusterMembershipSpec(
                    cluster_id="cluster-b", population_unit_ids=("case-001",)
                ),
            )
        )
    with pytest.raises(ValidationError):
        _cluster_design(
            memberships=({"cluster_id": " ", "population_unit_ids": ("case-001",)},)
        )


def test_pairing_enforces_shared_coordinate_keys_and_distinct_block_sides() -> None:
    assert _pairing().pairing_kind == "paired"
    assert _pairing(pairing_kind="unpaired", pair_key_fields=()).pair_key_fields == ()

    for overrides in (
        {"subject_block_id": ""},
        {"comparator_block_id": " "},
        {"subject_block_id": "same", "comparator_block_id": "same"},
        {"pair_key_fields": ()},
        {"pair_key_fields": ("case_id", "case_id")},
        {"pair_key_fields": ("world_seed", "case_id")},
        {"pair_key_fields": ("subject_role",)},
        {"pair_key_fields": ("subject_seat_id",)},
        {"pair_key_fields": ("attempt_id",)},
        {"pair_key_fields": ("rater_id",)},
        {"pair_key_fields": ("outcome",)},
    ):
        with pytest.raises(ValidationError):
            _pairing(**overrides)

    with pytest.raises(ValidationError):
        _pairing(pairing_kind="unpaired", pair_key_fields=("case_id",))
    for later_owned_field in (
        "assignment_kind",
        "assignment_seed",
        "matching_algorithm",
        "exchangeability_provenance",
        "arm_id",
    ):
        with pytest.raises(ValidationError):
            _pairing(**{later_owned_field: "not-owned-here"})


def test_replication_variants_enforce_positional_seed_contract() -> None:
    seeded = _seeded_replication()
    assert seeded.rollout_seeds == (11, 22)
    assert _seeded_replication(rollout_seeds=(11, 11)).rollout_seeds == (11, 11)

    for rollout_seeds in (
        (11,),
        (11, 22, 33),
        (-1, 22),
        (True, 22),
        (1.0, 22),
        ("1", 22),
    ):
        with pytest.raises(ValidationError):
            _seeded_replication(rollout_seeds=rollout_seeds)
    for count in (0, True, 2.0, "2"):
        with pytest.raises(ValidationError):
            _seeded_replication(repetition_count=count)
        with pytest.raises(ValidationError):
            _unseeded_replication(repetition_count=count)

    unseeded = _unseeded_replication()
    assert "rollout_seeds" not in type(unseeded).model_fields
    assert "rollout_seeds" not in unseeded.model_dump(mode="json")
    with pytest.raises(ValidationError):
        _unseeded_replication(rollout_seeds=(0, 0, 0, 0, 0))
    with pytest.raises(ValidationError):
        _unseeded_replication(replay_seed_guarantee="declared_seed_control")


def test_replication_union_rejects_missing_unknown_and_mixed_discriminators() -> None:
    adapter = TypeAdapter(EpisodeReplicationDesign)
    seeded = _seeded_replication().model_dump(mode="python")
    unseeded = _unseeded_replication().model_dump(mode="python")
    assert isinstance(adapter.validate_python(seeded), SeededEpisodeReplicationDesign)
    assert isinstance(
        adapter.validate_python(unseeded), UnseededEpisodeReplicationDesign
    )

    for payload in (
        {key: value for key, value in seeded.items() if key != "replication_mode"},
        {**seeded, "replication_mode": "opaque"},
        {**unseeded, "rollout_seeds": (0, 1, 2, 3, 4)},
        {**seeded, "replicate_identity": "repetition_index"},
    ):
        with pytest.raises(ValidationError):
            adapter.validate_python(payload)
    assert "PlannedEpisodeReplicate" not in sdk_v1.__all__
    assert not hasattr(sdk_v1, "PlannedEpisodeReplicate")


def test_tau3_style_constructor_pressure_fixed_panel_clusters_and_zipped_seeds() -> (
    None
):
    assert _population().population_kind == "finite_declared_frame"
    assert _fixed_panel().inference_scope == "conditional_on_selected_panel"
    assert _cluster_design().cluster_level == "scenario"
    assert _seeded_replication().rollout_seeds == (11, 22)
    assert _pairing(pairing_kind="unpaired", pair_key_fields=()).pairing_kind == (
        "unpaired"
    )
    with pytest.raises(ValidationError):
        _fixed_panel(selected_unit_ids=("case-002", "case-001"))


def test_state_style_constructor_pressure_preserves_upstream_unseeded_repetitions() -> (
    None
):
    design = _unseeded_replication(repetition_count=5)
    assert design.replicate_identity == "repetition_index"
    assert design.replay_seed_guarantee == "none"
    with pytest.raises(ValidationError):
        _unseeded_replication(rollout_seeds=(0, 1, 2, 3, 4))


def test_econ_scheduling_style_constructor_pressure_unrealized_srswor_and_unequal_clusters() -> (
    None
):
    assert _sampled_panel(sample_size=2).sampling_method == (
        "simple_random_without_replacement"
    )
    assert _population().frame_artifact_ref.sha256 == "a" * 64
    assert tuple(
        len(item.population_unit_ids) for item in _cluster_design().memberships
    ) == (
        1,
        3,
        7,
    )
    with pytest.raises(ValidationError):
        _cluster_design(
            memberships=(
                ClusterMembershipSpec(
                    cluster_id="cluster-a", population_unit_ids=("case-001",)
                ),
                ClusterMembershipSpec(
                    cluster_id="cluster-b", population_unit_ids=("case-001",)
                ),
            )
        )


def test_terms_style_constructor_pressure_pairs_only_shared_coordinates() -> None:
    pairing = _pairing(
        pair_key_fields=(
            "case_id",
            "repetition_index",
            "rollout_seed",
            "world_seed",
        )
    )
    assert pairing.subject_block_id != pairing.comparator_block_id
    with pytest.raises(ValidationError):
        _pairing(pair_key_fields=("case_id", "subject_role"))


def test_gdpval_style_constructor_pressure_fixed_tasks_and_case_clusters() -> None:
    panel = _fixed_panel(selected_unit_ids=("case-001", "case-002"))
    clusters = _cluster_design(cluster_level="case")
    repetitions = _seeded_replication(rollout_seeds=(11, 22))
    assert len(panel.selected_unit_ids) == repetitions.repetition_count == 2
    assert clusters.cluster_level == "case"
    with pytest.raises(ValidationError):
        _cluster_design(memberships=tuple(reversed(clusters.memberships)))


def test_housing_style_constructor_pressure_pairs_case_world_and_seed_coordinates() -> (
    None
):
    pairing = _pairing(pair_key_fields=("case_id", "rollout_seed", "world_seed"))
    assert pairing.pair_key_fields == ("case_id", "rollout_seed", "world_seed")
    with pytest.raises(ValidationError):
        _pairing(subject_block_id="housing", comparator_block_id="housing")
