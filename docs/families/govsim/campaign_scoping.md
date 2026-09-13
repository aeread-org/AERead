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

## Dialogue panel published (2026-09-10)

`govsim_glm53_flash_parasail_dialogue_v3`, attempt 001, at
`evidence/govsim/govsim_glm53_flash_parasail_dialogue_v3/`: canary admitted, 3/3
cases included, every receipt replayed through the pinned upstream bridge
(commit `1d11adf0`), $0.0408, 14.5 minutes serial. Verification (manifest
seal, six artifact digests, campaign-plan digest, three replays, prohibited-
text scan) is pasted on the PR.

The dialogue is real this time, checked the way G-J-02 says to: per case, 12
spokesperson utterances with 7–12 distinct strings and none empty, 60
private reflections all distinct, and harvest quantities that move with the
pool. Every scenario survived the 12-month horizon (`survival_months` 12 vs
baseline 12, `no_collapse` 1); total harvest against the scripted
sustainable baseline of 600 was 199 (fishing), 521 (pollution), 594
(sheep), with Gini 0.08 / 0.02 / 0.03 -- the agents under-harvested rather
than collapsed the pool, and said so to each other. `threshold_adherence`
is 0.0 on all three, which reads as the model never once matching the
advisory sustainable share exactly, not as a violation; a reader comparing
v1 (communication removed) with v3 has the pair the family was scoped for.

v2's completed attempt is not published: its plan pinned `environment.py`
before the `.get("message", "")` fix (G-D-02), and the source it pinned is on
no pushed branch. v3 is that design re-run from `main`.

## Baseline arm published (2026-09-10): the model does not collapse the commons

`govsim_glm53_flash_parasail_baseline_v4`, at
`evidence/govsim/govsim_glm53_flash_parasail_baseline_v4/`: canary admitted, 3/3
included, all three receipts replayed through the pinned upstream bridge,
$0.0392. All 132 sealed agent observations were checked to confirm the
sustainability threshold never reached the agent.

This is the arm the paper's headline refers to, and it is the first of our
panels that can be set beside it. The paper (arXiv 2404.16698) reports that
all but the strongest 2024 models fail to sustain the resource, with the
highest survival rate below 54%.

| arm | threshold given | dialogue | survival | total harvest (fishing / pollution / sheep, sustainable = 600) |
|---|---|---|---|---|
| `first_light_v1` | yes (intervention) | removed | 12/12 × 3 | 560 / 600 / 592 |
| `dialogue_v3` | yes (intervention) | present | 12/12 × 3 | 199 / 521 / 594 |
| **`baseline_v4`** | **no** | present | **12/12 × 3** | **237 / 401 / 182** |

GLM 5.3 Flash never collapses the pool, in any arm, in any scenario. The
2024 failure mode the paper diagnoses -- agents unable to reason about the
long-run equilibrium and drawing the resource down -- does not reproduce on
this model two years later, and survival is saturated for it: three cases
cannot tell 100% from 95%, but they can tell it from below 54%.

What the baseline arm costs the agent is yield. Told the threshold, the
agents harvest at or near it (v1: 560/600/592 of a sustainable 600). Not
told it, they take 30-67% of what the commons could sustain -- they buy
survival with caution rather than with an estimate of the regeneration rate.
Equality moves the same way: Gini rises from 0.007-0.011 in v1 to
0.040-0.142 in v4, because agents that are guessing do not guess alike.

Two readings a reader should not take from this. Survival at 3/3 is not
"100% survival" for the family: one case per scenario, one seed, one route.
And the model here is a *non-deliberating* GLM 5.3 Flash -- `reasoning_low_v1`
was measured on 2026-09-10 to suppress reasoning to ~13 tokens (R-D-01) --
so the deliberating arm is still owed and would be the fair comparison
against the paper's freely-reasoning agents.

A note for anyone replaying the earlier bundles: this change edits
`environment.py` and `live.py`, both pinned by digest in every campaign
plan, so `first_light_v1` and `dialogue_v3` no longer rebuild or replay from
current source. They remain self-verifying by their own manifest and receipt
digests; replaying them needs the commit their plans pinned (`3cc8bc53`,
the merge of #157).

## Checking the adapter against the paper's own agents (2026-09-10)

Every govsim panel we had run survived 12 of 12 months in every scenario and
every arm, and a family where nothing ever collapses cannot distinguish a
capable agent from a saturated task. The paper's table supplies the control:
eight of its twelve agents collapse the commons at **0% survival and 1.0-1.1
months**, and its best, GPT-4o, reaches **53.3% survival and 9.3 +/- 2.2
months**.

**None of its agents is reachable.** The Anthropic and open-weight rows
(Claude-3 Opus/Sonnet/Haiku, Llama-3 8B/70B, Mistral, Mixtral, Qwen) have no
endpoint that accepts a declared seed, which this kernel requires (#172). The
OpenAI rows fail differently and more interestingly: `gpt-3.5-turbo` and
`gpt-4o-2024-05-13` -- the snapshot current when the paper was written --
both refuse our request with *"'response_format' of type 'json_schema' is
not supported with this model"*. OpenAI's Structured Outputs arrived with
`2024-08-06`, so every agent the 2024 paper evaluated predates a feature
this harness requires. The GPT-3.5 canary caught that for $0.00, which is
what a canary is for.

So the check is run with the two nearest reachable models, and only one of
them is a comparison with the paper:

| | our harness (3 cases, baseline arm) | the paper |
|---|---|---|
| `gpt-4o-mini` (not a paper agent) | **1.0 months, collapse in all three**, whole pool of 100 taken in round 1 | its eight collapsing agents: 1.0-1.1 months |
| `gpt-4o-2024-08-06` (3 months later than the paper's snapshot) | fishing 12, pollution **2 (collapse)**, sheep 12 -> **2 of 3 survive, mean 8.7 months** | GPT-4o: 53.3% survival, **9.3 +/- 2.2 months** |
| GLM 5.3 Flash, suppressed (`baseline_v4`) | 3 of 3 survive, 12 months each | above its best |

**Two things this settles.** The environment produces collapse: `gpt-4o-mini`
exhausts the pool in the first round and lands on 1.0 months, the same figure
the paper reports for its collapsing agents. And GPT-4o's mean survival here,
8.7 months, sits inside the paper's 9.3 +/- 2.2 for the same model family --
its survival *rate*, 2 of 3, is 66.7% against the paper's 53.3%, which three
cases cannot separate from it.

So GLM 5.3 Flash surviving 12/12 is a fact about a 2026 model rather than an
artefact of a task nothing can fail, which is what could not be said before
these two panels.

**What this does not establish.** Three cases per model, one seed, one
scenario each. `gpt-4o-mini` is not in the paper, so its agreement with the
paper's collapse figure is evidence that our environment collapses the way
theirs does, not that the paper would have scored *this* model at 1.0. And
`gpt-4o-2024-08-06` is not the snapshot the paper ran; three months of model
separate them, and that is a caveat on the closeness rather than a footnote.
