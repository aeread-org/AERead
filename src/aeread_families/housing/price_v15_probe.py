"""Section 7's one-call admission probe for the v15 profiles, run after the fact, and an audit of every sealed v15 call.

    PYTHONPATH=src python -m aeread_families.housing.price_v15_probe --runs RUN_ROOT --out OUT [--probe]

Declared here and committed before the probe runs (``docs/families/housing/price_confirmatory_v15_plan.md``,
Section 7; HL-J-14):

- **The probe.** For each admitted profile (GPT-6 Luna, Gemini 3.8 Flash), the first request its sealed admission cell
  sent is sent once more through the kernel's ``OpenRouterChatClient``: the same route pin, reasoning setting, seed and
  output schema. The rebuilt request must hash to the sealed ``request_sha256`` before it is sent.
  - Structured output passes when the client returns a reply. The client parses every reply against the request's
    schema and raises otherwise.
  - The reasoning check reads the provider's own count, ``usage.completion_tokens_details.reasoning_tokens``, from the
    raw response. ``OpenRouterChatClient`` does not copy that count into ``ProviderResult.reasoning_tokens``; only
    ``ArenaChatClient`` does. That is why every sealed v15 call shows ``reasoning_tokens: null``. The check passes when
    the provider reports a count, and the count is recorded beside the declared tier.
- **The audit.** Every sealed ``provider_call_succeeded`` payload of the v15 OpenRouter calls in the run roots
  (admission, pilot, confirmatory, A/A), read the same way, per identity: the calls, the calls with a reported reasoning
  count, its minimum, median and maximum, and the cached share of input tokens.

This runs after the freeze, so Gate 4 stays ``partial`` whatever it finds: Section 7 puts the probe first. It records
whether the declared reasoning tiers took effect, which the sealed raw responses can show at no cost.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aeread.shared_runner.task.execution import OpenRouterChatClient, ProviderRequest

PROFILES = {"gpt6_luna": "housing_lemons_price_v15_admission_gpt6_luna",
            "gemini38_flash": "housing_lemons_price_v15_admission_gemini38_flash"}
REQUEST_FIELDS = {f.name for f in dataclasses.fields(ProviderRequest)}


def _usage(result_payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = (result_payload.get("provider_result") or {}).get("raw_response") or {}
    usage = raw.get("usage") or {}
    completion = usage.get("completion_tokens_details") or {}
    prompt = usage.get("prompt_tokens_details") or {}
    return {"reasoning_tokens": completion.get("reasoning_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "prompt_tokens": usage.get("prompt_tokens"), "cached_tokens": prompt.get("cached_tokens"),
            "kernel_reasoning_tokens": (result_payload.get("provider_result") or {}).get("reasoning_tokens"),
            "provider": raw.get("provider"), "model": raw.get("model")}


def sealed_calls(identity_root: Path) -> list[dict[str, Any]]:
    """Every OpenRouter call sealed under one identity's run root: its request and what the provider reported."""
    out = []
    for events in sorted(identity_root.rglob("events.jsonl")):
        base = events.parent
        started: dict[str, Mapping[str, Any]] = {}
        for line in events.read_text().splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            kind = event.get("event_type")
            if kind not in ("provider_call_started", "provider_call_succeeded"):
                continue
            payload = json.loads((base / event["payload_ref"]).read_text())
            if kind == "provider_call_started":
                started[event["provider_call_id"]] = payload["request"]
                continue
            request = started.get(event["provider_call_id"], {})
            # The plan addresses every tenant seat to OpenRouter; only seat 0's calls reach it (the seat router sends the
            # outside seats to the scripted outside-demand provider), so only seat 0's are audited.
            if request.get("provider") != "openrouter" or event.get("visibility") != "seat:tenant_0":
                continue
            out.append({"events": str(events.relative_to(identity_root)), "request": request,
                        "request_sha256": request.get("request_sha256"), "reasoning_effort": request.get("reasoning_effort"),
                        **_usage(payload)})
    return out


def audit(runs: Path) -> dict[str, Any]:
    """Per v15 identity: reasoning and cached tokens as the provider reported them in the sealed raw responses."""
    rows = {}
    for identity_root in sorted(p for p in runs.iterdir() if p.is_dir() and p.name.startswith("housing_lemons_price_v15_")
                                and not p.name.endswith("_preflight")):
        calls = sealed_calls(identity_root)
        if not calls:
            continue
        reported = [c["reasoning_tokens"] for c in calls if isinstance(c["reasoning_tokens"], int)]
        prompt = sum(c["prompt_tokens"] or 0 for c in calls)
        cached = sum(c["cached_tokens"] or 0 for c in calls)
        rows[identity_root.name] = {
            "calls": len(calls), "declared_reasoning_effort": sorted({str(c["reasoning_effort"]) for c in calls}),
            "calls_with_reported_reasoning_count": len(reported),
            "reasoning_tokens": ({"min": min(reported), "median": statistics.median(reported), "max": max(reported),
                                  "zero": sum(r == 0 for r in reported)} if reported else None),
            "kernel_field_null": sum(c["kernel_reasoning_tokens"] is None for c in calls),
            "prompt_tokens": prompt, "cached_tokens": cached, "cached_share": round(cached / prompt, 4) if prompt else None,
        }
    return rows


def _request(sealed: Mapping[str, Any]) -> ProviderRequest:
    request = ProviderRequest(**{k: v for k, v in sealed.items() if k in REQUEST_FIELDS})
    if request.with_computed_hash().request_sha256 != sealed["request_sha256"]:
        raise ValueError("the rebuilt request does not hash to the sealed request_sha256")
    return request


async def probe_one(runs: Path, profile: str) -> dict[str, Any]:
    calls = sealed_calls(runs / PROFILES[profile])
    first = calls[0]
    request = _request(first["request"])
    request = dataclasses.replace(request, provider_call_id=request.provider_call_id + "_probe")
    result = await OpenRouterChatClient().complete(request)
    usage = _usage({"provider_result": {"raw_response": result.raw_response, "reasoning_tokens": result.reasoning_tokens}})
    return {"profile": profile, "identity": PROFILES[profile], "sealed_request_sha256": first["request_sha256"],
            "model": request.model, "revision": request.revision, "declared_reasoning_effort": request.reasoning_effort,
            "structured_output": "passed", "output_text": result.output_text, "response_id": result.response_id,
            "provider_reasoning_tokens": usage["reasoning_tokens"], "kernel_reasoning_tokens": result.reasoning_tokens,
            "reasoning_check": "passed" if isinstance(usage["reasoning_tokens"], int) else "no count reported",
            "prompt_tokens": usage["prompt_tokens"], "cached_tokens": usage["cached_tokens"],
            "completion_tokens": usage["completion_tokens"], "cost_usd": result.cost_usd,
            "sealed_first_call_reasoning_tokens": first["reasoning_tokens"]}


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", required=True, help="the v15 run root, read only")
    parser.add_argument("--out", required=True)
    parser.add_argument("--probe", action="store_true", help="send the one probe call per profile (paid, about $0.01)")
    args = parser.parse_args(argv)
    runs, out = Path(args.runs), Path(args.out)
    report: dict[str, Any] = {"plan": "docs/families/housing/price_confirmatory_v15_plan.md, Section 7 (HL-J-14)",
                              "module_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                              "after_the_freeze": True, "audit": audit(runs)}
    if args.probe:
        report["probe"] = [asyncio.run(probe_one(runs, p)) for p in PROFILES]
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "reports/probe.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "audit"}, indent=1)[:2000])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["PROFILES", "audit", "probe_one", "sealed_calls"]
