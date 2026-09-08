# Benchmark QC and Campaign Review Trajectory

**Status:** Informational walkthrough and operational guide.

**Related Standards:**
- [Benchmark Quality-Control Standard](../operations/benchmark_qc.md)
- [Experiment Campaign SOP](../operations/experiment_campaign_sop.md)
- [QC/SOP Open Items](../operations/qc_sop_open_items.md)

---

## 1. Overview: The Hybrid Review Trajectory

A common question when evaluating AERead benchmarks is:

> **Are benchmark gates and trajectory reviews determined automatically by the runner, or do they require human reviewer input?**

The architecture implements a **hybrid review trajectory**:
1. **Mathematical, execution, and replay properties are 100% automated** and cryptographically sealed.
2. **Construct validity, statistical clustering, and production promotion require explicit human reviewer sign-off.**

Neither layer can substitute for the other. Passing unit tests or a green CI run does not prove construct validity; conversely, human approval cannot override a broken accounting identity or a failed zero-call replay check.

```text
[ Task Generation / Specification ]
       │
       ▼  (Automated Gate 1: Check array shapes, finite bounds, digests)
[ Environment & Verifiers ]
       │
       ▼  (Automated Gate 2: 5 mandatory goldens, zero-call offline replay)
[ Construct Validity & Controls ]
       │
       ▼  (Human Review: Economic beatability, shortcut audit, cluster definition)
[ Model Schema & Profile Admission ]
       │
       ▼  (Automated Gate 4: JSON schema probes, routing/billing audit)
[ Confirmatory Freeze & Publication ]
       │
       ▼  (Human Sign-Off: Pre-registration hash freeze, cryptographic reviewer seal)
```

---

## 2. Review Responsibilities by Stage

| Stage | Review Method | Actor / Mechanism | Mandatory Exit Evidence |
|---|---|---|---|
| **Gate 1: Task Distribution** | **Automated** | Code / Schema Validator | Re-resolved task digests, finite bounds ($U \ge 0$), disjoint split validation. |
| **Gate 2: Environment & Verifiers** | **Automated** | Pytest / Shared Runner Replay | 5 goldens (Success, Poor, Invalid, Operational Drop, Zero-Denominator) + zero-call bit-exact replay. |
| **Gate 3: Construct Validity** | **Human Review** | Domain / Mechanism Reviewer | Predeclared beatability rule, shortcut resistance proof, non-trivial baseline gap. |
| **Gate 4: Attribution & Controls** | **Hybrid** | CI (probes) + Human (clustering) | Single-action schema probes, billing telemetry, explicit cluster definition (e.g. world-seed clustering). |
| **Gate 5: Confirmatory Freeze** | **Human Sign-Off** | Human Experimenter | Pre-registered holdout hash, sample power calculation, frozen cost ceiling before viewing outcomes. |
| **New Family Admission** | **Human Sign-Off** | Authorized Reviewer Key | Signed approval artifact binding reviewer ID, timestamp, and contribution digest. |

---

## 3. Automated Review Criteria (Zero Human Subjectivity)

The runner rejects or passes the following properties purely via code and cryptographic verification:

1. **Deterministic Regeneration & Hashing**:
   - Tasks and plans must re-derive byte-for-byte from pinned generator versions and seeds.
   - Referenced artifacts (receipts, event logs, summaries) are resolved on disk and their SHA-256 digests are recomputed directly from raw bytes.
2. **Offline Zero-Call Replay**:
   - An episode must be capable of reconstructing its full trajectory (`events.jsonl`), terminal state, and `ScoreEnvelope` without making any external LLM provider calls.
3. **The Five Mandatory Goldens (Gate 2)**:
   - *Successful*: Known optimal action reaches optimal payoff.
   - *Valid but Poor*: Sub-optimal legal action stays valid and preserves component diagnostics.
   - *Invalid / Unauthorized*: Malformed or illegal action changes no protected state.
   - *Malformed / Infrastructure Drop*: Transport dropouts (5xx, rate limits) become typed `invalid_measurement` / missingness—never economic score zero.
   - *Degenerate Reference*: Worlds where $U = 0$ are quarantined under explicit non-fabrication rules.
4. **Single-Action Profile Probes**:
   - Live models are probed with test inputs to confirm they emit strict JSON adhering to `additionalProperties: false` schemas before running full trajectories.

---

## 4. Human Review Criteria (Deliberate Subjectivity & Authority)

Human expert review is required where algorithmic checks cannot infer scientific validity:

1. **Construct Validity (Gate 3)**:
   - *Is the mechanism measuring what it claims to measure?*
   - For example, in Housing V1, human review determined that serial dictatorship was flawed because it was strategy-proof (leaving agents no strategic coordination decision). The sequential `contact -> respond -> commit` market was designed to restore strategic agency.
   - Reviewers must verify that beating the comparison baseline requires genuine strategic adaptation, not prompt exploits.
2. **Independent Cluster Definition**:
   - The human experimenter must declare the true unit of statistical independence (e.g., whether seeds across a generator share latent market conditions).
   - Replicate runs within the same cluster must be averaged rather than counted as independent sample points in paper tables.
3. **Production Promotion & Reviewer Authentication**:
   - Contributed benchmark families cannot be admitted into production registries by passing CI alone.
   - An authorized human reviewer must inspect the family, verify limits, and commit a cryptographic sign-off artifact matching the exact contribution digest.
