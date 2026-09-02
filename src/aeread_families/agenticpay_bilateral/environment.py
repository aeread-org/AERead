"""Kernel family plugin for the pinned AgenticPay bilateral negotiation.

The kernel schedules one buyer turn and one seller turn at a time,
alternating (spec section 3's "tau3-style alternation"). Upstream's own
``BaseEnv.step(buyer_action, seller_action)`` takes both parties' actions for
one round together, so only the seller phase's ``step`` actually calls the
bridge into upstream; the buyer phase's ``step`` only buffers the buyer's
message until the seller responds.

Per ``docs/agenticpay_adapter_spec.md`` section 2, ``GlobalScore``/
``BuyerScore``/``SellerScore`` are a labeled compatibility result, never
AERead's primary estimand -- this module carries them forward verbatim
(inside ``terminal``/``outcome``) exactly as upstream computed them, and
never recomputes or approximates them. The two support-normalized surplus-
share leaves and the contract/action legality leaf the spec declares are not
implemented here: ``measurement.py`` (Milestone 2) is where a
``MeasurementLeafSpec``/scorer is declared, per this milestone's scope
("cases + environment"; do not build the scorer yet).
"""
from __future__ import annotations

import copy
import hashlib
import subprocess
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from .agenticpay_bridge import AgenticpayBridge
from .cases import (
    FAMILY_ID,
    FAMILY_VERSION,
    PAYLOAD_FIELDS,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_REPO,
)

PLUGIN_ID = "agenticpay_bilateral_environment"
SCORER_ID = "agenticpay_bilateral_scorer"
BUYER_PHASE = "buyer_turn"
SELLER_PHASE = "seller_turn"

_PUBLIC_CONTRACT_FIELDS = ("continuous_bounds", "discrete_options", "field_descriptions", "contrainfo")


def _set_termination(state: dict[str, Any], reason: str) -> None:
    """Record a termination reason, refusing one this family never declares.

    Mirrors ``tau3_retail.environment._set_termination``'s discipline: the
    case manifest publishes ``TERMINATION_REASONS`` as this family's
    termination vocabulary, and nothing in the kernel cross-checks a
    terminal reason against that declaration at runtime without this.
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


def _role_contract_view(contract_config: Mapping[str, Any] | None, role: str) -> dict[str, Any] | None:
    """Project a role's own visible slice of ``contract_config``.

    Mirrors upstream's own ``_build_public_contract_config`` +
    ``_build_role_contract_config`` field lists exactly (spec's ownership
    boundary: AERead owns visibility projections, never a re-derivation of
    upstream's scoring/legality algorithms). The counterparty's
    ``buyer_preferences``/``seller_preferences`` are never included.
    """
    if not contract_config:
        return None
    view: dict[str, Any] = {
        key: contract_config[key] for key in _PUBLIC_CONTRACT_FIELDS if key in contract_config
    }
    preference_key = f"{role}_preferences"
    if preference_key in contract_config:
        view[preference_key] = contract_config[preference_key]
    return view


def family_manifest() -> FamilyManifest:
    """Return the strict family declaration used by the trusted registry."""
    return FamilyManifest.from_dict(
        {
            "spec_version": FamilyManifest.SPEC_VERSION,
            "family": {"id": FAMILY_ID, "version": FAMILY_VERSION, "plugin_id": PLUGIN_ID},
            "environment": {
                "topology": "bilateral_negotiation",
                "phase_specs": [BUYER_PHASE, SELLER_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "buyer": {"testable": True, "scripted_policies": ["scripted"]},
                "seller": {"testable": True, "scripted_policies": ["scripted"]},
            },
            "measurement": {
                # Placeholder declaration: the concrete MeasurementLeafSpec
                # pair (agenticpay_buyer_surplus_share /
                # agenticpay_seller_surplus_share, spec section 2) lands
                # with measurement.py in Milestone 2. Declared now only so
                # FamilyManifest.from_dict (which requires "measurement")
                # validates; build_scorer below raises until then.
                "primary_estimand": "agenticpay_bilateral_surplus_share",
                "measurement_kind": "optimizable_outcome",
                "direction": "maximize",
                "optimum_lower_bound": "0",
                "optimum_upper_bound": "1",
                "optimum_upper_bound_kind": "known",
                "bound_status": "family_defined",
                "outcome_support": "unit_interval",
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "AgenticpayBilateralPlugin | None" = None,
    upstream_root: Path | str | None = None,
    bridge: AgenticpayBridge | None = None,
) -> "AgenticpayBilateralPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = AgenticpayBilateralPlugin(upstream_root=upstream_root, bridge=bridge)
    registry.register(family_manifest(), plugin)
    return plugin


class AgenticpayBilateralPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``.

    ``family_case`` in every method below is one case's ``payload`` dict
    (mirrors ``Tau3RetailPlugin``'s identical convention), whose fields are
    exactly ``cases.PAYLOAD_FIELDS``.
    """

    def __init__(self, *, upstream_root: Path | str, bridge: AgenticpayBridge | None) -> None:
        self.upstream_root = Path(upstream_root)
        self.bridge = bridge

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != PAYLOAD_FIELDS:
            raise ValueError(f"payload must contain exactly {sorted(PAYLOAD_FIELDS)}")
        if data["kind"] not in ("basic", "realistic"):
            raise ValueError("payload.kind must be 'basic' or 'realistic'")
        if not isinstance(data["env_module"], str) or not data["env_module"]:
            raise ValueError("payload.env_module must be a non-empty string")
        if not isinstance(data["env_class"], str) or not data["env_class"]:
            raise ValueError("payload.env_class must be a non-empty string")
        constructor_kwargs = data["constructor_kwargs"]
        if not isinstance(constructor_kwargs, dict) or not isinstance(
            constructor_kwargs.get("max_rounds"), int
        ):
            raise ValueError("payload.constructor_kwargs.max_rounds must be an int")
        reset_kwargs = data["reset_kwargs"]
        if not isinstance(reset_kwargs, dict):
            raise ValueError("payload.reset_kwargs must be an object")

        pins = data["pins"]
        if pins.get("upstream_repo") != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if pins.get("upstream_commit") != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")

        revision = subprocess.run(
            ["git", "-C", str(self.upstream_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if revision.returncode != 0:
            raise ValueError(f"upstream_root is not a readable git checkout: {revision.stderr.strip()}")
        if revision.stdout.strip() != UPSTREAM_COMMIT:
            raise ValueError(
                f"upstream checkout revision mismatch: expected {UPSTREAM_COMMIT}, got {revision.stdout.strip()}"
            )
        status = subprocess.run(
            ["git", "-C", str(self.upstream_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout:
            raise ValueError("upstream checkout must be clean at the pinned revision")

        for label, info in data["provenance_files"].items():
            path = self.upstream_root / info["path"]
            if not path.is_file():
                raise ValueError(f"pinned source file for {label!r} is missing: {path}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if info["sha256"] != actual:
                raise ValueError(
                    f"payload provenance_files.{label}.sha256 mismatch for {path}: "
                    f"authored {info['sha256']!r}, actual {actual!r}"
                )
        return data

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del cell
        bridge = self._require_bridge()
        result = bridge.reset(
            env_module=family_case["env_module"],
            env_class=family_case["env_class"],
            constructor_kwargs=family_case["constructor_kwargs"],
            reset_kwargs=family_case["reset_kwargs"],
        )
        return {
            "history": [],
            "pending_buyer_message": None,
            "termination": None,
            "last_observation": result["observation"],
            "last_info": result["info"],
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        max_actions = int(family_case["constructor_kwargs"]["max_rounds"])
        return (
            PhaseSpec(
                phase_id=BUYER_PHASE,
                actor_selector="buyer",
                mode="single",
                observation_schema_by_role={"buyer": "agenticpay_bilateral_buyer_observation_v1"},
                action_schema_by_role={"buyer": "agenticpay_bilateral_buyer_message_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(SELLER_PHASE,),
            ),
            PhaseSpec(
                phase_id=SELLER_PHASE,
                actor_selector="seller",
                mode="single",
                observation_schema_by_role={"seller": "agenticpay_bilateral_seller_observation_v1"},
                action_schema_by_role={"seller": "agenticpay_bilateral_seller_message_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(BUYER_PHASE,),
            ),
        )

    def eligible_actors(
        self, family_case: Mapping[str, Any], state: Mapping[str, Any], phase: PhaseSpec
    ) -> tuple[str, ...]:
        del family_case, state
        if phase.phase_id == BUYER_PHASE:
            return ("buyer",)
        if phase.phase_id == SELLER_PHASE:
            return ("seller",)
        raise ValueError(f"unknown phase: {phase.phase_id}")

    def observe(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
    ) -> dict[str, Any]:
        constructor_kwargs = family_case["constructor_kwargs"]
        reset_kwargs = family_case["reset_kwargs"]
        environment_info = constructor_kwargs.get("environment_info") or {}
        contract_config = environment_info.get("contract_config")
        last_observation = state["last_observation"]
        shared = {
            "conversation_history": last_observation["conversation_history"],
            "current_round": last_observation["current_round"],
            "status": last_observation["status"],
            "product_info": reset_kwargs.get("product_info"),
        }
        if phase.phase_id == BUYER_PHASE and seat_id == "buyer":
            return {
                **shared,
                "user_requirement": reset_kwargs.get("user_requirement"),
                "max_price": constructor_kwargs.get("buyer_max_price"),
                "contract_config": _role_contract_view(contract_config, "buyer"),
            }
        if phase.phase_id == SELLER_PHASE and seat_id == "seller":
            return {
                **shared,
                "initial_price": constructor_kwargs.get("initial_seller_price", 100.0),
                "min_price": constructor_kwargs.get("seller_min_price"),
                "contract_config": _role_contract_view(contract_config, "seller"),
            }
        raise ValueError(f"seat {seat_id!r} is not active in phase {phase.phase_id!r}")

    def parse_action(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        response: Any,
    ) -> ParseResult:
        del family_case, state, seat_id, phase
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        content = raw.get("message")
        if not isinstance(content, str) or not content.strip():
            return ParseResult.failure("invalid_negotiation_message")
        return ParseResult.success({"message": content})

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, state, action
        expected = "buyer" if phase.phase_id == BUYER_PHASE else "seller"
        if seat_id != expected:
            return LegalityResult.illegal("seat_phase_mismatch")
        return LegalityResult.legal_action()

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        new_state = _plain(state)
        if phase.phase_id == BUYER_PHASE:
            message = actions["buyer"].action["message"]
            new_state["pending_buyer_message"] = message
            return TransitionResult(
                state=new_state, next_phase_id=SELLER_PHASE, consequences={"rounds": 0}
            )

        if phase.phase_id != SELLER_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")
        buyer_message = new_state["pending_buyer_message"]
        if buyer_message is None:
            raise RuntimeError("seller acted before a buyer message was buffered this round")
        seller_message = actions["seller"].action["message"]

        bridge = self._require_bridge()
        result = bridge.replay_round(
            env_module=family_case["env_module"],
            env_class=family_case["env_class"],
            constructor_kwargs=family_case["constructor_kwargs"],
            reset_kwargs=family_case["reset_kwargs"],
            history=new_state["history"],
            buyer_action=buyer_message,
            seller_action=seller_message,
        )
        new_state["history"] = new_state["history"] + [
            {"buyer_action": buyer_message, "seller_action": seller_message}
        ]
        new_state["pending_buyer_message"] = None
        new_state["last_observation"] = result["observation"]
        new_state["last_info"] = result["info"]
        if result["terminated"]:
            _set_termination(new_state, "agreed")
        elif result["truncated"]:
            _set_termination(new_state, "timeout")

        return TransitionResult(
            state=new_state,
            next_phase_id=(None if new_state["termination"] else BUYER_PHASE),
            consequences={"rounds": 1},
        )

    def terminal(self, family_case: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any] | None:
        del family_case
        reason = state["termination"]
        if reason is None:
            return None
        info = state["last_info"]
        return {
            "reason": reason,
            "rounds": info.get("round"),
            "buyer_price": info.get("buyer_price"),
            "seller_price": info.get("seller_price"),
            "agreed_price": info.get("agreed_price"),
            "buyer_contract": info.get("buyer_contract"),
            "seller_contract": info.get("seller_contract"),
            "agreed_contract": info.get("agreed_contract"),
            "buyer_utility": info.get("buyer_utility"),
            "seller_utility": info.get("seller_utility"),
            "z_max": info.get("z_max"),
            # GlobalScore/BuyerScore/SellerScore: labeled compatibility
            # result only (spec section 2) -- carried forward verbatim,
            # never AERead's primary estimand and never recomputed.
            "global_score": info.get("global_score"),
            "buyer_score": info.get("buyer_score"),
            "seller_score": info.get("seller_score"),
        }

    def outcome(self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]) -> dict[str, Any]:
        del family_case
        return dict(terminal)

    def build_scorer(self, family_case: Mapping[str, Any]) -> Any:
        """Not implemented in Milestone 1 ("cases + environment").

        The two support-normalized surplus-share leaves and the contract/
        action legality leaf (spec section 2) are declared in
        ``measurement.py``, which does not exist yet -- see this package's
        ``__init__.py`` docstring. ``build_scorer`` must still be a callable
        attribute for ``PluginRegistry.register`` to accept this plugin
        (``REQUIRED_FAMILY_PLUGIN_HOOKS``); it must not be called before
        measurement.py lands.
        """
        del family_case
        raise NotImplementedError(
            "agenticpay.bilateral measurement leaves are not implemented yet "
            "(Milestone 2, measurement.py); do not call build_scorer yet"
        )

    def build_reference_providers(self, family_case: Mapping[str, Any]) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None

    def _require_bridge(self) -> AgenticpayBridge:
        if self.bridge is None:
            raise RuntimeError("agenticpay.bilateral execution requires a provisioned AgenticpayBridge")
        return self.bridge


__all__ = [
    "BUYER_PHASE",
    "PLUGIN_ID",
    "SCORER_ID",
    "SELLER_PHASE",
    "AgenticpayBilateralPlugin",
    "family_manifest",
    "register_plugin",
]
