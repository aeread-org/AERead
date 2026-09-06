"""Kernel family plugin for the pinned STEER MCQA pilot corpus.

Mode A (docs/steer_adapter_spec.md): a single agent, one phase, one logical
action. There is no environment to mutate, no tool loop, and no counterpart
seat -- the agent observes one question and every one of its options (full
observability; no hidden information) and submits exactly one ``option_id``.

Scoring (the ``MeasurementLeafSpec``/``canonical_point`` verifier declared in
spec section 2) is built in ``measurement.py``; ``build_scorer`` below wires
this plugin's cached row to it -- see its own docstring.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.task.execution import CanonicalResponse
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .cases import (
    BRANCH_BY_ELEMENT,
    DECLARED_ELEMENTS,
    FAMILY_ID,
    FAMILY_VERSION,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
)
from .measurement import (
    ANSWER_KEY_LEAF_ID,
    ANSWER_KEY_REFERENCE_IMPLEMENTATION_ID,
    SteerScorer,
    build_scorer as build_measurement_scorer,
)

PLUGIN_ID = "steer_environment"
SCORER_ID = "steer_scorer"
PHASE_ID = "answer_question"


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors ``tau3_retail.environment``'s identical discipline: the case
    manifest publishes ``TERMINATION_REASONS`` as this family's termination
    vocabulary, and nothing in the kernel cross-checks a terminal reason
    against that declaration at runtime without this guard.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    state["termination"] = reason


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _recomputed_source_sha256(row: Mapping[str, Any]) -> str:
    """Recompute a cached row's own content digest from its own fields.

    Mirrors ``steer_bridge_driver._op_flatten``'s construction exactly: sha256
    of the canonical JSON ``{question_text, options: [option_text, ...] (in
    option_id order), correct_option_id}``. This is deliberately NOT a
    comparison of ``row["source_sha256"]`` against itself -- that stored
    field is just another value written once by the importer and never
    touched again, so comparing it to the payload's declared value only
    proves the cache and the case agree about what they *think* the digest
    is, never that it matches the content sitting right next to it in the
    same cached row (a critical review finding: a tampered/corrupted cache
    with the ``source_sha256`` field left byte-identical went undetected).
    """
    ordered_options = sorted(row["options"], key=lambda option: option["option_id"])
    payload = {
        "question_text": row["question_text"],
        "options": [option["option_text"] for option in ordered_options],
        "correct_option_id": row["correct_option_id"],
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def family_manifest() -> FamilyManifest:
    """Return the strict family declaration used by the trusted registry."""
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {
                "id": FAMILY_ID,
                "version": FAMILY_VERSION,
                "plugin_id": PLUGIN_ID,
            },
            "environment": {
                "topology": "single_shot_multiple_choice",
                "phase_specs": [PHASE_ID],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {"assistant": {"testable": True, "scripted_policies": ["scripted"]}},
            "measurement": {
                "primary_estimand": "steer_answer_key",
                "measurement_kind": "property_or_answer",
                "direction": "maximize",
                "optimum_lower_bound": "0",
                "optimum_upper_bound": "1",
                "optimum_upper_bound_kind": "known",
                "bound_status": "upstream_defined",
                "outcome_support": "unit_interval",
                # kernel_scoring_contract_spec.md section 3: every leaf this
                # family publishes at finalize time, exactly one primary, and
                # precisely the leaves that gate admission -- declared here,
                # the one source of truth, never inferred from
                # ``build_scorer`` or a test fixture. There is exactly one
                # declared leaf (``steer_answer_key``, ``scope="finalize_time"``:
                # it is a deterministic equality check with no judge/rater
                # dependency, per spec section 4), so it is trivially both
                # primary and the sole admission gate. See
                # docs/steer_adapter_status.md's "Leaf policy" section for
                # why.
                "leaves": [
                    {"leaf_id": ANSWER_KEY_LEAF_ID, "scope": "finalize_time"},
                ],
                "primary_leaf_id": ANSWER_KEY_LEAF_ID,
                "admission_leaf_ids": [ANSWER_KEY_LEAF_ID],
            },
            "scoring": {
                "scorer_id": SCORER_ID,
                "oracle_id": ANSWER_KEY_REFERENCE_IMPLEMENTATION_ID,
            },
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "SteerPlugin | None" = None,
    steer_data_root: Path | str | None = None,
) -> "SteerPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if steer_data_root is None:
            raise ValueError("steer_data_root is required when plugin is not supplied")
        plugin = SteerPlugin(steer_data_root=steer_data_root)
    registry.register_trusted(family_manifest(), plugin)
    return plugin


class SteerPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``.

    Reads the cached, flattened JSON at
    ``steer_data_root/<element>/cases.jsonl`` (never pandas, never the
    bridge subprocess, never the network) to recover the real question text
    and options a case's license-constrained ``payload`` cannot carry, and
    recomputes ``source_sha256`` from the row's own fields to verify it
    against the payload's declared value every time it does (spec section
    1; see :func:`_recomputed_source_sha256`).
    """

    def __init__(self, *, steer_data_root: Path | str) -> None:
        self.steer_data_root = Path(steer_data_root)

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        expected_keys = {"element", "question_id", "options_count", "source_sha256", "pins"}
        if set(data) != expected_keys:
            raise ValueError(
                "payload must contain exactly element, question_id, "
                "options_count, source_sha256, and pins"
            )
        element = data["element"]
        if element not in DECLARED_ELEMENTS:
            raise ValueError(f"payload.element is not one of the declared elements: {element!r}")
        question_id = data["question_id"]
        if not isinstance(question_id, str) or not question_id:
            raise ValueError("payload.question_id must be a non-empty string")
        options_count = data["options_count"]
        if isinstance(options_count, bool) or not isinstance(options_count, int) or options_count < 2:
            raise ValueError("payload.options_count must be an integer >= 2")
        source_sha256 = data["source_sha256"]
        if (
            not isinstance(source_sha256, str)
            or len(source_sha256) != 64
            or any(character not in "0123456789abcdef" for character in source_sha256)
        ):
            raise ValueError("payload.source_sha256 must be 64 lowercase hexadecimal characters")
        pins = data["pins"]
        if not isinstance(pins, dict):
            raise ValueError("payload.pins must be an object")
        if pins.get("upstream_repo") != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if pins.get("upstream_commit") != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")
        if pins.get("branch_by_element", {}).get(element) != BRANCH_BY_ELEMENT[element]:
            raise ValueError("payload.pins.branch_by_element does not match this case's element")
        return data

    def initial_state(self, family_case: Mapping[str, Any], run: Any) -> dict[str, Any]:
        del run
        row = self._load_cached_row(family_case["element"], family_case["question_id"])
        if _recomputed_source_sha256(row) != family_case["source_sha256"]:
            raise ValueError(
                "cached source_sha256 does not match the payload's declared value "
                f"for {family_case['element']}/{family_case['question_id']}"
            )
        if len(row["options"]) != family_case["options_count"]:
            raise ValueError(
                "cached options_count does not match the payload's declared value "
                f"for {family_case['element']}/{family_case['question_id']}"
            )
        return {
            "question_text": row["question_text"],
            "options": row["options"],
            "termination": None,
            "selected_option_id": None,
            "failure_code": None,
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        return (
            PhaseSpec(
                phase_id=PHASE_ID,
                actor_selector="agent_only",
                mode="single",
                # Keyed by ROLE (SeatSpec.role = "assistant"), not by seat id
                # ("agent") -- the scheduler resolves a phase's declared
                # schemas by the seat's role (see `_eligible_actors` in
                # scheduler.py), while `observe`/`parse_action`/`legal`/
                # `step` below are keyed by seat id throughout.
                observation_schema_by_role={"assistant": "steer_question_observation_v1"},
                action_schema_by_role={"assistant": "steer_option_choice_v1"},
                max_logical_actions=1,
                # An illegal or malformed submission must surface as a scored
                # `invalid_measurement`-shaped outcome (spec section 4,
                # goldens 3-4), never abort the run -- so this family, not
                # the scheduler, decides what an invalid action means.
                invalid_action_policy="family_defined",
                next_phases=(),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
    ) -> tuple[str, ...]:
        del family_case, state, phase
        return ("agent",)

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        del phase
        if seat_id != "agent":
            raise ValueError(f"seat {seat_id!r} is not active in this family")
        return {
            "element": family_case["element"],
            "question_text": state["question_text"],
            "options": [dict(option) for option in state["options"]],
        }

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state, phase
        if seat_id != "agent":
            return ParseResult.failure("seat_phase_mismatch")
        if isinstance(response, CanonicalResponse):
            text = response.text
        elif isinstance(response, str):
            text = response
        else:
            return ParseResult.failure("noncanonical_response")
        try:
            value = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            # Golden 4 (malformed-operational): free-text prose instead of a
            # parseable option identifier -- surfaced here, never coerced.
            return ParseResult.failure("malformed_answer_json")
        if not isinstance(value, dict) or set(value) != {"option_id"}:
            return ParseResult.failure("malformed_answer_shape")
        option_id = value["option_id"]
        if isinstance(option_id, bool) or not isinstance(option_id, int):
            return ParseResult.failure("malformed_option_id")
        return ParseResult.success({"option_id": option_id})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del state, phase
        if seat_id != "agent":
            return LegalityResult.illegal("seat_phase_mismatch")
        option_id = action["option_id"]
        # Golden 3 (invalid-unauthorized): an option_id absent from this
        # question's own option set (e.g. an index >= options_count) is
        # rejected here, never coerced to option 0 or recorded as a
        # legitimate wrong answer.
        if option_id < 0 or option_id >= family_case["options_count"]:
            return LegalityResult.illegal("option_id_out_of_range")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del family_case, phase
        envelope = actions["agent"]
        failure_code = None
        if not envelope.valid:
            failure_code = (
                envelope.parse.error_code if not envelope.parse.ok else envelope.legality.reason
            )
        new_state = _plain(state)
        new_state["selected_option_id"] = envelope.action["option_id"] if envelope.valid else None
        new_state["failure_code"] = failure_code
        _set_termination(new_state, "answered" if envelope.valid else "error")
        return TransitionResult(
            state=new_state,
            next_phase_id=None,
            consequences={"submission_valid": envelope.valid, "failure_code": failure_code},
        )

    def terminal(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        return {
            "reason": reason,
            "selected_option_id": state["selected_option_id"],
            "failure_code": state["failure_code"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "selected_option_id": terminal["selected_option_id"],
            "failure_code": terminal["failure_code"],
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> SteerScorer:
        """Build this case's declared verifier leaf and scorer.

        Reads the same cached row ``initial_state`` reads (never pandas,
        never the bridge subprocess, never the network) to recover the gold
        ``correct_option_id`` and the per-question ``source_sha256`` the
        declared reference pins (spec section 2), and recomputes
        ``source_sha256`` from the row's own fields to verify it against the
        payload's declared value exactly the way ``initial_state`` does.
        Mirrors ``tau3_retail.environment.Tau3RetailPlugin.build_scorer``'s
        contract: return the scorer built by ``measurement.py``.
        """
        row = self._load_cached_row(family_case["element"], family_case["question_id"])
        if _recomputed_source_sha256(row) != family_case["source_sha256"]:
            raise ValueError(
                "cached source_sha256 does not match the payload's declared value "
                f"for {family_case['element']}/{family_case['question_id']}"
            )
        return build_measurement_scorer(row)

    def build_reference_providers(
        self, family_case: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any] | None = None) -> None:
        del family_case
        return None

    def _load_cached_row(self, element: str, question_id: str) -> dict[str, Any]:
        path = self.steer_data_root / element / "cases.jsonl"
        if not path.is_file():
            raise FileNotFoundError(
                f"cached flattened corpus missing for element {element!r} at {path}; "
                "run the steer cases importer first (src/aeread_families/steer/cases.py)"
            )
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row["question_id"] == question_id:
                    return row
        raise ValueError(f"question_id {question_id!r} not found in cached {path}")


__all__ = [
    "PHASE_ID",
    "PLUGIN_ID",
    "SCORER_ID",
    "SteerPlugin",
    "family_manifest",
    "register_plugin",
]
