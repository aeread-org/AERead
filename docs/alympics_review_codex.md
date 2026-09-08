# Codex adversarial review — alympics adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **9**.

---

The review completed with 9 findings, but the read-only sandbox rejected the sole authorized write. No repository files or git state were changed.

Intended path: `/Users/sunzeyu/Documents/econ benchmark/AERead/.worktrees/alympics/docs/alympics_review_codex.md`

Findings: 0 Critical, 6 High, 3 Medium.

Key findings:

- High: Agent observations differ materially from upstream: balance excludes the current salary credit and prior public auction history is omitted (`environment.py:497-526`).
- High: Comparative scorers accept arbitrary, unverified baseline states; `baseline_policy_id` is ignored (`measurement.py:153-162,170-235,559-661`).
- High: Missing `bid_legal` evidence silently passes as legal and permits wealth/survival scoring (`measurement.py:390-401,452-477`).
- High: Dead players retain positive "terminal wealth," contradicting upstream's stated reset-to-zero rule (`environment.py:629-650`; `measurement.py:587-605`).
- High: Mutable replay records can be reported as `"match"` when no original is supplied (`replay.py:74-154,413-470`).
- High: A preloaded generic `waterAllocation` module bypasses the pinned-checkout guarantee (`environment.py:181-214`).
- Medium: The "full survival" golden never asserts survival; the real reference run eliminates four seats (`test_alympics_wac_measurement.py:213-248`).
- Medium: Malformed-action coverage depends on a test-only hook or monkeypatch unreachable from production `step()` (`environment.py:222-230,298-312,600-608`).
- Medium: Absence of the developer-specific upstream checkout skips five entire integration-test modules.

FINDINGS: 9
