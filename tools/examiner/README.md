# AERead examiner

A read-only browser over every published evidence bundle: status as stated,
validity checklist, incident rows, version chains and run order, phase graphs,
per-case step views (observation, action, consequence, state beyond the seat's
view) and a charts page per bundle. It reads `evidence/**` and, where a bundle's
receipt digests resolve to sealed attempt directories on this machine, the
sealed event logs. It never writes to `evidence/` or `runs/`.

Built 2026-09-21/22 in an agent session; published copies (private artifacts):
general examiner `https://claude.ai/artifact/SGVaNmQp1WKW9ET6F6PwEE`, lemons
case examiner `https://claude.ai/artifact/VfhkjFK6rEZbVWCYkCxVup`, phase
graphs `https://claude.ai/artifact/ECJREr8ur4MG4YTzs5y6Ye`.

## Build and view

```bash
tools/examiner/rebuild.sh <AERead checkout> [output dir] [run root ...]
cd tools/examiner/build && python3 -m http.server 8791 --bind 127.0.0.1
# open http://127.0.0.1:8791/index.html  (the page fetches data/*.json, so file:// does not work)
```

The output defaults to `tools/examiner/build/` (git-ignored). Run roots default
to `~/AERead*` plus every worktree git registers for those checkouts, which is
how runs sealed inside another session's worktree are found. `PY=<python>`
overrides the interpreter (default: the checkout's `.venv`).

Evidence that lives on branches not yet in the checkout (Housing's campaigns
sit on `codex/housing-v13-cooldown-full-trajectory`, the lemons pilot on
`codex/housing-lemons-refusal`) is read from extra checkouts of those branches:

```bash
AEREAD_EXAMINER_EXTRA_CHECKOUTS=/path/to/housing-v13:/path/to/lemons \
  tools/examiner/rebuild.sh <AERead checkout>
```

The checkout passed first wins when two carry a bundle of the same name. Each
bundle records the branch it came from as `checkout`; the local paths go to
`roots.json`, which is git-ignored and never published. A folder with
`reports/*.json` directly under `evidence/` or `evidence/<family>/` counts as a
bundle, so Housing's older layout (no publication manifest) is catalogued, and
its per-attempt receipts in `trajectories/attempted.json` and `tables/**` are
resolved to sealed logs. At most `AEREAD_EXAMINER_LENS_CAP` (default 60)
sealed attempts per bundle reach the page, round-robin over worlds; the page
states "N of M". The lemons pilot's narrated lens needs its run root; when that
is absent, a lens file already in `build/data/lens/` is kept as is.

A rebuild from `main` at 96ab6af0 on 2026-09-23: 72 bundles, 55 with
trajectories, 50 full-detail lenses, 40 trajectory sets synthesized from sealed
logs, 8.8 MB of packed data, `check_build.py` clean. The published artifact
shows 73 because it was built with the housing lemons bundle from PR #215.

## Steps (each a standalone script)

1. `extract_phase_graphs.py`, `dynamic_phase_graphs.py`: the phase graph every
   plugin declares, statically from source and live by instantiating each
   plugin on a real case. The committed `phase_graphs*.json` are the fallback
   a failed extraction keeps.
2. `index_receipts.py`: receipt sha256 to sealed attempt directory
   (`receipt_index.json`, machine-local, git-ignored).
3. `build_general_examiner.py` with `campaign_order.py`: the catalog (status,
   facts, incident rows including open family-level rows every bundle
   inherits, QC sentences, validity checklist, version chains, run order from
   sealed receipt times, else the first commit naming the identity) and a
   campaign file per bundle that publishes the kernel step grain.
4. `build_examiner_data.py`: the narrated housing lemons lens, only when that
   run root is present.
5. `build_general_lens.py`: full-detail lenses from sealed logs, one case per
   receipt (world panels share cell and attempt ids across inference seeds),
   and synthesized campaign files (`source: sealed_logs`) where no grain is
   published. Bundles with neither get a stated reason in `data/lens/index.json`.
6. `build_results.py`: tables, pivoted metric CSVs, merged arm reports,
   interval estimates and headline numbers for the charts page.
6b. `build_case_cards.py`: a family's case cards (`docs/families/*/case_cards/*.json` and
   `case_cards.md`) with each diagnostic check evaluated per published cell, from the
   bundle tables and, for negotiation, the sealed events. The step view shows the card
   as a full-width panel above the three columns.
6c. `build_starcraft.py`: the starcraft_master OpenBW prototype's local matches
   (`AEREAD_EXAMINER_STARCRAFT_RUNS`, default `~/starcraft_master/runs`) as one bundle marked
   external: cases are matches, steps are strategist decisions (goals, reviews, engagement
   postures, tactical missions, concession reviews), and the hidden state is the opponent's
   economy and army. They are not AERead evidence and the page says so; machine-local paths are
   cut, and replays and raw logs are never copied.
7. `check_build.py`: consistency and size checks, exit 1 on a hard problem.

`page/index.html` is the whole app (vanilla JS); `rebuild.sh` copies it into
the build folder. `page/lemons_case_examiner_template.html` is the template of
the standalone lemons examiner. `build_phase_graph_page.py` renders the
standalone phase-graph page. `apply_run_order.py` shows how to re-apply page
changes onto a newer live copy when another session published in between.

## Data packing

Campaign and lens files are JSON envelopes `{encoding: "gzip+base64", payload}`
because the artifact host serves only known text and media types; the page
inflates them with `DecompressionStream`. Lens records are compacted
losslessly (`$p` same as this seat's previous value, `$pa` previous action's,
`$pp` array prefix plus tail, `$pe` array with replaced elements plus tail,
`$o` terminal key equal to the outcome's). `jev/jev_lib.py` has a Python
`load` and `expand` that undo both.

## What adapts on its own

A new bundle under `evidence/<family>/<id>/` appears on the next rebuild, with
its family label derived from the directory, its QC profile found under
`docs/families/*/qc.md`, and its chain keyed on the last `_vN` token. Graphs
come from the plugin extraction or, failing that, from observed transitions.
Family-specific code is limited to the label and QC overrides and the housing
graph variants in `build_general_examiner.py`, and the lemons narration in
`build_examiner_data.py` and the page's `renderLens`.

## Jev probes

`jev/` holds the scripts and saved results behind
[`docs/research/jev_trajectory_triage_2026-09-22.md`](../../docs/research/jev_trajectory_triage_2026-09-22.md).
Each script takes an examiner build folder as its first argument and reads or
writes `jev/results/`. The ones that call Jev need `OPENROUTER_API_KEY` in the
environment (source it from the checkout's `.env`; never print it):

| script | calls Jev | what it does |
|---|---|---|
| `jev_probe.py`, `jev_probe2.py`, `jev_probe3.py` | yes | feasibility: state sizes, size limit, known-answer accuracy, cost |
| `jev_pass2.py` | yes | trajectory-level triage over three families (123 calls) |
| `jev_score.py` | no | scores the trajectory pass against rule truth |
| `jev_actions.py` | yes | action-level agency and outcome-effect pass (652 calls); `--truth-only` rebuilds the rule labels offline and compares them with the saved run |
| `jev_actions_score.py` | no | scores the action pass |
| `jev_scripted.py` | yes | the same questions on scripted reference tenants |
