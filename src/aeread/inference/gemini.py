"""Minimal Gemini-API backend (free-tier AI Studio key), call_llm-compatible.

Routes google/gemini-* models to the native generativelanguage REST endpoint using GEMINI_API_KEY
(an AIza... key), so harnesses can run gemini-family models without OpenRouter credits. Caches by
(model, system, user, temperature) hash so re-runs are free. Returns an object with a .text attribute.
"""
import os, json, time, hashlib, pathlib, urllib.request, urllib.error

_CACHE = pathlib.Path(os.environ.get("AEREAD_GEMINI_CACHE_DIR")
                      or pathlib.Path(os.path.dirname(os.path.abspath(__file__))) / ".gemini_cache")
_ALIAS = {}  # native API serves the real model IDs (incl. gemini-3.5-flash) — no aliasing
_CONTEXT_MARKER = "Viewer-specific contact context:"


class _R:
    def __init__(self, text, cached=False, usage=None, model_version=None):
        self.text = text
        self.cached = cached
        self.usage = usage
        # provider-resolved model version (the API's `modelVersion`), so a pinned
        # model string that silently updates is visible in run artifacts
        self.model_version = model_version


def _usage_from_metadata(meta: dict) -> dict:
    prompt = int(meta.get("promptTokenCount") or 0)
    cached = int(meta.get("cachedContentTokenCount") or 0)
    candidates = int(meta.get("candidatesTokenCount") or 0)
    thoughts = int(meta.get("thoughtsTokenCount") or 0)
    total = int(meta.get("totalTokenCount") or (prompt + candidates + thoughts))
    return {
        "input_tokens": prompt,
        "cached_input_tokens": cached,
        "output_tokens": candidates + thoughts,
        "total_tokens": total,
        "reasoning_tokens": thoughts,
    }


def _model_id(model: str) -> str:
    m = model.split("/")[-1]            # strip "google/"
    return _ALIAS.get(m, m)


def _text_from_generate_content_response(out: dict) -> str:
    txt = ""
    for c in out.get("candidates", []):
        for p in (c.get("content", {}) or {}).get("parts", []):
            if "text" in p:
                txt += p["text"]
    return txt


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _ttl_seconds(ttl: str) -> int:
    raw = ttl.strip().lower()
    if raw.endswith("s"):
        raw = raw[:-1]
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return 3600


def _cacheable_context_split(user: str):
    if not _truthy_env("GEMINI_CONTEXT_CACHE"):
        return None
    marker = os.environ.get("GEMINI_CONTEXT_CACHE_MARKER", _CONTEXT_MARKER)
    idx = user.find(marker)
    if idx <= 0:
        return None
    prefix = user[:idx]
    suffix = user[idx:]
    min_chars = int(os.environ.get("GEMINI_CONTEXT_CACHE_MIN_CHARS", "4000"))
    if len(prefix) < min_chars:
        return None
    return prefix, suffix


def _context_cache_path(mid: str, system: str, prefix: str, ttl: str) -> pathlib.Path:
    key = hashlib.sha256(json.dumps({
        "v": 1,
        "m": mid,
        "s": system,
        "prefix": prefix,
        "ttl": ttl,
    }, sort_keys=True).encode()).hexdigest()
    return _CACHE / f"context_{key}.json"


def _read_context_cache(path: pathlib.Path, ttl: str):
    if not path.exists():
        return None
    cached = json.loads(path.read_text())
    name = cached.get("name")
    created_at = float(cached.get("created_at") or 0)
    if not name:
        return None
    if time.time() - created_at > max(1, _ttl_seconds(ttl) - 60):
        return None
    return name


def _create_context_cache(mid: str, system: str, prefix: str, ttl: str, key: str):
    body = {
        "model": f"models/{mid}",
        "contents": [{"role": "user", "parts": [{"text": prefix}]}],
        "ttl": ttl,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/cachedContents",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        out = json.loads(urllib.request.urlopen(req, timeout=90).read())
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        if _truthy_env("GEMINI_CONTEXT_CACHE_STRICT"):
            raise
        return None
    return out.get("name")


def _context_cache_name(mid: str, system: str, prefix: str, ttl: str, key: str):
    _CACHE.mkdir(exist_ok=True)
    path = _context_cache_path(mid, system, prefix, ttl)
    name = _read_context_cache(path, ttl)
    if name:
        return name, path, False
    name = _create_context_cache(mid, system, prefix, ttl, key)
    if not name:
        return None, path, False
    path.write_text(json.dumps({"name": name, "created_at": time.time(), "ttl": ttl}))
    return name, path, True


def _generation_body(user: str, system: str, max_tokens: int, temperature: float, thinking_budget: int, cached_content=None):
    body = {
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens, "temperature": temperature,
            # default: thinking OFF (budget 0) so reasoning models emit a direct decision and
            # don't burn the token budget on a derivation. Set GEMINI_THINKING>0 to enable.
            "thinkingConfig": {"thinkingBudget": thinking_budget},
        },
    }
    if cached_content:
        body["cachedContent"] = cached_content
    else:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def _retry_sleep_seconds(attempt: int) -> float:
    base = float(os.environ.get("GEMINI_RETRY_BASE_DELAY", "15"))
    return base * (attempt + 1)


def _retryable_http_status(code: int) -> bool:
    return code == 429 or code in {500, 502, 503, 504}


def _urlopen_json_resilient(req, timeout: int = 90, attempts: int = 5):
    """urlopen + json.loads with retry on free-tier 429 and transient provider 5xx / network
    errors (mirrors the single-call path). Used by the batch create/poll calls so a long batch
    run is not killed by one transient HTTP 503."""
    for attempt in range(attempts):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if _retryable_http_status(e.code) and attempt < attempts - 1:
                time.sleep(_retry_sleep_seconds(attempt))
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt < attempts - 1:
                time.sleep(_retry_sleep_seconds(attempt))
                continue
            raise


def _response_cache_file(
    mid: str,
    system: str,
    user: str,
    temperature: float,
    cache_salt: str,
    max_tokens: int,
    thinking_budget: int,
    vertex: bool,
) -> pathlib.Path:
    h = hashlib.sha256(json.dumps({
        "v": 2,
        "m": mid,
        "s": system,
        "u": user,
        "t": temperature,
        "x": cache_salt,
        "max_tokens": max_tokens,
        "thinking_budget": thinking_budget,
        "vertex": vertex,
    }, sort_keys=True).encode()).hexdigest()
    return _CACHE / (h + ".json")


# Cross-run batch funnel (gemini_batch_pool.GeminiBatchPool.activated() installs it):
# when set, live AI-Studio calls route through one Batch API submission per flush
# instead of per-call HTTP. None = normal synchronous behavior.
_CROSSRUN_POOL = None


def call_gemini(system: str, user: str, model: str = "gemini-3.5-flash",
                max_tokens: int = 2000, temperature: float = 0.0, cache_salt: str = "",
                _bypass_pool: bool = False) -> _R:
    vertex = bool(os.environ.get("GEMINI_VERTEX") and os.environ.get("GOOGLE_ACCESS_TOKEN"))
    key = os.environ.get("GEMINI_API_KEY")
    if not key and not vertex:
        raise RuntimeError("set GEMINI_API_KEY (AI Studio free) or GEMINI_VERTEX=1 + GOOGLE_ACCESS_TOKEN (Vertex paid)")
    mid = _model_id(model)
    thinking_budget = int(os.environ.get("GEMINI_THINKING", "0"))
    cf = _response_cache_file(mid, system, user, temperature, cache_salt, max_tokens, thinking_budget, vertex)
    if cf.exists():
        cached = json.loads(cf.read_text())
        if str(cached.get("text", "")).strip():
            return _R(
                cached.get("text", ""),
                cached=True,
                usage=cached.get("usage"),
                model_version=cached.get("model_version"),
            )
        cf.unlink()
    if _CROSSRUN_POOL is not None and not vertex and not _bypass_pool:
        # live call under the lockstep orchestrator: block on the shared batch
        # (the batch path writes the same cache file this path would have written)
        return _CROSSRUN_POOL.submit(model, system, user, max_tokens, temperature, cache_salt)
    if vertex:   # Vertex AI (pay-as-you-go) via gcloud OAuth token; global endpoint serves gemini-3.5-flash
        proj = os.environ.get("GOOGLE_PROJECT", "")
        url = f"https://aiplatform.googleapis.com/v1/projects/{proj}/locations/global/publishers/google/models/{mid}:generateContent"
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + os.environ["GOOGLE_ACCESS_TOKEN"]}
    else:        # AI Studio API key (free tier)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
    context_path = None
    context_cache_created = False
    context_cache_ttl_seconds = 0
    split = None if vertex else _cacheable_context_split(user)
    if split:
        prefix, suffix = split
        ttl = os.environ.get("GEMINI_CONTEXT_CACHE_TTL", "3600s")
        context_cache_ttl_seconds = _ttl_seconds(ttl)
        context_name, context_path, context_cache_created = _context_cache_name(mid, system, prefix, ttl, key)
        body = _generation_body(
            suffix if context_name else user,
            system,
            max_tokens,
            temperature,
            thinking_budget,
            cached_content=context_name,
        )
    else:
        body = _generation_body(user, system, max_tokens, temperature, thinking_budget)
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    out = None
    fallback_without_context = False
    for attempt in range(5):                       # retry on free-tier 429 and transient provider 5xx
        try:
            out = json.loads(urllib.request.urlopen(req, timeout=90).read())
            break
        except urllib.error.HTTPError as e:
            if _retryable_http_status(e.code) and attempt < 4:
                time.sleep(_retry_sleep_seconds(attempt))
                continue
            if body.get("cachedContent") and not fallback_without_context and not _truthy_env("GEMINI_CONTEXT_CACHE_STRICT"):
                if context_path:
                    try:
                        context_path.unlink()
                    except FileNotFoundError:
                        pass
                context_cache_created = False
                context_cache_ttl_seconds = 0
                fallback_without_context = True
                body = _generation_body(user, system, max_tokens, temperature, thinking_budget)
                req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
                continue
            raise
        except (TimeoutError, urllib.error.URLError) as e:
            if attempt < 4:
                time.sleep(_retry_sleep_seconds(attempt))
                continue
            raise
    txt = _text_from_generate_content_response(out)
    usage = _usage_from_metadata(out.get("usageMetadata", {}))
    if context_cache_created:
        storage_tokens = usage.get("cached_input_tokens") or usage.get("input_tokens") or 0
        usage["context_cache_storage_token_hours"] = storage_tokens * context_cache_ttl_seconds / 3600
    model_version = out.get("modelVersion")
    _CACHE.mkdir(exist_ok=True)
    if txt.strip():
        cf.write_text(json.dumps({"text": txt, "usage": usage, "model_version": model_version}))
    time.sleep(float(os.environ.get("GEMINI_DELAY", "4")))   # pace under free-tier RPM (live calls only)
    return _R(txt, cached=False, usage=usage, model_version=model_version)


def _extract_inline_responses(batch_obj: dict) -> list[dict]:
    candidates = []
    if isinstance(batch_obj.get("response"), dict):
        candidates.append(batch_obj["response"])
    if isinstance(batch_obj.get("metadata"), dict):
        candidates.append(batch_obj["metadata"])
    candidates.append(batch_obj)
    for batch in candidates:
        output = batch.get("output") or batch.get("dest") or batch
        inline = output.get("inlinedResponses") or output.get("inlined_responses") or {}
        if isinstance(inline, list):
            return inline
        found = inline.get("inlinedResponses") or inline.get("inlined_responses") or []
        if found:
            return found
    return []


def _batch_complete(batch_obj: dict) -> bool:
    if batch_obj.get("done") is True:
        return True
    batch = batch_obj.get("response") or batch_obj
    return batch.get("state") in {
        "BATCH_STATE_SUCCEEDED",
        "BATCH_STATE_FAILED",
        "BATCH_STATE_CANCELLED",
        "BATCH_STATE_EXPIRED",
        "JOB_STATE_SUCCEEDED",
        "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED",
        "JOB_STATE_EXPIRED",
    }


def _batch_failed(batch_obj: dict) -> bool:
    if batch_obj.get("error"):
        return True
    batch = batch_obj.get("response") or batch_obj
    return batch.get("state") in {
        "BATCH_STATE_FAILED",
        "BATCH_STATE_CANCELLED",
        "BATCH_STATE_EXPIRED",
        "JOB_STATE_FAILED",
        "JOB_STATE_CANCELLED",
        "JOB_STATE_EXPIRED",
    }


def call_gemini_batch(
    requests: list[dict],
    model: str = "gemini-3.5-flash",
    poll_interval: float | None = None,
    display_name: str | None = None,
) -> list[_R]:
    """Run independent Gemini GenerateContent requests through Batch API.

    This only supports AI Studio API-key auth. Vertex batch handling uses a
    different file/job path, so callers should fall back to synchronous calls
    when GEMINI_VERTEX is enabled.
    """
    if not requests:
        return []
    if os.environ.get("GEMINI_VERTEX"):
        raise RuntimeError("Gemini Batch API path currently supports GEMINI_API_KEY, not GEMINI_VERTEX")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("set GEMINI_API_KEY for Gemini Batch API")
    mid = _model_id(model)
    thinking_budget = int(os.environ.get("GEMINI_THINKING", "0"))
    results: list[_R | None] = [None] * len(requests)
    pending: list[tuple[int, pathlib.Path, dict, bool, int]] = []

    for i, item in enumerate(requests):
        system = item.get("system", "")
        user = item["user"]
        max_tokens = int(item.get("max_tokens", 2000))
        temperature = float(item.get("temperature", 0.0))
        cache_salt = item.get("cache_salt", "")
        cf = _response_cache_file(mid, system, user, temperature, cache_salt, max_tokens, thinking_budget, False)
        if cf.exists():
            cached = json.loads(cf.read_text())
            if str(cached.get("text", "")).strip():
                results[i] = _R(
                    cached.get("text", ""),
                    cached=True,
                    usage=cached.get("usage"),
                    model_version=cached.get("model_version"),
                )
                continue
            cf.unlink()

        context_cache_created = False
        context_cache_ttl_seconds = 0
        split = _cacheable_context_split(user)
        if split:
            prefix, suffix = split
            ttl = os.environ.get("GEMINI_CONTEXT_CACHE_TTL", "3600s")
            context_cache_ttl_seconds = _ttl_seconds(ttl)
            context_name, context_path, context_cache_created = _context_cache_name(mid, system, prefix, ttl, key)
            body = _generation_body(
                suffix if context_name else user,
                system,
                max_tokens,
                temperature,
                thinking_budget,
                cached_content=context_name,
            )
        else:
            body = _generation_body(user, system, max_tokens, temperature, thinking_budget)
        pending.append((i, cf, body, context_cache_created, context_cache_ttl_seconds))

    if not pending:
        return [r for r in results if r is not None]

    inline_requests = [
        {"request": body, "metadata": {"key": f"req-{pos}"}}
        for pos, (_idx, _cf, body, _created, _ttl) in enumerate(pending)
    ]
    batch_body = {
        "batch": {
            "display_name": display_name or f"aeread-{int(time.time())}",
            "input_config": {"requests": {"requests": inline_requests}},
        }
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{mid}:batchGenerateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(batch_body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    batch_obj = _urlopen_json_resilient(req)
    job_name = batch_obj.get("name") or (batch_obj.get("response") or {}).get("name")
    if not job_name:
        raise RuntimeError(f"Gemini batch create returned no job name: {batch_obj}")

    poll_sleep = float(os.environ.get("GEMINI_BATCH_POLL_INTERVAL", "30")) if poll_interval is None else poll_interval
    deadline = time.time() + float(os.environ.get("GEMINI_BATCH_TIMEOUT", "7200"))
    while not _batch_complete(batch_obj):
        if time.time() > deadline:
            raise TimeoutError(f"Gemini batch job timed out: {job_name}")
        time.sleep(poll_sleep)
        get_req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/{job_name}",
            headers={"x-goog-api-key": key},
        )
        batch_obj = _urlopen_json_resilient(get_req)
    if _batch_failed(batch_obj):
        raise RuntimeError(f"Gemini batch job failed: {batch_obj}")

    inline_responses = _extract_inline_responses(batch_obj)
    if len(inline_responses) != len(pending):
        raise RuntimeError(f"Gemini batch returned {len(inline_responses)} responses for {len(pending)} requests")
    for pos, inline_response in enumerate(inline_responses):
        if inline_response.get("error"):
            raise RuntimeError(f"Gemini batch request failed: {inline_response['error']}")
        response = inline_response.get("response") or {}
        txt = _text_from_generate_content_response(response)
        usage = _usage_from_metadata(response.get("usageMetadata", {}))
        idx, cf, _body, context_cache_created, context_cache_ttl_seconds = pending[pos]
        if context_cache_created:
            storage_tokens = usage.get("cached_input_tokens") or usage.get("input_tokens") or 0
            usage["context_cache_storage_token_hours"] = storage_tokens * context_cache_ttl_seconds / 3600
        model_version = response.get("modelVersion")
        if txt.strip():
            _CACHE.mkdir(exist_ok=True)
            cf.write_text(json.dumps({"text": txt, "usage": usage, "model_version": model_version}))
        results[idx] = _R(txt, cached=False, usage=usage, model_version=model_version)
    return [r for r in results if r is not None]
