# The refund negotiation case

Refund V1 is a two-seat customer-support negotiation case.  It tests whether an
LLM support agent can apply a detailed refund policy while interacting with a
scripted customer whose private facts are revealed gradually.  The case is designed
for the AERead shared runner: manifests use `aeread.case/0.1`, actions are JSON
objects produced through the provider API boundary, and terminal outcomes are
replayable without new model calls.

## 1. Task shape

The seats are:

| seat | role | private information |
|---|---|---|
| `customer` | customer | true product condition, issue type, evidence, usage, activation, return status |
| `support_agent` | support agent | no hidden customer facts until the customer reveals them |

The support agent is the tested seat in the default evaluation block.  The
customer is a controlled deterministic script with access to the private truth,
so the counterpart is held fixed while the support agent varies.  The customer
initially states the request without revealing private fields, then reveals only
fields explicitly requested by support, capped at three fields per turn.  The
runner alternates:

1. `customer_message`: the customer states a request, reveals selected private
   fields, counters, accepts, or rejects.
2. `support_response`: the support agent asks for missing facts, makes an offer,
   or finalizes with `approve_direct`, `request_return`, `escalate`, or `deny`.

The maximum episode length is eight logical actions, enough for four
customer/support turns.  Invalid JSON is handled as an in-world invalid
operation, so model failures are counted rather than dropped.

## 2. Difference from Housing

Refund follows the housing case's shared-runner structure, but the economic
object differs.

| dimension | housing | refund |
|---|---|---|
| environment | scarce two-sided allocation market | two-party policy negotiation |
| seats | tenants and landlords | customer and support agent |
| hidden information | tenant values and landlord costs | customer product facts and policy-relevant evidence |
| gradual revelation | bids, holds, and commitments expose intent | customer messages reveal selected private fields |
| transfer | rent moves value between tenant and landlord | refund money moves value between customer and company |
| primary welfare | tenant plus landlord payoff | customer plus support/company payoff |
| oracle | max-weight assignment upper bound | full-information policy-resolution reference |

The analogy is the transfer accounting: rent does not create housing welfare,
and a refund transfer does not create refund welfare.  Welfare comes from
matching the valid economic resolution while avoiding friction, leakage,
underpayment, and compliance penalties.

## 3. LLM API Path

`aeread.shared_runner.refund.RefundV1Plugin` exposes the family to the shared
scheduler.  It parses `CanonicalResponse` JSON emitted by API clients and uses
the same observation/action path for tests and live runs.

The bridge includes `GeminiProviderClient`, which wraps the repository's native
Gemini REST backend.  Live Gemini runs require `GEMINI_API_KEY` or the existing
Vertex environment variables.  The same plugin can also be used with the
shared-runner OpenAI/OpenRouter clients by assigning compatible `AgentProfile`s
and structured-output schemas:

- customer prompt: `aeread.shared_runner.refund.CUSTOMER_PROMPT`;
- support prompt: `aeread.shared_runner.refund.SUPPORT_PROMPT`;
- customer schema: `CUSTOMER_OUTPUT_SCHEMA`;
- support schema: `SUPPORT_OUTPUT_SCHEMA`.

Tests use fixture `CanonicalResponse`s, not scripted policy choices.  This keeps
CI provider-free while exercising the same JSON parsing boundary a live LLM call
uses.

## 4. Policy

All monetary values are in USD.  A refund can never exceed the product price,
the customer-requested amount, or the category maximum.

| category | refund window | category maximum | base auto threshold | high-trust threshold | return required |
|---|---:|---:|---:|---:|---|
| perishable goods | 2 days | 150 | 35 | 70 | no |
| consumer electronics | 30 days | 1,000 | 150 | 400 | yes |
| software | 14 days | 300 | 80 | 150 | no |
| apparel | 30 days | 250 | 75 | 175 | yes |

Trust bands modify only the automatic direct-refund threshold.  They never make
an otherwise ineligible request eligible.

| trust band | rule |
|---|---|
| high trust | credit score at least 720, gold or platinum loyalty, no chargebacks, at most two prior refunds in 12 months |
| good trust | credit score at least 660, silver or better loyalty, no chargebacks, at most three prior refunds in 12 months |
| standard | any customer not otherwise classified |
| fraud watch | credit score below 580, any chargeback, or at least five prior refunds in 12 months |

Good-trust customers receive the midpoint between the base and high-trust
automatic threshold.  Fraud-watch customers have threshold `0`: any monetary
refund must be escalated to human review.

## 5. Category Rules

Perishable goods are refundable only for spoiled, damaged, missing, or recalled
items reported within two days, and evidence is required.  Buyer remorse is not
refundable because the goods cannot be restocked.

Consumer electronics are refundable within 30 days when unopened, or when opened
and defective.  Opened buyer-remorse returns receive a 15% restocking fee.  A
physical return is required before direct payment refund.

Software is refundable within 14 days for billing errors, low-use defects, or
unactivated remorse purchases.  Subscription cancellations are prorated over a
30-day service month.  Activated high-use remorse purchases are denied.

Apparel is refundable within 30 days for defective goods or resaleable remorse
returns with tags.  Worn buyer-remorse items are denied.  A physical return is
required before direct payment refund.

## 6. Ground Truth

The policy oracle applies rules in this order:

1. Reject requests outside the category window or excluded by category rules.
2. Compute the eligible amount after caps, restocking fees, and prorating.
3. If the product requires return and return has not been received, emit
   `request_return` with amount `0`.
4. If the customer is fraud-watch or the eligible amount exceeds the automatic
   threshold, emit `escalate` with the eligible amount and human review.
5. Otherwise emit `approve_direct` to the original payment method.

The oracle decision is not used as a scripted support action.  It is the
full-information reference used to score the terminal negotiation outcome.

## 7. Joint Utility

The primary outcome is `joint_utility`, the sum of customer utility and support
agent utility.  Refund money is treated as a transfer: it helps the customer and
costs the company, so it cancels in the joint total just as rent transfers do in
housing.  What remains are relationship surplus, friction, review cost, return
cost, leakage, underpayment, and compliance penalties.

| metric | definition |
|---|---|
| `customer_utility` | expected customer compensation minus negotiation friction |
| `support_agent_utility` | relationship surplus minus transfer, review, return, leakage, and compliance costs |
| `joint_utility` | `customer_utility + support_agent_utility`; primary score |
| `within_case_score` | realized joint utility divided by oracle joint utility when positive |
| `reason_codes` | diagnostic explanation for eligibility, penalties, and routing |

This makes negotiation meaningful.  The support agent can improve welfare by
asking for missing facts, avoiding unauthorized direct refunds, escalating large
or risky valid claims, and denying invalid claims without overpaying.

## 8. Cases

The initial curated pilot contains eight cases covering direct approval,
deadline denial, high-dollar escalation, return-required pending states,
fraud-watch escalation, restocking, prorated software, and category exclusions.

`cases/refund_v1/policy.json` stores the public policy.  Each
`cases/refund_v1/refund_v1.curated.<n>.json` manifest stores `public_order`,
`private_customer_truth`, and `payload.ground_truth`.  The support agent sees
only `public_order`, policy, transcript, and fields revealed by the customer.

Future generated cases should vary:

- product category and price, including prices above the category maximum;
- delivery age at, inside, and outside the refund window;
- customer trust band, especially threshold boundary cases;
- hidden condition and evidence fields that require follow-up questions;
- return status for physical goods;
- software activation, usage, and subscription proration;
- requested amount below price, equal to price, and above price.

Refund also supports housing-style generated experiments via `world_seeds`.
Unlike curated cases, generated cases are not written to disk by default; they
are generated deterministically inside the sealed run plan.

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund \
  --provider fake \
  --world-seeds 41001,41002,41003 \
  --output /tmp/aeread_refund_seeded
```

Each seed produces one generated refund case and one plan cell.

## 9. Reproducing

Regenerate the curated manifests:

```bash
PYTHONPATH=src python -c 'from pathlib import Path; from aeread.refund_env import write_curated_cases; write_curated_cases(Path("cases/refund_v1"))'
```

Run a provider-free smoke episode through the same shared-runner path used by
API-backed runs:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund \
  --provider fake \
  --case-id refund_v1.curated.000001 \
  --output /tmp/aeread_refund_smoke
```

Run the focused test suite:

```bash
PYTHONPATH=src pytest tests/test_refund_env.py -q
```

After installing the package in editable mode, the equivalent command is:

```bash
aeread-refund --provider fake --case-id refund_v1.curated.000001 --output /tmp/aeread_refund_smoke
```

## 10. API-backed runs

API keys are environment variables, not case-file fields.

```bash
export GEMINI_API_KEY="..."
export OPENAI_API_KEY="..."
export OPENROUTER_API_KEY="..."
export ARENA_API_KEY="..."
```

Gemini:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund \
  --provider gemini \
  --model gemini-3.5-flash \
  --case-id refund_v1.curated.000001 \
  --output /tmp/aeread_refund_gemini
```

OpenAI:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund \
  --provider openai \
  --model gpt-5-nano-2025-08-07 \
  --case-id refund_v1.curated.000001 \
  --output /tmp/aeread_refund_openai
```

DeepSeek through OpenRouter:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund \
  --provider openrouter \
  --model deepseek/deepseek-v4-flash-0731 \
  --revision deepseek/deepseek-v4-flash-20260731 \
  --case-id refund_v1.curated.000001 \
  --output /tmp/aeread_refund_deepseek
```

Arena:

```bash
PYTHONPATH=src python -m aeread.shared_runner.refund \
  --provider arena \
  --model claude-sonnet-4-6 \
  --max-output-tokens 4096 \
  --world-seeds 24 \
  --output /tmp/aeread_refund_arena
```

Arena exposes token usage but not a price schedule through the compatible Chat
Completions response, so these runs are recorded with an `unpriced` zero-rate
pricing profile.  API billing remains authoritative in the Arena dashboard.

`--model` and `--support-model` select the tested support model.  The customer
remains the fixed scripted counterpart and does not make an API call.

## 11. Relationship to AER and adjacent benchmarks

Refund V1 is compatible with AERead's goal because it evaluates an agent's
economic decisions under partial information, keeps the counterparty fixed,
records the interaction that produced the outcome, and scores the consequences
for both sides.  The refund payment is a transfer: it benefits the customer and
costs the support side, so it cancels from joint utility.  The remaining score
captures relationship surplus, interaction friction, return and review costs,
underpayment, leakage, and compliance failures.  This is the same accounting
principle used for rent transfers in Housing, while retaining Refund-specific
policy semantics.

The controlled customer is intentionally responsive rather than omniscient in
the public transcript.  It starts with a generic request and reveals at most
three requested private fields per turn.  This tests whether support asks for
decision-relevant information without allowing customer-model quality to
confound the support-agent comparison.

This differs from tau-bench/tau3 retail in measurement and benchmark ownership.
Those environments primarily evaluate tool-mediated service workflows against
task and terminal-state success, often with a simulated user and a database/API
state.  Refund V1 is an AERead-native economic environment: its policy oracle,
information projections, bilateral utility decomposition, transfer accounting,
interaction costs, generator, and receipts/evidence contract define benchmark
truth.  A future tau adapter should remain a separately pinned compatibility
measurement rather than being pooled with native Refund scores.

TERMS-Bench and negotiation benchmarks are closer in being interactive and
counterpart-dependent, but they typically measure agreement or role utility
under a specified opponent.  Refund fixes the customer policy to isolate the
tested support agent and evaluates policy compliance plus bilateral welfare.
Housing and Refund likewise share runner discipline but not a common scalar
scale; this work does not average or rank their scores across families.

## 12. Live 20-case coverage pilot

On 2026-08-31, DeepSeek V4 Flash was run through Arena on a fixed panel of 20
oracle-stratified generated worlds, with five cases from each product category
and three replicates under each of two requested condition labels.  The run
completed 100 of 120 trajectories and retained 20 operational exclusions.  All
120 event logs were audited, but Refund does not yet emit the durable evaluation
receipts used by the final Housing experiment.

The run is instrumentation and behavioral-coverage evidence, not a reasoning
experiment.  The Arena adapter recorded the requested `none` and `low` labels
but did not transmit a reasoning-control parameter; both arms returned reasoning
tokens.  Only eight worlds had all three valid replicates in both labels, and
the diagnostic paired interval included zero.  The selected panel was
oracle-stratified rather than sampled outcome-blind, so it does not support a
population claim.  The compact report is
[`evidence/refund_deepseek_arena_coverage20_2026-08-31.json`](evidence/refund_deepseek_arena_coverage20_2026-08-31.json).

If a live provider returns a `Retry-After` rate-limit signal, wait that many
seconds and rerun, or lower the number of `--world-seeds` in the batch.  The
provider-free `fake` path is intended for local reproducibility and does not
call external APIs.
