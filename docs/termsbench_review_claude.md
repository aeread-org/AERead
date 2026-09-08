# termsbench adapter — second-reviewer read (Claude)

Scope: `git diff` vs `origin/main` for branch `zeyu/termsbench-adapter`
(8 commits, `docs/termsbench_adapter_spec.md` +
`src/aeread_families/termsbench/{kernel,cases,environment,harness,measurement,replay}.py`
+ `cases/termsbench/pilot/*` + `tests/test_termsbench_*.py`). Read-only; no
files edited. Full local test run: `pytest tests/test_termsbench_*.py -q` →
**80 passed**. Independently re-ran the generator twice and diffed every
on-disk pilot case/manifest byte-for-byte against a fresh regeneration (via
`json.dumps` normalization, since Python tuple-vs-list is not itself a content
difference) — all 30 cases plus the manifest matched exactly.

Overall: the adapter is well-engineered and mostly does what its own spec
claims — replay genuinely re-executes (`TermsBenchPlugin.step()`'s
`_step_counterpart` recomputes `kernel.resolve_counterpart_turn` from sealed
draws and raises on divergence; verified this by hand — flipping
`u_accept` after the fact does trigger `SchedulerContractError("... replay
mismatch ...")`), Gate-1 digests are stable and dedup is a hard failure (not
silent resampling), and the verifier declarations mostly follow
`docs/research/verifier_taxonomy.md` correctly (comparative/head_to_head for the
value-axis leaves, rule_constraint/constraint_satisfaction for compliance,
`evaluation_class="deterministic"` per realized/sealed episode is a legitimate
application of taxonomy §2.2/§8's "a stochastic process can still feed a
deterministic verifier" reasoning, not a mislabeling). Two real gaps found,
both defensible with a concrete scenario; no critical defect.

---

## MAJOR

### 1. `termsbench_protocol_compliance`'s reference hash omits the actual IR anchor it claims to pin

`src/aeread_families/termsbench/measurement.py:150-161`

```python
def _case_constants_sha256(payload: Mapping[str, Any]) -> str:
    """Pin "the case's own declared constants" leaf 4 checks against (spec
    section 2): price bounds, agent role/IR anchor, and horizon. ...
    """
    rule_payload = {
        "price_bounds": dict(payload["price_bounds"]),
        "agent_role": payload["agent"]["role"],
        "horizon": payload["horizon"],
    }
    return hashlib.sha256(canonical_json_bytes(rule_payload)).hexdigest()
```

The docstring says the hash pins "price bounds, agent role/**IR anchor**, and
horizon" — but `rule_payload` only includes `agent["role"]` (the string
`"buyer"`/`"seller"`), never `agent["r_a"]` (the numeric reservation value
that is the actual anchor the individual-rationality critical-violation check
in `environment.py:_step_agent` (lines ~408-432) tests against). I verified
this concretely:

```python
_case_constants_sha256({"price_bounds": {"p_min":0,"p_max":200}, "agent": {"role":"buyer","r_a":150.0}, "horizon":10})
_case_constants_sha256({"price_bounds": {"p_min":0,"p_max":200}, "agent": {"role":"buyer","r_a":50.0},  "horizon":10})
# => identical sha256, despite a wildly different IR threshold
```

**Failure scenario:** the `termsbench_protocol_compliance`
`VerifierSpec.reference.source_sha256` exists precisely so a consumer/auditor
can detect "the rule set this leaf was checked against changed." Two cases
that share `price_bounds`/`agent_role`/`horizon` but differ in `r_a` (which
happens routinely — `r_a` is drawn per-seed in `cases.generate_payload`) get
an identical reference hash even though what counts as an IR violation for
each is completely different. A future refactor that silently changes how
`r_a` is drawn (or a corpus-generation bug that clamps/corrupts `r_a`) would
not be caught by anything that relies on this hash to detect a reference
change — it is the one piece of provenance whose whole job is to catch
exactly that class of silent change.

### 2. Golden 3 ("no protected state is touched") is never actually asserted, in either test file

`tests/test_termsbench_measurement.py:281-314` (`test_golden3_invalid_unauthorized_accept_earns_no_credit_but_stays_valid`)
and `tests/test_termsbench_environment.py:186-196` (`test_golden3_accept_without_counterpart_offer_is_agreement_violation`)

Both tests' own docstrings restate the spec's claim
(`docs/termsbench_adapter_spec.md:178`: *"No protected state (price, DB) is
touched"*), but neither test reads `result.final_state` at all — they only
check `result.terminal[...]` (`reason`, `final_price`,
`critical_violations`, `malformed_action_schema`), fields that don't even
include `agent_offers`/`counterpart_offers`/`round`
(`environment.py:terminal()` at lines 518-530 doesn't surface them).

I checked the underlying behavior directly (not just the tests) by running
golden 3's exact scenario and inspecting `result.final_state`:

```
{'round': 1, 'agent_offers': (), 'counterpart_offers': (), 'termination': 'agreement_violation',
 'final_price': None, 'critical_violations': {'price_bound': False, 'individual_rationality': False,
 'invalid_action': True}, ... 'transcript': ()}
```

— so the *implementation* is correct today: `_step_agent`'s invalid branch
(`environment.py:391-401`) returns before any append to
`agent_offers`/`counterpart_offers`/`transcript`, and `round` is never
incremented on an agent-phase transition. But this is exactly the invariant
the golden is supposed to lock in for regression purposes, and as written
neither test would fail if a future edit accidentally started appending to
`agent_offers`/`counterpart_offers` on the illegal-Accept path, or bumped
`round`, or otherwise mutated ledger state before terminating.

**Failure scenario:** someone refactors `_step_agent` (e.g. to unify the
invalid-action and reject paths, or to log the attempted accept into
`transcript` for observability) and, in doing so, appends something to
`agent_offers`/`counterpart_offers`/`transcript` before setting
`agreement_violation`. Every existing test still passes (`reason`,
`final_price`, `critical_violations["invalid_action"]`,
`malformed_action_schema` are unaffected), silently violating the one
invariant ("no protected state is touched") that golden 3 exists to
demonstrate. A one-line addition to either test —
`assert result.final_state["agent_offers"] == ()` /
`assert result.final_state["counterpart_offers"] == ()` /
`assert result.final_state["round"] == 1` — would close this.

---

## MINOR

### 3. `select_pilot_cell_seed`'s docstring overstates what it returns

`src/aeread_families/termsbench/cases.py:250-270`

The docstring says it returns "the smallest candidate seed whose quantile
bin ... equals difficulty_bin." The implementation actually returns the seed
at the *first rank* (i.e. lowest `difficulty_score`) whose computed bin
matches — not the smallest seed value among all candidates that land in that
bin. These coincide today only because `sorted(..., key=score)` is stable and
ties are rare with continuous floats, but the two descriptions are not the
same guarantee. Purely a documentation-accuracy nit; the function is still
deterministic and reproducible either way, and I found no case where the two
readings actually diverge in the committed 30-case pilot.

### 4. `FamilyManifest.measurement.primary_estimand` names a leaf that roughly half the corpus never declares

`src/aeread_families/termsbench/environment.py:96-97` declares
`"primary_estimand": "termsbench_surplus_efficiency"` at the family level,
but per `measurement.py`'s own regime-conditional `build_leaves`, No-deal
cases never produce a `termsbench_surplus_efficiency` leaf at all (only
`termsbench_no_deal_agreement` + `termsbench_protocol_compliance`). This is
consistent with the spec's own framing ("declared only for Overlap regime")
and `resolver.py`'s check only requires the suite's `AnalysisPlan` to know
about the family's `primary_estimand` id (not that every case emits it), so
I don't have evidence this breaks anything today — flagging only because a
suite-level report keyed on "the family's primary estimand" will silently be
empty for the No-deal half of any termsbench corpus unless the
analysis/reporting layer is aware of the regime split, and nothing in
`FamilyManifest` itself documents that split.

---

## What I checked and found clean (no finding)

- **Replay honesty:** `replay.py`'s `RecordedResponseSource` draws no random
  numbers and calls no model; `replay_episode` drives the real scheduler, and
  the actual verification is `TermsBenchPlugin.step()._step_counterpart`
  re-executing `kernel.resolve_counterpart_turn` on the sealed `draws` and
  raising on mismatch — confirmed this fires for a tampered draw
  (`tests/test_termsbench_replay.py:335-356`,
  `tests/test_termsbench_environment.py:267-293`). This is genuine
  re-execution, not "read the log back."
- **Gate-1 corpus admission:** regenerating the pilot corpus twice, and
  regenerating from `cases.py` against the 30 committed on-disk files, is
  byte-identical (verified directly, not just via the existing test).
  `build_pilot_cases` raises `ValueError` on a duplicate `case_id` (hard
  fail, not silent resampling); seed ranges are disjoint per
  `(family, regime)` by construction (`_candidate_seed_base`); 30/30 unique
  seeds and case ids confirmed on-disk.
- **Verifier declarations vs. `docs/research/verifier_taxonomy.md`:** the four leaves'
  `verifier_family`/`reference_kind` pairs are valid combinations under
  `_REFERENCE_KINDS` (`comparative`/`head_to_head` for leaves 1-3,
  `rule_constraint`/`constraint_satisfaction` for leaf 4); nothing
  judge-dependent is mislabeled `deterministic` — there is no `rater_judge`
  leaf at all this cycle, consistent with the spec's stated scope. The
  `evaluation_class="deterministic"` label for a stochastic-kernel opponent
  is a correct application of taxonomy §2.2/§8 (a stochastic process scored
  deterministically per realized/sealed run), reinforced by the fact that the
  harness seeds the counterpart PRNG per `(world_seed, round)` — for a fixed
  seed the counterpart's behavior is itself reproducible, not just
  "deterministic after the fact."
- **`CSE+`/`SafeTerm-` never folded into a `ScoreEnvelope`:** confirmed
  `aggregate_surplus_efficiency_corpus` is a separate, un-sealed
  analysis-layer helper, and that it reports `CSE_plus=None` (never `0.0`)
  when the agreed subset is empty (golden 5) — matches eq. 58's own text and
  is exercised by both the degenerate and mixed-corpus tests.
- **No `SE+ > 1` possibility:** traced through `acceptance_probability`'s
  hard `delta_bar < 0.0 → 0` gate plus `counter_offer_price`/
  `opening_offer_price`'s projection onto `[r_B, ...]`, confirming a bound
  price can never cross the counterpart's own reservation — the spec's own
  "within_case_score ≤ 1 by construction" claim holds structurally, not just
  by luck in the goldens' chosen numbers.
- **No observation leakage:** `observe()` never exposes `t_b`, `family`, or
  raw cue labels to the agent seat; only rendered natural-language messages
  and prices, matching the stated visibility policy.

