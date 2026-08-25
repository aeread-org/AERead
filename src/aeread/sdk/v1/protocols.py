"""Stable structural contracts for AERead plugins and runner integrations."""

from __future__ import annotations

from typing import Literal, Mapping, Protocol, Sequence, TypeVar, runtime_checkable

from .records import (
    ActionBundle,
    AgentRequest,
    CallAttemptStart,
    CallAttemptToken,
    CanonicalResponse,
    DecisionSlot,
    FamilyOutcome,
    LegalityResult,
    ObservationEnvelope,
    ParseResult,
    PhaseGraph,
    PhaseSpec,
    PluginManifest,
    ProviderCallFailure,
    ProviderCallResult,
    ScoreEnvelope,
    SealedEvidenceView,
    TerminalResult,
    TransitionResult,
)


FamilyCaseT = TypeVar("FamilyCaseT")
FamilyStateT = TypeVar("FamilyStateT")
PlanCellT = TypeVar("PlanCellT")
RuntimeSpecT = TypeVar("RuntimeSpecT")
RuntimeHandleT = TypeVar("RuntimeHandleT")
ProgramRequestT = TypeVar("ProgramRequestT")
ProgramResultT = TypeVar("ProgramResultT")
UpstreamSourceRefT = TypeVar("UpstreamSourceRefT")
UpstreamCaseRefT = TypeVar("UpstreamCaseRefT")
MaterializedCaseT = TypeVar("MaterializedCaseT")
ParityFixtureT = TypeVar("ParityFixtureT")
OfficialResultT = TypeVar("OfficialResultT")
ParityReportT = TypeVar("ParityReportT")


@runtime_checkable
class EnvironmentPlugin(Protocol[FamilyCaseT, FamilyStateT, PlanCellT]):
    """Deterministic economic environment hooks; only ``step`` mutates state."""

    manifest: PluginManifest

    def validate_case(self, payload: Mapping[str, object]) -> FamilyCaseT: ...

    def initial_state(
        self, case: FamilyCaseT, cell: PlanCellT
    ) -> FamilyStateT: ...

    def phase_graph(self, case: FamilyCaseT) -> PhaseGraph: ...

    def decision_slots(
        self,
        case: FamilyCaseT,
        state: FamilyStateT,
        phase: PhaseSpec,
    ) -> Sequence[DecisionSlot]: ...

    def observe(
        self,
        case: FamilyCaseT,
        state: FamilyStateT,
        phase: PhaseSpec,
        slot: DecisionSlot,
    ) -> ObservationEnvelope: ...

    def parse_action(
        self,
        case: FamilyCaseT,
        state: FamilyStateT,
        phase: PhaseSpec,
        slot: DecisionSlot,
        response: CanonicalResponse,
    ) -> ParseResult: ...

    def legal(
        self,
        case: FamilyCaseT,
        state: FamilyStateT,
        phase: PhaseSpec,
        bundle: ActionBundle,
    ) -> LegalityResult: ...

    def step(
        self,
        case: FamilyCaseT,
        state: FamilyStateT,
        phase: PhaseSpec,
        bundles: Mapping[str, ActionBundle],
    ) -> TransitionResult: ...

    def terminal(
        self, case: FamilyCaseT, state: FamilyStateT
    ) -> TerminalResult | None: ...

    def outcome(
        self, case: FamilyCaseT, terminal: TerminalResult
    ) -> FamilyOutcome: ...


@runtime_checkable
class AttemptObserver(Protocol):
    """Runner-owned write-ahead observation of provider calls."""

    def call_started(self, start: CallAttemptStart) -> CallAttemptToken: ...

    def call_succeeded(
        self, token: CallAttemptToken, result: ProviderCallResult
    ) -> None: ...

    def call_failed(
        self, token: CallAttemptToken, failure: ProviderCallFailure
    ) -> None: ...


@runtime_checkable
class AgentAdapter(Protocol):
    """Provider- or harness-specific canonical response adapter."""

    manifest: PluginManifest
    call_observability: Literal["full", "logical_only", "opaque"]

    async def act(
        self, request: AgentRequest, *, attempts: AttemptObserver
    ) -> CanonicalResponse: ...


@runtime_checkable
class VerifierPlugin(Protocol[FamilyCaseT]):
    """Deterministic scorer over a terminal outcome and sealed evidence."""

    manifest: PluginManifest

    def score(
        self,
        case: FamilyCaseT,
        outcome: FamilyOutcome,
        evidence: SealedEvidenceView,
    ) -> ScoreEnvelope: ...


@runtime_checkable
class BenchmarkSourceAdapter(
    Protocol[
        UpstreamSourceRefT,
        UpstreamCaseRefT,
        MaterializedCaseT,
        ParityFixtureT,
    ]
):
    """Materializes immutable upstream cases without controlling execution."""

    manifest: PluginManifest

    def source_ref(self) -> UpstreamSourceRefT: ...

    def enumerate_cases(self, split: str) -> Sequence[UpstreamCaseRefT]: ...

    def materialize_case(self, ref: UpstreamCaseRefT) -> MaterializedCaseT: ...

    def parity_fixtures(self) -> Sequence[ParityFixtureT]: ...


@runtime_checkable
class OfficialVerifierBridge(
    Protocol[ParityFixtureT, OfficialResultT, ParityReportT]
):
    """Compares an upstream official score with AERead's score envelope."""

    def evaluate_official(self, fixture: ParityFixtureT) -> OfficialResultT: ...

    def evaluate_aeread(self, fixture: ParityFixtureT) -> ScoreEnvelope: ...

    def compare(
        self, official: OfficialResultT, aeread: ScoreEnvelope
    ) -> ParityReportT: ...


@runtime_checkable
class ExecutionBackend(
    Protocol[RuntimeSpecT, RuntimeHandleT, ProgramRequestT, ProgramResultT]
):
    """Runtime placement boundary, independent of episode scheduling."""

    manifest: PluginManifest

    async def start(self, spec: RuntimeSpecT) -> RuntimeHandleT: ...

    async def run(
        self, handle: RuntimeHandleT, request: ProgramRequestT
    ) -> ProgramResultT: ...

    async def read(self, handle: RuntimeHandleT, path: str) -> bytes: ...

    async def write(
        self, handle: RuntimeHandleT, path: str, data: bytes
    ) -> None: ...

    async def stop(self, handle: RuntimeHandleT) -> None: ...


__all__ = [
    "AgentAdapter",
    "AttemptObserver",
    "BenchmarkSourceAdapter",
    "EnvironmentPlugin",
    "ExecutionBackend",
    "OfficialVerifierBridge",
    "VerifierPlugin",
]
