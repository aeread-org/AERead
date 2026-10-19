"""Bounded, provider-free candidate markets for the continuous regret contract.

Supplier terms are synthetic. Components come from the existing frozen sourcing
snapshot; none of these prices or quality rates is a marketplace observation.
The generator is declared before screening. Admission never changes a generated
world, and rejected candidates remain in the screen manifest.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

from aeread.shared_runner.run.resolver import case_content_sha256
from aeread.shared_runner.schemas import CaseManifest
from .case_matrix import REQUIRED_VARIANTS
from .duediligence_case_matrix import _build_case, _supplier

GENERATOR_ID = 'procurement_continuous_candidate_matrix_v2'
GENERATOR_VERSION = '2.0.0'
MASTER_SEED = 20260919
CANDIDATE_COUNT = 96


def build_candidate(index: int) -> dict[str, Any]:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < CANDIDATE_COUNT:
        raise ValueError('candidate index must be in the declared bounded pool')
    world_seed = 9190000 + index
    rng = random.Random(f'{GENERATOR_ID}:{MASTER_SEED}:{world_seed}')
    components = rng.sample(sorted(REQUIRED_VARIANTS), 2)
    high_signal_means_good = bool(hashlib.sha256(str(world_seed).encode()).digest()[0] % 2)
    suppliers = []
    for component in components:
        # Distinct menus, costs and precision prevent supplier exchangeability.
        qualities = [rng.uniform(.55, .7), rng.uniform(.75, .86), rng.uniform(.93, .995)]
        rng.shuffle(qualities)
        for rank, quality in enumerate(qualities):
            price = round(rng.uniform(.65, 1.0) + .35 * rank, 3)
            supplier = _supplier(
                component, f'candidate_{index}_{rank}', unit_price=price,
                yield_rate=round(quality, 4), capacity=20, moq=10, order_step=10,
                sample_cost=round(rng.uniform(.3, 1.8), 2), sample_days=rng.choice((1, 2)),
                lead_time=rng.choice((4, 5, 7)), shipping=round(rng.uniform(.02, .12), 3),
                on_time=round(rng.uniform(.95, .995), 4),
                floor_price=round(price * .92, 4), payment_days=rng.choice((15, 30)),
                maximum_payment_days=45, verbal_bias={'verified_yield_rate': .99},
            )
            # A public lead-time signal is imperfect, so learning can improve
            # selection while neither displayed price nor a label gives truth.
            quality_rank = sorted(qualities).index(quality)
            signal_rank = quality_rank if high_signal_means_good else 2 - quality_rank
            supplier['listing']['claimed_lead_time_days'] = 3 + 3 * signal_rank
            batch = rng.choice((4, 8, 12))
            supplier['private_terms']['quality'].update(sample_size=batch, observed_defects=round(batch * (1 - quality)))
            suppliers.append(supplier)
    definition = {
        'slug': f'market_{index:03d}', 'world_seed': world_seed,
        'product_id': f'pilot_kit_{index:03d}', 'bom': {component: 1 for component in components},
        'budget_actions': 9,
        'objective': {'revenue': round(rng.uniform(5, 9), 2), 'penalty': round(rng.uniform(.5, 2), 2),
                      'budget': round(rng.uniform(70, 105), 2), 'deadline': 28, 'minimum': 10},
        'interaction': {'inquiry': .05, 'quote': .1, 'counter': .15}, 'suppliers': suppliers,
    }
    case = _build_case(definition, surface='opaque')
    case['case_id'] = f'procurement_allocation_v1.continuous_candidates_v2.market_{index:03d}'
    case['split'] = 'continuous_candidates_v2'
    case['payload']['interaction'].update(sample_noise={'model': 'binomial', 'seed': MASTER_SEED}, counter_feedback='field_specific')
    case['provenance'] = {'generator_id': GENERATOR_ID, 'generator_version': GENERATOR_VERSION, 'review_status': 'curated'}
    case['content_sha256'] = '0' * 64
    case['content_sha256'] = case_content_sha256(CaseManifest.from_dict(case))
    return case
