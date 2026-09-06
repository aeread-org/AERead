"""aeread CLI — a thin dispatcher over the module command lines.

Each verb forwards to the corresponding module's own argparse CLI, so
``aeread run --help`` shows the full option surface of that verb.
"""
from __future__ import annotations

import runpy
import sys

VERBS: dict[str, tuple[str, str]] = {
    "run": ("aeread.exchange_v1.runner",
            "run one case (modes: offline / live_frozen / replay)"),
    "eval": ("aeread.exchange_v1.pilot",
             "evaluate agents on a case set (cases x agents x seeds grid)"),
    "sweep": ("aeread.exchange_v1.sweep",
              "sweep configs x models x seeds into a results CSV"),
    "submit": ("aeread.exchange_v1.submit",
               "score a submitted agent on frozen panels, with replay verification"),
    "validate-case": ("aeread.exchange_v1.filters",
                      "provider-free case admission gate (baselines + validity ordering)"),
    "baselines": ("aeread.exchange_v1.baselines",
                  "no-op / random / greedy baselines and non-triviality ordering"),
    "export-tables": ("aeread.shared_runner.analysis.research",
                      "export Run -> Task -> Model Call loss-analysis tables"),
    "errata": ("aeread.shared_runner.analysis.errata",
               "regenerate the errata register over published evidence"),
}


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: aeread <verb> [options]   (verb --help for details)\n\nverbs:")
        for verb, (_, desc) in VERBS.items():
            print(f"  {verb:14s} {desc}")
        return 0
    verb = argv[0]
    if verb not in VERBS:
        print(f"aeread: unknown verb {verb!r} (try `aeread --help`)", file=sys.stderr)
        return 2
    if verb == "export-tables":
        from aeread.shared_runner.analysis.research import main as export_tables_main

        return export_tables_main(argv[1:])
    module = VERBS[verb][0]
    sys.argv = [f"aeread {verb}"] + argv[1:]
    runpy.run_module(module, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
