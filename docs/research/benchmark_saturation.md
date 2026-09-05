# Tier 0: screening a benchmark from its score table

The only measurement that scales to a large field, what it cannot answer, and why that
limit is the argument for a per-case oracle.

**Status: a method note, not shipped code.** The statistic is ten lines and is stated in
full in §2 and §3 so anyone can reimplement it. The 23-benchmark survey in §4 was
auto-extracted and is reported with that caveat.

---

## 1. Why this tier exists

A common cardinal scale across benchmarks needs a common referent, and most benchmarks
have no computed optimum. So "fraction of attainable value" cannot be had at scale.

One thing can: **does the benchmark still separate models**. That needs only the
published results table. No oracle, no adapter, no execution, no domain knowledge. It is
therefore the only screen applicable to an arbitrary number of benchmarks, and it is
triage rather than measurement: it says where to spend the expensive tiers.

## 2. The statistic

For a benchmark's headline metric across `n >= 3` named models:

```
frontier_share = (best - third_best) / (best - worst)
```

A large share means the field's best models still separate. A small share means they
cluster. Where the metric has a known maximum, also compute `best / maximum`.

## 3. The classification, and the trap it avoids

A tight frontier has **two opposite causes**, and a scale-free spread statistic cannot
tell them apart:

| verdict | condition | meaning |
|---|---|---|
| `discriminates` | frontier_share >= 0.20 | the field separates its best models |
| `exhausted` | tight frontier, best >= 85% of maximum | retire or raise difficulty |
| `uniform_failure` | tight frontier, best well below maximum | **nobody has solved it**, which is a good benchmark |
| `undecidable` | tight frontier, **no known maximum** | cannot tell exhausted from unsolved |

Treating a tight frontier as "saturated" is the trap. SWE-bench launched at a 1.96%
resolve rate: every model failed, at the same level, and it became the standard benchmark
of its era. A screen that flagged it as saturated would have been exactly wrong.

## 4. The field, measured

23 economic-domain benchmarks with a per-model table, extracted from a local PDF corpus
at zero API cost.

| verdict | count |
|---|---|
| discriminates | 12 |
| uniform_failure | 4 |
| undecidable | 4 |
| exhausted | 3 |

**Exhausted (3).** Alympics (30 models, 8 tied at 1.00, frontier share 0.0%),
NegotiationArena (1.00), FinanceBench (85 of 100).

**Uniform failure (4), and these are the healthy ones.** STEER's best model reaches
**0.33** of 1.0. Market-Bench's best reaches **0.19**. TERMS-Bench's best SEπ+ is
**0.69**. "How far are we on decision-making" tops out at **0.70**. Under a spread-only
statistic all four look identical to the exhausted three and mean the opposite.

**Undecidable (4), and this is the finding.** AgenticPay tops out at **86.9**,
Algorithmic Collusion at **1.92**, Measuring Bargaining Abilities at **-33.81**, Economic
Rationality under Specialization at **100**. Their frontiers are tight and their metrics
have no stated maximum, so **nobody can say whether the best score is near-perfect or
barely trying**, including the authors.

## 5. What that buys the oracle argument

The usual case for a per-case oracle is cross-benchmark comparability. That is true and
abstract. The sharper case is visible in the `undecidable` column:

> Without a computed optimum a benchmark cannot interpret its own headline number.

AgenticPay reports 86.9 on hand-tuned points where quality, efficiency and deal bonuses
are summed with fixed weights. 86.9 out of what an agent could actually have achieved is
unanswerable, so "the frontier is close together at 86.9" supports no conclusion at all.
Four of twenty-three benchmarks in this field are in that position.

The same test applied to AERead's own housing case: gemini-3.7 at **0.400** and
deepseek-v4-flash at **0.389** of the computed optimum, indistinguishable from each
other. That is a `uniform_failure` reading rather than a broken benchmark, and it can be
stated with confidence **only because the optimum is computed**. With hand-tuned points
those same numbers would be as uninterpretable as 86.9.

So the oracle is not primarily for ranking across benchmarks. It is what makes a single
benchmark's own result legible.

## 6. Honest limits

- **Metrics are not commensurable.** `frontier_share` is a shape statistic. It compares
  the geometry of score distributions, never quality across benchmarks.
- **Panel size is not controlled.** Top-3-of-4 and top-3-of-30 are structurally
  different; Alympics has 30 models and the game-theoretic workflow paper has 4. The
  statistic should be normalised for panel size before any ranking is published.
- **No dates attached.** Saturation decays as models improve, so every row needs its
  evaluation date. The dataset does not yet carry one.
- **The 23-benchmark survey behind §4 was auto-extracted** from PDF text by a model and
  has NOT been hand-verified row by row, so it is not shipped here. Only the small seed
  set in `src/aeread/data/` was read from the papers directly. Publishing unverified
  numbers attributed to other people's work would risk misrepresenting their results;
  reproduce the survey yourself before citing its counts.
- **The thresholds are conventions.** 0.20 for frontier share and 0.85 for ceiling
  fraction were chosen for legibility, not derived.

## 7. Reimplementing it

Everything needed is four fields per benchmark: name, headline metric, per-model scores,
and the metric's maximum where one exists. The fourth field is the one that decides
whether the result is interpretable at all.

```python
def classify(scores, ceiling=None, frontier_k=3):
    v = sorted(scores, reverse=True)
    if len(v) < 3:
        return "insufficient_models"
    total = v[0] - v[-1]
    share = (v[0] - v[min(frontier_k, len(v)) - 1]) / total if total > 0 else 0.0
    if total > 0 and share >= 0.20:
        return "discriminates"
    if not ceiling:
        return "undecidable"
    return "exhausted" if v[0] / ceiling >= 0.85 else "uniform_failure"
```

Worked examples:

```python
classify([86.9, 82.2, 81.7, 63.9, 32.5])              # 'undecidable'   AgenticPay GlobalScore
classify([0.33, 0.32, 0.31, 0.05, -0.43], 1.0)        # 'uniform_failure'  STEER
classify([1.0, 1.0, 1.0, 0.6, 0.1], 1.0)              # 'exhausted'
classify([2217.9, 1200, 700, 400, 273.7])             # 'discriminates'  Vending-Bench
```

The thresholds (0.20, 0.85) are conventions chosen for legibility, not derived. Report
them alongside any verdict so a reader can disagree with them.
