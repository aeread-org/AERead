"""Version-isolated V7.1 validity repair; synthetic access planning, not business utility.

V7 cases and scores are immutable. No paid execution entry point is provided.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

from aeread.shared_runner.registry import HarnessRegistry, PluginRegistry
from aeread.shared_runner.run.resolver import canonical_json_bytes, case_content_sha256, resolve_run_plan
from aeread.shared_runner.schemas import CaseManifest
from . import v2_5_seat_extension_v7 as parent

REVISION = 'refund_v25_seat_extension/7.1'
VERSION = '2.5.11'
ACCESS_RULE = (
    'Synthetic intake-only document-release workflow: each catalogue fact has a release checkpoint. '
    'A prerequisite means its checkpoint must be completed by disclosure before this round starts; '
    'it is NOT a claim that one fact logically implies or verifies another. These access constraints '
    'apply only to intake; policy has separate collection permissions after handoff. Utility is a '
    'published synthetic task priority, not monetary value or empirically estimated information value. '
    'Optimize utility then cost; lexicographic ordering is only the reproducibility contract tie-break.'
)


def access_contract(case):
    return {'scope': 'intake_only_synthetic_document_release', 'rule': ACCESS_RULE,
            'external_business_validation': False,
            'checkpoints': [{'fact_id': r['fact_id'], 'checkpoint': 'release:' + r['fact_id'],
                             'requires_completed_checkpoints': ['release:' + k for k in r['requires']],
                             'rationale': 'Authored queue-release dependency, not an evidence or policy precedence dependency.'}
                            for r in case.seat_context['collection_v6']['catalogue']]}


def build_panels(seed=301, include_holdout=False):
    result = {}
    for seat, cases in parent.build_panels(seed, include_holdout).items():
        repaired = []
        for case in cases:
            ctx = copy.deepcopy(case.seat_context)
            if seat == 'intake': ctx['access_contract_v71'] = access_contract(case)
            if ctx['structure_id'] == 'C02':
                # Within-document revision is meaningful; across-document priority must win.
                # Both A/B keep these same conflicting records; ONLY priority changes.
                for record in ctx['private_records_v6']:
                    if record['document_id'] == 'backup': record['revision'] = 99
            interaction = replace(case.interaction, case_id=case.case_id.replace('seat_v7.', 'seat_v71.', 1),
                                  pair_id=case.interaction.pair_id.replace('seat_v7.', 'seat_v71.', 1))
            repaired.append(replace(case, interaction=interaction, seat_context=ctx))
        result[seat] = tuple(repaired)
    admit_panels(result)
    return result


def admit_panels(panels):
    parent.admit_panels(panels)
    for cases in panels.values():
        for case in cases:
            if not case.case_id.startswith('seat_v71.') or not case.interaction.pair_id.startswith('seat_v71.'):
                raise ValueError('V7.1 cases require distinct identities')
            ctx = case.seat_context
            if 'collection_v6' in ctx and ctx.get('access_contract_v71') != access_contract(case):
                raise ValueError('Missing or misleading public access rationale')
            if ctx['structure_id'] == 'C02':
                records = ctx['private_records_v6']
                if any(r['revision'] != (99 if r['document_id'] == 'backup' else 1) for r in records):
                    raise ValueError('C02 must contain a real cross-authority revision conflict')


class ExtensionPlugin(parent.ExtensionPlugin):
    def validate_payload(self, payload):
        # Parent admission is reused, but V7 payloads are never silently accepted here.
        if payload.get('design_revision') != REVISION: raise ValueError('Wrong V7.1 revision')
        return parent.baseline.ExtensionPlugin.validate_payload(self, payload)

    def observe(self, case, state, seat, phase):
        obs = dict(super().observe(case, state, seat, phase))
        if seat == 'intake' and 'access_contract_v71' in case.seat_context:
            obs['access_contract_v71'] = case.seat_context['access_contract_v71']
        return obs

    def build_scorer(self, case):
        scorer = super().build_scorer(case)
        digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        leaves = []
        for leaf in scorer.leaves:
            domain, ref = leaf.estimand.validity_domain, leaf.verifier.reference
            leaves.append(replace(leaf, leaf_version=VERSION,
                estimand=replace(leaf.estimand, estimand_version=VERSION,
                    validity_domain=replace(domain, domain_version=VERSION,
                        predicate=replace(domain.predicate, version=VERSION, content_sha256=digest))),
                verifier=replace(leaf.verifier, reference=replace(ref, reference_version=VERSION,
                    implementation=replace(ref.implementation, version=VERSION, content_sha256=digest)))))
        return replace(scorer, leaves=tuple(leaves))


ScriptedProvider = parent.ScriptedProvider


def build_run(cases, active_agents=('policy',), provider='scripted', model='refund-v25-scripted', provider_revision=REVISION):
    admit_panels({'selected': cases})
    template = parent.build_run(cases, active_agents, provider, model, provider_revision)
    family = template.plan.families[0]
    pin = parent.v3.legacy._pin('refund_v25_v71_validity_repair', 'reference', Path(__file__), VERSION)
    parent_pin = parent.v3.legacy._pin('refund_v25_v7_parent_dependency', 'reference', Path(parent.__file__), parent.VERSION)
    parent_digest = hashlib.sha256(Path(parent.__file__).read_bytes()).hexdigest()
    pins = tuple(parent.v3.legacy._pin(p.component_id, p.kind, Path(__file__), VERSION)
                 if p.sha256 == parent_digest else p for p in template.plan.implementation_pins)
    family = replace(family, scoring=replace(family.scoring,
        reference_provider_ids=family.scoring.reference_provider_ids + (pin.component_id, parent_pin.component_id)))
    registry = PluginRegistry()
    registry.register(family, ExtensionPlugin(), contribution=parent.v3.legacy._contribution(),
                      evidence_root=parent.v3.legacy.ROOT / 'cases/refund_v2')
    manifests = []
    for manifest in template.plan.cases:
        # Template resolver may sort cases; bind by ID, never positional coincidence.
        case = next(c for c in cases if c.case_id == manifest.case_id)
        raw = json.loads(canonical_json_bytes(manifest))
        raw['payload']['design_revision'] = REVISION
        raw['payload']['semantic_case_sha256'] = hashlib.sha256(canonical_json_bytes({'case': asdict(case), 'revision': REVISION})).hexdigest()
        raw['provenance']['generator_version'] = VERSION
        raw['content_sha256'] = case_content_sha256(raw)
        manifests.append(CaseManifest.from_dict(raw))
    prompts = dict(template.prompt_sources)
    prompts[parent.v3.legacy.PROMPT_IDS['intake']] += ' ' + ACCESS_RULE
    profiles = tuple(replace(p, prompt=replace(p.prompt,
        sha256=hashlib.sha256(prompts[p.prompt.prompt_id].encode()).hexdigest())) for p in template.plan.agent_profiles)
    harnesses = HarnessRegistry()
    for h in template.harnesses.values(): harnesses.register(h)
    suite = 'refund_v25_seat_extension_v71'
    plan = resolve_run_plan(families=(family,), cases=tuple(manifests),
        suite=replace(template.plan.suite, suite_id=suite), sampling=template.plan.sampling,
        evaluation_blocks=template.plan.evaluation_blocks, analysis=template.plan.analysis,
        agent_profiles=profiles, run_spec=replace(template.plan.run_spec, suite_id=suite), registry=registry,
        implementation_pins=pins + (pin, parent_pin), harness_registry=harnesses,
        provider_capabilities={provider: parent.v5.ProviderCapabilities(False, False, False, True, True, False, None),
                               'scripted': parent.v5.ProviderCapabilities(False, False, False, True, False, False, None)})
    return replace(template, registry=registry, plan=plan, prompt_sources=prompts)


async def conformance(output, seeds=(301, 302, 303)):
    if output.exists(): raise FileExistsError('Fresh offline output required')
    rows = []
    for seed in seeds:
        for panel, cases in build_panels(seed, include_holdout=True).items():
            for seat in parent.v3.legacy.ROLES:
                setup = build_run(cases, active_agents=(seat,))
                for cell in setup.plan.cells:
                    root = output / str(seed) / panel / seat
                    execution = await parent.v3.legacy.execute_plan_cell(plan=setup.plan, cell_id=cell.cell_id,
                        registry=setup.registry, evidence_root=root, prompt_sources=setup.prompt_sources,
                        providers={'scripted': ScriptedProvider()}, pricing=setup.pricing,
                        episode_attempt_ordinal=0, harnesses=setup.harnesses)
                    receipt = parent.v3.legacy.finalize_family_execution(setup=setup, execution=execution)
                    parent.v3.legacy.replay_family_receipt(setup=setup, receipt=receipt, evidence_root=root)
                    if not all(s.primary.value == 1 for s in receipt.scores): raise AssertionError((cell.case_id, seat))
                    metrics = next(s.primary.metadata['collaboration_metrics'] for s in receipt.scores
                                   if s.leaf.leaf_id == parent.v3.measurement.END_TO_END_LEAF_ID)
                    if not all(m['value'] == 1 and m['coverage'] == 1 for m in metrics.values()):
                        raise AssertionError((cell.case_id, metrics))
                    rows.append({'case_id': cell.case_id, 'seat': seat, 'full_scores': True, 'replayed': True,
                                 'receipt_sha256': receipt.receipt_sha256})
        print(json.dumps({'seed': seed, 'completed': len(rows), 'paid_calls': 0}), flush=True)
    summary = {'revision': REVISION, 'seeds': list(seeds), 'completed': len(rows), 'rows': rows,
               'paid_calls': 0, 'paid_execution_authorized': False, 'human_normative_qc_approved': False,
               'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    with (output / 'summary.json').open('xb') as f: f.write(canonical_json_bytes(summary) + b'\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(conformance(parser.parse_args().output))
