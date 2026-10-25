# Refund V3.4 developmental evidence

This is a sanitized, digest-bound **amended sequential developmental/exploratory**
publication, not a formal QC admission or a confirmatory model ranking.
Five profiles each cover the same 220 cases / 110 counterfactual pairs:
Policy 82, Intake 56, Payments 26, Customer 56. One LLM seat is active per
episode; the other three seats are scripted. World 610001, execution 0,
repetition 0. These cases have been exposed during development, not held out.

| Profile | Strict pass | Strict failure | Strict unknown |
|---|---:|---:|---:|
| Gemini 2.5 Flash Lite | 23 | 197 | 0 |
| Gemini 2.5 Pro, requested low | 192 | 28 | 0 |
| GPT-6-Sol, requested none | 160 | 60 | 0 |
| GPT-6-Sol, requested low | 194 | 26 | 0 |
| GPT-6-Sol, requested medium | 202 | 18 | 0 |

Rows identify profiles, not a ranking. Lite actions were collected in
V3.3 and replayed/rescored under V3.4. The new Pro panel consists of 187 retained
parent outcomes and 33 authorized continuation outcomes, including one explicit
retry of an unscored frontier. Old Pro results are separately retained in
[historical_original660.jsonl](tables/historical_original660.jsonl); they are
not silently replaced in historical denominators. Parent frontier receipts
and answers remain in the private local source store, not this projection.

## Reproduce without a provider

From the repository root, with Python 3.10+ and the normal project dependencies:

```sh
python research/refund_v34/reproduce.py
python -m pytest -q --noconftest research/refund_v34/test_publication.py
```

The verifier checks manifest digests, every listed and unlisted file, runtime
pins and prohibited public text, then reconstructs native observations from
case definitions and replays **all four seats' parsed actions**. It compares
all 1,100 final-state hashes and all eleven native score leaves, strict scores,
seat-scoped taxonomy, pair coverage and recomputed summaries. Network connections
are blocked. This is not a regeneration of model answers or original receipt seals.
The source snapshot and [reproduction guide](../../../research/refund_v34/README.md)
are part of the repository, outside this evidence directory and hash-bound by
[runtime_bindings.json](qc/runtime_bindings.json).

## Public grains and provenance

- [episodes.jsonl](trajectories/episodes.jsonl): one selected episode per profile/case, 1,100 total.
- [sanitized.jsonl](trajectories/sanitized.jsonl): canonical kernel per-action projections,
  including typed illegal actions, legality, outcomes and usage; no observations
  or full provider response envelopes (structured action text fields remain).
- [tables](tables/): run/task/call/result grains and the case panel; profiles are explicit.
- [receipt projections](receipts/projections.jsonl): source receipt and seal digests,
  not complete receipts or proof that private originals can be re-sealed publicly.
- [summary.json](reports/summary.json): per-seat counts, all eleven leaves' validity
  denominators, overlapping failure dimensions and matched descriptive GPT comparisons.
- [中文报告](reports/REPORT_zh.md), [QC and limitations](qc/STATUS.md),
  [local public-verifier output](qc/PUBLIC_VERIFICATION.md),
  [source artifact hashes](qc/source_bindings.json), [stage records](qc/stages.json).

Source hashes bind the retained local input artifacts. The raw sealed event stores,
prompts, observations, model answers and model reasoning text are deliberately
not public. Independent public checks reproduce native state/score from typed
actions; wire identity, raw envelope transformation and billing authenticity
remain source-audit claims rather than independently verifiable public facts.

Historical rows without a saved native-state digest are explicitly marked
`publication_native_recomputation`: these new replay digests are not represented
as fields already present in the original experiment record.

The envelope protocol only accepts bare JSON or one standalone complete JSON
fence, with no schema/value repair. Prior checks found Lite's 485 and GPT none's
642 retained replies byte-identical under this normalization. Historical raw
text is not included here, so that byte-equivalence claim is not independently
recheckable from this public projection alone.

No new paid calls were made to package this bundle. Stage/time differences,
single executions, development exposure and the Pro retry prevent isolated
causal reasoning-effect claims or population-wide superiority conclusions.
Requested reasoning levels do not independently establish Arena internal execution.
Missing reasoning-token data and historical unknown billing are not imputed.

Related [issue #309](https://github.com/aeread-org/AERead/issues/309) concerns
specific V2.5 paper artifacts and conformance counts; this different V3.4
publication does **not** resolve or replace those missing historical records.
