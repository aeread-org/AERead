# Exchange experiment configurations

This directory contains protocol, treatment, ladder, and runtime experiment
configurations for the Exchange environment. Files are grouped by their role:

| Folder | Contents |
|---|---|
| [`baselines/`](baselines/) | Clean reference environments and the structured RL starter config |
| [`diagnostics/`](diagnostics/) | Pressure probes that diagnose search and institutional behavior |
| [`mechanisms/`](mechanisms/) | Paired mechanism control/treatment comparisons |
| [`treatments/`](treatments/) | Named treatment families and their experiment toolbox |
| [`ladders/`](ladders/) | Development capability ladders not attached to a frozen release |
| [`releases/v1/`](releases/v1/) | The frozen v1 main config, six ladder rungs, and verification manifest |

Canonical public benchmark cases live under
[`cases/exchange_v1/`](../../cases/exchange_v1/).

`cases_v0` is a compatibility link to `cases/exchange_v1/v0` for scripts that
used the former location. Wheel builds materialize the same canonical files at
that former package path because wheel archives do not preserve the repository
symlink. New code and documentation should use the canonical `cases/` path.

Paths stored in [`treatments/treatment_toolbox.json`](treatments/treatment_toolbox.json)
are relative to this directory. Paths in the frozen v1 manifest are relative to
the repository root because the baseline verifier consumes them directly.
