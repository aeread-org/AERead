# Implementation Specification — `termsbench` adapter for the AERead shared-runner kernel

**Scope.** A **faithful reimplementation from the paper** of TERMS-Bench's bilateral
alternating-offer price-negotiation environment. There is no upstream code: the paper's own
repository link is dead, so the pinned source is the paper text, not an executable oracle.
Every doc/receipt must say "aeread reimplementation from paper, version-pinned to arXiv
2605.13909v2" — never "port" or "wraps upstream code". Tonight's slice: the environment
(§2.2.1, App. B), 3 of 6 counterpart behavior families (§2.2.2, App. C), and the deterministic
scoring axes computable from logged actions (SE⁺/CSE⁺, AGR⁺/FAGR⁻, CritViol%; App. F). The
Oracle-Cue Bayes-optimal DP upper bound (App. D–E) is **explicitly deferred** — no upper-bound
or `Gap_π` claim tonight; all comparative results are baseline/paired only.

**Pinned source.**

| Field | Value |
|---|---|
| Paper | "TERMS-Bench: Diagnosing LLM Negotiation Agents Beyond Deal Rate", arXiv `2605.13909v2` |
| Local artifacts | `upstream-termsbench-paper/paper.html` (sha256 `d62f52687a3d03a1fd3252501baed1bcb432bb2857edd66208de34eb26cb1848`), `paper.pdf` (sha256 `bea6a0a272f9e4f97539ebace7936239926268cb71c83f8d00203ba8398b1dcf`) |
| Upstream repository | **dead link** — no code pin exists; not used as a dependency, oracle, or parity target |
| Adapter family | `termsbench`, family package `src/aeread_families/termsbench/` |

## 1. Corpus enumeration and content digest (QC Gate 1)

There is no upstream corpus to re-resolve. The "source" Gate 1 check #1 re-resolves against
is **our own deterministic generator**, pinned by (a) the paper hashes above, (b)
`generator_id="termsbench_generator"` + `generator_version` (semver), and (c) an explicit
integer `world_seed` per case. Regenerating from the same `(generator_version, world_seed)`
must produce a byte-identical `CaseManifest`; `content_sha256` covers the generated payload
(regime draw, counterpart type `t_B`, opener `χ`, price bounds, every pinned hyperparameter
from Table 5/6), never a network artifact.

Generation pipeline per case, cited to source:
1. Draw regime ∈ {Overlap, No-deal} (§3.1) → reservation geometry `(r_buyer, r_seller)`, price
   bounds `p_min, p_max`. Urgency-shift is deferred (§6).
2. Draw counterpart family `𝓕` ∈ {Candid, Taciturn, Expressive} (§6 for why these 3).
3. Draw `t_B = (r_B, κ_B, η_B) ~ μ` (§2.2.1): `κ_B ~ Beta(α_κ,β_κ)` rescaled to `[0,1]`; `η_B`
   from the family's stance prior (Table 3 — uniform for these 3 families).
4. Draw opener `χ ∈ {AgentOpens, CounterpartOpens}` (episode protocol attribute, §3.2).
5. Compute pre-registered difficulty score `D_overlap^env` (eq. 67, App. G.2) or
   `D_nodeal^env`/`d_gap` (App. G.2) from steps 1–3 only (never from realized play — Gate 1
   check #3 forbids an outcome-dependent denominator) and assign one of 5 quantile bins
   (App. G.3).
6. Freeze the payload: `{regime, family, t_B, χ, price_bounds, difficulty_score,
   difficulty_bin, hyperparameters}` (Table 5/6 verbatim) → `CaseManifest.payload`.

`case_id = termsbench.<family>.<regime>.<seed>` (e.g. `termsbench.candid.overlap.7` — dots
only, id grammar forbids colons per `schemas.is_exportable_id`). `split` = family name;
`upstream_task_id = null` (no upstream numeric id exists); `provenance.review_status =
"generated"` (not `"upstream_pinned"` — nothing was pinned from a live repo). Duplicate
rejection (Gate 1 check #5) is seed-uniqueness plus a `(family, regime, difficulty_bin)`
stratum cap; dev/confirmatory splits (check #6) use disjoint seed ranges, never re-rolled.

Tonight's pilot manifest (mirrors `tau3_retail/base/pilot_manifest.json`): **30 scenarios** =
3 families × 2 regimes (Overlap, No-deal) × 5 difficulty bins, one seed per cell, opener `χ`
alternated by seed parity rather than stratified (kept out of the pilot's stratification to
hold cell count small; full corpus expansion adds it as a 6th factor).

## 2. Verifier declaration

Per `docs/research/verifier_taxonomy.md` §6 and `docs/research/verifier_case_mapping.md`'s `comparative` /
TERMS-Bench row: there is no defensible optimum without the deferred oracle, so the headline
value axis is `comparative`, `reference_kind="head_to_head"` (evaluated against the declared,
version-pinned counterpart family — not a paired cross-model design, though a paired
model-vs-model analysis can be layered on top using the kernel's existing
`analyze_paired_results`, keyed on `(condition_id, world_seed, replicate_index)`). Protocol
compliance is a genuine `rule_constraint` check (price bounds, IR, action legality against the
case's own declared constants), **not** comparative — it does not depend on the counterpart at
all. Four leaves, all `evaluation_class="deterministic"` per realized episode (the counterpart
kernel is stochastic *within* an episode, but each sealed `world_seed` realization is scored
deterministically from logged actions; repeated seeds are nested replicates per
`cluster_mapping: task_instance`, mirroring the tau3/refund convention):

| Leaf id | `verifier_family` | `reference_kind` | `input_scope` | `direction` | Declared for | Paper eq. |
|---|---|---|---|---|---|---|
| `termsbench_surplus_efficiency` | `comparative` | `head_to_head` | `terminal_state` | `maximize` | Overlap regime (`Δ_i>0`) | eq. 56 (§F.1) |
| `termsbench_feasible_agreement` | `comparative` | `head_to_head` | `terminal_state` | `maximize` | Overlap regime | eq. 57 (§F.1) |
| `termsbench_no_deal_agreement` | `comparative` | `head_to_head` | `terminal_state` | `minimize` | No-deal regime (`Δ_i<0`) | eq. 60 (§F.2) |
| `termsbench_protocol_compliance` | `rule_constraint` | `constraint_satisfaction` | `trajectory` | `minimize` | every episode | eq. 66 (App. B.3, F.4) |

`CSE⁺` (eq. 58) and `SafeTerm⁻ᵢ=1-FAGR⁻` are **corpus-level aggregations**, not separate
leaves: `CSE⁺` is the mean of leaf-1's sealed per-episode value over the subset with leaf-2
value `=1` (the agreed subset `A⁺`); the product identity `SE⁺=AGR⁺·CSE⁺` (eq. 59) is checked
as an analysis-layer invariant, not recomputed inside a `ScoreEnvelope`. Because
`analyze_paired_results` diffs `treatment − control` sign-agnostically and enforces
`within_case_score ≤ 1` (true here by construction: the committed price can never cross the
counterpart's own reservation bound, eq. 9's projection), the two `minimize`-direction leaves
are additionally fed to that helper as their maximize-oriented complements
(`SafeTerm⁺ = 1-FAGR⁻`, `Compliance⁺ = 1-CritViol%`) alongside the native metric recorded in
the receipt — exactly the paper's own §F.2 `SafeTerm` convention, not a workaround for a
kernel gap.

```python
MeasurementLeafSpec(
  estimand=EstimandSpec(estimand_id="termsbench_surplus_efficiency",
      input_scope="terminal_state", direction="maximize", units="zopa_fraction", ...),
  verifier=VerifierSpec(verifier_family="comparative", evaluation_class="deterministic",
      reference=ReferenceSpec(reference_kind="head_to_head",
                               input_scope="terminal_state", units="zopa_fraction", ...)),
  scorer=ImplementationRef(package="aeread_families.termsbench.measurement", ...),
)
```

Explicitly **not** declared tonight: `BE_type` (opponent-modeling Brier score, §2.3 Table 1,
out of scope per this cycle) and any `objective_reference`/oracle-gap leaf (App. D deferred).
Reference hashes point at the cited equations, not at a runtime artifact.

## 3. Adapter boundary

There is no upstream code, so "upstream owns / AERead owns" (refund doc §4) becomes
"**paper owns / AERead owns**":

**Paper owns** (pinned text, never altered): the regime generator (§3.1); the counterpart
kernel — opener protocol, acceptance model eq. 5–6, walk-away hazard eq. 7, counter-offer rule
eq. 8–9 (§3.2, App. C.2); family presets (Table 3–4); history-feature definitions eq. 12–14
(App. C.3); termination cases and constraints (App. B.3); metric formulas (App. F); difficulty
scores (App. G); all default hyperparameters (Table 5–6).

**AERead owns**: translating that mechanism into code — RNG-seeded `CaseManifest` generation
(§1); the phase graph and `step()` function below; a `ScriptedTermsBenchHarness` supplying
both seats without any LLM call (the counterpart is **not an LLM**, it is our from-scratch
reimplementation of the kernel above; the agent seat is a fixed script for goldens); canonical
events/evidence/replay/receipts; the 4 measurement leaves and scorers; the hand-derived goldens.

**Key structural difference from `tau3_retail`/refund**: with no oracle binary to delegate to
or diff against, "component-level parity" (refund doc §6, replay against upstream) is replaced
by **formula-level golden parity** — every golden's arithmetic is hand-derived from a cited
equation (shown in code comments) and cross-checked by a second, independently-written
evaluation of the same formula, never validated against upstream output because none exists.

### 3.1 Phase graph and one logical action

Two single-actor phases, strict alternation, opener `χ` decides round-1 seat (§2.2.1, §3.2):

```
χ=AgentOpens:        agent_turn ⇄ counterpart_turn   (agent moves first)
χ=CounterpartOpens:  counterpart_turn ⇄ agent_turn    (counterpart's opening offer moves first)
```

One agent logical action = one `a_k=(d_k,p_k,l_k)`, `d_k∈{Offer,Accept,Reject}` (App. B.2, eq.
11). One counterpart logical action = one realization of the stochastic kernel: draw
`(a_k, ω_k)` (eq. 5, 7) → resolve to `{Accept, Reject, Offer}` (§C.2.3) → if `Offer`, draw the
counter-offer price (eq. 8–9) → draw cues `(s̃_k,c̃_k)` (App. C.5.3; for our 3 families: base
model for Candid/Expressive, collapsed `{neutral,Hold}` for Taciturn) → render `l_k^B` from a
**deterministic template**, never an LLM (§6). `step()` re-executes the same formula code on
the recorded random draws (not re-sampling) so offline replay is exact — see §5.

`terminal()` fires on any of the 5 B.3 cases; `outcome()` returns `f_i ∈ [p_min,p_max]∪{⊥}`
plus `τ_terminal ∈ {AgentAccept, CounterpartAccept, AgentReject, CounterpartWalkAway, Timeout,
AgreementViolation}` (§C.2.3 — `AgreementViolation` is the paper's own name for an
invalid-Accept termination, used directly in Golden 3 below).

## 4. QC Gate-2 goldens

Common setup unless noted: `p_min=0, p_max=200` (`R=200`), agent role = buyer, `r_A=150`,
`r_B=100` (`Δ=50`), family = Candid (type-instrumental preset: `ρ(η)=(0,-0.25,-0.75)`,
`ξ(η)=(0.40,0,-0.50)`), `η_B=neutral`, `κ_B=0.5`, `K=10`, round `k=1` (so
`ConcedeSpeed_k=Rigidity_k=0`, boundary condition, App. C.3), `α=6,β=1,γ=2` (Table 5).

**1. Successful.** Agent (buyer, opens) offers `p=110`. `Δ̄₁=(110-100)/200=0.05≥0` → IR gate
passes (eq. 5). `D̃₁=√(1/10)=0.3162`, `D̃̄₁=0.6838`. `g_θ = 6(0.05)+1(0.5)-2(0.6838)+0+0 =
0.3+0.5-1.3675 = -0.5675` (eq. 6). `a₁=σ(-0.5675)=0.3618`. Counterpart RNG stub returns
`u=0.10 < 0.3618` → realized Accept (eq. 5). Termination case 3 (App. B.3): `f=110`.
`u_A(f)=r_A-f=150-110=40`; leaf-1 = `40/50=0.8`; leaf-2 = `1`; leaf-4 = `0` (no violation:
`110∈[0,200]`, `110<150`). Exercises leaves 1, 2, 4.

**2. Valid but poor.** Counterpart's price/message is **pinned directly as fixture input**
(bypassing the stochastic kernel — this golden isolates the *scorer*, not the RNG): a prior
counterpart offer of `p=145` is given. Agent accepts. `f=145`, `u_A(f)=150-145=5`, leaf-1 =
`5/50=0.10` — legal, positive, but poor surplus; leaf-4 = `0`. Per Gate 2, the low-quality
outcome stays valid and preserves the component (surplus is reported honestly, not clipped or
flagged invalid).

**3. Invalid/unauthorized.** Round 1, `χ=AgentOpens` (no counterpart offer yet observed).
Agent's action is `Accept`. This is the F.4 invalid-action case ("choosing Accept when no
counterpart offer has been observed") — cannot bind to any price. Adapter rule: terminates
immediately as `τ_terminal=AgreementViolation`, `f=⊥` (App. C.2.3 already names this outcome).
`u_A(⊥)=0` by definition; leaf-2 = `0` (no positive credit for an unauthorized action); leaf-4
= `1` (`InvalidAct%` component of eq. 66). No protected state (price, DB) is touched.

**4. Malformed/operational.** The agent's raw response for round `k` fails to parse into the
`{d_k,p_k,l_k}` schema. Per §F.4 ("If the malformed output prevents recovery of a valid
economic action, it is also counted as an invalid-action violation"), the episode is typed
`invalid_measurement` at the receipt layer (`docs/research/verifier_taxonomy.md` §9): leaves 1–2 report
`ValidityReport(status="invalid", reasons=["malformed_action_schema"])` and are **excluded**
from the SE⁺/AGR⁺ denominators for that cell (never scored as an economic zero), while leaf-4
still records the violation (`InvalidAct%=1`) — the paper's own convention double-counts
unrecoverable schema failure as both "missing" for value axes and "positive" for compliance.

**5. Degenerate reference.** Cell = (Candid, Overlap, hardest difficulty bin), 5 scripted
episodes, all `Δ_i>0`. Agent script = immediate `Reject` in round 1 for all 5 → `f_i=⊥` ∀i.
`SE⁺ = (1/5)Σ(0/Δ_i) = 0` (disagreement contributes zero utility, well-defined, §F.1).
`AGR⁺ = 0/5 = 0` → `A⁺=∅` → **`CSE⁺` is reported `undefined`**, never imputed as `0` (eq. 58's
own text: "If an agent reaches no feasible agreements, we report `CSE⁺` as undefined rather
than imputing a value"). The identity `SE⁺=AGR⁺·CSE⁺` (eq. 59) is vacuous here and is not
asserted when `CSE⁺` is undefined.

## 5. Test plan

No upstream binary exists, so there is no upstream-replay parity procedure (refund doc §6) —
parity is **formula-level**: every golden above is asserted twice, once via the adapter
scorer and once via an independently-written re-derivation of the same cited equation.

- `test_termsbench_cases.py` — generator determinism (same `(generator_version, world_seed)` →
  byte-identical manifest, stable `content_sha256`); difficulty-bin assignment is
  outcome-independent (Gate 1 check #3).
- `test_termsbench_counterpart.py` — acceptance/walk-away/counter-offer formulas (eq. 5–9)
  against hand-derived values across the 3 presets in Table 4; history-feature boundary
  conditions (App. C.3: `<2` agent/counterpart offers ⇒ features `=0`).
- `test_termsbench_environment.py` — phase graph both opener orders; all 5 termination cases
  (App. B.3); constraint checks (price bounds, monotonic concession, IR) map to the right
  `V^crit` component.
- `test_termsbench_measurement.py` — the 4 leaves against the 5 goldens in §4, plus the
  `SE⁺=AGR⁺·CSE⁺` invariant on a small enumerated corpus.
- `test_termsbench_replay.py` — **replay reconstructs from recorded random draws, never
  re-samples them.** The counterpart kernel is genuinely stochastic (Bernoulli accept, Gaussian
  price noise `ε_k`, cue draws), so every draw `step()` consumes must be sealed as evidence per
  round (unlike tau3, where re-executing a deterministic tool is itself the replay check).
  Offline replay with the RNG source stubbed to the sealed draws must reproduce every
  transition state hash and terminal outcome, zero network calls, zero re-sampling.

No bridge is required (`bridge: "none"`): the whole mechanism is closed-form Python, no
upstream package, no network, no venv.

## 6. Stated limits

- **Oracle-Cue Bayes-optimal DP (App. D–E) is explicitly deferred.** No `π*`, no `Gap_π`, no
  saturation or upper-bound claim is emitted tonight. All results are comparative/paired
  against the declared counterpart only (`docs/research/verifier_taxonomy.md` §13's own
  `not_demonstrated` framing for TERMS-Bench applies unchanged).
- **`BE_type`** (opponent-modeling Brier score over `r_B,κ_B,η_B`, Table 1) is out of scope
  this cycle; cues (App. C.5) are modeled only as far as environment fidelity requires for the
  3 implemented families, not scored.
- **3 of 6 families implemented**: Candid, Taciturn, Expressive — the type-instrumental and
  high-reactivity legs of the 2×2 diagnostic core (Table 3), sharing only 2 economic presets
  and a uniform stance prior, i.e. the most fully-pinned dynamics with the fewest unresolved
  knobs. Strategic (same preset as Expressive, cue-channel-only difference), Stochastic
  (elevated noise/temperature sampling), Adversarial (skewed prior + hardball preset) deferred.
- **Urgency-shift regime deferred**; only Overlap and No-deal are generated tonight (§1).
  Data-grounded scenarios (§3.3) and the Bankroll/Commerce extension (§4.4, App. J) are
  out of scope — paper-declared extensions, not the core instantiation.
- **No LLM-authored counterpart language.** `l_k^B` renders from a deterministic template
  keyed on `(d_k,p_k,s̃_k,c̃_k)`, never App. C.5.4's LLM voice layer — required for a
  provider-free adapter. Goldens validate the economic scoring pipeline, not message realism.
- Secondary diagnostics (`MonoViol%`, turn-budget, information-leakage flag, App. F.4) are
  logged but not gated; only `CritViol%` is a scored leaf tonight.
- **No kernel/runner defect was found.** One adapter-design note, not a defect:
  `paired_analysis.analyze_paired_results` is direction-agnostic (unsigned
  `treatment−control`) and enforces `within_case_score≤1` — both satisfied by feeding it
  maximize-oriented complements for the two `minimize` leaves (§2), the paper's own `SafeTerm`
  convention, not a workaround.

## 7. Milestone 1 amendment (cases + environment): reality-forced deviations

Built: `src/aeread_families/termsbench/{kernel,cases,environment,harness}.py`,
`cases/termsbench/pilot/` (30 cases + `pilot_manifest.json`), and
`tests/test_termsbench_{cases,counterpart,environment}.py`. **Not built yet**: the 4
measurement leaves (`build_scorer` raises `NotImplementedError`, deferred to milestone 2) and
`replay.py`'s standalone sealed-draw replay harness (deferred; `step()` itself already
re-executes `kernel.resolve_counterpart_turn` on the recorded draws and raises on mismatch —
see §3.1 and `TermsBenchPlugin._step_counterpart`).

Every deviation below is an **AERead-owned engineering decision** translating a paper
mechanism into code (§3's ownership split), not a change to what the paper itself specifies:

- **Regime-generator numeric ranges are an AERead choice, not a paper default.** Table 10
  ("regime-specific task generation parameters ... are provided in Table 10 in Section H")
  and Appendix C.6 ("regime-specific task generation parameters used in experiments are
  provided in Table 10 in Section H") cross-reference **each other** for the concrete values
  of `(ακ, βκ, α_shifted, β_shifted, Δmin, Δmax, gmin, gmax)`; neither section actually
  contains the numbers, in both the pinned `paper.html` and `paper.pdf` renderings. This is a
  gap in the published paper itself, confirmed by reading both pinned artifacts directly, not
  an extraction bug. `kernel.py` freezes concrete values once (`P_MIN=0, P_MAX=200` reusing
  this spec's own §4 golden common-setup scale; `ZOPA_WIDTH_MIN/MAX=20/100` so the golden's
  `Δ=50` sits centrally; `NODEAL_GAP_MIN/MAX=20/100` symmetric; `Beta(2, 2)` for the baseline
  urgency law, symmetric with mean 0.5 matching the golden's `κ_B=0.5`), documented at each
  constant's definition. `K=10` is not part of this gap — it is confirmed independently in
  Appendix D's backward-induction sizing note ("With N≈300, M=50, K=10, ...").
- **Small numerical-stability constants** `ε_κ, ε_σ, ε_d, ε_c` (App. G.2, C.5) are named by
  the paper but never assigned a value; `kernel.py` sets each to `1e-6`.
- **Pilot fixes `agent_role="buyer"`** for all 30 cases. The full paper design balances agent
  role and opener role in a 2x2 within each regime-family cell across a much larger main suite
  (§4.1/H.1.2); the pilot instead only alternates opener `χ` by seed parity (already specified
  in §1) and holds role fixed to keep the 30-cell design exactly as specified. Role-balancing
  is deferred to a future corpus expansion, not silently dropped.
- **Round index `k` under mixed opener roles.** The paper shares one subscript `k` between
  the agent's `k`-th offer and the counterpart's `k`-th response, and confirms `k=1` for the
  boundary case worked in golden 1 (agent opens). It does not fully disambiguate `k`'s
  bookkeeping when the counterpart opens and then also produces the *next* substantive
  response — there is no reference implementation to check against (dead repository link).
  `environment.py`/`kernel.py` operationalize `k` as **the counterpart's own invocation
  counter** (starts at 1, increments by exactly 1 every time the counterpart acts — opening or
  responding — and never on an agent move); this coincides with the paper's own text for every
  configuration the goldens exercise and is the natural reading of a shared per-round `k` for
  an alternating-offer protocol.
- **Termination vocabulary is lower_snake_case** (`agent_accept`, `counterpart_accept`,
  `agent_reject`, `counterpart_walk_away`, `timeout`, `agreement_violation`), not the paper's
  PascalCase (`AgentAccept`, ...): `CaseManifest.episode.termination` values must satisfy the
  identifier grammar, which forbids uppercase. The mapping to the paper's own vocabulary
  (App. C.2.3) is 1:1 and total; see `cases.TERMINATION_REASONS`.
- **`docs/operations/benchmark_qc.md` does not exist in this repository.** The build instructions for
  this milestone named it as the source for QC Gate 1/2 definitions; this spec's own §1 and §4
  already restate every Gate 1 check (#1, #3, #5, #6) and the Gate 2 golden conventions inline,
  cited to this document, so no gate definition was actually missing — only the filename.
