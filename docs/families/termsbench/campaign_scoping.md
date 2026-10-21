# TERMS-Bench live campaign (#92): what is done, and the blocker

## Done

- **Finalizer migrated (#75).** `TermsBenchScorer` had no `__call__` at all,
  so the kernel's finalizer could not score it and none of its four leaves
  could reach a receipt. It now implements
  `__call__(scoring_input) -> FamilyScoreSet`, scoring exactly the leaves a
  case declares -- they are regime-dependent, `(surplus_efficiency,
  feasible_agreement, protocol_compliance)` for Overlap and
  `(no_deal_agreement, protocol_compliance)` for No-deal -- so a case is
  never scored on a leaf it does not declare. `protocol_compliance` is the
  admission leaf, being the one leaf both regimes declare: a trajectory that
  broke the protocol is an invalid measurement, not a low score.
- **`scoring.reference_provider_ids` declared**, as the union across both
  regimes, built from the same `_implementation` helper the leaves use.
- **No upstream checkout is needed.** Unlike econevals and govsim, this
  family carries its own kernel and a 30-case pilot corpus; nothing has to
  be cloned or provisioned.

## The blocker: a seat that is not a model

TERMS-Bench has two seats. `agent` is the model under test. `counterpart` is
**not a model** -- it is resolved by this family's own stochastic kernel
(`kernel.resolve_counterpart_turn`, driven by the case's `world_seed`), which
is what makes the benchmark a negotiation against a specified opponent rather
than a self-play conversation.

`execute_plan_cell` has no way to express that. Every seat in a resolved plan
is routed through a profile to a harness to a model call, and there is no
scripted-seat parameter. The two obvious workarounds are both wrong:

- **A harness that returns the counterpart's action without a model call**
  is rejected by the kernel (`harness ... returned without a model call`),
  and rightly: that invariant is what stops a harness fabricating a
  trajectory no model took part in.
- **Giving `counterpart` a live profile** would have the model play both
  sides. That is a different experiment from TERMS-Bench, whose result is
  defined against the specified opponent.

## Three ways forward

| option | what it means | cost |
|---|---|---|
| **Fold the counterpart into the environment** | `counterpart_turn` stops being a seat; its resolution becomes part of `step()`, where the stochastic draw already belongs conceptually -- the counterpart is environment, not agent | a family redesign: the phase graph, the replay goldens and every case's `content_sha256` change |
| **Add a scripted-seat capability to the kernel** | `execute_plan_cell` accepts a per-seat response source for seats whose profile declares no model | a shared-kernel change benefiting any family with a specified opponent; needs its own evidence story, since a scripted seat's actions must still be replayable and clearly marked as not-model-produced |
| **Run the agent seat only, with the counterpart pre-resolved** | pre-compute the counterpart's turns per case from the seeded kernel and serve them as fixed observations | cheapest, but the counterpart stops reacting to the agent's offers, which destroys the negotiation |

The second is the one I would argue for: the counterpart being scripted is a
property many families share (govsim's scripted policies, procurement's
oracle), and the kernel currently forces every one of them into either a
model call or a bespoke driver outside `execute_plan_cell`. But it is a
shared-kernel capability with an evidence contract of its own, so it is a
ruling rather than an implementation detail.

Until then #92's live panel cannot be run without misrepresenting what
TERMS-Bench measures.

## Resolved (2026-09-08): the counterpart is a kernel scripted seat

The second option above was taken. The kernel now has a scripted-seat
capability (#150, `docs/kernel_scripted_seats_design.md`): a plan may
declare a seat as filled by a family policy rather than a profile
(`RunSpec.scripted_seats`), the kernel asks the plugin's
`scripted_response(policy_id, request, world_seed=...)` for that seat's
turn, seals it as a `scripted_action` (never as a provider call), and replay
recomputes it and holds it against the sealed response. A scripted seat may
be a block's control and never its subject.

What this family did with it:

- `environment.py` -- `TermsBenchPlugin.scripted_response` answers
  `termsbench_counterpart_kernel_v1` from the same pure function the legacy
  test harness used (`harness.resolve_counterpart_response`), so the
  scripted seat reproduces the legacy counterpart exactly
  (`tests/test_termsbench_scripted_seat.py`).
- `live.py` -- the live setup: the agent is the only profile, the
  counterpart is the scripted seat and the block's control. The harness
  makes one model call per agent turn and hands the JSON object to the
  family unchanged: a malformed move is a *measured* agreement violation
  here, and `protocol_compliance` is the admission leaf, so the harness
  does not judge it. Route, retry policy and the reasoning declaration are
  econevals' measured configuration on the same GLM 5.3 Flash/Parasail
  route.
- `campaign.py` -- the pilot: one unscored canary, then the 30-case corpus
  in the corpus manifest's order, serially, with the cost ceilings and the
  campaign SOP's wall-time gate frozen in the plan. The publisher reports
  per regime, because the leaves are regime-dependent, and adds the
  family's own corpus aggregate (`SE+`, `AGR+`, `CSE+`) over the Overlap
  half.

Every corpus case was run offline through the real kernel against the
scripted counterpart before the canary (`tests/test_termsbench_live_campaign.py`).
The first defect that surfaced is TB-D-01 in the incident log: a receipt
with a scripted seat could be sealed and replayed but not read back by the
research layer, fixed in #150 before any spend.

## Pilot v1 → v2 (2026-09-08)

`termsbench_glm53_flash_parasail_pilot_v1`, attempt_001: canary admitted;
cases 0–6 complete and replayed; case 7 (`nodeal.1010055`) aborted the
panel. GLM 5.3 Flash at temperature 0 wrote `{"decision": "offer", "price":
56.5993352745860345659335…` and repeated the digits of the price to the
4,000-token ceiling (`finish_reason: length`); the 1.0 harness typed that
as a non-retryable `malformed_structured_output` route fault, which the
kernel wraps as a contract error and the campaign as an operational abort
(TB-O-01, TB-D-02 in the incident log). Two things were wrong with that,
neither of them the model's answer:

- the family already defines a malformed move as a *measured* outcome
  (`malformed_action_schema`, spec golden 4), and the kernel's OpenRouter
  client deliberately keeps a completed non-JSON answer on the normal path
  for the family to classify -- the harness had pre-empted both;
- one cell's failure should never cost the other twenty-two cases.

v2 is the new campaign identity that carries the fixes, as a changed
frozen control requires: harness 1.1 hands a finished non-object answer to
the family as `{"raw_text": …}`, and a cell that fails inside the kernel is
sealed as a typed exclusion receipt (`finalize_family_failure`) while the
campaign continues. The v1 attempt root stays sealed as evidence. What the
two clients do with a truncated structured response differs (Arena types it
`length`, OpenRouter returns the text) and is filed as #152 rather than
changed under the scripted-seat PR.

## Pilot v2 result (2026-09-08)

`termsbench_glm53_flash_parasail_pilot_v2`, attempt_001, published at
`evidence/termsbench_glm53_flash_parasail_pilot_v2/`: canary admitted; 30/30
cases complete, every receipt `ok` and included, every receipt replayed with
the counterpart recomputed on every turn; $0.029 in total, 5.6 minutes of
serial wall time (longest case 108 s). The Tier 1 register
(`evidence/termsbench_failure_register/`) holds one row, v1's abort.

What GLM 5.3 Flash did under this profile (no reasoning effort, a
1,500-token reasoning cap that in practice yields ~30 reasoning tokens,
temperature 0):

- **Overlap (15):** every case reached agreement (`AGR+ = 1.0`), 12 by the
  counterpart accepting the agent's offer and 3 by the agent accepting; the
  agent's share of the zone of agreement averaged `SE+ = CSE+ = 0.40`
  (range −0.03 to 0.81). One case is a critical violation: the buyer agreed
  above its own reservation value.
- **No-deal (15):** 14 ended by the counterpart walking away and 1 by the
  agent accepting a price -- an agreement in a world with no zone of
  agreement (`FAGR- = 1` on that case). Twelve of the fifteen carry an
  individual-rationality violation: the buyer offered above its own
  reservation value to chase a seller it could not reach. That is the
  paper's `CritViol` and it is scored, not excluded; a reader of the corpus
  aggregate should not average it away.
- No malformed move in v2. v1's case 7 did not repeat its degeneration at
  the same seed and temperature; the route is not deterministic.

Episodes ran 1–10 rounds (median 3); the wall-time gate and both cost
ceilings had an order of magnitude of headroom.

## Pilot v3: the same panel with the model allowed to think (2026-09-10)

v2's 43% critical-violation rate sat twenty times above the paper's 0–2.06%
band for thirteen agents, which is the kind of gap that is usually the
harness rather than the model. It was. One probe call per condition on this
route showed that `reasoning.max_tokens` is a suppression switch rather than
a budget — 1,500 and 8,000 both yield ~13 reasoning tokens, as does
`reasoning.effort: "low"` — while declaring no reasoning block at all yields
~260. v2 (`reasoning_capped_1500_v1`) therefore measured a GLM 5.3 Flash
that did not deliberate. v3 is the same 30 cases, same seed, same scripted
counterpart, with `reasoning_unconstrained_v1` and a 12,000-token completion
budget for the rationale the route now emits (that budget change is bundled
with the condition, and the claim is about the bundled configuration, per
`docs/research/reasoning_condition_and_diagnostics.md` §3).

| | v2 suppressed | v3 deliberating | paper, 13 agents |
|---|---:|---:|---|
| `SE+` | 0.402 | **0.533** | 0.189 – 0.694 |
| `CSE+` | 0.402 | **0.533** | 0.296 – 0.721 |
| `AGR+` | 1.00 | 1.00 | 0.522 – 0.999 |
| `FAGR-` | 0.067 (1/15) | **0.133 (2/15)** | ~0, worst 0.0017 |
| `CritViol%` | 0.433 (13/30) | **0.067 (2/30)** | 0 – 0.0206 |
| cost / wall | $0.029 / 5.6 min | $0.134 / 43.5 min | — |

Deliberation bought a third more surplus and cut critical violations by
6.5×: the agent stopped offering above its own reservation value to chase a
seller it could not reach, which was 12 of v2's 13 breaches. What it did not
fix — and appears to have made worse — is the false agreement: two no-deal
cases closed in v3 against one in v2, both times by the counterpart
accepting an offer the agent should never have made. On 15 no-deal cases
that is one event of difference and no basis for a claim, but it is the
axis the paper singles out as independent of surplus, and ours is the arm
where it is worst.

Per counterpart family, `SE+` moved candid 0.325 → 0.562, taciturn 0.351 →
0.476, expressive 0.529 → 0.562. The paper's "cue penalty" predicts *less*
surplus where cues are informative (candid, expressive) than where they are
muted (taciturn); v3 is ordered that way and v2 was not, but five overlap
cases per family cannot support the comparison.

Neither arm produced a malformed action. v1's degeneration has not recurred.

## Checking the adapter against the paper's own agents (2026-09-10)

Every number above is for a model the paper never ran, which makes it a
measurement and not a check. Two of the paper's thirteen agents are
reachable on our route, and they sit at opposite ends of its table, so
running the same 30 cases through them tests whether this adapter
discriminates the way the paper's does.

| panel | model | route | what the paper reports |
|---|---|---|---|
| `termsbench_gpt4o_mini_pilot_v1` | `openai/gpt-4o-mini-2024-07-18` | OpenAI | its **weakest** agent: `SE+` 0.189 ± 0.013, `AGR+` 52.2 ± 2.8% -- the only model below the frontier band of 93.4-99.9% |
| `termsbench_glm51_pilot_v1` | `z-ai/glm-5.1-20260406` | DeepInfra, fp4 | its **best conditional surplus**: `CSE+` 0.721 ± 0.014, `CritViol%` 1.33 ± 0.53%, and the remark that it "anchors strongly in overlap yet breaches reservation in no-deal" |

Both panels declare the same reasoning condition, the same completion
budget, the same schema dialect and the same corpus: they differ in the
model and nothing else.

**Recorded before the runs, so the check cannot be read backwards.** If this
adapter measures what the paper measures, then:

1. `AGR+` is markedly lower for GPT-4o-mini than for GLM-5.1. This is the
   sharpest prediction, because the paper separates them by ~40 points on a
   metric that saturates for everyone else.
2. `SE+` and `CSE+` are substantially higher for GLM-5.1.
3. GLM-5.1 shows individual-rationality breaches concentrated in the No-deal
   regime, which is the paper's own remark about this model rather than a
   number.

What the check cannot settle: absolute agreement with the paper's table. Our
agent is one JSON call per turn against a scripted counterpart, while the
paper's agents run its own scaffold; 30 cases against 1,800 leaves wide
intervals; three of six counterpart families are missing; and GLM-5.1 is
served here at fp4, which the paper's serving was probably not. A
reproduction of the *ordering* is the strongest evidence available at this
scale, and a failure to reproduce it would be evidence of a defect.

**Two caveats on the route, recorded because they bound what can ever be
checked here.** Claude Opus 4.6 and 4.7 -- the paper's best `SE+` -- are
unreachable: none of their OpenRouter endpoints supports a declared seed,
and this kernel refuses a diagnostic run without one. And GLM-5.1 is
reachable only through DeepInfra, the sole endpoint offering both a seed and
structured output, at fp4.

## The check, run (2026-09-10)

Same 30 cases, same scripted counterpart, same reasoning condition, same
schema dialect for the two paper models; only the model differs.

| | GPT-4o-mini | GLM-5.1 | GLM 5.3 Flash | paper: GPT-4o-mini | paper: GLM-5.1 |
|---|---:|---:|---:|---|---|
| `SE+` | **0.035** | **0.458** | 0.533 | 0.189 (its lowest) | — (table's best is 0.694) |
| `CSE+` | **0.044** | **0.458** | 0.533 | ~0.296 (its lowest) | **0.721 (its best)** |
| `AGR+` | **0.80** | **1.00** | 1.00 | **0.522 (its lowest)** | frontier 0.934 – 0.999 |
| `FAGR-` | 0.00 | 0.00 | 0.133 | ~0 | ~0 |
| `CritViol%` | 0.233 | 0.133 | 0.067 | (band 0 – 0.0206) | 0.0133 |
| cost / wall | $0.003 / 0.7 min | $0.182 / 30.8 min | $0.134 / 43.5 min | | |

**Prediction 1 — `AGR+` markedly lower for GPT-4o-mini — holds.** It is the
only model in the set that fails to close a feasible deal, 0.80 against 1.00
for both others, and the paper's structural claim is exactly that: every
frontier agent between 0.934 and 0.999, GPT-4o-mini alone at 0.522. It
rejected 3 of 15 Overlap cases outright, and all 15 No-deal cases, which is
also why its `FAGR-` is a clean zero.

**Prediction 2 — surplus substantially higher for GLM-5.1 — holds, and by
more than the paper's margin.** 13× on `SE+` (0.035 against 0.458) where the
paper separates the same two ends by 3.7×.

**Prediction 3 — GLM-5.1 breaching reservation in No-deal — does not
reproduce.** One individual-rationality breach in 30 cases, and it is in an
Overlap case. Fifteen No-deal cases cannot rule the paper's remark out, but
they did not show it.

**What the check establishes.** This adapter orders the paper's own agents
the way the paper orders them, on the metric the paper says separates them,
with the gap in the same direction on every axis. That is the strongest
available evidence that the environment, the counterpart and the scoring
measure what they claim to.

**What it does not.** Every absolute number is displaced from the paper's:
surplus lower, violations higher. The most likely cause is the agent rather
than the environment -- ours is one JSON call per turn with no memory,
reflection or planning stage, against the paper's own scaffold -- and that
displacement is uniform across all three models, which is what one would
expect of a scaffold effect rather than a scoring defect. Thirty cases
against 1,800 leaves intervals wide enough to swallow most of the paper's
column, three of six counterpart families are missing, and GLM-5.1 is served
here at fp4.

**One number needs decomposing (TB-D-05).** GLM-5.1's `CritViol` of 0.133 is
4 cases: 1 reservation breach and 3 accepts that echoed the counterpart's
price. The strict schema declares `price` required while the prompt says not
to include one for a non-offer; `price: null` satisfies both and GPT-4o-mini
used it on all 20 of its non-offer turns, but GLM-5.1 resolved the tension
toward the schema. Its negotiation-conduct violation rate is 1/30, against
the paper's 1.33% -- close. A strict-dialect prompt should say "set price to
null", and that is a fix for the next identity, not a reason to reissue this
one.
