# negarena adapter — independent adversarial review (Claude / Sonnet 5)

Scope: `git diff origin/main` on `.worktrees/negarena` (branch `zeyu/negarena-adapter`,
10 commits ahead of `origin/main`), read against `docs/negarena_adapter_spec.md` and
`docs/verifier_taxonomy.md`. This is the second review of a cross-model pair; findings
below were independently reproduced against the real pinned upstream checkout
(`/Users/sunzeyu/Documents/econ benchmark/upstream-negarena`, commit
`c447fafd439a20b84cdedeb2f8a85c4fad764745`) and the provisioned bridge venv
(`/Users/sunzeyu/Documents/econ benchmark/bridges/negarena-venv`), not just read from source.

**Verification performed, not just read:**
- Re-ran `aeread_families.negarena.cases.run_author()` into a scratch directory and
  diffed byte-for-byte against the checked-in `cases/negarena/**` — identical (Gate-1
  digest reproducibility holds; no drift, no silent resampling).
- Ran the full bridge-backed suite: `74 passed in 274.12s` with
  `AEREAD_NEGARENA_BRIDGE_PYTHON` exported, `40 passed, 34 skipped` with it unset —
  exactly matching `docs/negarena_adapter_status.md`'s claimed counts.
- Read the real pinned upstream source (`negotiationarena/game_objects/trade.py`,
  `resource.py`, `alternating_game.py`, `negotiationarena/parser.py`,
  `games/ultimatum/game.py`, `games/ultimatum/interface.py`) to check the adapter's
  claims about upstream behavior (trade-key ordering, `check_transaction_legal`,
  `after_game_ends()`'s ultimatum asymmetry, `write_game_state`'s bare re-raise)
  against the actual code, not just its docstrings.
- Reproduced one defect live through `NegarenaPlugin.parse_action`/`legal` (see
  CRITICAL-1 below), not merely through static reading.

## Overall shape (what's genuinely good)

- All five QC Gate-2 goldens are real for both families: each is independently
  exercised structurally (`tests/test_negarena_environment.py`), at the scoring layer
  (`tests/test_negarena_measurement.py`), and — for golden 1 — end-to-end through the
  real scheduler with a sealed `EvidenceStore` plus an independent bridge-driven
  parity check (`tests/test_negarena_harness.py`, `tests/test_negarena_parity.py`).
  None of the five is a copy-paste duplicate; golden 2 (lowball accept), golden 3
  (RED oversells `X`), golden 4 (missing/garbled trade tag), and golden 5
  (no-ZOPA/zero-endowment run to `iteration_cap`) all use materially different
  scripted transcripts and assert materially different outcomes.
- The invalid-action golden's "no protected state changed" claim holds for the
  protected state that actually exists in this design: resources are static JSON
  read from `family_case["scenario"]` and are never mutated by `step()`; the only
  place a payoff gets computed is `measurement.score_seat_outcome`'s call to
  `bridge.settle(...)`, and `test_score_seat_outcome_never_touches_the_bridge_for_an_invalid_termination`
  (`tests/test_negarena_measurement.py:170-184`) passes `bridge=None` and asserts the
  short-circuit fires before any bridge call — a real, not merely asserted, proof that
  invalid/malformed terminations never reach settlement. `step()` also hard-sets
  `next_phase_id=None` on an invalid action (`environment.py:361-369`), so the episode
  cannot silently continue past it either. (Caveat: see CRITICAL-1 — this guarantee
  only covers what actually gets *routed into* the invalid path.)
- Verifier declarations are legitimate against both the taxonomy and the kernel's own
  enforced enums, not fabricated: `verifier_family="comparative"` +
  `reference_kind="head_to_head"` and `verifier_family="rule_constraint"` +
  `reference_kind="constraint_satisfaction"` are both real entries in
  `src/aeread/shared_runner/measurement.py`'s `_REFERENCE_KINDS`, and
  `measurement_kind="comparative_or_human_judged"` is a real `MeasurementDeclaration`
  enum value (`src/aeread/shared_runner/schemas.py:279-282`). Nothing judge-dependent
  is declared deterministic — there genuinely is no judge/LLM-scored component in
  either leaf; both leaves reduce to a pure function of a transcript
  (`after_game_ends()`, delegated, never reimplemented) or a pure predicate over the
  terminal reason. `evaluation_class="deterministic"` for the `comparative` family is
  legal per the kernel's own `VerifierSpec.__post_init__` (only `rater_judge` is
  restricted to `judge_dependent`), and matches the taxonomy's explicit statement that
  evaluation mode is orthogonal to verifier family (`docs/verifier_taxonomy.md` §2.2,
  §6).
- No derived field is dressed up as independent confirmation: the parity harness's
  "upstream_direct" side (`parity.py::_run_upstream_direct` →
  `NegarenaBridge.replay_transcript` → upstream's own `write_game_state`/`game_over`/
  `after_game_ends()` loop) is a genuinely different code path from the adapter's own
  `step()` + `NegarenaBridge.settle`'s two-synthetic-entry shortcut
  (`negarena_bridge_driver.py::_op_settle` vs. `_op_replay_transcript`) — confirmed by
  reading both driver functions; a match is real evidence, not a tautology.
- Replay genuinely re-executes rather than re-reading a cached result: `replay.py`'s
  `RecordedResponseSource` only replays raw scripted text; `NegarenaPlugin.parse_action`/
  `legal`/`build_scorer` are exercised again for real (bridge subprocess calls happen
  again), and `score_replayed_episode` recomputes both leaves from the *replayed*
  `final_state`/`terminal`, not from the original run's envelopes. The
  status doc's own "Known limits" section honestly documents that this means replay
  still spawns bridge subprocesses (contradicting the spec's literal "zero
  bridge-venv call" wording) and narrows the guarantee to "zero further *provider*
  (model) calls" — this is a disclosed, defensible correction, not a hidden gap.
  `tests/test_negarena_harness.py::test_replay_of_a_reordered_recording_surfaces_as_a_scheduler_contract_error`
  and `::test_recorded_response_source_rejects_phase_seat_mismatch` both confirm a
  reordered/truncated recording is rejected, not silently replayed.
- Gate-1 corpus admission is real: `content_sha256` is stable and reproducible
  (verified independently above), case IDs are dot-separated/lower-case/colon-free and
  actually enforced by the kernel's `is_exportable_id` grammar
  (`tests/test_negarena_cases.py::test_case_id_grammar_rejects_a_naive_colon_joined_id`),
  and `author_all_cases()` raises on a duplicate `case_id` (`cases.py:297-298`).

## CRITICAL

**1. Malformed-response detection only actually works for the trade tag; a response
missing any other required tag (`<message>`, `<player answer>`, `<my resources>`,
`<reason>`, `<move>`/`<proposal count>`) is silently accepted as a normal, legal,
non-terminal turn instead of being flagged `malformed_action`.**

- `environment.py:308-316` (`NegarenaPlugin.parse_action`) checks only *key presence*
  in the parsed `public` dict:
  ```python
  if "message" not in public or "player answer" not in public or "newly proposed trade" not in public:
      return ParseResult.failure("malformed_action")
  ```
- Upstream's own `get_tag_contents` (`negotiationarena/utils.py:33-38`) uses
  `str.find()` for the tag boundaries; when a tag is absent, `find()` returns `-1` for
  both start and end, and the subsequent slice does **not** raise — it returns an
  arbitrary substring of the raw response. Every upstream parser
  (`ExchangeGameDefaultParser`/`BuySellGameDefaultParser`/`UltimatumGameDefaultParser`)
  unconditionally does `ms.add_public(TAG, value)` for every tag regardless of whether
  `value` is meaningful, so the key is *always* present in `public` — the adapter's own
  "key not in public" check can therefore never fire for any tag except the trade tag,
  whose *value* undergoes further hand-parsing (`parse_proposed_trade`) that does
  raise on garbage input. Upstream's real game loop (`AlternatingGame.write_game_state`,
  `negotiationarena/alternating_game.py:69-78`) does nothing beyond
  `self.game_interface.parse(response)` either, so this is not an artifact of the
  bridge driver — the same silent-acceptance would happen inside upstream's own
  `runner/*.py` scripts too.
- **Reproduced live**, not just read (see the exact script and output below): a
  `buy_sell` response with a well-formed `<message>`/`<newly proposed trade>`/`<my
  resources>` but *no* `<player answer>` tag at all parses through
  `NegarenaPlugin.parse_action` with `parsed.ok == True`, and
  `parsed.action["public"]["player answer"]` is populated with a garbage substring of
  the surrounding response (`'/message>\n<newly proposed trade> ... <proposal count> 1 </proposal count'`
  in the repro). `NegarenaPlugin.legal(...)` for the same action returns
  `legality.legal == True`. Because this garbage string is not `"ACCEPT"`/`"REJECT"`,
  `step()` (`environment.py:384-394`) falls through to "continue the game" exactly as
  if a normal `"PROPOSAL"` turn had been played — the malformed input is never routed
  into the `invalid_measurement`/`malformed_action` path, is never excluded from
  scoring, and (if it happened to be the pre-accept turn) its garbage
  `"newly proposed trade"` value would be executed by `bridge.settle()` as if it were
  a legitimate proposal.
- **Failure scenario:** any real policy under evaluation (this benchmark's actual
  purpose — the scripted goldens are only a fixture) that emits a response missing
  one tag — a very common LLM formatting slip, e.g. forgetting `<player answer>` or
  truncating before it — is scored as a completed, ordinary negotiation turn with
  corrupted `"player answer"`/`"message"` content instead of being caught as
  `malformed_action` per spec section 3's explicit invariant ("the harness must catch
  this at the seat boundary ... never ... silently substitute a default action"). This
  directly contradicts the QC-Gate-2 claim golden 4 is supposed to establish, and the
  gap is invisible to the current test suite because every scripted transcript in the
  corpus happens to supply every tag except (intentionally) the trade tag.
- This is not a spec-scope question — `environment.py`'s own code contains a check
  that was clearly *intended* to catch exactly this ("message"/"player answer"
  presence), it is simply written in a way that can never fire given upstream's tag
  parser's actual behavior. A tag-presence check needs to operate on the *raw response
  text* (e.g. verifying `<tag>...</tag>` actually appears) rather than on the
  already-parsed `public` dict, or the bridge driver needs to detect and report
  `find() == -1` for any of the required tags before calling `parser.parse()`.

Reproduction (run against the real bridge venv and the real adapter code, exactly as executed for this review):

```python
from pathlib import Path
import json
from aeread_families.negarena.environment import NegarenaPlugin
from aeread_families.negarena.negarena_bridge import NegarenaBridge

UPSTREAM_ROOT = Path("/Users/sunzeyu/Documents/econ benchmark/upstream-negarena")
bridge = NegarenaBridge.discover(UPSTREAM_ROOT)
plugin = NegarenaPlugin(upstream_root=UPSTREAM_ROOT, bridge=bridge)
case = json.loads(Path("cases/negarena/buy_sell/negarena.buy_sell.0.json").read_text())
family_case = plugin.validate_payload(case["payload"])
phase = plugin.phases(family_case)[0]
state = plugin.initial_state(family_case, None)

text = (
    "<message> hi </message>\n"
    "<newly proposed trade> Player RED Gives X: 1 | Player BLUE Gives ZUP: 40 </newly proposed trade>\n"
    "<my resources> X: 1 </my resources>\n"
    "<my goals> goal </my goals>\n"
    "<reason> r </reason>\n"
    "<proposal count> 1 </proposal count>"
)  # note: no <player answer> tag at all
parsed = plugin.parse_action(family_case, state, "red", phase, {"response": text})
assert parsed.ok is True   # expected malformed_action, got a clean parse
legality = plugin.legal(family_case, state, "red", phase, parsed.action)
assert legality.legal is True  # a malformed response is now a "legal" ordinary turn
```

## WARNING

**2. Ultimatum's per-seat outcome reduction is asymmetric in upstream itself (RED's
`player_outcome` is its absolute final holdings, BLUE's is a *delta* from BLUE's own
initial holdings), the adapter passes this through unchanged, and nothing guards
against a future corpus case where the asymmetry would actually bite.**

- `games/ultimatum/game.py`'s `after_game_ends()` (upstream, read directly):
  ```python
  outcome = [(final - initial) for initial, final in zip(initial_resources, final_resources)]
  outcome[0] = final_resources[0]   # RED overwritten to an absolute value; BLUE stays a delta
  ```
- `negarena_bridge_driver.py::_outcome_json` and `measurement.py::native_outcome_value`
  both pass this straight through (correctly, per the "never reimplement settlement"
  rule) with no correction.
- It is harmless for **tonight's** corpus only because every authored
  `negarena.ultimatum.*` case (`cases.py:149-166`, `_ultimatum_payload`) gives BLUE a
  zero starting `Dollars` balance, so delta == absolute for BLUE in every shipped case.
  `environment.py::validate_payload` (lines 173-177) does not check this — it accepts
  any non-negative integer starting resources for BLUE — so a future scenario-grid
  edit that authors an ultimatum case with a nonzero BLUE starting endowment (a
  perfectly natural variant to want to add) would silently make leaf 1's "own_value"
  for BLUE a delta while RED's is an absolute value, i.e. two numbers under the same
  `comparative`/`head_to_head` estimand that are not comparable, with no error, no
  test failure, and no `invalid_measurement` anywhere to catch it.
- This is honestly disclosed in `docs/negarena_adapter_status.md`'s "Known limits"
  section, which is why this is WARNING rather than CRITICAL — but disclosure in a
  status doc is not a runtime guard, and nothing stops a future scenario-grid PR from
  reintroducing it silently. Worth either a `validate_payload` check
  (reject/flag a nonzero BLUE ultimatum endowment, or record which reduction rule
  applies as leaf metadata) or at minimum a code comment at
  `negarena_bridge_driver.py:100-104` pointing back at this specific risk (currently
  only `measurement.py`'s docstring and the status doc mention it).

## SUGGESTION

**3. Dangling cross-reference:** `cases.py:265-271`'s comment says review the
"Deviations from the original spec text" note in `docs/negarena_adapter_spec.md` for
why `"curated"` was chosen over `"aeread_authored"`. No such heading or literal phrase
exists anywhere in `docs/negarena_adapter_spec.md` or `docs/negarena_adapter_status.md`
(checked via `grep`); the actual explanation lives under section 1's unlabeled
"Correction (found during implementation)" bullet. Low-cost fix: point at the real
section, or add the referenced heading.

**4. Spec/implementation gap in the declared integrity layer:** spec section 2 states
`measurement_validity` "additionally checks: parseable scripted response (tag schema),
in-bounds trade ..., and iteration-count/turn-alternation replay consistency"
(`docs/negarena_adapter_spec.md:169-171`). In the actual code, `measurement.py` only
ever emits a `ValidityReport("invalid", ...)` for the two termination reasons
(`malformed_action`/`invalid_measurement`) already produced by `parse_action`/`legal`;
there is no separate, independently-reported check anywhere that verifies
"iteration-count/turn-alternation replay consistency" as its own named validity
signal — that invariant currently holds only *implicitly*, via the phase graph's
`next_phases` wiring (`environment.py:212-235`) and the scheduler's own bookkeeping,
never as a check with its own pass/fail status a consumer of the receipt could
inspect. Not a scoring bug (the invariant does hold), but the taxonomy-facing spec
text promises more granular, itemized admission evidence than the leaf declarations
actually surface.

## Summary

- CRITICAL: 1 (malformed-action detection bypassable for non-trade tags — demonstrated live)
- WARNING: 1 (ultimatum outcome-reduction asymmetry has no runtime guard for future corpus growth)
- SUGGESTION: 2 (dangling doc cross-reference; measurement_validity claim broader than what's implemented)

All five QC Gate-2 goldens are genuine and non-duplicated for both families; Gate-1
corpus admission (digests, dedup, no silent resampling) is real and independently
reproduced; the verifier declarations are legitimate against both the taxonomy and the
kernel's enforced schema, with no judge-dependent component mislabeled deterministic
and no derived field dressed up as independent confirmation; replay genuinely
re-executes rather than re-reading a cache. The one CRITICAL finding is a real,
reproduced gap in the adapter's own malformed-response admission gate that the current
scripted-golden corpus cannot expose (every golden happens to supply every tag except,
intentionally, the trade tag) but that will matter as soon as this adapter scores
output from an actual policy rather than a hand-written script.
