# TERMS-Bench reproduction: declared plan, v1

**Status:** declared on 2026-10-19, before any code, pack or model call for this identity. The owner approved the
design on 2026-10-18. Every later change to a control below is a new identity, never an edit to this one. An addendum
may add measured numbers (Stage 2 and 3) before the freeze; it may not change the test.

## 1. Question

Does AERead's reimplementation of TERMS-Bench (Zhang et al. 2026, arXiv 2605.13909v2) rank the paper's own agents as
the paper's Table 16 ranks them, on the three counterpart families AERead implements (Candid, Expressive, Taciturn),
when the agents are given the paper's protocol?

The four published pilots answer a weaker question: they ordered two of the paper's agents as the paper does, with every
absolute level displaced. The 2026-10-18 design review traced the displacement to the protocol, not to the agent
scaffold (TB-J-01): our prompt stated no objective and no rule (TB-D-06), our observation was not the paper's (TB-D-07),
a malformed move removed the episode from the surplus measures instead of the paper's fallback (TB-D-08), and the world
geometry differed from the paper's stated one (TB-D-09). This plan removes those differences and tests the ranking.

## 2. Identity: `termsbench_repro_v1`

What changes from the pilots, and why:

| Control | Pilots | This identity | Row |
|---|---|---|---|
| Agent prompt | no objective, no rule | the paper's buyer and seller prompts (Fig. 20): payoff, "lower is better" (buyer), never accept beyond the reservation value, avoid anchoring at the reservation value, belief block; `price: null` for a non-offer | TB-D-06, TB-D-05 |
| Observation | full transcript | the paper's five-key payload: rounds remaining, legal decisions, offer on the table, utility of accepting now, opener; last six rounds of history | TB-D-07 |
| Malformed move | episode removed from SE+ and AGR+ | the paper's deterministic fallback; an Accept that carries a price executes at the standing offer. The old rule is reported as a sensitivity | TB-D-08 |
| World geometry | R = 200, Δ ~ U[20, 100], buyer only, one quintile-boundary seed per difficulty bin | generator v0.2.0: price range [0, 100], Δ ~ U[10, 40], no-deal gap ~ U[10, 40], role × opener balanced 2 × 2, uniform draws, fresh seeds | TB-D-09 |
| Output budget | 4,000 or 12,000 tokens, doubled on truncation up to 48,000 | 16,000 tokens; a truncated answer is typed `length` and not retried; transport errors retried 3 times | review issue 7 |
| Reasoning | none declared, or a suppressing cap | as the paper's Table 9 states per model, declared per route and checked at profile admission by the reasoning tokens actually used; a route that cannot honour it is recorded and its model dropped | review issue 4 |

`environment.py` is not edited, so the published pilots keep replaying from current source. The new prompt and
observation live in a new harness module; the fallback rule is a new plugin version.

## 3. Subjects

**Primary, the seven frontier agents in Table 16 that are reachable under the kernel's route rules** (an endpoint that
accepts a declared seed, with fallbacks disabled). Routes as queried on 2026-10-19; the five-field route seal is the
identity, and a tier OpenRouter does not distinguish (flex, priority) is a stated limit.

| Agent | Route | Paper SE+ (three families, overlap) |
|---|---|---:|
| GLM-5.1 | Nebius, fp8 (`z-ai/glm-5.1-20260406`) | 0.668 |
| Gemini 3.1 Pro | Google AI Studio | 0.635 |
| DeepSeek V4 Pro | DeepInfra, fp8 | 0.616 |
| Kimi K2.6 | Parasail, int4 | 0.590 |
| Grok 4.20 | xAI | 0.586 |
| Qwen3.6-Plus | Alibaba | 0.584 |
| GPT-5.4 | OpenAI | 0.517 |

**Anchor:** GPT-4o-mini (OpenAI), the paper's weakest agent (0.196).

**Not run:** Claude Opus 4.6 and 4.7 (no endpoint accepts a declared seed; the kernel's seed rule is kept), Doubao 2.0
(not on OpenRouter), GPT-5.5 (cost), Gemma 4 (not in Table 16). Claude Code and Codex are outside this plan.

Temperature 0 where the route accepts it; GPT-5.x routes do not, and that is sealed as unavailable.

## 4. Corpus

- **Confirmatory:** 48 overlap worlds = 3 families × 2 roles × 2 openers × 4, plus 12 no-deal worlds (2 per family ×
  role) for the violation and false-agreement levels. Seeds from the generator's cell formula with block b = 2,
  disjoint from the pilot corpus and from development.
- **Development:** block b = 1, used only for Stages 1 to 3.
- One rollout per world per agent; every agent plays every world.

## 5. Primary test

The 13 pairs of frontier agents that Table 16 separates: a gap in three-family overlap SE+ larger than
1.96 · √2 · 0.25/√300 = 0.040.

| Higher in the paper | Lower in the paper |
|---|---|
| GLM-5.1 | DeepSeek V4 Pro, Kimi K2.6, Grok 4.20, Qwen3.6-Plus, GPT-5.4 |
| Gemini 3.1 Pro | Kimi K2.6, Grok 4.20, Qwen3.6-Plus, GPT-5.4 |
| DeepSeek V4 Pro | GPT-5.4 |
| Kimi K2.6, Grok 4.20, Qwen3.6-Plus | GPT-5.4 |

Each pair's difference is the world-paired mean difference in overlap SE+ over the 48 worlds.

- **Reproduced:** at least 12 of 13 pairs in the paper's order (exact permutation one-sided p ≈ 0.035), and every
  frontier agent above GPT-4o-mini on both SE+ and AGR+.
- **Not reproduced:** 8 or fewer of 13 in the paper's order, or any pair reversed with a two-sided paired t test
  significant after Holm across the 13.
- **Inconclusive:** otherwise.

Headline estimate: Kendall τ_b between our and the paper's order of the seven, with a world-bootstrap 95% interval.
AGR+ is not ranked: the paper's frontier spans only 95% to 99.9%.

If an agent is dropped (Section 8), its pairs leave the test and the rule becomes "all but at most one of the remaining
resolved pairs"; with fewer than 8 remaining pairs the result is inconclusive by declaration.

## 6. Secondary, descriptive

- Levels against the paper per agent: SE+, CSE+, AGR+, FAGR−, CritViol.
- The old malformed-move rule as a sensitivity on the same cells.
- Fixed-concession baselines FC1, FC10 and FC30 played offline through the same environment and corpus. The rule
  assumed (the paper does not state it): open at the price bound, concede the stated share of the remaining distance
  to the reservation value each turn, accept any counterpart offer within the reservation value.
- The sign of the paper's cue penalty by family.

## 7. Power

Simulated with per-world SD 0.27 (pilot overlap SE+) and within-world correlation 0.5 to 0.7:

| Overlap worlds | Our gaps equal the paper's | Gaps shrink by 30% | Shrink by 30% and each agent drifts by SD 0.02 |
|---:|---|---|---|
| 48 | 0.77 to 0.89 | 0.58 to 0.73 | 0.44 to 0.54 |
| 96 | 0.91 to 0.96 | 0.78 to 0.89 | 0.57 to 0.63 |

48 worlds is what the budget allows; a "not reproduced" verdict is therefore strong evidence and an "inconclusive" one is
not. Scripts: `aeread-run-backups/design-reviews-2026-10-18/termsbench/scripts/power*.py`.

## 8. Stages, gates and stops

| Stage | What | Gate to continue |
|---|---|---|
| 0, offline | harness, plugin version, generator v0.2.0, tests, `qc.md`; FC baselines on development seeds; a manual trace of one cell | FC1 < FC10 < FC30 on SE+; FC SE+ within ±0.03 of the paper's .249/.266/.374; median ZOPA width near the paper's 24.6 |
| 1, about $0.01 | GPT-4o-mini on the 30 pilot cases under the new protocol | none; descriptive: does the level shift close? |
| 2 | profile admission and one full trajectory per agent | measured tokens, cost and seconds a call; if 48 worlds project above $20 in total, stop and ask |
| 3 | 12-world variance pilot on development seeds | none on outcomes; records the variance for the addendum |
| 4 | freeze (addendum with Stage 2 and 3 numbers, test unchanged), then the confirmatory | — |

Stops during the confirmatory: a hard ceiling of $22 across all agents; a per-agent ceiling of 1.5 times its Stage 2
projection; a 4-hour serial wall-time gate per agent; an agent halts after 3 consecutive failures; a failed cell is typed
missingness and never rerun; an agent with more than 10% of cells missing leaves the test.

## 9. Quality control

The family gets a QC profile, beside this plan, before Stage 1. Gate 1: generator geometry and FC
baselines as in Stage 0. Gate 2: `aeread verify-replay` on every published cell. Gate 3: FC ordering, and GPT-4o-mini
below every frontier agent in the development pilot. Gate 4: routes, reasoning tokens and temperatures sealed per
agent. Gate 5: this plan, its addendum and the freeze.

## 10. Budget

OpenRouter balance on 2026-10-18: $23.96. Estimated cost of the confirmatory at about 1,000 output tokens a call: $21;
at 3,000: $52. GPT-5.4 and Gemini 3.1 Pro are about 60% of it. Stage 2 decides whether a top-up is needed.

## 11. Known gaps in the paper's specification

The paper names but does not value the four ε constants, and its Table 10 generation parameters are circular with
Section C.6; the adapter sets ε to 1e-6 and takes the geometry from H.2 and Fig. 21. The fixed-concession rule is
assumed (Section 6). None of these has been raised with the author.
