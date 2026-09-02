# Implementation Specification — `steer` adapter for the AERead shared-runner kernel

**Scope.** Wrap STEER (`narunraman/STEER`, ICML 2024, arXiv 2402.09552, pinned at
`d66673c8277b9112fc5e39751524ccda6d852446`, **no license file**) as one AERead family:
a single-agent, one-shot multiple-choice question-answering corpus over 48 economic-
rationality taxonomy elements. Tonight's milestone is a **pilot corpus** — 8 declared
elements, two per taxonomy branch (utility theory, game theory, social choice, mechanism
design), deterministic head-N ≤ 200 admitted questions each — gated on corpus admission
(§1) and five component-level goldens (§4), not on paid agent runs. Interaction is Mode A:
no environment, no tools, no counterpart seat, no phase graph — one observation, one
answer, one score.

**Governing facts** (verified in recon; do not re-derive):
- 48 elements under `elements/<name>/{questions,options,answers,questions_metadata}.pkl`.
  Every `.pkl` in the pinned checkout is a **git-LFS pointer** (131-132 bytes); the real
  bytes are fetched per-file from
  `https://media.githubusercontent.com/media/narunraman/STEER/main/<path>`. The pointer's
  `oid` is the sha256 of those real bytes — verified this session for all 32 files (4 per
  element × 8 declared elements): fetch, recompute sha256 locally, compare to the
  checked-in, commit-pinned `oid`. **32/32 matched, zero mismatches.**
- **No `LICENSE` file anywhere in the checkout** at the pin (confirmed). The corpus text
  therefore never enters the AERead git repo — only ids, digests, and fetch instructions
  are committed; real text is cached at `bridges/steer-data/` (sibling of the AERead repo,
  never committed) and read from there at runtime, verified by `source_sha256` each time.
- **No scoring code exists upstream to delegate to.** The pinned commit's own message is
  "Remove STEER evaluation submodule" (`git show d66673c --stat`: deletes `.gitmodules`
  and the `STEER-evaluation` submodule reference). `canonical_point` equality is therefore
  entirely AERead-authored per `docs/verifier_taxonomy.md` §3 — there is nothing to
  import or subprocess-bridge for scoring, unlike tau3/econevals.
- **The `Answers` schema is not uniform**, and upstream's own `README.md` documents it
  wrong (`correct: bool`) for several elements. Of the 8 declared elements: `transitivity`,
  `plurality_voting`, `borda_count` use `correct_answer` (int64 0/1); `certainty_effect`,
  `backward_induction`, `dsic_mechanism`, `ir_mechanism` use `correct` (object, bool-like);
  `pure_nash` carries **both** columns. The importer must probe for either name per
  element, never assume one (logged: `ledger_entries/steer.md`).
- **A material fraction of questions have zero or multiple options marked correct** —
  not sparse noise. Per declared element (total questions / exactly-one-correct /
  zero-correct / multi-correct):

  | Element | Branch | Total | Exactly-1-correct | Zero-correct | Multi-correct |
  |---|---|---|---|---|---|
  | `transitivity` | utility_theory | 16,610 | 16,452 | 158 | 0 |
  | `certainty_effect` | utility_theory | 8,030 | 7,970 | 60 | 0 |
  | `pure_nash` | game_theory | 18,597 | 6,047 | 550 | 12,000 |
  | `backward_induction` | game_theory | 23,810 | 23,260 | 550 | 0 |
  | `plurality_voting` | social_choice | 10,020 | 10,020 | 0 | 0 |
  | `borda_count` | social_choice | 15,030 | 15,030 | 0 | 0 |
  | `dsic_mechanism` | mechanism_design | 2,417 | 652 | 1,760 | 5 |
  | `ir_mechanism` | mechanism_design | 435 | 195 | 240 | 0 |

  `pure_nash`'s multi-correct rate (64.5%) is largely real (many questions legitimately
  admit more than one equilibrium, which `canonical_point` cannot score — excluded at
  Gate 1, never mis-scored, §6); `dsic_mechanism`'s zero-correct rate (72.8%) means most
  of its raw questions have no gold answer at all in `Answers`.
- `dsic_mechanism` (1,016/1,395 base ids) and `ir_mechanism` (2/433) contain multi-part
  `question_id`s (`<base_id>_<sub_id>`, `sub_id > 0`). Upstream's README separately flags
  that *some* elements (its own example: `independence`, not declared tonight) are graded
  on cross-question consistency absent from `Answers` — this adapter implements
  per-`question_id` `canonical_point` only and does **not** implement any such cross-part
  check (§6).
- Project venv (Python 3.11) has no `pandas`; unpickling a STEER dataframe requires it.
  This is a missing-package gap, not a Python-version gap.

## 1. Pinned source, corpus enumeration, and content digest (Gate 1)

**Pin.** `narunraman/STEER` @ `d66673c8277b9112fc5e39751524ccda6d852446` (2024-08-14), no
license — corpus text is fetch-cached, never repo-committed. 48 elements exist; 8 are
declared tonight (table above), 2 per branch.

**Fetch procedure**, mirroring `tools/tau2_bridge/provision.sh`'s verify-then-trust style,
run once per declared element inside the `bridges/steer-venv` interpreter (§3):
1. For each of the element's 4 files, download from `media.githubusercontent.com`, compute
   sha256 of the downloaded bytes, and compare to the `oid` recorded in the **pinned**
   upstream checkout's git-lfs pointer file (the checked-in, commit-frozen declared value —
   never a server response header alone). Mismatch aborts the build as a hard failure, not
   a silent skip.
2. Cache verified bytes at `bridges/steer-data/<element>/*.pkl` — a sibling of the AERead
   repo, outside version control, per the no-license constraint.
3. Load with pandas; join `questions`/`options`/`answers`/`questions_metadata` on
   `question_id`; probe `answers` for `correct` or `correct_answer` (never assume one —
   the schema-drift finding above); admit only rows with **exactly one** option truthy.
   Zero-correct and multi-correct question_ids are recorded as typed exclusions
   (`reason: "no_gold_answer"` / `"multiple_correct_options"`) in the build manifest,
   never silently dropped.
4. Take a deterministic head-N of the admitted rows in original frame order (N = 200,
   capped at availability — only `ir_mechanism` has fewer than 200 admitted rows, at 195).
5. Emit one `CaseManifest` per admitted, truncated question. `content_sha256` (kernel
   resolver) covers the manifest; `payload` carries only
   `{element, question_id, options_count, source_sha256, pins}` — **never**
   `question_text`/`option_text`/`explanation`/`domain`/`tags` (the license constraint).
   `source_sha256` = sha256 of the canonical JSON `{question_text, options: [...],
   correct_option_id}`, recomputed at flatten time; it is both the Gate-1 content digest
   and the runtime integrity check against the local cache.

**Case-manifest fields:**

| field | value |
|---|---|
| `case_id` | `steer.<element>.<question_id>`, e.g. `steer.transitivity.412_0` — dot-separated, no colon (the question_id's own underscore is grammar-legal) |
| `family_id` / `family_version` | `steer` / `0.1.0` |
| `split` | `"<branch>"`, e.g. `"utility_theory"` |
| `world_seed` | not applicable (static corpus, no generator); set to `0` |
| `seats` | `(SeatSpec(id="agent", role="assistant"),)` — single-agent, no counterpart, no environment |
| `episode` | `EpisodeSpec(max_logical_actions=1, termination=("answered","error"))` — Mode A: exactly one logical action picks one option_id |
| `visibility_policy` | full observability — question + all options always shown; no hidden information |
| `payload` | `{element, question_id, options_count, source_sha256, pins}` — no corpus text |
| `provenance` | `ProvenanceSpec(generator_id="steer_importer", generator_version="0.1.0", review_status="upstream_pinned")` |
| `upstream_task_id` | the raw `question_id` string, e.g. `"412_0"` |

Branch assignment was done from element name + README description, **not** by parsing
`taxonomy.pkl` (itself another unfetched LFS pointer) — a stated limit (§6), not a silent
claim of upstream's own taxonomy structure.

## 2. Verifier declaration (per `docs/verifier_taxonomy.md`)

One leaf per case, identical shape for all 8 elements:

```python
MeasurementLeafSpec(
  leaf_id="steer_answer_key", leaf_version="0.1.0",
  estimand=EstimandSpec(estimand_id="steer_answer_key", estimand_version="0.1.0",
    input_scope="answer", direction="maximize", units="pass",
    validity_domain=...),
  verifier=VerifierSpec(verifier_family="canonical_reference",
    evaluation_class="deterministic",
    reference=ReferenceSpec(reference_id="steer_gold_option", reference_version="0.1.0",
      reference_kind="canonical_point", input_scope="answer", units="pass",
      source_sha256="<per-question source_sha256, §1>",
      implementation=ImplementationRef("steer_bridge.flatten_answer_key", "0.1.0"))),
  scorer=ImplementationRef("steer_adapter.canonical_point_scorer", "0.1.0"))
```

Match mode is exact index equality after canonicalizing option order to a stable local
ordinal (upstream's `option_id` is already a per-question 0-based int; no remapping
needed beyond validating membership). Score is 1.0 iff the parsed action's option_id
equals the gold option_id from `Answers`, else 0.0; an out-of-range or non-numeric answer
is rejected as illegal/malformed before scoring (§4 goldens 3-4), never coerced.

**Direction is declared `"maximize"` (higher-is-better) explicitly for every one of the 8
elements.** This is not automatic: `docs/problem_bound_case_audit.md` P09 (GARP-violation
scoring, on the same audit row-class as P22/STEER) is **lower-is-better** on the same
general "property/answer" kind — the two must not be conflated by inheriting one
direction convention. All 8 declared elements are accuracy-against-answer-key, not
violation counts, so `maximize` is correct for every one, confirmed by inspection.

**Aggregation is a retained per-element accuracy vector** (mean leaf score grouped by
`element`, then by `branch`) — never one blended STEER scalar across elements
(`verifier_taxonomy.md` §10, "vector"). `problem_bound_case_audit.md` P22 labels STEER
`property/answer` → `property_verified`; that is audit-status vocabulary, not a
`verifier_taxonomy` family name, and maps onto `canonical_reference`/`canonical_point`
exactly as declared here.

## 3. Adapter boundary (mirrors `refund_external_benchmark_integration.md` §4)

**Upstream owns:** question/option/answer/metadata content and the answer key (fetched,
hash-verified, never edited); element-to-branch taxonomy structure in principle (§1 notes
we approximated it manually tonight).

**AERead owns:** fetch + verify + flatten (Gate 1, bridge-venv only, one-time per
element); `CaseManifest` resolution; the trivial one-logical-action phase (no tool loop,
no `ToolRuntime`, no mutating tools — Mode A); the `MeasurementLeafSpec` and
`canonical_point` scorer (AERead's own code, since no upstream scorer exists to delegate
to — a genuine boundary difference from tau3/econevals); per-element and per-branch
aggregation; receipt/evidence/replay sealing.

**Bridge**, mirroring `tools/tau2_bridge/`: `tools/steer_bridge/` (`provision.sh`,
`requirements.txt` pinning `pandas`, `README.md` — committed, unlike the venv/data it
provisions). Invoked **only at Gate-1 build time** to unpickle upstream's pandas-serialized
format and emit plain JSON into `bridges/steer-data/<element>/cases.jsonl`; runtime
scoring, e2e, and replay read that flattened JSON directly and need no pandas import at
all — keep this boundary narrow, so pandas never becomes a test-time dependency. Env var
`AEREAD_STEER_BRIDGE_PYTHON`, default venv `bridges/steer-venv` (sibling of the AERead
repo; built this session with Python 3.12 + `pandas` 3.0.5, since project venv lacks
`pandas` — a missing-package gap, not a Python-version one).

## 4. Five QC Gate-2 goldens

All scripted (gold-trajectory), no live model calls:

1. **Successful** — `steer.transitivity.<qid>`: scripted action selects the gold
   `option_id`. Expect leaf pass, score 1.0.
2. **Valid-but-poor** — `steer.plurality_voting.<qid>`: scripted action selects a legal,
   in-range, schema-valid `option_id` that is not gold. Expect leaf legal, score 0.0 —
   distinguishes a wrong answer from an illegal one.
3. **Invalid-unauthorized** — `steer.borda_count.<qid>`: scripted action names an
   `option_id` absent from that question's own option set (e.g. an index ≥
   `options_count`). Must be rejected as illegal before scoring, never coerced to option 0
   or silently recorded as a legitimate wrong answer.
4. **Malformed-operational** — `steer.ir_mechanism.<qid>`: scripted action returns
   free-text prose instead of a parseable option identifier (mirrors provider
   truncation/non-compliance). Must surface as `invalid_measurement`
   (`verifier_taxonomy.md` §9), never as an economic zero.
5. **Degenerate-reference** — `steer.dsic_mechanism.<qid*>`, a real question_id drawn from
   `dsic_mechanism`'s own zero-correct-rows set (1,760/2,417 exist natively — no fixture
   needs to be invented). Gate 1 must have already excluded it; this golden is a
   regression test proving the exclusion path fires — an admitted case must never carry a
   reference with zero correct options — rather than a live case reaching the scorer.

## 5. Test plan

**Gate 1 (corpus admission).** `test_steer_cases.py`: for each of the 8 declared
elements, refetch independently (fresh bridge subprocess) and byte-compare sha256 to the
committed digest table (§1); assert the exactly-one/zero/multi-correct counts reproduce
this session's recon table exactly (the regression guard for the schema-drift finding —
must fail loudly if a future importer hardcodes one `Answers` column name); assert every
admitted `CaseManifest.payload` contains no raw question/option/explanation text (a
licensing regression guard, not just a schema check).

**Unit — scorer.** Table-driven pass/fail/illegal/malformed cases covering the 4
non-golden shapes of §4 plus an edge case: an `option_id` present in `Options` globally
but not within this question's own subset.

**Parity — none against upstream scoring exists** (Governing Facts: the eval submodule
was removed at the pin itself). "Parity" here means only (a) fetch-hash parity against
the git-lfs `oid` (§1, already 32/32 verified this session) and (b) flatten-determinism
parity: running the importer twice over the same cached bytes yields byte-identical
manifests (mirrors `tau3_retail_adapter_spec.md` §1's import-determinism check, P1).

**Offline replay.** Network disabled, no bridge subprocess spawned: replay each of the 5
goldens from its sealed episode record; the recorded parsed action reproduces the same
`option_id` and leaf score by reading only the locally-cached flattened JSON
(`source_sha256`-verified), never re-fetching or re-invoking pandas.

**e2e.** One scripted trajectory per declared element (8 total) through the one-shot
phase: observe → one action → terminal. Assert exactly one logical action per episode and
that the sealed `ScoreEnvelope`'s leaf/units/direction match §2.

## 6. Stated limits

- Tonight's 8/48 elements, ≤ 200 questions/element (1,595 admitted rows total: 200 × 7
  elements + `ir_mechanism`'s full 195) is an **integration-gate pilot**, not a population
  estimate or saturation claim (`refund_external_benchmark_integration.md` §9's reasoning,
  applied here).
- Head-N is original-frame-order, **not** stratified by `domain`/`difficulty_level`/`tags`;
  a later revision could stratify.
- Branch assignment was manual (element name + README), not derived from upstream's own
  `taxonomy.pkl` (also an unfetched LFS pointer) — flagged, not silently asserted as
  upstream's structure.
- `pure_nash`'s real multi-correct-option questions (legitimately multiple Nash equilibria)
  are excluded at Gate 1, not scored under a weakened match rule; a `canonical_set`
  variant for such elements is future work, not implemented tonight.
- No upstream scoring code exists to delegate to or achieve parity against — unlike
  tau3/econevals, there is no "upstream reproduces our score" parity claim in this family.
- `Answers` schema drift (`correct` vs `correct_answer`; `pure_nash` carries both) is real
  upstream inconsistency (`ledger_entries/steer.md`), not a bug in Gate 1 — the importer
  must stay probe-based, never name-fixed.
- `dsic_mechanism`'s and `ir_mechanism`'s multi-part `question_id`s are scored
  independently per part; the cross-part consistency check upstream's README describes
  for other elements (example: `independence`) is not implemented here.
- The bridge (`pandas`) is needed only at Gate-1 build time — don't let a later change quietly promote it to a runtime/test-time dependency.
