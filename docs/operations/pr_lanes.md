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

## 2. Claim the work before you build it

Two of us migrated the same three families' scorers in parallel and neither
noticed. It cost a day and produced a merge that passes review and is wrong
(#141). Preventing the next one is three cheap habits.

- **File an issue assigned, or file it unassigned on purpose.** An unassigned
  issue is an open invitation, and it will be read as one. If you intend to do
  the work yourself, assign it to yourself when you file it. `#74`, `#75` and
  `#76` were filed by one person, left unassigned, and picked up by another
  running a systematic sweep -- both were behaving reasonably.
- **Look before you start, not before you push.** Before opening a branch on
  a family or adapter, run `gh pr list --state open --search "<family>"` and
  `gh issue list --search "<family>"`. In two of the three collisions above,
  the other person's PR had been open for **five and eighteen hours** when the
  second branch was started. Nobody looked, because the only "check first"
  rule in this document was `--author @me` for the WIP limit -- a rule that
  points at your own work, which is the one place a collision cannot be.
- **Say you are taking it.** A one-line comment on the issue ("taking this in
  `codex/<branch>`") is the whole protocol. If you find a PR already open on
  your family, comment there instead of opening a second one.

## 3. A clean merge is not evidence

When two branches touch the same family's `measurement.py`, `environment.py`
or scorer, **the second to land re-runs that family's tests against the merged
file**. Not against its own branch -- against the merge.

This is not caution for its own sake. In the collision above, each branch
passed its own suite (30 and 24 tests) and the automatic merge produced a
scorer that fails 6. Git reported no conflict because each side had added its
`__call__` at a different point in the file, so the two insertions did not
overlap; Python does not error on a duplicate method, it silently keeps the
last one. The govsim pair, which edited the same lines, conflicted loudly and
was safe. The difference between "caught" and "silently wrong" was where in
the file each person happened to put the method.

`tests/test_no_duplicate_class_members.py` now fails on a duplicated method in
any family module, so this particular shape cannot merge silently again. The
rule stays anyway: the test catches duplicate definitions, not two definitions
that were merged into one wrong one.

For each conflicted registration file, run the structural checks before
committing the resolution, from the scratch worktree:

```bash
python tools/check_registration_merge.py tests/test_shared_runner_scoring_contract.py --ours HEAD --theirs MERGE_HEAD
python tools/check_registration_merge.py src/aeread/shared_runner/registry.py --ours HEAD --theirs MERGE_HEAD
python tools/check_registration_merge.py conftest.py --ours HEAD --theirs MERGE_HEAD
pytest tests/test_shared_runner_scoring_contract.py -q
```

For a rebase, pass the corresponding two parent revisions explicitly. The
checker includes imports and aliases in the bound-name comparison, rejects
new duplicate bindings, preserves the intersection of migration exemptions
and the union of bridge enrollment, and flags annotated helpers that may
return no value. Its return analysis is conservative, not a Python type
checker; known non-returning pytest skip/fail/exit calls are recognized.
An ambiguous result requires inspection, never deleting a parent block to
make the check green. Scorer behavior still needs the test on the resolved
tree. The repository-wide duplicate-binding guard also checks imports,
while allowing ordinary sibling namespace imports such as `urllib.error`
and `urllib.request`.

## 4. Limits

- **Work in progress:** at most **3 ready-for-review PRs per worker**. Drafts
  do not count, but a draft says in its first line why it is a draft and what
  would make it ready. A draft that is not expected to become mergeable is
  closed, not parked; the branch keeps the work.

  **Per worker, not per GitHub account.** Several agent sessions push under one
  identity in this repo, so counting by account charges one session for
  another's work: the first run of this check reported 10 ready PRs to a
  session that held 5, with 3 belonging to a different session and 2 being
  drafts. A limit that miscounts is one people learn to disregard, which is
  worse than not having a limit. Every PR body carries the session URL that
  opened it, and `pr-hygiene` groups by that; PRs with no session id are a
  human's and count together. If you are a person reading this: your account
  is your worker, and nothing changes for you.

  The corollary matters more than the count. Two sessions under one account
  cannot see each other in `gh pr list --author @me` — each sees a list
  containing the other's work and no way to tell which is which. That is a
  second reason the "look before you start" rule above is written against
  `--state open` for the whole repo rather than against your own PRs.
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

## 5. What a review comment contains

- **kernel:** what was checked (tests read, invariants reasoned about, a
  mutation tried if the change is a guard), ranked findings with file:line,
  and an explicit verdict. Findings without a failure scenario are questions,
  not findings.
- **evidence:** the verification commands and their output — digests matched,
  replay reproduced, scan clean, errata regenerated — plus the one question
  only a human can answer: does the declaration match the measurement
  (`docs/getting-started/reviewing_trajectories.md` §3).

## 6. When the rule bends

`enforce_admins` is off, so an admin can merge past a red `kernel-review`
check. Doing so is an incident-log row (`docs/operations/incident_log.md`),
not a shortcut: record why, and what verification replaced the review.

## 7. A PR shows "kernel-review — expected, waiting for status"

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

## 8. A kernel PR stays BLOCKED although it is approved and every check is green

Symptom: `gh pr view N --json mergeStateStatus` says `BLOCKED`, the review
decision is `APPROVED`, and every check reads `SUCCESS`. Looking at the rollup
shows `kernel-review` **twice on the same head**, once `FAILURE` and once
`SUCCESS`. That is the normal shape when the check ran before the approval
existed and again after it: the first run failed honestly, and the failed run
stays attached to the head.

**Do not reach for section 7's empty commit here.** A push moves the head, and
a kernel-lane approval is pinned to the head SHA — `pr-lanes.yml` selects
reviews with `.state == "APPROVED" and .commit_id == "$HEAD_SHA"`. Pushing
anything, empty commit included, discards the approval you just obtained and
costs your reviewer a second round.

`kernel-review-reconcile.yml` checks for this after each `pr-lanes` run
finishes. It reads the live PR head, changed files, and formal reviews,
then re-runs older failed or cancelled **whole workflows** on that same
head. It does not set checks to success or merge anything. Drafts, changed
heads, absent approvals, incomplete file listings, and failures outside
`kernel-review` do not qualify. After three workflow attempts it stops for
manual inspection. Review comments do not revoke a formal approval;
changes-requested and dismissed reviews do.

For inspection or recovery before that workflow is deployed, use:

```bash
python tools/ci/reconcile_kernel_review.py --repo aeread-org/AERead --sha <full-head-sha>
# Add --apply only after inspecting the reported candidates.
```

Or re-run the failed run directly. The SHA does not change, so the approval
survives. Use a full rerun, not `--failed`: the partial rerun on #176 left a
cancelled gate instance attached to the head.

```bash
gh run list --repo aeread-org/AERead --branch <branch> \
  --workflow pr-lanes.yml --json databaseId,conclusion,headSha
gh run rerun <databaseId of the FAILURE run>
```

Observed on #158: approved and green, `BLOCKED` until the pre-approval
`kernel-review` run was re-run in place.

## 9. Repository automation and test timings

Auto-merge, deletion of merged branches, and the Update branch button are
enabled at repository level. Auto-merge is selected per PR after its scope
and landing order are settled; it still waits for the required checks.
Updating a kernel PR changes its head and requires a fresh non-author
approval. Branch deletion does not replace rebase and combined-tree checks
for dependent PRs.

The provider-free CI jobs print their 30 slowest tests and retain JUnit XML
as `test-results-python-<version>` artifacts, including on failures. The
pytest command's exit status is preserved directly. Use these timings to
identify long individual tests that more xdist workers cannot split.
