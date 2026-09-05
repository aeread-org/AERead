# tau3 retail adapter — status

Branch `zeyu/tau3-retail`. Last verified 2026-08-27.

## What the adapter claims

For each pinned tau2-bench retail task, it reproduces upstream's deterministic
result exactly, by delegating every tool body, database mutation, and scoring
rule to the pinned upstream checkout across a subprocess bridge. It publishes
two separately-labelled measurement leaves rather than one blended number:

| Leaf | Verifier family | Evaluation class | Declared when |
|---|---|---|---|
| `tau3_retail_db_state` | `canonical_reference` | `deterministic` | always — this is the paper-primary claim |
| `tau3_retail_nl_assertions` | `rater_judge` | `judge_dependent` | only when the task's `nl_assertions` list is actually non-empty |

The second condition is deliberate and load-bearing. 112 of the 114 tasks
*declare* `NL_ASSERTION` in `reward_basis`, but only 40 carry a non-empty
`nl_assertions` list; upstream short-circuits the rest to a deterministic 1.0
with no model call. Branching on the declaration rather than the content would
have attached a judged claim to the majority of the corpus that upstream never
actually judges.

### Why `tau3_retail_db_state` is primary, stated explicitly

Kernel scoring-contract ruling R8 requires every family's status doc to record why its
primary leaf was chosen, because no identifier validation can catch a family that wires every
name correctly and still picks the wrong leaf as headline (R8 is itself named after this
family: its `primary_estimand`, `"retail_task_reward"`, is a third string that names neither
leaf, and the kernel contract deliberately does not check it against either `estimand_id` --
see `docs/kernel_contract_design_critique.md`'s R8 resolution).

`tau3_retail_db_state` is primary because it is upstream tau2-bench's own deterministic,
always-computed reward and the number every published tau2-bench result reports; it is what
"reproduces upstream" (this doc's central claim) actually means. `tau3_retail_nl_assertions`
is real and receipted, but it is judge-dependent, present for only 40 of 114 tasks, and a
model-graded claim about a natural-language assertion -- exactly the kind of leaf R8 warns
could be mistaken for a headline result. Declaring it primary instead would have made "did an
LLM judge approve of the response text" the family's headline claim on 74 tasks where no judge
call happens at all, which is incoherent. Every identifier check in the kernel contract would
pass either way; this paragraph, not a validator, is what fixes the choice.

## Evidence

### First live pipeline-proof campaign

Issue #89 adds a deliberately small live campaign. The originally requested
GLM 5.3 Flash/Parasail route was unavailable in the owner's Arena API catalog;
the owner explicitly selected Arena's `glm-5p2` model instead. It runs one
unscored admission canary followed by five
scored cases, one from each predeclared pilot stratum, sequentially and with no
fallback. The driver aborts on the first operational failure, enforces a
per-trajectory ceiling of $0.05 and a total ceiling of $0.30,
checkpoints only
complete replayed receipts, and separates execution from publication.

Arena reports request cost in each response, so the driver records and enforces
those dollar ceilings. The canary reserves 256 output tokens because GLM 5.2
uses the same completion budget for hidden reasoning and visible JSON.
Arena may also return an ordinary customer-facing reply even when instructed
to emit the reply envelope. The adapter normalizes such completed prose only
when the declared schema explicitly permits `kind=reply`; malformed JSON and
non-reply schemas still fail the provider contract.
The assistant request also places the invariant policy and tool catalog before
the changing conversation state. This preserves the same observation while
giving Arena a stable prompt prefix to cache across turns; without that
ordering, repeated 5–8k-token uncached prefixes exhausted the assistant's
case-level budget before the episode completed.
The support seat reserves 4096 completion tokens because Arena counts hidden
reasoning and visible structured actions against one limit. The dollar ceiling
still governs actual spend, so this prevents truncation without expanding the
financial budget.

This is a **pipeline proof**, not an upstream behavioral-parity claim. Both the
retail assistant and customer simulator use GLM 5.2, and the harness uses
schema-constrained JSON actions rather than upstream's GPT-4.1 user simulator
and native provider tool calling. The deterministic database-state scorer and
pinned tau2 bridge remain the authoritative evaluation path.

Freeze and inspect the digest-bound plan before spending:

```bash
PYTHONPATH=src python -m aeread_families.tau3_retail.campaign \
  --run-root runs/tau3_retail_glm5p2_arena_pipeline_proof_v5
```

Execute only with the pinned bridge and skip-fail gate enabled:

```bash
AEREAD_TAU2_UPSTREAM_ROOT=$PWD/runs/upstream-tau2 \
AEREAD_TAU2_BRIDGE_PYTHON=$PWD/runs/tau2-bridge-venv/bin/python \
AEREAD_TAU2_BRIDGE_REQUIRED=1 \
PYTHONPATH=src python -m aeread_families.tau3_retail.campaign \
  --run-root runs/tau3_retail_glm5p2_arena_pipeline_proof_v5 \
  --upstream-root runs/upstream-tau2 --execute
```

Publication is a separate, provider-free operation and refuses incomplete or
digest-mismatched checkpoints:

```bash
PYTHONPATH=src python -m aeread_families.tau3_retail.campaign \
  --run-root runs/tau3_retail_glm5p2_arena_pipeline_proof_v5 \
  --publication-root evidence/tau3_retail_glm5p2_arena_pipeline_proof_v5 \
  --publish-only
```

**Full-corpus parity: all 114 retail tasks match upstream, component by
component.** Zero mismatched, zero skipped, zero errored — every task upstream
ships for this domain, not a sample. The 18-task pilot is the same procedure at
CI granularity and also matches 18 of 18.

Both sides execute the same gold actions — one directly through upstream's own
`Environment.get_response` with no plugin or scheduler involved, one through the
real kernel-facing path — and the two are compared on the initial database, the
ordered tool calls, their ordered results, the final database, the deterministic
DB-reward component, and the judged component's *inputs*.

Receipts: `docs/families/tau3-retail/receipts/corpus_parity.json` (all 114) and
`docs/families/tau3-retail/receipts/pilot_parity.json` (the 18-task pilot).

Regenerate either with the parity CLI, which exits non-zero on a skip:

```bash
PYTHONPATH=src python -m aeread_families.tau3_retail.parity \
  --upstream-root <pinned-checkout> --json docs/families/tau3-retail/receipts/pilot_parity.json
```

**Suite: 572 passed, 3 skipped, 1 xfailed** with `AEREAD_TAU2_BRIDGE_REQUIRED=1`.
The three skips are `rllm` integration tests (`No module named 'rllm'`), which
belong to the rLLM export work and are unrelated to this family.

**Mutation tested.** Three deliberate defects were injected. One was caught
immediately; two survived — a swallowed tool-error counter and a neutered
replay cross-check — proving those paths had no coverage at all. Both are now
covered and both mutations are killed.

**Deterministic across runs.** The pilot was executed twice, independently, and
the two receipts are byte-identical (SHA-256
`75270a673212fe693c9800be4d017ca7...`, 3674 bytes). Determinism here had been a
property of the implementation -- CPython float repr, no unicode normalisation
-- rather than a checked fact; it is now the latter, at least across runs on one
machine. Cross-machine and cross-Python-version reproduction is untested.

**Independently reviewed.** No critical findings. The review confirmed by
tracing upstream source, not spec prose, that termination semantics reproduce
`orchestrator.py`'s role-skip behavior and that the stop signals match
upstream's user simulator exactly.

## Why the bridge needs provisioning

Upstream requires Python >= 3.12 and nineteen dependencies; this project runs
on 3.11 and carries none of them. Without a provisioned bridge interpreter the
fidelity tests **skip rather than fail** — which is how the adapter's first full
run reported `544 passed, 29 skipped` while 26 of those skips were the entire
fidelity surface, never once executed.

```bash
tools/tau2_bridge/provision.sh
export AEREAD_TAU2_BRIDGE_PYTHON=<printed path>
AEREAD_TAU2_BRIDGE_REQUIRED=1 pytest    # fails if a fidelity test skips
```

See `tools/tau2_bridge/README.md`.

## What it costs to run

Each bridge call spawns a fresh subprocess that imports upstream from scratch,
measured at **~1.95s per call**, almost entirely import cost rather than work.
A parity task executes its gold actions twice — once directly through upstream,
once through the adapter — plus the database, reward, and judge-input
comparisons, which works out to a **median of ~78s per task**.

Timings vary more than the gold-action count explains: across the full corpus
the median was 78s while one task took 1032s and another with more gold actions
took 143s. The cause of the outliers was not isolated, so treat the median as
the planning figure and expect a long tail. The full 114-task sweep took 5.3
hours end to end.

That shapes where each belongs: the 18-task pilot is a few minutes and is the
right granularity for CI; a full 114-task sweep is a multi-hour job to run
deliberately, not on every push. The obvious optimisation — one persistent
bridge process instead of a subprocess per call — is not implemented, because
the current design buys real isolation: no state can leak between calls through
a long-lived interpreter, which is exactly the property that makes "the adapter
reproduces upstream" checkable. Worth revisiting only if corpus sweeps become
routine.

## Known limits, stated rather than implied

- **The judged leaf's output is never produced here.** Parity compares the
  prompt upstream *would* send, never a verdict; scoring reads already-recorded
  verdicts sealed as evidence. Nothing in this family calls a model.
- **Parity is proved on gold trajectories, not on model behaviour.** All 114
  tasks match, but the trajectory compared is each task's own
  `evaluation_criteria.actions` — the only reproducible, non-model trajectory
  tau2-bench ships. That establishes the adapter reproduces upstream's
  machinery exactly; it says nothing about how any agent scores.
- **Failed mutating calls were probed, not proved.** Four rejected mutating
  calls each left the database byte-identical, so upstream validates before it
  mutates on those paths. That is four probes across two tools, not a proof for
  all seven mutating tools and every error path.
- **`agent_stop` cannot occur in retail.** Upstream's `LLMAgent` never overrides
  `Participant.is_stop`, so only the user simulator can stop an episode. The
  case manifest previously declared it anyway; the vocabulary is now enforced.

## Open contract item for the kernel owner

Upstream's `tool_call_id` is not forwarded into the tool implementation, because
`ToolRuntime.invoke` takes `action_attempt_id` and has no parameter for it.
Changing that signature is shared kernel surface, so it has not been changed
here. The linkage is not lost: the harness records both the upstream
`tool_call_id` and the `invocation_record_id` in each execution entry. Whether
the kernel's tool ABI should carry the originating call id is a decision for
the kernel owner.
