"""Section 7's one-call admission probe: structured output and reasoning tokens through an identity's exact route.

    PYTHONPATH=src python tools/housing/price_v15_route_probe.py <campaign_id> [...]

For each identity, one paid OpenRouter call with the contract's route (provider only, its quantization, no
fallbacks), seed, temperature, top_p and reasoning effort, asking for a tenant-shaped JSON move under a strict schema.
The record keeps the routing request (no key), the served provider and model, whether the reply parsed as the schema's
object, and the usage the provider reported, reasoning tokens included; it is written to
``evidence/housing/housing_lemons_price_v15_route_probes/reports/<campaign_id>.json``. The kernel's ``reasoning_tokens`` field
is empty for OpenRouter calls (RN-T-07), though each sealed raw response carries the count; this record states it
directly, with ``require_parameters`` set as the client sets it (HL-J-15).
Run for GLM on Novita before its admission (addendum A); for Luna and Gemini after their run, as a recorded
after-the-fact check that cannot change Gate 4.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from aeread_families.housing import price_campaign as pc

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evidence/housing/housing_lemons_price_v15_route_probes/reports"
SCHEMA = {"type": "object", "properties": {"decision": {"type": "string", "enum": ["offer", "pass"]},
                                           "listing_id": {"type": "integer"}, "rent": {"type": "number"}},
          "required": ["decision", "listing_id", "rent"], "additionalProperties": False}
MESSAGES = [{"role": "system", "content": "You are a tenant. Answer only with the JSON object the schema asks for."},
            {"role": "user", "content": "Listing 2 asks $900 a month and was inspected as sound; its cost to the landlord is "
                                        "at least $820. Make one offer: decision offer, the listing id, and a rent."}]


def probe(campaign_id: str) -> dict:
    contract = pc.load_contract(pc.DEFAULT_CONTRACT.with_name(f"{campaign_id}.json"))
    model, route = pc.ROUTES[contract["route"]["route_id"]]
    controls = contract["controls"]
    body = {"model": model, "seed": controls["tenant_inference_seed_base"], "max_tokens": 4096,
            "provider": {"only": [route.provider], "quantizations": [route.quantization], "allow_fallbacks": False,
                         "require_parameters": True},  # as the kernel's client sends it (HL-J-15)
            "reasoning": {"effort": controls["reasoning_effort"]},
            "response_format": {"type": "json_schema", "json_schema": {"name": "tenant_move", "strict": True, "schema": SCHEMA}},
            "messages": MESSAGES}
    if controls["temperature"] != "unavailable":
        body["temperature"] = controls["temperature"]
    if controls["top_p"] is not None:
        body["top_p"] = controls["top_p"]
    request = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + os.environ["OPENROUTER_API_KEY"],
                                              "Content-Type": "application/json"})
    record = {"campaign_id": campaign_id, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "request": body, "route_pin": {"provider": route.provider, "quantization": route.quantization,
                                             "canonical_model": route.canonical_model}}
    try:
        response = json.load(urllib.request.urlopen(request, timeout=300))
    except urllib.error.HTTPError as error:
        record.update(status="refused", http_status=error.code, detail=error.read()[:400].decode("utf-8", "replace"))
        return record
    text = response["choices"][0]["message"].get("content") or ""
    try:
        value = json.loads(text)
        parsed = isinstance(value, dict) and set(value) == set(SCHEMA["required"])
    except json.JSONDecodeError:
        parsed = False
    usage = response.get("usage") or {}
    record.update(status="answered", served_provider=response.get("provider"), served_model=response.get("model"),
                  structured_output_ok=parsed, usage={"prompt_tokens": usage.get("prompt_tokens"),
                                                      "completion_tokens": usage.get("completion_tokens"),
                                                      "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
                                                      "cost_usd": usage.get("cost")})
    return record


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for campaign_id in sys.argv[1:]:
        record = probe(campaign_id)
        (OUT / f"{campaign_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
        print(json.dumps({k: record.get(k) for k in ("campaign_id", "status", "served_provider", "structured_output_ok", "usage")}))
