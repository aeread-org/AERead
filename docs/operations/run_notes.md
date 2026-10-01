# Notes on runs

**Status:** standard procedure. A result a reader should not miss is written on the run, in
the same session that produced it.

A sealed bundle says what ran. It does not say what a reader should take from it, and the
things worth taking (the headline estimate with its interval, which cells are missing and why,
a caveat that changes the reading, a later run that replaces it) otherwise live in a chat, a PR
body or someone's memory. A note puts one such thing next to the run, where the person opening
the run will see it.

The notes themselves are kept with the Examiner, which is maintained in the organization's
private repository and not in this one: the sealed evidence stays here, and the reading of it
is attached to the run there. This page is the procedure; the file format and the tool that
validates it live with the Examiner.

## When to write one

Write a note when a run finishes, or when you learn something about a finished run, and any of
these holds:

| Tag | Write it when |
|---|---|
| `finding` | the run supports a headline estimate or contrast. Give the number, its unit, its interval and its sample (worlds or clusters, not cells), and say if it is exploratory |
| `caveat` | something changes how the run is read: cells missing, a confound, an incomplete pack, a score that cannot see the thing studied |
| `invalid` | the run, or a cell range, must not be relied on (a route fault, a defect found after the fact) |
| `superseded` | a later run or a correction replaces it; name it |
| `todo` | something about the run is still to be done and is not yet an incident row |
| `info` | context that is neither: what the run was for, where its raw output lives |

A run that produced nothing a reader needs does not need a note. Do not restate the bundle's own
README or status.

## How

A note is one line: a date, a tag, the text, and optionally the author and a link to the
incident row, report or path that holds the detail.

- **One claim per note, 280 characters at most.** Numbers carry their unit, interval and sample
  size. The reasoning goes in the [incident log](incident_log.md) or a report and the link
  points to it.
- **Append-only.** A wrong note is corrected by a later note that says so and names what it
  corrects, as with the incident log; edit a line in place only to fix a typo.
- **Write it before you report the result.** The note is the record; the message to the owner
  can then say what it says.
- **A run not yet published is noted under the id it will have.** The Examiner build lists such
  a note as unmatched and shows it once the bundle is in a build.
- **The note is not the failure record.** A failure goes to the incident log when it happens;
  the note points to that row. Notes never touch `evidence/`.

## For agent sessions

Before ending a session that ran or analysed a run, list the runs you produced a result for and
check that each has the note it needs. A result reported in a message and absent from the run's
notes is not yet recorded.
