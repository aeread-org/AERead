# Housing v1 cases

Housing worlds are generated deterministically at runtime by
`src/aeread/housing_v1/environment.py`; this family intentionally has no static JSON case
fixtures. The generator produces the preference and capacity state from the
case parameters and seed.

See [`docs/housing_case.md`](../../docs/housing_case.md) for the case contract
and `tests/test_housing_assignment.py` plus
`tests/test_shared_runner_housing.py` for executable examples and regression
coverage. The normative admission and publication requirements are in the
[`Housing V1 quality-control contract`](../../docs/housing_qc.md).
