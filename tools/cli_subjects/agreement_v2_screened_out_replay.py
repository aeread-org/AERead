"""The evaluation setup an addendum receipt was sealed under, for ``aeread verify-replay``.

    AEREAD_AGREEMENT_RUNS=<directory of run roots> PYTHONPATH=src:tools/cli_subjects \\
        aeread verify-replay evidence/datacenter_development/datacenter_agreement_v2_screened_out_<dry|opus|sol> \\
        --run-root <directory of run roots>/<run root> --setup agreement_v2_screened_out_replay:setup_for_receipt

The addendum's campaigns were frozen through ``agreement_v2_screened_out_cli``, which registers the 14-world pack,
the arms ``dry``, ``opus`` and ``sol`` and its own sources on the v2 driver. Importing it here puts the driver in the
state the plans were frozen in; the search and the pin restoration are ``agreement_v2_replay``'s, unchanged.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import agreement_v2_screened_out_cli  # noqa: F401  (registers the addendum's pack, arms and sources)
from agreement_v2_replay import setup_for_receipt as _v2_setup_for_receipt


def setup_for_receipt(receipt: Mapping[str, Any]):
    return _v2_setup_for_receipt(receipt)
