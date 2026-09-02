# AucArena adapter integration spec (`aucarena` family)

**Status:** design spec; implementation not started
**Scope:** wrap `jiangjiechen/auction-arena` (paper P21) as a provider-free AERead family using
scripted `model_name == "rule"` bidders. LLM-driven bidders, the Gradio demo, and the
learning/memo path are out of scope tonight (see §6).

## Governing facts (verified in recon; do not re-derive)

- **Pin.** `jiangjiechen/auction-arena` @ `d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3`, license
  Apache-2.0. Checkout: `/Users/sunzeyu/Documents/econ benchmark/upstream-aucarena` (no `.git`
  remote metadata beyond the pinned commit; treated read-only).
- **Import cost.** `src/auctioneer_base.py` and `src/bidder_base.py` import `langchain`,
  `vertexai`, `torch`, `transformers`, `trueskill` at module level (`requirements.txt` pins
  `langchain==0.0.350`, `torch`, `google-cloud-aiplatform==1.28.1`). There is no way to import
  either module without paying that dependency cost, even to reach the deterministic bookkeeping
  methods inside them.
- **No fixed task corpus.** Unlike tau3 retail's 114 pre-existing task records, upstream ships
  only a raw item pool (`data/pseudo_items.jsonl`, 26 items, sha256
  `7418dba88c65ffd82797b6a2cbfab854cc1ebfabf87b5f40019834b84f21cf9b`) and an example bidder
  roster (`data/example/bidders_demo.jsonl`). `auction_workflow.py --shuffle --repeat` is a
  *generator over declared pools*, not an enumerable task list. AERead therefore authors the
  scenario corpus itself (item subset + order + bidder roster + budgets), the same relationship
  `housing_v1` has to its generated worlds, not the relationship `tau3_retail` has to its
  imported task records.
- **The `model_name == "rule"` path is fully deterministic and provider-free.** Tracing
  `auction_workflow.py:123-124` against `Bidder.bid`/`init_plan`/`summarize`/`replan`
  (`src/bidder_base.py:413-420,297-303,476-478,547-550`) confirms: for a rule bidder, `bid()`
  returns `''` immediately, `init_plan()`/`summarize()`/`replan()` do only bookkeeping
  (`rule_bid_cnt` reset, `cur_item_id` advance, `withdraw` reset) — no LLM call is reachable on
  this path. `bidding_multithread` still calls these methods per bidder but they are no-ops for
  `rule` model names, so a scripted all-rule-bidder auction is deterministic end to end.
- **`docs/benchmark_qc.md` does not exist in this repo** (checked worktree and main checkout).
  QC Gate 1/2 semantics below are inferred from `verifier_taxonomy.md` §9,
  `refund_external_benchmark_integration.md` §4, and this task's own five-golden enumeration.

## 1. Pinned source, corpus enumeration, content digest (QC Gate 1)

| Field | Value |
|---|---|
| `upstream_repo` | `jiangjiechen/auction-arena` |
| `upstream_commit` | `d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3` |
| `upstream_license` | Apache-2.0 |
| `item_pool_path` | `data/pseudo_items.jsonl` |
| `item_pool_sha256` | `7418dba88c65ffd82797b6a2cbfab854cc1ebfabf87b5f40019834b84f21cf9b` |
| `item_pool_count` | 26 |
| `vendored_files_sha256` | `item_base.py` `4ba0aefc...`, `auctioneer_base.py` `4c4311fc...`, `bidder_base.py` `1a8a298e...` (pinned at import; see §4) |

**Enumeration.** AERead defines each case as a *scenario record*: an ordered subset of item
ids from the pinned pool, a bidder roster (seat id, role, `budget`, `min_markup_pct`,
`max_bid_cnt`, `enable_discount`), and a `world_seed`. The importer (`cases.py`) does not read
an upstream task list — there isn't one — it materializes AERead-authored scenario records
against the pinned item pool and validates every referenced item id resolves in
`pseudo_items.jsonl`.

**Content digest.** `content_sha256` = kernel resolver hash over the canonical JSON payload
`{item_ids: [...], item_pool_sha256, roster: [...], world_seed, min_markup_pct,
enable_discount}` — the same resolver used by every other family (`is_exportable_id`-checked
`case_id`, no upstream DB blob to pin separately since there is none). Two importer runs must
be byte-identical (mirrors tau3 parity check P1).

**Case id grammar.** `aucarena.pilot.<golden_name>_<NN>`, e.g. `aucarena.pilot.successful_01`
— lower-case, dot/underscore-separated, no colons (`_ID_RE` in
`src/aeread/shared_runner/schemas.py:20`).

## 2. Verifier declaration

Per `docs/verifier_taxonomy.md` §2.1 and the P21 row in both `verifier_taxonomy.md` §13 and
`docs/problem_bound_case_audit.md:59`: **profit and TrueSkill do not solve the auction policy
game.** No `objective_reference` leaf is declared. Four leaves, all `composition_kind="leaf"`
(no scalar collapse):

| `estimand` | `verifier_family` | `reference_kind` | `input_scope` | `direction` | Claim |
|---|---|---|---|---|---|
| `aucarena_budget_invariant` | `rule_constraint` | `state_invariant` | `trajectory` | `none` | No seat's budget goes negative at any recorded state. |
| `aucarena_bid_legality` | `rule_constraint` | `constraint_satisfaction` | `trajectory` | `none` | Every recorded non-withdraw bid meets upstream's own rule: `>= item.price`, `>= prev_highest + min_markup_pct * item.price`, `<= budget` (vendored `bid_sanity_check`). |
| `aucarena_hammer_rule` | `rule_constraint` | `temporal_property` | `trajectory` | `none` | Each item's sold/unsold determination and winning bidder/price match the vendored `check_hammer`/`record_bid` trace exactly, in order. |
| `aucarena_profit_vs_field` | `comparative` | `head_to_head` | `terminal_state` | `maximize` | Tested seat's terminal profit against the named, declared field of frozen rule-bidder seats in the same scenario, same item order, same seed. |

`aucarena_profit_vs_field`'s comparator (the frozen bidder field: seat ids, `model_name`,
budgets) and the pairing (same `case_id`, same item order, same `world_seed`) are part of the
estimand per `verifier_taxonomy.md` §6 — never a global auction-skill score. `evaluation_class
= "deterministic"` for all four leaves in the scripted-rule-bidder scope of this spec (no
sampling, no judge). `measurement_validity` (§9 of the taxonomy) governs when
`aucarena_profit_vs_field` is declared `invalid_measurement` instead of scored — see golden 5.

## 3. Adapter boundary

Mirrors `docs/refund_external_benchmark_integration.md` §4.

**Upstream remains authoritative for** (via vendored, provenance-headed copies, §4 below):
the bid-legality rule (`bid_sanity_check`), the bid-increment rule (`bid_rule`), the
hammer/sale determination (`check_hammer`, `_num_bids_in_round`, `hammer_fall`), bid recording
and tie-breaking (`record_bid`), profit/budget bookkeeping (`win_bid`, `lose_bid`,
`set_withdraw`), and the item data shape (`Item`).

**AERead owns:** the scenario corpus (there is no upstream task list to resolve, §1);
canonical events, phases, decision slots, evidence, replay, receipts; the four
`MeasurementLeafSpec` declarations and their scorers; the scripted-bidder harness (deterministic
response source, not an LLM call); and all identifier/versioning/hash plumbing.

**Not delegated, and why that's safe here:** unlike tau3 (parity needs a live, stateful,
torch/langchain-loaded `Environment`), the rule-bidder path is ≈120 lines of pure,
dependency-free bookkeeping with no LLM prompt construction and no upstream randomness beyond
Python's seeded `random`. Vendoring it, rather than provisioning a venv to import two modules
that pull in `torch`/`vertexai` to run functions that never touch either, is the smaller
surface — enforced by a parity test (§5), not by trusting the transcription.

### Phase graph

One phase, self-looping per bidding round, matching `PhaseSpec` in
`src/aeread/shared_runner/scheduler.py:99-109` (mirrors the `housing_v1` `mode="simultaneous"`
pattern in `src/aeread/shared_runner/housing.py:520-551`):

```text
bid_round (mode="simultaneous", actor_selector="eligible_bidders")
  eligible_bidders = roster - {current highest bidder} - {seats withdrawn on this item}
  every eligible seat's observation is frozen pre-round (current highest bid/bidder,
    minimum next bid, own budget/items-won) -- no peer bid this round is visible until
    the round's bundle closes, per the simultaneous-phase contract
  step() applies vendored record_bid + check_hammer:
    not sold -> next_phases = ("bid_round",)   # next round, same item
    sold     -> advance to the next item (hammer_fall, cur_item_id += 1); if items remain,
                next_phases = ("bid_round",) for the new item, else -> terminal
```

The Auctioneer is environment-owned bookkeeping, not a seat (mirrors tau3: "the environment is
not a seat"). Plan/summarize/replan carry no informational content on the rule-bidder path (all
three are literal no-ops beyond counter resets, confirmed above) and are therefore **not**
modeled as decision slots — only the genuine per-round bid decision is. A future LLM-bidder mode
would need to promote them to real slots; out of scope tonight (§6).

## 4. Module layout

```
src/aeread_families/aucarena/
    __init__.py            # registers family_id "aucarena", version "0.1.0"
    _vendored_upstream.py  # bid_rule, bid_sanity_check, win_bid, lose_bid, set_withdraw,
                            # record_bid, check_hammer, _num_bids_in_round, hammer_fall,
                            # gather_all_status, Item -- each function carries a provenance
                            # docstring: source repo, exact commit, upstream file:lines,
                            # upstream Apache-2.0 license, and "changes: none beyond import
                            # removal / dataclass conversion" per Apache-2.0 SS4(b)
    cases.py                # scenario generator/importer -> cases/aucarena/pilot/*.json
    environment.py          # AucArenaPlugin: state, phase graph, decision slots, step/terminal
    measurement.py          # the four MeasurementLeafSpec declarations + scorers
    replay.py               # offline replayer (zero network, zero upstream import)
    parity.py               # hand-computed-trace parity runner (see §5)
cases/aucarena/pilot/
    aucarena.pilot.successful_01.json ... degenerate_reference_01.json
```

Example provenance header (in `_vendored_upstream.py`, one per function):

```python
def bid_sanity_check(bid_price, prev_round_max_bid, cur_item_price, budget, min_markup_pct):
    """Vendored from jiangjiechen/auction-arena @ d0f3bc851eb376d4ea5e69ae5fe52ec5be987bb3,
    src/bidder_base.py:623-637 (Bidder.bid_sanity_check). License: Apache-2.0.
    Changes: extracted to a free function over explicit arguments; no logic changed."""
```

## 5. Five QC Gate-2 goldens

All five use the same 3-seat roster unless noted: `agent` (tested), `field_low` (rule,
`budget=2000`), `field_high` (rule, `budget=9000`); `min_markup_pct=0.1`, `max_bid_cnt=4`,
`enable_discount=False`; items from `data/pseudo_items.jsonl` ids 1-4 (`Widget A`..`Doodad D`,
price 1000 / true_value 2000 each) unless noted.

1. **`successful_01`.** `agent` bids the legal minimum markup on every round it stays in,
   winning 2 of 4 items and losing 2 to `field_high`; `field_low` withdraws immediately every
   time. All three `rule_constraint` leaves pass on every recorded bid/hammer event;
   `aucarena_profit_vs_field` reports a finite, non-trivial (mixed-sign per-item) delta against
   `{field_low, field_high}`.
2. **`valid_but_poor_01`.** `agent` bids `-1` ("I'm out!") in round 0 of every item — always
   legal (`bid_price < 0` short-circuits `bid_sanity_check` to pass). Terminal profit is 0,
   budget untouched. All `rule_constraint` leaves pass trivially (no bid was ever attempted);
   `aucarena_profit_vs_field` is negative (both rule seats out-earn `agent`) — a valid,
   scoreable, strategically poor outcome, never misclassified as invalid.
3. **`invalid_unauthorized_01`.** Item 1 only. Round 0: `agent`'s scripted bid is `150` — a
   well-formed integer below the item's $1000 starting price, violating vendored
   `bid_sanity_check`'s `bid_price < cur_item.price` rule. `legal()` must reject it before any
   mutation (auctioneer `highest_bid`/`highest_bidder` and `agent.budget` unchanged) and
   `aucarena_bid_legality` must record the `constraint_satisfaction` failure keyed to that
   action id. Distinguishes an *impermissible* well-formed action from golden 4's malformed one.
4. **`malformed_operational_01`.** Item 1 only. Round 0: `agent`'s raw scripted response text
   is `"uh, I'll think about it"` — matches neither upstream `parse_bid`'s `-1` sentinel nor its
   `\$?\d+` regex (upstream's own signal to rebid, never a legality failure). `parse_action`
   must classify this as malformed-operational with zero state mutation, on a code path
   distinct from golden 3's `legal()` rejection.
5. **`degenerate_reference_01`.** Single-seat roster: only `agent`, no rule-bidder field, one
   item (id 5, `Equipment E`, price 5000). `agent` withdraws in round 0; `check_hammer` returns
   `is_sold=True` immediately (`highest_bidder is None`, `num_bid == 0`,
   `enable_discount=False`) — a legal, correctly-adjudicated failed-to-sell terminal state.
   Both `rule_constraint` leaves pass trivially. `aucarena_profit_vs_field` has an empty
   comparator population and must be declared `invalid_measurement` (per
   `verifier_taxonomy.md` §9), never silently scored as 0 or an undefined ratio.

## 6. Test plan

- **Parity (`tests/test_aucarena_parity.py`).** For each vendored function, a hand-computed
  trace over a small fixed item/bidder set (drawn from `data/pseudo_items.jsonl`) — e.g.
  `bid_rule(cur_bid=0, item.price=1000)` -> `1000`; `bid_rule(cur_bid=1000)` -> `1100`;
  `check_hammer` sequences with 0/1/2 bidders across rounds; `record_bid` tie-breaking with two
  equal bids. Every trace is asserted against the vendored function's output; hardening
  (optional, non-gating): re-derive the same trace by hand from the upstream source text quoted
  in each provenance header, so a reviewer can check the vendored body against the header
  citation without running upstream.
- **e2e (`tests/test_aucarena_environment.py`).** Drive all five goldens (SS5) through the full
  phase graph with the scripted harness; assert terminal outcomes, leaf results (including the
  `invalid_measurement` case), and zero network/API-key access (repo-wide provider-free
  convention, `conftest.py`).
- **Replay (`tests/test_aucarena_replay.py`).** Every golden's episode record replays offline
  (`replay.py`) to the identical terminal state and leaf results with no upstream import and no
  network call — the vendored functions are pure, so replay is exact by construction, not by
  fixture luck; this is the one property tau3 needs a live upstream bridge to get and this
  family gets for free.
- **Case/import (`tests/test_aucarena_cases.py`).** Importer determinism (byte-identical across
  two runs), item-id resolution against the pinned pool, `content_sha256` matches the kernel
  resolver, id-grammar rejects a colon-joined variant (mirrors
  `test_case_id_grammar_rejects_a_naive_colon_joined_upstream_id` in the tau3 suite).
- **Measurement (`tests/test_aucarena_measurement.py`).** One test per leaf per golden
  (20 cases: 4 leaves x 5 goldens), asserting pass/fail/`invalid_measurement` as declared in
  §5, plus a `VerifierSpec` construction test per family (`verifier_family` /
  `reference_kind` pairing must be accepted by `src/aeread/shared_runner/measurement.py`'s
  `_REFERENCE_KINDS`/`_REFERENCE_SCOPE` tables).

## 7. Stated limits

- Scripted `model_name == "rule"` bidders only. LLM-driven bidders (`plan_strategy` beyond
  `"none"`/`"static"`, `_belief_tracking`, `learn_from_prev_auction`) are not wrapped; they
  require the `langchain`-chained prompt/parse path this spec deliberately avoids importing.
- `aucarena_profit_vs_field` is `comparative`/`head_to_head`: it establishes performance against
  the *named, declared* rule-bidder field in that scenario, never a policy optimum, a universal
  auction-skill score, or a TrueSkill-style rating — per the P21 row in both
  `verifier_taxonomy.md` and `problem_bound_case_audit.md`, this route is `not_demonstrated` for
  saturation and must stay that way in any paper claim.
- The scenario corpus is AERead-authored (SS1); it is not a reproduction of an upstream-published
  task list, and no such list exists to expand toward. Growing coverage means authoring more
  scenario records against the same 26-item pool (or a future larger pinned pool), not importing
  more upstream tasks.
- `enable_discount` (price cuts after 3 failed-to-sell rounds) and the human-bidder path
  (`human_bidder.py`) are unvendored; scenarios in this spec fix `enable_discount=False`.
- No tool-call layer: AucArena bids are plain typed actions, not `ToolDefinition`-bound calls,
  so the shared-runner tool/state-evidence machinery tau3 uses is not exercised by this family.

---

**Ledger note:** the missing `docs/benchmark_qc.md` (governing facts, above) is logged to
`ledger_entries/aucarena.md` — not this spec's problem to fix.
