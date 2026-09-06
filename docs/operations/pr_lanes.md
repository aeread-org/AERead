# Pull-request lanes and limits

**Status:** repository policy. Enforced where GitHub can enforce it; the rest
is expected of every contributor and every agent session.

Adopted 2026-09-06 after one week in which 62 PRs merged, 61 of them with no
review and half within an hour of opening, while the four PRs that most needed
a reader — 20k to 100k lines of evidence — sat for days. Two kernel defects
(receipt identity coupled to kernel bytes; multi-round turns costed only on
their final round) shipped through that gap. The count of PRs was never the
problem; using a PR as a commit for load-bearing code was.

## 1. Three lanes, two review standards

A PR's lane is decided by the paths it touches. The `pr-lanes` workflow labels
every PR (`lane:kernel`, `lane:evidence`, `lane:family`; a PR can carry more
than one) and enforces the one rule that differs.

| Lane | Paths | Gate to merge |
|---|---|---|
| **kernel** | `src/aeread/shared_runner/**`, `src/aeread/cli.py`, `conftest.py`, `tests/conftest.py` | CI green **and one approving review on the current head from someone other than the author** (`kernel-review` status check; `.github/CODEOWNERS` requests the reviewers). Re-approval is needed after every push. |
| **evidence** | `evidence/**` | CI green. Review is **verification, not reading**: run the bundle's replay/digest check, the prohibited-text scan, and `aeread errata`, and paste the output as the review comment. A 70k-line bundle is reviewed in ten minutes this way, and better. |
| **family** | everything else (`src/aeread_families/**`, `configs/`, `cases/`, `docs/`, tests) | CI green. Ask for a review when the change touches a scoring contract, a verifier declaration, or a frozen self-hashed module. |

The kernel is small and load-bearing; a second pair of eyes there has paid
for itself twice in one week. Evidence is large and generated; eyes on the
diff are worth less than a script that recomputes it.

## 2. Limits

- **Work in progress:** at most **3 ready-for-review PRs per author**. Drafts
  do not count, but a draft says in its first line why it is a draft and what
  would make it ready. A draft that is not expected to become mergeable is
  closed, not parked; the branch keeps the work.
- **Stacks:** at most **2 deep**, always rooted in `main` (never on a branch
  that is not itself an open PR), rebased on every merge below them. Stack
  bodies say "n of N" and the merge order.
- **Size:** kernel PRs stay reviewable — one concern each; split a mixed PR
  (evidence riding on a kernel change, or a family suite riding on a
  calibration PR) before asking for review.
- **Failing CI:** a PR whose checks fail gets a fix or a close within
  **24 hours**. Red PRs are not a queue.
- **Merging:** `main` is protected — required CI, no force-push, no deletion.
  Merge commits, in stack order. Nobody merges their own kernel-lane PR
  without the review above; anyone may merge their own evidence or family PR
  once the gate is met.

## 3. What a review comment contains

- **kernel:** what was checked (tests read, invariants reasoned about, a
  mutation tried if the change is a guard), ranked findings with file:line,
  and an explicit verdict. Findings without a failure scenario are questions,
  not findings.
- **evidence:** the verification commands and their output — digests matched,
  replay reproduced, scan clean, errata regenerated — plus the one question
  only a human can answer: does the declaration match the measurement
  (`docs/getting-started/reviewing_trajectories.md` §3).

## 4. When the rule bends

`enforce_admins` is off, so an admin can merge past a red `kernel-review`
check. Doing so is an incident-log row (`docs/operations/incident_log.md`),
not a shortcut: record why, and what verification replaced the review.

## 5. A PR shows "kernel-review — expected, waiting for status"

The check is a required status on `main`, and it is produced by the
`pr-lanes` workflow on a pull-request event. A PR opened before that workflow
existed on `main` receives the status only after a **push** to its branch
(GitHub evaluates the new workflow on a fresh merge ref). A review comment or
a close/reopen does not start it. An empty commit is enough:

```bash
git commit --allow-empty -m "chore: trigger lane check" && git push
```

The PR is labelled and checked within about a minute. Do this right before
merging a stale PR rather than for every open PR at once.
