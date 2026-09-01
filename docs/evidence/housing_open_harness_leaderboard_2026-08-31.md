# Housing V1 Open Harness Leaderboard

Primary ranking: mean within-case Housing score. Reliability is an eligibility gate; cost breaks exact score/reliability ties.

| Rank | Harness | Status | Full runs | Quality | Reliability | Time/run | Cost/run | Input/run | Model calls/run |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | AERead Minimal Chat | Ranked | 3/3 | 0.8629 | 100% | 52.9s | $0.000883 | 8724 | 20.0 |
| 2 | LangChain Provider Strategy | Ranked | 3/3 | 0.7300 | 100% | 47.2s | $0.000992 | 9879 | 22.7 |
| — | smolagents Tool-Calling Agent | Disqualified: operational failure | 0/1 | — | 0% | 198.3s | ≥$0.004463 | ≥53398 | ≥35.0 |

Observed LangChain minus AERead score difference: -0.1330; paired bootstrap 95% interval [-0.3013, +0.0830] across 3 worlds.

Unranked rows remain visible because operational failure is missingness, not a zero quality score. Values prefixed with ≥ are known lower bounds.
Wall-clock time includes live provider variance and is not used for the primary rank.

## Single-action qualification gate

This table is not comparable to full Housing trajectories.

| Gate order | Harness | Valid | Time/action | Cost/action | Input/action | Output/action |
|---:|---|---:|---:|---:|---:|---:|
| 1 | AERead Minimal Chat | 3/3 | 1.881s | $0.0000459 | 428 | 57.0 |
| 2 | LangChain Provider Strategy | 3/3 | 2.736s | $0.0000453 | 428 | 52.7 |
| 3 | PydanticAI Native Output | 3/3 | 3.243s | $0.0000459 | 428 | 55.3 |
| 4 | smolagents Tool-Calling Agent | 3/3 | 5.513s | $0.0001441 | 1532 | 116.7 |
