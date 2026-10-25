# Local verification of the public projection

Performed before upload, using the isolated publication checkout and retained
local source evidence only during export. No model calls or paid retries.
These are local verification results, not independent human approval or a
claim that repository-wide CI has already passed.

```text
python research/refund_v34/reproduce.py
Offline native replay 1100/1100
PASS: 1100 episodes, 10794 typed actions; native states, 11 leaves, pairs and taxonomy reproduced; provider calls=0

python research/refund_v34/reproduce.py --manifest-only
PASS: manifest, all file digests, runtime pins and prohibited-text scan

python -m pytest -q --noconftest research/refund_v34/test_publication.py
23 passed
```

The verifier additionally reconciles run/task/call/result relational grains,
all 12,100 typed component rows, selected-episode active-call counts/costs,
and the preserved original 660-row historical projection. Call identifiers
are scoped by run/task/attempt, not incorrectly assumed globally unique.

Native states/scores/taxonomy were checked on the same action and runtime bytes
published here. Final documentation and this transcript were added afterward;
the final manifest was sealed and checked again before commit.

Additional existing shared-runner publication tests: **19 passed, 3 failed**
because this local interpreter has incompatible SciPy/NumPy versions; see
[STATUS.md](STATUS.md). This package does not claim those failures passed.
`aeread errata` is unavailable at the pinned base (`unknown verb 'errata'`).
No old evidence bundle or original experimental source/receipt was edited.
