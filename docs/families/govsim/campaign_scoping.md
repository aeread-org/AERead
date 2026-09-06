# GovSim live campaign (#91): scoping, and the one decision it needs

Written after building econevals' first live path (#90, PR #107), whose
thirteen defects double as a checklist for every remaining adapter.

## Correction to an earlier scoping note

I previously reported that govsim "already has a `FamilyScoreSet` finalizer,
so #91 needs only `live.py` + `campaign.py`". That was from a grep for
`__call__` and it is wrong. `GovsimScorer.__call__` takes a **recorded
outcome mapping** and returns a **single** `ScoreEnvelope`:

```python
def __call__(self, outcome: Mapping[str, Any], *, evidence_refs=()) -> ScoreEnvelope:
    reason = outcome["termination_reason"]
```

The kernel passes a `FamilyScoringInput` dataclass and expects every declared
leaf (`evaluation.py`, `normalize_family_score_set`). So govsim would fail on
the first subscript, and four of its five leaves would never reach a receipt.
It is mid-migration on an older seam -- exactly what issue #76 describes.

## What #91 actually requires

1. **Finalizer migration (#76).** `__call__(scoring_input) -> FamilyScoreSet`
   over all five leaves: `no_collapse`, `threshold_adherence`,
   `survival_months` (the declared primary estimand), `total_harvest`,
   `equality_gini`. Two of them need `round_trace`, which is reachable from
   the replayed terminal state, as in econevals.
2. **`scoring.reference_provider_ids`.** The manifest declares none. econevals
   had the same gap: the resolver rejects a pin nothing references while the
   receipt rejects a cited implementation that is not pinned, so a plan cannot
   resolve until the manifest declares the union its leaves cite.
3. **`live.py` + `campaign.py`.** Harder than econevals': three phases
   (`harvest` -> `discuss` -> `reflect`) with multiple persona seats, against
   econevals' single self-looping single-seat phase. The kernel contracts are
   the same, and the econevals checklist applies unchanged -- route seal
   shape, declared seed, retry policy sized to the call count, declared
   backoff, output budget sized to a real burst, whole-burst validation, empty
   turns raised as typed conditions, and the publisher kept outside the
   execution freeze.
4. **No upstream checkout needed at runtime.** The gini is vendored pure
   numpy; the bridge is only for parity tests. Unlike econevals, a live panel
   needs no third-party clone.

## The decision needed before the finalizer can be written

govsim is a **comparative** family: `bound_status: baseline_only`,
`comparison_baseline: govsim_sustainable_v1`. `score_all` therefore requires
three baseline values -- `baseline_survival_months`, `baseline_total_harvest`,
`baseline_gini` -- and `__call__` today sidesteps this by scoring only
`survival_months` with `baseline_survival_months=None`, which its own
docstring defends as "honestly omitted rather than fabricated".

A finalizer cannot omit them, so the baselines have to come from somewhere
and be frozen. Three options:

| option | what it means | cost |
|---|---|---|
| **Scripted baseline episode per case** | run `policies.sustainable_v1` through the same environment, provider-free, and freeze its three values into the campaign plan | cheap and provider-free, but the baseline becomes part of the plan digest, so changing the policy re-freezes the campaign |
| **Baselines pinned in the case payload** | corpus carries the reference values | most reproducible; requires a corpus revision and re-derivation of `content_sha256` |
| **Emit the leaves with a null comparative** | report absolute values, mark the comparative reference absent | no design change, but four leaves lose the comparison their estimands are defined by |

I recommend the first: it keeps the baseline derived from a committed policy
rather than a hand-entered number, it is provider-free, and freezing it into
the plan is the same discipline every other campaign parameter gets. But it
determines what the family's headline numbers *mean*, so it is a ruling, not
an implementation detail.

## Communication restored (2026-09-06)

The first published panel measured the common-pool dilemma **with
communication removed**: `discuss` and `reflect` both accepted `{}` and
carried no content, so nothing an agent said could reach anyone. Upstream's
whole contribution is that dialogue changes the outcome
(`persona_v3/cognition/converse.py`, `prompt_converse_utterance_in_group`,
utterances recorded per round and plotted in `analysis/details.py`), so the
panel was not measuring what GovSim measures.

Now:

- `discuss` carries `{"message": str}`. The utterance goes into a **public
  transcript** that appears in every agent's next observation, so one
  agent's stated intent can change another's harvest -- the mechanism the
  benchmark exists to study.
- `reflect` carries `{"reflection": str}`, stored **per agent** and returned
  only to its author. That is memory, not speech.
- The scripted harness produces utterances too, so a baseline exercises the
  same content-carrying action a live persona does.

### The first attempt at this was fake, and how it was caught

Attempt 002 ran with dialogue "enabled" and produced a transcript in which
**every utterance was identical**: `"I will take my usual share this
round."` -- a fallback string the harness substituted, not a word the model
wrote.

`output_schema` is a **profile-level** setting, not a per-call one, so the
harvest-only schema forced structured output to `{"quantity": n}` in every
phase. The model was structurally incapable of returning a `message`, the
harness found none, and the fallback filled the gap -- into the public
transcript, into every other agent's observation, as if it were real.

The offline dry run did not catch it because the stub returned
`{"message": ...}`: it validated the plumbing and the fallback at once and
could not tell them apart. Only reading the sealed utterances from a live
run showed ten identical strings.

Fixed two ways. The schema now admits `quantity`, `message` and
`reflection` with nothing `required`, and the prompt says which field
belongs to which phase; a live probe confirms the model answers each phase
correctly. And **the fallback is gone** -- an empty utterance now raises,
because inventing dialogue is fabricating evidence, which is worse than
failing the period.

Verified offline before that: 12 transcript entries over a 12-round
episode, 126 of 132 observations carrying a prior utterance, reflections
stored for all five personas, receipt `ok`/`included`, replay matching.
Those numbers show the mechanism works; attempt 003 is the first run where
the content is the model's own.

**Still short of upstream**, and worth stating rather than glossing:

| | upstream | here |
|---|---|---|
| speakers per round | the whole group converses, multiple turns | one fixed spokesperson, one turn |
| transcript visible | the full conversation | a six-entry window (`TRANSCRIPT_WINDOW`) |
| memory | a retrieval-backed store (`cognition/store.py`) | the agent's own last reflection |

So dialogue now exists and demonstrably influences other agents, but it is a
single-speaker channel rather than a group conversation. Closing that gap
means multi-speaker turns in the discuss phase and is the next step.

## What a live panel can and cannot exercise

The action contract limits what an LLM can do here, and the limit is not
obvious from the family's name:

| phase | action schema | what a model contributes |
|---|---|---|
| `harvest` | `{"quantity": int >= 0}` per persona seat, simultaneous | the whole decision |
| `discuss` | `{"message": str}` | a public utterance every agent then sees |
| `reflect` | `{"reflection": str}` | a private memory returned to its author |

`observe()` says as much in its own comment: the observation is "deliberately
symmetric across seats", and "a richer, seat-private observation is a
follow-up for an LLM-driven persona, not this milestone".

So a live govsim panel measures **sustainability decisions without
deliberation**. That is a real result -- it is the common-pool dilemma with
communication removed -- but it is not what a reader assumes GovSim measures,
since upstream's contribution is precisely that dialogue changes the
outcome. Any claim from this panel must say so, and a follow-up that gives
`discuss` real content is the more interesting experiment.

The harness therefore makes no model call at all during `discuss` and
`reflect`: calling a model to produce `{}` would spend money to record
nothing and would misrepresent the trajectory as deliberated.

## Decisions taken

- **Baselines** (2026-09-06): the scripted-policy option, implemented. The
  plugin carries `baselines`, produced by running the declared
  `govsim_sustainable_v1` policy through this same environment provider-free
  and frozen into the campaign plan. Without them the scorer emits the three
  baseline-free leaves rather than inventing a reference, and the declared
  primary estimand is present either way.
- **Interpreter**: the corpus pins the bridge to CPython **3.11.3** exactly,
  and preflight refuses anything else (`python_version mismatch: pinned=3.11.3`).
  Provision with that interpreter, not merely "a 3.11".

## Defects the offline pass caught

Building the live path surfaced five contract defects, none of which cost a
paid call because every one was found by a stub-provider dry run:

| # | Defect | Why it mattered |
|---|---|---|
| 1 | scorer took a recorded-outcome `Mapping`, not `FamilyScoringInput` | four of five leaves could never reach a receipt (#76) |
| 2 | manifest declared no `reference_provider_ids` | plan unresolvable |
| 3 | `compute_baseline` called `asyncio.run` from inside the campaign's running loop | would have raised on the first live invocation, after the canary was paid for |
| 4 | harness skipped the model call in `discuss`/`reflect` | kernel refuses: an action with no model call could be a trajectory no model took part in |
| 5 | validity-domain predicate hangs off `leaf.estimand` here and `verifier.objective_scope` in econevals; only the second was walked | receipt refused to seal, **after** a full episode ran |

Defect 4 is worth keeping in mind as a rule rather than an incident: skipping
a model call in a contentless phase looked like the honest saving, and it is
exactly what the kernel forbids. The invariant is what makes a sealed
trajectory mean anything.

## Status

**The live path is built and verified offline**: 132 model calls, termination
`collapse_or_horizon` at 12 rounds, receipt `ok`/`included`, all five leaves
sealed, replay digest matching the seal. That is #76 demonstrated on a real
receipt rather than a unit test.

Remaining: the live panel itself, which waits for a Parasail window --
housing's confirmatory campaign is running on the same shared pool, and
econevals' first light showed what contention on it costs.
