# AERead working rules

## Record every failure when it happens, not when it is fixed

A failure that is only written down once it is understood loses the thing
that made it worth recording: what it looked like before anyone knew the
cause. Log it at the moment it occurs, with the wrong hypothesis included.

The register has two tiers and they are not interchangeable.

**Tier 1, the machine register.** One per family, at
`evidence/<family>_failure_register/`, derived only from published evidence
so every row traces to a committed artifact by digest. It is generated, never
edited: regenerating it must reproduce the committed bytes. For Housing:
`python -m aeread_families.housing.failure_register`.

**Tier 2, the judgment log.** [`docs/operations/incident_log.md`](docs/operations/incident_log.md).
Everything a machine cannot derive: design defects, operational stops,
tooling faults, and errors of judgment including the ones made by whoever is
writing the entry. Categories are `design`, `operational`, `tooling`,
`judgment`.

Rows are never deleted. Only their disposition changes, and a disposition of
`open` is a normal resting state rather than an admission of failure.

Do not start a new register shape. Four sessions did that once and
consolidating them is why this standard exists.

**Errata.** A finding that reaches already-published numbers also gets a
sealed record under `evidence/errata/` selecting the affected evidence by
identity; see [`docs/operations/errata.md`](docs/operations/errata.md).
Published bundles are never edited; `aeread errata --write-notes`
regenerates the register and the `ERRATA.md` sidecars.

## Campaign discipline

A changed frozen control requires a new campaign identity, never a rerun in
place. A failed cell is typed missingness and is never selectively rerun.
Estimate serial wall time from the sealed full-trajectory gate before
launching any multi-world pilot, and stop if it exceeds the operational
limit; see the campaign SOP's backend escalation instruction.

Every limit that can terminate a run belongs in the contract. A budget, an
attempt count, a timeout or a route policy that lives only in code is
invisible to anyone reading the experiment definition and silently changes
what the experiment measured.

## Pull requests

Follow [`docs/operations/pr_lanes.md`](docs/operations/pr_lanes.md). The
short form:

- **Lane by path.** Kernel (`src/aeread/shared_runner/**`, `src/aeread/cli.py`,
  `conftest.py`) merges only with one approving review on the current head from
  someone other than the author — the `kernel-review` check enforces it, and
  nobody merges their own kernel PR. Evidence (`evidence/**`) is reviewed by
  verification: run the digests, replay, prohibited-text scan and
  `aeread errata`, paste the output. Everything else: CI green.
- **Limits.** At most 3 ready PRs per author; a draft says why in line one and
  is closed if it will not become mergeable. Stacks at most 2 deep, rooted in
  `main`, rebased on every merge. One concern per kernel PR. A red-CI PR is
  fixed or closed within 24 hours.
- **From an agent session:** check `gh pr list --author @me --state open`
  against the limit before opening another PR; never run scripted git in
  `/Users/chenyusu/AERead` (that checkout is live); work in a scratch
  worktree with a `cd "$wt" || exit` guard.

## Merging is a step that can fail

A green branch proves the branch. It does not prove what `main` becomes
after the merge — hand-resolved conflicts, stale kernel bytes and untested
combined state are all invisible on a single branch. Treat the merge itself
as work to verify.

- **A stack merges only after its combined tree is green.** Before merging a
  stack (kernel PRs plus the family PRs above them), build the whole thing on
  a scratch branch, in order, resolve every conflict, run the full suite, and
  post the result on the base PR. Fourteen green branches are not a green
  result; on 2026-09-06 the first combined run of a fourteen-PR stack failed
  2/2391 from the hand-merge alone.
- **Registration-file conflicts are unions.** Every family registers itself
  in the same three files: `tests/test_shared_runner_scoring_contract.py`,
  `src/aeread/shared_runner/registry.py`, `conftest.py`. When two family PRs
  conflict there, keep both sides' blocks, take the union of the set
  literals, and keep every removal from `_NOT_YET_MIGRATED_TRUSTED_KEYS`.
  Never drop another family's block to resolve a conflict.
- **Prove nothing was dropped, then run the fast test.** After each conflicted
  merge, with the merge still in progress, check that the resolved file's
  module-level bound names (imports and aliases, defs, classes, assignments,
  parsed with `ast`) are a superset of both parents' — a `grep` for `def`
  cannot see dropped imports, which is exactly what got dropped. Then run
  `pytest tests/test_shared_runner_scoring_contract.py -q` with no bridges
  exported (under a minute; bridge-gated tests skip). Both green, then merge.
- **Any other conflict is a stop, not a resolve.** A conflict in
  `src/aeread/shared_runner/` outside `registry.py`, or two PRs editing the
  same function body differently, is a real incompatibility. Stop and report
  it; do not resolve it by hand.
- **Order is part of the stack's contract.** Kernel tier strictly in the
  declared order; family tiers only after the kernel PR they are based on has
  merged; within a tier, any order. GitHub retargets a stacked PR when its
  base merges; nothing else is done by hand between tiers.
- **Never chain a repository-settings change after a merge attempt without
  checking the merge happened** (`gh pr view N --json state` must say
  `MERGED`). Required checks, protections and labels are not undoable by
  reverting a commit.

## Why these rules exist

Recorded so the rules are not mistaken for taste. Each line is an incident on
this repository, with where it is written down.

- **Hand-merged stacks drop blocks.** The first adapter batch (#28–#38, #55)
  was merged as one chain on 2026-09-04; one conflict resolution dropped a
  `conftest.py` header and needed hotfix #85. The same chain's script made two
  stray merge commits on the maintainer's live checkout. The 2026-09-06 scratch
  merge of the migration stack dropped fourteen import symbols the same way
  (#103 comments). Hence the combined-tree gate, the union rule, the
  bound-names check, and the ban on scripted git in the live checkout.
- **Unreviewed kernel changes shipped two defects.** In one week 61 of 62
  merges had no review and `task/execution.py` changed six times in a day.
  Two defects survived: receipt identity coupled to kernel bytes (#66) and
  multi-round turns costed only on their final round, leaving published totals
  as lower bounds (#101, erratum ERR-2026-09-06-001). Hence the kernel lane's
  non-author approval and the `kernel-review` check.
- **Parallel adapters were built against an unspecified contract.** Eleven
  families implemented in parallel; the finalizer's receipt shape was never
  pinned, so four adapters bolted on shims that dropped most of their scores
  (#39). The fix already existed on `main`; the branches had not been told.
  Hence: rulings are posted on the tracking issue, and branches rebase before
  review.
- **Evidence PRs sat while trivial PRs flowed.** 20k–100k-line self-hashed
  bundles waited days for a reader who could not read them; two-hour merges
  flowed around them. Hence review-by-verification for the evidence lane.
- **Documents were dumped where nobody would find them.** Seventy-nine
  adapter and kernel-review documents at the root of `docs/`, unindexed, with
  ninety-two stale cross-references. Hence the placement rule in
  `docs/README.md` and the deferred move in #123.
