# The pandas bridge interpreter for the `steer` adapter

The `steer` adapter wraps STEER (`narunraman/STEER`, pinned at
`d66673c8277b9112fc5e39751524ccda6d852446`) without a repo license: real
question/option text can never enter the AERead git repository (see
`docs/steer_adapter_spec.md`). It is fetched once, hash-verified against the
pinned checkout's own git-LFS pointers, and cached outside version control at
`bridges/steer-data/` (a sibling of the AERead repo).

## Why a second interpreter

Every `elements/<name>/*.pkl` file in the pinned checkout is a
pandas-serialized dataframe. Unpickling it requires pandas, and the
project's own venv (Python 3.11) deliberately does not carry it -- a
missing-package gap, not a Python-version one. Rather than installing pandas
into that venv, the importer delegates the one pandas-dependent step --
unpickle, join on `question_id`, probe the `Answers` schema, classify and
admit rows -- to a small driver script
(`src/aeread_families/steer/steer_bridge_driver.py`) run under a SEPARATE,
already-provisioned interpreter. `src/aeread_families/steer/steer_bridge.py`
spawns that driver as a subprocess, one call per declared element, and gets
back plain JSON: admitted rows, per-question-id exclusion reasons, and the
exactly-one/zero/multi-correct counts.

Nothing downstream of this one flatten step needs pandas. The driver writes
`bridges/steer-data/<element>/cases.jsonl` (plain JSON, real question/option
text, never committed); the importer (`cases.py`) reads that file with the
standard library `json` module to build the committed `CaseManifest`s, whose
`payload` never carries the text itself -- only `source_sha256` and the
`options_count`. The kernel environment plugin (`environment.py`) reads the
same cached JSONL at runtime, re-verifying `source_sha256` each time, and
never imports pandas or spawns the bridge.

## The failure mode this exists to prevent

Without that interpreter, the Gate-1 corpus-admission tests do not fail.
They **skip**. That is the right behavior for someone working on an
unrelated part of the repo, and a trap everywhere else: a green suite would
then mean "the schema-drift and admission-count regression guards never
ran", not "the corpus still admits what the spec's Governing Facts table
says it does".

`provision.sh` makes the interpreter one command to obtain, and verifies it
can import the pinned pandas version rather than trusting that `pip` exited
zero.

That covers only `test_steer_cases.py`'s own two extra prerequisites (this
interpreter and the pinned upstream checkout). The flattened cache at
`bridges/steer-data/` gates all six `test_steer_*.py` modules the same way,
and the same trap applies: without it, they skip rather than fail, and a
multi-module run can go green while none of steer's tests ran at all
(reproduced in `tests/test_steer_fixtures_required.py`, docs/steer_codex_
triage.md finding 5). `AEREAD_STEER_FIXTURES_REQUIRED=1` (see the root
`conftest.py`) turns any of those fixture-related skips into a failed run
instead. It is opt-in and off by default so it never surprises a local run,
and it is **not** set by `.github/workflows/ci.yml`'s generic `test` job:
unlike a licensed upstream, provisioning it automatically would mean this
family's own CI fetching a no-license corpus over the network on every
push, which `steer_bridge_driver.py`'s `fetch` operation is deliberately
never invoked to do outside an explicit, manual step (see "No network in
tests" below). Set it yourself for any run meant to certify fidelity.

## Usage

```bash
tools/steer_bridge/provision.sh                  # defaults to ~/.cache/aeread/steer-bridge-venv
export AEREAD_STEER_BRIDGE_PYTHON=<printed path>

pytest tests/test_steer_cases.py

# and to certify none of the six steer modules silently skipped:
AEREAD_STEER_FIXTURES_REQUIRED=1 pytest tests/test_steer_cases.py \
  tests/test_steer_environment.py tests/test_steer_measurement.py \
  tests/test_steer_goldens.py tests/test_steer_e2e.py tests/test_steer_replay.py
```

The adapter also accepts a venv colocated at
`<sibling-of-the-AERead-repo>/bridges/steer-venv/bin/python` without any
environment variable; see `discover_bridge_python` in
`src/aeread_families/steer/steer_bridge.py`.

## No network in tests

`steer_bridge_driver.py`'s `flatten` operation (the one every test uses)
never makes a network call: it reads the already-cached bytes at
`bridges/steer-data/<element>/*.pkl` and re-verifies their sha256 against the
git-LFS `oid` recorded in the pinned upstream checkout's pointer files (a
local, offline read). The one operation that does reach the network --
fetching those bytes from `media.githubusercontent.com` the first time -- is
a separate, explicit `fetch` operation, never invoked automatically by the
importer, the environment plugin, or any test.
