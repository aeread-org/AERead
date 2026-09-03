# Implementation Specification — `tau3.retail` adapter for the AERead shared-runner kernel

**Scope.** Run tau2-bench retail/`base` (upstream pinned at `fc0055dc4e0a316c3f83133267fbd6faaa770992`) inside the AERead kernel. "tau3" is AERead's family name for this pinned import; "upstream" always means the tau2-bench checkout at that commit. Milestone 1 is an 18-task pilot gated on component-level parity against upstream (§8), not the 114-task corpus. The DB-equality component and the LLM-judge component are declared as **separate measurement leaves** and never folded into one score inside the kernel.

**Governing facts** (verified in recon; do not re-derive):
- 114 tasks, ids are the strings `"0"`–`"113"`; `base` = the entire file (train ∪ test, no overlap). All 114 have `initial_state: null` — every episode starts from the same unmodified `db.json` (2,811,616 bytes, sha256 `413a65160adbdb5fde0ffc0015c49b6d70250b10c18128de169b597af7766765`).
- `reward_basis` is `{DB, NL_ASSERTION}` for 112 tasks, `{DB}` for 2 (ids `33`, `34`). `COMMUNICATE`/`ACTION`/`ENV_ASSERTION` never gate. The NL judge actually fires for only the **40** tasks with non-empty `nl_assertions`; for the other 72 it short-circuits deterministically to 1.0 with no LLM call.
- Upstream's DB check is hash equality: `sha256(json.dumps(db.model_dump(), sort_keys=True, default=str))`, all-or-nothing.
- The retail tool/DB layer is fully deterministic, **including a real bug** in `modify_pending_order_items` (stale `variant` across the second loop for multi-item calls) that the gold replay exercises. Byte-exact parity therefore requires **delegating to upstream code, never reimplementing tool bodies**.
- Upstream's own re-grade path (`tau2 evaluate-trajs`) re-invokes the NL judge; recorded verdicts, not re-invocation, are the only reproducible form of that component.

---

## 1. Upstream dependency and pinning

- Install the `fc0055dc` checkout as an importable package (`pip install -e <checkout>` into the adapter's environment). The checkout has **no `.git`**, so upstream's own `get_commit_hash()` reports `"unknown"`; the pin is tracked by the adapter, never read from upstream.
- Build step 1 produces `pins.json`, consumed by the importer and embedded per-case (§3):

```json
{
  "upstream_repo": "tau2-bench",
  "upstream_commit": "fc0055dc4e0a316c3f83133267fbd6faaa770992",
  "db_sha256": "413a65160adbdb5fde0ffc0015c49b6d70250b10c18128de169b597af7766765",
  "db_bytes": 2811616,
  "tasks_sha256": "<computed at import>",
  "policy_sha256": "<sha256 of data/tau2/domains/retail/policy.md>",
  "user_sim_guidelines_sha256": "<sha256 of the selected simulation_guidelines*.md>",
  "tool_schema_sha256": "<get_dict_hash({t.name: t.openai_schema for t in env.get_tools()})>",
  "greeting_message": "<verbatim upstream initial assistant message>",
  "max_steps": "<upstream orchestrator default, read from config at import>",
  "judge_model": "gpt-4.1-2025-04-14", "judge_args": {"temperature": 0.0},
  "user_sim_model": "gpt-4.1-2025-04-14", "user_sim_args": {"temperature": 0.0}
}
```

There is no static tool-schema file upstream; `tool_schema_sha256` is computed from the runtime-derived OpenAI schemas and re-verified at every episode start (abort on mismatch).

## 2. Module layout

```
aeread_families/tau3_retail/
    __init__.py       # registers the plugin under family_id "tau3.retail", version "0.1.0"
    plugin.py         # Tau3RetailPlugin: the 13 registry hooks (10 live + 3 registration stubs)
    cases.py          # importer: upstream tasks.json -> 114 CaseManifest JSON files + pins.json
    conversation.py   # Tau3RetailState, message shapes, phase graph, step/terminal logic
    tools.py          # 16 ToolDefinition/ToolBinding wrappers over upstream RetailTools
    harness.py        # adapter-owned response source: agent LLM, user-simulator LLM, tool loop
    measurement.py    # the two MeasurementLeafSpec declarations + their scorers
    recorder.py       # episode record schema + exporter to upstream SimulationRun format
    replay.py         # offline replayer (zero network)
    parity.py         # pilot parity runner + report
cases/tau3_retail/base/
    tau3.retail.base.0.json ... tau3.retail.base.113.json
    pins.json
```

The three registry-required-but-unused hooks (`build_scorer`, `build_reference_providers`, `generator`) are implemented as real callables: `build_scorer` returns the scorer from `measurement.py` (so it becomes live the day the kernel calls it), `generator` returns `None`, `build_reference_providers` returns the gold-DB provider.

## 3. Task → case record mapping

One upstream task → one `CaseManifest` (spec `"aeread.case/0.1"`), written by `cases.py`:

| field | value |
|---|---|
| `case_id` | `tau3.retail.base.<n>` (e.g. `tau3.retail.base.108`) — dot-separated; the id grammar (and a known GRPO grouping bug) forbids colons |
| `family_id` / `family_version` | `tau3.retail` / `0.1.0` |
| `split` | `"base"` |
| `world_seed` | `int(upstream id)` — deterministic and injective; tau2 has no intrinsic world seed (see UNRESOLVED Q2) |
| `seats` | `(SeatSpec(id="assistant", role="assistant"), SeatSpec(id="user", role="user"))` — the environment is **not** a seat |
| `episode` | `EpisodeSpec(max_logical_actions=<pins.max_steps>, termination=("agent_stop","user_stop","max_steps","error"))` — declarations only; authoritative termination is the family's upstream-mirrored step counter (§4). Termination labels mirror upstream's `TerminationReason` enum, lowercased |
| `visibility_policy` | kernel-standard value for asymmetric information (see UNRESOLVED Q3) |
| `payload` | `{"task": <the verbatim upstream task record, unmodified>, "pins": <pins.json contents>}` |
| `provenance` | `ProvenanceSpec(generator_id="tau3_retail_importer", generator_version="0.1.0", review_status="upstream_pinned")` |
| `upstream_task_id` | the upstream string, e.g. `"108"` |
| `content_sha256` | computed by the kernel resolver |

Notes:
- The full 2.8MB `db.json` is **not** embedded (114 copies ≈ 320MB); the payload carries its sha256 pin and `initial_state` loads-and-verifies from the installed upstream package. Consequence: `content_sha256` covers the pin, not the DB bytes — acknowledged.
- `ProvenanceSpec` cannot carry the upstream commit/db/policy/schema hashes first-class; they live in `payload.pins` and in every episode record until a receipt schema exists.
- The importer is deterministic: two runs must produce byte-identical manifests (parity check P1).
- `evaluation_criteria.reward_basis` is read **per task from the payload**, never assumed per-domain (upstream's own docs are wrong about retail).

Pilot ids (all verified to exist; look up as strings): `"14","53","73","108","10","11","82","83","5","48","84","91","16","28","103","104","30","46"`. Task `"5"` carries an open upstream issue annotation (agent may skip authentication); it stays in the pilot because the parity target is upstream behavior including quirks.

## 4. Conversation → phase and decision-slot model

### 4.1 Family state (canonically serializable dict, kernel-custody)

```json
{
  "db":              { "...": "RetailDB.model_dump(), full DB" },
  "messages":        [ "upstream-shaped message dicts (assistant/user/tool), lossless" ],
  "upstream_step_count": 0,
  "consecutive_error_count": 0,
  "termination": null
}
```

Message dicts use upstream's own `model_dump()` shapes (from `data_model/simulation.py`) so export to `SimulationRun` (§7) is lossless. `initial_state(case, cell)`: load `db.json` from the installed upstream package, verify sha256 against `payload.pins`, seed `messages` with the pinned upstream greeting (`pins.greeting_message`, assistant-authored), counters zero.

### 4.2 Phase graph — `phases()`

Two single-actor phases; strict alternation with an assistant self-loop:

```
(initial state: greeting in transcript)
  → user_turn        mode="single", eligible_actors → ["user"]
  → assistant_turn   mode="single", eligible_actors → ["assistant"]
       ├─ assistant message with tool calls → next = assistant_turn  (self-loop)
       ├─ assistant plain text              → next = user_turn
       └─ termination condition             → terminal
  user_turn: user stop-sentinel → terminal, else next = assistant_turn
```

`sequential` mode is explicitly not used (it transitions per actor inside one phase instance, which does not match the alternation).

### 4.3 One logical action

**One assistant decision slot = one assistant LLM message together with the execution of all tool calls it contains and their results.** The upstream ENV round-trip is *not* a decision slot (the kernel has no ENV seat); it is absorbed into the assistant action as follows:

1. `observe(case, state, "assistant", phase)` returns a self-contained observation: policy-text identity (`policy_sha256`), the assistant-oriented message list (full text, not hashes), and `tool_schema_sha256`.
2. The **harness** (adapter-owned response source, §6) calls the agent model. If the response contains tool calls, the harness executes them **in list order** (upstream orchestrator semantics) via `ToolRuntime.invoke` against its live upstream `Environment`, collecting `(result, ToolInvocationRecord)` per call.
3. `parse_action` wraps everything into one parsed action:

```json
{ "kind": "assistant_message",
  "message": { "content": "...", "tool_calls": [ ... ] },
  "tool_executions": [
    { "tool_call_id": "...", "name": "...", "arguments": { },
      "result": "...", "error": false, "invocation_record_id": "..." } ],
  "raw_response": "<verbatim provider payload>" }
```

4. `legal` always passes — upstream has no illegal actions; malformed/failed tool calls become in-band error tool messages via upstream's own `make_tool_call` error path, which the wrapper preserves byte-for-byte.
5. `step()` (sync, pure function of state+action): re-validate `state["db"]` into a `RetailDB`, bind upstream `RetailTools` to it, **re-execute** each tool call, and require each result to equal the harness-recorded result under canonical JSON comparison — mismatch aborts the episode as an infrastructure error. (This is upstream's `strict_replay` guarantee enforced live, and it is what makes offline replay through `step()` provably equivalent to the live run.) Append assistant + tool messages, store the updated `db` dump, advance `upstream_step_count` by upstream's orchestrator accounting rule (copied verbatim from `orchestrator.py:881-900` at the pin: increments per participant message *and* per environment round-trip — this is why `EpisodeSpec.max_logical_actions` is a non-binding declaration and the in-state counter is authoritative).

The user turn is symmetric and simpler: harness calls the user-simulator model on the flipped-role view (upstream `flip_roles` semantics; observation carries the flipped messages plus `user_scenario` and guidelines identity); `parse_action` detects the sentinels `###STOP###` / `###TRANSFER###` / `###OUT-OF-SCOPE###`; `step()` appends the message and either terminates (`user_stop`) or routes to `assistant_turn`.

`terminal()` returns a termination record when `state["termination"]` is set or `upstream_step_count ≥ pins.max_steps`. `outcome()` returns `{"final_db_sha256": <upstream get_dict_hash of state db>, "termination_reason": ..., "upstream_step_count": ..., "message_count": ...}`. Upstream's rule that any termination other than `agent_stop`/`user_stop` forces reward 0 is applied in the scorers, mirroring `evaluator.py:119-129`.

Performance note: `step()` revalidates/redumps a 2.8MB DB per action. Fine for the 18-task pilot; a state-hash-keyed live-env cache is a permitted pure optimization later.

## 5. Tool registration

Sixteen `ToolBinding`s, one per upstream tool, constructed in `tools.py` and given to `ToolRuntime(evidence, bindings)` by the harness at episode start.

- `tool_id` = upstream name (`cancel_pending_order`, …) — already grammar-valid.
- `tool_version` = `"0.1.0"`; the upstream commit rides in `payload.pins` (see UNRESOLVED Q5 on version-string format).
- `effect` = `"mutating"` for exactly the 7 WRITE tools (`cancel_pending_order`, `exchange_delivered_order_items`, `modify_pending_order_address`, `modify_pending_order_items`, `modify_pending_order_payment`, `modify_user_address`, `return_delivered_order_items`); `"read_only"` for the 7 READ + 2 GENERIC (`calculate`, `transfer_to_human_agents`). This equals upstream's `mutates_state` exactly.
- `input_schema` = upstream `Tool.openai_schema["function"]["parameters"]` (runtime-derived from signature + docstring); the aggregate hash is `pins.tool_schema_sha256`.
- `idempotency_supported` = `False` for all 16 (upstream tools are not idempotent — e.g. gift-card balance mutations would double).
- `implementation` = async wrapper delegating to upstream's `Environment.make_tool_call` path on the harness-held env, so success payloads **and error strings** match upstream byte-for-byte. Never reimplement tool bodies (the multi-item `modify_pending_order_items` bug must be reproduced, and delegation reproduces it by construction).
- `state_reader` (required for every mutating tool): **one shared reader** for all seven — `lambda: harness_env.get_db().model_dump()`, i.e. the complete `RetailDB` dump (plain JSON-compatible, canonically serializable). Per-tool narrower readers are forbidden: e.g. `cancel_pending_order` mutates both `orders` and `users` (gift-card balances), so only the whole-DB snapshot captures every mutation. `ToolRuntime` snapshots before/after and records hashes/diffs in `ToolInvocationRecord`.

Two things `ToolDefinition` cannot carry, handled elsewhere: (a) tool **descriptions** — the harness builds the provider-facing tool list directly from upstream `openai_schema` (name + description + parameters), independent of `ToolDefinition`, which exists for evidence/identity; (b) argument validation — `ToolRuntime` does not validate against `input_schema`, and neither does upstream (bad arguments become upstream-formatted error results); the adapter deliberately matches upstream and does **not** add validation.

## 6. Harness (adapter-owned response source)

The kernel's `execute_plan_cell()` hardcodes a no-tools `MinimalChatExecutor` and never constructs a `ToolRuntime`; per the portability contract, the tool loop is adapter-owned. `harness.py` therefore implements the response source that serves both decision seats:

- **assistant seat**: system prompt = upstream `SYSTEM_PROMPT` construction (`policy.md` text only — upstream sends no tool text in the prompt); tools passed as provider function-calling schemas; model/args are run configuration.
- **user seat**: upstream `UserSimulator` prompt construction (guidelines + `user_scenario` + flipped history), pinned model `gpt-4.1-2025-04-14`, temperature 0, provider `seed` kwarg plumbed like upstream (`set_seed`). Port prompt assembly by importing upstream builders wherever importable; where not, copy verbatim and pin by hash.
- Executes the per-slot tool loop of §4.3 and returns the raw provider payload for recording.

Trial seeding for the pilot follows upstream: `random.seed(300)`, `seeds = [randint(0, 1000000) ...]`, `seeds[trial]` shared across tasks within a trial index; the seed is recorded per episode.

## 7. Measurement declarations — two separate leaves

No composed score is sealed by the kernel (`composition_kind` is fixed to `"leaf"`); the upstream product is a *derived* quantity in the parity report only.

**Leaf 1 — `tau3_retail_db_state` (deterministic).** Declared for all 114 tasks.

```python
MeasurementLeafSpec(
  estimand = EstimandSpec(name="tau3_retail_db_state", input_scope="terminal_state",
                          direction="none", units="pass", ...),
  reference = ReferenceSpec(name="tau3_gold_database",
                            reference_kind="terminal_state_equivalence",
                            input_scope="terminal_state", units="pass", ...),
  verifier = VerifierSpec(verifier_family="canonical_reference",
                          evaluation_class="deterministic", reference=reference),
)
```

Scorer: (1) gold hash — fresh `db.json` load, replay `evaluation_criteria.actions` via upstream `make_tool_call`, `get_dict_hash(model_dump())` (identical to `evaluator_env.py:104-115`); (2) predicted hash — computed two ways as a self-check: from the kernel terminal state's `db`, and by upstream-style `set_state` replay of the exported transcript's tool calls; both must agree, and the score is 1.0 iff predicted == gold (string equality of sha256). Termination-reason forcing (non-`agent_stop`/`user_stop` → 0.0) applied here. Concretely, the scorer **imports and calls upstream `EnvironmentEvaluator`** on the exported `SimulationRun` + `Task` rather than reimplementing.

**Leaf 2 — `tau3_retail_nl_assertions` (judge-dependent).** Declared **only** for tasks with a non-empty `nl_assertions` list (40/114 corpus-wide). For the 72 tasks where `NL_ASSERTION` sits in `reward_basis` with an empty list, upstream's component is a deterministic 1.0 no-op; no judge leaf is declared and the fact is recorded as a note (see UNRESOLVED Q8).

```python
MeasurementLeafSpec(
  estimand = EstimandSpec(name="tau3_retail_nl_assertions", input_scope="transcript",
                          units="pass", ...),
  reference = ReferenceSpec(reference_kind="rubric_score", ...),   # rubric = the task's nl_assertions
  verifier = VerifierSpec(verifier_family="rater_judge",
                          evaluation_class="judge_dependent", reference=reference),
)
```

Scorer: build the judge request with upstream `NLAssertionsEvaluator`'s prompt construction (model `gpt-4.1-2025-04-14`, temperature 0, no caching upstream), call once, parse to `{nl_assertion, met, justification}` triples, score 1.0 iff all met. The raw request, raw response, and parsed verdicts are sealed as evidence; **replay reads the recorded verdicts and never re-calls the judge** (upstream's `evaluate-trajs` re-invokes the judge and is explicitly not judge-deterministic — do not imitate it). Judge model + args + prompt hash are recorded per envelope since `VerifierSpec` has no dedicated judge-provenance fields.

Because the current kernel neither invokes scorers nor attaches `ScoreEnvelope`s to `CellExecution`, both envelopes are produced and sealed by the adapter as artifacts alongside the episode record (UNRESOLVED Q4).

## 8. Parity procedure (pilot gate)

Corpus: the 18 pilot ids, one live trial each (parity gates on scoring identity, not statistics; pass^k and trial conventions are corpus-phase concerns). Oracle: upstream `evaluate_simulation` at `fc0055dc`.

- **P1 — Import determinism.** Importer run twice → byte-identical 114 manifests; `pins.json` matches the constants in §1 (notably `db_sha256`, `db_bytes`).
- **P2 — Gold-hash parity.** For each of 18 tasks, the adapter's gold construction equals the hash from calling upstream's gold path directly. 18/18 string-equal.
- **P3 — Export fidelity.** Each kernel episode exports to a `SimulationRun`; upstream `Environment.set_state(strict=True)` replays it without divergence, and the resulting DB hash equals the kernel terminal outcome's `final_db_sha256`. 18/18.
- **P4 — Component parity.** Run oracle `evaluate_simulation` once per exported run, with upstream's NL `generate` patched to (a) assert its request — messages, model, args — is byte-identical to the adapter's recorded judge request, then (b) return the adapter's recorded raw judge response (single real call, shared verdicts). Require: leaf-1 == oracle breakdown `DB`; leaf-2 == oracle breakdown `NL_ASSERTION` (where declared); derived product leaf1 × leaf2 == oracle `RewardInfo.reward` exactly (all values are 0/1); termination handling identical. 18/18.
- **P5 — Offline replay.** With network disabled, replay every episode per §9: every transition state hash matches, terminal outcome matches, leaf-1 recomputes equal, leaf-2 reproduces from recorded verdicts. 18/18.
- **P6 — Bug preservation.** Unit test drives a multi-item `modify_pending_order_items` through the adapter tool layer and asserts the exact upstream post-state (last item's price/options overwriting all exchanged items) — guards against any future reimplementation. Also check whether any pilot gold trajectory contains a multi-item call; if so P2 already covers it live.

Any failure blocks the milestone. Optional hardening (not gating): re-score one upstream-CLI-generated results file with the adapter scorers.

## 9. Episode record for offline replay

Sealed per episode (this is the complete no-model-ever-again replay set):

1. `case content_sha256` + full manifest (contains the verbatim task and pins).
2. Run config: agent model + args, user-sim model + args, judge model + args, trial index, seed, adapter version.
3. Ordered decision log — per slot: phase, seat, full observation, **verbatim raw provider response**, parsed action, provider request params (+ response id / system fingerprint where available).
4. All `ToolInvocationRecord`s (args, results, before/after state hashes, diffs).
5. Kernel transition state hashes per step.
6. Termination reason + terminal outcome (incl. `final_db_sha256`, `upstream_step_count`).
7. Upstream-format `SimulationRun` export.
8. Judge evidence (leaf-2 tasks only): exact request messages, raw response, parsed `{nl_assertion, met, justification}` verdicts.
9. Both `ScoreEnvelope`s.

**Replay =** rebuild `initial_state` from the pinned upstream data, fold the recorded parsed actions through `step()` (whose in-state tool re-execution regenerates all tool results deterministically), assert every state hash and the terminal outcome, recompute leaf 1 from replayed state + gold replay, reproduce leaf 2 from item 8. Zero network calls; the recorded verdicts are the only reproducible form of the judge component.

## 10. Ordered build steps

| # | Step | Size |
|---|---|---|
| 1 | Pin upstream as installable package; compute and check in `pins.json` | ~0.5 day, small script |
| 2 | `cases.py` importer + 114 manifests + pilot-id validation | ~200 LOC, 0.5–1 day |
| 3 | `tools.py`: 16 definitions/bindings, shared state reader, schema hash | ~250 LOC, 1 day |
| 4 | `conversation.py` + `plugin.py`: state model, phases, hooks, `step()` with re-execution cross-check, upstream step accounting | ~550 LOC, 2–3 days |
| 5 | `harness.py`: agent + user-sim response source, ToolRuntime loop, sentinels, seeding | ~400 LOC, 2–3 days |
| 6 | `measurement.py`: two leaf specs + scorers delegating to upstream evaluators | ~300 LOC, 1–2 days |
| 7 | `recorder.py` + `replay.py`: record schema, `SimulationRun` exporter, offline replayer | ~300 LOC, 1–2 days |
| 8 | `parity.py`: P1–P6 runner + pilot execution + report | ~250 LOC + run time, 1–2 days |
| 9 | Tests woven throughout (P6 bug test, importer determinism, sentinel parsing, termination mapping, gold hashes) | ~1 day |

Total ≈ 2 working weeks for one engineer.

## 11. UNRESOLVED — decisions needed from a human or the kernel owner

1. **Execution path**: `execute_plan_cell()` hardcodes a no-tools executor, never builds a `ToolRuntime`, and attaches no scores ("R5+ stages"). Does the pilot run through an adapter-owned driver that mimics the scheduler loop (this spec's assumption), or must a kernel change land first — and who owns it?
2. **`world_seed`**: tau2 has no intrinsic world seed. Is `world_seed = int(upstream id)` acceptable, or should it carry something else (it cannot be the per-trial simulation seed without making case identity vary per trial)?
3. **Vocabulary gaps**: what `SeatSpec.role` strings does the resolver's role cross-check expect, and what are the legal `visibility_policy` values for an asymmetric two-party conversation?
4. **Score custody**: is adapter-sealed `ScoreEnvelope`-as-artifact (outside `CellExecution`) sufficient for the paper's typed claims until R5, given there is also no typed composition record for upstream's `DB × NL_ASSERTION` product?
5. **Two small contract discrepancies**: the documented `legal(..., action: ActionEnvelope)` signature conflicts with execution (which passes `parsed.action`) — code wins?; and does the `tool_version`/semver grammar permit build-metadata (e.g. `0.1.0+fc0055dc`) or must the upstream pin stay only in `payload.pins`?
6. **Pilot models/budget**: which agent model generates the 18 pilot trajectories, and are keys/budget available for the pinned user-sim and judge model (`gpt-4.1-2025-04-14`)?
7. **Judge-parity standard**: is prompt-byte-equality plus a single shared judge call (P4) an acceptable definition of component-level parity for the judge leaf, or does the paper require an empirical judge-stability study (k repeated calls) in the pilot?
8. **Empty-list NL tasks**: for the 72 tasks with `NL_ASSERTION` in `reward_basis` but an empty assertion list, this spec declares *no* judge leaf (the component is a deterministic 1.0 no-op). Does the paper's claim structure agree that "judge-dependent" is labeled only where a judge actually fires?
9. **Trial-failure convention (corpus phase)**: upstream's library default excludes infrastructure-error runs from metrics while its leaderboard convention counts them as failures — which does AERead adopt for the 114-task run?
10. **Task `"5"`**: it carries an open upstream issue (authentication-bypass annotation). Confirm it stays in the pilot on the "parity includes upstream quirks" rationale.
