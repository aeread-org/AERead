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

## Evidence

**Pilot parity: 18 of 18 tasks match upstream, component by component.**
Zero mismatched, zero skipped, zero errored. Both sides execute the same gold
actions — one directly through upstream's own `Environment.get_response` with
no plugin or scheduler involved, one through the real kernel-facing path — and
the two are compared on the initial database, the ordered tool calls, their
ordered results, the final database, the deterministic DB-reward component, and
the judged component's *inputs*.

Receipt: `docs/tau3_pilot_parity_receipt.json`. Regenerate it with

```bash
PYTHONPATH=src python -m aeread_families.tau3_retail.parity \
  --upstream-root <pinned-checkout> --json docs/tau3_pilot_parity_receipt.json
```

**Suite: 572 passed, 3 skipped, 1 xfailed** with `AEREAD_TAU2_BRIDGE_REQUIRED=1`.
The three skips are `rllm` integration tests (`No module named 'rllm'`), which
belong to the rLLM export work and are unrelated to this family.

**Mutation tested.** Three deliberate defects were injected. One was caught
immediately; two survived — a swallowed tool-error counter and a neutered
replay cross-check — proving those paths had no coverage at all. Both are now
covered and both mutations are killed.

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

## Known limits, stated rather than implied

- **The judged leaf's output is never produced here.** Parity compares the
  prompt upstream *would* send, never a verdict; scoring reads already-recorded
  verdicts sealed as evidence. Nothing in this family calls a model.
- **The pilot is 18 tasks, not 114.** The importer handles all 114; parity has
  been executed on the 18-task pilot.
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
