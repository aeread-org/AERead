# housing_lemons_price_v15_probe: Section 7's one-call admission probe, after the fact, and a sealed-call audit

The v15 plan (Section 7) asked for a one-call probe of structured output and reasoning tokens for each profile before
the freeze. It was never built (HL-J-14). `src/aeread_families/housing/price_v15_probe.py`, committed before the probe
ran (9e38c6c3), runs it now. Because this is after the freeze, Gate 4 stays `partial`. Reproduce the audit, with no
call sent:

    PYTHONPATH=src python -m aeread_families.housing.price_v15_probe --runs <v15 run root> --out <dir>

Add `--probe` to send the two calls ($0.002 in total on 2026-10-19).

**Why every sealed v15 call shows `reasoning_tokens: null`.** `OpenRouterChatClient` (`execution.py`) builds its
`ProviderResult` without the provider's reasoning count; only `ArenaChatClient` copies it. The provider does report the
count. It sits in each sealed raw response at `usage.completion_tokens_details.reasoning_tokens`, which is where this
probe and audit read it.

**The probe** (`reports/probe.json`, `probe`): each profile's first sealed admission request, rebuilt to the same
`request_sha256`, sent once.

| Profile | Declared tier | Structured output | Reasoning tokens (probe / that call when sealed) | Cost |
|---|---|---|---|---:|
| GPT-6 Luna | low | passed (`{"decision":"inspect","listing_id":0}`) | 127 / 223 | $0.0002 |
| Gemini 3.8 Flash | minimal | passed (same action) | 209 / 209 | $0.0017 |

**The audit** (`reports/probe.json`, `audit`): every sealed seat-0 call of the v15 run roots. Only seat 0's calls reach
OpenRouter; the outside seats are answered by the scripted provider.

| Identity | Seat-0 calls | With a provider count | Reasoning tokens min / median / max (zero) | Cached share of input |
|---|---:|---:|---|---:|
| admission Luna | 9 | 9 | 0 / 223 / 440 (2) | 21% |
| admission Gemini | 12 | 12 | 0 / 440 / 994 (1) | 0% |
| pilot Luna | 420 | 420 | 0 / 215 / 685 (24) | 37% |
| pilot Gemini | 429 | 429 | 0 / 310 / 1,102 (25) | 0% |
| confirmatory Luna | 2,928 | 2,928 | 0 / 230.5 / 793 (130) | 31% |
| confirmatory Luna A/A | 2,589 | 2,589 | 0 / 225 / 750 (100) | 40% |
| confirmatory Gemini | 3,246 | 3,246 | 0 / 276 / 1,915 (287) | 0% |

Both declared tiers took effect: every seat-0 call reports a reasoning count, and the tier reasons on the large
majority of calls. Gemini's "minimal" still reasons about 276 tokens at the median. Prompt caching hit for Luna's route
(21–40% of input tokens) and never for Gemini's.
