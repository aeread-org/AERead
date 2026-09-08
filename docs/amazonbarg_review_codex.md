# Codex adversarial review — amazonbarg adapter

Second-reviewer pass (cross-model, read-only). Recovered from the build run's
transcript: the reviewer's sandbox permitted reads only, so it could not write
this file itself and reported its findings in its returned text instead.

Declared finding count: **10**.

---

The review completed, but the sandbox rejected the sole authorized write because the workspace is read-only. `docs/amazonbarg_review_codex.md` was not created.

Findings, severity-ordered:

1. **Critical — Runtime upstream pin is not enforced.** `environment.py:161-173` validates only declared strings and SHA shape; `upstream_shim.py:346-406` imports arbitrary runtime files without checking commit or bytes. A dirty `eval.py` can publish altered scores under the official pin.

2. **High — False ZOPA passes.** `measurement.py:678-683` treats upstream `B` as the genuine budget, but upstream `eval.py:226-238` replaces budgets when the bargaining interval is under $1. An executed probe on `home-kitchen_20` (`case JSON:17-25`) showed actual budget `47.992`, delegated `B=48.99`, and a `$48.50` deal incorrectly scoring ZOPA `1.0`.

3. **High — Replay never reads sealed evidence.** `replay.py:137-155` records from in-memory `EpisodeResult`; `test_amazonbarg_replay.py:140-151,266-275` creates evidence and then discards it. Corrupted or missing durable evidence does not affect replay tests.

4. **High — Unverified offline replay reports `match`.** `replay.py:388-418` sets `comparison=None` without an original but still returns status `match`. A tampered record can therefore be labeled verified.

5. **High — Production execution does not produce or seal scores.** `measurement.py:820-826` admits the kernel never invokes `build_scorer`; `measurement.py:904-927` defaults every score's evidence references to empty. The shared-runner episode path seals decisions but no measurement result.

6. **Major — Tests silently skip wholesale.** `test_amazonbarg_measurement.py:50-65` performs a module-level skip when one developer-specific upstream path is absent, including upstream-free tests beginning at lines 157-220. The same pattern exists in the other adapter test modules.

7. **Major — "Component parity" compares the implementation with itself.** `test_amazonbarg_measurement.py:287-331` calls the same scoring path twice and derives assertions from that output. It cannot detect shared semantic errors such as the false-ZOPA bug.

8. **Major — Sanitization is collision-prone and non-reversible.** `cases.py:118-146` leaves literal `_xHHHH_` markers untouched. `a:b` and `a_x003a_b` therefore sanitize to the same identifier; the tests at `test_amazonbarg_cases.py:110-123` omit this case.

9. **Medium — Pilot digest depends on dictionary insertion order.** `cases.py:445-463` hashes `list(cases)` without validating or canonicalizing order. Identical pilot membership inserted in another order receives another identity.

10. **Medium — Import shim is unsafe under concurrency.** `upstream_shim.py:224-343` mutates global `sys.modules`, `sys.path`, `socket.socket.connect`, and `openai.OpenAI` without synchronization. Concurrent scoring can import from the wrong root or prematurely disable the network guard.

Pytest verification was blocked before collection by `FileNotFoundError: No usable temporary directory found`. The standalone scoring probe above executed successfully against pinned upstream commit `834ad9066d0627f0332504d5fa6d236706f2402b`.

FINDINGS: 10
