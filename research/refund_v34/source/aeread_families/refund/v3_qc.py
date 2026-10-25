"""Offline Refund V3 QC, independent of the case generator and environment.

Row contract: exactly one observation per (case_id, pair_id, seed, seat,
cohort, control). IDs are nonempty strings, seed is a nonnegative integer,
validity is a bool. Valid rows require strict to be a finite score in [0, 1]
and policy_semantic to be a finite [0, 1] score for seat='policy' (None for
other seats). Invalid rows may have either score set to None; numeric values
on invalid rows are never performance evidence. Both score keys are required.
Invalid observations explicitly fail QC. They retain their declared panel
positions: contaminated arm means, comparisons and pair shares are undefined
(None), never zero-filled or estimated by dropping invalid rows. Unaffected
arms/strata remain evaluable. No conservative composite is computed.

The caller prespecifies pairs={(seat, cohort): {pair_id: (twin_a, twin_b)}},
seeds and lower_controls (all are included in B3).
'reference' is reserved. The full Cartesian panel is required: no duplicates,
missing twins/arms/seeds/targets, or undeclared observations. Case IDs cannot
belong to different pairs within a target. No seat, cohort, or seed is pooled.
For each target/seed, B1 requires reference minus EACH lower control cohort
mean PRIMARY >= .5: policy PRIMARY is the mean of both-twins strict-pass
outcomes; other seats use case strict means. B2 requires a policy case-mean
semantic gap >= .25. B3 requires EACH lower control's both-twins strict-pass
share <= .1. A strict pass means score == 1 and valid. Invariance
pairs are declared (seat, cohort, pair_id) triples; disagreement is reported
independently, without excluding those pairs from any threshold denominator.
Lower-control flags are diagnostic (random controls need not agree). Declared
reference invariance failures block passage.

Payment admission takes source records with case_id, cohort, initial_no_op
([0, 1] initial-state score), and redelivery (bool). Each cohort's mean over
ALL first-delivery source cases must be <= .25; no source-case filtering is
allowed before computing that mean. An offending cohort is wholly quarantined.
Explicit quarantine reasons are keyed by cohort, not case. Redelivery never
enters the mean or admitted set. All source records and cohort facts survive.

Approval envelope has exactly reviewer_id, payload, signature (strict base64). Payload
has exactly family, version, scope, contribution_digest, reviewer_id. The
signature is RSA PKCS#1 v1.5 SHA256 over approval_payload() bytes (sorted,
compact, ASCII JSON, no newline). The caller owns the reviewer trust mapping
(reviewer ID -> PEM public key bytes), exact scope, and SHA256 digest of the
complete contribution, including evidence/gate facts. This module never signs
or creates approvals. QC status is a rollup of supplied evidence, not an
empirical Gate 3 certification; all six normative gates are required.
"""

from __future__ import annotations

import base64
import binascii
import itertools
import json
import math
import re
import subprocess
import tempfile
from collections.abc import Collection, Iterable, Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

VERSION = '3.0.0'
FAMILY = 'refund_v3'
RULE_ID = 'refund_v3_beatability/1'
STRICT_GAP = 0.5
POLICY_SEMANTIC_GAP = 0.25
WEAK_PAIR_PASS_CAP = 0.1
PAYMENT_INITIAL_NO_OP_CAP = 0.25
REQUIRED_GATES = tuple(f'gate{i}' for i in range(6))
NORMATIVE_STATUSES = frozenset(('passed', 'failed', 'partial', 'not_run', 'not_applicable'))


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _score(value: Any) -> bool:
    return (type(value) in (int, float) and 0 <= value <= 1
            and math.isfinite(value))


def _validate_row(row: Mapping[str, Any]) -> None:
    if any(not _identifier(row.get(k)) for k in
           ('case_id', 'pair_id', 'seat', 'cohort', 'control')):
        raise ValueError('row IDs must be nonempty strings')
    if type(row.get('seed')) is not int or row['seed'] < 0:
        raise ValueError('seed must be a nonnegative integer')
    if type(row.get('validity')) is not bool:
        raise ValueError('validity must be bool')
    if 'strict' not in row or not (
        _score(row['strict']) or (not row['validity'] and row['strict'] is None)
    ):
        raise ValueError('strict must be in [0, 1], or None when invalid')
    if 'policy_semantic' not in row:
        raise ValueError('policy_semantic is required, including when invalid')
    semantic = row['policy_semantic']
    if not ((_score(semantic) or (not row['validity'] and semantic is None))
            if row['seat'] == 'policy' else semantic is None):
        raise ValueError('policy_semantic must be a policy score, otherwise None')


def _observed(row: Mapping[str, Any], metric: str) -> float:
    if not row['validity']:
        raise ValueError('invalid observations have no performance score')
    return float(row[metric])


def _mean(values: Iterable[float]) -> Fraction:
    values = [Fraction(str(v)) for v in values]
    return sum(values, Fraction()) / len(values)


def policy_pair_outcome(twins: Sequence[Mapping[str, Any]]) -> bool | None:
    """Both policy twins must be valid and strict-pass.

    Requires exactly two distinct cases sharing pair/seed/seat/cohort/control.
    Semantic means are measured separately by B2, not folded into PRIMARY.
    Returns None if either twin is invalid, even if its scores are numeric.
    """
    if len(twins) != 2:
        raise ValueError('exactly two twins required')
    for row in twins:
        _validate_row(row)
    if (any(row['seat'] != 'policy' for row in twins)
            or twins[0]['case_id'] == twins[1]['case_id']
            or any(twins[0][k] != twins[1][k] for k in
                   ('pair_id', 'seed', 'seat', 'cohort', 'control'))):
        raise ValueError('twins must share one policy pair/seed/target/control')
    if not all(row['validity'] for row in twins):
        return None
    return all(row['strict'] == 1 for row in twins)


def evaluate_beatability(
    rows: Iterable[Mapping[str, Any]], *,
    pairs: Mapping[tuple[str, str], Mapping[str, tuple[str, str]]],
    seeds: Sequence[int], lower_controls: Sequence[str],
    invariance_pairs: Collection[tuple[str, str, str]] = (),
) -> dict[str, Any]:
    """Validate the complete panel; return threshold and invariance facts.

    B1/B2 compare cohort means, separately per target/seed/control. B3 includes
    every lower control. ``passed`` requires thresholds, validity and reference
    invariance; lower-control invariance flags are diagnostic. No QC gate is set.
    Contaminated comparisons/shares have passed=None, reason=invalid_observations.
    """
    if (not seeds or any(type(s) is not int or s < 0 for s in seeds)
            or len(set(seeds)) != len(seeds)):
        raise ValueError('declare distinct nonnegative seeds')
    if (not lower_controls or isinstance(lower_controls, str)
            or any(not _identifier(c) for c in lower_controls)
            or len(set(lower_controls)) != len(lower_controls)
            or 'reference' in lower_controls):
        raise ValueError('declare distinct non-reference controls')
    expected = set()
    declared_pairs = set()
    if not pairs:
        raise ValueError('declare nonempty target pairs')
    for target, manifest in pairs.items():
        if (not isinstance(target, tuple) or len(target) != 2
                or not all(_identifier(v) for v in target) or not manifest):
            raise ValueError('each target requires a nonempty pair manifest')
        cases = set()
        for pair_id, twins in manifest.items():
            if (not _identifier(pair_id) or not isinstance(twins, (tuple, list))
                    or len(twins) != 2
                    or not all(_identifier(v) for v in twins)
                    or len(set(twins)) != 2 or cases.intersection(twins)):
                raise ValueError('each pair requires two unique, distinct case IDs')
            cases.update(twins)
            declared_pairs.add((*target, pair_id))
            expected.update((case, pair_id, seed, *target, control)
                            for case, seed, control in itertools.product(
                                twins, seeds, ('reference', *lower_controls)))
    if not set(invariance_pairs) <= declared_pairs:
        raise ValueError('undeclared invariance pair')
    panel = {}
    for row in rows:
        _validate_row(row)
        key = tuple(row[k] for k in
                    ('case_id', 'pair_id', 'seed', 'seat', 'cohort', 'control'))
        if key in panel:
            raise ValueError(f'duplicate observation: {key}')
        if key not in expected:
            raise ValueError(f'undeclared observation: {key}')
        panel[key] = dict(row)
    if set(panel) != expected:
        raise ValueError(f'missing observations: {len(expected - set(panel))}')

    invalid = [dict(row) for row in panel.values() if not row['validity']]
    failures = [dict(row, metric='validity', reason='invalid_observation') for row in invalid]
    shares, flags, policy_outcomes, gaps = [], [], [], []
    for (seat, cohort), manifest in pairs.items():
        for seed in seeds:
            means = {}
            for control in ('reference', *lower_controls):
                observations = [panel[c, p, seed, seat, cohort, control]
                                for p, twins in manifest.items() for c in twins]
                arm_valid = all(r['validity'] for r in observations)
                pair_passes = []
                for pair_id, twins in manifest.items():
                    pair_rows = [panel[c, pair_id, seed, seat, cohort, control]
                                 for c in twins]
                    outcome = (policy_pair_outcome(pair_rows) if seat == 'policy'
                               else all(r['strict'] == 1 for r in pair_rows)
                               if all(r['validity'] for r in pair_rows) else None)
                    pair_passes.append(outcome)
                    if seat == 'policy':
                        policy_outcomes.append(dict(seat=seat, cohort=cohort,
                            seed=seed, pair_id=pair_id, control=control, passed=outcome))
                means[control] = dict(primary=None if not arm_valid else
                                     _mean(int(v) for v in pair_passes) if seat == 'policy'
                                     else _mean(_observed(r, 'strict') for r in observations))
                if seat == 'policy':
                    means[control]['policy_semantic'] = (_mean(
                        _observed(r, 'policy_semantic') for r in observations)
                        if arm_valid else None)
                if control != 'reference':
                    share = _mean(int(v) for v in pair_passes) if arm_valid else None
                    fact = dict(seat=seat, cohort=cohort, seed=seed, control=control,
                                both_pass=sum(pair_passes) if arm_valid else None,
                                pairs=len(manifest), invalid_pairs=pair_passes.count(None),
                                share=float(share) if share is not None else None,
                                passed=share <= Fraction(str(WEAK_PAIR_PASS_CAP))
                                if share is not None else None)
                    if not arm_valid:
                        fact['reason'] = 'invalid_observations'
                    shares.append(fact)
                    if fact['passed'] is False:
                        failures.append(dict(fact, metric='lower_pair_pass_share', rule='B3'))
            for control in lower_controls:
                metrics = [('primary', STRICT_GAP, 'B1')]
                if seat == 'policy':
                    metrics.append(('policy_semantic', POLICY_SEMANTIC_GAP, 'B2'))
                for metric, minimum, rule in metrics:
                    reference_mean = means['reference'][metric]
                    lower_mean = means[control][metric]
                    gap = (reference_mean - lower_mean
                           if reference_mean is not None and lower_mean is not None else None)
                    fact = dict(seat=seat, cohort=cohort, seed=seed, control=control,
                                metric=metric, rule=rule,
                                reference_mean=float(reference_mean) if reference_mean is not None else None,
                                lower_mean=float(lower_mean) if lower_mean is not None else None,
                                gap=float(gap) if gap is not None else None,
                                passed=gap >= Fraction(str(minimum)) if gap is not None else None)
                    if gap is None:
                        fact['reason'] = 'invalid_observations'
                    gaps.append(fact)
                    if fact['passed'] is False:
                        failures.append(fact)
            for pair_id, twins in manifest.items():
                for control in ('reference', *lower_controls):
                    observations = [panel[c, pair_id, seed, seat, cohort, control]
                                    for c in twins]
                    if (seat, cohort, pair_id) in invariance_pairs:
                        metrics = ('strict', 'validity') + (
                            ('policy_semantic',) if seat == 'policy' else ())
                        if any(observations[0][m] != observations[1][m]
                               for m in metrics):
                            flags.append(dict(seat=seat, cohort=cohort, seed=seed,
                                              pair_id=pair_id, control=control,
                                              blocking=control == 'reference'))
    return dict(rule_id=RULE_ID, version=VERSION,
                passed=not failures and not any(f['blocking'] for f in flags),
                threshold_passed=not failures, failures=failures,
                validity_passed=not invalid, invalid_observations=invalid,
                thresholds_complete=all(f['passed'] is not None for f in gaps + shares),
                cohort_gaps=gaps, lower_pair_shares=shares, invariance_flags=flags,
                policy_pair_outcomes=policy_outcomes)


def payment_admission(
    cases: Iterable[Mapping[str, Any]], *,
    quarantine: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Admit whole first-delivery cohorts using their unfiltered no-op mean.

    ``quarantine`` maps cohort IDs to reasons. ``passed`` means at least one
    cohort is admitted; each cohort's decision and every source case are exposed.
    """
    quarantine = {} if quarantine is None else dict(quarantine)
    if any(not _identifier(k) or not _identifier(v) for k, v in quarantine.items()):
        raise ValueError('quarantine requires cohort IDs and nonempty reasons')
    sources, seen, grouped = [], set(), {}
    for case in cases:
        case_id = case.get('case_id')
        if not _identifier(case_id) or case_id in seen:
            raise ValueError('source case IDs must be unique and nonempty')
        seen.add(case_id)
        if (not _identifier(case.get('cohort')) or not _score(case.get('initial_no_op'))
                or type(case.get('redelivery')) is not bool):
            raise ValueError('cohort, initial_no_op score and redelivery bool required')
        source = dict(case)
        sources.append(source)
        grouped.setdefault(source['cohort'], []).append(source)
    if set(quarantine) - set(grouped):
        raise ValueError('quarantine contains unknown source cohort IDs')
    cohorts = {}
    for cohort, members in grouped.items():
        first_delivery = [c for c in members if not c['redelivery']]
        mean = _mean(c['initial_no_op'] for c in first_delivery) if first_delivery else None
        reasons = []
        if mean is None:
            reasons.append('no_first_delivery')
        elif mean > Fraction(str(PAYMENT_INITIAL_NO_OP_CAP)):
            reasons.append('cohort_initial_no_op_above_cap')
        if cohort in quarantine:
            reasons.append('quarantined')
        quarantined = cohort in quarantine or 'cohort_initial_no_op_above_cap' in reasons
        rationale = quarantine.get(cohort)
        if rationale is None and quarantined:
            rationale = 'First-delivery cohort mean initial_no_op exceeds 0.25'
        cohorts[cohort] = dict(admitted=not reasons, quarantined=quarantined,
                              quarantine_reason=rationale, reasons=reasons,
                              first_delivery_count=len(first_delivery),
                              initial_no_op_mean=float(mean) if mean is not None else None)
    records = []
    for source in sources:
        fact = cohorts[source['cohort']]
        reasons = list(fact['reasons'])
        if source['redelivery']:
            reasons.append('redelivery_excluded')
        records.append(dict(source=source, admitted=not reasons, reasons=reasons,
                            quarantined=fact['quarantined'],
                            quarantine_reason=fact['quarantine_reason']))
    return dict(passed=any(r['admitted'] for r in records), cases=records,
                cohorts=cohorts,
                admitted_case_ids=[r['source']['case_id'] for r in records
                                   if r['admitted']])


def approval_payload(contribution_digest: str, scope: str, reviewer_id: str) -> bytes:
    """Canonical unsigned bytes for an external reviewer; no signing support."""
    if (not isinstance(contribution_digest, str)
            or re.fullmatch(r'[0-9a-f]{64}', contribution_digest) is None
            or not _identifier(scope) or not _identifier(reviewer_id)):
        raise ValueError('SHA256 hex digest, exact scope and reviewer ID required')
    return json.dumps(dict(family=FAMILY, version=VERSION, scope=scope,
                           contribution_digest=contribution_digest,
                           reviewer_id=reviewer_id),
                      sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def verify_reviewer_approval(
    approval: Mapping[str, Any], *, contribution_digest: str, scope: str,
    authorized_reviewers: Mapping[str, bytes],
) -> bool:
    """Fail closed on untrusted identity, mismatched binding, or OpenSSL failure."""
    try:
        if not isinstance(approval, Mapping) or set(approval) != {
            'reviewer_id', 'payload', 'signature'
        }:
            return False
        reviewer = approval['reviewer_id']
        expected = approval_payload(contribution_digest, scope, reviewer)
        if approval['payload'] != json.loads(expected):
            return False
        key = authorized_reviewers[reviewer]
        if not isinstance(key, bytes) or b'PRIVATE KEY' in key:
            return False
        signature = base64.b64decode(approval['signature'], validate=True)
        if not signature:
            return False
        with tempfile.TemporaryDirectory(prefix='refund-v3-qc-') as directory:
            public_path = Path(directory) / 'reviewer.pem'
            signature_path = Path(directory) / 'signature.bin'
            public_path.write_bytes(key)
            signature_path.write_bytes(signature)
            rsa = subprocess.run(
                ['openssl', 'rsa', '-pubin', '-in', str(public_path), '-noout'],
                capture_output=True, timeout=10, check=False)
            if rsa.returncode != 0:
                return False
            result = subprocess.run(
                ['openssl', 'dgst', '-sha256', '-verify', str(public_path),
                 '-signature', str(signature_path), '-sigopt', 'rsa_padding_mode:pkcs1'],
                input=expected, capture_output=True, timeout=10, check=False)
            return result.returncode == 0
    except (KeyError, TypeError, ValueError, binascii.Error, OSError,
            subprocess.SubprocessError):
        return False


def qc_status(
    gates: Mapping[str, str], *, approval: Mapping[str, Any],
    contribution_digest: str, scope: str,
    authorized_reviewers: Mapping[str, bytes],
    not_applicable_rationales: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Roll up gate0..gate5; omitted gates default to not_run.

    Exact states: passed/failed/partial/not_run/not_applicable. Any unfinished
    gate yields partial, except an entirely unrun panel yields not_run. A failed
    gate dominates. All not_applicable yields not_applicable. Each such gate
    requires a rationale {version: VERSION, rationale: nonempty string}; stale,
    missing or extraneous rationales raise. Otherwise all gates must be passed
    or justified not_applicable AND reviewer approval verified to return passed.
    Callers must bind gate facts and rationales into contribution_digest before
    obtaining approval. This rollup does not generate evidence or certify gates.
    """
    if (set(gates) - set(REQUIRED_GATES)
            or any(not isinstance(v, str) or v not in NORMATIVE_STATUSES
                   for v in gates.values())):
        raise ValueError('unknown gate or gate state')
    complete = {g: gates.get(g, 'not_run') for g in REQUIRED_GATES}
    rationales = {} if not_applicable_rationales is None else dict(not_applicable_rationales)
    if set(rationales) != {g for g, v in complete.items() if v == 'not_applicable'}:
        raise ValueError('each not_applicable gate requires a versioned rationale')
    for rationale in rationales.values():
        if (not isinstance(rationale, Mapping) or set(rationale) != {'version', 'rationale'}
                or rationale['version'] != VERSION or not _identifier(rationale['rationale'])):
            raise ValueError('not_applicable rationale requires current version and rationale text')
    approved = verify_reviewer_approval(approval, contribution_digest=contribution_digest,
                                       scope=scope, authorized_reviewers=authorized_reviewers)
    states = set(complete.values())
    state = ('failed' if 'failed' in states else
             'not_run' if states == {'not_run'} else
             'not_applicable' if states == {'not_applicable'} else
             'passed' if states <= {'passed', 'not_applicable'} and approved
             else 'partial')
    return dict(version=VERSION, normative_status=state, gates=complete,
                not_applicable_rationales={g: dict(r) for g, r in rationales.items()},
                reviewer_approved=approved)
