"""Static, prospective two-family campaign launcher with cumulative offline gates."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import inspect
import json
import os
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .shared_runner.run.controlled_campaign import CampaignControls, PlannedCell, run_controlled_cells
from .shared_runner.run.layout import RunLayout
from .shared_runner.run.resolver import canonical_json_bytes, verify_run_plan
from .shared_runner.task.execution import EvidenceStore, MinimalChatExecutor, OpenRouterChatClient
from .shared_runner.task.receipts import read_evaluation_receipt
from .shared_runner.task.spend import attempt_spend, total_spend

ROOT = Path(__file__).resolve().parents[2]
ADAPTERS = {
    'housing_model_sensitivity': 'aeread_families.housing.budget_campaign',
    'datacenter_terms_reliability': 'aeread_families.datacenter_development_terms.budget_campaign',
}
STAGES = ('design', 'provider_free', 'profile_admission', 'live')
SCHEMA = 'aeread.controlled_campaign/1.0'


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sealed(value: Mapping[str, Any]) -> dict[str, Any]:
    core = {key: item for key, item in value.items() if key != 'artifact_sha256'}
    return {**core, 'artifact_sha256': digest(core)}


def source_pins() -> dict[str, str]:
    """Pin the complete local shared kernel and both adapters' family sources.

    Launch envelopes pin base contracts separately too. This intentionally
    requires a new envelope when a transitive family or kernel source changes.
    """
    paths = {ROOT / 'src/aeread/cli.py', ROOT / 'src/aeread/campaign_cli.py'}
    for directory in ('src/aeread/shared_runner', 'src/aeread_families/housing',
                      'src/aeread_families/datacenter_development_terms'):
        paths.update((ROOT / directory).rglob('*.py'))
    return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def _resources(bindings: tuple[Any, ...]) -> dict[str, Any]:
    profiles: dict[str, Any] = {}
    profile_hashes: dict[str, set[str]] = {}
    for binding in bindings:
        for profile in binding.setup.plan.agent_profiles:
            resource = {
                'max_cost_usd': profile.budgets.max_cost_usd,
                'base_max_output_tokens': profile.sampling.max_output_tokens,
                'effective_max_output_tokens_ceiling': MinimalChatExecutor._length_retry_ceiling(profile),
                'max_action_attempts': profile.retry_policy.max_action_attempts,
                'retryable_conditions': list(profile.retry_policy.retryable_conditions),
                'cap_scope': 'profile_shared_by_assigned_seats_within_cell_executor',
            }
            if profile.profile_id in profiles and profiles[profile.profile_id] != resource:
                raise ValueError('profile resource identity differs across prepared cells')
            profiles[profile.profile_id] = resource
            profile_hashes.setdefault(profile.profile_id, set()).add(digest(profile))
    return {key: {**value, 'profile_sha256s': sorted(profile_hashes[key])}
            for key, value in profiles.items()}


def load_contract(path: Path | str) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    contract = json.loads(Path(path).read_bytes())
    fields = {'schema_version', 'adapter_id', 'campaign_id', 'base_contract', 'controls',
              'source_pins', 'resources', 'account_preflight'}
    if not isinstance(contract, dict) or set(contract) != fields or contract['schema_version'] != SCHEMA:
        raise ValueError('controlled campaign contract fields or schema differ')
    if contract['adapter_id'] not in ADAPTERS:
        raise ValueError('unknown campaign adapter')
    adapter = importlib.import_module(ADAPTERS[contract['adapter_id']])
    if contract['campaign_id'] != adapter.CAMPAIGN_ID:
        raise ValueError('new campaign identity required')
    if contract['source_pins'] != source_pins():
        raise ValueError('campaign source pins differ')
    reference = contract['base_contract']
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'} or reference['path'] != adapter.BASE_PATH:
        raise ValueError('base family contract reference differs')
    base = adapter.load_base(ROOT / reference['path'])
    if digest(base) != reference['sha256']:
        raise ValueError('base family contract digest differs')
    try:
        CampaignControls(**contract['controls'])
    except (TypeError, ValueError) as error:
        raise ValueError('invalid declared campaign controls') from error
    if adapter.ADAPTER_ID == 'housing_model_sensitivity' and contract['controls']['concurrency'] != 1:
        raise ValueError('Housing campaign preserves serial execution')
    preflight = contract['account_preflight']
    if (not isinstance(preflight, dict) or set(preflight) != {'required'}
            or not isinstance(preflight['required'], bool)):
        raise ValueError('account_preflight requires an explicit boolean requirement')
    return contract, adapter, base


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    result = sealed(value)
    payload = canonical_json_bytes(result) + b'\n'
    result = json.loads(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'{path.name}.{uuid.uuid4().hex}.tmp')
    published = False
    try:
        with temporary.open('xb') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # A durable temporary file is published exclusively. No successful
        # artifact name exists while its bytes are still being fsynced.
        os.link(temporary, path)
        published = True
        temporary.unlink()
        _sync_directory(path.parent)
    except BaseException:
        if published:
            # Every post-link operation belongs to this rollback boundary.
            # Error-path cleanup is best effort and cannot replace the
            # primary failure (including cancellation).
            try:
                path.unlink()
            except OSError:
                pass
            try:
                _sync_directory(path.parent)
            except OSError:
                pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return result


def _claim_root(root: Path) -> None:
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise ValueError('campaign requires a fresh empty output root; resume is unsupported')
    root.mkdir(parents=True, exist_ok=True)
    try:
        with (root / '.launch_owner').open('xb') as handle:
            handle.write(b'controlled_campaign/1.0\n')
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise ValueError('campaign output root is already claimed') from error


def _inventory(bindings: tuple[Any, ...], expected: Mapping[str, Any]) -> list[dict[str, Any]]:
    cells = []
    provenance = set()
    for binding in bindings:
        verify_run_plan(binding.setup.plan)
        members = [cell for cell in binding.setup.plan.cells if cell.cell_id == binding.cell.cell_id]
        if len(members) != 1 or canonical_json_bytes(members[0]) != canonical_json_bytes(binding.cell):
            raise ValueError('binding cell is foreign to its verified setup plan')
        case_members = [case for case in binding.setup.plan.cases if case.case_id == binding.cell.case_id]
        if len(case_members) != 1 or binding.cell.case_sha256 != case_members[0].content_sha256:
            raise ValueError('bound cell case hash differs from its verified plan case')
        identity = (binding.setup.plan.run_plan_id, binding.cell.cell_id)
        if identity in provenance:
            raise ValueError('duplicate prepared plan/cell provenance')
        provenance.add(identity)
        cells.append({
            'cell_key': binding.planned.cell_key, 'arm_key': binding.planned.arm_key,
            'run_plan_id': binding.setup.plan.run_plan_id,
            'run_plan_sha256': binding.setup.plan.plan_sha256,
            'cell_id': binding.cell.cell_id,
            'case_id': binding.cell.case_id, 'case_sha256': binding.cell.case_sha256,
            'seat_to_profile': dict(binding.cell.profile_by_seat),
        })
    keys = [cell['cell_key'] for cell in cells]
    if len(keys) != len(set(keys)) or not cells:
        raise ValueError('prepared campaign cells must be nonempty and unique')
    if keys != list(expected):
        raise ValueError('prepared campaign inventory differs from complete ordered base inventory')
    for binding in bindings:
        declared = expected[binding.planned.cell_key]
        if (binding.planned.arm_key != declared['arm_key']
                or dict(binding.metadata) != declared['metadata']):
            raise ValueError('prepared cell arm or metadata differs from base assignment')
    return cells


def _result_receipt(binding: Any, evidence_root: Path, payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], Any]:
    attempts = RunLayout(evidence_root, binding.setup.plan.run_plan_id).resolve_attempts_dir(binding.cell.cell_id)
    paths = [path for path in attempts.iterdir() if path.is_dir() and not path.is_symlink()] if attempts.is_dir() else []
    if len(paths) != 1:
        raise ValueError('callback has no unique receipt at the expected binding attempt path')
    receipt_path = paths[0] / 'evaluation_receipt.json'
    if receipt_path.is_symlink():
        raise ValueError('callback receipt must not be a symlink')
    receipt = read_evaluation_receipt(receipt_path)
    for field, expected in {
        'receipt_sha256': payload.get('receipt_sha256'),
        'run_plan_id': binding.setup.plan.run_plan_id,
        'run_plan_sha256': binding.setup.plan.plan_sha256,
        'cell_id': binding.cell.cell_id,
        'case_id': binding.cell.case_id, 'case_sha256': binding.cell.case_sha256,
    }.items():
        if receipt.get(field) != expected:
            raise ValueError(f'callback receipt {field} differs from expected binding')
    for field in ('receipt_status', 'inclusion_status'):
        receipt_field = 'status' if field == 'receipt_status' else field
        if payload.get(field) != receipt[receipt_field]:
            raise ValueError(f'callback payload {field} differs from actual receipt')
    store = EvidenceStore.audit_existing(paths[0])
    try:
        seal = store.verify_seal()
        if canonical_json_bytes(receipt['evidence']) != canonical_json_bytes(seal):
            raise ValueError('callback receipt differs from its actual evidence seal')
    finally:
        store.close()
    return receipt, attempt_spend(paths[0])


def _counts(planned: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, int]:
    completed = sum(row['status'] == 'completed' for row in rows)
    failed = sum(row['status'] == 'attempted_failure' for row in rows)
    unstarted = sum(row['status'] == 'not_attempted' for row in rows)
    if len(planned) != completed + failed + unstarted:
        raise ValueError('planned/attempted/missing cell counts do not reconcile')
    return {'planned': len(planned), 'attempted': completed + failed,
            'completed': completed, 'attempted_failure': failed, 'not_attempted': unstarted}


async def run_campaign(
    *, contract_path: Path | str, output_root: Path | str,
    stage: str = 'design', provider_factory: Callable[[], Any] = OpenRouterChatClient,
    account_preflight: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Fresh launch only. Injected clients exercise real executors offline.

    Design is the default inspection artifact. Live always reruns the design,
    provider-free and static admission gates in its own fresh output root.
    """
    if stage not in STAGES:
        raise ValueError('unknown campaign stage')
    contract, adapter, base = load_contract(contract_path)
    root = Path(output_root)
    _claim_root(root)
    context = {'schema_version': SCHEMA, 'campaign_id': contract['campaign_id'],
               'contract_sha256': digest(contract), 'controls_sha256': digest(contract['controls']),
               'source_pins_sha256': digest(contract['source_pins']),
               'base_contract_sha256': contract['base_contract']['sha256'], 'stage': stage}
    try:
        _write(root / 'contract.json', contract)
        bindings = adapter.prepare(base)
        expected = adapter.expected_inventory(base)
        inventory = _inventory(bindings, expected)
        for binding in bindings:
            adapter.validate_binding(base, binding)
        by_key = {binding.planned.cell_key: binding for binding in bindings}
        design = dict(adapter.design_gate(base, bindings))
        if design.get('status') != 'passed':
            raise ValueError('family design gate failed')
        actual_resources = _resources(bindings)
        if actual_resources != contract['resources']:
            raise ValueError('declared profile resource caps or identities differ from prepared profiles')
        design = _write(root / 'design.json', {**context, **design, 'cells': inventory,
                                              'resources': actual_resources, 'resume_supported': False})
        if stage == 'design':
            return design
        provider_free = dict(await adapter.provider_free_gate(base, root / 'gates'))
        if provider_free.get('status') != 'passed':
            raise ValueError('family provider-free gate failed')
        provider_free = _write(root / 'provider_free.json', {**context, 'gate': provider_free, 'status': 'passed'})
        if stage == 'provider_free':
            return provider_free
        for binding in bindings:
            if not binding.setup.plan.profile_admissions or not all(item.admitted for item in binding.setup.plan.profile_admissions):
                raise ValueError('static profile admission gate failed')
        admission = _write(root / 'profile_admission.json', {**context, 'status': 'passed',
                           'admitted_cells': [cell['cell_key'] for cell in inventory]})
        if stage == 'profile_admission':
            return admission
        preflight: Any = {'status': 'unsupported', 'real_account_verified': False}
        if account_preflight is not None:
            preflight = account_preflight()
            if inspect.isawaitable(preflight):
                preflight = await preflight
        if not isinstance(preflight, Mapping) or preflight.get('status') not in {'passed_snapshot', 'failed', 'unsupported', 'unknown'}:
            raise ValueError('invalid account preflight result')
        _write(root / 'account_preflight.json', {**context, **preflight})
        if (preflight['status'] == 'failed' or
                (contract['account_preflight']['required'] and preflight['status'] != 'passed_snapshot')):
            raise ValueError('required account preflight unavailable or failed')
        # All gates, including resource and optional account admission, precede
        # construction of any live client.
        provider = provider_factory()
        rows: list[dict[str, Any]] = []
        receipt_provenance: set[tuple[str, str, str]] = set()
        receipt_digests: set[str] = set()
        inventory_by_key = {cell['cell_key']: cell for cell in inventory}
        async def execute(planned: PlannedCell) -> Any:
            return await adapter.execute(by_key[planned.cell_key], provider,
                                         root / 'cells' / planned.cell_key / 'evidence')
        def persist(planned: PlannedCell, result: Any) -> None:
            payload = dict(result.payload)
            binding = by_key[planned.cell_key]
            for field, expected_value in {**inventory_by_key[planned.cell_key], **expected[planned.cell_key]['metadata']}.items():
                if field in payload and canonical_json_bytes(payload[field]) != canonical_json_bytes(expected_value):
                    raise ValueError(f'callback payload {field} conflicts with expected cell identity')
            receipt, actual_spend = _result_receipt(
                binding, root / 'cells' / planned.cell_key / 'evidence', payload,
            )
            if actual_spend != result.spend:
                raise ValueError('callback spending differs from expected attempt evidence')
            provenance = (receipt['run_plan_id'], receipt['cell_id'], receipt['episode_attempt_id'])
            if provenance in receipt_provenance or receipt['receipt_sha256'] in receipt_digests:
                raise ValueError('duplicate callback receipt provenance')
            if result.status == 'completed':
                if (receipt['status'] != 'ok' or not payload.get('replay_verified')
                        or canonical_json_bytes(payload.get('scores')) != canonical_json_bytes(receipt['scores'])):
                    raise ValueError('completed row differs from actual valid replayed receipt')
            elif ('scores' in payload or receipt['status'] != 'invalid_measurement'
                    or payload.get('final_failure_condition') != receipt['failure']['condition']
                    or payload.get('failure_class') != receipt['failure']['failure_class']):
                raise ValueError('failed row differs from actual failure receipt')
            row = _write(root / 'cells' / planned.cell_key / 'result.json', {
                **payload, **context, **inventory_by_key[planned.cell_key],
                'status': result.status, 'spend': actual_spend.as_dict(),
            })
            receipt_provenance.add(provenance)
            receipt_digests.add(receipt['receipt_sha256'])
            rows.append(row)
        controlled = await run_controlled_cells(
            [binding.planned for binding in bindings], execute,
            controls=CampaignControls(**contract['controls']), persist=persist,
        )
        for planned in controlled.not_attempted:
            rows.append(_write(root / 'cells' / planned.cell_key / 'result.json', {
                **context, **inventory_by_key[planned.cell_key], 'status': 'not_attempted',
                'receipt_sha256': None, 'receipt_status': 'not_attempted',
                'failure_class': 'operational', 'failure_condition': controlled.halt['condition'],
            }))
        if len({row['cell_key'] for row in rows}) != len(rows) or set(inventory_by_key) != {row['cell_key'] for row in rows}:
            raise ValueError('missing, duplicate or foreign campaign result')
        rows.sort(key=lambda row: next(i for i, cell in enumerate(inventory) if cell['cell_key'] == row['cell_key']))
        by_arm = {}
        for arm in sorted({cell['arm_key'] for cell in inventory}):
            arm_plan = [cell for cell in inventory if cell['arm_key'] == arm]
            arm_rows = [row for row in rows if row['arm_key'] == arm]
            arm_spend = total_spend(result.spend for cell, result in controlled.results if cell.arm_key == arm)
            by_arm[arm] = {**_counts(arm_plan, arm_rows), 'spend': arm_spend.as_dict()}
        return _write(root / 'summary.json', {
            **context, 'status': 'halted' if controlled.halt else 'completed',
            **_counts(inventory, rows), 'by_arm': by_arm, 'cells': inventory, 'rows': rows,
            'spend': controlled.spend.as_dict(), 'halt': controlled.halt,
            'controls': contract['controls'], 'resources': actual_resources,
            'within_declared_campaign_cost_ceiling': (
                controlled.spend.cost_usd <= contract['controls']['cost_limit_usd']
                if controlled.spend.cost_accounting == 'exact' else None),
            'winner_claim_allowed': False, 'ranking_allowed': False,
            'resume_supported': False,
        })
    except BaseException as error:
        # The partial evidence and any already persisted rows remain intact.
        # No successful summary is published for cancellation or gate failure.
        try:
            _write(root / 'incomplete.json', {**context, 'status': 'incomplete', 'error_type': type(error).__name__})
        except Exception:
            # A failed disk cannot promise another durable marker. Preserve
            # the original exception and the evidence prefix already written.
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--stage', choices=STAGES, default='design')
    args = parser.parse_args(argv)
    result = asyncio.run(run_campaign(contract_path=args.contract, output_root=args.output_root, stage=args.stage))
    print(canonical_json_bytes(result).decode('utf-8'))
    return 2 if result.get('halt') else 0


if __name__ == '__main__':
    raise SystemExit(main())
