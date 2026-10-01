# Stratum splits: which carry signal, and what they cost

**Status:** audit of every stratum split published as of 2026-09-26, with the
verdict for future packs. The rule it motivates is in the
[campaign SOP](../operations/experiment_campaign_sop.md#strata-declare-only-the-splits-you-will-report).
Incident rows: EX-J-02 (stratified reading without a noise test), EX-D-08 (what
the test does not see).

Most packs declare more strata than they can support. Of 81 stratum splits in
the published evidence, 39 cannot be tested at all (one world per stratum, or
fewer than 5 independent worlds), and of the 42 that can, 12 differ at
p < 0.05 where chance alone gives 2.1; 8 survive
[Benjamini–Hochberg (1995)](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x)
false-discovery-rate adjustment at q = 0.10,
seven of them datacenter reasoning-arm or world-type splits. Meanwhile the
strata that multiply cost, the ones every world is re-run under, are mostly the
ones that show nothing. Future packs keep a stratum only when it will be
reported and is sized to be tested; everything else is coverage.

## 1. How a split was tested

For each split, the per-world paired difference between the two models (their
primary measure, matched seeds, the other strata averaged equally within the
world) is grouped by stratum, and the spread of the stratum means,
`sum over strata of n_s * (mean_s - grand mean)^2`, is compared with 2000
seeded shuffles of the stratum labels. A stratum that labels worlds (world
type, favourite listing, scenario) is shuffled across independent clusters, a
world and its twin moving together; a stratum every world is run under (arm,
seat, opponent, difficulty) is shuffled within each world. A split is not
testable when a stratum holds one independent world, or the split has fewer
than 5 clusters.
This permutation diagnostic follows the randomization logic of
[Fisher (1935)](../../references.bib) and respects AERead's declared world or
twin-cluster unit. World-type labels were not randomly assigned, so their
shuffle p-values are not exact design-based randomization p-values. Multiple
splits reuse the same worlds; the resulting p-values and Benjamini–Hochberg
q-values are exploratory screens, not a confirmatory false-discovery-rate
guarantee for these dependent tests.

The test is `tools/examiner/strata_noise.py` on `codex/examiner-case-cards`
(commit 17271955), the offline twin of the noise line the
[Examiner](https://aeread.org/examiner) prints under every split; the two
agree on 67 of 67 comparison splits. The part-by-part procurement split and the
pairwise contrasts in §3 were computed from the same gap reports with the same
test, in session; they are not yet a build step.

What the test reads: whether the gap a table compares **shifts on average**
from stratum to stratum. A stratum that moves both models' scores alike, or
moves the gap one way in some worlds and the other way in others, reads as
noise even when it matters world by world (EX-D-08; the Housing opponent in §3
is the example).

## 2. Cost lives in the strata that multiply cells

A stratum that labels worlds costs nothing: the pack has the worlds it has, and
the label only sorts them. It starts to cost when the split is reported, because
then each stratum needs enough worlds to be tested, 5 or more.

A stratum every world is run under multiplies the cells by its number of values:
the reasoning arm and the seat double a pack, three difficulties triple it, and a
crossed opponent adds a cell type per value. These are where the budget goes, and
§3 shows that apart from the datacenter reasoning arm none of them separates the
models. A factor that should be covered but will not be reported is *assigned*,
one value per world balanced across the pack, not crossed: the paired model
contrast survives, because both models still play the same world under the same
value, at 1x instead of kx.

## 3. Verdicts

| Family | Stratum | How it costs | Evidence (gap p; worlds per stratum) | Verdict |
|---|---|---|---|---|
| Datacenter risk allocation | reasoning arm | x2 (v1 x3) | v2 0.001 (q 0.031; Gemini ahead by 94.1 regret at low effort, 10.9 at default); v1 0.37; menu 0.18. The arm moves both models' level at p < 0.001 in all three | **keep, report** |
| Datacenter risk allocation and world panel | world type | labels worlds | one seat v1 0.014, v2 0.036; two-sided as client 0.010, as integrator 0.17; menu 0.003 (q 0.049); world-panel interfaces 2 and 3, 0.014 and 0.009; 2 to 5 worlds per type | **keep, report, size to 5 per type** |
| Datacenter risk allocation | seat (one seat vs scripted) | x2 | v1 0.92, v2 0.56; the seat moves the level (0.044, 0.014), not the gap | **stop splitting**; assign one seat per world unless the claim is per seat |
| Datacenter two-sided | opponent model | crossed 2x2 | as client 0.59, as integrator 0.20 | report pooled; keep the crossing, the same cells serve both seat views |
| Datacenter full terms | world type (9 to 11) | labels worlds | v2 0.99 on 58 worlds (4 or more per type); v1 one world per type | **coverage**; do not size up to 55 or more worlds |
| Datacenter full terms, menu | integrator's playbook | labels worlds | 0.11, 0.029 (q 0.12), 0.14; the playbooks' order differs between packs | hypothesis only; pre-register before reporting |
| Datacenter counteroffer probes | condition, stage | x2 on one world | one world: not testable | conditions on one world are treatments of a case study, not strata |
| Procurement repeated sourcing | world type (6 types x 2 worlds) | labels worlds | total gap dev2 0.46, holdout 0.61; the loyalty-and-retaliation part 0.018, 0.002 (below) | **six-way split is coverage**; report pooled, plus a two-way split on the relationship part |
| Procurement single order, curated relationship | world, world type | labels worlds | one world per stratum | **invalid as a split**; read as cases |
| Housing bid world | market difficulty (3) | x3 | 8-world tenant panels v23 0.028, v26 < 0.001 (q 0.021); landlords 0.84, 0.93; the 30-world confirmatory 0.27 tenants (mild against severe 0.61), 0.082 landlords, 0.56 to 0.92 on the utility measures | **not replicated**: one difficulty per world, after the D-27 estimand decision |
| Housing bid world | opponent model | crossed 2x2 | confirmatory 0.21 and 0.22; 8-world panels 0.12 to 0.94 | report pooled; keep the crossing (fixing it saves at most a quarter) |
| Housing sensitivity panels v10 to v24 | opponent, difficulty | x2, x3 | 1 to 4 worlds each: not testable | do not read their stratum rows |
| Housing lemons | favourite listing (2 x 12 worlds) | labels worlds | 0.41; admission makes a favourite's quality depend on its popularity (HL-D-03) | **drop the split** until quality-blind admission |
| Refund V2.1 | scenario (6 x 1 world) | labels worlds | one world per stratum (RF-D-01) | **invalid as a split**; the due outcome, 3 worlds each, 0.10 to 1.00, is coverage |

**Procurement, part by part.** The six repeated-sourcing world types are the
relationship extension itself: each is one tension built from the loyalty
discount, the retaliation markup and the incumbent's capacity
(`docs/families/procurement-allocation/relationship_design.md` §3 on
`codex/procurement-repeated-relationship`). Split into the gap report's parts,
Gemini minus GLM per world:

| Part | loyalty investment | retaliation trap | demand ramp | incumbent capacity | unreliable incumbent | qualification investment | noise p (dev2, holdout) |
|---|---:|---:|---:|---:|---:|---:|---|
| loyalty discounts and retaliation, dev2 | 23.9 | 28.1 | 27.7 | 5.8 | 4.2 | 0.0 | 0.018 |
| the same, holdout | 24.9 | 16.5 | 31.4 | 5.5 | 1.9 | 0.0 | 0.002 |
| periods lost to a rejected award, dev2 | 10.4 | 9.5 | 77.3 | 27.9 | 63.1 | 62.7 | 0.44 |
| the same, holdout | 31.8 | 0.0 | 33.1 | 18.6 | 9.6 | 31.5 | 1.00 |
| total gap, dev2 | 29.4 | 33.0 | 96.3 | 34.0 | 64.5 | 57.3 | 0.46 |
| the same, holdout | 49.3 | 12.5 | 56.4 | 23.1 | 13.6 | 44.5 | 0.65 |

The relationship part separates worlds whose stratum carries loyalty or
retaliation terms (Gemini ahead by 14 to 32 on each of those 12 worlds) from the
rest (p = 0.003 in both packs), and does not separate the three that carry them
(p = 0.82, 0.07). The total does not move because its largest part, GLM's
rejected awards, is unrelated to world type. The contrast is partly structural,
a world without loyalty terms has no loyalty part, so it shows the design
working, not the models reacting differently to different mechanisms. Six
strata carry one two-way distinction here.

**Housing, the opponent.** The opponent reads within noise on the confirmatory,
yet the estimand review (`docs/families/housing/estimand_review.md` on
`codex/housing-v13-cooldown-full-trajectory`, row D-27) finds
it explains 56.4% of within-case variance (p = 0.003). Both hold: per case the
opponent moves the within-case score by 0.08 on average, with the sign split 51
to 39 over the 90 cases, so the average shift is +0.034. The opponent matters to
each market and not to the pooled model contrast, where it enters both arms
equally.

**Housing, difficulty.** The within-case score is welfare scaled between doing
nothing (0) and the market's bound (1), so difficulty cannot move its level; it
moves raw welfare and both utilities at p < 0.001. D-27 reports that on tenant
surplus share the subject contrast rises with `common_weight` (+0.141, +0.296,
+0.867), a measure not in the published tables: if the family moves to that
estimand, test difficulty on it before assigning it.

## 4. What the trims save

| Pack | Today | After the verdicts |
|---|---|---|
| Datacenter one seat (v2 layout: 32 worlds in 24 clusters, 4 per type, 2 seats x 2 arms x 2 models x 2 seeds; $8.94, a floor) | world type not sized, seat split read | 5 clusters per type with one seat per world: about 0.63x the model cells (about $5.6) and a reportable world-type split; both seats crossed at 5 per type would be 1.25x (about $11.2) |
| Datacenter two-sided (24 clusters, 4 per type; $1.40) | world type not sized | 5 per type: 1.25x |
| Housing confirmatory (30 worlds x 3 difficulties x crossed opponents, 717 cells; $6.90) | difficulty crossed | one difficulty per world: about $2.30 for the same 30 worlds, or 90 worlds for $6.90 |
| Procurement repeated sourcing (12 worlds per pack) | six-way split read | unchanged cost; a reportable six-way split would need 30 worlds (2.5x) and the evidence does not justify it |
| Lemons, refund, full terms, single order | splits read | no cells saved; stop reading splits that cannot be tested |

Every change above alters a frozen control of a sealed pack, so it is a new
campaign identity, never an edit in place, and the family owner decides it.

## 5. Open

- Seat in the datacenter one-seat design: whether the claim covers both seats is
  a scope decision; the data say the seat does not change the model gap.
- Housing difficulty waits on the D-27 estimand decision.
- The Examiner's noise line on a gap breakdown tests the total only; a part can
  separate while the total does not (procurement above). A per-part test is not
  built.
- The housing lemons world draws on [Akerlof's quality-uncertainty problem
  (1970)](https://doi.org/10.2307/1879431). Its luck part is itself in question
  (HL-J-02): blind bets on listings no rival bid on were lemons 11 times in 15,
  against 6.2 expected. The adverse selection from better-informed rivals is
  related to the winner's curse discussed by
  [Milgrom and Weber (1982)](https://www.jstor.org/stable/1911865), but this
  diagnostic is not an auction result or a tested causal mechanism.
