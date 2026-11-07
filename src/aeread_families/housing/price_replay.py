"""The evaluation setup a published Housing price receipt was sealed under, for ``aeread verify-replay`` on any kernel.

    PYTHONPATH=src aeread verify-replay evidence/housing/<bundle> --run-root runs/housing_v15/<campaign_id> \\
        --setup aeread_families.housing.price_replay:setup_for_receipt

``price_publication.replay_setup`` finds a receipt's plan by ``run_plan_id``. A v14 or v15 plan pins the kernel's
runtime modules (``aeread.shared_runner.execution`` and ``aeread.shared_runner.housing``) by digest, so every kernel
commit that touches them moves every id, and that lookup then finds nothing (HL-T-11). This factory rebuilds the same
setups from the committed contracts and returns the one whose plan, with the receipt's own pins put back
(``plan_with_recorded_pins``: kernel-owned digests may have moved since sealing, family digests may not), has the
receipt's ``run_plan_sha256``, as ``pay_or_test_v3_replay`` does for procurement. The kernel's receipt audit puts the
same pins back before it compares identities. The command-line addendum's plans are rebuilt by
``tools/cli_subjects/housing_v15_cli_replay.py``. This module is new and unhashed; nothing hashed is edited.

One family pin needs more (HL-D-11). A v14 plan pins its reference ``housing_feasible_zero_v1`` at the bridge digest,
sha256 of ``runner.py`` followed by the kernel's ``task/evaluation.py``, and it is the only record of ``runner.py`` in
a v14 plan. That digest is recomputed from the current ``runner.py`` and ``task/evaluation.py`` as it was when v14 was
sealed (``git show 6aaf46bb:...``); only when it reproduces the recorded digest is the pin treated like a kernel pin, so
a change to ``runner.py`` is still refused. Without that commit in the local history (a shallow clone) a v14 receipt is
refused with ``V14_AT_PUBLISHING_KERNEL`` as the reason, never accepted.
"""
from __future__ import annotations

import dataclasses
import hashlib
import subprocess
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import (
    ImplementationPin,
    PlanResolutionError,
    is_kernel_pin,
    plan_with_pins,
    plan_with_recorded_pins,
)
from aeread_families.housing import price_campaign
from aeread_families.housing import runner as housing_runner

REPOSITORY = Path(__file__).resolve().parents[3]
BRIDGE_PIN = "housing_feasible_zero_v1"
#: The kernel v14 was sealed under, and the kernel file its bridge digest hashes after ``runner.py``.
V14_KERNEL_COMMIT = "6aaf46bb"
BRIDGE_KERNEL_FILE = "src/aeread/shared_runner/task/evaluation.py"
V14_AT_PUBLISHING_KERNEL = (f"v14 identity is verified at its publishing kernel {V14_KERNEL_COMMIT} (TB-D-04's precedent); "
                            "run with full history to check")


class SealingKernelUnavailable(ValueError):
    """The sealing-time kernel file a v14 bridge digest needs is not in the local history."""


@lru_cache(maxsize=None)
def sealing_bridge_digest() -> str | None:
    """sha256 of the current ``runner.py`` followed by ``task/evaluation.py`` at the v14 kernel, or None without it."""
    try:
        kernel_file = subprocess.run(
            ["git", "-C", str(REPOSITORY), "show", f"{V14_KERNEL_COMMIT}:{BRIDGE_KERNEL_FILE}"],
            capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return hashlib.sha256(Path(housing_runner.__file__).read_bytes() + kernel_file).hexdigest()


@lru_cache(maxsize=None)
def setups() -> tuple[Any, ...]:
    """Every setup ``price_publication.replay_setup`` rebuilds: the v14 identities and fill, and each notice-5 identity."""
    built = []
    for campaign_id in (k for k in price_campaign.IDENTITIES if "confirmatory_v14" in k):
        contract = price_campaign.load_contract(price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json"))
        for arm in contract["arms"]:
            built.append(price_campaign.build_setup(contract, arm, live=True))
    from aeread_families.housing import price_seat0

    for campaign_id, spec in price_campaign.IDENTITIES.items():
        if spec.get("notice_version") != 5:
            continue
        path = price_campaign.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json")
        if not path.exists():
            continue
        contract = price_campaign.load_contract(path)
        live = not spec.get("scripted_only")
        for holdout_rate in (False, True) if "holdout" in contract else (False,):
            for arm in contract["arms"]:
                built.append(price_seat0.build_v15_setup(contract, arm, live=live, holdout_rate=holdout_rate))
    return tuple(built)


def recorded_pins(receipt: Mapping[str, Any]) -> tuple[ImplementationPin, ...]:
    """The pins the receipt was sealed under, as the kernel's audit reads them."""
    return tuple(ImplementationPin.from_dict(item) for item in receipt.get("plan_implementation_pins") or ())


def _key(pin: ImplementationPin) -> tuple[str, str, str]:
    return (pin.component_id, pin.kind, pin.version)


def audit_plan(plan: Any, receipt: Mapping[str, Any]) -> Any | None:
    """The plan the receipt's audit should start from: ``plan`` itself, or ``plan`` with a v14 bridge pin set to its
    recorded digest once that digest is reproduced from the current ``runner.py`` and the sealing-time kernel file.
    None when a family pin differs in any other way; ``SealingKernelUnavailable`` when the bridge cannot be checked."""
    recorded = {_key(pin): pin for pin in recorded_pins(receipt)}
    drifted = [pin for pin in plan.implementation_pins
               if not is_kernel_pin(pin) and _key(pin) in recorded and recorded[_key(pin)].sha256 != pin.sha256]
    if not drifted:
        return plan
    if [pin.component_id for pin in drifted] != [BRIDGE_PIN]:
        return None
    bridge = sealing_bridge_digest()
    if bridge is None:
        raise SealingKernelUnavailable(V14_AT_PUBLISHING_KERNEL)
    if recorded[_key(drifted[0])].sha256 != bridge:
        return None
    pins = tuple(dataclasses.replace(pin, sha256=bridge) if pin.component_id == BRIDGE_PIN else pin
                 for pin in plan.implementation_pins)
    return plan_with_pins(plan, pins)


def sealed_plan(plan: Any, receipt: Mapping[str, Any]) -> Any | None:
    """``plan`` as the receipt sealed it (its recorded pins put back), or None if a family pin differs."""
    start = audit_plan(plan, receipt)
    if start is None:
        return None
    try:
        sealed, _drift = plan_with_recorded_pins(start, recorded_pins(receipt))
    except PlanResolutionError:
        return None
    return sealed


def match(candidates: Sequence[Any], receipt: Mapping[str, Any]) -> Any | None:
    """The candidate whose plan, with the receipt's pins put back, has the receipt's plan digest, carrying the plan
    its audit should start from."""
    expected = receipt["run_plan_sha256"]
    unavailable = None
    for setup in candidates:
        try:
            plan = sealed_plan(setup.plan, receipt)
        except SealingKernelUnavailable as error:
            unavailable = error
            continue
        if plan is not None and plan.plan_sha256 == expected:
            start = audit_plan(setup.plan, receipt)
            return setup if start is setup.plan else dataclasses.replace(setup, plan=start)
    if unavailable is not None:
        raise unavailable
    return None


def setup_for_receipt(receipt: Mapping[str, Any]) -> Any:
    setup = match(setups(), receipt)
    if setup is None:
        raise ValueError(f"no v14, v14 fill or v15 plan rebuilds {receipt.get('run_plan_id')!r} with its recorded pins")
    return setup
