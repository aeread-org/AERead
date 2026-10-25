"""Refund output-envelope protocol /1. No schema/value repair and no I/O."""
from dataclasses import dataclass
import hashlib
import json
import math
import re

REVISION = 'refund_json_outer_fence/1'


def digest_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def strict_object(text):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate JSON key')
            out[key] = value
        return out
    def nonfinite(value):
        raise ValueError('Nonfinite JSON number')
    def finite_float(text):
        value=float(text)
        if not math.isfinite(value):
            raise ValueError('Nonfinite JSON number')
        return value
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite,parse_float=finite_float)
    if not isinstance(value, dict):
        raise ValueError('Action must be an object')
    return value


def normalize(text, *, truncated=False):
    """Preserve all bytes except a complete, unambiguous standalone fence.

    Inner malformed/duplicate/nonfinite/nonobject JSON remains unmodified, so
    the frozen parser can reject the original answer. Schema and guards still
    run afterwards. Bare responses (including malformed ones) stay unchanged.
    """
    if not isinstance(text,str):
        raise TypeError('Provider text must be a string')
    status, effective = 'identity', text
    match = re.fullmatch(r'```(?:json)?[ \t]*\r?\n(.*?)\r?\n```',text.strip(),re.DOTALL)
    if truncated:
        status = 'truncated_preserved'
    elif match and '```' not in match[1]:
        try:
            strict_object(match[1])
        except (ValueError,RecursionError):
            status = 'invalid_inner_json_preserved'
        else:
            status, effective = 'outer_fence_removed', match[1]
    elif text.lstrip().startswith('```'):
        status = 'unsupported_envelope_preserved'
    return effective, dict(revision=REVISION,status=status,changed=effective!=text,
        original_text=text,effective_text=effective,
        original_sha256=digest_text(text),effective_sha256=digest_text(effective))


def verify_transform(effective, transform, *, truncated=False):
    expected, record = normalize(transform['original_text'],truncated=truncated)
    if effective != expected or record != transform:
        raise ValueError('Output transform does not reproduce exactly')


@dataclass
class CoverageGate:
    """Collection stop decision only; never rewrites a scored model outcome."""
    completed: int = 0
    invalid_native: int = 0
    format_blocked: int = 0

    def observe(self, *, native_valid, format_blocked):
        self.completed += 1
        self.invalid_native += int(not native_valid)
        self.format_blocked += int(format_blocked)
        return dict(completed=self.completed,invalid_native=self.invalid_native,
            format_blocked=self.format_blocked,
            stop_new_calls=bool(self.invalid_native or self.format_blocked),
            reason='measurement_coverage_stop' if self.invalid_native or self.format_blocked else None)
