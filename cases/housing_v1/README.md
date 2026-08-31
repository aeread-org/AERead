# Housing v1 cases

Housing worlds are generated deterministically at runtime by
`src/aeread/housing_env.py`; this family intentionally has no static JSON case
fixtures. The generator produces the preference and capacity state from the
case parameters and seed.

See [`docs/housing_case.md`](../../docs/housing_case.md) for the case contract
and `tests/test_housing_assignment.py` plus `tests/test_housing_resolver.py`
for executable examples and regression coverage.
