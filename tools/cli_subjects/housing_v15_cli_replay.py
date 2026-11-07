"""The evaluation setup a published Housing v15 addendum-B receipt was sealed under, for ``aeread verify-replay``.

    PYTHONPATH=src:tools/cli_subjects aeread verify-replay evidence/housing/housing_lemons_price_v15_cli_addendum \\
        --run-root runs/housing_v15/<campaign_id> --setup housing_v15_cli_replay:setup_for_receipt

``housing_v15_cli_publication.replay_setup`` rebuilds the CLI plans from the contracts in ``runs/`` and finds a
receipt's plan by ``run_plan_id``, which moves with every kernel commit that touches the runtime modules a plan pins
(HL-T-11). This factory rebuilds them from the contracts the published bundles carry (``reports/contracts.json`` of the
addendum and of its admission bundle, byte-equal to the run roots' copies) and matches the receipt's plan digest with
its recorded pins put back, as ``aeread_families.housing.price_replay`` does for v14, v15 and addendum A.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

import housing_v15_cli as cli
from aeread_families.housing.price_replay import match

BUNDLES = ("housing_lemons_price_v15_cli_addendum", "housing_lemons_price_v15_cli_addendum_admission")


def _subject(campaign_id: str) -> str:
    return next(s for s in cli.SUBJECTS if campaign_id.endswith(s))


@lru_cache(maxsize=None)
def setups() -> tuple[Any, ...]:
    """Each addendum-B setup, rebuilt from the published contracts."""
    built = []
    for bundle in BUNDLES:
        path = cli.REPOSITORY / "evidence" / "housing" / bundle / "reports" / "contracts.json"
        for campaign_id, contract in sorted(json.loads(path.read_text(encoding="utf-8")).items()):
            subject = _subject(campaign_id)
            cli.register(subject, "admission" if "admission" in campaign_id else "main")
            runtime = contract["cli"]["provider_runtime"]
            for holdout_rate in (False, True) if "holdout" in contract else (False,):
                for arm in contract["arms"]:
                    built.append(cli.cli_setup(contract, arm, subject, runtime, holdout_rate=holdout_rate))
    return tuple(built)


def setup_for_receipt(receipt: Mapping[str, Any]) -> Any:
    setup = match(setups(), receipt)
    if setup is None:
        raise ValueError(f"no addendum-B plan rebuilds {receipt.get('run_plan_id')!r} with its recorded pins")
    return setup
