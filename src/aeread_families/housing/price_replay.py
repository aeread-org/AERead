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
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

from aeread.shared_runner.run.resolver import ImplementationPin, PlanResolutionError, plan_with_recorded_pins
from aeread_families.housing import price_campaign


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


def sealed_plan(setup: Any, receipt: Mapping[str, Any]) -> Any | None:
    """The setup's plan as the receipt sealed it (its recorded pins put back), or None if a family pin differs."""
    try:
        plan, _drift = plan_with_recorded_pins(setup.plan, recorded_pins(receipt))
    except PlanResolutionError:
        return None
    return plan


def match(candidates: Sequence[Any], receipt: Mapping[str, Any]) -> Any | None:
    """The candidate whose plan, with the receipt's pins put back, has the receipt's plan digest."""
    expected = receipt["run_plan_sha256"]
    for setup in candidates:
        plan = sealed_plan(setup, receipt)
        if plan is not None and plan.plan_sha256 == expected:
            return setup
    return None


def setup_for_receipt(receipt: Mapping[str, Any]) -> Any:
    setup = match(setups(), receipt)
    if setup is None:
        raise ValueError(f"no v14, v14 fill or v15 plan rebuilds {receipt.get('run_plan_id')!r} with its recorded pins")
    return setup
