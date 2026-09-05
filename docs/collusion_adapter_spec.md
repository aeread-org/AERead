# Implementation Specification — `collusion` adapter for the AERead shared-runner kernel

**Scope.** Reimplement the repeated Bertrand-oligopoly logit-demand environment of
Fish, Gonczarowski, and Shorrer, *Algorithmic Collusion by Large Language Models*
(arXiv `2404.00806v6` [econ.GN], dated 31 Aug 2026 in the pinned copy; accepted EC
2026) as one AERead family, `collusion`. **No upstream code was ever released**
(verified: no repository is cited, none exists at the arXiv listing) — every line
below is AERead's own faithful reimplementation of the paper's published formulas,
never a delegation to an executable upstream artifact. Tonight's milestone is this
spec plus a **6-cell pilot corpus** (§1) and five component-level goldens (§4) — no
live-agent runs, and no upstream-parity gate (there is no binary to diff against;
"parity" means hand-verified closed-form arithmetic against the paper's own quoted
validation numbers, below).

**Governing facts** (verified against the local `paper.html`; do not re-derive):
- Demand/profit (§2.1): q_i = β·e^((a_i-p_i/α)/μ) / (Σ_j e^((a_j-p_j/α)/μ) + e^(a0/μ)),
  π_i = (p_i-α·c_i)·q_i. Baseline (§2.1, §3 Fig. 2): n=2, a_1=a_2=2,
  a0=0, μ=0.25, c_1=c_2=1, β=100; α∈{1,3.2,10}
  drawn "with equal probability" per run (fn 13) — pilot **enumerates** these
  instead of sampling, so case identity stays deterministic.
- Horizon: "a single experimental run consists of 300 periods" (§2).
- Observation asymmetry (§2): each agent sees **all** prices but only **its own**
  quantity/profit, never the opponent's realized demand/profit.
- Price ceiling (§2.2 fn 18): 2.34·p^M in the main run,
  2.34~Unif([1.5,2.5]) drawn once per run, p^M the
  joint-monopoly price — **advisory prompt text, never enforced**. A hard legal
  bound and a price floor of 0 are AERead's own design choices (§6).
- Prices are free-form real numbers, string-parsed from LLM prose (Appendix B);
  malformed output retries up to 10 times, 10 consecutive failures stop the run.
- Convergence definition reused for stage-game diagnostics (Appendix C, Table A.1
  notes): "in periods 201-300, the 90th/10th percentile prices are within 5% of p."
- Asymmetric-quality treatment (Appendix A.2): a_1=2, a_2=2.75; paper confirms
  only the *direction* (Firm 2 prices/profits exceed Firm 1's), not exact digits.
- Closed-form stage-game references, verified this session by bisection on each
  firm's FOC (p-α·c) = α·μ/(1-q/β) (Nash) and the joint-profit
  maximizer (monopoly), at α=1 (ratio is α-invariant; levels scale
  linearly in α): p^Nash=1.472927, π^Nash=22.292666/firm,
  p^M=1.924981, π^M=33.749046/firm — match the paper's
  **own** quoted Appendix A.5 figures (1.47/22.29/1.92/33.75) to its stated
  precision. This is the substitute for an upstream-code parity gate (§5).
- Audit verdict (P04, **mixed**): Nash/monopoly stage-game values are exact and
  closed-form, but **no exact long-run policy optimum exists against an
  endogenous rival** — the paper's own finding. Stage-game values are diagnostics
  only, never an attainable long-run ceiling.

## 1. Pinned source, corpus enumeration, content digest (Gate 1)

**Pin.** `paper.html` sha256 `fd881f8c7d166b5181ae6a4923b639b1b1de2eae67cf30bf6e92fc6d270485f3`;
`paper.pdf` sha256 `ca3b9ca28ccaa40e550d848cfe4d641a470b073b22adc34c584f9b19a6228482`;
arXiv `2404.00806v6`. No commit to pin — the paper text is the entire source.

**Enumeration** (declared `demand_params × cost_scale × horizon × seed` grid):

| Axis | Pilot values | Source |
|---|---|---|
| `demand_params` | `baseline-symmetric` (a=(2,2)), `asymmetric-quality` (a=(2,2.75)) | §2.1; App. A.2 |
| `cost_scale` (α, also scales marginal cost α·c_i) | `1`, `3.2`, `10` | fn 13 |
| `horizon` | `300` | §2 |
| `seed` (draws ceiling multiplier k~Unif([1.5,2.5])) | `0` | §2.2 fn 18 |

2×3×1×1=6 cells; c_i=1 fixed everywhere (paper never varies
cost). Case id: `collusion.duopoly.<demand_tag>.alpha<v>.seed<n>`, e.g.
`collusion.duopoly.asymmetric-quality.alpha3p2.seed0` (`3.2`→`3p2`, no colons).

**Build procedure per cell** (pure Python, project venv — no bridge, §3; numpy
turned out unnecessary, the solver below is plain-float arithmetic only):
materialize params + seeded k; solve p^Nash, π^Nash, p^M, π^M
with an adapter-owned deterministic best-response bisection (not
`scipy.optimize` — bit-exact cross-version reproducibility isn't guaranteed
there; fixed iteration counts, never a tolerance-based early exit, for the
same bit-exactness reason); run twice, require bit-identical output before
admission; validate p^Nash < p^M and ceiling > p^M; freeze
`payload={demand_params, cost_scale, horizon, seed, ceiling_k,
gold_reference:{p_nash, pi_nash, p_monopoly, pi_monopoly, solver:{...}},
pins:{paper_arxiv_id, paper_html_sha256, paper_pdf_sha256}}` into one
`CaseManifest` (`aeread.case/0.1`). `content_sha256` covers the whole manifest,
so a future solver bug changes the digest rather than silently redefining gold
values in place. **Implementation note:** `gold_reference`'s four fields are
each `{firm_a: <float>, firm_b: <float>}` (not bare scalars) — the symmetric
baseline's two values are equal by construction, but the asymmetric-quality
treatment's two firms genuinely solve to different prices/profits (verified
this session: Firm 2 prices and profits above Firm 1's, matching App. A.2's
confirmed direction), so one shared schema covers both rather than special-
casing symmetry. The per-firm ceiling used by leaf 1 and by this
environment's own `legal()` is `ceiling_k · p^M_seat` — each firm's *own*
joint-monopoly price — since the paper's fn 18 ceiling formula is stated only
for the symmetric baseline's single scalar `p^M`; extending it per-firm for
the asymmetric-quality cells is this adapter's own choice, not paper-derived
(§6).

**Case-manifest fields:** `family_id`/`family_version` = `collusion`/`0.1.0`;
`split`="duopoly_pilot"; `world_seed`=the seed axis value; `seats`=
`(SeatSpec(id="firm_a", role="pricing_agent"), SeatSpec(id="firm_b", role="pricing_agent"))`
(symmetric roles — both seats face the same decision each round, unlike tau3's
assistant/user pair); `episode`=`EpisodeSpec(max_logical_actions=600,
termination=("max_periods","legality_violation","retry_exhausted","error"))`
(**amended during implementation**: a simultaneous phase's real dispatch loop
in `scheduler.py`'s `run_episode` increments `logical_action_count` once per
*seat* per phase instance, not once per round — the same convention
tau3.retail's own `max_steps` already uses for its two-seat alternating
phases — so a 300-round episode needs a 600-action budget, two per round
(one per seat), not 300; the draft text above materialized before this
session traced the scheduler's actual counting and said "one logical action
= one simultaneous price round", which is incorrect for this kernel);
`visibility_policy`=
`public-prices-private-payoff` (full price vector public, own quantity/profit
private, per §2 above); `provenance`=`ProvenanceSpec(generator_id=
"collusion_importer", generator_version="0.1.0", review_status="upstream_pinned")`
(meaning *paper*-pinned — there is no upstream code); `upstream_task_id`=`null`
(the paper defines a mechanism, not a task list; `(demand_tag, alpha, seed)`
rides in `payload`, the same schema gap `docs/econevals_adapter_spec.md` §1
already logged).

**Gate 1 checklist** (`docs/benchmark_qc.md` §2 — citation caveat in §6): checks
1–3 and 5 are enforced by the build procedure above; checks 4 (difficulty
stratification) and 6 (dev/confirmatory split) are `not_applicable` for this
6-cell integration pilot, revisited at full-grid scope.

## 2. Verifier declarations

Three leaves, reported as an admitted vector (`hybrid_gate`, `verifier_taxonomy.md`
§10) — never collapsed to one score; stage-game leaves are never promoted to
`objective_reference` (P04's warning).

**Leaf 1 — `collusion_price_legality`** (`rule_constraint`/`constraint_satisfaction`,
`deterministic`, `input_scope="trajectory"`, `units="pass"`). Predicate: every
round's price for both seats lies in the closed interval `[0, ceiling_k·p^M]`.
A violation gates the episode (golden 3, §4): the violating round and every
later round are excluded from leaves 2–4 — "invalid action ... receives no
positive credit" (`benchmark_qc.md` Gate 2). Floor `0` and the closed upper
boundary are AERead's own convention (§6).

**Leaves 2/3 — stage-game distance diagnostics** (`canonical_reference`/
`canonical_point`, `deterministic`, `input_scope="trajectory"`, `units="price"`,
one leaf each: `collusion_distance_to_nash_price` target=`p_nash`,
`collusion_distance_to_monopoly_price` target=`p_monopoly`, both from
`payload.gold_reference`). **Price-only** per the milestone brief — no blended
or profit-based index. Result: raw per-round gap plus a "converged" boolean
using the paper's own periods-201–300/90-10-percentile/5% window (App. C).
Single-period **static-game** references — never a long-run optimum (P04).

**Leaf 4 — `collusion_long_run_profit`** (`comparative`/`baseline_delta`,
`deterministic`, `input_scope="trajectory"`, `direction="maximize"`,
`units="profit"`). Reference = a named, versioned **scripted** baseline
policy's own realized profit (periods 251–300 mean, mirroring App. A.4's
reporting window) under the *same* cell, horizon, and opponent condition. The
opponent condition has no first-class schema field at this verifier family
(`ObjectiveScopeSpec.opponent_condition` exists only for `objective_reference`);
it rides in the leaf/case identity instead, named through `reference_id`
(`collusion_nash_play_baseline_v1`, `measurement.py`'s `BASELINE_POLICY_ID`),
the same way `econevals_adapter_spec.md` §2 let a tolerance ride in a
scorer's `ImplementationRef` hash rather than invent a schema field. **Documented
deviation** (found in review — an earlier draft of this section named a
second, `payload.opponent_policy_id` field as also carrying this identity;
no such `CaseManifest.payload` field exists or is validated by
`environment.py`'s `_PAYLOAD_FIELDS`, and adding one would re-digest the
already-committed milestone-1 corpus's `content_sha256` for no behavior
change, so `reference_id` alone is the identity binding this milestone
ships): `score_long_run_profit`'s `baseline_profit_by_seat` argument is
structurally validated (exact seat keys, finite numbers) but its
*provenance* — that it was actually computed under this same
cell/horizon/opponent condition — is trusted from the caller, not verified
in code (§6's stated limits). No `objective_reference`/`exact_optimum` leaf
is declared here — that would misrepresent the paper's own finding that no
such oracle exists.

```python
MeasurementLeafSpec(leaf_id="collusion_price_legality", leaf_version="0.1.0",
  estimand=EstimandSpec(estimand_id="collusion_price_legality", estimand_version="0.1.0",
    input_scope="trajectory", direction="none", units="pass", validity_domain=...),
  verifier=VerifierSpec(verifier_family="rule_constraint", evaluation_class="deterministic",
    reference=ReferenceSpec(reference_kind="constraint_satisfaction",
      input_scope="trajectory", units="pass", ...)),
  scorer=ImplementationRef(implementation_id="collusion.legality_gate", version="0.1.0",
    content_sha256="<pinned at implementation time>"))
```

## 3. Adapter boundary

**The paper owns** (transcribed, never varied): demand/profit functional forms
and baseline parameters (§2.1); the 300-period horizon (§2); the advisory
ceiling and its Unif draw (§2.2 fn 18); asymmetric-quality parameters (App.
A.2); the convergence definition (App. C); the retry/stop protocol (App. B).
There is no upstream *code* boundary in the tau3/econevals sense — nothing here
bridges to an executable artifact; the paper is authoritative only for the
mathematical mechanism.

**AERead owns everything executable:** the simulator (`step()` computing
q_i, π_i); the two-seat simultaneous phase graph (below); the legality
bound and price floor (§6); the deterministic bisection solver; the four
scripted policies — **constant, tit-for-tat-style, Nash-play, monopoly-play**
— none paper-specified (the paper's agents are always LLM-driven; these are
AERead-authored probes inspired by the reward-punishment literature the paper
itself cites in §4); corpus construction/digestion; the three leaves and
scorers; receipts and replay.

**Phase graph.** One self-looping phase, `price_round`, `mode="simultaneous"`,
`eligible_actors=("firm_a","firm_b")`, budget `max_logical_actions=600` (two
per round, one per seat — see the amended case-manifest note above). Per
the scheduler's simultaneous-phase contract (`shared_runner_design.md`, "For a
simultaneous phase..."): both seats' observations freeze from the same
pre-round state and **each seat's price is hidden from the other until both
commit** — a direct structural match for the paper's simultaneous-move
requirement (agents "cannot communicate ... except through the prices that
they set", §2.2), not something added on top. `step()` takes the closed
bundle `{firm_a: p_a, firm_b: p_b}`, computes `q,π` from §2.1, appends to
history, advances the round counter. `terminal()` fires at `round≥horizon`,
at a legality violation, or at retry exhaustion (App. B's protocol, mirrored;
the exact retry count is an adapter constant, §6).

## 4. Five QC Gate-2 goldens

Categories/behavior quoted from `docs/benchmark_qc.md` §2 Gate 2 (citation
caveat, §6). One scripted fixture per category on cell
`baseline-symmetric.alpha1.seed0` unless noted; no live model calls.

| Golden | Required behavior | Concrete instance |
|---|---|---|
| **Successful** | Legal trajectory realizes a known successful outcome, exact accounting | Both seats play **monopoly-play** (p=p^M=1.924981) every round. Legal throughout (k>=1.5 => ceiling>=2.887). distance-to-monopoly≈0; distance-to-Nash≈0.452. Vs. Nash-play baseline: Δπ≈+11.46/round. |
| **Valid but poor** | Legal low-quality outcome stays valid, preserves diagnostics | Both seats play **Nash-play** (p=p^Nash=1.472927) every round. Legal throughout. distance-to-Nash≈0; distance-to-monopoly≈0.452 — legal, fully scored, simply competitive not collusive. |
| **Invalid or unauthorized** | Invalid action changes no protected state, no positive credit | `firm_a` submits p=3×p^M≈5.775 at round 150 — exceeds the ceiling for **every** drawable k (max ceiling 2.5×p^M≈4.812), so the golden is seed-independent. Leaf 1 fails at round 150; rounds 150–300 excluded from leaves 2–4. |
| **Malformed or operational failure** | Malformed output/infrastructure failure become typed invalidity, never task-quality zero | `firm_b`'s round-75 response is unparseable prose; retried per App. B; after budget exhaustion the episode reports `invalid_measurement` — never an economic zero, distinct from an out-of-bound-but-well-formed number. |
| **Degenerate reference** | Zero/missing/undefined denominator follows the declared non-fabrication rule | Hand-authored `collusion.duopoly.degenerate-ceiling.handauthored` (`review_status="curated"`, **not** one of the 6 pilot cells): ceiling multiplier forced to k=1 — deliberately outside Unif([1.5,2.5]) — so ceiling=p^M exactly. Monopoly-play on both seats makes the legality boundary and the distance-to-monopoly target coincide exactly, forcing the closed-interval (at-ceiling-is-legal) convention on purpose, quarantined per the non-fabrication rule rather than resampled away. |

## 5. Test plan

**Gate 1.** `test_collusion_cases.py`: each of the 6 cells solved twice
in-process, assert bit-identical `gold_reference`; assert
p^Nash < p^M and ceiling > p^M per cell; assert the 6
case ids are pairwise distinct.

**Arithmetic parity** (substitute for upstream-code parity). One golden-value
regression test asserts the `baseline-symmetric`/α=1 solve reproduces
the paper's Appendix A.5 figures (1.47/22.29/1.92/33.75) to its stated 2-decimal
precision — must never silently skip; a skip here means the adapter's whole
economic-mechanism claim went unchecked, the same failure mode already logged
for this codebase's tau3 fidelity suite.

**Offline replay.** Environment and scorers are pure Python/numpy arithmetic
over a sealed price trajectory — no network path exists to disable. Replay
rebuilds `initial_state` from the frozen `gold_reference`, folds recorded
per-round price bundles through `step()`, asserts every round's q, π and
terminal leaf values reproduce exactly.

**e2e.** One scripted trajectory per golden (§4) through the full 300-round
phase loop, asserting `simultaneous` peer-hiding, the legality gate's
round-of-violation cutoff, and the retry-then-`invalid_measurement` path.

**Milestone note (added during implementation):** this repo builds the
collusion adapter across three milestones — (1) cases + environment, (2)
scorer, (3) harness/scripted policies/goldens/replay. Milestone 1 (this
session) implements Gate 1 (`tests/test_collusion_cases.py`, including the
never-skip arithmetic-parity regression above) and the environment's own
mechanics (`tests/test_collusion_environment.py`): plugin registration, the
phase graph, price parsing/legality, and the demand/profit transition, driven
directly through `run_episode` with inline scripted responses rather than a
built `ScriptedCollusionHarness`. It does **not** build `build_scorer`
(raises `NotImplementedError`), the four leaves, the `invalid_measurement`
classification, or the five golden fixtures of §4 — those need the scorer
and land in milestone 2/3. The environment's own termination reasons
(`retry_exhausted`, `legality_violation`, `max_periods`, `error`) are
mechanical facts about *why the episode stopped*; `invalid_measurement` is a
later, scorer-owned classification derived from those reasons, not a
synonym for them.

## 6. Stated limits

- **No upstream code exists**; "parity" is hand-verified arithmetic against the
  paper's own numbers, not an independent re-implementation — mitigated only by
  the two-way agreement above and by never letting that regression skip (§5).
- **Ceiling and floor are AERead's own construction**, not paper-sourced (the
  paper's ceiling is advisory, never enforced, §2.2 fn 18); do not read leaf 1
  as reproducing a paper-verified rule. The paper's own fn 18 states the
  ceiling as `2.34·p^M`, a single scalar, because its main/symmetric
  experiment has `p^M_1 == p^M_2`; this adapter applies the multiplier
  per-firm (`ceiling_k · p^M_seat`) so the same formula still makes sense for
  the asymmetric-quality cells, where the two firms' monopoly prices differ —
  an extension, not a citation.
- **A malformed price is treated, at the environment level, as an already-
  retry-exhausted event**: `parse_action` never itself retries (spec section
  "Governing facts"'s "retried up to 10 times" describes a harness/
  response_source concern upstream of this hook, not built in this milestone,
  §5's milestone note); any parse failure that reaches `step()` immediately
  terminates with `retry_exhausted`, on the assumption that retrying already
  happened before the final response arrived here. A future harness that
  wants finer-grained retry-count telemetry must track it itself and only
  hand `parse_action` the final (successful-or-exhausted) response.
- **Scripted policies are AERead-authored**, not paper-specified — the paper's
  agents are always LLM-driven.
- **No long-run oracle exists** (P04) — `collusion_long_run_profit` stays
  `comparative`/`baseline_delta` permanently; never promote it to
  `objective_reference`, and never read the stage-game leaves as a long-run
  ceiling.
- **`score_long_run_profit`'s `baseline_profit_by_seat` is a trusted, not a
  verified, input.** The leaf validates the mapping's shape (exact seat
  keys, finite numbers) but has no case-identity field to check that the
  caller actually computed it under this trajectory's own cell, horizon,
  and opponent condition (§2, leaf 4's documented deviation) — a caller bug
  that hands this leaf the wrong cell's baseline (e.g. a different `alpha`)
  would still score without error. Closing this gap fully would need a
  case-identity token threaded alongside the baseline value, which no
  caller in this milestone (no live-agent harness exists yet, §5) needs
  today; revisit when one is built.
- α is enumerated (3 values) rather than drawn "with equal probability"
  per run (fn 13) — a pilot-determinism choice, not a claim the paper's own
  randomization is unimportant at full scope.
- The paper's LLM prompt truncates history to a rolling 100 periods (§2.2);
  AERead's state keeps the full 300-round history — a future live-agent harness
  must truncate when building the prompt (boundary note, not a discrepancy).
- Asymmetric-quality reference prices/profits are AERead-computed; the paper
  confirms only their direction (App. A.2), a weaker citation than the
  symmetric baseline's exact-match numbers above.
- The 6-cell pilot is an integration gate, not a population estimate (mirrors
  `refund_external_benchmark_integration.md` §5's identical reasoning).
- `docs/benchmark_qc.md` **is cited above but does not exist on `main` or this
  branch.** It exists at commit `2b831fec7d9962bebe4396108ad47a5e2321d9e7` on
  unmerged branch `codex/procurement-harness-bakeoff` — the seventh independent
  benchmark file to confirm this gap after `ledger_entries/{amazonbarg,aucarena,
  govsim,negarena,steer,econevals}.md` (`runner_defect_ledger.md` `D-10`). This
  spec quotes that commit's real Gate 1/Gate 2 text directly into §1/§4 rather
  than re-deriving a taxonomy from the task brief alone. See
  `ledger_entries/collusion.md`.
- `CaseManifest.upstream_task_id` has no natural filler for a paper-only corpus
  (left `null`; same gap `econevals_adapter_spec.md` §1 already logged).
