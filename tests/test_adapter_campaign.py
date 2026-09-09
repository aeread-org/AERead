from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from aeread.shared_runner.run.adapter_campaign import run_adapter_canary


class _Client:
    async def complete(self, request):
        return SimpleNamespace(
            output_text=json.dumps({"status": "ok"}),
            cost_usd=0.001,
            resolved_model="glm-5p2",
            finish_reason="stop",
            input_tokens=20,
            cached_input_tokens=0,
            output_tokens=5,
        )


def test_adapter_canary_is_hashed_and_resumable(tmp_path: Path) -> None:
    path = tmp_path / "canary.json"
    first = asyncio.run(
        run_adapter_canary(family_id="steer", checkpoint_path=path, client=_Client())
    )
    second = asyncio.run(
        run_adapter_canary(family_id="steer", checkpoint_path=path, client=_Client())
    )
    assert first == second
    assert first["status"] == "admitted"
    assert first["scored"] is False
    assert first["record_sha256"]
