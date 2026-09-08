# Implementation Specification — `amazonbarg` adapter for the AERead shared-runner kernel

**Scope.** Wrap *Measuring Bargaining Abilities of LLMs* (Findings of ACL 2024, arXiv 2402.15813;
`TianXiaSJTU/AmazonPriceHistory` @ `834ad9066d0627f0332504d5fa6d236706f2402b`, Apache-2.0) as
family `amazonbarg.bilateral`. Bilateral buyer/seller free-text bargaining over 930 real Amazon
products; real-life grounding (genuine list/high/low Amazon prices, not synthetic values) is the
paper's main strength. Tonight's build is **one category-pair pilot (45 sessions)**; full-corpus
enumeration is declared (Gate 1) but explicitly **not run**. Provider-free: scripted/gold
trajectories only, no network, no API keys, no LLM calls.

**Implementation status.** Built in three milestones. **Milestone 1 (done, 2026-09-02): cases +
environment** — `cases.py` (importer, pins, sanitization, the 45-session pilot), `environment.py`
(phase graph, `AmazonbargPlugin`, registration), and `upstream_shim.py` (§3.1's delegation
mechanism, needed already because the phase graph's own action parsing delegates to
`session.parseReply`). **Milestone 2 (done, 2026-09-02): measurement** — `measurement.py`'s
five leaves (§2), each delegated to upstream's own `eval.py:Metrics`, wired into
`AmazonbargPlugin.build_scorer`, and verified against all five QC Gate-2 goldens (§4) with a
component-parity check (two independent delegated `Metrics` calls on the identical recorded
transcript must agree byte-for-byte). **Milestone 3 (done, 2026-09-02): harness, end-to-end,
replay** — `harness.py`'s `ScriptedAmazonbargHarness` drives full episodes through the real
`run_episode`/`AmazonbargPlugin`/`PluginRegistry` path (never a hand-wired shortcut) and seals
every served decision as a durable, hash-chained `EvidenceStore`; `replay.py` reproduces a sealed
episode's state and score with zero further model/network calls (see
`docs/amazonbarg_adapter_status.md` for the full evidence). One deliberate scope decision versus
the original three-milestone sketch: unlike `tau3_retail` (whose pinned upstream ships a
directly callable `Environment.get_response` entirely outside any AERead code, making a
genuinely separate "upstream_direct" trajectory buildable for `parity.py` to compare against the
adapter path), amazonbarg's only entry point into upstream's negotiation semantics *is*
`session.parseReply`/`utils.Action.ActionParser` — the exact functions `AmazonbargPlugin.step()`
already calls. There is no separate upstream orchestration loop to run side-by-side without
either reimplementing upstream's own `Agent2AgentSession` (which needs live buyer/seller agent
objects that do not exist in a provider-free, tool-free phase graph) or merely calling the same
delegated function twice — which is exactly what milestone 2's component-parity check and
milestone 3's replay-vs-original score-equality check (`tests/test_amazonbarg_replay.py`)
already do. No standalone `parity.py` module was built for this reason; flagged here for
reviewer sign-off alongside §3.1's own flagged deviation.

**Governing facts** (verified by direct exploration of the pinned checkout; do not re-derive):

- The corpus is 18 category JSON files under `data/AmazonHistoryPrice/`; a **session = one
  product** (`product.py:CamelAmazon` builds one single-item `Inventory` per record). Total
  930 records. `codename = f"{category}_{idx+1}"` (already lower-case, `[a-z0-9_-]` only — the
  export grammar's forbidden colon never appears in this corpus).
- Buyer budget and seller cost are derived, not stored raw: `price = max(highest_price,
  list_price)`, `cost = lowest_price`, `budget = price * budget_ratio`. Upstream's own run
  scripts (`run_2stages.sh`, `run_3stages.sh`) pin `budget_ratio = 0.8`; this adapter pins the
  same value. At that ratio the full corpus is **886 mutual-interest (MI, `cost <= budget`) +
  44 conflicting-interest (CI, `cost > budget`) sessions** — verified by re-deriving both
  numbers directly from the 18 files, matching the audit's figures exactly.
- The negotiation protocol has **no tool calls and no environment-side state mutation**. Each
  turn is one free-text LLM reply parsed by a fixed regex grammar (`session.py:parseReply` +
  `utils/Action.py:ActionParser`) into `Thought`/`Talk`/`Action`, where `Action` is one of
  `BUY|SELL|REJECT|DEAL|QUIT` (`+` money/object fields for the first three). The live loop
  (`session.py:Agent2AgentSession.agents_talk_with_action`) enforces **no economic legality
  live** — a `DEAL` below cost or above budget is not blocked at generation time. All legality
  (fake-deal detection, need-matching) and the profit/ratio arithmetic are computed **ex post**
  by `eval.py:Metrics`, which this adapter delegates to rather than reimplements (P20 audit:
  the outcome geometry is bracketed by ZOPA/cost/budget, but there is no hidden-information
  policy optimum to compare against — only comparative and rule-legality claims are honest).
- `utils/Action.py` (parsing) and `product.py` (corpus loading) have **zero third-party
  imports** (`re`/`dataclasses`/`json`/`os` only) and import cleanly today. `eval.py` and
  `session.py` import cleanly *for the functions this adapter needs* once §3 is handled:
  `openai==2.53.0` is already present and its client constructor makes no network call, so only
  `requests`, `jsonlines`, `matplotlib`, `seaborn`, `pandas`, `fire` are missing — all used
  exclusively by code paths (`API.ChatCompletion`, `HistoryManager.save_history_jsonl`,
  `eval_all_jsonl`/plotting) this adapter never calls.

  **Implementation update (milestone 1, 2026-09-02):** this last claim needed one correction,
  found by attempting the import for real rather than assuming it: `api_setting.py` (pulled in
  transitively by `session.py` via `BuyerAgent`/`SellerAgent`) builds `api_pool =
  API(temperature=0.0)` at *module import time*, and `API.__init__` calls
  `openai.OpenAI(api_key='', base_url=...)` verbatim. Against the `openai==2.53.0` actually
  installed in this project's venv, an explicit empty-string `api_key` raises `OpenAIError:
  Missing credentials` *locally* — never a network call, but also before the import that only
  wants `parseReply` can complete. `upstream_shim.py` (§3.1) works around this by temporarily
  substituting a subclass of the *real* `openai.OpenAI` that fills in a placeholder key only
  when the caller passed a falsy one, restoring the original class immediately after the
  delegated import completes; a dedicated no-network test proves construction still never
  touches a socket either way. `utils/Action.py`/`product.py` import exactly as cleanly as
  claimed (verified, not just asserted) — no correction needed there.
- **`max_turns` pin (added in milestone 1, missing from the original draft):** upstream's own
  `run_session.py:main` defaults to `max_turns=6`, and neither `run_2stages.sh` nor
  `run_3stages.sh` overrides it — read from the pinned checkout, never executed, exactly like
  `tau3_retail`'s own `MAX_STEPS` pin. This adapter pins the same value; each episode's
  `CaseManifest.episode.max_logical_actions = 2 * max_turns = 12` (buyer + seller message per
  round, up to 6 rounds).

---

## 1. Pinned source, corpus enumeration, and content digest (QC Gate 1)

| Field | Value |
|---|---|
| repository | `TianXiaSJTU/AmazonPriceHistory` |
| pinned commit | `834ad9066d0627f0332504d5fa6d236706f2402b` |
| license | Apache-2.0 |
| corpus root | `data/AmazonHistoryPrice/` (18 files, listed below) |
| `budget_ratio` (pinned) | `0.8` |
| `max_turns` (pinned) | `6` (upstream `run_session.py:main` default, never overridden) |

The importer (`cases.py`) is declared over every one of the 18 pinned category files
(`automotive.json, baby-products.json, beauty.json, books.json, electronics.json,
health-personal-care.json, home-kitchen.json, industrial-scientific.json, movies-tv.json,
music.json, other.json, patio-lawn-garden.json, pet-supplies.json, software.json,
sports-outdoors.json, tools-home-improvement.json, toys-games.json, video-games.json`) and its
per-session derivation is fixed (`price = max(highest_price, list_price)`, `cost =
lowest_price`, `budget = price * budget_ratio`, one `CaseManifest` per product). Tonight,
`pins.json` records each file's real byte-length and `sha256` (cheap, done for all 18 now, so a
future upstream data revision is caught immediately), but **the per-session `CaseManifest` walk
is declared and not executed for the full 930** — only the 45-session pilot pair (§1.2) is
actually materialized into manifests tonight. The kernel resolver computes each materialized
manifest's `content_sha256` the usual way (over `family_id`/`family_version`/`payload`).

### 1.1 Identifier grammar and the sanitization mapping

`case_id = f"amazonbarg.bilateral.{sanitize(codename)}"`. `sanitize()` is declared as: pass
`[a-z0-9_.-]` through unchanged; replace any other character with `_x{ord(c):04x}_` (reversible
— the inverse table is the identity except at those markers) — with one refinement (codex-review
finding 8): a raw underscore is itself escaped, rather than passed through, whenever the literal
text immediately following it in the input already matches the rest of a genuine marker shape
(`x[0-9a-f]{4}_`), so a codename that happens to already contain marker-lookalike text can never
collide with the escaped form of some other codename. **All 930 upstream codenames in this corpus
already satisfy the export grammar, and none contains such a lookalike substring**, so `sanitize()`
is still the identity function on every case built tonight; the mapping exists and is unit-tested
against synthetic counter-examples (`"café_1"`, `"a:b"`, upper-case, and a literal marker-shaped
input) so a future non-conforming category name does not silently produce a colon-bearing,
otherwise unsafe, or colliding id.

### 1.2 Pilot corpus: one category pair, 45 sessions

Categories **`home-kitchen`** (23 products) and **`toys-games`** (22 products) — chosen because
their sum lands in the requested 40–60 range while still including at least one session of each
interest type: **44 MI + 1 CI** (`toys-games_22`, the DJI Mini 4 Pro drone: `cost=$959.00 >
budget=$864.93`). The other 16 categories' 885 sessions are digested at the file level (§1) but
get no `CaseManifest`, scripted trajectory, or score tonight — no comparative/legality claim is
made about them.

The CI stratum here is `n=1` — enough to exercise the degenerate-reference path (§4, golden 5),
not a powered sample for any CI-specific claim (restated in §6).

## 2. Verifier declarations (families per `docs/research/verifier_taxonomy.md`; field names per the real
`aeread.shared_runner.measurement` contract, not the prose-only names in taxonomy §5.1)

Five leaves, `composition_kind="leaf"` throughout — no composite score is sealed by the kernel.
Every leaf's `evaluation_class="deterministic"` tonight (scripted trajectories, no sampled
trials); `stochastic_estimator` becomes relevant only once a real model policy replaces the
scripted seat (§6).

| `leaf_id` | `verifier_family` | `reference_kind` | Owner | Claim |
|---|---|---|---|---|
| `amazonbarg_deal_authenticity` | `rule_constraint` | `constraint_satisfaction` | **delegated** (upstream `Metrics`) | Deal matches a genuine prior same-type offer and equals the buyer's declared need — upstream's own `wrongAction` semantics, imported verbatim, never reimplemented |
| `amazonbarg_zopa_membership` | `rule_constraint` | `constraint_satisfaction` | **AERead-owned**, computed from delegated `B`/`C`/`D` | Deal price inside `[cost, budget]` when `budget >= cost`; reports `degenerate` (not pass/fail) when no ZOPA exists |
| `amazonbarg_deal_lower_bound` | `objective_reference` | `outcome_support_min` | AERead-owned | `S_min = cost`; realized deal price's position against this bound only |
| `amazonbarg_deal_upper_bound` | `objective_reference` | `outcome_support_max` | AERead-owned | `S_max = budget`; realized deal price's position against this bound only |
| `amazonbarg_bargained_ratio` | `comparative` | `head_to_head` | AERead-owned, delegated arithmetic | Tested seat's `bargained_ratio` vs. the fixed scripted counterpart (opponent identity recorded in the estimand's `validity_domain`, per seat — see below) |

`amazonbarg_deal_lower_bound`/`amazonbarg_deal_upper_bound` are **two separate
`MeasurementLeafSpec`s** (each `VerifierSpec` carries exactly one `ReferenceSpec`, mirroring
`housing.py`'s `_housing_measurement_leaf` pattern) — never one combined
`outcome_support_normalized` leaf, which is not a legal `reference_kind` in the real contract.
Taxonomy §5.1's `support_score = (V - S_min)/(S_max - S_min)` is a **derived** quantity computed
from the two, reported in the parity/analysis layer, never sealed as a third kernel score. Per
§5.1 and the audit brief: this is a **bounded support position, not an attainable optimum** —
there is no feasible-policy witness or certified upper bound on the *unknown optimal bargaining
policy* here, only the ex-post price bracket. No leaf, docstring, or receipt field may describe
`amazonbarg_deal_lower_bound`/`_upper_bound` as an optimality claim.

`amazonbarg_deal_authenticity` and `amazonbarg_zopa_membership` are deliberately two different
checks: the former is **upstream's own** legality definition (a deal that reproduces a real
prior offer and matches need — upstream never checks price-vs-cost/budget); the latter is an
**AERead-added** check over the same delegated `B`/`C`/`D` fields. A below-cost deal that
upstream calls legitimate (§4, golden 3) is exactly the case that motivates keeping these
separate — folding them into one leaf would silently import AERead's own added rule as if it
were upstream's, contrary to `docs/families/tau3-retail/refund_external_benchmark_integration.md` §3's rule against
relabeling a benchmark's own semantics.

`amazonbarg_bargained_ratio` direction is `maximize`, `units="ratio"`. It uses the plain
`comparative`/`head_to_head` path (no `ObjectiveScopeSpec` — that field is only legal on
`objective_reference` verifiers); the scripted counterpart's policy id + version is recorded in
the estimand's `validity_domain` instead, fixing opponent identity as part of the estimand.
Diagnostics (`turns`, `buyer_offer_num`, `seller_offer_num`, raw `wrongAction`) live in this
leaf's `ScoreEnvelope.metrics`, never its `primary`.

**Measurement validity gate:** when the episode terminates via `action_error` (golden 4), the
comparative and both bound leaves are sealed as `ScoreEnvelope(status="invalid_measurement",
primary=None, validity=ValidityReport(status="invalid", reasons=[...]))` — never a computed
zero. `amazonbarg_deal_authenticity` still seals `status="ok"` with a failing `primary`, since
the malformed action *is* the evidence being checked.

## 3. Adapter boundary (mirrors `refund_external_benchmark_integration.md` §4)

**Upstream remains authoritative for:**
- product/session definitions and the price → cost/budget derivation formula;
- the negotiation protocol grammar (`Thought`/`Talk`/`Action` lines, the `BUY|SELL|REJECT|
  DEAL|QUIT` vocabulary, the extraction regexes in `session.parseReply` and
  `utils.Action.ActionParser`);
- deal-legality and profit/ratio scoring (`eval.py:Metrics` — fake-deal detection,
  need-matching, `wrongAction`, `buyer_bargained_ratio`/`seller_bargained_ratio`).

**AERead owns:**
- resolving the pinned category files into `CaseManifest`s with content digests (Gate 1);
- the phase graph (buyer_turn ↔ seller_turn strict alternation, no tool runtime — there is no
  tool-calling surface in this benchmark at all, unlike `tau3_retail`);
- the scripted counterpart policy (an AERead-authored fixture, not upstream code — upstream's
  own CLI-mode `dummyAgent` classes are a constant `[REJECT]` no-op and cannot produce
  deal/no-deal variety; the fixture reuses their exact reply-format contract,
  `Talk: <str>\nAction: [TYPE] ...`, so the shared parser accepts it unmodified);
- `amazonbarg_zopa_membership` and both bound leaves (layered over delegated fields, never
  touching upstream's own arithmetic);
- canonical events, evidence sealing, replay, and receipts.

### 3.1 Delegation mechanism — in-process import shim (no bridge venv, no vendored copy)

Unlike `tau3_retail`, the Python version is not the blocker (upstream targets 3.11 fine); the
only blocker is six packages (`requests`, `jsonlines`, `matplotlib`, `seaborn`, `pandas`,
`fire`) used exclusively by code this adapter never calls. A full second venv (the
`tools/tau2_bridge/provision.sh` pattern) to work around unused imports was judged heavier than
the problem; vendoring a copy of `eval.py::Metrics` would duplicate exactly the class "never
reimplement" most wants delegated. Instead, `upstream_shim.py`: (1) installs minimal stub
modules into `sys.modules` for those six names, **only** for whichever are actually absent
(`openai` is real, installed, unused beyond construction — no stub needed); (2) **(implementation
update, milestone 1)** each stub's attribute access returns an inert placeholder rather than
raising immediately — `api_setting.py` writes a plain (non-`from __future__ import annotations`)
`-> requests.Response` return-type annotation that Python evaluates *eagerly* at
class-definition time, so a stub that raised on every read would make even the intended,
provider-free delegation (`session.parseReply`) impossible to import. Only *calling* a stub
placeholder — the one thing that could otherwise silently fake a real behavioural result —
raises `UpstreamShimMissError`, and the session-scoped counter records exactly those calls, not
bare reads; (3) imports `session.py` (for `parseReply`) and `eval.py` (for `Metrics`) unmodified
from the pinned checkout under these stubs, then removes them from `sys.modules`; (4)
`utils/Action.py` and `product.py` import directly with **no shim** — zero third-party imports
of their own. See `upstream_shim.py`'s own module docstring for the two deviations above (stub
read-vs-call semantics; the `openai` empty-api-key construction gate from the Governing Facts
note above) in full.

A dedicated test asserts the miss-counter is `0` across the entire suite (§5, P2) — turning a
silent behavioral gap into a loud failure the moment upstream code touches a stubbed symbol on
a path this adapter exercises. **This is a deliberate departure from the two patterns named in
this task's ground rules** (isolated venv / vendored copy), flagged here for review;
`bridges/amazonbarg-venv` following `tools/tau2_bridge/provision.sh` is the documented fallback
if a reviewer prefers not to monkeypatch `sys.modules`, even transiently, in adapter code.

## 4. Five QC Gate-2 goldens

All five use real pilot-corpus numbers (`budget_ratio = 0.8`), each isolating one code path.

1. **successful** — `home-kitchen_2` (Shark vacuum; `cost=$95.00, budget=$173.44`). Scripted
   `BUY $120 → SELL $150 → BUY $135 → DEAL $135`. Passes both rule_constraint leaves (matches
   prior offer; `$135 ∈ [95, 173.44]`); comparative ratios ≈0.49/0.51.
2. **valid-but-poor** — `home-kitchen_3` (Calphalon; `cost=$60.99, budget=$103.99`). Scripted
   deal closes at `$61.50` — legal on both rule_constraint leaves, but `seller_bargained_ratio
   ≈ 0.012`: a real, authenticated, in-bracket deal that is comparatively bad for one seat.
3. **invalid-unauthorized** — `home-kitchen_5` (Breville; `cost=$524.97, budget=$599.96`).
   Scripted `SELL $480 → BUY $480 → DEAL $480` (matches the seller's own prior offer exactly,
   so `amazonbarg_deal_authenticity` **passes** — upstream calls this a legitimate deal) but
   `$480 < cost`, so `amazonbarg_zopa_membership` **fails**: the case upstream's own scorer
   does not catch and AERead's added check exists specifically to catch. This golden proves
   scoring-layer detection of an environment-permitted illegal deal, not state-layer
   prevention — no economic legality is live at the state layer (governing fact above), so
   the below-cost `DEAL` genuinely closes and mutates terminal state; only scoring catches it
   after the fact. See golden 4 for the adapter's actual "no protected state changed on
   invalid input" proof.
4. **malformed-operational** — `home-kitchen_4` (Bean Bag). Scripted buyer reply omits the
   `Action:` line entirely; `parseReply` yields `action=''`, `ActionParser` raises
   `RuntimeError("No action in text")`, upstream's own `action_error` path terminates the
   episode after one decision slot. `amazonbarg_deal_authenticity` seals `ok`/fail (evidence:
   the malformed action itself); comparative and bound leaves seal `invalid_measurement`.
5. **degenerate-reference** — `toys-games_22` (DJI drone, the pilot's one CI session:
   `cost=$959.00 > budget=$864.93`). Scripted `BUY $850 → REJECT → ... → QUIT` — the *correct*
   behavior, since no price satisfies both sides. `amazonbarg_zopa_membership` and both bound
   leaves report `degenerate`/`not_applicable` (`S_min > S_max`) rather than a computed number.

## 5. Test plan

- **P1 — Import/digest determinism.** File-hashing run twice over all 18 pinned files →
  byte-identical `pins.json`; the 45-session pilot `CaseManifest` walk run twice → byte-identical
  manifests.
- **P2 — Shim safety.** (a) no socket/HTTP call occurs during shim install or module import,
  including `api_setting.py`'s module-level client construction — an explicit no-network guard
  proves construction-without-use never touches the network; (b) the stub miss-counter is `0`
  after the full adapter test suite runs.
- **P3 — Delegated-scorer determinism.** For all 45 pilot sessions plus the 5 goldens, call
  delegated `eval.Metrics` twice on the identical recorded history (same process and a fresh
  process) and require byte-identical `B`/`C`/`D`/`wrongAction`/`closeADeal` output.
- **P4 — Offline replay.** Rebuild `initial_state` from the pinned corpus, fold each golden's
  recorded raw turn text through `step()` (pure regex parse via the delegated functions, zero
  model/network calls), and assert: transcript hash, terminal condition, and re-derived
  `ScoreEnvelope`s all match the sealed episode record exactly. 5/5 goldens + 45/45 pilot
  sessions once authored.
- **P5 — AERead-owned leaf correctness.** Since `amazonbarg_zopa_membership` and the two bound
  leaves are not upstream code, they get their own hand-verified-arithmetic unit tests (not
  merely parity-with-upstream tests) against each of the 5 goldens.
- **P6 — Sanitization round-trip.** `sanitize()`/inverse on all 930 real codenames (identity)
  plus synthetic non-conforming strings (colon, accents, upper-case) confirms reversibility and
  that today's corpus needing no rewriting is *verified*, not assumed.

## 6. Stated limits

- `budget_ratio` is pinned at the upstream default (`0.8`); no other ratio is explored tonight,
  so MI/CI proportions and all bracket widths are conditional on that one value.
- The CI stratum in the executed 45-session pilot is `n=1` (§1.2) — sufficient to exercise the
  degenerate-reference code path, not sufficient for any CI-specific comparative or bound
  claim; do not report CI-vs-MI comparisons from tonight's pilot.
- The scripted counterpart is a single fixed AERead-authored policy, not a distribution of
  opponents; `amazonbarg_bargained_ratio`'s claim is relative to *that one* opponent identity,
  never a general capability score (`docs/research/verifier_taxonomy.md` §6).
- Only the 45-session pair actually runs; the other 885 are digested at the file level but get
  no `CaseManifest`, trajectory, golden, or score — declared enumeration and executed pilot are
  different, separately labeled claims.
- `amazonbarg_zopa_membership` and the bound leaves are **AERead additions upstream never
  computes or validates**; never report them as "the paper's own headline metric."
- The `sys.modules` shim (§3.1) is a runtime technique, not one of the two patterns this task's
  ground rules named; flagged for reviewer sign-off, documented bridge-venv fallback available.
- No stochastic estimation is declared tonight (`evaluation_class="deterministic"`
  throughout); a real model policy in either seat reintroduces `stochastic_estimator` mode,
  nested replicate seeding, and pass@k conventions, all out of scope tonight.
