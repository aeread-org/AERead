# Data-center development QC profile

**Standard:** [AERead benchmark QC](../../operations/benchmark_qc.md)

**Campaign procedure:** [experiment campaign SOP](../../operations/experiment_campaign_sop.md)

**Design plan:** [development negotiation implementation plan](development_negotiation_implementation_plan.md)

**Status:** as of 2026-09-20, case-specific profile covering six registered family ids;
`profile_admission=passed`, while
`task_distribution_admission=partial`,
`environment_and_verifier_qc=partial`,
`construct_validity=partial`,
`attribution_and_controls=partial`,
`confirmatory_reliability=passed` for the
`datacenter_development_v2_world_panel_confirmatory_v1` and
`datacenter_development_v2_world_panel_interface3_confirmatory_v1` tracks and
`partial` for the family, and
`normative_datacenter_profile=partial`.

As audited on 2026-09-19 this profile read `task_distribution_admission=failed`,
`construct_validity=failed`, `confirmatory_reliability=not_run` and
`normative_datacenter_profile=failed`. The sections below keep that audit as
written and date every change of status, because the 30 bundles it audited
are still published and are still read against the reference it describes.

As audited, two gates were failed, and the construct failure was the most
important line in this profile. On
`cases/datacenter_development_v1/v2/full_stack_amendment_001.json`
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
**Held-out pack (2026-09-20).** `worlds_v2_holdout/`: the same generator from
master seed 20270920, a seed domain disjoint from `worlds_v2`, sharing no case
digest, knob signature or seed label with it. The pilot that tuned the schema
and prompt ran only on `worlds_v2`; every confirmatory runs on the holdout.
Still missing for `passed`: near-duplicate clustering across strata, and a
measured control rate per world from the frozen control rather than from the
scripted reference alone.

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
A second gap of the same class is open (DC-D-08): the schema allows a walk
that states its reason, the parser accepts only a bare walk, and 8 cells across
the pilot and the confirmatory were typed malformed for walking with a reason.
It is fixed in the next campaign identity, never under a frozen one.

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

**Joint venture, scope V3 (2026-09-21, PR #214).** The coalition primitive
adds a partner seat, a jointly proposed feeder agreement and a fourth and
fifth scored control. Its endpoint is the developer's coalition decision, and
that endpoint has a stated failure rule, because the probes showed a subject
whose every choice was payoff-maximising, including free-riding on a partner
that had announced it would cover the rest, and a rule that cannot call that
either right or wrong guards nothing (Gate 5, item 7).

*The rule.* The developer's objective is its own equity NPV. The partner's
announcement is cheap talk; its public record of earlier feeders (what it
announced, what it funded) is the only evidence. **Free-riding is the correct
answer exactly when the record is non-empty and every recorded feeder was
funded in full by the partner; otherwise the developer's capacity share is.**
Funding less than the evidence requires is `under_funded` (the coalition
fails and the developer pays the solo price, or it rode on cheap talk and
happened to be covered, which the rule counts the same); funding more is
`over_funded` (money left on the table); the reference funds the licensed
share and is `best_response` by construction, enforced in
`validate_payload`. The classification is written into every outcome's
`coalition` block as `record_best_response_share_bps` and
`coalition_decision`, implemented once in
`stack_environment.record_best_response_share_bps`. A consequence the reader
must accept: on the sincere generous case (003, no record) Gemini's four free
rides earned 18,000 each and are classified `under_funded`, because the
benchmark scores the decision against the evidence, not the outcome.

*The two synthetic arms the rule must reject.* `free_rider` offers nothing
whatever the record shows; `fair_share` offers the capacity share whatever
the record shows. On the six curated cases
(`datacenter_v3_jv_scored_controls_v1`, 30 trajectories) the rule classifies
the reference `best_response` 6 of 6, the free rider `under_funded` 4 of 6,
the fair share `over_funded` 2 of 6. On the generated pack
(`datacenter_v3_jv_world_controls_v1`, 24 worlds, 120 trajectories) the
reference is `best_response` 24 of 24, the free rider `under_funded` 13 of
24, the fair share `over_funded` 11 of 24. Both arms fail the rule somewhere
and the reference nowhere; a subject that always free-rides and one that
always pays its share both score below the reference on the pack.

*The generator.* `python -m aeread_families.datacenter_development.jv_worlds`
lays a sampled joint venture over each of the 24 sealed interface-3 worlds:
the partner's capacity is a sampled multiple of the developer's contracted
power (0.5x to 3x), the feeder's cost a sampled multiple of the solo
interconnection price (1.3x to 2.4x), the partner one of five types with a
sampled truthful record of 0 to 3 feeders, the joint offer one round or
three. Every draw goes through the construct guard, and the guard's admission
is measured across seeds rather than asserted: 24 of 47 draws admitted, 23
refused as inert (the developer's share would not beat the solo price by the
margin), an admission rate of 51%. The admitted pack has 7 pro-rata, 1
conditional, 7 generous, 3 bluffing and 6 posturing partners, 6 worlds with no
record, and 11 worlds where the record licenses a free ride. What the pack
does not yet vary: records that are mixed or stale, and partner types that
change conduct between feeders. Six curated cases are development
qualification; this pack is the first thing a JV panel could be frozen on.

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

**Status: passed for two confirmatory tracks** (`datacenter_development_v2_world_panel_confirmatory_v1`, `datacenter_development_v2_world_panel_interface3_confirmatory_v1`), `partial` for the family: one route, descriptive, and the Gate 1-4 blockers still stand.

**Design contract (2026-09-19).** `configs/datacenter_development_v2_world_panel_v1.json`
with `world_campaign.py`: the 24-world pack pinned by digest, one route
(Gemini 3.8 Flash via Google AI Studio, chosen to keep the pilot under $10),
two predeclared inference seeds, 48 cells, a $0.20 per-cell cap and a $10
ceiling, `claim_status` exploratory, the world as the resampling unit with
24 clusters, missingness reported separately, and every winner, ranking and
causal claim flag set to false. The provider-free and profile-admission
gates run on `main` without a key; the variance pilot is the next paid step.

**Variance pilot (2026-09-19).** `evidence/datacenter_development/datacenter_development_v2_world_panel_v1/`:
47 of 48 cells completed (1 timeout), $2.52 lower bound. Admitted 7 of 48; the
rest split into 23 output-format deaths (DC-D-07), 7 no-op amendments and 10
completed stacks the lender would not fund. Admitted cells sit at the scripted
reference (median −0.03 billion cents on ~50-billion references, 3 of 7 above
it), so the reference is beatable and the score sees it. Four of 24 worlds
completed on both seeds; where both did, the seed difference was 2.6 billion
cents median — for a live model, seeds are not repeats, but most of the
variance is admission, which is binary. What this fixes before a freeze: the
confirmatory runs under a new campaign identity with the bounded schema and
v2 prompt, and its sample is sized on 24 worlds, not 48 cells.

**Confirmatory freeze (2026-09-20).** `configs/datacenter_development_v2_world_panel_confirmatory_v1.json`
and its `.freeze.json`: 24 held-out worlds x 3 predeclared seeds x Gemini 3.8
Flash = 72 cells, bounded schema and v2 prompt, $0.20 per cell, $15 ceiling.
Hashed before any confirmatory outcome is inspected: the contract, the holdout
pack, the sealed design with every run-plan digest, the driver, the prompt.
Primary endpoint: admission rate over worlds with a world-clustered bootstrap
interval; secondary: mean delta from the scripted reference over admitted
cells; seeds averaged within the world; missingness ceiling 10% of planned
cells; no early stop; predeclared slice by stratum; no winner, ranking or
causal claim, one route. Gates 1-3 pass on the holdout without a key.

**Interface-3 pilot (2026-09-21).** `evidence/datacenter_development/datacenter_development_v2_world_panel_interface3_pilot_v1/`:
the same 24 worlds and two seeds as the first pilot, at developer interface 3
(`worlds_v3`). 48 of 48 cells completed, $3.36; 15 cells were re-executed as
recorded further attempts after a network outage turned the last seven worlds
into instant `transport` failures (DC-O-03, DC-T-08). The harness check holds:
**0 amendment-phase deaths** (the first pilot had 28 of 48). They did not
become admissions: 44 of 48 cells declined the amendment, 34 stacks completed
but were not funded, and in every one of them site control expired before
commercial operation — the model had the executed land (expiry 22-23, no
extension), the EPC completion month and the capacity schedule in view and
answered "no amendment required". Admitted 6 of 48 (first pilot 7), 5 of 24
worlds on any seed (7), 1 on both (4); 3 cells walked with a stated reason,
now valid walks; 4 exhausted the power rounds; 1 non-JSON. Read against the
first confirmatory's 0.42 ceiling: that bound counted stacks whose site control
covered COD, and the model declines the amendment that would have made it so.
The gap the first confirmatory hid was an interface gap; what the interface
now shows is a cross-agreement error, scored as `completed_but_unfinanced`.

**Second confirmatory (2026-09-21).** `evidence/datacenter_development/datacenter_development_v2_world_panel_interface3_confirmatory_v1/`,
frozen by `confirmatory.write_freeze` on a fresh held-out pack
(`worlds_v3_holdout`, master seed 20280920, developer interface 3) with the
first confirmatory's design, and analysed by `confirmatory.analyze` with the
analysis sealed in: 72 of 72 cells, 0 operational failures, $5.26 exact,
attended. The predeclared harness check passed — 0 amendment-phase
exclusions. **Admission over worlds 0.208, 95% world-clustered bootstrap
0.111-0.306**; 11 of 24 worlds on at least one seed, none on all three.
66 of 72 cells declined the amendment; site control expired before commercial
operation in 46 of the 49 unfunded stacks, 17 carried the 40 MW power counter,
10 a funding shortfall. Five walks stated a reason — four refusing a written
20-30% advance rate the lender's message had disavowed — and are valid walks.
Admitted cells sit 0.61 billion cents below the reference on average (95%
-1.44 to +0.06; 8 of 15 above it); 12 of the 15 were admitted after a
decline that happened to leave site control long enough. Read against the
first confirmatory (0.25, 0.15-0.35, another pack, interface 2): descriptive
only, as the freeze declares; the interface gap is closed and admission did
not rise, because the developer declines the amendment that would carry site
control through operation. What may be claimed: one route's descriptive
admission rate and reference gap on fresh held-out worlds, with no harness
exclusion left in the count.

**Confirmatory result (2026-09-20).** `evidence/datacenter_development/datacenter_development_v2_world_panel_confirmatory_v1/`,
with the predeclared analysis sealed in as `reports/confirmatory_analysis.json` (reproduced by `aeread_families.datacenter_development.confirmatory`, DC-T-07):
72 of 72 cells completed, no operational failure, $5.34 exact. **Admission rate
over worlds 0.25, 95% world-clustered bootstrap 0.15-0.35** (seeds averaged
within the world first); 14 of 24 worlds admitted on at least one seed, none on
all three. Admitted cells sit 2.2 billion cents below the scripted reference on
average (95% -2.9 to -1.5 billion; 3 of 18 above it). Excluded: 21 completed
stacks the lender would not fund, 16 no-op amendments, 12 walks with a stated
reason typed malformed (DC-D-08), 5 non-JSON outputs. Verbal/written divergence
admitted 0 of 12; revenue without bankability 1 of 12. Walk-away scores the
outside option on every world (`datacenter_v2_scored_controls_v1`); the
adopt-every-counter control also fails on every world, but at the amendment
phase on a refusal that carries no terms to copy (DC-D-09), so it does not yet
show that transcribing priced counters fails admission.
What the number may be read as: one route's descriptive admission rate and
reference gap on held-out worlds, biased down by the two harness gaps the next
identity closes; not a winner, a ranking, or a causal claim.

**As audited on 2026-09-19.** Before that pilot, no step of the live sequence
had been attempted: no declared variance pilot, no confirmatory freeze
artifact, no holdout table, and no `analysis_plan` anywhere in the 30 bundles
then published. The nearest artifacts were a `decision_rule` and
`primary_endpoint` in `terms_public_glm_transfer_v1/reports/summary.json`
(which returned `inconclusive_operational_missingness`) and a
`primary_contrast` in `terms_public_candidate_screen_v1`; the word frozen
appeared only as prose about a run configuration. The audit required that the
guarded metric be one walking away fails, because the outside option is a
legal terminal economic outcome and on the sealed V2 case beat the reference,
as procurement's terminal feasibility once counted a deferral as a success.
That is why the confirmatory's primary endpoint is admission — a completed
stack the lender funds — and why walk-away and adopt-every-counter run as
scored controls that fail it on every world. For scope V3 the coalition
endpoint carries its own falsifying arms (§3, joint venture): `free_rider`
fails the record rule on 13 of 24 generated worlds and `fair_share` on 11 of
24, so the endpoint rejects both a subject that always rides and one that
always pays.

**Main blocker (2026-09-20):** one route and no random or blind control rate
measured per world, so the confirmatory number is descriptive and compares
nothing; and the amendment phase has no decline (DC-D-10): 22 of 72 cells died
there after signing all four agreements — 16 no-op re-proposals and 6 walks
phrased as declines, the latter typed malformed (DC-D-08) — and 12 of the 22
pass every static cross-agreement check, so the measured 0.25 has an upper
bound of 0.42. The other 6 DC-D-08 walks are reasoned refusals at the loan
and score the outside option under either typing. Both gaps close in the next
campaign identity, never under this one.

## 6. Current implementation coverage

| Gate | Current coverage | Main blocker to `passed` |
|---|---|---|
| Profile admission | this document, as of 2026-09-20 | none |
| Task-distribution admission | 4 curated projects and the repaired `full_stack_amendment_002`, 15 counteroffer cases on one world, 6 authored terms packs, and two generated 24-world packs (`worlds_v2`, `worlds_v2_holdout`) refused at generation unless a naive strategy fails them, sealed by pack digest and split by seed domain | **Partial:** no near-duplicate clustering across strata; the control rate per world comes from the scripted reference, not from a measured control |
| Environment and verifier | deterministic ledger with sources-equals-uses and rollforward identities, leakage tests for all six ids, provider-free success goldens, typed missingness | **Partial:** replay copies a flag over 531 published rows instead of recomputing; no identities for `stack_cashflow.py`; five golden kinds missing on three ids |
| Construct validity and baselines | a scripted reference per case; the opt-in `construct_controls` guard (strict dominance by a declared margin, two-sided price bands); walk-away and adopt-every-counter as scored controls on the curated case and all 24 worlds (`datacenter_v2_scored_controls_v1`) | **Partial:** no random or adaptive policy; the guard covers `construct_controls` cases only, so the sealed `001` case and the 1.0.0/1.1.0 identities keep their dominated reference |
| Attribution and controls | claim status, digests and route snapshots on all 33 contracts; byte-identical paired conditions; typed missingness | **Partial:** one independent cluster in 19 of 30 bundles, five at most; 0 of 10 exposure-qualified pairs in one campaign |
| Confirmatory reliability | two frozen confirmatories on disjoint held-out packs (`…confirmatory_v1` under interface 2, `…interface3_confirmatory_v1` under interface 3): 72 of 72 cells each, predeclared endpoints, world-clustered bootstrap, analyses sealed into the bundles by `confirmatory.py` | **Passed for both tracks, partial for the family:** one route, descriptive, no random control rate per world; the second run carries no harness exclusion (0 amendment-phase deaths) and reads 0.208 (0.111-0.306) |

## 7. Registers

Tier 1 does not exist on main. `docs/operations/incident_log.md` indexes a
data-center register at `evidence/datacenter_failure_register.{json,md}` marked
*to be moved*; that path is absent from `main`, and the register in the standard
layout exists only on the unmerged branch `codex/datacenter-world-panel-v1`. The
index row is therefore stale in both directions and is corrected alongside this
profile. Tier 2 rows for the defects this audit found are in the data-center
section of the incident log.

## 8. Published campaigns

Thirty-three sealed bundles: 14 under `evidence/datacenter_development/` and
19 under `evidence/datacenter_development_terms/`, all digest-verified against
their manifests. The 30 audited on 2026-09-19 hold 531 rows in
`trajectories/sanitized.jsonl`; the two world-panel campaigns add 2,811 rows of
the kernel trajectory grain (878 in the pilot, 1,933 in the confirmatory) and
the scored-controls bundle carries tables only. The largest live bundle is the
confirmatory at 72 of 72 cells; the smallest is the two-cell probe of
2026-09-03. Recorded spend: under $0.11 across the 30 audited bundles, most
reporting a `lower_bound` because failed calls report no usage; $2.52 lower
bound for the pilot; $5.34 exact for the confirmatory.

One of them is confirmatory, none claims a winner, and only the three bundles
of 2026-09-20 — generated or run under the `construct_controls` guard with
scored controls beside them — may be described as measuring the family's
declared construct. The 30 earlier bundles may not, because the reference they
are read against is beatable by walking away.

## 9. What may be claimed today

Data-center results describe **whether a model can conduct a legal, internally
consistent multi-agreement negotiation and report grounded project terms, on one
to five clusters, as a diagnostic**. Specifically permitted:

- interface and instrument findings on a single world, labelled as such — the
  affordance contrast is the worked example;
- operational findings about routes, schemas and provider behavior, which is
  what the integrated V4 to V11 series actually measured;
- descriptive completion, validity and compliance rates with their typed
  missingness;
- on the held-out world packs, one route's descriptive admission rate and
  its gap from the scripted reference: 0.25 (95% world-clustered bootstrap
  0.15-0.35) under interface 2, biased down by the amendment phase's missing
  decline (DC-D-10), and 0.208 (0.111-0.306) under interface 3 on a fresh
  pack with no harness exclusion in the count; the two are not a before-after
  comparison.

Not permitted, and not currently claimed anywhere: a model winner, an
inferential ranking, a population or project generalization, a causal condition
effect, or any statement that a subject negotiated *well*. The last one stays:
on the 30 pre-guard bundles because their reference is beatable by walking
away, and on the world-panel campaigns because one route on a descriptive
endpoint says nothing about how it negotiated relative to any other.
