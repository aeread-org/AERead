"""Per-role policy seam (D9) — seat table + routing composite for the exchange arena.

The engine (`run_exchange_transcript`) drives ALL agents through ONE policy object,
so every run is self-play. This module makes "who sits in which seat" configurable
without touching the engine: a case config declares a `roles` block, and
`CompositePolicy` — which satisfies the same duck type the engine already probes —
routes each call to the seat's assigned sub-policy via the `agent_id` the engine
already passes.

```json
"roles": {
  "under_test": {"agents": [1], "policy": {"kind": "llm", "model": "<candidate>"}},
  "panel": [
    {"agents": [2, 3], "policy": {"kind": "frozen_llm", "model": "gemini-3.5-flash",
                                   "pin_resolved_model": "gemini-3.5-flash-2026"}},
    {"agents": [4],    "policy": {"kind": "scripted_bilateral_ir"}}
  ],
  "compiler":  {"policy": {"kind": "frozen_llm", "model": "gemini-3.5-flash"}},
  "verifier":  {"policy": {"kind": "frozen_llm", "model": "gemini-3.5-flash"}}
}
```

Seat labels — `under_test` (the candidate being scored), `panel` (the frozen
counterparts the env supplies), `env` (compiler/verifier) — flow into every
manifest row so scoring and cost split per seat.

Policy kinds: `llm` (any model through our stack), `frozen_llm` (temperature and
sample forced to 0; optional `pin_resolved_model` asserts the provider-resolved
version), `scripted_bilateral_ir` (the deterministic L1 policy), and
`live-learning` (RESERVED for the L3 gym — parses, refuses to run).

The agent_id→policy mapping is topology-agnostic (star/mesh/chain/dyad all encode
the same way), matching the yardstick doc's deferred `topology`/`panel_comm` fields.

Validation is strict — refuse to run, never mis-run: exactly one under_test group,
every world agent covered exactly once, compiler+verifier seats mandatory,
unknown kinds rejected.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Optional

ROLES_SCHEMA_VERSION = "1.0"

SEAT_UNDER_TEST = "under_test"
SEAT_PANEL = "panel"
SEAT_ENV = "env"

KIND_LLM = "llm"
KIND_FROZEN_LLM = "frozen_llm"
KIND_SCRIPTED = "scripted_bilateral_ir"
KIND_SCRIPTED_OPTIMAL = "scripted_bilateral_optimal"  # full-info benevolent panel (max joint surplus -> W*)
KIND_SCRIPTED_EXTRACT = "scripted_bilateral_extract"  # full-info self-interested panel (max own surplus)
KIND_SUBMITTED = "submitted"  # a foreign agent behind the text boundary (D10)
KIND_LIVE_LEARNING = "live-learning"  # reserved for L3 (D17); parses, refuses to run
# scripted bilateral panels: deterministic seat policies with no standalone env behavior
SCRIPTED_PANEL_KINDS = {KIND_SCRIPTED, KIND_SCRIPTED_OPTIMAL, KIND_SCRIPTED_EXTRACT}
KNOWN_KINDS = {KIND_LLM, KIND_FROZEN_LLM, KIND_SUBMITTED, KIND_LIVE_LEARNING} | SCRIPTED_PANEL_KINDS


class RoleConfigError(ValueError):
    """The roles block is malformed — the run must be refused, not mis-run."""


@dataclasses.dataclass(frozen=True)
class SeatGroup:
    """One entry of the seat table: a set of agents (or an env role) + a policy spec."""

    seat: str  # SEAT_UNDER_TEST | SEAT_PANEL | "compiler" | "verifier"
    agents: tuple[int, ...]  # empty for compiler/verifier
    policy: dict[str, Any]

    @property
    def manifest_seat(self) -> str:
        """Seat label as recorded on manifest rows (compiler/verifier fold into env)."""
        if self.seat in (SEAT_UNDER_TEST, SEAT_PANEL):
            return self.seat
        return SEAT_ENV

    @property
    def kind(self) -> str:
        return self.policy["kind"]

    @property
    def pin_resolved_model(self) -> Optional[str]:
        return self.policy.get("pin_resolved_model")


@dataclasses.dataclass(frozen=True)
class RoleTable:
    """Validated seat assignment for one case."""

    groups: tuple[SeatGroup, ...]

    @property
    def under_test_agents(self) -> tuple[int, ...]:
        for group in self.groups:
            if group.seat == SEAT_UNDER_TEST:
                return group.agents
        raise RoleConfigError("role table has no under_test group")  # pragma: no cover

    def group_for(self, seat: str) -> SeatGroup:
        for group in self.groups:
            if group.seat == seat:
                return group
        raise RoleConfigError(f"role table has no {seat!r} group")

    def agent_groups(self) -> list[SeatGroup]:
        return [g for g in self.groups if g.agents]

    def summary(self) -> dict[str, Any]:
        """Compact provenance form for run_meta.json."""
        return {
            "roles_schema_version": ROLES_SCHEMA_VERSION,
            "seats": [
                {
                    "seat": group.seat,
                    "agents": list(group.agents),
                    "kind": group.kind,
                    "model": group.policy.get("model"),
                    "pin_resolved_model": group.pin_resolved_model,
                }
                for group in self.groups
            ],
        }


def _parse_policy_spec(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("policy"), dict):
        raise RoleConfigError(f"{where}: expected an object with a 'policy' object")
    spec = dict(raw["policy"])
    kind = spec.get("kind")
    if kind not in KNOWN_KINDS:
        raise RoleConfigError(f"{where}: unknown policy kind {kind!r}; known: {sorted(KNOWN_KINDS)}")
    if kind in (KIND_LLM, KIND_FROZEN_LLM) and not spec.get("model"):
        raise RoleConfigError(f"{where}: policy kind {kind!r} requires a 'model'")
    return spec


def _parse_agents(raw: Any, where: str, num_agents: int) -> tuple[int, ...]:
    agents = raw.get("agents") if isinstance(raw, dict) else None
    if not isinstance(agents, list) or not agents:
        raise RoleConfigError(f"{where}: expected a non-empty 'agents' list")
    parsed = []
    for value in agents:
        if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= num_agents):
            raise RoleConfigError(f"{where}: agent ids must be ints in 1..{num_agents}, got {value!r}")
        parsed.append(value)
    return tuple(parsed)


def parse_role_table(raw: dict[str, Any], num_agents: int) -> RoleTable:
    """Parse + validate a `roles` config block. Raises RoleConfigError on any defect."""
    if not isinstance(raw, dict):
        raise RoleConfigError("roles block must be an object")
    unknown_keys = set(raw) - {SEAT_UNDER_TEST, SEAT_PANEL, "compiler", "verifier"}
    if unknown_keys:
        raise RoleConfigError(f"roles block has unknown keys: {sorted(unknown_keys)}")

    groups: list[SeatGroup] = []
    if SEAT_UNDER_TEST not in raw:
        raise RoleConfigError("roles block requires exactly one under_test group")
    under_test = raw[SEAT_UNDER_TEST]
    groups.append(
        SeatGroup(
            seat=SEAT_UNDER_TEST,
            agents=_parse_agents(under_test, "roles.under_test", num_agents),
            policy=_parse_policy_spec(under_test, "roles.under_test"),
        )
    )

    panel_entries = raw.get(SEAT_PANEL, [])
    if not isinstance(panel_entries, list):
        raise RoleConfigError("roles.panel must be a list of seat groups")
    for index, entry in enumerate(panel_entries):
        where = f"roles.panel[{index}]"
        groups.append(
            SeatGroup(
                seat=SEAT_PANEL,
                agents=_parse_agents(entry, where, num_agents),
                policy=_parse_policy_spec(entry, where),
            )
        )

    # the engine compiles+verifies every round, so both env seats are mandatory
    for env_seat in ("compiler", "verifier"):
        if env_seat not in raw:
            raise RoleConfigError(f"roles block requires a {env_seat!r} seat")
        groups.append(
            SeatGroup(
                seat=env_seat,
                agents=(),
                policy=_parse_policy_spec(raw[env_seat], f"roles.{env_seat}"),
            )
        )
        if groups[-1].kind in SCRIPTED_PANEL_KINDS:
            raise RoleConfigError(
                f"roles.{env_seat}: a scripted bilateral policy has no standalone "
                f"{env_seat} behavior; use an llm/frozen_llm seat"
            )

    for group in groups:
        if group.kind == KIND_SUBMITTED and group.seat != SEAT_UNDER_TEST:
            raise RoleConfigError(
                f"roles.{group.seat}: only the under_test seat may be 'submitted' — "
                "the panel and env seats are the benchmark's, never the candidate's"
            )

    seen: dict[int, str] = {}
    for group in groups:
        for agent_id in group.agents:
            if agent_id in seen:
                raise RoleConfigError(
                    f"agent {agent_id} assigned to both {seen[agent_id]!r} and {group.seat!r}"
                )
            seen[agent_id] = group.seat
    missing = [a for a in range(1, num_agents + 1) if a not in seen]
    if missing:
        raise RoleConfigError(f"agents with no seat: {missing} (every agent needs exactly one)")

    return RoleTable(groups=tuple(groups))


class _SubmittedAction:
    """Response-shaped record of one foreign-agent action, for the manifest/snapshots."""

    def __init__(self, model: str, text: str):
        self.model = model
        self.text = text
        self.cached = False
        self.usage = None
        self.estimated_cost_usd = 0.0
        self.cost_note = "submitted agent; inference cost external to the harness"
        self.resolved_model = model


class SubmittedAgentPolicy:
    """Text-boundary adapter for a foreign agent in the under_test seat (D10).

    THE information barrier: the foreign agent never receives the world object.
    Each phase renders the exact per-agent prompt an LLM seat would see (the
    engine's own prompt builders, which expose only that agent's private state
    plus the public transcript) and calls ``agent.act(observation, phase) -> str``.

    Every action is recorded to the manifest (origin="submitted") and snapshotted
    under a replay key of the observation text, so a submission run replays
    byte-identically with the foreign agent absent: in replay mode the adapter
    serves recorded actions and hard-fails on a miss, mirroring llm_agent.

    Uses the engine's underscore-prefixed prompt builders — the same private-API
    trade-off as the manifest mixin: breaks loudly on refactor, covered by tests.
    """

    v1_recorder = None  # attached by the runner, like the manifest mixin
    v1_seat = SEAT_UNDER_TEST

    def __init__(self, agent: Optional[Any], label: str = "submitted"):
        self._agent = agent
        self._model_label = f"submitted:{label}"
        self.protocol = None

    def _act(self, observation: str, phase: str, agent_id: int, round_index: Optional[int]) -> str:
        from aeread.inference import llm_agent

        key = llm_agent.compute_replay_key(self._model_label, "", observation, 0, 0.0, 0)
        replay_dir = llm_agent.get_replay_dir()
        if replay_dir is not None:
            path = replay_dir / f"{key}.json"
            if not path.is_file():
                raise llm_agent.ReplayCacheMiss(
                    f"replay miss: no recorded submitted-agent action {key}.json in {replay_dir} "
                    f"(phase={phase}, observation starts: {observation[:80]!r})"
                )
            import json as _json

            text = str(_json.loads(path.read_text())["text"])
        else:
            if self._agent is None:
                raise RoleConfigError(
                    "a live run with an under_test seat of kind 'submitted' requires "
                    "an agent instance (pass under_test_agent to run_v1)"
                )
            text = str(self._agent.act(observation, phase)).strip()
        action = _SubmittedAction(self._model_label, text)
        if self.v1_recorder is not None:
            self.v1_recorder.record(
                role=phase,
                agent_id=agent_id,
                round_index=round_index,
                system="",
                prompt=observation,
                response=action,
                model=self._model_label,
                params={"max_tokens": 0, "temperature": 0.0, "sample": 0},
                batched=False,
                seat=self.v1_seat,
                origin="submitted",
            )
        return text

    def communication_text(self, world, agent_id, round_index, history):
        from aeread.exchange_v1 import economy as ex

        observation = ex._freeform_communication_prompt(
            world, agent_id, round_index, history, protocol=self.protocol
        )
        return self._act(observation, "communication", agent_id, round_index)

    def propose_text(self, world, agent_id, round_index, history, communication_texts):
        from aeread.exchange_v1 import economy as ex

        observation = ex._freeform_proposal_prompt(
            world, agent_id, round_index, history, communication_texts, protocol=self.protocol
        )
        return self._act(observation, "proposal", agent_id, round_index)

    def respond_text(self, world, agent_id, transcript, history):
        from aeread.exchange_v1 import economy as ex

        observation = ex._freeform_response_prompt(
            world, agent_id, transcript, history, protocol=self.protocol
        )
        return self._act(observation, "response", agent_id, transcript.round_index)

    def finalize_text(self, world, agent_id, transcript, history):
        from aeread.exchange_v1 import economy as ex

        observation = ex._freeform_finalize_prompt(
            world, agent_id, transcript, history, protocol=self.protocol
        )
        return self._act(observation, "finalization", agent_id, transcript.round_index)

    def private_acceptance_text(self, world, agent_id, transcript, mechanism, history):
        from aeread.exchange_v1 import economy as ex

        observation = ex._private_acceptance_prompt(
            world, agent_id, transcript, mechanism, history, protocol=self.protocol
        )
        return self._act(observation, "private_acceptance", agent_id, transcript.round_index)


class CompositePolicy:
    """Routes each engine call to the seat's sub-policy. Engine sees ONE policy.

    Exposes exactly the surface the engine probes, nothing more:
    - the six duck-typed methods, routed by agent_id / env seat;
    - `private_acceptance_texts` (semantic, not just batching: without it the
      engine gets NO acceptance texts and private-acceptance configs change
      behavior) — routed per debited agent, seats without the method abstain;
    - deliberately NO `communication_texts`/`response_texts`: their absence makes
      the engine fall back to per-agent singular calls, which is what routing
      needs (v0 forfeits provider-batch under composite);
    - `protocol` (fanned out to sub-policies), `call_records`, `usage_summary`
      (aggregated across seats for the funnel check and the cost line).
    """

    def __init__(self, agent_policies: dict[int, Any], compiler_policy: Any, verifier_policy: Any):
        self._agent_policies = dict(agent_policies)
        self._compiler_policy = compiler_policy
        self._verifier_policy = verifier_policy
        unique: list[Any] = []
        for policy in [*self._agent_policies.values(), compiler_policy, verifier_policy]:
            if all(policy is not seen for seen in unique):
                unique.append(policy)
        self.sub_policies: tuple[Any, ...] = tuple(unique)
        self._protocol = None

    # -- protocol propagation (the engine assigns policy.protocol before running) --

    @property
    def protocol(self):
        return self._protocol

    @protocol.setter
    def protocol(self, value) -> None:
        self._protocol = value
        for policy in self.sub_policies:
            if hasattr(policy, "protocol"):
                policy.protocol = value

    # -- routing --

    def _agent_policy(self, agent_id: int):
        try:
            return self._agent_policies[agent_id]
        except KeyError:
            raise RoleConfigError(f"no seat assigned for agent {agent_id}") from None

    def communication_text(self, world, agent_id, round_index, history):
        return self._agent_policy(agent_id).communication_text(world, agent_id, round_index, history)

    def propose_text(self, world, agent_id, round_index, history, communication_texts):
        return self._agent_policy(agent_id).propose_text(
            world, agent_id, round_index, history, communication_texts
        )

    def respond_text(self, world, agent_id, transcript, history):
        return self._agent_policy(agent_id).respond_text(world, agent_id, transcript, history)

    def finalize_text(self, world, agent_id, transcript, history):
        return self._agent_policy(agent_id).finalize_text(world, agent_id, transcript, history)

    def compile_transcript(self, world, transcript):
        return self._compiler_policy.compile_transcript(world, transcript)

    def verify_compilation(self, world, transcript, mechanism):
        return self._verifier_policy.verify_compilation(world, transcript, mechanism)

    def private_acceptance_texts(self, world, agent_ids, transcript, mechanism, history):
        texts: dict[int, str] = {}
        for agent_id in agent_ids:
            policy = self._agent_policy(agent_id)
            if hasattr(policy, "private_acceptance_text"):
                texts[agent_id] = policy.private_acceptance_text(
                    world, agent_id, transcript, mechanism, history
                )
            elif hasattr(policy, "private_acceptance_texts"):
                texts.update(
                    policy.private_acceptance_texts(world, [agent_id], transcript, mechanism, history)
                )
            # seats without the method (scripted) abstain — same as a policy
            # without the attribute under the single-policy path
        return texts

    # -- aggregation across seats (funnel check + cost line) --

    @property
    def call_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for policy in self.sub_policies:
            records.extend(getattr(policy, "call_records", []) or [])
        return records

    def usage_summary(self) -> dict[str, Any]:
        # borrow the canonical aggregation over self.call_records
        from aeread.exchange_v1 import economy as ex

        return ex.LLMCompilerVerifierPolicy.usage_summary(self)
