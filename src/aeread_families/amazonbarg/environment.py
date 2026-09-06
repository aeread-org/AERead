"""Kernel family plugin for pinned AmazonPriceHistory bilateral bargaining.

The kernel schedules one buyer turn and one seller turn at a time, strictly
alternating, buyer first each round -- mirroring upstream's own
``session.Agent2AgentSession.agents_talk_with_action`` loop exactly (buyer
acts; if its action is ``DEAL``/``QUIT``/unparseable the round -- and the
episode -- ends immediately with only the buyer's record; otherwise the
seller responds and the same check applies to it; otherwise the round
count advances and play continues up to the pinned turn limit). There is
no tool-calling surface in this benchmark at all: every turn is one
free-text reply parsed by upstream's own extraction grammar
(``session.parseReply`` + ``utils.Action.ActionParser``), never
reimplemented here (spec section 3).

Milestone note: milestone 1 built cases + environment only, with
``build_scorer`` deferred (spec section 2's five measurement leaves).
Milestone 2 (this update) wires ``build_scorer`` to
``measurement.build_scorer`` -- see that module for the five leaves
themselves, each delegated to upstream's own ``eval.py:Metrics``.

Separately, kernel_scoring_contract_spec.md migration milestone 2 of 3
(a later change) declares this family's finalize-time leaf policy in
``family_manifest()`` and gives ``measurement.AmazonbargScorer`` a
``__call__`` seam for ``task.evaluation.finalize_family_execution`` -- see
``measurement.py``'s module docstring and
``docs/amazonbarg_adapter_status.md``'s "Leaf policy" section.
"""
from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.schemas import FamilyManifest
from aeread.shared_runner.task.scheduler import (
    LegalityResult,
    ParseResult,
    PhaseSpec,
    TransitionResult,
)

from . import measurement, upstream_shim
from .cases import (
    BUDGET_RATIO,
    FAMILY_ID,
    FAMILY_VERSION,
    MAX_TURNS,
    TERMINATION_REASONS,
    UPSTREAM_COMMIT,
    UPSTREAM_LICENSE,
    UPSTREAM_REPO,
    codename_category,
    load_all_derived_products,
    load_raw_category_records,
)

PLUGIN_ID = "amazonbarg_environment"
SCORER_ID = "amazonbarg_scorer"
BUYER_PHASE = "buyer_turn"
SELLER_PHASE = "seller_turn"


def _set_termination(state: dict[str, Any], reason: str, actor: str | None) -> None:
    """Record a termination reason, refusing one the case never declared.

    Mirrors ``tau3_retail``'s own guard: the case manifest publishes
    ``TERMINATION_REASONS`` as this family's termination vocabulary, and
    nothing in the kernel cross-checks a terminal reason against that
    declaration at runtime without this.
    """
    if reason not in TERMINATION_REASONS:
        raise ValueError(
            f"termination reason {reason!r} is not declared by this family; "
            f"declared reasons are {list(TERMINATION_REASONS)}"
        )
    if actor is not None and actor not in ("buyer", "seller"):
        raise ValueError(f"termination actor must be 'buyer', 'seller', or None, got {actor!r}")
    state["termination"] = reason
    state["termination_actor"] = actor


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
                "topology": "alternating_conversation",
                "phase_specs": [BUYER_PHASE, SELLER_PHASE],
                "needs_tools": False,
                "needs_sandbox": False,
            },
            "roles": {
                "buyer": {"testable": True, "scripted_policies": ["scripted"]},
                "seller": {"testable": True, "scripted_policies": ["scripted"]},
            },
            "measurement": {
                # No composite score is sealed by the kernel (spec section 2:
                # five leaf verifiers, composition_kind="leaf" throughout).
                # This single family-level summary points at the one
                # comparative leaf closest to a headline claim, with an
                # explicit fixed-opponent caveat recorded in that leaf's own
                # `validity_domain` once measurement.py exists -- never an
                # optimality claim (there is no feasible-policy witness or
                # certified upper bound on the unknown optimal bargaining
                # policy here).
                "primary_estimand": "amazonbarg_bargained_ratio",
                "measurement_kind": "comparative_or_human_judged",
                "direction": "maximize",
                "outcome_support": "ratio",
                # kernel_scoring_contract_spec.md section 3: every leaf this
                # family publishes at finalize time, exactly one primary, and
                # precisely the leaves that gate admission -- declared here,
                # the one source of truth, never inferred from
                # `build_scorer` or a test fixture. All five are
                # `scope="finalize_time"`: every leaf in measurement.py is
                # `evaluation_class="deterministic"` with no judge, rater, or
                # other not-yet-existing artifact dependency (spec section
                # 4), so none is `deferred`. See
                # docs/amazonbarg_adapter_status.md's "Leaf policy" section
                # for why `amazonbarg_bargained_ratio` is primary and why it
                # alone gates admission.
                "leaves": [
                    {
                        "leaf_id": measurement.DEAL_AUTHENTICITY_LEAF_ID,
                        "scope": "finalize_time",
                    },
                    {
                        "leaf_id": measurement.ZOPA_MEMBERSHIP_LEAF_ID,
                        "scope": "finalize_time",
                    },
                    {
                        "leaf_id": measurement.DEAL_LOWER_BOUND_LEAF_ID,
                        "scope": "finalize_time",
                    },
                    {
                        "leaf_id": measurement.DEAL_UPPER_BOUND_LEAF_ID,
                        "scope": "finalize_time",
                    },
                    {
                        "leaf_id": measurement.BARGAINED_RATIO_LEAF_ID,
                        "scope": "finalize_time",
                    },
                ],
                "primary_leaf_id": measurement.BARGAINED_RATIO_LEAF_ID,
                "admission_leaf_ids": [measurement.BARGAINED_RATIO_LEAF_ID],
            },
            "scoring": {"scorer_id": SCORER_ID},
        }
    )


def register_plugin(
    registry: PluginRegistry,
    *,
    plugin: "AmazonbargPlugin | None" = None,
    upstream_root: Path | str | None = None,
) -> "AmazonbargPlugin":
    """Register one exact family/version binding in the kernel registry."""
    if plugin is None:
        if upstream_root is None:
            raise ValueError("upstream_root is required when plugin is not supplied")
        plugin = AmazonbargPlugin(upstream_root=upstream_root)
    registry.register_trusted(family_manifest(), plugin)
    return plugin


def _plain(value: Any) -> Any:
    """Detach mapping proxies/tuples into ordinary JSON-shaped containers."""
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


class AmazonbargPlugin:
    """The complete family-owned hook boundary required by ``PluginRegistry``."""

    def __init__(self, *, upstream_root: Path | str) -> None:
        self.upstream_root = Path(upstream_root)
        self._parse_reply = upstream_shim.import_parse_reply(self.upstream_root)
        _action_cls, action_parser_cls = upstream_shim.import_action_parser(self.upstream_root)
        self._action_parser_cls = action_parser_cls

    # -- validation ---------------------------------------------------

    def validate_payload(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = _plain(payload)
        if set(data) != {"product", "derived", "pins"}:
            raise ValueError("payload must contain exactly product, derived, and pins")
        product = data["product"]
        derived = data["derived"]
        pins = data["pins"]
        if not isinstance(product, dict) or not isinstance(derived, dict) or not isinstance(pins, dict):
            raise ValueError("payload.product, payload.derived, and payload.pins must be objects")

        if pins.get("upstream_repo") != UPSTREAM_REPO:
            raise ValueError("payload pins the wrong upstream repository")
        if pins.get("upstream_commit") != UPSTREAM_COMMIT:
            raise ValueError("payload pins the wrong upstream commit")
        if pins.get("license") != UPSTREAM_LICENSE:
            raise ValueError("payload pins the wrong upstream license")
        if pins.get("budget_ratio") != BUDGET_RATIO:
            raise ValueError("payload pins the wrong budget_ratio")
        if pins.get("max_turns") != MAX_TURNS:
            raise ValueError("payload pins the wrong max_turns")

        # Codex-review finding 1: the checks above only compare the payload's
        # own declared pin *strings* against constants -- they never touch the
        # actual bytes at `upstream_root`. Verify the real checkout itself is
        # at the pinned commit and clean (mirrors tau3_retail's identical
        # check), so an operator (or a compromised dependency) editing the
        # on-disk checkout in place is caught here rather than silently
        # delegated into by `upstream_shim`/`measurement.compute_upstream_metrics`.
        revision = subprocess.run(
            ["git", "-C", str(self.upstream_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if revision.returncode != 0:
            raise ValueError(
                "upstream_root is not a readable git checkout: "
                f"{revision.stderr.strip()}"
            )
        if revision.stdout.strip() != UPSTREAM_COMMIT:
            raise ValueError(
                "upstream checkout revision mismatch: "
                f"expected {UPSTREAM_COMMIT}, got {revision.stdout.strip()}"
            )
        status = subprocess.run(
            ["git", "-C", str(self.upstream_root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status.returncode != 0 or status.stdout:
            raise ValueError("upstream checkout must be clean at the pinned revision")

        category_file_sha256 = pins.get("category_file_sha256")
        if not isinstance(category_file_sha256, str) or len(category_file_sha256) != 64:
            raise ValueError("payload.pins.category_file_sha256 is malformed")

        for field in ("codename", "category", "category_file", "title", "interest"):
            if not isinstance(derived.get(field), str) or not derived[field]:
                raise ValueError(f"payload.derived.{field} must be a non-empty string")
        if not isinstance(derived.get("description"), str):
            # A handful of upstream records have neither a `description` nor
            # `features` field long enough to use -- product.py's own
            # amazonDescInfo falls back to an empty string, never omits the
            # key. Empty is allowed; missing or non-string is not.
            raise ValueError("payload.derived.description must be a string")
        if not isinstance(derived.get("index_in_file"), int) or derived["index_in_file"] < 0:
            raise ValueError("payload.derived.index_in_file must be a non-negative integer")
        for field in ("price", "cost", "budget"):
            value = derived.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"payload.derived.{field} must be a non-negative number")
        if abs(derived["budget"] - derived["price"] * BUDGET_RATIO) > 1e-9:
            raise ValueError("payload.derived.budget is not price * budget_ratio")
        expected_interest = "mutual" if derived["cost"] <= derived["budget"] else "conflicting"
        if derived["interest"] != expected_interest:
            raise ValueError(
                f"payload.derived.interest is {derived['interest']!r}, "
                f"expected {expected_interest!r} from cost/budget"
            )
        expected_category = codename_category(derived["codename"])
        if derived["category"] != expected_category:
            raise ValueError("payload.derived.category does not match its own codename")
        if derived["category_file"] != f"{derived['category']}.json":
            raise ValueError("payload.derived.category_file does not match its own category")
        expected_codename = f"{derived['category']}_{derived['index_in_file'] + 1}"
        if derived["codename"] != expected_codename:
            raise ValueError(
                f"payload.derived.codename {derived['codename']!r} does not match "
                f"category_{{index_in_file + 1}} = {expected_codename!r}"
            )

        raw_records = load_raw_category_records(self.upstream_root, derived["category_file"])
        index_in_file = derived["index_in_file"]
        if index_in_file >= len(raw_records):
            raise ValueError(
                f"payload.derived.index_in_file {index_in_file} is out of range for "
                f"{derived['category_file']!r} ({len(raw_records)} records)"
            )
        if raw_records[index_in_file] != product:
            raise ValueError(
                "payload.product does not exactly match its pinned category-file record"
            )
        return data

    # -- episode lifecycle ---------------------------------------------

    def initial_state(self, family_case: Mapping[str, Any], cell: Any) -> dict[str, Any]:
        del cell
        derived = family_case["derived"]
        # Cross-check the payload's derived fields against a fresh delegated
        # recomputation (upstream's own product.CamelAmazon loader), never a
        # hand-derived formula -- mirrors tau3_retail's initial_state()
        # cross-checking its payload's tool_schema_sha256 against a live
        # delegated computation.
        products = load_all_derived_products(self.upstream_root)
        matching = [product for product in products if product.codename == derived["codename"]]
        if len(matching) != 1:
            raise ValueError(
                f"delegated product.CamelAmazon() produced {len(matching)} sessions for "
                f"codename {derived['codename']!r}, expected exactly 1"
            )
        (delegated,) = matching
        if (
            delegated.title != derived["title"]
            or delegated.description != derived["description"]
            or abs(delegated.price - derived["price"]) > 1e-9
            or abs(delegated.cost - derived["cost"]) > 1e-9
        ):
            raise ValueError(
                "payload.derived does not match the delegated product.CamelAmazon() "
                f"recomputation for codename {derived['codename']!r}"
            )
        return {
            "messages": [],
            "history": [],
            "turn_index": 0,
            "pending_buyer_input_message": "",
            "pending_seller_input_message": None,
            "_pending_buyer_record": None,
            "termination": None,
            "termination_actor": None,
        }

    def phases(self, family_case: Mapping[str, Any]) -> tuple[PhaseSpec, ...]:
        del family_case
        max_actions = 2 * MAX_TURNS
        return (
            PhaseSpec(
                phase_id=BUYER_PHASE,
                actor_selector="buyer",
                mode="single",
                observation_schema_by_role={"buyer": "amazonbarg_buyer_observation_v1"},
                action_schema_by_role={"buyer": "amazonbarg_reply_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(SELLER_PHASE,),
            ),
            PhaseSpec(
                phase_id=SELLER_PHASE,
                actor_selector="seller",
                mode="single",
                observation_schema_by_role={"seller": "amazonbarg_seller_observation_v1"},
                action_schema_by_role={"seller": "amazonbarg_reply_v1"},
                max_logical_actions=max_actions,
                invalid_action_policy="reject",
                next_phases=(BUYER_PHASE,),
            ),
        )

    def eligible_actors(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
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
        derived = family_case["derived"]
        if phase.phase_id == BUYER_PHASE and seat_id == "buyer":
            return {
                "product": {
                    "codename": derived["codename"],
                    "title": derived["title"],
                    "description": derived["description"],
                    "price": derived["price"],
                },
                "need": {
                    "codename": derived["codename"],
                    "quantity": 1,
                    "budget": derived["budget"],
                },
                "messages": _plain(state["messages"]),
                "incoming_message": state["pending_buyer_input_message"],
                "turn_index": state["turn_index"],
                "max_turns": MAX_TURNS,
            }
        if phase.phase_id == SELLER_PHASE and seat_id == "seller":
            return {
                "product": {
                    "codename": derived["codename"],
                    "title": derived["title"],
                    "description": derived["description"],
                    "price": derived["price"],
                    "cost": derived["cost"],
                },
                "messages": _plain(state["messages"]),
                "incoming_message": state["pending_seller_input_message"],
                "turn_index": state["turn_index"],
                "max_turns": MAX_TURNS,
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
        del family_case, state
        if phase.phase_id == BUYER_PHASE and seat_id == "buyer":
            pass
        elif phase.phase_id == SELLER_PHASE and seat_id == "seller":
            pass
        else:
            return ParseResult.failure("seat_phase_mismatch")
        if not isinstance(response, Mapping):
            return ParseResult.failure("response_not_object")
        raw = _plain(response)
        content = raw.get("content")
        if not isinstance(content, str) or not content:
            # Mirrors upstream's own `parseReply` guard:
            # `if not reply: raise ValueError('parse Reply got empty reply')`.
            return ParseResult.failure("empty_reply")
        thought, talk, action_text, message_to_other = self._parse_reply(content)
        return ParseResult.success(
            {
                "raw_text": content,
                "thought": thought,
                "talk": talk,
                "action_text": action_text,
                "message_to_other": message_to_other,
            }
        )

    def legal(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        seat_id: str,
        phase: PhaseSpec,
        action: Mapping[str, Any],
    ) -> LegalityResult:
        del family_case, state, action
        # No economic legality live (spec "Governing facts"): a DEAL below
        # cost or above budget is not blocked at generation time -- upstream
        # itself never checks this until eval.py:Metrics runs ex post. Only
        # the scheduling-level seat/phase binding is enforced here.
        expected = "buyer" if phase.phase_id == BUYER_PHASE else "seller"
        if seat_id != expected:
            return LegalityResult.illegal("seat_phase_mismatch")
        return LegalityResult.legal_action()

    def _classify_action(self, action_text: str) -> str | None:
        """Mirrors upstream's own ``Agent2AgentSession.isDealOrQuit`` exactly.

        Never reimplements ``ActionParser`` itself (delegated, spec section
        3.1 point 4) -- only its trivial three-way branch on the parsed
        result, which upstream expresses as a bound method on a class this
        adapter never otherwise instantiates (constructing
        ``Agent2AgentSession`` requires live buyer/seller agent objects that
        do not exist in a provider-free, tool-free phase graph).
        """
        try:
            action = self._action_parser_cls()(action_text)
        except RuntimeError:
            return "action_error"
        if action.isDEAL():
            return "deal"
        if action.isQUIT():
            return "quit"
        return None

    def step(
        self,
        family_case: Mapping[str, Any],
        state: Mapping[str, Any],
        phase: PhaseSpec,
        actions: Mapping[str, Any],
    ) -> TransitionResult:
        del family_case
        new_state = _plain(state)

        if phase.phase_id == BUYER_PHASE:
            parsed = actions["buyer"].action
            record = {
                "turn": new_state["turn_index"],
                "role": "buyer",
                "thought": parsed["thought"],
                "talk": parsed["talk"],
                "action": parsed["action_text"],
                "input_message": new_state["pending_buyer_input_message"],
                "raw_text": parsed["raw_text"],
            }
            new_state["messages"].append({"role": "buyer", "content": parsed["raw_text"]})
            status = self._classify_action(parsed["action_text"])
            if status is not None:
                new_state["history"].append([record])
                _set_termination(new_state, status, "buyer")
                return TransitionResult(
                    state=new_state,
                    next_phase_id=None,
                    consequences={"turns_completed": new_state["turn_index"], "terminating_actor": "buyer"},
                )
            new_state["_pending_buyer_record"] = record
            new_state["pending_seller_input_message"] = parsed["message_to_other"]
            return TransitionResult(
                state=new_state,
                next_phase_id=SELLER_PHASE,
                consequences={"turns_completed": new_state["turn_index"], "terminating_actor": None},
            )

        if phase.phase_id != SELLER_PHASE:
            raise ValueError(f"unknown phase: {phase.phase_id}")

        buyer_record = new_state.pop("_pending_buyer_record", None)
        if buyer_record is None:
            raise RuntimeError("seller_turn reached without a pending buyer record")
        parsed = actions["seller"].action
        record = {
            "turn": new_state["turn_index"],
            "role": "seller",
            "thought": parsed["thought"],
            "talk": parsed["talk"],
            "action": parsed["action_text"],
            "input_message": new_state["pending_seller_input_message"],
            "raw_text": parsed["raw_text"],
        }
        new_state["messages"].append({"role": "seller", "content": parsed["raw_text"]})
        new_state["history"].append([buyer_record, record])
        new_state["pending_seller_input_message"] = None
        status = self._classify_action(parsed["action_text"])
        new_state["turn_index"] += 1
        if status is not None:
            _set_termination(new_state, status, "seller")
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"turns_completed": new_state["turn_index"], "terminating_actor": "seller"},
            )
        if new_state["turn_index"] >= MAX_TURNS:
            _set_termination(new_state, "turn_limit", None)
            return TransitionResult(
                state=new_state,
                next_phase_id=None,
                consequences={"turns_completed": new_state["turn_index"], "terminating_actor": None},
            )
        new_state["pending_buyer_input_message"] = parsed["message_to_other"]
        return TransitionResult(
            state=new_state,
            next_phase_id=BUYER_PHASE,
            consequences={"turns_completed": new_state["turn_index"], "terminating_actor": None},
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
            "terminating_actor": state["termination_actor"],
            "turns_completed": state["turn_index"],
            "message_count": len(state["messages"]),
            "history": state["history"],
        }

    def outcome(
        self, family_case: Mapping[str, Any], terminal: Mapping[str, Any]
    ) -> dict[str, Any]:
        del family_case
        return {
            "termination_reason": terminal["reason"],
            "terminating_actor": terminal["terminating_actor"],
            "turns_completed": terminal["turns_completed"],
            "message_count": terminal["message_count"],
        }

    def build_scorer(self, family_case: Mapping[str, Any]) -> measurement.AmazonbargScorer:
        """Return the five declared measurement leaves plus their scorers.

        See ``measurement.py`` (spec section 2): every leaf is declared for
        every case (unlike ``tau3_retail``, none are conditional).
        ``task.evaluation.finalize_family_execution`` calls the returned
        object directly (``plugin.build_scorer(family_case)(scoring_input,
        evidence_refs=scoring_input.evidence_refs)``, per
        kernel_scoring_contract_spec.md section 1); ``self.upstream_root``
        is threaded through here -- mirroring ``Tau3RetailScorer.bridge``'s
        identical build-time binding -- because ``AmazonbargScorer.__call__``
        needs the pinned upstream checkout to delegate to
        ``eval.py:Metrics`` and no other seam in the kernel's fixed
        ``__call__`` signature could carry it in.
        """
        return measurement.build_scorer(family_case, upstream_root=self.upstream_root)

    def build_reference_providers(
        self, family_case: Mapping[str, Any]
    ) -> tuple[Any, ...]:
        del family_case
        return ()

    def generator(self, family_case: Mapping[str, Any]) -> None:
        del family_case
        return None


__all__ = [
    "AmazonbargPlugin",
    "BUYER_PHASE",
    "PLUGIN_ID",
    "SCORER_ID",
    "SELLER_PHASE",
    "family_manifest",
    "register_plugin",
]
