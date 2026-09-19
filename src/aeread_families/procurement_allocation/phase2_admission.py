"""Reviewable contribution contract; approval is supplied, never synthesized."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from aeread.shared_runner.quality import (
    FamilyContribution,
    HumanQCApproval,
    QCEvidenceRef,
    ResourceLimits,
)
from aeread.shared_runner.registry import family_contribution_sha256
from aeread.shared_runner.run.resolver import canonical_json_bytes
from .phase2_environment import FAMILY_ID, PLUGIN_ID
from .runner import procurement_action_output_schema


def digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def source_pins():
    root = Path(__file__).resolve().parents[3]
    paths = set()
    for directory in (
        "src/aeread/shared_runner",
        "src/aeread_families/procurement_allocation",
        "src/aeread_families/procurement_grounding",
    ):
        paths.update((root / directory).rglob("*.py"))
    paths.update((root / "tests").glob("test_procurement_phase2*.py"))
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(paths)
    }


def action_schema():
    schema = procurement_action_output_schema()
    schema["properties"]["action"]["enum"].remove("check_award")
    return schema


def schema_from_example(value):
    """Infer closed structural schemas from this version's stable public records."""
    if isinstance(value, dict):
        return dict(
            type="object",
            properties={k: schema_from_example(v) for k, v in value.items()},
            required=list(value),
            additionalProperties=False,
        )
    if isinstance(value, list):
        if not value:
            raise ValueError("a schema example must populate each array")
        return dict(type="array", items=schema_from_example(value[0]))
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    raise ValueError("unsupported schema example")


def observation_schema():
    from .phase2_policies import replay_policy
    from .phase2_worlds import build_world

    observation = replay_policy(build_world(0)["payload"])["trace"][-1]["observation"]
    observation["inquiry_results"] = ["serialized nonbinding supplier claims"]
    return schema_from_example(observation)


def evidence_ref(root, path, kind, coverage, ids):
    return dict(
        artifact_type=kind,
        path=path,
        sha256=hashlib.sha256((root / path).read_bytes()).hexdigest(),
        family_id=FAMILY_ID,
        family_version="1.0.0",
        profile_id=FAMILY_ID,
        coverage=[
            dict(coverage_id=coverage, required_ids=list(ids), observed_ids=list(ids))
        ],
    )


def contract(root):
    conformance = json.loads((root / "provider_free_conformance.json").read_text())
    if not conformance["passed"] or conformance["implementation_pins"] != source_pins():
        raise ValueError("provider-free conformance failed or source pins drifted")
    return dict(
        family_id=FAMILY_ID,
        family_version="1.0.0",
        plugin_id=PLUGIN_ID,
        registry_namespace="aeread.procurement_phase2.v1",
        action_schema=action_schema(),
        observation_schema=observation_schema(),
        provider_free_evidence=evidence_ref(
            root,
            "provider_free_conformance.json",
            "provider_free_conformance",
            "provider_free_validation",
            tuple(conformance["checks"]),
        ),
        resource_limits=dict(
            max_wall_seconds=1800.0,
            max_logical_actions=10,
            max_provider_calls=20,
            max_input_tokens=100_000,
            max_output_tokens=24_000,
            max_cost_usd=0.025,
        ),
    )


def load_contribution(root):
    """Load a reviewed contract; missing or stale approval blocks execution."""
    root = Path(root)
    core = json.loads((root / "contribution_contract.json").read_text())
    if core != contract(root):
        raise ValueError("contribution differs from current conformance and schemas")
    approval = json.loads((root / "human_qc_approval.json").read_text())
    if approval["decision"] != "approved" or approval["contribution_sha256"] != digest(
        core
    ):
        raise ValueError("human approval does not bind this exact contribution")
    if not approval.get("source_user_message"):
        raise ValueError("approval must retain the actual human review instruction")
    approval_ref = evidence_ref(
        root,
        "human_qc_approval.json",
        "human_qc_approval",
        "human_qc",
        ("phase2_contract_review",),
    )
    result = FamilyContribution(
        **{
            k: v
            for k, v in core.items()
            if k not in {"provider_free_evidence", "resource_limits"}
        },
        provider_free_evidence=QCEvidenceRef.from_dict(core["provider_free_evidence"]),
        resource_limits=ResourceLimits(**core["resource_limits"]),
        human_qc_approval=HumanQCApproval(
            reviewer_id=approval["reviewer_id"],
            decision="approved",
            contribution_sha256=approval["contribution_sha256"],
            evidence=QCEvidenceRef.from_dict(approval_ref),
        ),
    )
    if family_contribution_sha256(result) != digest(core):
        raise AssertionError("contribution hash mismatch")
    return result
