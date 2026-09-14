"""Skip helper for tests that read the gitignored `runs/` directory.

Several publication tests verify a campaign's published artifacts by reading
the run that produced them. Those runs are scratch and are not committed, so on
a clean checkout the tests fail on a missing file rather than on anything being
wrong. That contradicted the family's own exit gate, which requires the suite
to be reproducible from a clean checkout.

They still run, and still assert everything they did, wherever the artifacts
are present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def requires_run_artifacts(*run_roots: Path | str) -> pytest.MarkDecorator:
    """Skip a module whose source run artifacts are not on this machine."""

    missing = [
        str(Path(root))
        for root in run_roots
        if not Path(root).exists()
    ]
    return pytest.mark.skipif(
        bool(missing),
        reason=(
            "needs local run artifacts under the gitignored runs/ directory: "
            + ", ".join(Path(path).name for path in missing)
        ),
    )
