"""Prospective controlled Housing sensitivity cells, without the legacy loop."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aeread.shared_runner.run.controlled_campaign import CellResult, CriticalStop, PlannedCell
from aeread.shared_runner.run.halt import CellOutcome
from aeread.shared_runner.run.layout import RunLayout
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread.shared_runner.task.receipts import verify_evaluation_receipt
from aeread.shared_runner.task.spend import attempt_spend

from . import model_sensitivity as base
from .runner import finalize_housing_execution, finalize_housing_failure, replay_housing_receipt

BASE_PATH = 'configs/housing_model_sensitivity_v1.json'
CAMPAIGN_ID = 'housing_budget_campaign_v1'
ADAPTER_ID = 'housing_model_sensitivity'


@dataclass(frozen=True)
class Binding:
    planned: PlannedCell
    setup: Any
    cell: Any
    metadata: Mapping[str, Any]


def load_base(path: Path) -> dict[str, Any]:
    return base.load_contract(path)


def expected_inventory(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the full launch matrix from the strict base, without setups."""
    expected = {}
    conditions = contract['conditions']
    for seed in contract['execution']['world_seeds']:
        for index, config in enumerate(base.selected_configs(contract)):
            order = list(range(len(conditions)))
            offset = index % len(conditions)
            for condition_index in order[offset:] + order[:offset]:
                condition = conditions[condition_index]
                for rep in range(contract['execution']['replicates']):
                    key = f"{config['config_id']}__{condition['condition_id']}__{seed}__{rep}"
                    expected[key] = {'arm_key': condition['condition_id'], 'metadata': {
                        'config_id': config['config_id'], 'condition_id': condition['condition_id'],
                        'subject': condition['subject'], 'opponent': condition['opponent'],
                        'evaluation_kind': condition['evaluation_kind'], 'world_seed': seed,
                        'replicate_index': rep,
                    }}
    return expected


def _base_case(contract: Mapping[str, Any], config: Mapping[str, Any], seed: int) -> CaseManifest:
    """Freeze the existing v1 runner's case schema under this strict base.

    This derives only the manifest, not a second setup or execution. The
    fields are the unchanged build_housing_smoke experiment-case fields.
    """
    index = contract['execution']['world_seeds'].index(seed) + 1
    raw = {
        'spec_version': 'aeread.case/0.1',
        'case_id': f'housing_v1__experiment__{index:06d}',
        'family_id': 'housing_v1', 'family_version': '1.0.0',
        'split': 'evaluation', 'world_seed': seed,
        'seats': [
            *[{'id': f'tenant_{i}', 'role': 'tenant'} for i in range(config['tenants'])],
            *[{'id': f'landlord_{i}', 'role': 'landlord'} for i in range(config['listings'])],
        ],
        'episode': {'max_logical_actions': config['rounds'] * (2 * config['tenants'] + config['listings']),
                    'termination': ['allocation', 'deadline']},
        'visibility_policy': 'housing_private_preferences_v1',
        'payload': {'world_kind': 'bid', 'world_seed': seed,
                    'num_tenants': config['tenants'], 'num_listings': config['listings'],
                    'rounds': config['rounds'], 'common_weight': config['common_weight']},
        'provenance': {'generator_id': 'housing_generator_v1',
                       'generator_version': '1.0.0', 'review_status': 'generated'},
        'content_sha256': '0' * 64,
    }
    raw['content_sha256'] = case_content_sha256(raw)
    return CaseManifest.from_dict(raw)


def validate_binding(contract: Mapping[str, Any], binding: Binding) -> None:
    config = next(item for item in base.selected_configs(contract)
                  if item['config_id'] == binding.metadata['config_id'])
    cases = {case.case_id: case for case in binding.setup.plan.cases}
    case = cases[binding.cell.case_id]
    expected_case = _base_case(contract, config, binding.metadata['world_seed'])
    if (canonical_json_bytes(case) != canonical_json_bytes(expected_case)
            or binding.cell.case_sha256 != expected_case.content_sha256):
        raise ValueError('Housing actual plan case identity/hash differs from the strict base configuration')
    expected_payload = {
        'world_kind': 'bid', 'world_seed': binding.metadata['world_seed'],
        'num_tenants': config['tenants'], 'num_listings': config['listings'],
        'rounds': config['rounds'], 'common_weight': config['common_weight'],
    }
    if (dict(case.payload) != expected_payload
            or binding.cell.world_seed != binding.metadata['world_seed']
            or binding.cell.replicate_index != binding.metadata['replicate_index']):
        raise ValueError('Housing setup differs from its base cell assignment')
    subject = contract['models'][binding.metadata['subject']]
    opponent = contract['models'][binding.metadata['opponent']]
    expected_profiles = {'tenant': subject['tenant_profile_id'],
                         'landlord': opponent['landlord_profile_id']}
    if dict(binding.cell.profile_by_seat) != {
        seat.id: expected_profiles[seat.role] for seat in case.seats
    }:
        raise ValueError('Housing seat/profile assignment differs from base condition')


def prepare(contract: Mapping[str, Any]) -> tuple[Binding, ...]:
    setups = base.build_setups(contract)
    conditions = list(contract['conditions'])
    bindings = []
    for world_index, seed in enumerate(contract['execution']['world_seeds']):
        for config_index, config in enumerate(base.selected_configs(contract)):
            offset = config_index % len(conditions)
            rotated = conditions[offset:] + conditions[:offset]
            for condition in rotated:
                setup = setups[(config['config_id'], condition['condition_id'])]
                for rep in range(contract['execution']['replicates']):
                    matches = [cell for cell in setup.plan.cells if cell.world_seed == seed and cell.replicate_index == rep]
                    if len(matches) != 1:
                        raise ValueError('Housing planned cell did not resolve uniquely')
                    cell = matches[0]
                    key = f"{config['config_id']}__{condition['condition_id']}__{seed}__{rep}"
                    bindings.append(Binding(PlannedCell(key, condition['condition_id']), setup, cell, {
                        'config_id': config['config_id'], 'condition_id': condition['condition_id'],
                        'subject': condition['subject'], 'opponent': condition['opponent'],
                        'evaluation_kind': condition['evaluation_kind'], 'world_seed': seed,
                        'replicate_index': rep,
                    }))
    return tuple(bindings)


def design_gate(contract: Mapping[str, Any], bindings: tuple[Binding, ...]) -> Mapping[str, Any]:
    # Keep the base scientific profile admission check; do not change its
    # strict schema or silently adopt newer Housing treatments.
    expected = contract['profile_admission_reference']['profile_sha256s']
    for binding in bindings:
        for profile in binding.setup.plan.agent_profiles:
            if base._sha256(profile) != expected[profile.profile_id]:
                raise ValueError('Housing frozen profile digest differs')
    return {'status': 'passed', 'claim_status': contract['claim_status']}


async def provider_free_gate(contract: Mapping[str, Any], root: Path) -> Mapping[str, Any]:
    return base.provider_free_artifact(contract)


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
        # Finalization errors deliberately escape; never manufacture a valid
        # result after a receipt or persistence failure.
        receipt = finalize_housing_failure(setup=setup, cell_id=cell.cell_id,
                                            evidence_root=evidence_root, error=error)
        verify_evaluation_receipt(receipt)
        condition = base._exception_attribute(error, 'condition') or receipt.failure.condition
        critical = base._critical_failure(error)
        payload = {
            **binding.metadata, 'receipt_sha256': receipt.receipt_sha256,
            'receipt_status': receipt.status, 'inclusion_status': receipt.inclusion_status,
            'provider_failure_condition': condition,
            'final_failure_condition': receipt.failure.condition,
            'failure_class': receipt.failure.failure_class,
            'error_type': type(error).__name__, 'replay_verified': False,
        }
        status, outcome = 'attempted_failure', CellOutcome(True, str(condition))
        stop = CriticalStop('critical_route_or_replay_failure') if critical else None
    else:
        receipt = finalize_housing_execution(setup=setup, execution=execution)
        verify_evaluation_receipt(receipt)
        replayed = replay_housing_receipt(setup=setup, receipt=receipt, evidence_root=evidence_root)
        verify_evaluation_receipt(replayed)
        if canonical_json_bytes(replayed.scores) != canonical_json_bytes(receipt.scores):
            raise ValueError('Housing replay score mismatch')
        payload = {**binding.metadata, 'receipt_sha256': receipt.receipt_sha256,
                   'receipt_status': receipt.status, 'inclusion_status': receipt.inclusion_status,
                   'scores': receipt.scores, 'replay_verified': True}
        status, outcome, stop = 'completed', CellOutcome(False), None
    attempts = RunLayout(evidence_root, setup.plan.run_plan_id).resolve_attempts_dir(cell.cell_id)
    paths = [path for path in attempts.iterdir() if path.is_dir()]
    if len(paths) != 1:
        raise ValueError('expected exactly one fresh Housing attempt')
    return CellResult(status, payload, attempt_spend(paths[0]), outcome, stop)
