"""One prepared data-center terms setup per controlled campaign cell."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.controlled_campaign import CellResult, PlannedCell
from aeread.shared_runner.run.halt import CellOutcome
from aeread.shared_runner.run.layout import RunLayout
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.task.spend import attempt_spend

from . import campaign as base
from .runner import (build_openrouter_setup, finalize_datacenter_terms_execution,
                     finalize_datacenter_terms_failure, replay_datacenter_terms_receipt)

BASE_PATH = 'configs/datacenter_development_terms_reliability_v1.json'
CAMPAIGN_ID = 'datacenter_terms_budget_campaign_v1'
ADAPTER_ID = 'datacenter_terms_reliability'


@dataclass(frozen=True)
class Binding:
    planned: PlannedCell
    setup: Any
    cell: Any
    metadata: Mapping[str, Any]


def load_base(path: Path) -> dict[str, Any]:
    return base.load_contract(path)


def expected_inventory(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Independent base seed/model product, without rebuilding any setup."""
    return {
        f'{model_id}__seed_{seed}': {
            'arm_key': model_id,
            'metadata': {'cell_key': f'{model_id}__seed_{seed}',
                         'model_id': model_id, 'inference_seed': seed},
        }
        for seed in contract['inference_seeds']
        for model_id in sorted(contract['models'])
    }


def validate_binding(contract: Mapping[str, Any], binding: Binding) -> None:
    model = contract['models'][binding.metadata['model_id']]
    expected_case = base.load_cases(case_slugs=(str(contract['case_slug']),))[0]
    actual_cases = [case for case in binding.setup.plan.cases if case.case_id == binding.cell.case_id]
    if len(actual_cases) != 1:
        raise ValueError('data-center bound case is absent or ambiguous in the actual plan')
    actual_case = actual_cases[0]
    expected_hash = contract['expected_case_sha256']
    if (actual_case.content_sha256 != expected_hash
            or binding.cell.case_sha256 != expected_hash
            or case_content_sha256(actual_case) != expected_hash
            or canonical_json_bytes(actual_case) != canonical_json_bytes(expected_case)
            or canonical_json_bytes(binding.setup.case) != canonical_json_bytes(expected_case)):
        raise ValueError('data-center actual plan case, cell, facade and base contract differ')
    profiles = binding.setup.plan.agent_profiles
    if (binding.cell.case_id != binding.setup.case.case_id
            or binding.setup.case.content_sha256 != contract['expected_case_sha256']
            or len(profiles) != 1
            or dict(binding.cell.profile_by_seat) != {'analyst': model['profile_id']}):
        raise ValueError('data-center setup differs from its base cell assignment')
    profile = profiles[0]
    if (profile.model.model != model['requested_model']
            or profile.model.revision != model['canonical_model']
            or profile.sampling.seed != binding.metadata['inference_seed']):
        raise ValueError('data-center profile differs from its base model/seed assignment')


def prepare(contract: Mapping[str, Any]) -> tuple[Binding, ...]:
    bindings = []
    controls = contract['execution']
    for planned in base._cells(contract):
        setup = build_openrouter_setup(
            base._route(contract['models'][planned['model_id']]),
            seed=planned['inference_seed'], case_slug=contract['case_slug'],
            max_output_tokens=controls['max_output_tokens'],
            timeout_seconds=controls['timeout_seconds'],
            max_cost_usd=controls['max_cost_usd_per_cell'],
        )
        if len(setup.plan.cells) != 1:
            raise ValueError('data-center terms requires one prepared cell')
        bindings.append(Binding(PlannedCell(planned['cell_key'], planned['model_id']),
                                setup, setup.plan.cells[0], planned))
    return tuple(bindings)


def design_gate(contract: Mapping[str, Any], bindings: tuple[Binding, ...]) -> Mapping[str, Any]:
    for binding in bindings:
        if binding.setup.case.content_sha256 != contract['expected_case_sha256']:
            raise ValueError('data-center terms frozen case hash differs')
    return {'status': 'passed', 'claim_status': contract['claim_status']}


async def provider_free_gate(contract: Mapping[str, Any], root: Path) -> Mapping[str, Any]:
    return await base.run_provider_free_gate(contract, run_root=root)


def _condition(error: BaseException) -> str | None:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if getattr(error, 'condition', None):
            return str(error.condition)
        error = error.__cause__ or error.__context__
    return None


async def execute(binding: Binding, provider: Any, evidence_root: Path) -> CellResult:
    setup, cell = binding.setup, binding.cell
    try:
        execution = await execute_plan_cell(
            plan=setup.plan, cell_id=cell.cell_id, registry=setup.registry,
            evidence_root=evidence_root, prompt_sources=setup.prompt_sources,
            providers={'openrouter': provider}, pricing=setup.pricing,
            harnesses=setup.harnesses, episode_attempt_ordinal=0,
        )
    except Exception as error:
        receipt = finalize_datacenter_terms_failure(setup=setup, cell_id=cell.cell_id,
                                                    evidence_root=evidence_root, error=error)
        verify_evaluation_receipt(receipt)
        condition = _condition(error) or receipt.failure.condition
        payload = {**binding.metadata, 'receipt_sha256': receipt.receipt_sha256,
                   'receipt_status': receipt.status, 'inclusion_status': receipt.inclusion_status,
                   'provider_failure_condition': condition,
                   'final_failure_condition': receipt.failure.condition,
                   'failure_class': receipt.failure.failure_class,
                   'error_type': type(error).__name__, 'replay_verified': False}
        status, outcome = 'attempted_failure', CellOutcome(True, condition)
    else:
        receipt = finalize_datacenter_terms_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_datacenter_terms_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        verify_evaluation_receipt(replayed)
        if canonical_json_bytes(receipt.scores) != canonical_json_bytes(replayed.scores):
            raise ValueError('data-center terms replay score mismatch')
        payload = {**binding.metadata, 'receipt_sha256': receipt.receipt_sha256,
                   'receipt_status': receipt.status, 'inclusion_status': receipt.inclusion_status,
                   'scores': receipt.scores, 'replay_verified': True}
        status, outcome = 'completed', CellOutcome(False)
    attempts = RunLayout(evidence_root, setup.plan.run_plan_id).resolve_attempts_dir(cell.cell_id)
    paths = [path for path in attempts.iterdir() if path.is_dir()]
    if len(paths) != 1:
        raise ValueError('expected exactly one fresh data-center terms attempt')
    return CellResult(status, payload, attempt_spend(paths[0]), outcome)
