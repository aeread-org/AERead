# AERead project instructions

## Record every failure, as it happens

`docs/operations/incident_log.md` is the single register of things that went
wrong. Its "register standard" section is authoritative; read it before adding
anything. The short version:

**When something fails, add it then — not when it is fixed.** This is not a
post-hoc writeup step. A failed run, a rejected canary, a contract error, a
broken main branch, a wrong claim you corrected, a script that damaged a
checkout: all of it goes in, at the time, before moving on to the fix.

- **Tier 1 (machine)** — one row per failed cell/call/attempt, derived only
  from published evidence so every row traces to a committed artifact by
  digest. Lives at `evidence/<family>_failure_register/tables/failures.csv`
  with `reports/summary.json`. Regenerated, never hand-edited. Every new
  family owes one.
- **Tier 2 (judgment)** — one row per design (**D**), operational (**O**),
  tooling (**T**) or judgment (**J**) incident in `incident_log.md` itself.
  These cannot be derived from evidence, because they are about what the
  evidence means. Judgment failures are the ones no test catches; record them
  anyway, especially your own.

Rules that are easy to get wrong:

1. A row is never deleted. Only `disposition` changes.
2. `Detection` is honest about what caught it, including "a person read the
   output" and "nothing, it was found later".
3. A failed attempt root is evidence: keep it sealed, never reuse it, and
   rebuild the Tier 1 register from it.
4. A fix that changes a frozen plan does not retro-publish the run it broke.
   Re-run, and record both the run and the reason.
5. Do not start a fifth register shape. Four sessions did that once already;
   consolidating them is why this standard exists.

When a run fails, the fix and the incident row land in the same commit, so a
reader can never see the fix without seeing what it cost.
