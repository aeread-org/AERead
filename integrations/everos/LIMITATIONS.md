# What the memory integration does not do

`aeread.integrations.everos_memory` is experimental. This page states what it
cannot currently measure or guarantee, so that a result produced with it is read
at the strength it supports.

Nothing here is a defect report against [EverOS](https://github.com/EverMind-AI/EverOS).
Each item is either a property of how we drive the layer, a property of the task
class, or a capability that no memory service exposes today.

## 1. Memory-augmented episodes are not policy-replayable

A published AERead run replays byte-identically from its inference manifest. A
memory-augmented episode does not, because the memory state that produced the
actions lives outside the manifest. Byte-replay of the *recorded actions* still
passes, but that is action playback, not policy reproduction: re-running the
policy from the manifest alone would not reconstruct what the agent knew.

Consequences, both deliberate:

- A/B runs set `verify_replay=False`.
- Official leaderboard submissions remain **memory-off**. A verified row has to
  be reproducible by a third party, and today a memory-augmented one is not.

The fix is a memory-state manifest: hash the memory tree per episode, pin it
alongside the inference manifest, and restore it before a replay. That needs a
snapshot and restore API from the memory service. Until one exists, memory is
measurable here but not certifiable.

## 2. Retrieval is similarity-only

Search returns episodes, agent cases and skills ranked by embedding similarity.
There is no way to request a **content type** ("procedure, not specifics") or an
**abstraction level**, and items carry no outcome annotation, so ranking cannot
prefer material from episodes that went well.

We work around both client-side, and the workarounds are partial in a way worth
being precise about:

| workaround | what it cannot do |
|---|---|
| `overfetch` (search `top_k * overfetch`, filter, cap at `top_k`) | Filtering only reorders what similarity already surfaced. If the transferable item ranks below the fetch window, no filter reaches it. Ranking has to happen at the index. |
| outcome-aware recall (drop snippets from sessions whose realized AER we recorded, unless nothing better survives) | Only covers sessions **this candidate** scored. It cannot rank, only exclude, and it knows nothing about material written by other agents. |

## 3. Content type is partly our write policy, not the layer's

`end_episode` writes the full turn transcript and appends a reflection. With
`distill=True` the reflection is an LLM-written lessons summary that is
explicitly instructed to avoid world-specific quantities, but it is **appended
alongside** the transcript rather than replacing it. So the integration has
never withheld specifics from the layer, and the specifics-heavy mix of stored
content is a consequence of that choice as much as of any extraction default.

An arm that writes only the distilled lessons is a straightforward change and
has not been measured. Read any content-type conclusion from this integration
with that gap in mind.

## 4. The agent-case track needs tool calls

Agent-case extraction is gated on tool-call rounds. AERead agents act by
emitting natural language and have zero, so in a stock configuration that track
produces nothing while the episode track fills normally. The gate encodes a view
that agent memory is primarily for tool-using agents, which is a reasonable
product position and not an oversight; it simply does not fit this task class.

Two practical notes for anyone reproducing this: the threshold is a library
default rather than a server-side setting, and a flush that extracted nothing
for one track is not distinguishable from a successful one at the API surface
(the server logs do say why, and the skip reasons there are clear).

## 5. The runner's mute circuit breaker does not cover this path

AERead's runner trips a circuit breaker when too many under-test calls come back
empty. Its basis, `empty_llm_rows`, **excludes `submitted`-origin calls by
design**, because the no-op baseline is silent on purpose. The memory candidate
enters through that same text boundary, so its empty turns are counted as a
diagnostic and never gate.

Three failure modes here therefore produce a valid-looking pooled AER instead of
an error, and each is counted explicitly in the arm's `health` block instead:

| counter | failure it makes visible |
|---|---|
| `blank_turns` / `blank_turn_rate` | the candidate emitted nothing and the round scored as a deliberate no-op |
| `memory_snippets` | the arm injected nothing and is silently a second control. A live-but-empty server passes `memory_errors == 0`, so this is the only signal. Also checked during the run: a memory arm aborts after 3 completed episodes with zero injection. |
| `memory_errors` | some turns degraded to memoryless |

`everos_memory_ab.py` exits non-zero when an arm fails these, so an unhealthy
arm cannot be quietly pooled.

## 6. Statistical reach

The measured A/B is one case family, one model, and three sequences per
condition. Three sequences is the binding constraint on significance: the
control's between-sequence SD is 0.014, so a single-sequence memory comparison
on this benchmark cannot resolve effects of the size being argued about. Treat
any single-sequence memory result, here or elsewhere, accordingly.

The design also shares one memory scope across **different seeds**, which means
different worlds. That follows from AERead's stance against memorization: seeds
are randomized precisely so that recalling a specific world cannot be the source
of a score. A consequence worth stating plainly is that **this benchmark can
only reward procedural memory**, because any benefit from recalling world
specifics is, by its own definition, contamination. A design in which episodes
repeat the same world would make facts genuinely transferable and would be a
fair but different test, scored separately from the leaderboard.

## 7. Status, and what is unmeasured

Anyone picking this up should know which claims rest on measurement and which
do not.

**Measured.** Memory-on vs memory-off, `case03_hidden_discovery`, one model,
12 dev seeds, three independent sequences per condition, sequential so memory
accumulates. Reproduce with the command in the guide, adding
`--memory-project <fresh-scope>` per sequence so scopes do not share state.

**Not measured, in rough order of what would be worth learning:**

| open arm | change required |
|---|---|
| write only the distilled lessons, dropping the transcript | one branch in `end_episode`; this is the arm that tests §3 directly |
| retrieval restricted to procedural content | needs content-type selection at the index, so not reachable client-side today (§2) |
| a second case family, and a second model | configuration only; the current result is single-family, single-model |
| repeated episodes on the **same** world | would make facts genuinely transferable, and must be scored separately from the leaderboard for the reason in §6 |

**Before trusting any new arm**, read the `health` block in its `summary.json`.
The three counters in §5 exist because each of those failure modes produces a
plausible pooled AER rather than an error. `everos_memory_ab.py` exits non-zero
when an arm fails them, so a non-zero exit is a result to investigate, not a
run to retry blindly.

**Also worth knowing:** memory-augmented prompts are substantially larger than
the control's on identical seeds, so memory arms generate longer, and long
generations are where streaming-reassembly failures concentrate. Budget wall
clock accordingly.

## 8. Setup

Python **3.12+**. On 3.11, pip resolves to an older cloud-client package with a
different surface. The integration searches with `method="vector"`, which does
not reach the reranker stage, so no rerank provider is required.
