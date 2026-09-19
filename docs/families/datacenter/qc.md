# Data-center development QC profile

**Standard:** [AERead benchmark QC](../../operations/benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](../../operations/experiment_campaign_sop.md)

**Design plan:** [development negotiation implementation plan](development_negotiation_implementation_plan.md)

**Status:** case-specific profile covering six registered family ids;
`profile_admission=passed`, while
`task_distribution_admission=failed`,
`environment_and_verifier_qc=partial`,
`construct_validity=failed`,
`attribution_and_controls=partial`,
`confirmatory_reliability=not_run`, and
`normative_datacenter_profile=failed`.

Two gates are failed, and the construct failure is the most important line in
this profile. On `cases/datacenter_development_v1/v2/full_stack_amendment_001.json`
the declared scripted-developer comparison baseline is **-155,000 cents** while
the case's own outside option is **-100,000 cents**. The reference the family
compares subjects against is dominated by walking away, by 55,000 cents, and
nothing rejects it: the dominance precondition exists only in the 2.1.0 objective
scorer (`src/aeread_families/datacenter_development/objective_measurement.py:198-199`)
and the three earlier identities are scored by `DataCenterDevelopmentScorer`
(`measurement.py:131`), which has no such check. The consequence is measured, not
hypothetical: in `evidence/datacenter_development/datacenter_development_v2_interaction_v1/`
all four model-by-condition groups scored exactly the outside option
(`mean_developer_equity_npv_cents = -100000.0`, `project_completion_rate = 0.0`)
against a `scripted_baseline` of `-155000.0`. A policy that refuses to negotiate
at all beats the declared reference on that case. That is the same class of
failure procurement's Gate 3 found, and it had nowhere to be recorded here.

What this family did **not** do is over-claim. All 33 campaign contracts in
`configs/datacenter*.json` declare a `claim_status`, every one of them is
diagnostic, exploratory, preflight or reliability-only, none is confirmatory, and
every published README denies a winner, a ranking, a population effect or a
causal claim. The bundles also carry machine flags
(`winner_claim_allowed: false`, `inferential_model_ranking_allowed: false`,
`project_generalization_allowed: false`). The gap Gate 0 names was therefore not
a false claim but a missing artifact: the gate verdicts had nowhere to land, so
a dominated baseline read as an interesting negative panel rather than as a
construct-validity failure.

This profile binds the shared gates to the data-center families. Requirements
inherited from the standard are not repeated unless this family supplies a
specific implementation, threshold, policy or artifact.

## Scope: one profile, six registered family ids

The standard asks for a profile at `docs/families/<family>/qc.md`. These six ids
share one environment lineage, one cash-flow kernel and one scorer family, so
they share this document and each carries its own typed statuses where they
differ. Registrations are in `src/aeread/shared_runner/registry.py`.

| Family id | Versions | What it is | Cases on main |
|---|---|---|---|
| `datacenter_development_v1` | 1.0.0, 1.1.0, 2.0.0, 2.1.0 | the negotiation stack: service and loan terms, then power and EPC, then the full six-agreement stack | 4 curated projects, one per version |
| `datacenter_counteroffer_adoption_v1` | 1.0.0, 1.1.0, 1.2.0 | nested prefix ladder (land, land+power, land+power+EPC) | 9 files, all one world |
| `datacenter_counteroffer_salience_v1` | 1.0.0 | `full_package` against `explicit_delta` presentation | 2 files, same world |
| `datacenter_counteroffer_affordance_v1` | 1.0.0 | `reemit_package` against `accept_by_reference` | 2 files, same world |
| `datacenter_counteroffer_action_schema_v1` | 1.0.0 | `shared_offer_schema` against `dedicated_accept_schema` | 2 files, same world |
| `datacenter_development_terms_v1` | 1.0.0 | single-phase report on SEC-grounded project terms | 6 on-disk packs (20 authored cases) plus 8 derived packs |

Every one of the 15 counteroffer case files pins the *same* base world:
`world_seed = 312101`, `base_case_id = datacenter_development_v1.v2.objective_bounded_001`,
`base_case_sha256 = 3e487d62…5139` (base path pinned at
`src/aeread_families/datacenter_development/adoption_environment.py:25-31`). Four
of the six ids therefore have an independent-cluster count of one by
construction, and that is a property of the family, not of any one campaign.

## 0. Profile admission

`passed` as of 2026-09-19: this document is the profile, it records a typed
status for the family and for each of Gates 1 through 5, and it states a blocker
for every gate that is not `passed`. Before it existed all six ids sat on the
dated exemption list in `tests/test_benchmark_qc_profiles.py`, which means they
were `failed` at this gate for the whole life of the family — including through
the 30 published campaigns inventoried below.

## 1. Task-distribution admission

**Status: partial** (was `failed` until 2026-09-19; see the world pack below).

The independent unit differs by side of the family and both are declared:

- negotiation side (`datacenter_development_v1` and the four counteroffer ids):
  the **curated project**, one case being one negotiated agreement stack. The
  four projects are different family versions with different agreement counts
  (2, 4, 6, 6), and `cases/datacenter_development_v1/README.md` forbids pooling
  across them.
- terms side (`datacenter_development_terms_v1`): the **source cluster**,
  declared per pack as `independent_sampling_unit` with an
  `independence_cluster_count`. Wording conditions over one cluster are paired
  mirrors, asserted byte-identical except the prompt suffix
  (`tests/test_datacenter_terms_public_integrated_expansion_v4.py:39-58`), and
  are never independent observations of it.

What is validated today:

| Check | State |
|---|---|
| Per-case content digest, re-derived in tests | `content_sha256` on every case, re-derived at `tests/test_datacenter_runner.py:18`, `tests/test_datacenter_stack.py:148`, `tests/test_datacenter_adoption.py:83-88`, `tests/test_datacenter_salience.py:60`, `tests/test_datacenter_affordance.py:34`, `tests/test_datacenter_action_schema.py:47`; `expected_case_sha256` in every campaign contract |
| Pack digest for the terms family | `pack_sha256` as a length-prefixed digest over the pack's files (`public_cases.py:79-86`, `:326-327`); derived packs pin `base_pack_sha256` and their loaders raise on any mismatch (`public_affirm_only_cases.py:34-71`) |
| Denominator and reference recompute | `validate_payload` re-simulates the scripted baseline and rejects a drifted case (`environment.py:292-304`, `stack_environment.py:365-373`); the terms packs reconcile their own arithmetic oracle (`public_cases.py:70-76`) |
| Duplicate identifiers | rejected inside a pack (`public_cases.py:187` and siblings) and per campaign cell (`publication.py:179`) |
| SEC source pinning | accession, document, URL and clause locators, with `upstream_sha256: null` and `upstream_byte_hash_status: not_available_shell_retrieval_returned_http_403` recorded honestly in `cases/datacenter_development_terms_v1/public_v1/source_catalog.json` |

What does not exist, and why the gate is `failed` rather than `partial`:

1. **No informativeness screen of any kind.** There is no counterpart to
   procurement's `headroom_screen.classify_world`: no trivial, floored or
   saturated classification, no measured control rate per world, no multi-seed
   screen, no within-world variance report. A search for headroom, saturated,
   degenerate, trivial or floored across the datacenter sources, tests and docs
   returns nothing.
2. **A degenerate case was admitted, and the admission rule cannot see it.**
   `full_stack_amendment_001` carries a reference worse than its own outside
   option (see the status note above). `validate_payload` checks that the
   authored baseline matches the simulation, which it does; nothing checks that
   the baseline is worth reaching.
   **Repair (2026-09-19):** `full_stack_amendment_002` carries an opt-in
   `construct_controls` block; `validate_payload` refuses a case that declares
   it unless the scripted reference strictly dominates the outside option by
   the declared margin (here 28,000 over a 25,000 minimum) and every negotiated
   price is bounded on both sides. Switched on against the sealed `001` payload
   the guard dies on both controls (`test_construct_controls_guard_kills_the_sealed_dominated_case`);
   `001` itself is unchanged, so no published campaign moves. The gate stays
   `failed` for the family: one repaired case is not an admission screen.
3. **Seeds are repeats, not replicates.** `cases/datacenter_development_terms_v1/README.md:149-155`
   records that in integrated V5 all six model-by-project groups repeat exactly
   across seeds. The effective sample size of a panel is its cluster count, and
   any interval computed across rows is narrower than the truth by construction.
4. **No development-versus-confirmatory split.** The `split` values (`dev`,
   `v1`, `v2`, `v3`) are family-version stages, and the adoption v2 and v3 cases
   are repairs of the same three worlds rather than held-out ones. The only
   artifact named held-out — `public_candidate_screen_v1` — is three fresh
   *inference* seeds on the same Denton case, which the standard itself excludes
   at `docs/operations/benchmark_qc.md:124`: "a new seed alone is not a held-out
   mechanism condition".
5. **No near-duplicate clustering across packs.** The Core Denton cluster
   appears as the fifth case of `public_v1/`, as all six cases of
   `public_mechanism_v1/`, and as the single case of
   `public_candidate_screen_v1/`. Only per-pack counts are asserted; nothing
   detects the overlap.
6. **The planned panel does not exist.** The design plan declares 24 worlds
   across six mechanism strata — revenue without bankability, delayed revenue,
   restrictive draws, covenant cliff, liability transfer, verbal/written
   divergence (`development_negotiation_implementation_plan.md:321-331`). No
   case file carries a stratum label and no test stratifies on one. What shipped
   is one curated project per version.

**Main blocker:** an admission screen that measures whether a world can express
a difference, plus a case-level rejection of a reference that does not
strictly dominate the outside option for the 1.0.0, 1.1.0 and 2.0.0 identities.

**World pack (2026-09-19).** `cases/datacenter_development_v1/worlds_v2/` holds 24
generated worlds — six mechanism strata, four variants each, 50 MW / 36 months
at published 2026 figures — ported from `codex/datacenter-world-panel-v1` and
regenerated on `main`. Every world is refused at generation unless a naive
strategy fails it (`solved_by_naive_strategy`: adopt every counter, market
convention, adopt-and-size), its declared lever moves value (`lever_is_inert`),
its concession costs something (`concession_is_free`), its feasible path beats
walking away, and it passes the `construct_controls` guard with a declared
margin of 1% of the EPC contract price. Closing the guard's two-sided rule
required flooring six money terms the branch had left one-sided, which is the
guard doing on 24 worlds what it did on `001`. Independent clusters: 24.
Still missing for `passed`: a development-versus-confirmatory split bound to
disjoint seed domains, near-duplicate clustering across strata, and a measured
control rate per world from the frozen control rather than from the scripted
reference alone.

## 2. Environment and verifier

**Status: partial.**

The oracle is a deterministic monthly ledger, `simulate_project`
(`cashflow.py:488`), with the stack variant `simulate_development_stack`
(`stack_cashflow.py:105`) adjusting terms and then calling it. There is **no
independent second implementation** for any family id, and no exhaustive
enumeration anywhere in the tree. `validate_payload` recomputing the authored
baseline with the same function is a self-consistency check, not a cross-check.
The compensating control is that the same simulator produces the baseline, the
outside option and the score, so a defect in it moves all three together rather
than producing a disagreement; the price is that the family cannot detect such a
defect from disagreement. This is a known weakness, not a strength.

Goldens by kind. The standard asks for six; this is what exists:

| Golden | `development_v1` | `adoption` | `salience` / `affordance` / `action_schema` | `terms` |
|---|---|---|---|---|
| Successful trajectory | `test_datacenter_runner.py:55`, `test_datacenter_stack.py:148`, `test_datacenter_objective.py:315` | `:140`, `:270`, `:339` | `salience:100`, `affordance:65`, `action_schema:112`, `:235` | `test_datacenter_development_terms.py:177`, `:193` |
| Valid but poor | `test_datacenter_stack.py:239` (outside option) | **none** | **none** | **none** (only a hard-gate zero at `:209`) |
| Invalid or unauthorized | scored on hand-built dicts only (`objective:263`, `:293`) | `test_datacenter_adoption.py:167`, the one test that drives an invalid action | published-row assertions only (`action_schema:340`) | **none** |
| Rejected action leaves state unchanged | `stack:97`, `contracts:74` | `adoption:113` (closest) | **none** | not applicable (single phase, report authority) |
| Malformed model output | **none** (parser-level only) | partial, via `:167` | **none** | `terms:224`, `:158` |
| Degenerate reference | **none** for any id: `cashflow.py:60-62`, `cashflow.py:76-79` and `objective_measurement.py:198-199` are untested guards | | | |

Leakage is the best-covered requirement in this family and every id has a test:
`runner:31`, `stack:198` and `:217`, `objective:153`, `adoption:92`,
`salience:74`, `affordance:48`, `action_schema:61`, `terms:80` and `:98`, plus
pack-level oracle hiding at `test_datacenter_terms_public.py:64`. The caveat is
that most assert substring absence over `repr(observation)` rather than a
structural allowlist.

Ledger identities exist and are real: per-row sources equal uses and the debt
rollforward `opening + draw == repayment + closing`
(`test_datacenter_cashflow.py:115`), DSCR breach typed separately from a funding
shortfall (`:177`), and a metamorphic property that service price is a pure
transfer leaving `cod_month` invariant (`:160`). They cover `cashflow.py` only:
there is **no test file for `stack_cashflow.py`**, so the six-agreement ledger
every V2 campaign ran on has no sources-equals-uses assertion.

**Replay is the weakest point.** Nothing re-drives a published row through the
environment and recomputes its score. Per-run replay via the kernel's
`replay_family_receipt` is asserted on fixtures generated inside the test
(`runner:83`, `stack:177`, `objective:320`, `adoption:148`, and six more), and
publishers then *copy* a `replay_verified` boolean into the sealed bundle
(`adoption_publication.py:204`, `public_publication.py:145`, and siblings), which
the publication tests assert as a boolean. Across 30 bundles and **531 sealed
rows**, the published claim of replay rests on a flag, not on a recomputation.
Procurement's regret decomposition, which re-drives every published action trace
and matches to $0.000001, has no datacenter counterpart.

Sixteen datacenter tests are gated on a gitignored `runs/<campaign_id>`
directory by the `local_run` marker (`tests/conftest.py:31-50`), which skips
locally and fails under `AEREAD_LOCAL_RUNS_REQUIRED=1`. Fourteen of them guard a
bundle that a second, ungated test also checks. Two do not:
`datacenter_development_terms_public_integrated_v12` has **no committed bundle
under `evidence/`**, so both of its publication tests skip and that campaign's
publication is verified by nothing on a clean checkout.

No datacenter test records a **mutation kill** in the sense the standard
requires. What exists is a set of corruption counterexamples — a broken
arithmetic oracle (`test_datacenter_terms_public.py:271`), accession drift
(`:253`), pair and world-seed drift
(`test_datacenter_terms_public_mechanism.py:154`), a wrong-fields amendment
(`stack:97`) — which show a guard rejecting a broken input but not a guard being
reverted and observed to die.

**Schema and parser agree (2026-09-19, DC-D-07).** For cases that opt into
`construct_controls`, the strict developer output schema carries every lower
bound the contract parser enforces (`stack_runner.TERM_MINIMUMS`; every other
integer term non-negative) and the developer prompt states that months are
numbered from 1. The gap cost five of the first ten pilot cells. Sealed cases
keep their v1 schema and prompt byte for byte.

**Main blockers:** replay that recomputes a published score instead of copying a
flag; ledger identities for `stack_cashflow.py`; the missing invalid-action and
malformed-output goldens for the salience, affordance and action-schema ids; and
a committed bundle for integrated V12 or its removal.

## 3. Construct validity and baselines

**Status: partial** (was `failed` until 2026-09-19; see the scored controls below).

Declared controls, as they exist on main:

| Control the standard asks for | State in this family |
|---|---|
| No-op or feasible lower anchor | the case's `outside_option` (walking away) is a legal economic outcome, but it is **not run as a policy**, so it has no measured score to compare against |
| Seeded random or weak behavioral control | **does not exist** |
| Simple comparison baseline | the authored `scripted_developer` re-simulated per case; on the V2 full-stack case it is dominated by the outside option |
| Informed or adaptive policy | **does not exist** |
| Oracle-informed diagnostic ceiling | only for 2.1.0: `developer_equity_npv_reference` with `reference_kind: exact_optimum` and `certified_control_reference = -95000.0` cents |

Three findings bound what this family can claim:

1. **The comparison baseline is beatable by refusing to play.** Numbers in the
   status note above. A beatability rule was never predeclared, which is why a
   panel where every subject scored the outside option was read as a completion
   floor rather than as the baseline failing.
2. **For the adoption family, copying is the scored optimum.** The primary
   leaf's `required_behavior` is to copy each complete written counter package
   exactly and sign its accepted offer id
   (`adoption_measurement.py:93-110`), and the counterparty counters even when
   the terms are already exact (`test_datacenter_adoption.py:113`). That is a
   defensible instrument for *contract compliance*; it cannot distinguish
   negotiation quality from transcription, and no test asserts that copying the
   counterparty's offer is suboptimal.
3. **One instrument contrast did discriminate, on one world.** In
   `datacenter_counteroffer_affordance_v1`, re-emitting the package succeeded
   9 of 10 against 5 of 10 for acceptance by reference, on 10 usable pairs with
   byte-identical initial observations. This is the family's most informative
   published result and it is an *interface* finding, not a capability one.

**Main blocker:** a declared policy set run through the active interface — at
minimum a walk-away anchor and a blind-adoption policy — with a predeclared
beatability rule, on a case whose reference strictly dominates walking away.

**Scored controls (2026-09-19).** Three provider-free developer policies now
run through the real scheduler — the scripted reference at the floor of every
band, `walk_away` at the first offer, and `adopt_every_counter` (an opening the
counterparty must refuse, then its counter copied verbatim) — on the repaired
curated case and all 24 worlds, every trajectory finalised, verified and
replayed: 75 trajectories, 75 included. The reference beats walking away in
25 of 25 cases and beats adoption in 25 of 25; adoption completes the stack
only on the curated case (−155,000, below walking) and on every world declines
the landowner's no-op amendment counter and strands at the outside option, the
trap the worlds set for a transcriber. On the worlds the reference clears
walking away by a median of 54.4 billion cents. Published as the derived
bundle `evidence/datacenter_development/datacenter_v2_scored_controls_v1/`,
regenerated never edited (`python -m aeread_families.datacenter_development.scored_controls`).
Still missing for `passed`: a seeded random or weak behavioural control, an
informed policy that uses the counterparty's stated reasons, shortcut tests on
the prompt surface, and a beatability rule predeclared before any live subject
is read against these anchors.

**What changed on 2026-09-19.** Two live probes on the sealed V2 case (Gemini
3.8 Flash and GPT-6 Astra, three seeds each, $1.10 in total) showed why the
score hides everything: Gemini opened every agreement bidding *against itself*
(300,000 for land quoted at 20,000), was countered only because an unrelated
field breached a ceiling, then copied the counter and scored exactly the
reference, -155,000; Astra bid 800,000 for the same land, demanded three times
the customer's price ceiling, never conceded to it, stranded the project and
scored the outside option, -100,000 — better than Gemini by failing to close.
Re-simulation showed the case's own optimum was an EPC price of one cent
(+69,999) because the bands had ceilings and no floors, and that a 300,000
land bid with the other fields in band is *accepted* (-435,000) because the
purchase price had a floor and no ceiling. `full_stack_amendment_002` closes
both holes with two-sided bands (floors 15% below the counter, 8% for EPC;
ceilings at the counter; the customer's price ceiling opened to 160 against
its value of 200) and re-points the scripted reference to the floor of every
band: it scores -72,000, beating walking by 28,000, while copying every counter
stays admissible and still loses (-155,000), which is the trap the case now
sets. The walk-away and blind-adoption controls are still owed as *scored*
policies. The decision tree, the simulated ladders and the repaired
case's ladder are recorded in [the V2 walk-away analysis](v2_walk_away_analysis.md).

## 4. Attribution and experimental controls

**Status: partial.**

What is genuinely strong here, and stronger than in most families:

- every campaign contract declares `claim_status`, `expected_case_sha256` or
  `pack_sha256`, `inference_seeds`, and a `route_catalog_snapshot`;
- paired conditions are proven identical apart from the treatment at the byte
  level: identical initial observations and profiles for the action-schema and
  affordance pairs (`action_schema:61`, `affordance:48`), and identical
  evidence, oracle, authority, cluster id and world seed for the terms wording
  pairs (`expansion_v4:39-58`);
- typed missingness is preserved rather than scored: excluded rows are sealed
  with `replay_level: none` and `scores is None` (`stack:507-509`,
  `objective:518`, `terms:303`, `:432`);
- the machine flags forbidding a winner or ranking claim are written into the
  bundles themselves.

The blockers are all about the assignment block, not the pinning:

1. **The independent cluster is one, in all eleven `datacenter_development`
   bundles and in eight of the nineteen terms bundles.** The maximum any
   datacenter bundle ever reached is five
   (`terms_public_v1`, `terms_public_gptoss_v1`, `terms_public_affirm_only_v1`);
   the integrated series runs at three. With seeds behaving as repeats, no
   published bundle supports a cluster-level interval.
2. **Exposure-qualified pairs collapse below the planned count.**
   `action_schema_v1` planned 10 pairs and produced **0** exposure-qualified
   ones, 17 of its 19 completed cells having emitted an invalid opening action;
   v2 recovered 6 of 10.
3. **Attrition is large and provider-driven.** Two campaigns completed **zero**
   of six planned cells (`v2_objective_grounding_v1` and `v2`, failure fraction
   1.0); `grounded_glm_v1` lost 8 of 12 to rate limits; `integrated_v4` lost 9
   of 18 to a provider rejecting `uniqueItems`. Every one of these is sealed as
   typed missingness, which is correct, and none of them leaves a reportable
   matrix.

**Main blocker:** a matrix with more than one independent cluster on a case
whose construct gate passes; until then attribution claims stay at the level of
one project.

## 5. Confirmatory reliability and publication

**Status: not_run.**

No step of the required sequence has been attempted: there is no declared
variance pilot, no confirmatory freeze artifact, no holdout table, and no
`analysis_plan` anywhere in the 30 bundles. The nearest artifacts are a
`decision_rule` and `primary_endpoint` in
`terms_public_glm_transfer_v1/reports/summary.json` (which returned
`inconclusive_operational_missingness`) and a `primary_contrast` in
`terms_public_candidate_screen_v1`. The word frozen appears only as prose about
a run configuration.

When this gate is attempted, the guarded metric must be chosen so that walking
away fails it. Today it does not: the outside option is a legal terminal
economic outcome, so a subject that never transacts scores `-100,000` cents and,
on the V2 case, beats the reference. Procurement hit exactly this with terminal
feasibility counting a deferral as a success; the lesson transfers, and
`project_completion_rate` — `0.0` for every group in the interaction campaign —
is the candidate the family already records.

**Main blocker:** Gates 1 and 3 are failed, so a confirmatory design would
measure a case that cannot express a difference against a reference that
refusing to play can beat.

## 6. Current implementation coverage

| Gate | Current coverage | Main blocker to `passed` |
|---|---|---|
| Profile admission | this document, as of 2026-09-19 | none |
| Task-distribution admission | 4 curated projects, 15 counteroffer cases on one world, 6 authored terms packs with pack digests and honest source lineage | **Failed:** no informativeness screen, no split, and a case admitted whose reference is dominated by walking away |
| Environment and verifier | deterministic ledger with sources-equals-uses and rollforward identities, leakage tests for all six ids, provider-free success goldens, typed missingness | **Partial:** replay copies a flag over 531 published rows instead of recomputing; no identities for `stack_cashflow.py`; five golden kinds missing on three ids |
| Construct validity and baselines | one authored scripted-developer reference per case; a dominance precondition on the 2.1.0 identity only | **Failed:** the reference is beaten by not transacting; no no-op, random, adaptive or blind-adoption policy exists |
| Attribution and controls | claim status, digests and route snapshots on all 33 contracts; byte-identical paired conditions; typed missingness | **Partial:** one independent cluster in 19 of 30 bundles, five at most; 0 of 10 exposure-qualified pairs in one campaign |
| Confirmatory reliability | nothing attempted; all 33 contracts declare diagnostic, exploratory or reliability-only | **Not run:** blocked by Gates 1 and 3; the guarded metric must be one a walk-away fails |

## 7. Registers

Tier 1 does not exist on main. `docs/operations/incident_log.md` indexes a
data-center register at `evidence/datacenter_failure_register.{json,md}` marked
*to be moved*; that path is absent from `main`, and the register in the standard
layout exists only on the unmerged branch `codex/datacenter-world-panel-v1`. The
index row is therefore stale in both directions and is corrected alongside this
profile. Tier 2 rows for the defects this audit found are in the data-center
section of the incident log.

## 8. Published campaigns

Thirty sealed bundles: 11 under `evidence/datacenter_development/` and 19 under
`evidence/datacenter_development_terms/`, together 531 rows in
`trajectories/sanitized.jsonl`, all digest-verified against their manifests. The
largest is `terms_public_mechanism_v1` at 53 of 54 cells; the smallest is the
two-cell probe of 2026-09-03. Total recorded spend across the family is under
$0.11, most bundles reporting a `lower_bound` because failed calls report no
usage.

None of them is confirmatory, none claims a winner, and after this profile none
of them may be described as measuring the family's declared construct until
Gates 1 and 3 change status.

## 9. What may be claimed today

Data-center results describe **whether a model can conduct a legal, internally
consistent multi-agreement negotiation and report grounded project terms, on one
to five clusters, as a diagnostic**. Specifically permitted:

- interface and instrument findings on a single world, labelled as such — the
  affordance contrast is the worked example;
- operational findings about routes, schemas and provider behavior, which is
  what the integrated V4 to V11 series actually measured;
- descriptive completion, validity and compliance rates with their typed
  missingness.

Not permitted, and not currently claimed anywhere: a model winner, an
inferential ranking, a population or project generalization, a causal condition
effect, or any statement that a subject negotiated *well*. The last one is the
new restriction this profile adds, because the reference it would be measured
against is beatable by walking away.
