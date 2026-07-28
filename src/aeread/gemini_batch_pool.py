"""Cross-run Gemini batch pool — the lockstep orchestrator's funnel (50% batch pricing).

Many arena runs execute concurrently (one thread each; per-run hook state is
context-local in llm_agent). Each run's live gemini call, instead of opening its own
HTTP request, enqueues here and blocks; a flusher thread drains the queue every
``flush_interval`` seconds (or at ``max_batch`` items) and submits ONE
``call_gemini_batch`` job per model group. Wall-clock per run stays sequential-shaped
(a run waits per call), but every flush carries up to one call from every live run —
batch efficiency equals run concurrency.

Correctness defenses:
- ``call_gemini_batch`` returns aligned per-request results but DROPS entries that end
  empty (its final ``[r for r in results if r is not None]``). The pool therefore
  re-runs a group through per-item synchronous ``call_gemini`` whenever the returned
  length mismatches (and for any item whose text is empty) — correctness over savings.
- Per-item failures resolve that caller's future with the exception; other callers in
  the same flush are unaffected.
- The pool never touches manifests/snapshots/caches directly: ``call_gemini_batch``
  writes the same response-cache files the synchronous path writes, so replay and
  funnel accounting are unchanged.

Usage:
    pool = GeminiBatchPool(flush_interval=20.0)
    with pool.activated():          # installs the hook in gemini_llm
        ... run many arena runs in threads ...
    print(pool.stats)

Batch API is AI-Studio-key only (``call_gemini_batch`` raises under GEMINI_VERTEX);
the pool refuses to activate on the vertex path.
"""
from __future__ import annotations

import contextlib
import os
import threading
from typing import Any, Optional

try:
    from aeread import gemini_llm
except ModuleNotFoundError:  # pragma: no cover - package-style import
    from . import gemini_llm


class _Pending:
    __slots__ = ("model", "request", "event", "result", "error")

    def __init__(self, model: str, request: dict[str, Any]):
        self.model = model
        self.request = request
        self.event = threading.Event()
        self.result: Optional[Any] = None
        self.error: Optional[BaseException] = None


class GeminiBatchPool:
    def __init__(self, *, flush_interval: float = 20.0, max_batch: int = 500):
        self.flush_interval = float(flush_interval)
        self.max_batch = int(max_batch)
        self._lock = threading.Lock()
        self._queue: list[_Pending] = []
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.stats = {"submitted": 0, "batches": 0, "batched_items": 0, "sync_fallbacks": 0}

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if os.environ.get("GEMINI_VERTEX"):
            raise RuntimeError(
                "GeminiBatchPool needs the AI-Studio key path; the Batch API "
                "does not support GEMINI_VERTEX"
            )
        if not os.environ.get("GEMINI_BATCH_ORDERING_VERIFIED"):
            # LAUNCH BLOCKER (review 2026-07-16): Google's Batch API returns inline
            # responses OUT OF ORDER (googleapis/python-genai#1909) and does not echo
            # metadata.key (#1886). call_gemini_batch aligns positionally, so a
            # shuffled batch writes WRONG responses into content-hash-keyed cache
            # files — misattributed decisions that replay "verified" against their
            # own corrupted snapshots. Until correlation is verified end-to-end (or
            # the upstream bugs are fixed), the pool refuses to run scored work.
            # Set GEMINI_BATCH_ORDERING_VERIFIED=1 only after demonstrating reliable
            # request<->response correlation on the current API.
            raise RuntimeError(
                "GeminiBatchPool disabled: Gemini Batch API inline-response ordering "
                "is unreliable upstream (python-genai #1909/#1886) and would "
                "misattribute responses. Run synchronous/Vertex instead, or set "
                "GEMINI_BATCH_ORDERING_VERIFIED=1 after verifying correlation."
            )
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="gemini-batch-pool", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        self._flush()  # drain anything enqueued between last flush and join
        # a caller that raced past the _stop check still must not hang forever
        with self._lock:
            leftovers, self._queue = self._queue, []
        for p in leftovers:
            p.error = RuntimeError("GeminiBatchPool stopped with the request unflushed")
            p.event.set()

    @contextlib.contextmanager
    def activated(self):
        """Install the pool as gemini_llm's cross-run funnel for this process."""
        previous = getattr(gemini_llm, "_CROSSRUN_POOL", None)
        self.start()
        gemini_llm._CROSSRUN_POOL = self
        try:
            yield self
        finally:
            gemini_llm._CROSSRUN_POOL = previous
            self.stop()

    # -- caller side (run threads) ------------------------------------------

    def submit(self, model: str, system: str, user: str, max_tokens: int,
               temperature: float, cache_salt: str):
        """Enqueue one live call; block until its batch resolves; return gemini_llm._R."""
        p = _Pending(model, {
            "system": system, "user": user, "max_tokens": max_tokens,
            "temperature": temperature, "cache_salt": cache_salt,
        })
        with self._lock:
            # the stop check lives INSIDE the queue lock: a submit racing past an
            # outside check could enqueue after stop()'s final drain and hang forever
            if self._stop.is_set():
                raise RuntimeError("GeminiBatchPool is stopped; no new submissions")
            self._queue.append(p)
            self.stats["submitted"] += 1
            if len(self._queue) >= self.max_batch:
                self._wake.set()
        p.event.wait()
        if p.error is not None:
            raise p.error
        return p.result

    # -- flusher side --------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=self.flush_interval)
            self._wake.clear()
            try:
                self._flush()
            except BaseException as err:  # noqa: BLE001 — a dead flusher would hang
                # every blocked caller forever; _flush/_run_group already isolate
                # per-group errors, so anything reaching here is a pool bug: fail
                # the currently queued requests loudly and keep the loop alive.
                with self._lock:
                    orphans, self._queue = self._queue, []
                for p in orphans:
                    p.error = RuntimeError(f"batch pool flusher error: {err!r}")
                    p.event.set()

    def _flush(self) -> None:
        with self._lock:
            take, self._queue = self._queue, []
        if not take:
            return
        by_model: dict[str, list[_Pending]] = {}
        for p in take:
            by_model.setdefault(p.model, []).append(p)
        for model, group in by_model.items():
            self._run_group(model, group)

    def _run_group(self, model: str, group: list[_Pending]) -> None:
        results = None
        try:
            results = gemini_llm.call_gemini_batch(
                [p.request for p in group], model=model)
        except BaseException as err:  # noqa: BLE001 - fall back per item below
            results = None
            batch_error: Optional[BaseException] = err
        else:
            batch_error = None
        if results is not None and len(results) == len(group) and all(
            str(getattr(r, "text", "")).strip() for r in results
        ):
            self.stats["batches"] += 1
            self.stats["batched_items"] += len(group)
            for p, r in zip(group, results):
                p.result = r
                p.event.set()
            return
        # misaligned / empty / failed batch -> per-item synchronous fallback
        del batch_error  # recorded implicitly via sync fallback; per-item errors surface below
        for p in group:
            try:
                p.result = gemini_llm.call_gemini(
                    p.request["system"], p.request["user"], model=model,
                    max_tokens=p.request["max_tokens"],
                    temperature=p.request["temperature"],
                    cache_salt=p.request["cache_salt"],
                    _bypass_pool=True,
                )
                self.stats["sync_fallbacks"] += 1
            except BaseException as err:  # noqa: BLE001 - propagate to the caller
                p.error = err
            p.event.set()
