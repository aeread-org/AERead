# Implementation specification — `negarena` adapter for the AERead shared-runner kernel

**Scope.** Wrap two upstream `NegotiationArena` (`vinid/NegotiationArena`, MIT) scenarios pinned at
commit `c447fafd439a20b84cdedeb2f8a85c4fad764745`: `buy_sell_game` (bilateral price negotiation,
real-life grounding) and `ultimatum` (`MultiTurnUltimatumGame`, multi-round split-the-resource).
`trading_game` is stretch and not covered here. Family name inside AERead is `negarena`; "upstream"
always means the pinned checkout. Per the problem-bound audit (`docs/problem_bound_case_audit.md`,
row P17), this is a **comparative, opponent-dependent** measurement: utilities are known exactly,
but win/gain depends on the paired opponent, so opponent identity and pairing are part of the
estimand, not incidental run configuration.

**Governing facts** (verified in recon; do not re-derive):

- Upstream ships **no static task corpus**. Scenarios are constructed programmatically
  (`player_goals`, `player_starting_resources`, `iterations`) via Python calls — same situation as
  `housing_v1` (see `cases/README.md`: "generated; no static JSON fixtures"), not like `tau3_retail`'s
  imported `tasks.json`. AERead therefore authors the scenario grid; upstream owns only the game
  mechanics and settlement math applied to it.
- `negotiationarena/game_objects/{resource,valuation,trade,goal}.py` are pure dataclass/arithmetic
  (`Resources.__add__/__sub__`, `Valuation.value`, `Trade.execute_trade`, `Goal.goal_reached`) — no
  I/O, no randomness. `BuySellGame.after_game_ends()` / `MultiTurnUltimatumGame.after_game_ends()`
  (in `games/{buy_sell_game,ultimatum}/game.py`) call only this arithmetic and are likewise pure.
- **But none of these modules import cleanly in isolation.** `negotiationarena/utils.py` does
  `from negotiationarena.agents import ChatGPTAgent, ClaudeAgent` at module scope, and
  `negotiationarena/agents/__init__.py` unconditionally imports `chatgpt.py` (`import openai`),
  `claude.py` (`import anthropic`), and `llama2.py` (`import openai`). `resource.py` itself imports
  `negotiationarena.utils.text_to_dict`, and every game module imports `negotiationarena.utils`
  directly. Importing *any* of the above — including the "pure" arithmetic modules — therefore
  requires `openai` and `anthropic` importable, even though no key is ever read and no network call
  is ever made. This is an upstream fact, not an AERead design choice (ledger: `ledger_entries/negarena.md`).
- `AlternatingGame.run()` (`negotiationarena/alternating_game.py`) is the turn loop: alternate
  `players[turn].step(message)` → parse → append to `game_state` → check `game_over()` → on true,
  call `after_game_ends()` and stop; else flip `turn` (`0 ↔ 1`). Two single-actor seats, strict
  alternation, self-contained per-turn text action — the same shape as tau3's phase graph, mapped
  onto AERead's **Mode B** (turn-based, single eligible actor per phase, no environment seat).
- `Trade.from_string` calls Python `eval()` on the trade text; `write_game_state` wraps parsing in
  `try/except` that **re-raises** on failure — upstream has no in-band malformed-action recovery
  (unlike tau2's tool-error path). `execute_trade` never calls the sibling
  `Resources.check_transaction_legal` / `Trade.can_offer`/`can_accept` methods — upstream itself does
  not gate a trade proposal against the offering seat's actual holdings before executing it. Both are
  adapter-owned admission gates, not upstream behavior to preserve as "correct."
- Reference scenario (from upstream's own `runner/buysell_main.py` and its shipped
  `example_logs/buysell/1707347676639/`): seller (RED) cost `X:40`, buyer (BLUE) willingness-to-pay
  `X:60`, starting resources `{X:1}` / `{ZUP:1000}`, `iterations=10`. The shipped transcript settles
  at `40 ZUP`; upstream's own recorded outcome is `[0, 20]`. This is used as the parity anchor below.
  `runner/one_shot_ultimatum.py` imports `games.ultimatum.one_shot_ultimatum.game.UltimatumOneShotGame`,
  which **does not exist** at this pin — that runner script is stale; the adapter targets the working
  `games.ultimatum.game.MultiTurnUltimatumGame`, exercised successfully by `runner/ultimatum_main.py`.

---

## 1. Upstream dependency, pinning, and corpus enumeration (Gate 1)

No `docs/benchmark_qc.md` exists in this repo to cite for the Gate-1/Gate-2 contract (see the
ledger); this section states the convention this spec follows, reconstructed from
`tau3_retail_adapter_spec.md` §1/§8 and `refund_external_benchmark_integration.md` §5-6.

- **Pin.** Repository `vinid/NegotiationArena`, commit `c447fafd439a20b84cdedeb2f8a85c4fad764745`,
  license MIT. No release tag; pin is the dereferenced commit only.
- **Execution path: bridge venv**, mirroring `tools/tau2_bridge/`. Upstream's `pyproject.toml`
  declares no `[project]` table (no Python floor); `requirements.txt` pins `openai`, `anthropic==0.5.0`
  (unpinned `openai`), plus `matplotlib`/`streamlit` (webapp/figures only — not imported by anything
  the adapter executes). The blocker is not Python-version skew (unlike tau2) but the ground rule
  against installing `openai`/`anthropic` into the project venv; an isolated
  `bridges/negarena-venv` (provisioned by `tools/negarena_bridge/provision.sh`, same pattern as
  `tools/tau2_bridge/provision.sh`) installs the pinned upstream checkout plus its two SDK deps,
  never touching the project venv. The bridge driver imports upstream's real
  `games.buy_sell_game.game.BuySellGame`, `games.ultimatum.game.MultiTurnUltimatumGame`, and
  `negotiationarena.game_objects.*` unmodified and returns JSON over stdio (tau2 bridge shape),
  so `after_game_ends()`, `Trade.execute_trade`, and `Resources` arithmetic are upstream's own code,
  never reimplemented. Vendoring was rejected: the poisoned-import fact above means a vendor copy
  of the four "pure" files still needs a stub for `text_to_dict` and cannot reach
  `after_game_ends()` (which lives in `games/*/game.py`, not `game_objects/`) without also vendoring
  the class bodies verbatim — strictly more surface than provisioning one venv.
- **Corpus enumeration.** Upstream ships no task bank, so AERead authors the scenario grid and is
  the corpus's provenance owner (`ProvenanceSpec.review_status="aeread_authored"`, not
  `"upstream_pinned"` — the inverse of tau3). Tonight's corpus: **6 scenarios** — 3 per family,
  each a `CaseManifest` (spec `"aeread.case/0.1"`):
  - `negarena.buy_sell.0` — the verified reference scenario above (RED cost 40, BLUE max-pay 60,
    `X:1`/`ZUP:1000`, `iterations=10`). Doubles as the parity anchor.
  - `negarena.buy_sell.1` — thin-ZOPA variant (RED cost 55, BLUE max-pay 60): only a narrow
    agreement region exists.
  - `negarena.buy_sell.2` — no-ZOPA variant (RED cost 65, BLUE max-pay 60): no legal trade can
    benefit both seats; the informative outcome is disagreement, not a low-value deal.
  - `negarena.ultimatum.0` — reference scenario from `runner/ultimatum_main.py` (proposer `RED`
    holds `Dollars:100`, responder `BLUE` holds `Dollars:0`, `iterations=6`).
  - `negarena.ultimatum.1` — low-iteration-cap variant (`iterations=2`, one proposal round only).
  - `negarena.ultimatum.2` — degenerate endowment (`Dollars:0` for both seats): every legal
    proposal is the empty split; agreement is possible but economically inert.
  - Case IDs are dot-separated, lower-case, no colons (`is_exportable_id`,
    `src/aeread/shared_runner/schemas.py:57`) — mirrors `tau3.retail.base.<n>`.
- **Content digest.** `content_sha256` over the canonicalized manifest (`family_id`, scenario
  parameters, `iterations`, seat roles, upstream pin) — computed once by the importer, checked
  twice-run-identical (parity check analogous to tau3's P1), same as every other family.

## 2. Verifier declaration (per `docs/verifier_taxonomy.md`)

Two separate leaves; `composition_kind` fixed to `"leaf"` — no cross-seat or cross-scenario scalar.

**Leaf 1 — `negarena_seat_outcome` (primary).** `measurement_kind: comparative_or_human_judged`,
`verifier_family: comparative`, `reference_kind: head_to_head` (§6 of the taxonomy: "evaluate against
a declared opponent, field, or matchup distribution" — exactly the P17 audit's `baseline_only`
verdict). Evaluation mode is **deterministic calculation**: given a complete two-seat transcript,
`after_game_ends()` is a pure function, so scoring itself has no stochastic estimator layer even
though the underlying capability question is comparative. Reported per seat, native units (ZUP /
resource-valuation units), `direction: higher_is_better`, no fixed target — a win against one paired
opponent is not a capability score (taxonomy §6). The opponent's identity, seat role, and pairing
rule are recorded in the case/cell manifest, not just the run config, per the audit's explicit
instruction to treat pairing as part of the estimand.

```yaml
verifier_id: negarena_seat_outcome_v1
measurement_kind: comparative_or_human_judged
verifier_family: comparative
reference_kind: head_to_head
input_scope: trajectory        # full transcript needed: proposal history + final accept/reject
direction: higher_is_better
units: native_valuation
determinism: deterministic
composition: leaf
cluster_mapping: task_instance  # one scenario x one seat-pairing
opponent:
  seat_role: string             # "RED" | "BLUE" (buy_sell) or proposer/responder (ultimatum)
  policy_id: string              # versioned identity of the paired seat's policy
  pairing_rule: fixed_pairing_v0 # tonight: one declared opponent per case, not a field/panel
implementation:
  package: aeread_families.negarena
  upstream_commit: c447fafd439a20b84cdedeb2f8a85c4fad764745
```

**Leaf 2 — `negarena_agreement_reached` (diagnostic).** `measurement_kind: property_or_answer`,
`verifier_family: rule_constraint`, deterministic predicate over the terminal state: did the episode
end via an in-band `ACCEPT`/`REJECT` sentinel, or via `iteration == iterations` with no resolution
(upstream's fallback branch in `game_over()`)? Reported separately so a degenerate no-agreement
episode is never silently averaged into the payoff leaderboard as a "loss" (taxonomy §9:
"an invalid or missing observation must not be scored as ... a dominated policy").

`measurement_validity` (integrity layer, not a capability score) additionally checks: parseable
scripted response (tag schema), in-bounds trade (adapter-owned `check_transaction_legal` gate, see
§3), and iteration-count/turn-alternation replay consistency.

## 3. Adapter boundary (mirrors `refund_external_benchmark_integration.md` §4)

**Upstream owns:**
- game-object arithmetic (`Resources`, `Valuation`, `Trade`, `Goal` subclasses);
- the turn-alternation rule and termination condition (`game_over()`);
- settlement computation (`after_game_ends()`), executed via the bridge, never reimplemented;
- the scripted-response tag grammar the parsers expect (`<message>`, `<player answer>`, `<newly
  proposed trade>`, etc.) and the parser classes themselves.

**AERead owns:**
- resolution of the authored scenario grid into an immutable `CaseManifest` (§1) — upstream has no
  corpus to resolve *from*, so AERead is provenance-first here, uniquely among the families that use
  a bridge;
- the phase graph (Mode B: two single-actor phases, strict alternation, self-loop-free — upstream's
  turn never re-enters the same seat mid-decision, unlike tau3's assistant self-loop) and one logical
  action = one parsed scripted/agent response;
- the **trade-legality admission gate** upstream itself skips: before executing an `ACCEPT`, call
  upstream's own `Trade.can_offer`/`can_accept` (delegated, not reimplemented) against the offering
  seat's current `Resources`; a violation is `invalid_measurement`, never a scored negative payoff;
- the **malformed-response catch**: upstream's `write_game_state` re-raises on an unparseable
  response (`eval()` failure in `Trade.from_string`, missing tag); the harness must catch this at the
  seat boundary and record `malformed_action` / `outcome_unknown`, never let the episode process die;
- canonical events, visibility, evidence, replay, and receipts (portable records, unchanged from the
  portability contract);
- typed measurement declarations (§2) and opponent/pairing metadata.

No native `negarena_v1` is proposed; this stays a thin bridge over pinned upstream mechanics, same
posture as the refund integration's stance on `tau3_retail` (§10 of that doc).

## 4. QC Gate-2 goldens (concrete, `buy_sell_game`; `ultimatum` mirrors the same five shapes)

1. **Successful.** `negarena.buy_sell.0`, scripted 8-turn transcript reproducing upstream's own
   shipped `example_logs/buysell/1707347676639/` verbatim (proposals `50→30→45→35→42→38→40`, then
   `ACCEPT`). Expected leaf 1: `{RED: 0, BLUE: 20}` (matches upstream's own recorded
   `player_outcome`); leaf 2: `agreement_reached=true`.
2. **Valid-but-poor.** Same scenario; RED scripted to `ACCEPT` BLUE's opening lowball offer
   (`ZUP:20`) on turn 2 — fully legal, parses cleanly, completes normally, but RED's outcome is
   `v({X:-1, ZUP:20}) = -20` (a real loss below cost) against BLUE's `40`. Exercises "legal action,
   bad outcome" without touching the admission gates.
3. **Invalid-unauthorized.** RED (holds only `{X:1}`) is scripted to propose
   `Player RED Gives X: 5 | Player BLUE Gives ZUP: 100` — a trade RED cannot legally offer. Upstream
   itself would execute this without complaint (see governing facts); the adapter's delegated
   `can_offer` check must catch it and mark the episode `invalid_measurement` before any
   `after_game_ends()` call, rather than let a negative resource count masquerade as a completed
   trade.
4. **Malformed-operational.** Scripted response omits the closing `</newly proposed trade>` tag (or
   supplies non-`eval()`-able trade text). Upstream's `write_game_state` raises; the harness must
   catch it at the seat boundary and record `malformed_action`, not crash the episode process nor
   silently substitute a default action.
5. **Degenerate-reference.** `negarena.buy_sell.2` (no-ZOPA: RED cost 65 vs BLUE max-pay 60), both
   seats scripted to counter-propose without ever `ACCEPT`ing through all 10 iterations. `game_over()`
   fires on `iteration == iterations`; `after_game_ends()`'s non-ACCEPT branch leaves
   `final_resources = initial_resources`, so leaf 1 is `{RED: 0, BLUE: 0}` — a technically-computed
   but information-free comparative result, flagged by leaf 2 (`agreement_reached=false`) rather than
   read as "both seats tied at zero skill."

Ultimatum analogues: successful = reference scenario reaching `ACCEPT`; valid-but-poor = responder
accepts a near-zero split; invalid-unauthorized = proposer offers more `Dollars` than held;
malformed-operational = malformed `<move>`/`<player answer>` tag; degenerate-reference =
`negarena.ultimatum.2` (zero endowment on both seats).

## 5. Test plan

- **e2e.** Each of the 10 goldens (5 × 2 families) driven through the Mode B phase graph with
  Scripted `Agent` subclasses (subclass of `negotiationarena.agents.agents.Agent`, never
  `ChatGPTAgent`/`ClaudeAgent` — no key touched); assert leaf 1/leaf 2 values match the hand-derived
  expectations in §4 exactly.
- **Parity (bridge-executed, required per the "never reimplement" rule).** For golden 1 in each
  family: run the identical scripted transcript twice — once through the AERead adapter (kernel-side
  `step()`), once as a direct bridge call to upstream's own
  `BuySellGame(...).after_game_ends()` / `MultiTurnUltimatumGame(...).after_game_ends()` — and require
  byte-identical `player_outcome`. This is the component-level parity gate (mirrors tau3 §8 P2-P4,
  minus the judge component negarena has none of).
- **Replay.** Serialize the decision log (parsed scripted actions only, no raw provider payload
  needed since goldens are fully scripted); fold through `step()` offline (zero network, zero
  bridge-venv call) and require identical turn sequence, identical terminal `game_state`, and
  identical leaf recomputation. Proves the bridge is needed only at authoring/parity time, not at
  every replay.
- **Admission-gate unit tests.** Goldens 3 and 4 additionally assert the specific typed failure
  (`invalid_measurement` vs `malformed_action`) and that no `negarena_seat_outcome` leaf is emitted
  for either.

## 6. Stated limits

- Tonight's corpus is 6 scenarios (3 buy_sell + 3 ultimatum), not a population sample — an
  integration gate, same posture as tau3's 18-task pilot, not a claim about scenario coverage.
- `trading_game` (resource-exchange, multi-item) is out of scope tonight; its `game_objects` reuse
  is expected to be direct, but its interface/prompt code is unread.
- The bridge venv is required even for the "pure" arithmetic modules (see governing facts); there is
  no zero-dependency import path into any upstream negarena code at this pin.
- `is_exportable_id`'s legal `visibility_policy` / `SeatSpec.role` vocabulary for a two-seat
  adversarial (not customer-service) dialogue is unconfirmed — same open question tau3 already
  raised (its UNRESOLVED Q3); not re-litigated here.
- Upstream's own completeness marking is unreliable: the top-level README's status table marks
  Ultimatum "not done," but `games/ultimatum/game.py` is complete, working code exercised by
  `runner/ultimatum_main.py` at this pin — this spec trusts direct code inspection over the README.
- No judge-dependent or LLM-scored component exists in either scenario; both leaves are fully
  deterministic given a transcript, so no judge-provenance fields are needed in `VerifierSpec`.
