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
