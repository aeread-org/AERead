# Plan: issue #122 — production json_pointer module + R10 enforcement at replay

Branch: create `zeyu/issue-122-r10-replay-json-pointer` from `origin/main`
**after** the #135 A1 replay-cell PR (adding the required keyword-only
`cell: PlanCell` to `replay_family_scoring_input` / `replay_family_state` /
`_replay_family_trajectory`) has merged. Do not start this branch from the
current `zeyu/issue-135-a1-replay-cell` worktree; that worktree is read-only
reference material for this plan and is being edited concurrently by another
agent. All line numbers below are verified against `origin/main` at
`2318d748bc9c82456995912088c6f9934375df55` (the commit pinned for this task;
the live `origin/main` ref has since advanced past it to `f3ac7b0f` via
unrelated merges — re-verify line numbers against the actual merge base at
branch-creation time, since A1 itself will shift `evaluation.py`).

## Goal

1. Add one production module, `src/aeread/shared_runner/run/json_pointer.py`:
   RFC 6901 `parse` / `get` / `drop`, with `~0`/`~1` decoding, explicit
   object-only navigation (raises on a list or any non-mapping), and no
   root/empty pointer.
2. `schemas.py`'s `MeasurementDeclaration.trajectory_outcome_paths` format
   validation consumes that module instead of its own regex-only tokenizer;
   the scoring-contract test's duplicate tokenizers
   (`_json_pointer_get`, `_drop_json_pointer`) are deleted in favor of it.
3. Enforce ruling R10 — every declared `trajectory_outcome_paths` entry must
   be present in the recomputed outcome *and* in the final replayed state,
   sequence-shaped, and canonically equal — inside `_replay_family_trajectory`
   itself, so `finalize_family_execution`, `replay_family_receipt`, and
   `audit_family_receipt` get it for free. The declaration is read only from
   `registration.manifest` (the trusted registered manifest each of those
   three callers already resolves), never from the run-plan's own manifest
   copy.
4. No-declaration behavior and canonical digest neutrality are unchanged:
   a family with `trajectory_outcome_paths == ()` produces byte-identical
   receipts/digests before and after this change.

## Architecture

```
src/aeread/shared_runner/run/json_pointer.py   (NEW, leaf module, stdlib only)
    parse(pointer: str) -> tuple[str, ...]          # decoded segments
    get(document: Any, pointer: str) -> Any         # object-only read
    drop(document: Mapping, pointer: str) -> Mapping # object-only delete
    class JsonPointerError(ValueError)

src/aeread/shared_runner/schemas.py
    _json_pointer / _json_pointer_tuple  -> delegate syntax check to
    json_pointer.parse(); array-index rejection, duplicate rejection, and
    prefix-overlap rejection stay HERE (schema-specific business rules, not
    generic RFC 6901) but operate on json_pointer.parse()'s decoded segments.

src/aeread/shared_runner/task/evaluation.py
    _replay_family_trajectory(..., trajectory_outcome_paths: tuple[str, ...])
        -> NO DEFAULT (Codex review R1 finding 1): omitting this keyword at
           any call site is a TypeError, not a silent `()`. After computing
           `outcome` and before returning, call a new module-private
           _assert_trajectory_outcome_paths_are_consistent(
               outcome, state, trajectory_outcome_paths)  # `state` is the
           SAME local variable already holding the final replayed state --
           see Task 2 for the exact line.
    replay_family_state(..., trajectory_outcome_paths: tuple[str, ...])
    replay_family_scoring_input(..., trajectory_outcome_paths: tuple[str, ...])
        both thread the new keyword straight through to
        _replay_family_trajectory; NO DEFAULT here either, so every one of
        the 12 existing direct test call sites (listed below) gains an
        explicit `trajectory_outcome_paths=()` in Task 2 (ruling R9: no
        declaration == pre-R9 behavior, but "no declaration" must now be
        written at the call site, never implied by an omitted argument).

    finalize_family_execution / replay_family_receipt / audit_family_receipt
        each already binds `registration = setup.registry.resolve_registration(...)`
        before calling replay_family_scoring_input; each call site adds
        `trajectory_outcome_paths=registration.manifest.measurement.trajectory_outcome_paths`.
```

### Why `trajectory_outcome_paths: tuple[str, ...]`, not `manifest: FamilyManifest`

All three production callers already hold `registration.manifest` in scope
at their `replay_family_scoring_input(...)` call site (verified below).
Passing the single field they need:
- keeps `_replay_family_trajectory`/`replay_family_scoring_input` ignorant of
  `FamilyManifest` as a type (it already takes no manifest-shaped argument
  anywhere else in its signature);
- makes the trusted-sourcing requirement impossible to get wrong by
  omission — there is no `manifest.measurement.leaves`-shaped temptation to
  reach for the *other* manifest (the plan's own copy) sitting in scope at
  two of the three call sites;
- matches the existing `seat_context: SeatContext` parameter precedent on
  `replay_family_scoring_input`, which is also a pre-extracted, caller-owned
  value rather than a whole resolved object.
This parameter has **no default** (Codex review R1 finding 1): a default of
`()` would let an implementation that forgets to source
`trajectory_outcome_paths` from `registration.manifest` — or that wrongly
reads it from the run-plan's own manifest copy instead — compile, and then
silently pass every test that does not specifically declare a non-empty
path, since `()` is also the declaration's own dataclass default and the
value every family under `src/aeread_families` happens to declare today
(verified below: zero non-empty declarations). Matching `seat_context`'s
"required, no default" precedent instead turns that failure mode into a
`TypeError` at every call site, including the 12 existing direct test call
sites (listed below), each of which gains an explicit
`trajectory_outcome_paths=()` in Task 2.

## Spec references

- `kernel_scoring_contract_spec.md` ruling R9 (declaration), ruling R10
  (trajectory-copy consistency), ruling R7 (paired-history precondition).
- `docs/kernel_r9r10_review.md` (existing review; Task 4 appends to it).
- `kernel_contract_impl_review.md` finding 6 (resolve through
  `registry.resolve_registration`, never the plan's own manifest copy —
  already the rule `finalize_family_execution` et al. follow for leaf
  policy; this plan applies the identical rule to `trajectory_outcome_paths`).

## Facts verified against `origin/main` (2318d748) before writing this plan

- `src/aeread/shared_runner/schemas.py`:
  - Ruling-R9 comment block + the two format regexes: lines **24–37**
    (not 27–32 — the comment starts 3 lines earlier than quoted in the
    issue and the regexes are part of the same block).
  - `_json_pointer` / `_json_pointer_tuple`: lines **169–212** (not
    169–190 — `_json_pointer_tuple`'s array-index and prefix-overlap
    checks run to line 212).
  - `class MeasurementDeclaration`: decorator at line 505, `class` at
    line **506** (matches the issue). `trajectory_outcome_paths` field
    at line **545**. `__post_init__`'s unconditional
    `_json_pointer_tuple` call: lines **561–569** (issue said 516–570,
    which is the whole class body through `__post_init__`, not just the
    validation call — narrowed here to the exact call).
  - `from_dict`'s `trajectory_outcome_paths = _json_pointer_tuple(...)`:
    lines **748–750** (matches); passed into `cls(...)` at line **769**
    (issue said "748–770" — confirmed, off by one at the tail only).
  - **Current tokenizer behavior** (`_JSON_POINTER_RE = r"^(?:/[^/]+)+$"`,
    `_ARRAY_INDEX_SEGMENT_RE = r"^[0-9]+$"`):
    - Rejects: `""` (caught earlier by `_string`'s "non-empty string"
      check, before the pointer regex ever runs), `"/"`, `"//history"`,
      `"/history/"`, any string without a leading `/`, any segment that
      is all-ASCII-digits *anywhere in the pointer* (not just the final
      segment — `/a/0/b` is rejected, not only `/a/0`), and one declared
      path that is a strict prefix of another declared path.
    - Accepts: multi-segment object paths of any depth (e.g.
      `/payload/history`), and does **not** decode `~0`/`~1` at all — a
      segment is compared and stored literally, tildes included. The new
      module adds decoding; it does not need to add any new rejection to
      stay behavior-preserving, because no currently-passing schemas test
      exercises a `~`-bearing pointer.
    - Confirmed against `tests/test_shared_runner_schemas.py` (lines
      ~967–1386): every one of the above shapes has a standing test
      (`test_measurement_declaration_rejects_a_malformed_trajectory_outcome_path`,
      `..._rejects_duplicate_...`, `..._rejects_an_array_index_...`,
      `..._rejects_overlapping_...`, `..._accepts_a_nested_object_field_...`).
      These must stay green, unmodified, after Task 1.
- `src/aeread/shared_runner/task/evaluation.py`:
  - `_replay_family_trajectory`: def at line **243**, ends at line
    **549** (issue said "~243–550" — matches).
  - **Final replayed state**: the local variable `state`, reassigned at
    `state = replayed.state` inside the per-transition loop (line ~464
    in the pinned commit). After the phase loop exits, `state` holds
    exactly the value `_replay_family_trajectory` passes to
    `plugin.terminal(family_case, state)` (line ~537) — this is the same
    value the scoring-contract test helper's `_final_replayed_state`
    independently reconstructs from `phase_instances[-1].transitions[-1].state`.
    **Insertion point**: immediately after `outcome = plugin.outcome(...)`
    and its sealed-evidence cross-check (`_use(outcome_events[0])`, line
    ~549 in the pinned commit) and before the `return` — call the new
    check with `outcome` and the still-in-scope `state`, *before* `state`
    could be shadowed or reassigned by anything else (it is not touched
    again in this function after the phase loop).
  - `replay_family_state`: def at line **552**; `replay_family_scoring_input`:
    def at line **603** (issue said "~603–640" — the function body itself
    spans 603–636).
  - Production callers, each already resolving the trusted registration
    immediately before its `replay_family_scoring_input(...)` call:
    `finalize_family_execution` (registration at line **959**, call at
    line **965**), `replay_family_receipt` (registration at line
    **1247**, call at line **1253**), `audit_family_receipt`
    (registration at line **1427**, call at line **1433**). The issue's
    cited line numbers (934, 1186, 1355) are each function's `def` line,
    which matches.
  - **Direct test call sites of `replay_family_scoring_input` /
    `replay_family_state`** — the issue said 17; the verified count
    against `2318d748` is **12**, all inside the three files already
    flagged as under concurrent A1 edit:
    - `tests/test_shared_runner_family_scoring_input.py`: lines 69, 99,
      123, 144, 155 (5 call sites).
    - `tests/test_shared_runner_family_scoring_input_sequential.py`:
      lines 492, 538 (2 call sites).
    - `tests/test_shared_runner_scoring_contract.py`: lines 2697, 3003,
      3009, 3313, 3319 (5 call sites).
    Every one of these already passes `seat_context=` explicitly and
    will gain a required `cell=` from A1; every one of them also gains an
    explicit `trajectory_outcome_paths=()` under this plan (Task 2 step 4)
    — the new parameter has no default (Codex review R1 finding 1), so
    omitting it here would be a `TypeError`, not a silent `()`.
- **No family under `src/aeread_families` currently declares a non-empty
  `trajectory_outcome_paths`** — `git grep -n trajectory_outcome_paths
  2318d748 -- src/aeread_families` returns nothing. The only non-empty
  declarations anywhere in the repo are synthetic, test-local manifests
  inside `tests/test_shared_runner_scoring_contract.py` and
  `tests/test_shared_runner_schemas.py`. Task 3's finalize/replay/audit
  fixtures therefore cannot reuse an existing real declared family; they
  attach a synthetic `trajectory_outcome_paths` onto a *copy* of a real,
  already-migrated family's manifest (Housing), the same way
  `tests/test_shared_runner_family_scoring_policy_enforcement.py`
  already attaches a synthetic leaf policy onto a Housing manifest copy
  for an analogous reason (see that file's `_with_leaf_policy` /
  `_run_housing_episode` / `_registered_under_declared_policy`, lines
  35–92 — read-only reference, not edited by this plan).
  - Verified empirically (via a throwaway script run against this
    worktree, deleted after use — not committed) that Housing's own
    outcome and its own final replayed state agree byte-for-byte at
    `/signed_rents`: the outcome's `signed_rents` (built from
    `economics.signed_rents` in `HousingV1Plugin.terminal`) and the
    final state's `signed_rents` (built from `market.signed_rent` in
    `_snapshot_market`) are the same underlying rent-signing data. This
    is Task 3's one genuine, real, list-shaped, byte-identical
    conforming path — `("/signed_rents",)` — with no synthetic plugin
    needed for the positive case.

## Global constraints

- No JSON Schema engine, no list-navigation expansion in `json_pointer.py`
  (object-only; a list anywhere on the navigated path is a
  `JsonPointerError`, by design — array-index rejection for
  `trajectory_outcome_paths` specifically stays a `schemas.py` business
  rule, not something the generic module decides).
- No family-local helpers: the R10 check lives once, in
  `_replay_family_trajectory`; no `if family_id == "housing": ...`
  anywhere.
- No import from `tests/` in any `src/` module.
- `trajectory_outcome_paths` is read **only** from `registration.manifest`
  inside the three production callers — never from `setup.plan.families[...]`
  (the run-plan's own manifest copy), matching `kernel_contract_impl_review.md`
  finding 6's existing rule for leaf policy.
- Every step below runs from inside this plan's own worktree (created after
  A1 merges), never the `issue-135-a1-replay-cell` worktree.
- Test command (adjust the worktree path to the new branch's worktree):
  ```
  cd "<new-worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    "/Users/sunzeyu/Documents/econ benchmark/AERead/.venv/bin/python" \
    -m pytest -p no:cacheprovider -q <files>
  ```

---

## Task 1 — `json_pointer.py` module, `schemas.py` adoption, test-helper removal

### Files

- Create: `src/aeread/shared_runner/run/json_pointer.py`
- Create: `tests/test_shared_runner_json_pointer.py`
- Modify: `src/aeread/shared_runner/schemas.py`
- Modify: `tests/test_shared_runner_scoring_contract.py` (helper removal only
  — **do this sub-step last**, after rebasing onto the merged A1 branch, and
  re-diff the file immediately before editing: another agent's concurrent
  work may have moved these helpers or their line numbers)

### Interfaces

```python
# src/aeread/shared_runner/run/json_pointer.py
class JsonPointerError(ValueError): ...

def parse(pointer: str) -> tuple[str, ...]: ...
def get(document: Any, pointer: str) -> Any: ...
def drop(document: Mapping[str, Any], pointer: str) -> Mapping[str, Any]: ...
```

### Authoring rejections that must remain unchanged (Codex review R1 finding 4)

`schemas.py`'s business-rule rejections on top of plain RFC 6901 syntax are
untouched by Task 1 — `json_pointer.parse()` only supplies the decoded
segments these rules already operate on (`schemas.py:66-69`, `:169-212`):

- a `trajectory_outcome_paths` declaration that is not a list/tuple;
- a non-string or whitespace-only entry;
- the empty pointer, `"/"` alone, a pointer missing its leading `/`, a
  doubled `/`, a trailing `/`, or any other empty segment;
- an exact duplicate of another declared pointer;
- an all-ASCII-digit segment at any depth (the array-index rejection);
- one declared pointer being a strict prefix of another declared pointer.

Task 1 step 6/7's regression run against `tests/test_shared_runner_schemas.py`
is what proves every one of these stays green, unmodified.

### Steps

- [ ] 1. Write the RED test file `tests/test_shared_runner_json_pointer.py`:

```python
"""Unit tests for the shared RFC 6901 JSON Pointer module (issue #122).

Ruling R9/R10 (kernel_scoring_contract_spec.md): trajectory_outcome_paths'
JSON Pointer projection previously lived only in test helpers
(tests/test_shared_runner_scoring_contract.py). This module is the one
production tokenizer/navigator that schemas.py format validation and
evaluation.py's replay-time R10 check both consume.
"""

from __future__ import annotations

import pytest

from aeread.shared_runner.run.json_pointer import JsonPointerError, drop, get, parse


def test_parse_decodes_tilde_one_as_a_literal_slash() -> None:
    assert parse("/a~1b") == ("a/b",)


def test_parse_decodes_tilde_zero_as_a_literal_tilde() -> None:
    assert parse("/a~0b") == ("a~b",)


def test_parse_returns_one_segment_per_slash() -> None:
    assert parse("/a/b/c") == ("a", "b", "c")


def test_parse_rejects_the_empty_string() -> None:
    with pytest.raises(JsonPointerError):
        parse("")


def test_parse_rejects_the_root_pointer() -> None:
    with pytest.raises(JsonPointerError):
        parse("/")


def test_parse_rejects_a_pointer_without_a_leading_slash() -> None:
    with pytest.raises(JsonPointerError):
        parse("history")


def test_parse_rejects_a_doubled_slash() -> None:
    with pytest.raises(JsonPointerError):
        parse("//history")


def test_parse_rejects_a_trailing_slash() -> None:
    with pytest.raises(JsonPointerError):
        parse("/history/")


def test_parse_rejects_a_dangling_tilde_at_the_end_of_a_segment() -> None:
    """RFC 6901: every '~' must be followed by exactly '0' or '1'. A '~'
    with nothing after it is not a valid escape (Codex review R1 finding 4)."""
    with pytest.raises(JsonPointerError):
        parse("/a~")


def test_parse_rejects_an_unrecognized_escape() -> None:
    """'~2' is not '~0' or '~1' -- not a valid RFC 6901 escape."""
    with pytest.raises(JsonPointerError):
        parse("/a~2b")


def test_get_navigates_nested_objects() -> None:
    assert get({"a": {"b": 1}}, "/a/b") == 1


def test_get_raises_on_a_missing_segment() -> None:
    with pytest.raises(JsonPointerError):
        get({"a": {}}, "/a/b")


def test_get_raises_when_an_intermediate_value_is_a_list() -> None:
    with pytest.raises(JsonPointerError):
        get({"a": [1, 2]}, "/a/0")


def test_get_raises_when_the_document_itself_is_not_a_mapping() -> None:
    with pytest.raises(JsonPointerError):
        get([1, 2], "/0")


def test_get_decodes_escaped_segments_during_navigation() -> None:
    assert get({"a/b": 1}, "/a~1b") == 1


def test_drop_removes_a_top_level_field() -> None:
    assert drop({"a": 1, "b": 2}, "/a") == {"b": 2}


def test_drop_removes_a_nested_field_without_disturbing_siblings() -> None:
    assert drop({"a": {"b": 1, "c": 2}, "d": 3}, "/a/b") == {
        "a": {"c": 2},
        "d": 3,
    }


def test_drop_raises_on_a_missing_segment() -> None:
    with pytest.raises(JsonPointerError):
        drop({"a": 1}, "/b")


def test_drop_raises_when_an_intermediate_value_is_a_list() -> None:
    with pytest.raises(JsonPointerError):
        drop({"a": [1, 2]}, "/a/0")
```

- [ ] 2. Run RED:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_json_pointer.py
  ```
  Expected: collection error —
  `ModuleNotFoundError: No module named 'aeread.shared_runner.run.json_pointer'`
  (every test errors, not just fails).

- [ ] 3. Smallest production change — create the module:

```python
# src/aeread/shared_runner/run/json_pointer.py
"""RFC 6901 JSON Pointers, restricted to JSON *object* navigation.

Issue #122: the projection and navigation that `MeasurementDeclaration.
trajectory_outcome_paths` (ruling R9) and its replay-time consistency check
(ruling R10) both need existed only as duplicated test helpers. This is the
one production implementation both `schemas.py` validation and
`task/evaluation.py`'s R10 replay check consume.

Deliberately does not support: the root pointer (the empty string), any
empty intermediate segment, or navigating through a list at any point --
every declared `trajectory_outcome_paths` entry names a chain of JSON
*object* fields, never an array index (schemas.py enforces that as its own,
narrower business rule on top of this module's plain RFC 6901 syntax check;
this module stays a generic pointer reader).
"""
from __future__ import annotations

import re
from typing import Any, Mapping

# Codex review R1 finding 4: the only valid RFC 6901 escapes are "~0" (a
# literal "~") and "~1" (a literal "/"). This matches a "~" NOT immediately
# followed by "0" or "1" -- a dangling "~" at the end of a segment (nothing
# follows it) and an unrecognized escape such as "~2" both match, and are
# rejected.
_INVALID_ESCAPE_RE = re.compile(r"~(?![01])")


class JsonPointerError(ValueError):
    """A JSON pointer string is malformed, or navigation hit a non-object."""


def parse(pointer: str) -> tuple[str, ...]:
    """Parse an RFC 6901 pointer into its decoded (~1->'/', ~0->'~') segments.

    Requires at least one non-empty segment: the empty string (root), "/"
    alone, and any pointer with an empty segment (a leading, trailing, or
    doubled "/") are all rejected. Every "~" must be followed by exactly "0"
    or "1"; a dangling "~" or an unrecognized escape (e.g. "~2") is rejected.
    """
    if not isinstance(pointer, str) or not pointer or pointer[0] != "/":
        raise JsonPointerError(
            f"{pointer!r} is not a JSON pointer with at least one segment"
        )
    raw_segments = pointer.split("/")[1:]
    if any(segment == "" for segment in raw_segments):
        raise JsonPointerError(f"{pointer!r} contains an empty segment")
    if any(_INVALID_ESCAPE_RE.search(segment) for segment in raw_segments):
        raise JsonPointerError(
            f"{pointer!r} contains an invalid escape -- every '~' must be "
            "followed by exactly '0' or '1'"
        )
    return tuple(
        segment.replace("~1", "/").replace("~0", "~") for segment in raw_segments
    )


def get(document: Any, pointer: str) -> Any:
    """Read `pointer` out of `document`, navigating JSON objects only."""
    node = document
    for segment in parse(pointer):
        if not isinstance(node, Mapping):
            raise JsonPointerError(f"{pointer!r} does not navigate a JSON object")
        if segment not in node:
            raise JsonPointerError(f"{pointer!r} does not exist in this document")
        node = node[segment]
    return node


def drop(document: Mapping[str, Any], pointer: str) -> Mapping[str, Any]:
    """Return `document` with the field named by `pointer` removed."""
    return _drop(document, parse(pointer), pointer)


def _drop(document: Any, segments: tuple[str, ...], pointer: str) -> Mapping[str, Any]:
    if not isinstance(document, Mapping):
        raise JsonPointerError(f"{pointer!r} does not navigate a JSON object")
    key = segments[0]
    if key not in document:
        raise JsonPointerError(f"{pointer!r} does not exist in this document")
    if len(segments) == 1:
        return {k: v for k, v in document.items() if k != key}
    return {
        k: (_drop(v, segments[1:], pointer) if k == key else v)
        for k, v in document.items()
    }
```

- [ ] 4. Run GREEN:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_json_pointer.py
  ```
  Expected: `19 passed` (17 tests already in step 1's file before the two
  escape-validation tests Codex review R1 finding 4 added, plus those 2 --
  not 16: the step-1 file has 17 tests even before this revision, an
  off-by-one in the original count being corrected here).

- [ ] 5. Commit:
  ```
  git add src/aeread/shared_runner/run/json_pointer.py \
          tests/test_shared_runner_json_pointer.py
  git commit -m "feat(run): add an RFC 6901 json_pointer module"
  ```

- [ ] 6. Adopt it in `schemas.py` — replace the regex-only format check
  inside `_json_pointer` (keep `_string`'s prior "non-empty string" check;
  keep the array-index/duplicate/prefix-overlap business rules in
  `_json_pointer_tuple` exactly as they are, just operating on
  `json_pointer.parse()`'s decoded segments instead of a raw
  `pointer.split("/")[1:]`):

```python
# top of schemas.py, new import
from .run import json_pointer

# replace the body of _json_pointer:
def _json_pointer(value: Any, path: str) -> str:
    result = _string(value, path)
    try:
        json_pointer.parse(result)
    except json_pointer.JsonPointerError as error:
        raise AuthoringValidationError(
            f"{path} must be a JSON pointer with at least one non-empty segment "
            f"(e.g. '/history'): got {result!r}"
        ) from error
    return result

# inside _json_pointer_tuple, replace:
#     segments = pointer.split("/")[1:]
# with:
#     segments = json_pointer.parse(pointer)
# (the rest of the function -- duplicate check on raw `result`, array-index
# check on `segments`, prefix-overlap check on raw `result` -- is unchanged)
```
  `_JSON_POINTER_RE` and `_ARRAY_INDEX_SEGMENT_RE` stay (the latter is still
  used by `_json_pointer_tuple`'s own array-index rejection); only the
  format check inside `_json_pointer` stops using `_JSON_POINTER_RE`
  directly. If `_JSON_POINTER_RE` becomes otherwise unused after this edit,
  delete it and its now-orphaned part of the comment block (lines 24–37) —
  confirm with `grep -n _JSON_POINTER_RE src/aeread/shared_runner/schemas.py`
  before deleting.

- [ ] 7. Run GREEN on the full existing regression suite for this field
  (must stay green, unmodified):
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_schemas.py tests/test_shared_runner_json_pointer.py
  ```
  Expected: all pass, same pass count `test_shared_runner_schemas.py` had
  before this step (record the exact count from a pre-edit run and diff it).

- [ ] 8. Commit:
  ```
  git add src/aeread/shared_runner/schemas.py
  git commit -m "refactor(schemas): tokenize trajectory_outcome_paths via json_pointer"
  ```

- [ ] 9. **After** rebasing onto the merged A1 branch, re-read
  `tests/test_shared_runner_scoring_contract.py` fresh (`git show
  HEAD:tests/test_shared_runner_scoring_contract.py`) to re-locate
  `_json_pointer_get` and `_drop_json_pointer` (they may have moved). Delete
  both functions; change `project_outcome` and
  `_assert_trajectory_outcome_paths_are_consistent` to call
  `json_pointer.get` / `json_pointer.drop` (imported as
  `from aeread.shared_runner.run import json_pointer`) instead. Run the full
  file:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_scoring_contract.py
  ```
  Expected: identical pass count to the pre-edit run (this is a pure
  refactor of the test file, zero behavior change — `_json_pointer_get`'s
  prior `KeyError` becomes `json_pointer.JsonPointerError`; confirm every
  `pytest.raises(KeyError, ...)` / `pytest.raises(AssertionError, ...)` in
  this file around these two helpers still matches, since
  `_assert_trajectory_outcome_paths_are_consistent` catches
  `KeyError` specifically at two points — change those `except KeyError:`
  clauses to `except json_pointer.JsonPointerError:`).
- [ ] 10. Commit:
  ```
  git add tests/test_shared_runner_scoring_contract.py
  git commit -m "test(scoring_contract): drop the duplicate json-pointer tokenizers"
  ```

---

## Task 2 — R10 at replay in `_replay_family_trajectory`, trusted-manifest sourcing

### Files

- Create: `tests/test_shared_runner_trajectory_outcome_r10_replay.py`
- Modify: `src/aeread/shared_runner/task/evaluation.py`

### Interfaces

```python
def _replay_family_trajectory(
    *,
    plugin: Any,
    family_case: Mapping[str, Any],
    evidence: EvidenceStore,
    cell: "PlanCell",                          # from A1, already present
    trajectory_outcome_paths: tuple[str, ...],  # NEW, no default (finding 1)
) -> tuple[Mapping[str, Any], tuple[PhaseInstance, ...], Any, tuple[str, ...]]: ...

def replay_family_state(
    *, plugin, family_case, evidence, cell, trajectory_outcome_paths: tuple[str, ...]
) -> tuple[Mapping[str, Any], Any]: ...

def replay_family_scoring_input(
    *, plugin, family_case, evidence, cell, seat_context: SeatContext,
    trajectory_outcome_paths: tuple[str, ...],
) -> FamilyScoringInput: ...

def _assert_trajectory_outcome_paths_are_consistent(
    outcome: Mapping[str, Any],
    final_state: Any,
    trajectory_outcome_paths: tuple[str, ...],
) -> None: ...
```

(`cell` above is A1's parameter, already required by the time this branch is
cut — shown only so the new parameter's position, after it, is unambiguous.
`trajectory_outcome_paths` has **no default** anywhere in this interface --
Codex review R1 finding 1: omitting it is a `TypeError`, never a silent
`()`.)

### Steps

- [ ] 1. Write the RED test file. All cases use Housing's real plugin end to
  end (`build_housing_smoke` + `execute_plan_cell`, the established pattern
  already used by `tests/test_shared_runner_family_scoring_input.py`), and
  pass `trajectory_outcome_paths` straight to the function under test — no
  manifest/registry wiring needed for the unit-level cases, since the new
  keyword is independent of where a caller later sources it from (Task 3
  covers that sourcing). `cell=` is threaded through using A1's helper for
  resolving the plan's cell (match whatever A1 actually named it —
  `_seat_context_for_cell`'s sibling; re-check against the merged A1 branch
  before filling this in literally).

```python
"""Ruling R10 (kernel_scoring_contract_spec.md) enforced at replay time
itself, not only inside the scoring-contract protocol test (issue #122).

A deterministic outcome() that mis-copies its own trajectory state used to
verify against itself on every production replay path
(finalize_family_execution / replay_family_receipt / audit_family_receipt):
each compares a freshly replayed outcome only against bytes produced by that
SAME outcome() call, sealed earlier by that SAME call. A self-consistent
mis-copy agrees with itself at every boundary those paths already check.
This file proves _replay_family_trajectory now catches it directly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.task.evaluation import (
    SeatContext,
    replay_family_scoring_input,
)
from aeread.shared_runner.task.execution import execute_plan_cell
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)


def _run_housing_episode(tmp_path: Path, *, registry: PluginRegistry | None = None):
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=registry or setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    cell = next(item for item in setup.plan.cells if item.cell_id == execution.cell_id)
    case = next(item for item in setup.plan.cases if item.case_id == cell.case_id)
    family = next(item for item in setup.plan.families if item.family.id == cell.family_id)
    plugin = (registry or setup.registry).resolve_manifest(family)
    family_case = plugin.validate_payload(case.payload)
    return setup, execution, plugin, family_case, cell


def test_r10_is_a_no_op_with_no_declared_paths(tmp_path) -> None:
    """Unchanged behavior: no declaration, no check, whatever Housing's real
    outcome/state happen to be."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        cell=cell,
        seat_context=SeatContext((), {}),
        trajectory_outcome_paths=(),
    )


def test_r10_accepts_a_genuine_matching_path(tmp_path) -> None:
    """/signed_rents is byte-identical between Housing's real outcome and
    its real final replayed state -- a true positive, no corruption needed."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    scoring_input = replay_family_scoring_input(
        plugin=plugin,
        family_case=family_case,
        evidence=execution.evidence,
        cell=cell,
        seat_context=SeatContext((), {}),
        trajectory_outcome_paths=("/signed_rents",),
    )
    assert scoring_input.outcome["signed_rents"]


def test_r10_rejects_a_declared_path_missing_from_the_outcome(tmp_path) -> None:
    """Housing's real outcome has no "/not_a_real_field" key at all."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/not_a_real_field",),
        )


def test_r10_rejects_a_declared_path_missing_from_the_final_state(tmp_path) -> None:
    """"/assignment_pairs" is a real, sequence-shaped outcome field, but
    Housing's own state snapshot never carries that key."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    with pytest.raises(AssertionError, match="does not exist in the final replayed state"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/assignment_pairs",),
        )


def test_r10_rejects_a_non_sequence_declared_path(tmp_path) -> None:
    """"/baseline_total" is a real outcome field, but it is a float, not a
    per-step record sequence."""
    _setup, execution, plugin, family_case, cell = _run_housing_episode(tmp_path)
    with pytest.raises(AssertionError, match="not a.*sequence"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/baseline_total",),
        )


class _CorruptedSignedRentsHousingPlugin:
    """Delegates every hook to a real HousingV1Plugin except outcome(),
    which deterministically drops the first signed_rents entry -- exactly
    the class of bug issue #122 describes: a deterministic outcome() that
    mis-copies trajectory state, which verifies against itself at every
    other replay boundary because both the live run and the replay call the
    SAME corrupted outcome() the same way."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def outcome(self, case, terminal):
        real = dict(self._inner.outcome(case, terminal))
        real["signed_rents"] = tuple(real["signed_rents"])[1:]
        return real


def test_r10_rejects_two_trajectory_copies_that_currently_pass_outside_protocol_fixtures(
    tmp_path,
) -> None:
    """The corrupted plugin is registered BEFORE the live episode runs, so
    its mis-copy is sealed as evidence once and replayed consistently --
    the existing outcome-vs-sealed-evidence cross-check in
    _replay_family_trajectory (line ~545) passes, because it only compares
    the corrupted outcome() against itself. Only the new R10 check, which
    compares the outcome's OWN copy against the final replayed state at
    the same pointer, can catch this."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(manifest)
    registry = PluginRegistry()
    registry.register_trusted(manifest, _CorruptedSignedRentsHousingPlugin(real_plugin))

    _setup, execution, plugin, family_case, cell = _run_housing_episode(
        tmp_path, registry=registry
    )

    with pytest.raises(AssertionError, match="does not match the same pointer read"):
        replay_family_scoring_input(
            plugin=plugin,
            family_case=family_case,
            evidence=execution.evidence,
            cell=cell,
            seat_context=SeatContext((), {}),
            trajectory_outcome_paths=("/signed_rents",),
        )
```

- [ ] 2. Run RED:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_trajectory_outcome_r10_replay.py
  ```
  Expected: `test_r10_is_a_no_op_with_no_declared_paths` and
  `test_r10_accepts_a_genuine_matching_path` fail with
  `TypeError: replay_family_scoring_input() got an unexpected keyword
  argument 'trajectory_outcome_paths'`; the four `pytest.raises(...)` tests
  fail with `Failed: DID NOT RAISE` (or the same `TypeError`, depending on
  whether the `TypeError` itself satisfies `pytest.raises(AssertionError,
  ...)` — it will not, since `TypeError` is not `AssertionError`, so these
  also fail, just via an unmatched-exception-type failure rather than
  "did not raise"). 6 failed.

- [ ] 3. Smallest production change, in `src/aeread/shared_runner/task/evaluation.py`:

```python
# new import near the top, alongside the existing relative imports
from ..run import json_pointer

# new private function, placed directly above _replay_family_trajectory
def _assert_trajectory_outcome_paths_are_consistent(
    outcome: Mapping[str, Any],
    final_state: Any,
    trajectory_outcome_paths: tuple[str, ...],
) -> None:
    """Ruling R10: each declared path's outcome copy must equal the SAME
    pointer read from the final replayed state. Enforced here, at replay,
    so every production caller of _replay_family_trajectory gets it --
    previously this comparison existed only inside the scoring-contract
    protocol test (issue #122)."""
    if not trajectory_outcome_paths:
        return
    for pointer in trajectory_outcome_paths:
        try:
            outcome_value = json_pointer.get(outcome, pointer)
        except json_pointer.JsonPointerError as error:
            raise AssertionError(
                f"outcome{pointer} does not exist in the outcome -- every "
                "declared trajectory_outcome_path must be present in the "
                "outcome"
            ) from error
        if not isinstance(outcome_value, (list, tuple)):
            raise AssertionError(
                f"outcome{pointer} is a {type(outcome_value).__name__}, not "
                "a sequence -- a declared trajectory_outcome_path must point "
                "at a sequence of per-step records"
            )
        try:
            derived_value = json_pointer.get(final_state, pointer)
        except json_pointer.JsonPointerError as error:
            raise AssertionError(
                f"outcome{pointer} does not exist in the final replayed "
                "state -- ruling R10 reads the SAME pointer from both the "
                "outcome and the final replayed state"
            ) from error
        if canonical_json_bytes(outcome_value) != canonical_json_bytes(derived_value):
            raise AssertionError(
                f"outcome{pointer} does not match the same pointer read "
                "from the final replayed state"
            )
```

Then, inside `_replay_family_trajectory`:
  - Add `trajectory_outcome_paths: tuple[str, ...]` to its signature (after
    `cell`, before the return type arrow) — **no default** (Codex review R1
    finding 1): omitting it at any call site is a `TypeError`.
  - Immediately after the existing
    `outcome = plugin.outcome(family_case, terminal)` /
    `_use(outcome_events[0])` block and before the function's final
    `return (...)`, insert:
    ```python
    _assert_trajectory_outcome_paths_are_consistent(
        outcome, state, trajectory_outcome_paths
    )
    ```
    (`state` is already the correct local variable — see the verified
    facts above; no new variable is introduced).
  - In `replay_family_state` and `replay_family_scoring_input`, add the
    same `trajectory_outcome_paths: tuple[str, ...]` parameter (again, no
    default) and forward it verbatim into the `_replay_family_trajectory(...)`
    call.
  - In `finalize_family_execution`, `replay_family_receipt`, and
    `audit_family_receipt`, add
    `trajectory_outcome_paths=registration.manifest.measurement.trajectory_outcome_paths`
    to each existing `replay_family_scoring_input(...)` call (registration
    is already bound in each, above the call, per the verified facts).

- [ ] 4. Because step 3 removed the default, every existing direct call site
  of `replay_family_state` / `replay_family_scoring_input` now raises
  `TypeError` unless it passes `trajectory_outcome_paths=()` explicitly.
  Add that one keyword, verbatim, to each of the 12 call sites enumerated in
  "Facts verified" above — **re-diff each file first** (same caution as
  Task 1 step 9: A1 is concurrently adding a required `cell=` to these same
  call sites):
  - `tests/test_shared_runner_family_scoring_input.py`: lines 69, 99, 123,
    144, 155.
  - `tests/test_shared_runner_family_scoring_input_sequential.py`: lines
    492, 538.
  - `tests/test_shared_runner_scoring_contract.py`: lines 2697, 3003, 3009,
    3313, 3319.
  No other change at any of these 12 sites: they keep exercising the
  pre-R9/R10, no-declaration behavior, now spelled out instead of implied.

- [ ] 5. Run GREEN:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_trajectory_outcome_r10_replay.py
  ```
  Expected: `6 passed`.

- [ ] 6. Run GREEN on every existing direct call site updated in step 4, to
  confirm the explicit `trajectory_outcome_paths=()` reproduces the
  pre-change, no-declaration behavior unchanged:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_family_scoring_input.py \
    tests/test_shared_runner_family_scoring_input_sequential.py
  ```
  Expected: same pass counts as a pre-edit run (record and diff).

- [ ] 7. Commit:
  ```
  git add src/aeread/shared_runner/task/evaluation.py \
          tests/test_shared_runner_trajectory_outcome_r10_replay.py \
          tests/test_shared_runner_family_scoring_input.py \
          tests/test_shared_runner_family_scoring_input_sequential.py \
          tests/test_shared_runner_scoring_contract.py
  git commit -m "fix(evaluation): enforce R10 trajectory-copy consistency at replay"
  ```

---

## Task 3 — digest neutrality and conforming finalize/replay/audit coverage

### Files

- Create: `tests/test_shared_runner_trajectory_outcome_r10_production_callers.py`
- No production changes expected (Task 2 already wired all three callers);
  this task is coverage only. If any of these tests reveal a caller that was
  missed or mis-wired, fix it here and say so in the commit message.

### Steps

- [ ] 1. Write the RED test file:

```python
"""Issue #122, requirement 5: trajectory_outcome_paths' declaration must be
read from the TRUSTED registered manifest by all three production callers
of replay_family_scoring_input, and a family that declares none must be
byte-identical, digest-for-digest, to the same family before this change.

Codex review R1 findings 1 and 3 (see docs/kernel_r9r10_review.md's issue
#122 section once Task 4 lands): finding 1 requires adversarial coverage at
all three production callers -- a TRUSTED declaration that is guaranteed to
fail R10 while the run-plan's own manifest copy declares none (must raise),
and the inverse (must pass) -- not only the "both declare the same
genuinely-conforming path" coverage below. Finding 3 requires a pinned,
pre-change golden oracle for digest neutrality, not a two-episode
comparison.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
from pathlib import Path
from typing import Any

import pytest

from aeread.shared_runner import canonical_json_bytes
from aeread.shared_runner.registry import PluginRegistry
from aeread.shared_runner.run import resolver as _resolver
from aeread.shared_runner.task.evaluation import (
    audit_family_receipt,
    finalize_family_execution,
    replay_family_receipt,
)
from aeread.shared_runner.task.execution import EvidenceStore, execute_plan_cell
from aeread_families.housing.runner import (
    HousingScriptedLandlordProvider,
    HousingScriptedTenantProvider,
    build_housing_smoke,
)


def _with_trajectory_outcome_paths(manifest, paths: tuple[str, ...]):
    measurement = dataclasses.replace(manifest.measurement, trajectory_outcome_paths=paths)
    return dataclasses.replace(manifest, measurement=measurement)


def _poisoned_plan_and_episode(tmp_path: Path, base_setup, *, failing_paths: tuple[str, ...]):
    """A second, independently-sealed RunPlan whose OWN family-manifest copy
    declares `failing_paths` -- needed for finding 1's inverse direction.

    The plan's own copy cannot be mutated in place: `plan_sha256` covers
    `families` (verified against `_plan_payload` in
    `src/aeread/shared_runner/run/resolver.py`), and `execution.run_plan_id`
    is bound to whichever plan sealed it, so a fresh episode must run
    against the re-sealed plan. `resolver._seal_plan` (private; the only
    change here is one family's `measurement`, which `resolve_run_plan`'s
    full suite/sampling/case cross-validation does not need to re-run) is
    the minimal way to get a digest-valid plan back. `PluginRegistry.
    resolve_registration` keys only on `(family_id, family_version,
    plugin_id)` (verified against `src/aeread/shared_runner/registry.py`),
    so passing the SAME, untouched `base_setup.registry` here keeps the
    TRUSTED registration declaring `()` throughout -- only the plan's own
    copy is poisoned."""
    base_manifest = base_setup.plan.families[0]
    poisoned_manifest = _with_trajectory_outcome_paths(base_manifest, failing_paths)
    poisoned_families = tuple(
        poisoned_manifest if family is base_manifest else family
        for family in base_setup.plan.families
    )
    poisoned_plan = _resolver._seal_plan(
        dataclasses.replace(base_setup.plan, families=poisoned_families)
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=poisoned_plan,
            cell_id=poisoned_plan.cells[0].cell_id,
            registry=base_setup.registry,
            evidence_root=tmp_path,
            prompt_sources=base_setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=base_setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    return poisoned_plan, execution


def _run_housing_episode(tmp_path: Path):
    setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    execution = asyncio.run(
        execute_plan_cell(
            plan=setup.plan,
            cell_id=setup.plan.cells[0].cell_id,
            registry=setup.registry,
            evidence_root=tmp_path,
            prompt_sources=setup.prompt_sources,
            providers={
                "housing_scripted_tenant": HousingScriptedTenantProvider(),
                "housing_scripted_landlord": HousingScriptedLandlordProvider(),
            },
            pricing=setup.pricing,
            episode_attempt_ordinal=0,
        )
    )
    return setup, execution


class _FinalizeOnlySetup:
    def __init__(self, plan, registry, prompt_sources, pricing):
        self.plan = plan
        self.registry = registry
        self.prompt_sources = prompt_sources
        self.pricing = pricing


def test_finalize_sources_trajectory_outcome_paths_from_the_trusted_registration(
    tmp_path,
) -> None:
    """A manifest declaring ("/signed_rents",), registered as the TRUSTED
    registration, must be consulted by finalize_family_execution even though
    the run-plan's own manifest copy (base_setup.plan.families[0]) carries
    none -- proving R10 is read from registration.manifest, not the plan's
    copy."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)

    declared_manifest = _with_trajectory_outcome_paths(base_manifest, ("/signed_rents",))
    registry = PluginRegistry()
    registry.register_trusted(declared_manifest, real_plugin)

    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # the plan's OWN manifest copy still has no declaration
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )

    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    # Codex review R1 finding 2: EvaluationReceipt.status permits only "ok"
    # or "invalid_measurement" (receipts.py ~203-204); a conforming
    # finalize on a real, admitted Housing episode is "ok", matching the
    # production expectation at tests/test_shared_runner_housing.py ~354.
    # "admitted" is not a receipt status at all.
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"


def test_finalize_rejects_a_failing_trusted_declaration_even_though_the_plan_copy_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, direction 1: the TRUSTED registration
    declares a path guaranteed to fail R10 ("/not_a_real_field" is absent
    from Housing's real outcome); the plan's own manifest copy
    (base_setup.plan) declares none. finalize_family_execution must still
    raise -- proving it is governed by the trusted registration, not a
    default that silently passes because the plan copy is empty."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)
    failing_manifest = _with_trajectory_outcome_paths(base_manifest, ("/not_a_real_field",))
    registry = PluginRegistry()
    registry.register_trusted(failing_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # unchanged: plan's own copy still declares ()
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        finalize_family_execution(setup=finalize_setup, execution=execution)


def test_finalize_passes_when_the_plan_copy_declares_a_failing_path_but_the_trusted_registration_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, the inverse direction: the plan's OWN
    manifest copy declares a path guaranteed to fail R10; the TRUSTED
    registration declares none. finalize_family_execution must still pass
    -- proving it never reads trajectory_outcome_paths from
    setup.plan.families[...] at all."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    poisoned_plan, execution = _poisoned_plan_and_episode(
        tmp_path, base_setup, failing_paths=("/not_a_real_field",)
    )
    finalize_setup = _FinalizeOnlySetup(
        plan=poisoned_plan,
        registry=base_setup.registry,  # unchanged: trusted registration still declares ()
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    assert receipt.status == "ok"
    assert receipt.inclusion_status == "included"
    assert receipt.replay_level == "state_and_score"


def test_replay_family_receipt_conforms_with_a_declared_trajectory_outcome_path(
    tmp_path,
) -> None:
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)
    declared_manifest = _with_trajectory_outcome_paths(base_manifest, ("/signed_rents",))
    registry = PluginRegistry()
    registry.register_trusted(declared_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)

    replayed = replay_family_receipt(
        setup=finalize_setup, receipt=receipt, evidence_root=tmp_path
    )
    assert canonical_json_bytes(replayed) == canonical_json_bytes(receipt)
    # Codex review R1 finding 2: a conforming replay must itself be a
    # conforming receipt -- "ok"/"included"/"state_and_score", never
    # "admitted" (not a valid status at all) or "invalid_measurement"
    # (replay_family_receipt skips nothing here; there IS a score to
    # replay, so "invalid_measurement" would not be conformance).
    assert replayed.status == "ok"
    assert replayed.inclusion_status == "included"
    assert replayed.replay_level == "state_and_score"


def test_replay_rejects_a_failing_trusted_declaration_even_though_the_plan_copy_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, direction 1, at replay_family_receipt: the
    receipt is sealed under a conforming (empty) trusted declaration, then
    replayed under a DIFFERENT registry whose trusted registration declares
    a path guaranteed to fail R10. The plan's own copy (unchanged throughout)
    still declares none. replay_family_receipt must raise."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)

    conforming_registry = PluginRegistry()
    conforming_registry.register_trusted(base_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=conforming_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)

    failing_manifest = _with_trajectory_outcome_paths(base_manifest, ("/not_a_real_field",))
    failing_registry = PluginRegistry()
    failing_registry.register_trusted(failing_manifest, real_plugin)
    replay_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # unchanged: plan's own copy still declares ()
        registry=failing_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        replay_family_receipt(setup=replay_setup, receipt=receipt, evidence_root=tmp_path)


def test_replay_passes_when_the_plan_copy_declares_a_failing_path_but_the_trusted_registration_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, the inverse direction, at
    replay_family_receipt: the plan's OWN manifest copy (poisoned_plan)
    declares a path guaranteed to fail R10; the TRUSTED registration
    declares none throughout. replay_family_receipt must still pass."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    poisoned_plan, execution = _poisoned_plan_and_episode(
        tmp_path, base_setup, failing_paths=("/not_a_real_field",)
    )
    finalize_setup = _FinalizeOnlySetup(
        plan=poisoned_plan,
        registry=base_setup.registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    replayed = replay_family_receipt(
        setup=finalize_setup, receipt=receipt, evidence_root=tmp_path
    )
    assert replayed.status == "ok"


def test_audit_family_receipt_conforms_with_a_declared_trajectory_outcome_path(
    tmp_path,
) -> None:
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)
    declared_manifest = _with_trajectory_outcome_paths(base_manifest, ("/signed_rents",))
    registry = PluginRegistry()
    registry.register_trusted(declared_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    finalize_family_execution(setup=finalize_setup, execution=execution)

    receipt_path = execution.evidence.root / "evaluation_receipt.json"
    audited = audit_family_receipt(setup=finalize_setup, receipt_path=receipt_path)
    # Codex review R1 finding 2: same fix as the finalize/replay conforming
    # tests above -- "admitted" is not a receipt status, and
    # "invalid_measurement" would not be conformance (audit_family_receipt
    # skips score replay entirely when a receipt has no scores, per
    # evaluation.py's `if receipt.get("scores"):` guard -- accepting
    # "invalid_measurement" here would not prove the score-replay path, let
    # alone R10, ran at all).
    assert audited["status"] == "ok"
    assert audited["inclusion_status"] == "included"
    assert audited["replay_level"] == "state_and_score"


def test_audit_rejects_a_failing_trusted_declaration_even_though_the_plan_copy_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, direction 1, at audit_family_receipt: the
    durable receipt is sealed under a conforming (empty) trusted
    declaration, then audited under a DIFFERENT registry whose trusted
    registration declares a path guaranteed to fail R10. The plan's own
    copy (unchanged throughout) still declares none. audit_family_receipt
    must raise."""
    base_setup, execution = _run_housing_episode(tmp_path)
    base_manifest = base_setup.plan.families[0]
    real_plugin = base_setup.registry.resolve_manifest(base_manifest)

    conforming_registry = PluginRegistry()
    conforming_registry.register_trusted(base_manifest, real_plugin)
    finalize_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,
        registry=conforming_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    finalize_family_execution(setup=finalize_setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"

    failing_manifest = _with_trajectory_outcome_paths(base_manifest, ("/not_a_real_field",))
    failing_registry = PluginRegistry()
    failing_registry.register_trusted(failing_manifest, real_plugin)
    audit_setup = _FinalizeOnlySetup(
        plan=base_setup.plan,  # unchanged: plan's own copy still declares ()
        registry=failing_registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    with pytest.raises(AssertionError, match="does not exist in the outcome"):
        audit_family_receipt(setup=audit_setup, receipt_path=receipt_path)


def test_audit_passes_when_the_plan_copy_declares_a_failing_path_but_the_trusted_registration_is_empty(
    tmp_path,
) -> None:
    """Codex review R1 finding 1, the inverse direction, at
    audit_family_receipt: the plan's OWN manifest copy (poisoned_plan)
    declares a path guaranteed to fail R10; the TRUSTED registration
    declares none throughout. audit_family_receipt must still pass."""
    base_setup = build_housing_smoke(
        tenant_provider="housing_scripted_tenant",
        tenant_model="housing_scripted_tenant_v1",
        tenant_revision="1.0.0",
    )
    poisoned_plan, execution = _poisoned_plan_and_episode(
        tmp_path, base_setup, failing_paths=("/not_a_real_field",)
    )
    finalize_setup = _FinalizeOnlySetup(
        plan=poisoned_plan,
        registry=base_setup.registry,
        prompt_sources=base_setup.prompt_sources,
        pricing=base_setup.pricing,
    )
    finalize_family_execution(setup=finalize_setup, execution=execution)
    receipt_path = execution.evidence.root / "evaluation_receipt.json"
    audited = audit_family_receipt(setup=finalize_setup, receipt_path=receipt_path)
    assert audited["status"] == "ok"


# Codex review R1 finding 3: a pinned, pre-change golden oracle, not a
# two-episode comparison. Pinned on origin/main at 2318d748 (pre-change),
# via tests/test_shared_runner_family_scoring_input.py's `_run_housing_episode`
# fixture helper (Housing's scripted tenant/landlord providers, deterministic
# given a fixed `world_seed` -- verified empirically: two independent
# episodes produce byte-identical `episode_result.outcome` and
# `.phase_instances`). The receipt's OWN bytes are NOT run-to-run
# byte-identical even with that: EvidenceStore.__init__'s `clock` keyword
# defaults to `_utc_now` (src/aeread/shared_runner/task/execution.py:144-145,
# used at :493 for each event's `occurred_at`), a real wall-clock read, and
# `execute_plan_cell` never exposes a way to inject a fixed clock -- verified
# empirically: two independent episodes' sealed `event_root_sha256` (and
# therefore `receipt_sha256` and the full canonical receipt bytes) differ
# without freezing it. `EvidenceStore.__init__.__kwdefaults__["clock"]` is
# the default's storage location for this keyword-only parameter (confirmed
# empirically: monkeypatching the module-level `_utc_now` name does NOT
# affect it, because the default was already bound to the original function
# object at class-definition time) -- monkeypatching that dict entry for the
# duration of this test is what makes the oracle reproducible.
_GOLDEN_RECEIPT_SHA256 = (
    "9da456722207a991f5cddb4a69c797c23d41facbf4f38c81516c214c5fdb67e0"
)
_GOLDEN_CANONICAL_BYTES_SHA256 = (
    "141fd82cf55d2fe44a9eacbb1c9655ab9d391933faca48ac81fd7774180d0441"
)


def _freeze_evidence_store_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        EvidenceStore.__init__.__kwdefaults__,
        "clock",
        lambda: "2024-01-01T00:00:00.000000Z",
    )


def test_finalize_is_digest_neutral_with_no_declared_trajectory_outcome_paths(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`finalize_family_execution` on a family declaring
    `trajectory_outcome_paths == ()` must produce these EXACT, pre-change-
    pinned receipt bytes and this EXACT receipt_sha256 after this change --
    proving R10's replay-time check is a true no-op for the undeclared case,
    not merely "close". (Re-derive both golden constants above from scratch
    on the actual pre-change commit at implementation time, with this exact
    fixture and this exact clock freeze, rather than trusting the values
    transcribed into this plan; if they differ, the plan's values are wrong,
    not the implementation.)"""
    _freeze_evidence_store_clock(monkeypatch)
    setup, execution = _run_housing_episode(tmp_path)
    finalize_setup = _FinalizeOnlySetup(
        plan=setup.plan,
        registry=setup.registry,
        prompt_sources=setup.prompt_sources,
        pricing=setup.pricing,
    )
    receipt = finalize_family_execution(setup=finalize_setup, execution=execution)
    assert receipt.receipt_sha256 == _GOLDEN_RECEIPT_SHA256
    assert (
        hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
        == _GOLDEN_CANONICAL_BYTES_SHA256
    )
```

  NOTE for the implementer: re-derive `_GOLDEN_RECEIPT_SHA256` and
  `_GOLDEN_CANONICAL_BYTES_SHA256` yourself on the actual pre-change
  worktree before Task 2's production change lands (run the golden-oracle
  test's fixture-and-freeze sequence once, by hand, print the two hashes,
  and paste them in) — do not assume the values transcribed into this plan
  are correct for your checkout; they were computed once, empirically,
  against `origin/main` at `2318d748`, and must be re-verified against the
  actual merge base at branch-creation time the same way every other
  pinned fact in this plan is re-verified.

- [ ] 2. Run RED:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_trajectory_outcome_r10_production_callers.py
  ```
  Expected: the three "conforms" tests and the golden-oracle digest-
  neutrality test pass already if Task 2 landed correctly (they exercise no
  new behavior beyond Task 2) — if any of them fails here, Task 2 missed a
  call site; fix Task 2's production code, not this test. The six
  adversarial tests (finding 1, both directions, at each of the three
  production callers) must also pass once Task 2 landed correctly: the
  "rejects" tests fail loudly if a caller never threads
  `trajectory_outcome_paths` through at all, and the "passes" tests fail
  loudly if a caller reads the plan's own copy instead of the trusted
  registration.

- [ ] 3. If step 2 shows a missing or mis-sourced call site, the smallest
  production fix is exactly one line at that call site (the
  `trajectory_outcome_paths=registration.manifest.measurement.trajectory_outcome_paths`
  keyword Task 2 step 3 specified, reading `registration.manifest`, never
  `setup.plan.families[...]`); re-run step 2 until every test in this file
  passes with zero other production changes.

- [ ] 4. Run GREEN:
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q \
    tests/test_shared_runner_trajectory_outcome_r10_production_callers.py
  ```
  Expected: `10 passed` (3 conforming + 6 adversarial + 1 golden-oracle
  digest-neutrality test).

- [ ] 5. Commit:
  ```
  git add tests/test_shared_runner_trajectory_outcome_r10_production_callers.py
  git commit -m "test(evaluation): cover R10 sourcing and digest neutrality end to end"
  ```

- [ ] 6. Final full-suite verification (record the exact command and real
  output, per the ground rules — do not call this green without running it):
  ```
  cd "<worktree>" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src TMPDIR=/tmp \
    .venv/bin/python -m pytest -p no:cacheprovider -q
  ```

---

## Task 4 — docs note

### Files

- Modify: `docs/kernel_r9r10_review.md`

### Steps

- [ ] 1. Append a new top-level section after the existing
  `### Fifth-pass targeted verification` block (end of file, currently line
  747 at the pinned commit — re-confirm the line count first, it will have
  moved once Tasks 1–3 land and other doc edits may land before this one):

  ```markdown
  ## Issue #122 — production enforcement moves out of the protocol test

  **Finding.** Everything above this section describes `trajectory_outcome_paths`'
  JSON Pointer projection and ruling R10's consistency check as they lived in
  `tests/test_shared_runner_scoring_contract.py` — test helpers, never run by
  `finalize_family_execution`, `replay_family_receipt`, or
  `audit_family_receipt` on an ordinary production run. A family whose
  `outcome()` deterministically mis-copies its own trajectory verified
  against itself on every path except the scoring-contract protocol test's
  enrolled fixtures.

  **Disposition — fixed.** `src/aeread/shared_runner/run/json_pointer.py` is
  now the one production RFC 6901 parser/navigator; `schemas.py`'s
  `trajectory_outcome_paths` format validation and
  `task/evaluation.py`'s `_replay_family_trajectory` both consume it.
  `_replay_family_trajectory` enforces ruling R10 itself, immediately after
  computing the recomputed `outcome`, against the same `state` local
  variable the scoring-contract test's `_final_replayed_state` independently
  reconstructs. The declaration reaches it as a required
  `trajectory_outcome_paths: tuple[str, ...]` keyword (no default --
  omitting it is a `TypeError`, so no call site can silently fall back to
  the wrong source) threaded through `replay_family_state` /
  `replay_family_scoring_input`, sourced by each of the three production
  callers from `registration.manifest.measurement.trajectory_outcome_paths`
  — the trusted registered manifest, never the run-plan's own copy (same
  rule `kernel_contract_impl_review.md` finding 6 already established for
  leaf policy, now covered by adversarial tests in both directions). Every
  family that declares nothing passes `trajectory_outcome_paths=()`
  explicitly and stays byte-for-byte unchanged, pinned by a golden-oracle
  digest-neutrality test.

  **Test.** `tests/test_shared_runner_json_pointer.py` (the module in
  isolation); `tests/test_shared_runner_trajectory_outcome_r10_replay.py`
  (R10 at the replay function itself, including a corrupted-plugin mutation
  test proving the prior gap was real); `tests/test_shared_runner_trajectory_outcome_r10_production_callers.py`
  (all three production callers source the declaration correctly, and
  digest neutrality holds for the no-declaration case).
  ```

- [ ] 2. Commit:
  ```
  git add docs/kernel_r9r10_review.md
  git commit -m "docs: record issue #122's production R10 enforcement"
  ```

---

FINDINGS: 0 (revised after Codex review R1)
