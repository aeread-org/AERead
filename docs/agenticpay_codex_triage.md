# Triage of docs/agenticpay_review_codex.md

The Codex review's author could not write files directly, so this triage records their findings verbatim below.

## Finding 1: Negotiation budget is too small

- **Classification**: REFUTED
- **Location**: `src/aeread_families/agenticpay_bilateral/cases.py:606`; `tests/test_agenticpay_bilateral_environment.py:362`
- **Evidence**: The current importer sets `"max_logical_actions": 2 * (max_rounds + 1)`, accounting for both seats and upstream's extra timeout round. The regression test asserts this exact budget and drives all 21 rounds to an upstream `"timeout"` with 42 logical actions. The claimed half-horizon budget is no longer present.

## Finding 2: Out-of-range agreements publish invalid shares

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/agenticpay_bilateral/measurement.py:482`
- **Evidence**: Lines 509–518 reject only a non-positive ZOPA or missing agreement, then calculate the share without checking `seller_min_price <= agreed_price <= buyer_max_price`. Lines 520–528 return `status="ok"`, validity `"valid"`, and reference bounds `[0,1]`. For `buyer_max=150`, `seller_min=80`, and `agreed_price=200`, this produces buyer share `-50/70` and seller share `120/70`, despite upstream explicitly defining the range check at `Task1_basic_price_negotiation.py:1188-1195`.

## Finding 3: Unbound replay reports "match" without comparison

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/agenticpay_bilateral/replay.py:110`
- **Evidence**: `RecordedEpisode` stores only `case_id` and decisions at lines 113–125. `replay_episode` checks only the case ID at line 219. `ReplayReport.status` returns `"match"` whenever there is no mismatching comparison—including when `comparison is None`—at lines 377–380. The test explicitly preserves this behavior at `tests/test_agenticpay_bilateral_replay.py:460-461`. A record can therefore be replayed against a newly hashed case and matching new `PlanCell` with altered reservation prices; no recorded provenance rejects it, and omitting `original` yields `comparison=None` plus `"match"`.

## Finding 4: Repeated legal contracts are marked illegal

- **Classification**: CONFIRMED
- **Location**: `src/aeread_families/agenticpay_bilateral/measurement.py:325`
- **Evidence**: Line 350 defines acceptance as `contract_before != contract_after`. Upstream, however, assigns every parsed, validated contract at `Task1_basic_price_negotiation.py:408-410`, even if it equals the previous value. Thus, after buyer contract `C` was previously accepted, repeating valid `C` leaves before and after equal. If the seller then submits compatible `C`, upstream reaches agreement, but the adapter emits `round_2_buyer_contract_legal=0` and makes the aggregate legality score `0.0`.

## Finding 5: Sealed evidence omits execution results

- **Classification**: KERNEL
- **Location**: `src/aeread/shared_runner/execution.py:2662`; `src/aeread/shared_runner/family_evaluation.py:211`
- **Evidence**: Evidence lifecycle ownership lies in the shared runner. Its production response source records the complete `TransitionResult` and post-state hash at `execution.py:2662-2677`, terminal and outcome at `execution.py:2693-2704`, and the finalized score at `family_evaluation.py:249-257`. The family's standalone scripted harness records only served responses, but deciding whether production evidence requires an additional bridge-specific event is a shared-runner evidence-contract concern, not an agenticpay-family defect.

## Finding 6: Fidelity tests can silently skip

- **Classification**: CONFIRMED
- **Location**: `conftest.py:29`; `tests/test_agenticpay_bilateral_environment.py:41`
- **Evidence**: The environment, measurement, and replay suites module-skip when the checkout is absent and individually skip when no bridge interpreter is available. `conftest.py:60-61` returns immediately unless a bridge-required environment variable is enabled. Therefore, with no usable bridge and no `AEREAD_AGENTICPAY_BRIDGE_REQUIRED=1`, pytest can exit successfully without running the bridge-backed fidelity assertions.

## Finding 7: Replay tests use circular scoring expectations

- **Classification**: REFUTED
- **Location**: `tests/test_agenticpay_bilateral_measurement.py:246`; `tests/test_agenticpay_bilateral_replay.py:360`
- **Evidence**: The replay-specific test does compare two results produced by the same scorer, but the wider family suite independently asserts hand-derived values. The provider-free unit test expects `50/70` at line 251, while bridge goldens independently expect buyer/seller shares `50/70` and `20/70` at lines 455–457 and `0.05`/`0.95` at lines 476–477. The proposed "change both formulas to the wrong denominator" scenario would therefore fail existing measurement tests even if the replay comparison itself remained equal.

COUNTS: confirmed=4 refuted=2 kernel=1
