# CI cancellation-context diagnosis (independent, unverified at time of writing)

Provenance: produced by an external reviewer diagnosing why `tests/test_shared_runner_execution.py`'s cancellation-chain assertions are version-sensitive; captured verbatim below and acted on in `zeyu/fix-cancellation-context-assertions`.

### Root cause (layer + why 3.11 differs)

The extra `CancelledError` is inserted at the `asyncio` Task/Future observation boundary used by `asyncio.run`, not by `ToolExecutor` or `pytest`.

The sequence is:

1. The implementation raises the original cancellation at [tests/test_shared_runner_execution.py:687](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/tests/test_shared_runner_execution.py:687) and [tests/test_shared_runner_execution.py:803](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/tests/test_shared_runner_execution.py:803).
2. `invoke` catches that exact object at [execution.py:3151](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/src/aeread/shared_runner/task/execution.py:3151).
3. While the bookkeeping `RuntimeError` is active, either `_observed_after_or_mark_unknown` re-raises the original object at [execution.py:2980-3009](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/src/aeread/shared_runner/task/execution.py:2980), or the event-write handler re-raises it at [execution.py:3182-3186](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/src/aeread/shared_runner/task/execution.py:3182). Python therefore attaches the bookkeeping error directly to the original cancellation.
4. When that cancellation exits the coroutine, the surrounding `asyncio.Task` becomes cancelled. `run_until_complete` then retrieves the Task through `future.result()` — CPython 3.10 [`Lib/asyncio/base_events.py:613-649`](https://github.com/python/cpython/blob/v3.10.9/Lib/asyncio/base_events.py#L613-L649).

CPython 3.10 saves the coroutine's cancellation in `Task._cancelled_exc` ([`tasks.py:242-245`](https://github.com/python/cpython/blob/v3.10.9/Lib/asyncio/tasks.py#L242-L245)), but `_make_cancelled_error()` constructs a fresh `CancelledError` and assigns the saved exception as its context ([`futures.py:129-142`](https://github.com/python/cpython/blob/v3.10.9/Lib/asyncio/futures.py#L129-L142)). Thus:

```
new Task/Future CancelledError
  -> original implementation CancelledError
       -> bookkeeping RuntimeError
```

CPython 3.11 changed `_make_cancelled_error()` to return the saved original exception directly when available ([`Lib/asyncio/futures.py:126-144`](https://github.com/python/cpython/blob/v3.11.3/Lib/asyncio/futures.py#L126-L144)), producing:

```
original implementation CancelledError
  -> bookkeeping RuntimeError
```

Qualification: stock CPython 3.12 source has the same return-the-saved-exception branch as 3.11 ([`Lib/asyncio/futures.py:126-144`](https://github.com/python/cpython/blob/v3.12.14/Lib/asyncio/futures.py#L126-L144)). Codex reproduced both paths only in-memory (not literally running the CI's 3.12 interpreter): 3.10.9 produced the extra wrapper, 3.11.3/3.12.14 source did not. So the reported CI 3.12 failure isn't explained by stock 3.12 semantics alone — it points to a specific 3.12 patch level/build or CI instrumentation difference, but the wrapper still originates at/above Task result extraction, outside `ToolExecutor`.

### Does the production guarantee hold on all versions?

Yes — this is a test-observation difference, not a production bug. On every version: the outward exception stays `asyncio.CancelledError`; the original cancellation remains reachable (depth zero on 3.11, nested under an asyncio-created wrapper elsewhere); the bookkeeping `RuntimeError` stays reachable beneath it because the re-raise happens while it's active. Only the tests' assumption that the bookkeeping error sits exactly one `__context__` hop away is invalid ([test:706](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/tests/test_shared_runner_execution.py:706), [test:822](/Users/sunzeyu/Documents/econ%20benchmark/AERead/.worktrees/ci-fix/tests/test_shared_runner_execution.py:822)).

### Correct assertion shape / recommended fix

Keep the outer type assertion, then traverse `__context__`/`__cause__` with cycle protection instead of asserting depth-one:

```python
assert isinstance(captured.value, asyncio.CancelledError)

def exception_graph(root):
    pending, seen = [root], set()
    while pending:
        error = pending.pop()
        if id(error) in seen:
            continue
        seen.add(id(error))
        yield error
        if error.__context__ is not None:
            pending.append(error.__context__)
        if error.__cause__ is not None:
            pending.append(error.__cause__)

chain = list(exception_graph(captured.value))
assert any(error is failures["bookkeeping"] for error in chain)
```

Keep `asyncio.run` — swapping to `loop.run_until_complete` doesn't remove the boundary (it also wraps the coroutine in a Task and calls `future.result()` on 3.10/3.11/3.12). If exact identity matters, catch the cancellation inside an async probe and return it as a normal result so the Task completes without cancellation:

```python
async def capture():
    try:
        await tools.invoke(...)
    except asyncio.CancelledError as error:
        return error

captured = asyncio.run(capture())
```

DIAGNOSIS: test-observation
