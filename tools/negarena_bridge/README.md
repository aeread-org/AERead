# The upstream NegotiationArena bridge interpreter

The negarena adapter's central claim is that it reproduces upstream
`NegotiationArena` exactly: the two admission gates (trade legality, malformed-
action detection) and, eventually, settlement (`after_game_ends()`) are all
computed by upstream's own, unmodified code — never reimplemented here.

## Why a second interpreter

Unlike `tools/tau2_bridge/`, the blocker here is not a Python-version floor —
upstream's `pyproject.toml` declares no `[project]` table at all, so there is
no version requirement to clash with. The blocker is that importing **any**
upstream negarena module, including the "pure" game-object arithmetic in
`negotiationarena/game_objects/*.py`, transitively imports `openai` and
`anthropic` at module scope (`negotiationarena/utils.py` does
`from negotiationarena.agents import ChatGPTAgent, ClaudeAgent`; see
`docs/negarena_adapter_spec.md`'s governing facts and
`ledger_entries/negarena.md`). This project's own venv must never carry those
two packages, so the adapter delegates across a subprocess instead:
`src/aeread_families/negarena/negarena_bridge.py` spawns
`negarena_bridge_driver.py` under a separate interpreter that has them
installed, hands it a scripted response or a trade/resources pair, and gets
back upstream's own answer.

No API key is ever read and no network call is ever made by either package —
they exist purely to satisfy an import-time dependency this adapter never
exercises.

## A second, independent upstream import bug

`games/ultimatum/interface.py` (and `games/trading_game/interface.py`, out of
scope for this adapter) reference `negotiationarena.agent_message.AgentMessageInterface`,
which does not exist at the pinned commit — only `AgentMessage` does. This is
a permanent defect in upstream's current `main` (verified via `git log`/`git
show`; see `ledger_entries/negarena.md`), not a artifact of pin selection.
`negarena_bridge_driver.py` works around it with a narrow, documented
compatibility alias set on the already-imported module object, immediately
before importing any `ultimatum` interface module. It never modifies the
read-only upstream checkout and never reimplements `AgentMessage`'s body.

## Usage

```bash
tools/negarena_bridge/provision.sh   # defaults to bridges/negarena-venv (see script)
export AEREAD_NEGARENA_BRIDGE_PYTHON=<printed path>
```

The adapter also accepts a venv colocated at `<upstream_root>/.venv/bin/python`
without any environment variable; see `discover_bridge_python` in
`negarena_bridge.py`.

## On pinning

`requirements.txt` pins `anthropic==0.5.0` (upstream's own
`requirements_dev.txt` value; still exports the legacy `Anthropic`,
`HUMAN_PROMPT`, `AI_PROMPT` names `claude.py` imports). It does **not** pin
`openai` to upstream's frozen `requirements_dev.txt` value (`0.28.1`): that
version predates the `from openai import OpenAI` client-class import
`chatgpt.py` actually uses at this pin, so a modern `openai` (>=1.0) is
installed instead. This is itself a small upstream inconsistency (their own
frozen dev requirements do not match their own imports) — importability, not
a version claim, is all this bridge needs.
