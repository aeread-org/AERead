# Exchange experiment configurations

This directory contains protocol, treatment, ladder, and runtime experiment
configurations for the Exchange environment. Canonical public benchmark cases
live under [`cases/exchange_v1/`](../../cases/exchange_v1/).

`cases_v0` is a compatibility link to `cases/exchange_v1/v0` for scripts that
used the former location. Wheel builds materialize the same canonical files at
that former package path because wheel archives do not preserve the repository
symlink. New code and documentation should use the canonical `cases/` path.
