# paper/working-draft

The AERead working paper's build package, versioned on its own branch: sources (`source/`), figures and their
scripts (`figures/`), the build (`build.py`, `paper.css`), the evidence copies the build checks against
(`analysis_evidence/`), and the built PDF. No repository code lives here, and CI does not run on this branch.

The draft is edited and built at `output/pdf/aeread_working_draft_20261018_v15/` in the maintainer's checkout;
`./sync_and_push.sh "message"` copies it here, commits and pushes, after every rebuild. Build:
`uv run --with markdown --with beautifulsoup4 --with pypdf python build.py` (needs pandoc and Chrome).
The sources-and-evidence zip and the HTML are build outputs and are not committed.
