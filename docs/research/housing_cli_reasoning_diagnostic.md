# Housing CLI reasoning retention diagnostic

Nine cells where neither original CLI subject finished by signing an inspected listing were rerun for Claude Code Opus 5.5 and Codex Sol 6.1. These cells were selected after observing results; this is a behavioral diagnostic, not a confirmatory model comparison.

## Capture and validation

Both subjects completed 9/9 cells. Each made 48 captured calls. Claude returned readable summaries on 44 calls and Codex on 24; missing text is explicit, never reconstructed. Requests, raw stdout/stderr, final actions and provider-exposed summaries are retained locally. All 18 episode transcripts and 4,707 retained-file hashes were verified. Each completed cell's receipt was verified and its score replayed by the existing housing runner.

Prompt text, model names, reasoning effort (`low`) and executable versions/digests match the original panel. Claude adds verbose stream-json and `--thinking-display summarized`; Codex adds `model_reasoning_summary="detailed"`. Neither resumes sessions. These are new plays, not recovered explanations of original decisions or full internal chain of thought.

## Observed signal

All five pooled-landlord cells repeated the original terminal choices and focal tenant payoffs for both models: two no-deals and three signings of sound listings inferred by elimination after inspecting both lemons. Claude's exposed summaries explicitly describe the elimination. Codex's summaries are sparser, so its actions provide stronger evidence than its explanatory text.

The four true-cost cells were less stable. Discounted-lemon signings can be deliberate: both subjects' exposed summaries include assessing the rent against the reduced lemon value. A positive immediate payoff does not establish optimality relative to further search.

| Mean focal tenant net on the four true-cost cells | Original | Rerun |
|---|---:|---:|
| Claude | $41.79 | $130.38 |
| Codex | $293.04 | $179.29 |
| Codex minus Claude | $251.26 | $48.91 |

Claude avoided its original two small losses and bought a different, already-inspected lemon in world 300005. The shrinking gap supports sensitivity to bargaining choices; it does not establish a ranking or isolate the effect of summary-display settings from fresh sampling.

## Reproduce

From this checkout, using an environment with the repository dependencies and authenticated CLIs:

```sh
PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/housing_reasoning_diagnostic.py --subject claude_opus55 --base runs/reasoning_capture_new
PYTHONPATH=src:tools/cli_subjects python tools/cli_subjects/housing_reasoning_diagnostic.py --subject codex_sol61 --base runs/reasoning_capture_new
python tools/cli_subjects/housing_reasoning_export.py runs/reasoning_capture_new
```

Use `--limit 1` and a separate base for capture canaries. Existing diagnostic roots are refused. Original runs remain unchanged. Actual local outputs are under `housing-lemons-outside-demand/runs/reasoning_capture_20261009/`; raw captures and transcripts are not published in Git. Costs for the final reruns were $0.8273 Claude and $0.5676 Codex at list-price token accounting, not subscription charges.
