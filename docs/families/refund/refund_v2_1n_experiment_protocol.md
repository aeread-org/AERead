# Refund V2.1 1:N Controlled Experiment Protocol

This protocol defines the first provider-backed Refund V2.1 campaign after the
shared-runner and publication-boundary updates. It does not authorize or imply
that a provider run has been completed.

## Fixed design

- **Topology:** 1:N: one customer, intake, policy, and payments seats.
- **Active seat:** `policy` only. Customer, intake, and payments use their
  declared deterministic scripted profiles.
- **Evaluation block:** `controlled`; `self_play` is excluded from this
  campaign and remains an explicitly opt-in diagnostic.
- **Model:** Grok 4.3, provider route `arena`, model/revision identifier
  `grok-4.3`.
- **Panel:** 20 fixed world seeds:
  `0,9,17,24,27,1,4,8,15,20,2,10,14,19,28,5,7,13,16,23`.
- **Cases:** six cases per seed, for 120 planned cells. The panel covers full
  refund, denial, partial refund, a policy-window boundary, conflicting claims,
  and missing evidence across four product categories.
- **Disclosure:** customer facts are revealed only in response to bounded fact
  requests. The policy seat receives no authorization oracle, semantic scenario
  label, or scenario-bearing case identifier.

## Measurement order

The primary reported measure is policy compliance. Transaction correctness is a
co-required admission leaf: an included success must satisfy both policy and
transaction checks. Coordination is a secondary process diagnostic. Holistic
system utility is reported last as a Refund-specific economic diagnostic and is
not a cross-family scalar comparable to Housing or AgenticPay.

Every planned cell must be represented by either a sealed evaluation receipt or
a durable typed operational-exclusion record. Operational exclusions are
reported separately from model performance.

## Run command

From the repository root, with the Arena key in the environment file:

```bash
PYTHONPATH=src python -m aeread_families.refund.v2_llm_experiment \
  --model grok-4.3 \
  --revision grok-4.3 \
  --active-agents policy \
  --evaluation-kind controlled \
  --world-seeds 0,9,17,24,27,1,4,8,15,20,2,10,14,19,28,5,7,13,16,23 \
  --max-output-tokens 4096 \
  --env-file /Users/ycfang/Documents/ChatGPT/AER/.env.local \
  --output /tmp/aeread_refund_v21_grok43_controlled
```

The command produces local sealed evidence only. It does not publish raw run
directories. After the run completes, publish it with:

```bash
PYTHONPATH=src python -m aeread_families.refund.v2_publication \
  --run-root /tmp/aeread_refund_v21_grok43_controlled \
  --publication-root /Users/ycfang/Documents/ChatGPT/AER/evidence/refund/refund_v2_1_grok43_controlled_2026-09-12
```

The publication command runs the canonical `export-tables` projection in a
private analysis directory, copies only vetted tables into the public bundle,
seals the publication manifest, and adds sanitized logical-action trajectories.

## Required report

The report must include planned, completed, included, and excluded cell counts;
policy compliance; transaction correctness; coordination; system utility;
typed operational-failure conditions; per-scenario counts; and the run-plan,
receipt, and publication-manifest digests. It must not rank the model using
system utility alone or claim cross-family numerical comparability.
