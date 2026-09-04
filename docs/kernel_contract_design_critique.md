<!--
Provenance: independent design critique of kernel_scoring_contract_spec.md, produced by a
reviewer operating under a restricted, permitted file-range view (it cannot write files itself).
Reproduced verbatim below; verdicts against the actual codebase follow in a separate section.
-->

## 1. Scorer input

1. The plain dataclass is the cleaner API: the current finalizer passes only `recorded_outcome`, while the new type makes outcome versus trajectory access explicit. But the claim that only two scorers depend on Mapping cannot be verified from the permitted ranges—the only visible dependency is the generic invocation. (`kernel_scoring_contract_spec.md:55-62`; `src/aeread/shared_runner/task/evaluation.py:315-320`)
2. `frozen=True` is insufficient for the promised deep immutability. Both `outcome` and `PhaseInstance.observations` remain mappings, while action/transition contents can contain mutable objects; the spec defines no freezing algorithm or canonical frozen representation. (`kernel_scoring_contract_spec.md:40-65`; `src/aeread/shared_runner/task/scheduler.py:267-278`)

## 2. Deferred leaves

3. The design works only for deferred, non-admission diagnostics. A deferred primary or admission leaf is omitted at finalization, but `FamilyScoreSet` requires the primary and every admission leaf to be present. The spec must explicitly forbid deferred leaves from both roles. (`kernel_scoring_contract_spec.md:120-127`; `kernel_scoring_contract_spec.md:137-145`; `src/aeread/shared_runner/measurement.py:413-436`)
4. "Recorded as declared-and-deferred" has no specified carrier. `FamilyScoreSet` contains only primary, returned scores, and admission IDs, and the visible finalizer passes nothing else onward. Receipt inclusion beyond `invalid_admission_leaf_ids` cannot be verified because receipt code is outside the authorized ranges. (`kernel_scoring_contract_spec.md:144-147`; `src/aeread/shared_runner/measurement.py:393-395`; `src/aeread/shared_runner/task/evaluation.py:315-320`)
5. The manifest could apparently classify every leaf as deferred, but normalization requires a nonempty score set containing a primary. Require at least one finalize-time primary leaf. (`kernel_scoring_contract_spec.md:140-143`; `src/aeread/shared_runner/measurement.py:399-416`)

## 3. Manifest policy

6. Actual manifest extensibility cannot be verified within the permitted files. The spec defines neither concrete fields/types nor parsing, defaults, serialization, compatibility, or version-bump behavior; the visible runtime resolves the manifest but never reads leaf policy. (`kernel_scoring_contract_spec.md:107-128`; `kernel_scoring_contract_spec.md:232-236`; `src/aeread/shared_runner/task/evaluation.py:297-320`)
7. The proposed test checks returned IDs, primary, admission IDs, and evidence references, but not whether the primary corresponds to `primary_estimand`, whether every deferred leaf names a wait artifact, or whether illegal primary/admission scope combinations exist. Those stated rules therefore lack a specified validator. (`kernel_scoring_contract_spec.md:120-150`; `kernel_scoring_contract_spec.md:196-214`)

## 4. Replay claim

8. The "already walks the full trajectory and discards it" claim is not verifiable from the authorized range. The visible portion walks phase starts and action starts through parse-result lookup, but lines 201–279—where transition replay, construction, and return would occur—were excluded. The visible caller receives only outcome plus an event. (`kernel_scoring_contract_spec.md:22-26`; `src/aeread/shared_runner/task/evaluation.py:138-200`; `src/aeread/shared_runner/task/evaluation.py:304-309`)
9. Retention is not specified field-by-field. `PhaseInstance` needs post-state hash, observations, complete action records, and transitions; the visible replay range has not shown how those values and their contributing event IDs become one immutable instance. (`src/aeread/shared_runner/task/scheduler.py:267-278`; `src/aeread/shared_runner/task/evaluation.py:150-200`; `kernel_scoring_contract_spec.md:67-68`)
10. "Exclusively from sealed evidence" is inaccurate: replay also invokes the current plugin's phases, initial state, and eligible-actor logic, using a currently validated family payload. The contract must distinguish evidence-carried data from values recomputed using live plugin code. (`kernel_scoring_contract_spec.md:42-47`; `src/aeread/shared_runner/task/evaluation.py:142-167`; `src/aeread/shared_runner/task/evaluation.py:301-308`)

## 5. Remaining implementer choices

11. Return shape contradicts itself: Section 2 preserves bare envelopes and sequences for single-leaf families, while Section 5 requires every migrating `__call__` to return `FamilyScoreSet` and says agents cannot choose the return shape. (`kernel_scoring_contract_spec.md:73-105`; `kernel_scoring_contract_spec.md:164-177`)
12. Evidence-reference ordering is underspecified. "Deterministic, deduplicated, ordered" does not say event-log order, lexical event-ID order, or dependency traversal order, nor which validation-only reads count as "used." (`kernel_scoring_contract_spec.md:67-68`; `src/aeread/shared_runner/task/evaluation.py:141-177`)
13. Provenance is duplicated in `FamilyScoringInput.evidence_refs` and the keyword argument, with no rule for detecting disagreement or which value is authoritative. (`kernel_scoring_contract_spec.md:50-53`; `kernel_scoring_contract_spec.md:73-79`; `kernel_scoring_contract_spec.md:93-96`)
14. The protocol test refers to `trajectory_leaf_ids`, but the manifest rules define only finalize-time versus deferred scope; no field or rule declares which finalize-time leaves are trajectory-sensitive. (`kernel_scoring_contract_spec.md:118-150`; `kernel_scoring_contract_spec.md:216-220`)
15. The paired-history protection is pseudocode, not a complete test: the critical score-difference assertion is an ellipsis, so eleven implementers can choose different comparisons, invalid-status handling, or leaf subsets. (`kernel_scoring_contract_spec.md:216-228`)

CRITIQUE-ITEMS: 15
