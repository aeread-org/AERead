"""
Shared LLM agent infrastructure for the sprint demos.

Uses OpenAI SDK pointed at OpenRouter (compatible API endpoint that fronts
multiple frontier models — Anthropic / OpenAI / Google / Qwen / etc.).

Features:
- temperature=0 for determinism
- on-disk response cache by prompt hash → reruns are free + reproducible
- defaults to a smart-but-affordable model; configurable per-call
- automatic price/choice parsing helpers

Env vars expected (set via shell rc or .env loader):
- OPENAI_API_KEY: OpenRouter key (sk-or-v1-...)
- OPENAI_BASE_URL: https://openrouter.ai/api/v1 (auto-set if missing)
- OPENAI_GPT5_REASONING_EFFORT: optional direct-OpenAI GPT-5.x effort
  ("none", "low", "medium", or "high")
- OPENAI_GPT5_MIN_COMPLETION_TOKENS: optional lower bound for direct GPT-5.x
  max_completion_tokens when a task needs extra reasoning headroom
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from openai import OpenAI
except ImportError as e:
    raise RuntimeError(
        "openai SDK required. `pip install openai` (already in python310 env)."
    ) from e


# ============================================================
# Defaults
# ============================================================

DEFAULT_MODEL = "anthropic/claude-sonnet-4.6"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_CACHE_DIR = Path(os.environ.get("AEREAD_CACHE_DIR")
                        or Path(__file__).parent / ".cache" / "llm_responses")
DEFAULT_TIMEOUT = 180  # seconds (GPT-5.x reasoning calls can exceed 60s)

# Transient-error backoff. Launch-day provider overloads (HF Inference Providers,
# z.ai free tier) return 429/5xx; retry those with exponential backoff. Never retry
# a billing/auth error (e.g. z.ai code 1113 "insufficient balance") — backoff can't fix it.
_RETRY_TRIES = int(os.environ.get("LLM_RETRY_TRIES", "6"))
_RETRY_BASE_DELAY = float(os.environ.get("LLM_RETRY_BASE_DELAY", "4"))  # seconds
_RETRY_MAX_DELAY = float(os.environ.get("LLM_RETRY_MAX_DELAY", "60"))


def _is_retryable_error(err: Exception) -> bool:
    msg = str(err).lower()
    # Billing / auth / bad-request — retry is pointless.
    for stop in ("1113", "insufficient balance", "no resource package",
                 "invalid api key", "401", "403", "unauthorized", "1211", "unknown model"):
        if stop in msg:
            return False
    markers = ("429", "rate limit", "rate-limit", "ratelimit", "overloaded", "1305",
               "temporarily", "try again", "timeout", "timed out", "500", "502",
               "503", "529", "service unavailable", "bad gateway", "gateway timeout",
               # transient empty/malformed provider body (OpenRouter under load)
               "no json object", "expecting value")
    return any(m in msg for m in markers)


def _with_retry(fn):
    """Call ``fn`` with exponential backoff on transient provider errors."""
    last: Optional[Exception] = None
    for attempt in range(_RETRY_TRIES):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — provider SDKs raise varied types
            last = e
            if attempt == _RETRY_TRIES - 1 or not _is_retryable_error(e):
                raise
            delay = min(_RETRY_BASE_DELAY * (2 ** attempt), _RETRY_MAX_DELAY)
            time.sleep(delay)
    assert last is not None  # pragma: no cover
    raise last


def _is_openrouter_transport_error(err: Exception) -> bool:
    """Return true for SDK/httpx transport failures worth retrying via raw HTTP."""

    text = f"{type(err).__name__}: {err}".lower()
    markers = (
        "apiconnectionerror",
        "connecterror",
        "connection error",
        "nodename nor servname",
        "name or service not known",
        "temporary failure in name resolution",
    )
    return any(marker in text for marker in markers)


# ============================================================
# Client + cache
# ============================================================


def _get_client() -> OpenAI:
    """Construct an OpenAI client pointed at OpenRouter."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Run with the OpenRouter key in env "
            "(see ~/.zshrc for the qwen alias as a reference)."
        )
    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=DEFAULT_TIMEOUT,
        default_headers={"Authorization": f"Bearer {api_key}"},
    )


def _post_chat_completions_raw(
    api_key: str,
    base_url: str,
    payload: dict,
) -> dict[str, Any]:
    """Direct OpenRouter-compatible chat/completions call.

    Some local OpenAI SDK versions can fail to attach Authorization when pointed
    at OpenRouter. The raw path is deliberately tiny and preserves the same cache
    semantics as the SDK path.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("OPENROUTER_HTTP_REFERER", "http://localhost"),
            "X-OpenRouter-Title": os.environ.get("OPENROUTER_APP_TITLE", "aeread"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            obj = _parse_openrouter_body(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter HTTP {e.code}: {body}") from e
    return obj


def _parse_openrouter_body(raw: str) -> dict[str, Any]:
    """Parse a chat/completions body that may be padded with SSE artifacts.

    During long reasoning waits OpenRouter interleaves SSE keep-alive comment lines
    (": OPENROUTER PROCESSING") and may emit the payload as ``data:`` chunks. A naive
    json.loads chokes on these (the symptom: heavy reasoners like GLM-5.2 / Kimi crash
    with JSONDecodeError while faster models parse fine). Recover the JSON robustly.
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Drop SSE comment/keep-alive lines (start with ":") and blanks, then reparse.
    kept = [ln for ln in raw.splitlines() if ln.strip() and not ln.lstrip().startswith(":")]
    cleaned = "\n".join(kept).strip()
    if cleaned and not cleaned.lstrip().startswith("data:"):
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    # Streaming fallback: assemble ``data: {...}`` chunks into a single completion.
    assembled: dict[str, Any] = {}
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    for ln in kept:
        s = ln.strip()
        if s.startswith("data:"):
            s = s[5:].strip()
        if not s or s == "[DONE]":
            continue
        try:
            chunk = json.loads(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(chunk, dict):
            continue
        if chunk.get("usage"):
            assembled["usage"] = chunk["usage"]
        for ch in chunk.get("choices", []) or []:
            delta = ch.get("delta") or ch.get("message") or {}
            if delta.get("content"):
                content_parts.append(delta["content"])
            if delta.get("reasoning"):
                reasoning_parts.append(delta["reasoning"])
        # a non-stream object that already carries a full message wins outright
        if any((c.get("message") or {}).get("content") for c in chunk.get("choices", []) or []):
            return chunk
    if content_parts or assembled:
        assembled["choices"] = [{"message": {"content": "".join(content_parts),
                                             "reasoning": "".join(reasoning_parts)}}]
        return assembled
    # Last resort: first '{' .. last '}'.
    i, j = raw.find("{"), raw.rfind("}")
    if i != -1 and j > i:
        return json.loads(raw[i:j + 1])
    raise json.JSONDecodeError("no JSON object in OpenRouter body", raw, 0)


def _hash_prompt(model: str, system: str, user: str, options: Optional[dict[str, Any]] = None) -> str:
    payload = json.dumps(
        {"m": model, "s": system, "u": user, "o": options or {}},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cache_path(cache_dir: Path, key: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{key}.json"


def _gpt5_completion_token_budget(max_tokens: int) -> int:
    floor = os.environ.get("OPENAI_GPT5_MIN_COMPLETION_TOKENS")
    if not floor:
        return max_tokens
    try:
        floor_value = int(floor)
    except ValueError as e:
        raise RuntimeError("OPENAI_GPT5_MIN_COMPLETION_TOKENS must be an integer") from e
    return max(max_tokens, floor_value)


def _openrouter_completion_token_budget(max_tokens: int) -> int:
    """Reasoning headroom for OpenRouter models (2026-08-01 mute audit).

    Reasoning-style models (deepseek-v4-flash, minimax-m3, glm-4.7-flash, ...)
    spend completion budget on reasoning tokens BEFORE emitting content; with
    the raw per-phase caps (800/1200) the content comes back empty and lands
    in the arena as a silent no-op turn. Mirrors the gpt-5 floor: set
    OPENROUTER_MIN_COMPLETION_TOKENS to lift every OpenRouter call's budget
    to at least that value. Unset = legacy behavior.
    """
    floor = os.environ.get("OPENROUTER_MIN_COMPLETION_TOKENS")
    if not floor:
        return max_tokens
    try:
        floor_value = int(floor)
    except ValueError as e:
        raise RuntimeError("OPENROUTER_MIN_COMPLETION_TOKENS must be an integer") from e
    return max(max_tokens, floor_value)


def _model_price_env_key(model: str, side: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_").upper()
    return f"LLM_PRICE_{normalized}_{side}_PER_1M"


def _usage_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _usage_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _usage_attr(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _normalize_openai_usage(usage: Any) -> Optional[dict[str, Any]]:
    if usage is None:
        return None
    input_tokens = _usage_int(_usage_attr(usage, "prompt_tokens"))
    output_tokens = _usage_int(_usage_attr(usage, "completion_tokens"))
    total_tokens = _usage_int(_usage_attr(usage, "total_tokens")) or input_tokens + output_tokens
    input_details = _usage_attr(usage, "prompt_tokens_details")
    cached_input_tokens = _usage_int(_usage_attr(input_details, "cached_tokens"))
    details = _usage_attr(usage, "completion_tokens_details")
    reasoning_tokens = _usage_int(_usage_attr(details, "reasoning_tokens"))
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


def _normalize_usage(usage: Any) -> Optional[dict[str, Any]]:
    if usage is None:
        return None
    if isinstance(usage, dict) and {"input_tokens", "output_tokens", "total_tokens"}.issubset(usage):
        normalized = {
            "input_tokens": _usage_int(usage.get("input_tokens")),
            "cached_input_tokens": _usage_int(usage.get("cached_input_tokens")),
            "output_tokens": _usage_int(usage.get("output_tokens")),
            "total_tokens": _usage_int(usage.get("total_tokens")),
            "reasoning_tokens": _usage_int(usage.get("reasoning_tokens")),
        }
        if "context_cache_storage_token_hours" in usage:
            normalized["context_cache_storage_token_hours"] = _usage_float(
                usage.get("context_cache_storage_token_hours")
            )
        return normalized
    return _normalize_openai_usage(usage)


def _provider_cache_hit_rate(usage: Optional[dict[str, Any]]) -> Optional[float]:
    if not usage or not usage.get("input_tokens"):
        return None
    return round(usage.get("cached_input_tokens", 0) / usage["input_tokens"], 6)


def _estimate_cost_usd(
    model: str,
    usage: Optional[dict[str, Any]],
    cached: bool = False,
    price_mode_override: Optional[str] = None,
) -> tuple[Optional[float], str]:
    if cached:
        return 0.0, "cache hit; no API cost for this call"
    if not usage:
        return None, "usage unavailable; cost not estimated"
    price_mode = (price_mode_override or os.environ.get("LLM_PRICE_MODE", "")).strip().upper()
    input_key = _model_price_env_key(model, "INPUT")
    output_key = _model_price_env_key(model, "OUTPUT")
    cached_input_key = _model_price_env_key(model, "CACHED_INPUT")
    normalized_model = re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_").upper()
    storage_key = f"LLM_PRICE_{normalized_model}_CACHE_STORAGE_PER_1M_TOKEN_HOUR"
    if price_mode:
        mode_input_key = f"LLM_PRICE_{normalized_model}_{price_mode}_INPUT_PER_1M"
        mode_cached_input_key = f"LLM_PRICE_{normalized_model}_{price_mode}_CACHED_INPUT_PER_1M"
        mode_output_key = f"LLM_PRICE_{normalized_model}_{price_mode}_OUTPUT_PER_1M"
        mode_storage_key = f"LLM_PRICE_{normalized_model}_{price_mode}_CACHE_STORAGE_PER_1M_TOKEN_HOUR"
        input_key_candidates = [mode_input_key, input_key, "LLM_PRICE_INPUT_PER_1M"]
        cached_input_key_candidates = [
            mode_cached_input_key,
            cached_input_key,
            "LLM_PRICE_CACHED_INPUT_PER_1M",
        ]
        output_key_candidates = [mode_output_key, output_key, "LLM_PRICE_OUTPUT_PER_1M"]
        storage_key_candidates = [
            mode_storage_key,
            storage_key,
            "LLM_PRICE_CACHE_STORAGE_PER_1M_TOKEN_HOUR",
        ]
    else:
        input_key_candidates = [input_key, "LLM_PRICE_INPUT_PER_1M"]
        cached_input_key_candidates = [cached_input_key, "LLM_PRICE_CACHED_INPUT_PER_1M"]
        output_key_candidates = [output_key, "LLM_PRICE_OUTPUT_PER_1M"]
        storage_key_candidates = [storage_key, "LLM_PRICE_CACHE_STORAGE_PER_1M_TOKEN_HOUR"]
    input_rate = next((os.environ[k] for k in input_key_candidates if os.environ.get(k) is not None), None)
    cached_input_rate = next(
        (os.environ[k] for k in cached_input_key_candidates if os.environ.get(k) is not None),
        None,
    )
    output_rate = next((os.environ[k] for k in output_key_candidates if os.environ.get(k) is not None), None)
    storage_rate = next((os.environ[k] for k in storage_key_candidates if os.environ.get(k) is not None), None)
    if input_rate is None or output_rate is None:
        return None, f"set {input_key_candidates[0]} and {output_key_candidates[0]} to estimate cost"
    cached_input_tokens = min(usage.get("cached_input_tokens", 0), usage["input_tokens"])
    uncached_input_tokens = usage["input_tokens"] - cached_input_tokens
    cached_rate = float(cached_input_rate) if cached_input_rate is not None else float(input_rate)
    cost = (
        uncached_input_tokens * float(input_rate)
        + cached_input_tokens * cached_rate
        + usage["output_tokens"] * float(output_rate)
    ) / 1_000_000
    note_extra = ""
    storage_token_hours = _usage_float(usage.get("context_cache_storage_token_hours"))
    if storage_token_hours and storage_rate is not None:
        cost += storage_token_hours * float(storage_rate) / 1_000_000
        note_extra = ", including context-cache storage"
    mode_text = f" {price_mode}" if price_mode else ""
    return round(cost, 10), f"estimated from configured{mode_text} per-1M token prices{note_extra}"


@dataclass(frozen=True)
class LLMResponse:
    model: str
    text: str
    cached: bool
    usage: Optional[dict[str, Any]] = None
    estimated_cost_usd: Optional[float] = None
    cost_note: str = ""
    provider_cache_hit_rate: Optional[float] = None
    # Provider-RESOLVED model version (e.g. "gpt-4o-mini-2024-07-18", Gemini's
    # modelVersion), vs `model` which echoes the REQUEST string. A pinned model
    # string can silently update server-side; recording the resolved version is
    # what makes re-recordings comparable and drift visible. None when the
    # provider (or an old cache entry) doesn't report one.
    resolved_model: Optional[str] = None


# ============================================================
# Run-recording hooks (exchange v1 runner: manifest + replay)
# ============================================================
#
# Additive, default-off instrumentation at the single LLM funnel. The v1 runner
# uses these for its inference manifest (D8) and record/replay:
# - a call OBSERVER notified once per completed call on every provider path
#   (OpenRouter / direct OpenAI / native Gemini, single or batch) — used to
#   verify funnel completeness (nothing reaches a model except through here);
# - a REPLAY mode: when a replay dir is set, calls are served exclusively from
#   run-local snapshot files and a miss raises ReplayCacheMiss BEFORE any
#   provider dispatch (replay must never touch the network).
#
# The replay key deliberately differs from the live cache key: the live key
# folds in env-specific options (base_url, reasoning-effort env vars) so caches
# never collide across setups, while the replay key is a pure function of
# (model, system, user, max_tokens, temperature, sample) so a recorded run
# replays on any machine regardless of provider environment.


class ReplayCacheMiss(RuntimeError):
    """A replayed run required an LLM response that was not recorded."""


# Per-run hook state is CONTEXT-LOCAL (contextvars), not process-global: a parallel
# sweep runs many arena runs in one process (one thread each), and a process-global
# observer/replay dir would cross-contaminate their manifests and funnel accounting.
# Threads start from an empty context, so each run thread's set_* is isolated to it.
_call_observer_var: "contextvars.ContextVar[Optional[Callable[[dict[str, Any]], None]]]" = (
    contextvars.ContextVar("llm_call_observer", default=None)
)
_replay_dir_var: "contextvars.ContextVar[Optional[Path]]" = contextvars.ContextVar(
    "llm_replay_dir", default=None
)


def set_call_observer(
    observer: Optional[Callable[[dict[str, Any]], None]],
) -> Optional[Callable[[dict[str, Any]], None]]:
    """Install (or clear with None) the per-call observer; returns the previous one."""
    previous = _call_observer_var.get()
    _call_observer_var.set(observer)
    return previous


def set_replay_dir(path: Optional[Path | str]) -> Optional[Path]:
    """Serve calls exclusively from snapshot files in ``path`` (None = live mode)."""
    previous = _replay_dir_var.get()
    _replay_dir_var.set(Path(path) if path is not None else None)
    return previous


def get_replay_dir() -> Optional[Path]:
    """The active replay dir, or None in live mode (for replay-aware policies)."""
    return _replay_dir_var.get()


def compute_replay_key(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    sample: int,
) -> str:
    payload = json.dumps(
        {"m": model, "s": system, "u": user, "mt": int(max_tokens),
         "t": float(temperature), "n": int(sample)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def write_response_snapshot(directory: Path, key: str, response: "LLMResponse") -> Path:
    """Persist one response as ``<key>.json`` (same content shape as the live cache).

    Atomic (temp file + rename): a crash mid-write must surface on replay as a
    clean ReplayCacheMiss, never as a JSONDecodeError on a truncated file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{key}.json"
    tmp = directory / f"{key}.json.tmp"
    tmp.write_text(
        json.dumps(
            {
                "model": response.model,
                "text": response.text,
                "usage": response.usage,
                "estimated_cost_usd": response.estimated_cost_usd,
                "cost_note": response.cost_note,
                "resolved_model": response.resolved_model,
            },
            indent=2,
        )
    )
    os.replace(tmp, path)
    return path


def _notify_observer(
    response: "LLMResponse",
    *,
    system: str,
    user: str,
    replay_key: str,
    provider_path: str,
    max_tokens: int,
    temperature: float,
    sample: int,
) -> None:
    observer = _call_observer_var.get()
    if observer is None:
        return
    observer(
        {
            "model": response.model,
            "resolved_model": response.resolved_model,
            "system": system,
            "user": user,
            "text": response.text,
            "cached": response.cached,
            "usage": response.usage,
            "estimated_cost_usd": response.estimated_cost_usd,
            "cost_note": response.cost_note,
            "replay_key": replay_key,
            "provider_path": provider_path,
            "params": {
                "max_tokens": int(max_tokens),
                "temperature": float(temperature),
                "sample": int(sample),
            },
        }
    )


def _serve_from_replay_dir(
    key: str,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
    sample: int,
) -> "LLMResponse":
    replay_dir = _replay_dir_var.get()
    assert replay_dir is not None
    path = replay_dir / f"{key}.json"
    if not path.is_file():
        raise ReplayCacheMiss(
            f"replay miss: no snapshot {key}.json in {replay_dir} "
            f"(model={model}, prompt starts: {user[:80]!r})"
        )
    snapshot = json.loads(path.read_text())
    usage = _normalize_usage(snapshot.get("usage"))
    response = LLMResponse(
        model=snapshot.get("model", model),
        text=snapshot["text"],
        cached=True,
        usage=usage,
        estimated_cost_usd=0.0,
        cost_note="replay; served from recorded snapshot",
        provider_cache_hit_rate=_provider_cache_hit_rate(usage),
        resolved_model=snapshot.get("resolved_model"),
    )
    _notify_observer(
        response,
        system=system,
        user=user,
        replay_key=key,
        provider_path="replay",
        max_tokens=max_tokens,
        temperature=temperature,
        sample=sample,
    )
    return response


def _import_call_gemini_batch():
    from aeread.gemini_llm import call_gemini_batch
    return call_gemini_batch


def call_llm(
    system: str,
    user: str,
    model: str = DEFAULT_MODEL,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    sample: int = 0,
) -> LLMResponse:
    """Call the LLM (with on-disk response cache by prompt hash).

    Defaults: temperature=0 (deterministic). For stochastic multi-sampling pass
    temperature>0 and a distinct `sample` index per draw — both are folded into
    the cache key ONLY when non-default, so existing temperature=0 caches are
    preserved bit-for-bit. cache means reruns are free + reproducible.
    """
    replay_key = compute_replay_key(model, system, user, max_tokens, temperature, sample)
    if _replay_dir_var.get() is not None:
        return _serve_from_replay_dir(
            replay_key, model, system, user, max_tokens, temperature, sample
        )

    # Standardize gemini-* on the native Gemini path (AI Studio free key or Vertex paid token).
    if model.split("/")[-1].startswith("gemini") and (os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_VERTEX")):
        from aeread.gemini_llm import call_gemini
        salt = "" if (temperature == 0.0 and sample == 0) else f"{temperature};{sample}"
        r = call_gemini(system, user, model=model, max_tokens=max_tokens, temperature=temperature, cache_salt=salt)
        cached = bool(getattr(r, "cached", False))
        usage = _normalize_usage(getattr(r, "usage", None))
        cost, note = _estimate_cost_usd(model, usage, cached=cached)
        response = LLMResponse(
            model=model,
            text=r.text,
            cached=cached,
            usage=usage,
            estimated_cost_usd=cost,
            cost_note=note,
            provider_cache_hit_rate=_provider_cache_hit_rate(usage),
            resolved_model=getattr(r, "model_version", None),
        )
        _notify_observer(
            response,
            system=system,
            user=user,
            replay_key=replay_key,
            provider_path="gemini_native",
            max_tokens=max_tokens,
            temperature=temperature,
            sample=sample,
        )
        return response

    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ.get("OPENAI_API_KEY")
    if "gpt-5" in model.lower():
        effective_budget = _gpt5_completion_token_budget(max_tokens)
    elif "openrouter.ai" in base_url:
        effective_budget = _openrouter_completion_token_budget(max_tokens)
    else:
        effective_budget = max_tokens
    gpt5_budget = effective_budget  # gpt-5 branch alias (kept for clarity below)
    cache_options = {
        "base_url": base_url.rstrip("/"),
        "max_tokens": max_tokens,
        "effective_completion_tokens": effective_budget,
        "temperature": temperature,
        "sample": sample,
        "openai_gpt5_reasoning_effort": os.environ.get("OPENAI_GPT5_REASONING_EFFORT") if "gpt-5" in model.lower() else None,
        "openrouter_reasoning_effort": os.environ.get("OPENROUTER_REASONING_EFFORT") if "openrouter.ai" in base_url else None,
    }
    key = _hash_prompt(model, system, user, cache_options)
    path = _cache_path(cache_dir, key)

    if path.exists():
        cached = json.loads(path.read_text())
        if str(cached.get("text", "")).strip():
            usage = _normalize_usage(cached.get("usage"))
            cost, note = _estimate_cost_usd(cached["model"], usage, cached=True)
            response = LLMResponse(
                model=cached["model"],
                text=cached["text"],
                cached=True,
                usage=usage,
                estimated_cost_usd=cost,
                cost_note=note,
                provider_cache_hit_rate=_provider_cache_hit_rate(usage),
                resolved_model=cached.get("resolved_model"),
            )
            _notify_observer(
                response,
                system=system,
                user=user,
                replay_key=replay_key,
                provider_path="disk_cache",
                max_tokens=max_tokens,
                temperature=temperature,
                sample=sample,
            )
            return response
        path.unlink()

    create_kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    if "openrouter.ai" in base_url and api_key:
        # Slow reasoners (GLM-5.2, Kimi) make OpenRouter pad the response with SSE keep-alive
        # comment lines (": OPENROUTER PROCESSING"). Two layers fail on this: raw urllib's
        # chunked reader ("int base 16: b''") AND the SDK's httpx .json() (naive json.loads ->
        # "Expecting value"). Fix: use the SDK for correct chunked TRANSPORT (with_raw_response),
        # but PARSE the body ourselves with the comment-stripping _parse_openrouter_body.
        create_kwargs["temperature"] = temperature
        create_kwargs["max_tokens"] = effective_budget
        _xb: dict[str, Any] = {}
        if os.environ.get("OPENROUTER_REASONING_EFFORT"):
            _xb["reasoning"] = {"effort": os.environ["OPENROUTER_REASONING_EFFORT"]}
        # Spread load across upstream providers to dodge a single provider's rate
        # limit (e.g. deepseek-v4-flash has 19 endpoints; the default pins the
        # cheapest, which 429s under sweep load). OPENROUTER_ALLOW_FALLBACKS=1 lets
        # OpenRouter fail over; OPENROUTER_PROVIDER_SORT (throughput|price|latency)
        # picks the routing preference.
        if os.environ.get("OPENROUTER_ALLOW_FALLBACKS") or os.environ.get("OPENROUTER_PROVIDER_SORT"):
            prov: dict[str, Any] = {"allow_fallbacks": True}
            if os.environ.get("OPENROUTER_PROVIDER_SORT"):
                prov["sort"] = os.environ["OPENROUTER_PROVIDER_SORT"]
            _xb["provider"] = prov
        if _xb:
            create_kwargs["extra_body"] = _xb
        client = _get_client()

        def _openrouter_call() -> dict[str, Any]:
            raw = client.chat.completions.with_raw_response.create(**create_kwargs)
            return _parse_openrouter_body(raw.text)

        def _raw_openrouter_call() -> dict[str, Any]:
            payload = dict(create_kwargs)
            extra_body = payload.pop("extra_body", None)
            if isinstance(extra_body, dict):
                payload.update(extra_body)
            return _post_chat_completions_raw(api_key, base_url, payload)

        def _openrouter_attempt() -> tuple[str, Any, Any]:
            try:
                obj = _with_retry(_openrouter_call)
            except Exception as e:
                if not _is_openrouter_transport_error(e):
                    raise
                obj = _with_retry(_raw_openrouter_call)
            choice0 = (obj.get("choices") or [{}])[0]
            t = (choice0.get("message") or {}).get("content") or choice0.get("text") or ""
            return t, _normalize_openai_usage(obj.get("usage")), obj.get("model")

        text, usage, resolved_model = _openrouter_attempt()
        if not text.strip():
            # Mute guard (2026-08-01 audit): empty content is NOT an error to
            # the SDK — reasoning consumed the completion budget, or OpenRouter
            # returned an HTTP-200 error body with no choices. One retry with
            # an escalated budget; the outcome (still-empty included) is what
            # gets recorded.
            create_kwargs["max_tokens"] = max(effective_budget * 2, 8192)
            text, usage, resolved_model = _openrouter_attempt()
            if isinstance(usage, dict):
                usage["empty_retry"] = 1
    elif "gpt-5" in model.lower():
        # OpenAI GPT-5.x reasoning models (direct OpenAI API): use
        # `max_completion_tokens` (they reject `max_tokens`) and the default
        # temperature (they reject temperature != 1). Reasoning tokens count
        # toward the budget; callers can set OPENAI_GPT5_MIN_COMPLETION_TOKENS
        # when a task needs extra headroom.
        create_kwargs["max_completion_tokens"] = gpt5_budget
        reasoning_effort = os.environ.get("OPENAI_GPT5_REASONING_EFFORT")
        if reasoning_effort:
            create_kwargs["reasoning_effort"] = reasoning_effort
        client = _get_client()
        response = _with_retry(lambda: client.chat.completions.create(**create_kwargs))
        text = response.choices[0].message.content or ""
        usage = _normalize_openai_usage(getattr(response, "usage", None))
        resolved_model = getattr(response, "model", None)
    else:
        # Anthropic/other via OpenRouter: temperature configurable (default 0).
        create_kwargs["temperature"] = temperature
        create_kwargs["max_tokens"] = max_tokens
        client = _get_client()
        response = _with_retry(lambda: client.chat.completions.create(**create_kwargs))
        text = response.choices[0].message.content or ""
        usage = _normalize_openai_usage(getattr(response, "usage", None))
        resolved_model = getattr(response, "model", None)

    cost, note = _estimate_cost_usd(model, usage, cached=False)
    if text.strip():
        path.write_text(
            json.dumps(
                {
                    "model": model,
                    "text": text,
                    "usage": usage,
                    "estimated_cost_usd": cost,
                    "cost_note": note,
                    "resolved_model": resolved_model,
                },
                indent=2,
            )
        )
    response = LLMResponse(
        model=model,
        text=text,
        cached=False,
        usage=usage,
        estimated_cost_usd=cost,
        cost_note=note,
        provider_cache_hit_rate=_provider_cache_hit_rate(usage),
        resolved_model=resolved_model,
    )
    _notify_observer(
        response,
        system=system,
        user=user,
        replay_key=replay_key,
        provider_path="gpt5_direct" if "gpt-5" in model.lower() else "openrouter",
        max_tokens=max_tokens,
        temperature=temperature,
        sample=sample,
    )
    return response


def call_llm_batch(
    requests: list[dict[str, Any]],
    model: str = DEFAULT_MODEL,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    poll_interval: Optional[float] = None,
) -> list[LLMResponse]:
    """Call independent LLM requests, using provider batch when available.

    Requests are dictionaries with `system`, `user`, and optional `max_tokens`,
    `temperature`, and `sample`. Today the native provider batch path is Gemini;
    other providers fall back to sequential `call_llm`.
    """
    if not requests:
        return []
    # In replay mode fall through to the sequential path: call_llm serves every
    # request from the recorded snapshots (and hard-fails on a miss).
    if _replay_dir_var.get() is None and model.split("/")[-1].startswith("gemini") and os.environ.get("GEMINI_API_KEY") and not os.environ.get("GEMINI_VERTEX"):
        call_gemini_batch = _import_call_gemini_batch()
        gemini_requests = []
        for item in requests:
            temperature = float(item.get("temperature", 0.0))
            sample = int(item.get("sample", 0))
            gemini_requests.append(
                {
                    "system": item.get("system", ""),
                    "user": item["user"],
                    "max_tokens": int(item.get("max_tokens", 2048)),
                    "temperature": temperature,
                    "cache_salt": "" if (temperature == 0.0 and sample == 0) else f"{temperature};{sample}",
                }
            )
        raw = call_gemini_batch(
            gemini_requests,
            model=model,
            poll_interval=poll_interval,
        )
        responses = []
        for item, r in zip(requests, raw):
            cached = bool(getattr(r, "cached", False))
            usage = _normalize_usage(getattr(r, "usage", None))
            cost, note = _estimate_cost_usd(model, usage, cached=cached, price_mode_override="BATCH")
            response = LLMResponse(
                model=model,
                text=r.text,
                cached=cached,
                usage=usage,
                estimated_cost_usd=cost,
                cost_note=note,
                provider_cache_hit_rate=_provider_cache_hit_rate(usage),
                resolved_model=getattr(r, "model_version", None),
            )
            item_max_tokens = int(item.get("max_tokens", 2048))
            item_temperature = float(item.get("temperature", 0.0))
            item_sample = int(item.get("sample", 0))
            _notify_observer(
                response,
                system=item.get("system", ""),
                user=item["user"],
                replay_key=compute_replay_key(
                    model, item.get("system", ""), item["user"],
                    item_max_tokens, item_temperature, item_sample,
                ),
                provider_path="gemini_batch",
                max_tokens=item_max_tokens,
                temperature=item_temperature,
                sample=item_sample,
            )
            responses.append(response)
        return responses

    return [
        call_llm(
            item.get("system", ""),
            item["user"],
            model=model,
            cache_dir=cache_dir,
            max_tokens=int(item.get("max_tokens", 2048)),
            temperature=float(item.get("temperature", 0.0)),
            sample=int(item.get("sample", 0)),
        )
        for item in requests
    ]


# ============================================================
# Parsing helpers
# ============================================================


_PRICE_REGEX = re.compile(r"\$?\s*(\d+(?:\.\d+)?)")
_FINAL_PRICE_REGEX = re.compile(
    r"(?:final[_\s]price|answer|optimal[_\s]price|p\^?\*|p\s*=)[^\d$]*\$?\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_price(text: str) -> Optional[float]:
    """Extract a price from LLM response.

    Strategy:
    1. Look for explicit "final price / answer / p* = X" pattern → use that number
    2. Otherwise, return the LAST number in the text (chain-of-thought ends with answer)

    Returns None on parse failure.
    """
    matches = list(_FINAL_PRICE_REGEX.finditer(text))
    if matches:
        return float(matches[-1].group(1))
    numbers = list(_PRICE_REGEX.finditer(text))
    if numbers:
        return float(numbers[-1].group(1))
    return None


def parse_choice(text: str, valid_ids: list[str]) -> Optional[str]:
    """Extract a product_id from response, matching against a set of valid IDs.

    Looks for the first valid ID mentioned anywhere in the text.
    """
    # Normalize text
    normalized = text.lower()
    for vid in valid_ids:
        if vid.lower() in normalized:
            return vid
    return None
