# Procurement panel preflight

**Entry point:** Approval to repair the readiness gaps before scaling procurement.
**Proposed action:** Validate locally, then select and authorize a live comparison and
budget. Do not equate an offline rehearsal with a model-performance result.
**Measurement and batch implementation:** `261a15c`, isolated branch
`codex/procurement-rfq-v1`. The fresh-live-seed guard is a follow-up at `b838ef1`;
it does not change the recorded offline cases, measurements, or shared batch code.

## Step 1: Sources and scope

The earlier [readiness audit](procurement_statistical_readiness.md) compared the one-world
Gemini smoke with Housing's 100-world, two-condition, three-repeat design. The corrected
RFQ bound, coupled-world generator, and shared-runner integration are now implemented.

The generator varies demand, prices, deadline slack, budget, vendor IDs, and directory
order while retaining split capacity, late/off-list alternatives, and incompatible MOQ
constraints. It constructs feasibility without rerolling or filtering seeds by outcomes.
It remains synthetic electronics procurement with a fixed supplier policy; it does not
establish coverage of real vendor discovery, evidence fraud, financing, or human approval.

### DANGER ZONE D1: synthetic feasibility is a restricted population

**HIGH — biases toward narrower and potentially easier worlds.** Feasible packages and
approval logic are constructed, not sampled from actual B2B purchasing histories. The
population claim is limited to this versioned generator.

## Step 2: Assumptions and controls

- The 100-world and three-repeat choices preserve Housing's convention. They are planning
  choices, not an independently estimated procurement sample-size requirement.
- Two offline labels use the same deterministic buyer. Their expected difference is zero
  by construction; this validates pairing and accounting, not equivalence of model policies.
- The primary live endpoint is the paired difference in normalized buyer surplus, with
  native money retained in each receipt. The live condition choices remain unapproved.
- A study manifest freezes the world panel, ordered comparison, inference seed base,
  analysis settings, source digest, and total recorded-spend limit before execution.

### DANGER ZONE D2: zero rehearsal difference is tautological

**CRITICAL — would bias toward false capability claims if treated as model evidence.**
The two offline arms intentionally share a policy. A zero-width interval is expected and
contains no information about Gemini's variance, effect size, or live reliability.

## Step 3: Measurement and execution chain

The native family maps to verifier `objective_reference`, class `deterministic`, reference
kind `objective_upper_bound`. The reference jointly optimizes purchase and contact spend
under the controlled supplier floor, approved vendors, deadline, MOQ, capacity, and contact
limit, retaining no trade. The bound regression catches a previously valid payoff of 943
exceeding the old reference of 939. The repaired reference is 943.

The family uses the same `execute_plan_cell` scheduler/provider path as Housing. Both now
share `family_evaluation.py` for typed receipt finalization and deterministic state-and-score
replay, and `paired_analysis.py` for world-cluster inference. Procurement's batch controller
is family-neutral; it does not call a separate procurement-only episode runner.

Batch invariants tested include:

- Matched real world/case hashes and inference seeds across conditions; repeats nested in
  worlds rather than counted as independent worlds.
- Replay-verified receipts, atomic result publication, exclusive batch lock, no-call resume,
  and result/manifest tamper rejection.
- Receipt-only crash recovery without another model call. An attempt lacking a verifiable
  receipt stops for manual recovery; it is never silently rerun.
- Typed operational exclusion without a fabricated zero payoff; legal economic losses
  remain valid measurements.
- A global recorded-cost stop and per-condition failure circuit; unknown billing stops
  further calls. Google calls and `usageMetadata.thoughtsTokenCount` are counted natively.
- Exact declared-panel coverage before complete analysis, plus case-specific missingness
  support that can extend below zero.

### DANGER ZONE D3: recorded cost is not a hard billing ceiling

**HIGH — can understate final spend.** Provider calls are billed before their usage is
known. One in-flight episode can cross the stop threshold. Unknown timeout billing remains
explicit and halts new calls; provider-side controls are needed for a strict hard cap.

## Step 4: Validation results

The targeted procurement, shared-receipt, batch, analysis, and Housing regression set passed
109 tests. The full offline suite at `261a15c` passed 672 tests, with 3 skipped and 1
expected failure, in 420.48 seconds. After the final seed-guard follow-up at `b838ef1`,
the full suite passed **674 tests, with 3 skipped and 1 expected failure**, in 377.52 seconds.

The provider-free rehearsal completed **600/600 included episodes**, with **100/100
complete world clusters**, no operational exclusions, no unknown billing, and **zero
external provider calls or API spend**. Both scripted conditions had mean normalized buyer
surplus 0.9051533128; the observed per-episode range was [0.8616819202, 0.9342829988].
The paired difference, cluster-bootstrap interval, paired-t interval, and missingness
interval were all zero, as expected for identical deterministic policies.

The independent cross-check passed **36 numerical/design checks**, verified all **600
receipt hashes and economic scores**, and checked all **2,400 buyer requests** without
finding supplier-private `unit_cost` fields. Run it with:

```bash
PYTHONPATH=src python examples/verify_procurement_preflight.py \
  --evidence-root /private/tmp/aeread-procurement-offline600.Ro87cp
```

The full durable bundle is at `/private/tmp/aeread-procurement-offline600.Ro87cp/offline`.
Its `summary.json` SHA-256 is
`ab7fa48de11e9cff0d808f3f2b88fa20c12daa772bf1d97f76023f0bd392e3ee`.
The shared plans are `runplan_ae93440b25e0dd31` and `runplan_7ce123a4d00859b6`.

A full no-call resume rebuilt the sealed plans and replayed all **600 included cells**
using provider clients that reject every call. It made **zero provider calls**, returned
identical rows, and left all **1,200 result/event files unchanged**. This used the shared
batch API directly against the recorded plans; the study wrapper correctly treats its
later seed-guard source change as a new study implementation.

The compact [evidence report](../experiment_results/procurement_offline_preflight_2026-08-27.json)
records counts, analysis, code versions, plan IDs, evidence hashes, and the resume fingerprint.

Rehearsal command (provider-free):

```bash
PYTHONPATH=src python -m aeread.shared_runner.procurement_experiment \
  --mode offline --world-count 100 --replicates 3 \
  --output /private/tmp/aeread-procurement-offline600.Ro87cp
```

### DANGER ZONE D4: sample size depends on complete worlds

**HIGH — can overstate precision after selective operational failure.** Housing's 600
episodes yielded only 83 complete world clusters. A 90-complete-world planning target is
retained for visibility, not automatically achieved by starting 600 episodes. The original
effect/retention sensitivity remains in the readiness audit. Do not top up based on
statistical significance.

## Load-bearing assumptions

1. The frozen synthetic grammar represents the procurement decisions the intended claim covers.
2. Controlled-supplier references and negative-outcome support remain valid on every world.
3. The selected live contrast, effect/precision target, and complete-world retention support
   the chosen sample size.

## Remaining live gate

No paid calls were made during this repair/preflight work. The earlier single low-thinking
Gemini smoke is not reused as admission for the new generated population or repaired code.

Before a paid panel: choose the comparison, total budget, and an explicit fresh master seed,
then run three disjoint worlds
in each selected condition. All six admission cells must have replayed included receipts,
native Google calls, correct model/thinking/seed identities, no scripted-provider evidence,
and known billing. Only then can `--mode sample` proceed. The total budget includes admission.
The live entry point rejects the default rehearsal master seed `20260827` and any panel
overlap with its 100 inspected worlds or an offline study saved in the same output root.
Other externally inspected diagnostic seeds must also be excluded when sealing a study.

For two live conditions, Housing's convention means 600 sample episodes plus six admission
episodes. A single Gemini condition versus the deterministic reference instead needs 300
paid sample episodes; that is a different comparison and is not selected by this paired-live
entry point. Neither design is authorized by the offline rehearsal.

**Honest conclusion:** The machinery can be tested without spending API quota. Scientific
readiness still depends on a chosen live comparison, successful admission, and adequate
independent-world retention—not the number 600 by itself.
