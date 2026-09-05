from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import pytest

from aeread.shared_runner import (
    ContributionAdmissionError,
    FamilyContribution,
    FamilyManifest,
    HumanQCApproval,
    PluginRegistry,
    QCCoverage,
    QCEvidenceRef,
    ResourceLimits,
    family_contribution_sha256,
)
from aeread.shared_runner.registry import DuplicatePluginError


class CompletePlugin:
    def validate_payload(self, payload):
        return payload

    def initial_state(self, case, run):
        return {}

    def phases(self, case):
        return ()

    def eligible_actors(self, case, state, phase):
        return ()

    def observe(self, case, state, seat, phase):
        return {}

    def parse_action(self, case, state, seat, phase, response):
        return response

    def legal(self, case, state, seat, phase, action):
        return True

    def step(self, case, state, phase, actions):
        return state

    def terminal(self, case, state):
        return None

    def outcome(self, case, terminal):
        return terminal

    def build_scorer(self, case):
        return object()

    def build_reference_providers(self, case):
        return ()

    def generator(self):
        return None


def _manifest(
    family_id: str = "contributed_market",
    plugin_id: str = "external.contributed_market",
) -> FamilyManifest:
    return FamilyManifest.from_dict(
        {
            "spec_version": "aeread.family/0.1",
            "family": {
                "id": family_id,
                "version": "1.0.0",
                "plugin_id": plugin_id,
            },
            "environment": {
                "topology": "bilateral",
                "phase_specs": ["act"],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "agent": {
                    "testable": True,
                    "scripted_policies": ["noop"],
                }
            },
            "measurement": {
                "primary_estimand": "utility",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
            },
            "scoring": {"scorer_id": "utility_scorer"},
        }
    )


def _evidence(
    *,
    evidence_root: Path,
    family_id: str,
    artifact_type: str,
    coverage_id: str,
    complete: bool = True,
) -> QCEvidenceRef:
    relative_path = Path("qc") / family_id / f"{artifact_type}.json"
    artifact_path = evidence_root / relative_path
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_bytes = f"{family_id}:{artifact_type}\n".encode()
    artifact_path.write_bytes(artifact_bytes)
    return QCEvidenceRef(
        artifact_type=artifact_type,
        path=str(relative_path),
        sha256=hashlib.sha256(artifact_bytes).hexdigest(),
        family_id=family_id,
        family_version="1.0.0",
        profile_id=family_id,
        coverage=(
            QCCoverage(
                coverage_id=coverage_id,
                required_ids=("conformance_suite",),
                observed_ids=("conformance_suite",) if complete else (),
            ),
        ),
    )


def _closed_schema() -> dict:
    return {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
        "additionalProperties": False,
    }


def _contribution(
    manifest: FamilyManifest,
    evidence_root: Path,
    *,
    namespace: str = "external.contributed_market.v1",
    action_schema: dict | None = None,
    provider_complete: bool = True,
) -> FamilyContribution:
    family_id = manifest.family.id
    provider_evidence = _evidence(
        evidence_root=evidence_root,
        family_id=family_id,
        artifact_type="provider_free_conformance",
        coverage_id="provider_free_validation",
        complete=provider_complete,
    )
    approval_evidence = _evidence(
        evidence_root=evidence_root,
        family_id=family_id,
        artifact_type="human_qc_approval",
        coverage_id="human_qc",
    )
    provisional = FamilyContribution(
        family_id=family_id,
        family_version=manifest.family.version,
        plugin_id=manifest.family.plugin_id,
        registry_namespace=namespace,
        action_schema=action_schema or _closed_schema(),
        observation_schema=_closed_schema(),
        provider_free_evidence=provider_evidence,
        resource_limits=ResourceLimits(
            max_wall_seconds=30.0,
            max_logical_actions=10,
            max_provider_calls=10,
            max_input_tokens=20_000,
            max_output_tokens=5_000,
            max_cost_usd=1.0,
        ),
        human_qc_approval=HumanQCApproval(
            reviewer_id="qc_reviewer",
            decision="approved",
            contribution_sha256="0" * 64,
            evidence=approval_evidence,
        ),
    )
    approval = dataclasses.replace(
        provisional.human_qc_approval,
        contribution_sha256=family_contribution_sha256(provisional),
    )
    return dataclasses.replace(provisional, human_qc_approval=approval)


def test_contributed_family_requires_all_safety_contracts_before_registration(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    contribution = _contribution(manifest, tmp_path)
    registry = PluginRegistry()

    with pytest.raises(ContributionAdmissionError, match="qualified registration"):
        registry.register_trusted(manifest, CompletePlugin())

    registry.register(
        manifest,
        CompletePlugin(),
        contribution=contribution,
        evidence_root=tmp_path,
    )

    registered = registry.registrations()[0]
    assert registered.registry_namespace == contribution.registry_namespace
    assert registered.contribution_sha256 == family_contribution_sha256(
        contribution
    )
    assert registered.resource_limits == contribution.resource_limits
    assert registry.resolve_registration(
        manifest.family.id,
        manifest.family.version,
        manifest.family.plugin_id,
    ) == registered


def test_contribution_rejects_open_schemas_incomplete_conformance_and_bad_approval(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    open_schema = {
        "type": "object",
        "properties": {"decision": {"type": "string"}},
        "required": ["decision"],
    }
    with pytest.raises(ContributionAdmissionError, match="additionalProperties"):
        PluginRegistry().register(
            manifest,
            CompletePlugin(),
            contribution=_contribution(
                manifest, tmp_path, action_schema=open_schema
            ),
            evidence_root=tmp_path,
        )

    with pytest.raises(ContributionAdmissionError, match="coverage is incomplete"):
        PluginRegistry().register(
            manifest,
            CompletePlugin(),
            contribution=_contribution(
                manifest, tmp_path, provider_complete=False
            ),
            evidence_root=tmp_path,
        )

    contribution = _contribution(manifest, tmp_path)
    bad_approval = dataclasses.replace(
        contribution.human_qc_approval,
        contribution_sha256="f" * 64,
    )
    with pytest.raises(ContributionAdmissionError, match="does not bind"):
        PluginRegistry().register(
            manifest,
            CompletePlugin(),
            contribution=dataclasses.replace(
                contribution, human_qc_approval=bad_approval
            ),
            evidence_root=tmp_path,
        )


def test_contribution_namespace_is_isolated_and_resource_limits_are_finite(
    tmp_path: Path,
) -> None:
    first_manifest = _manifest()
    second_manifest = _manifest(
        family_id="other_market",
        plugin_id="external.other_market",
    )
    registry = PluginRegistry()
    registry.register(
        first_manifest,
        CompletePlugin(),
        contribution=_contribution(first_manifest, tmp_path),
        evidence_root=tmp_path,
    )
    with pytest.raises(DuplicatePluginError, match="namespace"):
        registry.register(
            second_manifest,
            CompletePlugin(),
            contribution=_contribution(
                second_manifest,
                tmp_path,
                namespace="external.contributed_market.v1",
            ),
            evidence_root=tmp_path,
        )

    with pytest.raises(ValueError, match="max_wall_seconds"):
        ResourceLimits(
            max_wall_seconds=float("inf"),
            max_logical_actions=10,
            max_provider_calls=10,
            max_input_tokens=10,
            max_output_tokens=10,
            max_cost_usd=1.0,
        )


def test_contribution_rejects_missing_or_tampered_evidence(tmp_path: Path) -> None:
    manifest = _manifest()
    contribution = _contribution(manifest, tmp_path)
    provider_path = tmp_path / contribution.provider_free_evidence.path
    provider_path.unlink()
    with pytest.raises(ContributionAdmissionError, match="does not resolve"):
        PluginRegistry().register(
            manifest,
            CompletePlugin(),
            contribution=contribution,
            evidence_root=tmp_path,
        )

    contribution = _contribution(manifest, tmp_path)
    provider_path = tmp_path / contribution.provider_free_evidence.path
    provider_path.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ContributionAdmissionError, match="digest mismatch"):
        PluginRegistry().register(
            manifest,
            CompletePlugin(),
            contribution=contribution,
            evidence_root=tmp_path,
        )
