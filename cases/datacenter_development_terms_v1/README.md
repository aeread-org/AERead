# Data-center development terms grounding

This family measures whether a model can reconstruct the controlling commercial
state of a data-center project from mixed verbal and written evidence. It is a
report-only classifier. It does not negotiate or execute agreements; the separate
[`datacenter_development_v1`](../datacenter_development_v1/) family measures those
interactive decisions and downstream cash-flow effects.

The `pilot/` split contains one fully authored synthetic project spanning land,
power, EPC, construction finance, and customer service terms. It is suitable for
provider and harness diagnostics, but it is not historical evidence and it does
not establish performance across independent projects. The private project
manifest lists seven additional source-required slots so design coverage cannot
be mistaken for sample size.

The `grounded_v1/` split adds four cases from a user-provided sanitized
calibration pack whose commercial relationships were verified before
sanitization. They cover quote normalization, execution cutoffs, site/power
reconciliation, and build economics. Their source lineages overlap, so all four
remain one conservative archive cluster and support descriptive case variance
only—not independent-project generalization.

The `public_v1/` split adds five cases mapped one-to-one to distinct SEC filing
clusters. It exercises ground-lease commencement, phased colocation financing
and ready-for-service, large-load utility gates, credit-facility availability,
and linked land/power/construction underwriting. The pack records accession,
document, URL, and clause locators but does not vendor source documents. Its
five-cluster comparison is exploratory and does not support a population or
model-winner claim.

The `public_mechanism_v1/` split decomposes the integrated Denton case into
assignment-consent, coterminous land-power, and adjustable-GMP mechanisms. Each
mechanism has a baseline and affirm-only wording variant with identical evidence,
hidden oracle, title, authority, cutoff, and world seed. All six cases remain one
filing cluster and diagnose case composition and label-selection semantics only.

The `public_affirm_only_v1/` split derives one treatment from each original
`public_v1/` case by appending the same frozen candidate-selection sentence. It
preserves the five independent filing clusters, evidence, hidden oracles, and
world seeds while using a neutral visible split identifier. Its campaign bridges
to the sealed original baselines instead of rerunning them.

Run the provider-free admission case from the repository root:

```bash
PYTHONPATH=src python -m aeread_families.datacenter_development_terms \
  --response tests/fixtures/datacenter_development_terms/strong.json \
  --run-root /tmp/datacenter-development-terms
```

The primary score is a deterministic, hard-gate-conditioned mean of agreement
state accuracy, amount accuracy, required-action recall, required-claim recall,
and evidence coverage. Forbidden claims/actions or attempted external actions
zero the primary score. No LLM judge is used.

The matched five-seed route-reliability campaign is frozen in
[`configs/datacenter_development_terms_reliability_v1.json`](../../configs/datacenter_development_terms_reliability_v1.json).
It runs ten cells with no retries or provider fallbacks and a $0.25 campaign
ceiling:

```bash
PYTHONPATH=src python -m aeread_families.datacenter_development_terms.campaign
```

Because every cell uses the same synthetic project, this campaign estimates
response and operational stability only. It cannot establish project-level
generalization or a model winner.

The separate grounded case-variance campaign is frozen in
[`configs/datacenter_development_terms_grounded_v1.json`](../../configs/datacenter_development_terms_grounded_v1.json).
It runs the four grounded cases across two exact open-source routes and three
paired inference seeds, with no retries, fallback, or response cache.

[`configs/datacenter_development_terms_grounded_glm_v1.json`](../../configs/datacenter_development_terms_grounded_glm_v1.json)
adds one GLM route over the same case hashes and seeds. Its sealed bridge permits
descriptive three-model rows without rerunning or mutating the completed
two-route campaign.

The public-source campaign is frozen in
[`configs/datacenter_development_terms_public_v1.json`](../../configs/datacenter_development_terms_public_v1.json).
It runs five filing clusters across the same two exact routes and three seeds,
preserving provider failures as missingness and reporting safety gates separately
from completion and component accuracy.

[`configs/datacenter_development_terms_public_gptoss_v1.json`](../../configs/datacenter_development_terms_public_gptoss_v1.json)
adds one pinned GPT-OSS 120B route over the same public case hashes and seeds.
Its sealed bridge provides descriptive three-model rows without changing or
rerunning the predecessor campaign. The add-on completed all 15 cells, but all
three integrated land/power/construction outputs failed deterministic hard gates;
operational reliability therefore does not imply commercial-state safety.

The paired mechanism campaign is frozen in
[`configs/datacenter_development_terms_public_mechanism_v1.json`](../../configs/datacenter_development_terms_public_mechanism_v1.json).
It runs six cases across three pinned routes and three inference seeds. Baseline
wording produced three adjustable-GMP hard-gate failures; the affirm-only wording
rescued all three complete pairs with no hard-gate regressions. One rate-limited
cell remains operational missingness.

The five-cluster replication is frozen in
[`configs/datacenter_development_terms_public_affirm_only_v1.json`](../../configs/datacenter_development_terms_public_affirm_only_v1.json).
It runs 45 new treatment cells and hash-bridges to 45 prior baseline cells. The
observed run retained four Mistral rate limits, yielded 41 reportable pairs, and
found four hard-gate rescues with no regressions. Effects remained model- and
case-dependent, so the result is exploratory rather than a universal prompt or
model claim.

The matched single-source composition diagnostic is frozen in
[`configs/datacenter_development_terms_public_composition_v1.json`](../../configs/datacenter_development_terms_public_composition_v1.json).
It reruns the integrated Denton baseline and affirm-only cases on the mechanism
campaign's exact seeds, routes, harness, and output budget, then hash-bridges the
three decomposed clauses. The observed run found six composition gaps, one
inverse component-only gap, one GPT-OSS wording rescue, and one Qwen wording
regression. Cross-granularity scores are deliberately not compared.

The held-out candidate-screen diagnostic is frozen in
[`configs/datacenter_development_terms_public_candidate_screen_v1.json`](../../configs/datacenter_development_terms_public_candidate_screen_v1.json).
It reruns baseline, affirm-only, and a general cross-clause screening instruction
on three fresh seeds. The predeclared Qwen contrast had no hard-gate rescues and
zero score change across three reportable pairs; Mistral had two hard-gate
regressions. Five GPT-OSS calls remain typed operational exclusions. This
negative result favors a typed two-stage classifier or model/data intervention
over another sentence-level prompt variant.

The GLM model-transfer add-on is frozen in
[`configs/datacenter_development_terms_public_glm_transfer_v1.json`](../../configs/datacenter_development_terms_public_glm_transfer_v1.json).
It holds the integrated baseline case, harness, budget, and candidate-screen
campaign seeds constant while changing only the model/provider route. One of
three GLM/DeepInfra cells completed and passed at 0.9667; two rate limits remain
exclusions. The frozen qualification decision is therefore inconclusive, even
though the one reportable four-model row is a positive transfer signal.

The three-project integrated sequence is frozen in
[`configs/datacenter_development_terms_public_integrated_v1.json`](../../configs/datacenter_development_terms_public_integrated_v1.json)
through
[`configs/datacenter_development_terms_public_integrated_v4.json`](../../configs/datacenter_development_terms_public_integrated_v4.json).
V1 exposed an incorrect service-agreement state label; V2 corrected it but did
not produce a complete route comparison; V3 produced nine complete pairs but
was invalidated when a schema-permitted duplicate label conflicted with the
evaluator. V4 aligned the schema with the evaluator using `uniqueItems`.
Qwen/Google completed all nine V4 cells without duplicates, while
Mistral/DeepInfra excluded all nine because its grammar compiler did not support
that keyword. V4 therefore records a provider-capability finding and descriptive
Qwen case behavior, not a model comparison.

[`configs/datacenter_development_terms_public_integrated_v5.json`](../../configs/datacenter_development_terms_public_integrated_v5.json)
re-encodes candidate selection as complete boolean indicator maps and normalizes
selected labels before deterministic scoring. All 18 cells completed and all
nine pairs are reportable. Qwen passed 9/9 hard gates and Mistral 3/9, but the
contrast changes sign on Horizon and all six model-by-project groups repeat
exactly across seeds. The result is a stable three-project diagnostic, not an
inferential ranking or winner.

The `public_integrated_expansion_v1/` pack adds three independent public filing
clusters: Galaxy Helios, TeraWulf Lake Mariner, and Bitdeer Tydal. It extends
coverage to phased power and loan draws, lease commencement and prepaid rent,
and an executed open-book cost-plus construction agreement. The derived
`public_integrated_expansion_v2/` pack preserves every observation and oracle
while applying the complete indicator-map output contract.

[`configs/datacenter_development_terms_public_integrated_v6.json`](../../configs/datacenter_development_terms_public_integrated_v6.json)
runs those three new clusters once on each V5 route. Four of six cells completed
and passed their hard gates; two Mistral rate limits remain operational
missingness. Only Helios forms a valid reportable pair, with a descriptive
Qwen-minus-Mistral score difference of +0.0333. Qwen scored 1.0 on Lake Mariner.
The raw Tydal score is invalidated because its visible observation omitted the
oracle's invoice-payment-day value; a corrected successor is required before
interpreting that case. These results do not support a route comparison, model
winner, or project-population claim.

The derived `public_integrated_expansion_v3/` pack restores the Tydal
invoice-payment day to visible evidence and maps every numeric oracle field in
all three projects to an observation ID. The correction preserves the source
clusters, oracles, controlled vocabulary, and world seeds while changing the
pack and case identities.

[`configs/datacenter_development_terms_public_integrated_v7.json`](../../configs/datacenter_development_terms_public_integrated_v7.json)
is a fresh full-panel replacement over that corrected pack, not a selective
retry. Four of six cells completed and replayed at 1.0 with every hard gate
passed. Qwen completed all three projects; Mistral completed Helios while its
Lake Mariner and Tydal calls remained typed DeepInfra rate-limit exclusions.
The sole reportable Helios pair tied at 1.0. Tydal's completed Qwen output
correctly recovered the now-visible 22nd-day invoice term. A Parasail
qualification was rejected before inference at zero reported cost and was not
substituted. V7 therefore verifies answerability and records provider
missingness, but does not support a model winner or project-population claim.

[`configs/datacenter_development_terms_public_integrated_v8.json`](../../configs/datacenter_development_terms_public_integrated_v8.json)
adds deterministic per-provider queues and a predeclared 30-second DeepInfra
cooldown while retaining cross-provider parallelism. All six cells completed,
replayed, and passed hard gates at an exact cost of $0.00385881705. DeepInfra
improved descriptively from 1/3 V7 completions to 3/3, but the fresh seed and
later execution time preclude a causal pacing claim. Helios and Tydal are valid
1.0 ties. Lake Mariner's raw 0.9444 Mistral score and +0.0556 Qwen delta are not
interpretable because four currency fields did not specify whether values were
expected in millions or base dollars. The separate 250-versus-visible-750 MW
error is unambiguous. A unit-explicit full-panel successor is required before
interpreting the Lake score.

The derived `public_integrated_expansion_v4/` pack preserves all V3 evidence,
oracles, vocabularies, and world seeds while appending an explicit rule that
monetary amounts use base currency units and other numeric fields use their
key-named units.

[`configs/datacenter_development_terms_public_integrated_v9.json`](../../configs/datacenter_development_terms_public_integrated_v9.json)
runs a fresh full panel on V4 with the same 30-second DeepInfra pacing. Both
Lake routes returned the base-dollar values and visible 750 MW limit, scored
1.0, and form a valid tie; Helios also ties at 1.0. Five of six cells completed
and replayed, while Mistral's Tydal call remained a typed rate-limit exclusion.
Successful-call cost is a $0.0034725438 lower bound. V9 verifies the unit repair
but shows that 30-second pacing is not fully reliable across runs; no winner,
population, or causal pacing claim is supported.

[`configs/datacenter_development_terms_public_integrated_v10.json`](../../configs/datacenter_development_terms_public_integrated_v10.json)
holds V4 and both routes fixed while increasing the DeepInfra cooldown to 60
seconds on a fresh full panel. It again completed 5/6 cells and 2/3 DeepInfra
calls, so the extra minute of wall time produced no completion gain over V9's
30-second setting. Helios tied at 1.0. Lake's currencies remained correctly in
base units, while Mistral read the visible 750 MW limit as 250, yielding a valid
0.9889 score and +0.0111 Qwen delta. Tydal remained operationally missing on
Mistral. Across these descriptive runs, 30 seconds is the better observed
speed/reliability balance, not a causal or universal optimum.

[`configs/datacenter_development_terms_public_integrated_v11.json`](../../configs/datacenter_development_terms_public_integrated_v11.json)
returns to 30-second pacing but reverses only the DeepInfra case order to Tydal,
Lake Mariner, then Helios. Tydal completed first at 1.0, Lake rate-limited
second, and Helios completed third at 1.0; Qwen completed all three. Thus the
failure is neither Tydal-specific nor a deterministic third-call quota and is
best classified as intermittent provider availability. Five of six cells and
two perfect tied pairs were reportable at a $0.00347697405 successful-call
lower bound. No causal order, model-winner, or population claim is supported.
