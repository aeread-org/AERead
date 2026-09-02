# Experiment campaign SOP

**Status:** implemented control surface and standard operating procedure.

Use this sequence for harness, model, opponent, prompt-policy, reasoning, or
budget experiments. A campaign varies one primary scientific factor. Everything
else is a control, a predeclared robustness arm, or a diagnostic; it must not be
silently tuned while the campaign is running.

Every campaign must consume passed evidence from the shared
[benchmark quality-control standard](benchmark_qc.md) and its case-specific QC
profile. Benchmark QC validates the measurement instrument; this SOP validates
one experiment conducted with it.

The machine-checkable gate contract is in
`aeread.shared_runner.campaign`. It preserves failed attempts, permits an
evidence-backed retry of the same gate, and refuses to append a downstream gate
until the latest attempt at every predecessor has passed.

## 1. Declare the question and the frozen controls

Choose one focal factor and one estimand before execution:

| Campaign | Focal factor | Controls that must remain fixed |
|---|---|---|
| Harness | harness implementation/version | model route/revision, opponent profiles, prompt and schemas, tools, reasoning/sampling, budgets, retries, cases, seeds, scorer |
| Subject model | subject model profile | harness, opponent panel, role prompt, tools, budgets, retries, cases, seeds, scorer |
| Opponent | opponent profile or policy | subject profile, harness, background seats, cases, seeds, scorer |
| Prompt policy | versioned prompt/policy | model route, harness, tools, budgets, retries, cases, seeds, scorer |
| Reasoning or budget | one named reasoning/budget level | model route, harness, prompt, opponent, other budgets, cases, seeds, scorer |

Provider route differences that cannot be removed belong in the resolved
profile and narrow the claim to the complete model-plus-route treatment. They
must not be described as a pure model effect.

Classify every knob in the campaign contract:

- **treatment:** the one primary factor whose effect is being estimated;
- **control:** sealed and equal across paired cells;
- **robustness arm:** a separately declared secondary campaign or family of
  contrasts, not an unplanned addition to the confirmatory panel; or
- **diagnostic:** recorded for interpretation, never used to pick the winner or
  retune a completed confirmatory campaign.

## 2. Run the mandatory gates in order

| Order | Gate ID | Exit evidence |
|---:|---|---|
| 1 | `design_contract` | question, estimand, focal factor, controls, cases, pairing, missingness, stopping rule, and analysis plan are versioned; structural design audit passes |
| 2 | `provider_free_validation` | schema, scripted execution, scoring, sealing, and offline replay pass with no paid calls |
| 3 | `profile_admission` | every model-harness-tool combination is admitted and its resolved profile and route expectations are sealed |
| 4 | `full_trajectory` | one complete trajectory per condition verifies routing, parsing, tools, retry visibility, scoring, replay, and billing evidence |
| 5 | `variance_pilot` | the full paired design completes on a predeclared development panel; world-level variance and operational missingness are measured |
| 6 | `confirmatory_freeze` | cases/holdout, sample size, profiles, seeds, execution order, analysis, stopping rule, and implementation pins are hashed before confirmatory outcomes are inspected |
| 7 | `confirmatory_execution` | every planned cell has a verified receipt or typed missingness; no selective reruns or post-freeze configuration edits occurred |
| 8 | `publication` | fact tables and manifest verify, aggregates trace to admitted rows, uncertainty uses the declared cluster, and exploratory/confirmatory claims are labeled |

Do not infer a winner from the full-trajectory gate or variance pilot. Their job
is to expose integration failures and size the confirmatory run from the
predeclared minimum meaningful effect and paired cluster-level variance.

## 3. Enforce promotion in campaign drivers

Before starting a stage, ask for a promotion decision. After the stage, append
an evidence-backed pass or failure record:

```python
from aeread.shared_runner import (
    CampaignGateRecord,
    append_campaign_gate,
    campaign_promotion_decision,
)

decision = campaign_promotion_decision(
    campaign_id, "full_trajectory", gate_history
)
if not decision.eligible:
    raise RuntimeError(decision.blockers)

gate_history = append_campaign_gate(
    gate_history,
    CampaignGateRecord(
        campaign_id=campaign_id,
        gate_id="full_trajectory",
        attempt_index=decision.next_attempt_index,
        status="passed",
        evidence_refs=("runs/gate/run_plan.json", "runs/gate/receipt.json"),
    ),
)
```

A failed record remains part of the audit trail. The same gate can be attempted
again with the next contiguous `attempt_index`; downstream promotion stays
blocked until that retry passes. A generic episode API cannot infer which
scientific campaign it belongs to, so the campaign driver is responsible for
calling this boundary before launching paid work.

The Housing V0 reference implementation is
`aeread.shared_runner.housing_population_campaign`, with its frozen contract in
`configs/housing_population_crossplay_v0.json`. New case families should reuse
the same gate-history boundary and sealed-row resume behavior while supplying
their own case admission, goldens, baselines, attribution blocks, and profile
probes.

### Backend escalation instruction

Estimate paid cost and serial wall time from sealed full-trajectory billing
before launching a variance pilot. If the projection exceeds the campaign cost
ceiling or its declared operational-time limit, stop before the pilot. An Arena
API or other batch service may then be evaluated as a new execution backend,
but it must not replace the direct backend inside an active campaign.

Create a new campaign identity and re-run design, provider-free validation,
profile admission, and full-trajectory gates. Pin the Arena API version, model
and provider routes, concurrency, ordering, retry ownership, usage and billing
fields, and raw-response retention. The service must execute the same AERead
cases and produce AERead-verifiable receipts; an external arena score is not a
substitute for the Housing scorer or canonical fact tables.

## 4. Publish canonical fact-table projections

The benchmark export writes four reportable artifacts in addition to the
run/task/call and trajectory tables:

| Artifact | Grain | Meaning |
|---|---|---|
| `profiles.csv` | one sealed agent profile | complete model, harness, prompt, runtime, tools, memory, reasoning, sampling, budget, retry, and admission configuration |
| `model_features.csv` | one feature assertion per profile | long-form admission-derived capability facts with stable fact IDs and source provenance |
| `benchmark_results.csv` | one typed metric per receipt attempt | primary, component, reference, utility, capture, or invalid-status facts with inclusion and validity status |
| `fact_manifest.json` | one export | run-plan binding, row counts, per-table SHA-256 digests, and a digest of the manifest core |

Generate them with the normal export command:

```bash
aeread export-tables \
  --plan runs/<run_id>/run_plan.json \
  --receipts runs/<run_id>/receipts/ \
  --evidence-root runs/<run_id>/ \
  --output-dir analysis/<run_id>/
```

The tables are canonical, deterministic **projections**, not competing sources
of truth. `RunPlan`, `EvaluationReceipt`, and sealed event/artifact evidence
remain authoritative. The manifest makes a published projection immutable and
auditable.

### Evidence classes

Use these labels consistently in reports and future fact-table extensions:

1. **declared:** a versioned configuration or provider declaration;
2. **admission-derived:** a deterministic conclusion from declared harness
   requirements, provider capabilities, and the sealed profile;
3. **live-observed:** behavior captured in provider-call or tool-call evidence;
4. **receipt-verified:** a typed score or validity result in a verified receipt;
5. **analysis-derived:** an aggregate or interval computed from admitted facts
   under the sealed analysis plan.

The current `model_features.csv` is deliberately `admission_derived`. Feature
names such as `tool_calls_observed` describe whether the admission contract can
provide that evidence; the row does not claim that a particular live call used
a tool. Use `model_calls.csv`, trajectories, and receipts for observed behavior.

### Reuse and reporting rules

- Join and compare facts by typed IDs and digests, never by a display model name.
- A model-feature `fact_id` identifies the admission assertion; repeated run
  rows retain their `run_id` and source plan digest as provenance occurrences.
- Keep every verified receipt attempt. Filter leaderboard inputs to
  `reportable=true`, then apply the sealed analysis plan and cluster structure.
- Do not treat per-call, per-turn, per-seat, or per-metric rows as independent
  samples when the sampled unit is a world or case cluster.
- Report fact-table coverage, exclusions, invalid measurements, missing cells,
  and telemetry completeness alongside aggregate outcomes.
- Never overwrite a different fact export in place. Create a new run or output
  directory when its sealed inputs change.

## 5. Standard stopping and change policy

Stop promotion when a route drifts, hidden retries appear, replay fails, cost is
incomplete, a score is invalid, paired worlds are selectively missing, or a
control differs across treatment cells. Preserve the failure as evidence.

Before `confirmatory_freeze`, a design change starts a new gate attempt and must
be documented. After the freeze, any change to treatment, controls, cases,
sample size, seeds, stopping, or analysis starts a new campaign identity. A
purely mechanical correction may be published only when both the original and
corrected artifacts remain traceable and the scientific contract is unchanged.
