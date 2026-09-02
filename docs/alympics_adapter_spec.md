# Implementation specification — `alympics.wac` adapter for the AERead shared-runner kernel

**Scope.** Wrap one upstream game from `microsoft/Alympics` (MIT, arXiv 2311.03220 / COLING 2025), pinned at commit `caed7c8c3b8f9de9ac8be1ba54407a51087affc5` (upstream's own last commit, 2024-05-23 — **dormant since 2024-05, pin is fine, noted unmaintained in §6**): the **Water Allocation Challenge (WAC)** — a 5-seat sealed-bid repeated allocation with survival pressure. Family name inside AERead is `alympics.wac`; "upstream" always means this pinned checkout. Per the problem-bound audit (`docs/problem_bound_case_audit.md`, row P01): `optimizable, strategic and opponent-dependent`, strongest justified reference status `baseline_only` — *"survival has natural support, but the paper does not solve the policy game... do not equate survival with a solved optimum."* Corpus is **one parameterized scenario**, not N task files: `exp/WAC/*.zip` are recorded past-run outputs, not inputs, and are ignored.

**`docs/benchmark_qc.md` does not exist on `main` or this branch** (`find . -iname "*benchmark_qc*"` and `grep -rn "QC Gate" docs/*.md` both empty). It exists, unmerged, at commit `2b831fec7d9962bebe4396108ad47a5e2321d9e7` and is retrievable from any worktree via `git show 2b831fe:docs/benchmark_qc.md` without merging — already tracked as master ledger `D-10` (8 corroborating reports across 6 prior adapters). This spec quotes that file's real Gate 1/Gate 2 text directly (§1, §4) rather than re-deriving it a ninth time; see `ledger_entries/alympics.md`.

**Governing facts** (verified in recon by direct execution against the pinned checkout; do not re-derive):

- `src/Alympics.py` (60 lines) does module-level `import openai`, but **touches no attribute on it at import time** — verified: `dir(stub)` is empty immediately after `import Alympics; import waterAllocation`. `LLM.__init__` only *sets* `openai.api_type`/`api_base`/`api_version`/`api_key` (plain attribute assignment, safe on any object); `LLM.call` is the only method that reads `openai.ChatCompletion`, and the adapter never calls it.
- `waterAllocation.__init__` (`src/waterAllocation.py:71-98`) hardcodes exactly 5 personas — Alex(req 8, salary 70), Bob(9, 75), Cindy(10, 100), David(11, 120), Eric(12, 120), all starting `hp=8`, `maximum_health=10`, `no_drink=1` — with **no constructor parameter to vary them**. Persona identity/requirement/salary is therefore upstream-fixed scaffolding, not a grid dimension tonight (§6).
- Exactly 2 LLM call sites, both routed through the *same* `LLM.call(self, message)` method: `myPlayer.execute_bidding` (bid generation, via `self.llm` — one instance **per player**) and `waterAllocation._parse_result` (text-to-JSON parsing, via `self.llm` — **one instance owned by the game**). Because each of the 6 `LLM` instances is distinct, replacing `.call` **per instance** (not on the class) cleanly separates the two call sites with no content-sniffing — see §3.
- `_check_winner` (`waterAllocation.py:112-130`) is a greedy sequential admission: repeatedly find the highest bidder among not-yet-winners whose `requirement <= (currently remaining) supply` and `bidding <= balance`, admit exactly one per pass, decrement `supply` by that winner's `requirement`, repeat until no candidate qualifies. **Verified**: with 5 seats identically bidding 5 and `supply=20`, winners are `['Alex','Bob']` (order-of-construction is the tie-break, which coincides with ascending `requirement` for this specific persona list — not an explicit sort, contrary to `round_results_prompt`'s flavor text claiming "prioritizing low-demand individuals"). A bid exceeding the seat's own balance is **silently excluded from winning, never flagged**: verified — Alex bidding 10,000 against balance 70 simply loses that round's auction with no error and no distinguishing outcome from a legal loss.
- `_round_settlement` and `success_bid`/`unsuccess_bid` are pure, deterministic, delegated unmodified: win → `hp = min(10, hp+2)`, `balance -= bidding`, `no_drink = 1`; lose → `hp -= no_drink`, `no_drink += 1` (a **linearly escalating** drought penalty).
- **Full-elimination calls Python's builtin `exit()`** (`run_single_round`, when `len(survival_players)==0`) — a hard `SystemExit`, not a return value. Verified: driving 4 rounds of `supply=0` eliminates all 5 seats simultaneously (identical `hp` trajectory 8→7→5→2→eliminated for every seat, since starting `hp`/`no_drink` and the penalty formula do not depend on persona identity) and raises `SystemExit(None)` from inside upstream code. The harness **must** catch this at the seat boundary (§3); letting it propagate would kill the scheduler process, not just end one episode.
- Malformed parse output propagates as an **uncaught exception one level above** upstream's own retry loop, verified concretely: a parsed JSON missing one player's key raises `KeyError('Eric')` in `run_single_round` step 3; JSON that never parses across upstream's own 3 attempts leaves `_parse_result` returning the *raw last string* (not a dict), which then raises `TypeError("string indices must be integers, not 'str'")` at the same call site.
- Upstream's own reference driver (`src/run.py`) uses `argparse` defaults `round=20`, `lower=10`, `upper=20`, and calls `np.random.randint(lower, upper, round)` **with no seed set anywhere in the script** — upstream's own reference run is not reproducible as shipped; AERead must own an explicit, declared `world_seed` for the supply schedule (§1).
- `requirements.txt` lists only packaging-tool leftovers (`altgraph`, `macholib`, `pip`, `setuptools`, `wheel`, `future`, `six`) — not `openai`, not `numpy` (used by `run.py` only, not by the game/scoring modules the adapter executes).

---

## 1. Upstream dependency, pinning, and corpus enumeration (Gate 1)

Per the real `docs/benchmark_qc.md` §"Gate 1: Task-distribution admission": *"establish that sampled tasks are valid, distinct, informative instances of the declared construct"* — re-resolve from pinned source with identical digests, validate dimensions/ranges, validate denominators, stratify by declared difficulty, reject duplicates/near-duplicates, and separate development from confirmatory seeds.

- **Pin.** `microsoft/Alympics`, commit `caed7c8c3b8f9de9ac8be1ba54407a51087affc5`, MIT. No release tag since the repo's only activity is 9 PRs merged by 2024-05-23; **unmaintained**, noted as an explicit limit (§6), not a blocker — the pinned commit is immutable regardless.
- **No bridge.** Neither an isolated venv nor a vendored copy is needed (unusual among this family's other adapters — tau2/negarena/govsim all needed one). Execution is a direct import of the real, unmodified `src/Alympics.py` / `src/waterAllocation.py` from the read-only pinned checkout (`sys.path` prefixed at the checkout's `src/`, never copied, never written to), plus one AERead-owned `sys.modules["openai"] = types.ModuleType("openai")` stub installed before import — safe per the governing fact above (no attribute read at import or construction time). `_check_winner`, `_round_settlement`, `success_bid`, `unsuccess_bid`, `_get_salary` execute as upstream's own code via `run_single_round`, never reimplemented.
- **Corpus enumeration.** Upstream ships no task bank (same situation as `housing_v1`: cases are "generated; no static JSON fixtures", never `tau3_retail`'s imported `tasks.json`). AERead is the corpus's provenance owner; `ProvenanceSpec.review_status` (only `{"generated","reviewed","curated","upstream_pinned"}` are legal — `src/aeread/shared_runner/schemas.py:441-444`) is set to `"curated"`. Gate 1 = one declared parameter grid over {supply regime, rounds, supply-schedule seed, policy assignment vector across the 5 fixed seats}, **not** persona/requirement/salary (upstream-fixed, see governing facts). Tonight's grid is 7 cells, one `CaseManifest` each (`spec_version: "aeread.case/0.1"`), dot-separated lower-case ids, no colons (`is_exportable_id`):

| # | Case id | Supply regime | Rounds | Seed | Policy assignment |
|---|---|---|---|---|---|
| 1 | `alympics.wac.reference_baseline` | `U(10,20)` (upstream defaults) | 20 | 0 | all `proportional`; parity anchor (§5), reproduces upstream's own reference config, seeded for reproducibility upstream itself lacks |
| 2 | `alympics.wac.generous_supply` | `U(20,30)` | 10 | 0 | all `proportional` |
| 3 | `alympics.wac.scarce_supply` | `U(3,8)` | 10 | 0 | all `proportional`; high survival pressure, low headroom |
| 4 | `alympics.wac.mixed_policies_a` | `U(10,20)` | 15 | 1 | `{Alex:aggressive, Bob:conservative, Cindy:proportional, David:myopic_need, Eric:proportional}`; heterogeneous panel, one seat rotates as focal across paired trials (comparative estimand, §2) |
| 5 | `alympics.wac.mixed_policies_a_seed2` | `U(10,20)` | 15 | 3 | identical to #4 — disjoint-seed pairing Gate 1 requires before treating repeats as independent clusters |
| 6 | `alympics.wac.short_horizon` | `U(15,25)` | 5 | 2 | all `proportional`; low elimination risk, isolates early-round policy differences |
| 7 | `alympics.wac.zero_supply_degenerate` | `= 0` | 20 | — | all `proportional`; degenerate-reference golden anchor (§4) |

- **Content digest.** `content_sha256` over the canonicalized manifest (`family_id`, persona block, supply-schedule generator + seed, rounds, policy assignment, upstream pin) — the supply schedule itself is generated **once at import time** (`np.random.RandomState(world_seed)`, never upstream's unseeded global `np.random`) and frozen into the manifest, never regenerated at run time. Importer run twice must yield byte-identical manifests (Gate 1 check 1).

## 2. Verifier declaration (per `docs/verifier_taxonomy.md`)

Four leaves, `composition_kind` fixed to `"leaf"` on each — reported as a `vector` (taxonomy §10), never collapsed to one scalar, per the audit's explicit instruction not to equate survival with a solved optimum.

**Leaf 1 — `alympics_wac_terminal_wealth` (primary, comparative).** `measurement_kind: optimizable_outcome` (P01's own classification), `verifier_family: comparative`, `reference_kind: baseline_delta` — terminal balance for the focal seat compared with the same seat run under a named baseline policy, same supply schedule/seed/opponent panel. The **opponent panel (the other 4 seats' declared policies) is part of the estimand**, per the audit's explicit instruction, recorded in the case/cell manifest, not just run config. `direction: higher_is_better`, `units: native_currency`, evaluation mode deterministic (given a complete scripted trajectory, settlement is a pure function).

```yaml
verifier_id: alympics_wac_terminal_wealth_v1
verifier_family: comparative
reference_kind: baseline_delta
input_scope: trajectory
direction: higher_is_better
units: native_currency
determinism: deterministic
composition: leaf
cluster_mapping: task_instance   # one grid cell x one focal-seat policy assignment
opponent: {panel_policy_ids: [string, ...], pairing_rule: fixed_panel_v0}
implementation: {package: aeread_families.alympics_wac, upstream_commit: caed7c8c...}
```

**Leaf 2 — `alympics_wac_survival` (diagnostic, comparative).** `measurement_kind: optimizable_outcome`, `verifier_family: comparative`, `reference_kind: baseline_delta`, `units: rounds_survived` (or `alive_at_terminal: bool`). Reported **separately** from Leaf 1 so a degenerate zero-information elimination (§4 golden 5) is never averaged into wealth as if it were a normal loss (taxonomy §9: "an invalid or missing observation must not be scored as ... a dominated policy").

**Leaf 3 — `alympics_wac_bid_legality` (rule_constraint).** `measurement_kind: property_or_answer`, `verifier_family: rule_constraint`, `reference_kind: constraint_satisfaction`, `input_scope: trajectory`. Per round, per seat: bid is a non-negative integer and `bid <= balance` at the time of bidding — the gate upstream itself only enforces *implicitly* (a violating bid just never wins, silently — governing facts). The adapter checks this **before** delegating to `_check_winner`, independent of round outcome.

**Leaf 4 — `alympics_wac_settlement_exactness` (rule_constraint).** `measurement_kind: property_or_answer`, `verifier_family: rule_constraint`, `reference_kind: state_invariant`, deterministic, delegated: recompute each round's `balance`/`hp`/`no_drink` transition by direct (shadow) invocation of upstream's own `_get_salary`/`_check_winner`/`_round_settlement` against the recorded pre-state, and require exact equality with the sealed post-state — never a reimplementation, a **parity cross-check** of the same upstream call.

`measurement_validity` additionally checks: parseable scripted bid per seat (Leaf 3's prerequisite), and — per the real Gate 2's requirement 4 — an **agent-visible-payload leakage audit**: the focal seat's observation must never contain another seat's not-yet-revealed bid before that round's allocation is announced (upstream's own `inquiry_prompt` never includes other seats' bids pre-allocation, but the *adapter's* seat-private view construction must preserve that, since all 5 `myPlayer.history` lists are held on one shared Python object graph).

## 3. Adapter boundary (mirrors `refund_external_benchmark_integration.md` §4)

**Upstream owns:** the 5-persona construction and prompt text; `_get_salary`, `_check_winner`, `_round_settlement`, `success_bid`, `unsuccess_bid` (settlement math, executed via direct import, never reimplemented); the elimination check and its `exit()` idiom inside `run_single_round`.

**AERead owns:**
- resolution of the authored parameter grid into an immutable `CaseManifest` (§1) — upstream has no corpus to resolve *from*;
- the phase graph — **Mode C** (`mode="simultaneous"`, matching `housing_v1`'s `contact`/`respond`/`commit` shape, `src/aeread/shared_runner/scheduler.py:25`, `_PHASE_MODES = {"single","sequential","simultaneous"}`), a single self-looping phase:

```
bid   mode=simultaneous, actor_selector="survival_players" (upstream's own attribute name),
      max_logical_actions = 5 * rounds  (upper bound; the scheduler counts phase actions
      across every loop instance for the whole episode, never reset per round — a known
      kernel quirk, already ledgered by govsim, not re-raised here)
      -> one env-side round: _get_salary(), collect all alive seats' bids, _check_winner(),
         _round_settlement(), elimination check
-> loop to `bid`, or terminal on rounds exhausted / all seats eliminated
```

- **per-instance `LLM.call` replacement**, never a class-level monkeypatch: after constructing the real `waterAllocation(...)`, rebind `player.llm.call` (5 seats, closure-captures that player + its assigned scripted policy) and `wa_instance.llm.call` (one instance, closure-reads the per-seat bids the same driver just computed) *before* invoking `run_single_round`. This sidesteps content-sniffing the prompt entirely and prevents any cross-episode state leak, since each episode owns fresh `LLM` instances;
- **the bid-legality admission gate** upstream itself skips (Leaf 3, §2) — checked before `run_single_round` is invoked for that round, never after;
- **`SystemExit` interception**: `run_single_round` is called inside a `try/except SystemExit`; on catch, the episode terminates with reason `all_seats_eliminated`, never propagates past the adapter;
- **the malformed-parse catch**: `KeyError`/`TypeError` raised inside `run_single_round` (from an intentionally-malformed scripted "parse" stand-in, §4 golden 4) is caught at the seat boundary and recorded `malformed_action` / `outcome_unknown`, never left to crash the episode process;
- canonical events, visibility, evidence, replay, receipts (portable records, unchanged); typed measurement declarations (§2) and opponent/policy-assignment metadata.

No native `alympics_wac_v1` reimplementation is proposed; this stays a thin direct-import wrapper over pinned upstream mechanics.

## 4. QC Gate-2 goldens

Per the real `docs/benchmark_qc.md` §"Gate 2": successful / valid-but-poor / invalid-or-unauthorized / malformed-or-operational-failure / degenerate-reference, plus (beyond the table) independent-oracle cross-check, transition reconstruction, exact component reconciliation, payload-leakage audit, and zero-provider-call replay (all covered in §5 below).

| Golden | Construction | Expected outcome |
|---|---|---|
| Successful | `alympics.wac.reference_baseline`, all seats `proportional` | Round 1 verified concretely: seats bid `{Alex:24,Bob:27,Cindy:30,David:33,Eric:36}` (`3x` requirement); with the seeded supply draw, a strict subset wins per `_check_winner`'s greedy admission; Leaf 3/4 pass every round; focal seat (any) survives to `rounds=20`; Leaf 1/2 report a positive terminal wealth and full survival |
| Valid-but-poor | Same case, focal seat scripted `conservative` (bids `1x` requirement) against 4 `proportional` rivals | Every bid legal and well-formed (Leaf 3/4 pass); focal seat is systematically outbid, loses most rounds, ends with materially lower terminal wealth and/or more `no_drink` escalation than the `proportional` baseline — "legal action, bad outcome," never touching the admission gates |
| Invalid-unauthorized | Focal seat scripted to bid `balance + 1` (verified concretely with `balance=70`: a bid of `10000` never wins, no error, no distinguishing flag from upstream) | The adapter's independent Leaf-3 gate must catch `bid > balance` **before** delegating to `_check_winner` and mark that round `invalid_measurement` for the focal seat — never let the silent exclusion "masquerade" as an ordinary legal loss |
| Malformed-operational | Scripted "parse" stand-in for `wa_instance.llm.call` omits the focal seat's key from the JSON it returns | Verified: raises `KeyError` inside `run_single_round`; the adapter must catch it at the seat boundary and record `malformed_action`, never crash the episode process nor silently substitute a default bid |
| Degenerate-reference | `alympics.wac.zero_supply_degenerate` (supply `=0` every round) | Verified: no seat's `requirement <= 0` ever holds, so `_check_winner` returns zero winners every round; **all 5 seats** follow the identical `hp` trajectory `8→7→5→2→eliminated` at round 4 (persona identity is irrelevant to this outcome — starting `hp`/`no_drink` and the penalty formula do not depend on it) and hit the `SystemExit` path (§3) simultaneously. Leaf 1/2 become information-free — identical for every policy by construction — and must be flagged `not_informative`, never reported as "every policy tied at zero skill" |

## 5. Test plan

- **e2e.** Each of the 5 goldens driven through the Mode C phase graph with scripted per-instance `LLM.call` replacements (§3); assert Leaf 1-4 values match the hand-derived/verified expectations in §4 exactly, including the two verified exception types (golden 4) and the verified round-1 bid vector (golden 1).
- **Parity (required per "never reimplement").** For `reference_baseline`: run the identical scripted per-round bid sequence twice — once through the AERead adapter's `step()`, once as a direct call sequence against upstream's own `waterAllocation` instance driven by the same driver code path outside the kernel — and require byte-identical terminal `balance`/`hp`/`no_drink` per seat and identical winner lists every round. This is the independent-oracle cross-check the real Gate 2 requires (§4): since there is no second implementation to diff against, the "independent" oracle is upstream's own code invoked a second, unmodified time outside the kernel's state machinery — not a reimplementation diffed against itself.
- **Replay.** Serialize the decision log (parsed per-seat integer bids only, no raw text needed since goldens are fully scripted); fold through `step()` offline (zero network, zero subprocess/bridge call — everything is in-process) and require identical per-round state hashes and terminal outcome, and recompute all four leaves. Proves upstream execution is needed only at authoring/parity time for anything beyond replaying already-recorded transitions.
- **Admission-gate unit tests.** Goldens 3 and 4 additionally assert the specific typed failure (`invalid_measurement` vs `malformed_action`) and that no `alympics_wac_terminal_wealth`/`alympics_wac_survival` leaf is emitted for the seat/round in question.
- **Leakage-audit unit test.** Construct one round where seat A's scripted bid differs sharply from seat B's; assert seat B's frozen pre-allocation observation contains no reference to A's bid value.

## 6. Stated limits

- Tonight's corpus is 7 grid cells, not a population sample — an integration gate, same posture as tau3's 18-task pilot and negarena's 6 scenarios, not a claim about scenario coverage.
- Persona identity/requirement/salary is upstream-fixed (no constructor parameter); varying it would require a thin `waterAllocation.__init__` override that never touches `_check_winner`/`_round_settlement`/`success_bid`/`unsuccess_bid` — out of scope tonight, noted for later.
- Upstream is dormant since 2024-05 (last commit in the pinned history); the pin is immutable regardless, but no further upstream fixes should be expected.
- The four scripted policies (`proportional`, `aggressive`, `conservative`, `myopic_need`) are simple deterministic functions of observable state, illustrative of the family's shape, not claimed-optimal or literature-calibrated strategies; their exact constants are finalized at implementation time.
- Per P01's audit verdict, Leaf 1/2 are `baseline_only` comparatives with the opponent panel part of the estimand — never report a wealth or survival result as evidence of a solved policy optimum, and never collapse the four leaves into one scalar.
- `docs/benchmark_qc.md`'s real Gate 2 additionally names an "acceptance envelope" for difficulty stratification (Gate 1 check 4) that this spec does not yet quantify — supply-regime cells (`generous`/`scarce`) are labeled qualitatively, not by a measured, bounded difficulty statistic.
