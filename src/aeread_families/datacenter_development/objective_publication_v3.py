"""Publish the parameter-compatible V3 objective-grounding campaign."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from aeread.shared_runner.run.resolver import canonical_json_bytes

from .objective_campaign_v3 import (
    CAMPAIGN_ID,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_RUN_ROOT,
    load_contract,
)
from .objective_publication import PROHIBITED_PUBLIC_TEXT
from .objective_publication_v2 import publish as publish_projection


PUBLICATION_SCHEMA_VERSION = "aeread.datacenter_objective_publication/0.3"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLICATION_ROOT = REPOSITORY_ROOT / "evidence" / CAMPAIGN_ID

README = """# Data-center V2 objective-grounding campaign, adapter V3

This directory is the sanitized, PR-ready projection of the first scoreable
campaign on the bounded objective-visible V2 data-center agreement stack. V3
uses a versioned OpenRouter adapter that omits undeclared reasoning parameters,
plus new seeds and two non-reasoning Apache-2.0 model routes. It does not retry
or replace any excluded V1 or V2 cell.

Only the developer is live. Five deterministic counterparties enforce the one
complete calibrated package required by the exact-optimum reference. The
primary leaf grants credit only to a completed, binding, constraint-satisfying,
temporally valid agreement stack at or below the certified developer-NPV
optimum. Raw NPV, completion, contract integrity, constraints, temporal
compliance, intentional resolution, and reference dominance remain separate.

Authoritative prompts, raw provider payloads, event stores, and complete
receipts remain under the ignored local
`runs/datacenter_development_v2_objective_grounding_v3/` directory. This
publication omits raw responses, reasoning, failure text, and free-form
messages. Receipt and event digests bind it to the local source evidence.

Operational failures are typed exclusions, never score zero. `observed_usage`
is a spend lower bound when any cell is excluded. All cells share one curated
project, so the results diagnose objective grounding and contract maintenance;
they do not support population generalization or a model winner.
"""


def publish(
    *,
    contract_path: Path | str = DEFAULT_CONTRACT_PATH,
    run_root: Path | str = DEFAULT_RUN_ROOT,
    publication_root: Path | str = DEFAULT_PUBLICATION_ROOT,
) -> dict[str, Any]:
    return publish_projection(
        contract_path=contract_path,
        run_root=run_root,
        publication_root=publication_root,
        _contract_loader=load_contract,
        _publication_schema_version=PUBLICATION_SCHEMA_VERSION,
        _public_summary_schema_version=(
            "aeread.datacenter_objective_public_summary/0.3"
        ),
        _fact_manifest_schema_version=(
            "aeread.datacenter_objective_fact_manifest/0.3"
        ),
        _readme=README,
        _publisher_path=Path(__file__),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    parser.add_argument("--run-root", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--publication-root", type=Path, default=DEFAULT_PUBLICATION_ROOT)
    arguments = parser.parse_args(argv)
    manifest = publish(
        contract_path=arguments.contract,
        run_root=arguments.run_root,
        publication_root=arguments.publication_root,
    )
    print(canonical_json_bytes(manifest).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_PUBLICATION_ROOT",
    "PROHIBITED_PUBLIC_TEXT",
    "PUBLICATION_SCHEMA_VERSION",
    "main",
    "publish",
]
