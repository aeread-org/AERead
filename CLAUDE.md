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
