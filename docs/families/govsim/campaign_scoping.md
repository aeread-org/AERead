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

## What a live panel can and cannot exercise

The action contract limits what an LLM can do here, and the limit is not
obvious from the family's name:

| phase | action schema | what a model contributes |
|---|---|---|
| `harvest` | `{"quantity": int >= 0}` per persona seat, simultaneous | the whole decision |
| `discuss` | `{}` | **nothing** -- the action carries no content |
| `reflect` | `{}` | **nothing** |

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

## Status

Items 1, 2 and 4 are done: the finalizer is migrated (#76), the manifest
declares the reference providers its leaves cite, and the pinned upstream
checkout plus a 3.11.3 bridge are provisioned. Item 3, the live path,
follows.
