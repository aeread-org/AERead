# Walkthrough: receipt-preserving procurement continuation

Date: 2026-08-28. Entry point: the Parasail upstream shared pool returned HTTP 429.
Proposed action: acknowledge the drained rate-limit circuit once in a separate
continuation directory, retaining all previous attempts and charges, and dispatch
at most four new cells per invocation. Pause again on any new rate-limit error.

## Step 1: Evidence

The original temperature-1 study at
`/private/tmp/aeread-procurement-deepseek600-sampling.VjLskP` stopped at 69 of 600
sample attempts. There are 61 included episodes and eight rate-limit exclusions;
531 cells remain unattempted. All calls have drained, and billing is known.
The six admission receipts and 69 sample receipts replayed successfully. All
225 checked result/receipt/event files remained unchanged during the audit.

The sample cost is $0.2099360142. Its admission cost is $0.0179870922, and the
three earlier admission studies cost $0.097329276. Total spend is therefore
$0.3252523824, leaving $4.6747476176 of the original $5 authorization.

The failure metadata identifies an upstream shared-pool limit, not invalid
procurement actions or a verifier failure. The longer available evidence includes
successful calls before the burst and the earlier Housing run's operational
exclusions. Neither establishes that a particular request rate is always safe.
No economic outcome has been used to choose the continuation policy.

### DANGER ZONE D1

HIGH — eight failures in a time-correlated burst are not independent observations
of a stable error rate. Extrapolating them would bias reliability estimates in an
unknown direction. The new invocation cap is not a calibrated optimum.

## Step 2: Assumptions and provenance

- Data-derived: remaining cells are `600 - 69 = 531`; remaining budget is
  `5 - 0.097329276 - 0.0179870922 - 0.2099360142 = 4.6747476176`.
- Analyst judgment: four new cells per invocation may reduce request bursts.
  Shared upstream capacity could still limit requests at lower concurrency.
- Frozen defaults: the model/revision/route, temperature 1, top-p 1, all seeds,
  prompts, supplier policy, verifier, per-call ceilings and dollar limits are unchanged.
- Safety assumption: an explicit checkpoint can acknowledge past infrastructure
  failures without erasing them or changing the experiment's measurement inputs.

### DANGER ZONE D2

HIGH — lower concurrency may not resolve a globally shared provider limit; bias
direction is unknown. A new rate limit pauses the continuation after its bounded
wave drains. Unknown billing and new failure circuits continue to stop execution.

## Step 3: Exact recovery model

`prepare_rate_limit_recovery` is an explicit, one-time operation, not an automatic
retry. It requires an unlocked source, a verified manifest hash, unchanged plan
hashes, a contiguous sealed result prefix, an open circuit caused only by rate
limits, known billing and budget headroom. Other failure types cannot be acknowledged.

The source receives only a single-child pointer; its existing evidence is not
rewritten. A fresh destination retains every old result, receipt and event file.
The checkpoint binds the prefix's result hashes and the original policy manifest.
Existing outcomes remain exclusions or included measurements exactly as recorded.
Cost accounting still sums the entire prefix, including failed episodes.

Only the circuit state before that exact prefix is acknowledged. New failures
still accumulate and latch; a recovery directory cannot create another recovery.
The child has a sealed four-new-cell cap, and any new rate limit causes a pause.
Normal calls to the shared runner cannot raise that cap. Destination collisions,
symlinks, tampered checkpoints and duplicate child destinations are refused.

### DANGER ZONE D3

CRITICAL — losing old failures or counting copied evidence as fresh API work
would bias performance upward and misstate cost. Every old result hash and every
charge must survive exactly once. Never top up excluded cells or reset the $5 ledger.

## Step 4: Sensitivity and decomposition

The existing conservative reservation is $0.40 per in-flight episode. Varying
the proposed four-cell cap by plus/minus 50% gives:

| New-cell cap | Maximum reservation |
| ---: | ---: |
| 2 | $0.80 |
| 4 | $1.60 |
| 6 | $2.40 |

All are below the current remaining allowance, but only four is permitted by the
new checkpoint. This arithmetic verifies budget headroom, not a throughput or
reliability forecast. The per-episode price/context assumptions remain those in
the [sampling walkthrough](procurement_sampling_admission.md).

### DANGER ZONE D4

HIGH — collection now has an operational policy change after a provider outage.
Missingness may differ by condition and timing, so the bias direction is unknown.
Report the intervention, all exclusions, complete-world counts and exact-support
missingness bounds. Do not call this an uninterrupted fixed-throughput experiment.

## Danger zones summary

| Risk | Severity | Bias direction |
| --- | --- | --- |
| Treating a correlated burst as a stable failure rate | HIGH | Unknown |
| Assuming smaller batches guarantee available capacity | HIGH | Unknown |
| Dropping failures or double-counting copied charges | CRITICAL | Inflates performance or misstates cost |
| Nonrandom missingness across operational epochs | HIGH | Unknown |

## Load-bearing assumptions

1. The provider eventually has capacity at the pinned route; smaller batches alone
   cannot prove this.
2. Frozen model inputs and all previous receipts remain byte-for-byte unchanged.
3. The original budget and missingness accounting include all historical work once.

## Invariants and validation

- Exactly the original 600 identities; no duplicates and no outcome-based top-up.
- Every included or excluded old row persists, along with its cost and native evidence.
- Existing admission is reusable only because its plan hashes and all sample plan
  hashes remain unchanged; all 75 current receipts were replayed after the code change.
- The source stays intact, the continuation has one destination, and further circuit
  acknowledgments are not automatic.
- Regression tests cover prefix preservation, no duplicate calls, known/unknown
  billing, unchanged spend limits, recurrent failures, source locks, collisions,
  symlinks, checkpoint tampering, the four-cell cap and rate-limit pausing.
- Unit consistency, provenance and boundary arithmetic are checked above. Financial
  allocation-specific proxy and regime scenarios do not apply to this scheduler change.

Honest one-sentence conclusion: the same sample can continue if provider capacity
returns, but its earlier failures and all charges must remain visible.

Validation: eleven new safeguard cases were observed failing before their respective
implementations. All 106 focused checks passed, followed by **712 full-suite passes,
three skips and one expected failure** in 126.71 seconds. The standalone
`verify_recovery_numbers.py` in the stopped study verified the cost ledger and
reservation arithmetic. A fresh endpoint read retained the pinned prices/context;
it did not establish that the upstream shared pool had available generation capacity.
