# Triage — Codex adversarial review (`docs/alympics_review_codex.md`)

This pass independently re-reads the code each of the 9 findings names (the
Codex report is a reviewer summary, not a per-finding transcript, so each
bullet below is investigated from its one-sentence description plus its
cited file:line ranges). Classification is based strictly on what the code
does, verified by reading it and, where useful, by executing it against the
real pinned upstream checkout at
`/Users/sunzeyu/Documents/econ benchmark/upstream-alympics` — never on the
reviewer's say-so. All 9 findings are family-local (`environment.py`,
`measurement.py`, `replay.py`, and this family's own test files); none touch
`src/aeread/shared_runner/`, so none are routed to the runner defect ledger.

**Result: 9 CONFIRMED, 0 REFUTED, 0 OUT_OF_SCOPE.**

All 94 tests in this family currently pass (verified:
`pytest tests/test_alympics_wac_{environment,measurement,harness,parity,replay,cases}.py`
→ `94 passed`). Every finding below is a gap those 94 tests do not exercise.

---

## Finding 1 — Agent observations differ materially from upstream (balance excludes current salary credit; prior public auction history omitted)

**Cited:** `environment.py:497-526`.

**Read:** `AlympicsWacPlugin.observe` (`environment.py:497-527`) returns
`player_state["balance"]` straight from `state["players"][seat_id]`, which
is the balance **carried over from the previous round's settlement** —
`step()` only calls `_delegate_round` (which runs upstream's real
`run_single_round`, whose step 1 is `self._get_salary()`) *after* every
seat's bid for the round has already been collected via `observe`/
`parse_action`. Verified against the real pinned upstream
(`upstream-alympics/src/waterAllocation.py:150-171`): `run_single_round`
calls `_get_salary()` **first**, then `execute_bidding()` (which embeds
`get_status()` — the post-salary balance — into the very prompt the agent
bids from). So upstream's real agent sees this round's salary already
credited before deciding its bid; the adapter's agent sees last round's
post-settlement balance, one salary payment short, every round including
round 1 (`STARTING_BALANCE` with no round-1 salary at all).

Separately, `observe`'s returned dict
(`seat_id, requirement, daily_salary, balance, hp, no_drink,
maximum_health, round_id, rounds_total, supply`) carries no information
about any prior round's settlement — no other seat's bid, no past winners,
no past status broadcast. Upstream's own `run_single_round` step 6
(`round_results_prompt`) appends exactly that to **every surviving
player's own conversation history** each round, so a real upstream agent's
context accumulates the full public settlement record; the adapter's
per-round scratch `waterAllocation` instance (`_delegate_round`, fresh
`wa_module.waterAllocation(...)` every round) never carries any player's
`history` across rounds, and `observe`'s payload has no field for it either.

**Verdict: CONFIRMED.** Both sub-claims verified directly against the
pinned upstream source. Failure scenario: a real policy playing through
this adapter is deciding every bid with less information than the real
game gives it — a lower balance figure than it should see, and no memory
of who else won past rounds or what the going rate has been — which can
materially change bid sizing (an agent that budgets a fixed fraction of its
observed balance systematically under-budgets by exactly one salary
payment) and is not testable via `parity.py` (which only cross-checks
*settlement* projections — `final_balance_by_seat`, `winners_by_round` —
never what the acting policy is shown before it decides).

---

## Finding 2 — Comparative scorers accept arbitrary, unverified baseline states; `baseline_policy_id` is ignored

**Cited:** `measurement.py:153-162,170-235,559-661`.

**Read:** `_opponent_panel_sha256` (`measurement.py:153-162`) computes the
leaf's `source_sha256` from only `{focal_seat, panel_policy_ids}` —
`baseline_policy_id` never enters the hash. `build_terminal_wealth_leaf`
and `build_survival_leaf` (`measurement.py:170-235`) both accept a
`baseline_policy_id` parameter but **never reference it in the function
body** (grepped the full body of both — the only two occurrences of the
identifier in that range are the parameter declarations themselves, lines
174 and 215). `AlympicsWacScorer.leaves_for_focal_seat` doesn't even pass
`baseline_policy_id` through when it calls `build_leaves`. And
`score_terminal_wealth`/`score_survival` (`measurement.py:559-661`) take
`baseline_final_players`/`baseline_round_log` as plain caller-supplied
mappings and compute `actual - baseline` with **zero check** that those
values came from actually running the declared baseline policy (or any
particular policy at all) on the same supply schedule/seed/panel — any
dict shaped like `{seat: {"balance": ...}}` produces `status="ok"`,
`validity="valid"`. Grepped the whole `src/` tree: nothing outside this
family's own tests calls these scorers with a baseline, so no other code
path enforces the missing provenance check either.

**Verdict: CONFIRMED.** Concrete failure scenario: a caller could pass
`baseline_final_players` from a run under `"aggressive"` while the leaf
declares (via its unused `baseline_policy_id` default) that it's comparing
against `"proportional"` — the `ReferenceSpec.source_sha256` would be
identical either way (it never encodes which baseline ran), and the
envelope would report `status="ok"` with no trace of which baseline was
actually used. This is exactly "a status reported without the comparison
that would justify it": the comparative claim's whole meaning rests on the
baseline being the declared one, and nothing checks that.

---

## Finding 3 — Missing `bid_legal` evidence silently passes as legal and permits wealth/survival scoring

**Cited:** `measurement.py:390-401,452-477`.

**Read:** `_first_illegal_round` (`measurement.py:390-401`):
```python
for entry in round_log:
    bid_legal = entry.get("bid_legal")
    if not bid_legal or seat not in bid_legal:
        continue
    if not bid_legal[seat]:
        return entry["round_id"]
return None
```
An entry with no `bid_legal` key, or one missing the seat, is skipped —
not distinguished from "checked and found legal." If **no** round in the
log ever carries `bid_legal` evidence for a seat, the loop returns `None`,
so `bid_legality_ok()` returns `True`. `score_bid_legality`
(`measurement.py:452-477`) has the identical pattern for its per-round
`metrics` dict (`if entry.get("bid_legal") and focal_seat in
entry["bid_legal"]`) and returns `status="ok"`, `primary=1.0` when
`_first_illegal_round` finds nothing — i.e. when there is no legality
evidence at all, this scorer reports a **positive legality pass**, and
(since `score_terminal_wealth`/`score_survival` both gate on
`bid_legality_ok()`) leaves 1/2 proceed to `status="ok"` too.

In the real production path, `environment.step` (`environment.py:629-650`)
always populates `bid_legal` for every seat alive that round (verified:
`_check_winner_wrapper` sets it for every `_wa.survival_players` entry
unconditionally, and `RoundOutcome.bid_legal`/the round_log entry copy it
through without filtering), so this branch is not reachable from a live
`run_episode` today. But nothing in `measurement.py` enforces that
invariant — it silently trusts it. `round_log` is exactly the structure
`replay.py` serializes to and reloads from disk
(`RecordedEpisode`/`RecordedDecision`), and nothing round-trips or
re-verifies `bid_legal` through that path either.

**Verdict: CONFIRMED.** Concrete failure scenario: any `round_log` not
produced by today's exact `step()` code — a hand-assembled one (as several
unit tests already do), a future code change that only records
`bid_legal` for winners, or a corrupted/edited on-disk replay record with
`bid_legal` stripped from a round — silently scores as fully legal
(`status="ok"`, `primary=1.0`) rather than `invalid_measurement`, exactly
the "silent skip" shape called out as the likely defect class here. Grepped
`tests/test_alympics_wac_measurement.py` for any test of this branch
(`_first_illegal_round`/missing-evidence path): none exists.

---

## Finding 4 — Dead players retain positive "terminal wealth"

**Cited:** `environment.py:629-650`; `measurement.py:587-605`.

**Read:** `environment.py:629-650` (the `step()` tail) sets
`new_state["players"][seat]["alive"] = False` for each seat in
`outcome.eliminated_this_round` but never touches that seat's `balance` —
upstream's own settlement (`success_bid`/`unsuccess_bid`, verified in
`upstream-alympics/src/waterAllocation.py:30-42`) never zeroes a player's
balance on elimination either (elimination, `waterAllocation.py:203-207`,
only drops the player from `survival_players`; `self.balance` is untouched
by every code path that can run after that). `score_terminal_wealth`
(`measurement.py:587-605`, specifically line 587:
`actual_wealth = float(actual_final_players[focal_seat]["balance"])`) reads
that balance unconditionally — never checks `alive_at_terminal` — and
reports `status="ok"`, no caveat, for a dead seat exactly as for a living
one.

Reproduced concretely: driving `cases/alympics_wac/base/alympics.wac.
reference_baseline.json` through all-`proportional` (the actual golden 1
scenario, `tests/test_alympics_wac_measurement.py::
test_golden_1_successful_reports_positive_wealth_and_full_survival`) via
the real `_run` helper —
```
alex  {'balance': 280, ..., 'alive': False}
bob   {'balance': 300, ..., 'alive': False}
cindy {'balance': 570, ..., 'alive': False}
david {'balance': 480, ..., 'alive': False}
eric  {'balance': 1788, 'alive': True}
```
Four of five seats are dead, every one of them with a substantial positive
balance (accrued because salary is credited every round regardless of
bid outcome, while losing a round costs nothing but HP) — and
`score_terminal_wealth` for `alex`/`bob`/`cindy`/`david` reports
`status="ok"`, `actual_terminal_wealth > 0`, identically to `eric`'s. The
test that runs this exact scenario only asserts `wealth.status == "ok"` and
`> 0`; it never checks `alive_at_terminal`, so it passes without noticing.

One caveat on the reviewer's framing: I could not find any *stated*
"reset-to-zero" rule to contradict — not in the pinned upstream source
(`grep balance waterAllocation.py` shows only init-to-0/salary-credit/
bid-deduction, no elimination-time reset), not in upstream's `README.md`/
`Transparency_FAQ.md`, and not in this adapter's own spec. So "contradicts
upstream's stated rule" is not literally supported — upstream never states
or implements such a rule either. The substantive defect is real
regardless: leaf 1 reports a dead seat's stale, frozen-at-death balance as
an unqualified "terminal wealth" with no distinguishing flag, which can
make a seat that died look wealthier than a baseline seat that survived
and spent money on wins.

**Verdict: CONFIRMED** (the measurement gap; the specific "upstream's
stated rule" attribution in the summary is not supported by anything I
could find, see caveat above).

---

## Finding 5 — Mutable replay records can be reported as `"match"` when no original is supplied

**Cited:** `replay.py:74-154,413-470`.

**Read:** `ReplayReport.status` (`replay.py:424-427`):
```python
@property
def status(self) -> str:
    if self.comparison is not None and not self.comparison.matches:
        return "mismatch"
    return "match"
```
`replay_and_verify` (`replay.py:441-470`) takes `original:
EpisodeResult | None = None`; when `original` is `None` (the module's own
docstring names this as a real, intended mode: "a genuinely offline replay
from a previously-written record, with no original run in memory"),
`comparison` is set to `None` and never computed. `status` collapses that
`None` (nothing was ever compared) into the exact same string, `"match"`,
as a genuinely verified state-hash-level agreement. `RecordedEpisode`
(`replay.py:56-84`) is a plain dataclass round-tripped through
`json.dumps`/`json.loads` with no integrity check (no hash, no signature)
on the recorded decisions, so a record loaded from disk that has been
hand-edited (a bid value changed) replays and re-scores exactly the same
way, and still reports `status="match"`.

Checked test coverage: `tests/test_alympics_wac_replay.py` calls
`replay_and_verify` exactly once (`test_replay_and_verify_end_to_end_
returns_a_matching_report`) and it **always** passes `original=original`
— the `original=None` branch that produces this fabricated `"match"` is
never exercised by any test.

**Verdict: CONFIRMED.** Concrete failure scenario: an operator saves a
`RecordedEpisode` to disk, later reloads it with no original run in memory
(exactly the documented "genuinely offline replay" use case) and checks
`report.status`. They get `"match"` — the same string a real, verified
byte-identical reproduction would produce — with no way to tell from
`status` alone that nothing was actually compared. This is the single
clearest instance of "a status reported without the comparison that would
justify it" among all 9 findings, since it happens under the module's own
documented, intended usage, not an edge case.

---

## Finding 6 — A preloaded generic `waterAllocation` module bypasses the pinned-checkout guarantee

**Cited:** `environment.py:181-214`.

**Read:** `_load_upstream` (`environment.py:181-214`) guards against
importing upstream from **two different roots across successive calls**
(`_UPSTREAM_ROOT_BY_MODULE`, a process-global dict, raises `RuntimeError`
if `bound_root is not None and bound_root != root_key`). It does **not**
check whether `sys.modules["waterAllocation"]` was already populated by
anything else before this function's own first call. Python's `import
waterAllocation` statement, when the name is already in `sys.modules`,
returns the cached object without re-resolving against `sys.path` — so if
anything else in the process (an unrelated package, a stray script, a
leaked global from a prior test) had already bound `sys.modules
["waterAllocation"]` to a module from some other path, `_load_upstream`
silently returns *that* module and records `root_key` as "bound" to it,
with no check of `wa_module.__file__` against `upstream_root` anywhere.

Reproduced directly:
```python
sys.modules["waterAllocation"] = <fake module, __file__="/somewhere/else/...">
_load_upstream(Path(".../upstream-alympics"))
# → returns the fake module unchanged; no error, no warning
```
Grepped `environment.py` and `tests/test_alympics_wac_environment.py` for
any `__file__` check or a simulated pre-populated `sys.modules` case: none
exists.

**Verdict: CONFIRMED.** This is a real gap in the adapter's central
provenance claim ("direct, unmodified import of the pinned upstream
checkout... never a bridge, never reimplemented" — module docstring): the
guarantee is enforced only against *this function's own* prior calls, not
against the process's global module cache, and nothing verifies the
resolved module's actual file path. Narrower in practical likelihood than
the other findings (requires something else in the same process to import
a module literally named `waterAllocation` first), but a one-line defensive
check (`assert Path(wa_module.__file__).resolve() ==
Path(upstream_root, "src", "waterAllocation.py").resolve()`) is exactly the
kind of check this adapter's own stated design principle calls for and
does not have.

---

## Finding 7 — The "full survival" golden never asserts survival; the real reference run eliminates four seats

**Cited:** `test_alympics_wac_measurement.py:213-248`.

**Read:**
`test_golden_1_successful_reports_positive_wealth_and_full_survival`
(`tests/test_alympics_wac_measurement.py:213-268`) runs
`reference_baseline` under all-`proportional`, then for each seat asserts
only `wealth.status == "ok"`, `actual_terminal_wealth > 0`,
`survival.status == "ok"`, `legality.status == "ok"`,
`settlement.status == "ok"`. It never reads `final_players[seat]["alive"]`
or `rounds_survived`, and never asserts anything about the episode's
`termination` reason or how many rounds any seat actually played.

Reproduced the actual run (same helper, same case, same policy):
```
termination: rounds_exhausted at round 20
alex  {'balance': 280,  'alive': False}   (eliminated round 4)
bob   {'balance': 300,  'alive': False}   (eliminated round 4)
david {'balance': 480,  'alive': False}   (eliminated round 4)
cindy {'balance': 570,  'alive': False}   (eliminated round 6)
eric  {'balance': 1788, 'alive': True}
```
Four of the five seats are eliminated (`eliminated_order`:
`('alex', 'bob', 'david', 'cindy')`), only `eric` reaches round 20 alive —
the exact opposite of "full survival" for 4/5 seats — and the test passes
anyway, because none of its assertions would fail regardless.

**Verdict: CONFIRMED.** The golden's own name and docstring intent
("successful... full survival") is not what its assertions check, and is
not what the scenario it drives actually produces. A regression that
broke survival entirely (e.g. every seat dying round 1) would still pass
this test as written, as long as each seat's frozen pre-death balance
stayed positive.

---

## Finding 8 — Malformed-action coverage depends on a test-only hook, unreachable from production `step()`

**Cited:** `environment.py:222-230,298-312,600-608`.

**Read:** `step()`'s real call site (`environment.py:600-608`, current
line numbers) calls `_delegate_round(upstream, round_id=..., supply=...,
alive_seats=..., players_state=..., bids=...)` — **never** passing
`force_malformed`, which defaults to `None` (`_delegate_round`'s signature,
`environment.py:222-230`). With `force_malformed is None`, `_delegate_round`
(`environment.py:298-312`) takes the `else` branch: `payload = {p.name:
p.bidding for p in survivors}; wa.llm.call = lambda message: json.dumps
(payload)` — always valid, complete JSON by construction, since every
seat's bid is already known before `step()` runs. The `KeyError`/
`TypeError` catch that classifies a round as `"malformed_action"` can
therefore never fire from this call site; it is reachable only by passing
`force_malformed="missing_key"`/`"unparseable"` directly to
`_delegate_round`, which only this family's own tests do.

**Verdict: CONFIRMED** — as an accurate reading of the code (verified
independently, same facts on re-reading). **Note:** this is not a new
finding requiring a new fix. It is the same fact already surfaced as
finding M2 in the first (Claude) review pass and recorded in
`docs/alympics_review_disposition.md`, which reached the same conclusion
independently and disposed it as *"fixed (documentation), not a code
defect"* — rearchitecting `step()` to route through upstream's real
freeform-text parser so this branch could fire for real would reintroduce
exactly the prompt-content-sniffing risk this adapter's design deliberately
avoids (module docstring: "never sniffing or reconstructing them from
prompt text"). `docs/alympics_adapter_spec.md` §4/§5/§6 were already
amended to disclose this plainly. No further action item here beyond what
M2 already closed.

---

## Finding 9 — Absence of the developer-specific upstream checkout skips five entire integration-test modules

**Cited:** general (test-suite structure, not one file:line).

**Read:** Five of this family's six test files each duplicate a
`_upstream_root()` helper that defaults to the literal, developer-specific
path `/Users/sunzeyu/Documents/econ benchmark/upstream-alympics` (overridable
via `AEREAD_ALYMPICS_UPSTREAM_ROOT`) and calls `pytest.skip(...,
allow_module_level=True)` if the marker file is absent:
`test_alympics_wac_environment.py`, `test_alympics_wac_measurement.py`,
`test_alympics_wac_harness.py`, `test_alympics_wac_parity.py`,
`test_alympics_wac_replay.py` (`test_alympics_wac_cases.py` is the one
exception — it needs no upstream checkout). `.github/workflows/ci.yml`
contains no reference to "alympics" or "upstream" anywhere — no
provisioning step, no env var set.

Reproduced directly: running the full family's test files with
`AEREAD_ALYMPICS_UPSTREAM_ROOT=/nonexistent/path` yields
**`30 passed, 5 skipped`** — the 30 passes are entirely
`test_alympics_wac_cases.py` (which needs no checkout); the other five
files skip at module level, invisibly, with no failure reported. On this
machine (which happens to have the exact hardcoded path present) the same
files instead run **94 tests, all passing** — this triage's own earlier
verification run. `docs/alympics_adapter_status.md` reports "815 passed, 31
skipped... 0 failed" for the whole repository and attributes every skip to
*other* families' bridge-gated tests — that attribution is itself only
true on a machine where this family's own upstream checkout happens to be
present at that exact path.

**Verdict: CONFIRMED.** In any environment without that literal path
provisioned and without the env var set — which includes this project's
own CI workflow, verified above to set up neither — all of this family's
real environment/measurement/harness/parity/replay coverage silently never
runs, and the suite still reports 0 failures. This is the same failure
shape the project has already named once before (skips hiding unrun
claims): a green CI run for this family's PR would currently prove nothing
beyond `test_alympics_wac_cases.py`'s 30 tests.

---

## Summary

| # | Severity (reviewer) | Verdict | One-line evidence |
|---|---|---|---|
| 1 | High | CONFIRMED | `observe()` balance is pre-salary; no prior-round history in payload — verified against pinned upstream `run_single_round` order |
| 2 | High | CONFIRMED | `baseline_policy_id` unused in leaf body/hash; scorers trust caller-supplied baseline with no provenance check |
| 3 | High | CONFIRMED | `_first_illegal_round` treats missing `bid_legal` evidence as "not illegal"; untested branch |
| 4 | High | CONFIRMED | Reproduced: 4/5 seats dead with positive balance in the actual golden-1 run; `score_terminal_wealth` doesn't gate on `alive` (caveat: no literal "upstream reset-to-zero rule" found anywhere) |
| 5 | High | CONFIRMED | `ReplayReport.status` returns `"match"` whenever `comparison is None`, i.e. whenever no original was supplied — untested branch, and the documented primary offline-replay use case |
| 6 | High | CONFIRMED | Reproduced: a pre-populated `sys.modules["waterAllocation"]` is returned unchecked, no `__file__` verification |
| 7 | Medium | CONFIRMED | Reproduced: golden 1's real run eliminates alex/bob/david/cindy; the "full survival" test never reads `alive`/`rounds_survived` |
| 8 | Medium | CONFIRMED (already addressed) | Same fact as review-1's M2, already disposed as documentation-only, not a code defect |
| 9 | Medium | CONFIRMED | Reproduced: `AEREAD_ALYMPICS_UPSTREAM_ROOT=/nonexistent/path` → `30 passed, 5 skipped`; CI workflow provisions neither the path nor the env var |

**Totals: 9 confirmed, 0 refuted, 0 out-of-scope.**

**Worst confirmed finding:** #5 — `ReplayReport.status` reports the literal
string `"match"` under its own documented, intended "no original in
memory" offline-replay use case, without ever having compared anything,
making the family's zero-provider-call replay/audit mechanism assert a
verification that did not happen.
