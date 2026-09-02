"""Faithful, from-scratch reimplementation of TERMS-Bench's counterpart kernel
and difficulty grader.

Pinned source: "TERMS-Bench: Diagnosing LLM Negotiation Agents Beyond Deal
Rate", arXiv 2605.13909v2 -- ``upstream-termsbench-paper/paper.html``
(sha256 ``d62f52687a3d03a1fd3252501baed1bcb432bb2857edd66208de34eb26cb1848``)
and ``paper.pdf`` (sha256
``bea6a0a272f9e4f97539ebace7936239926268cb71c83f8d00203ba8398b1dcf``). There is
no upstream code -- the paper's own repository link is dead -- so every
function below is an **aeread reimplementation from paper**, never a "port".
Each function cites the paper equation it transcribes. See
``docs/termsbench_adapter_spec.md`` sections 1 and 3.

Constants fall into two provenance classes, kept visually distinct below:

* Pinned verbatim from Table 3, Table 4, Table 5, or Table 6 -- these must
  never be changed without a spec amendment citing a new paper version.
* "AERead choice" -- knobs the paper's own text never resolves to a number.
  In particular, Appendix C.6 ("Numerical defaults for (ακ, βκ, α_shifted,
  β_shifted, Δmin, Δmax, gmin, gmax) are listed in Appendix C.6") and Table 10
  ("regime-specific task generation parameters ... are provided in Table 10")
  point at *each other* and neither section actually contains the numbers, in
  both the pinned HTML and PDF renderings. This is a gap in the published
  paper, not an extraction bug on our side. Per
  ``docs/termsbench_adapter_spec.md`` section 3 ("AERead owns: translating
  that mechanism into code"), we pick concrete values once here and freeze
  them by ``generator_version``; see the spec's amendment note.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

StanceType = str  # one of "conciliatory", "neutral", "aggressive"

STANCE_TYPES: tuple[StanceType, ...] = ("conciliatory", "neutral", "aggressive")

# ---------------------------------------------------------------------------
# Table 3 / Table 4: family presets (pinned verbatim).
# ---------------------------------------------------------------------------

# Table 4: economic presets, keyed by preset name. Coefficients ordered
# (conciliatory, neutral, aggressive) in the paper; stored here as dicts keyed
# by stance name to avoid positional-index bugs.
ECONOMIC_PRESETS: Mapping[str, Mapping[str, Mapping[StanceType, float]]] = {
    "type_instrumental": {
        "rho": {"conciliatory": 0.0, "neutral": -0.25, "aggressive": -0.75},
        "xi": {"conciliatory": 0.40, "neutral": 0.0, "aggressive": -0.50},
        "lambda2": {"conciliatory": 0.30, "neutral": 0.50, "aggressive": 1.00},
    },
    "high_reactivity": {
        "rho": {"conciliatory": 0.0, "neutral": -0.75, "aggressive": -1.50},
        "xi": {"conciliatory": 0.40, "neutral": 0.0, "aggressive": -0.75},
        "lambda2": {"conciliatory": 0.45, "neutral": 0.90, "aggressive": 1.80},
    },
}

# Table 3: the 3 families implemented this cycle (Candid, Taciturn,
# Expressive -- docs/termsbench_adapter_spec.md section 6). cue_channel names
# feed both the cue generator below and the difficulty grader's d_cue lookup
# (Appendix G.1).
FAMILY_PRESETS: Mapping[str, Mapping[str, str]] = {
    "candid": {
        "economic_preset": "type_instrumental",
        "cue_channel": "accurate",
        "price_noise_tier": "low",
    },
    "taciturn": {
        "economic_preset": "type_instrumental",
        "cue_channel": "uninformative",
        "price_noise_tier": "low",
    },
    "expressive": {
        "economic_preset": "high_reactivity",
        "cue_channel": "accurate",
        "price_noise_tier": "moderate",
    },
}
FAMILIES: tuple[str, ...] = tuple(FAMILY_PRESETS)

# ---------------------------------------------------------------------------
# Table 5: shared acceptance / walk-away / counter-offer hyperparameters
# (pinned verbatim).
# ---------------------------------------------------------------------------

ALPHA = 6.0
BETA = 1.0
GAMMA = 2.0
PHI_0 = -4.5
PHI_DELTA = 30.0
PHI_T = 1.5
LAMBDA_0 = 0.12
LAMBDA_1 = 0.28
LAMBDA_3 = 0.10
LAMBDA_4 = 0.10
TAU_RIGID = 0.10
# sigma_bar_p^{low,mod,high}: normalized additive price-noise scale.
PRICE_NOISE_SCALE_BY_TIER: Mapping[str, float] = {
    "low": 0.01,
    "moderate": 0.03,
    "high": 0.08,
}

# ---------------------------------------------------------------------------
# Table 6: opening-offer and cue-generation hyperparameters (pinned verbatim).
# ---------------------------------------------------------------------------

D_OPEN_MIN = 0.20
D_OPEN_MAX = 0.80
OMEGA_KAPPA = 0.30
OMEGA_ETA = 0.15
OMEGA_ETA_PRIME = 0.15
PHI_MIN = 0.5
PHI_MAX = 1.5
OPENING_NOISE_SCALE = 0.02  # sigma_bar_0
TAU_DEAD = 0.80
TAU_CONC = 0.10
B_CONCEDE = 1.0
B_HOLD = 0.5
B_PRESSURE = 1.0
ALPHA_C = 2.0
ALPHA_P = 2.0
BETA_C = 1.0
MU_S = 1.0
TAU_S = 0.5
SIGMA_S = 0.75

# ---------------------------------------------------------------------------
# Confirmed elsewhere in the paper (Appendix D's backward-induction sizing
# note: "With N~=300, M=50, K=10, ..."), not from Table 10 itself.
# ---------------------------------------------------------------------------

DEFAULT_HORIZON = 10  # K

# ---------------------------------------------------------------------------
# AERead choice -- see module docstring. Small numerical-stability constants
# the paper names (epsilon_kappa, epsilon_sigma, epsilon_d, epsilon_c) but
# never assigns a value to.
# ---------------------------------------------------------------------------

EPS_KAPPA = 1e-6
EPS_SIGMA = 1e-6
EPS_D = 1e-6
EPS_C = 1e-6

# ---------------------------------------------------------------------------
# AERead choice -- regime-generator numeric ranges. The public price scale
# and Overlap ZOPA width reuse docs/termsbench_adapter_spec.md section 4's own
# golden common-setup numbers (R=200, Delta=50) as the generator's fixed
# defaults rather than inventing an unrelated second scale. Beta(2, 2) is
# symmetric with mean 0.5, matching the golden section's kappa_B=0.5 baseline
# illustration.
# ---------------------------------------------------------------------------

P_MIN = 0.0
P_MAX = 200.0
ZOPA_WIDTH_MIN = 20.0
ZOPA_WIDTH_MAX = 100.0
NODEAL_GAP_MIN = 20.0
NODEAL_GAP_MAX = 100.0
BETA_KAPPA_ALPHA = 2.0
BETA_KAPPA_BETA = 2.0


def k_walk(K: int) -> int:
    """Appendix C.2.2: k_walk = ceil(K/2)."""
    return math.ceil(K / 2)


def sigmoid(x: float) -> float:
    """Numerically stable logistic function sigma(.)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def norm_cdf(x: float) -> float:
    """Standard normal CDF Phi(.), used by the sentiment-cue model (C.5.2)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


# ---------------------------------------------------------------------------
# Appendix C.3: agent history features (eq. 12-14).
# ---------------------------------------------------------------------------


def agent_role_sign(agent_role: str) -> float:
    """s_A: +1 for a buyer agent, -1 for a seller agent."""
    if agent_role == "buyer":
        return 1.0
    if agent_role == "seller":
        return -1.0
    raise ValueError(f"agent_role must be 'buyer' or 'seller', got {agent_role!r}")


@dataclass(frozen=True, slots=True)
class HistoryFeatures:
    concede_magnitude: float
    concede_speed: float
    rigidity: float


def agent_history_features(
    agent_offers: Sequence[float], *, agent_role: str, price_range: float
) -> HistoryFeatures:
    """ConcedeMagnitude_k, ConcedeSpeed_k, Rigidity_k (eq. 12-14).

    ``agent_offers`` is the agent's own past OFFER prices in chronological
    order (Accept/Reject do not append). Boundary condition (App. C.3, App.
    D.2): fewer than two agent offers => all three features are 0.
    """
    if len(agent_offers) < 2:
        return HistoryFeatures(0.0, 0.0, 0.0)
    s_a = agent_role_sign(agent_role)
    # J_k := {j : max(2, k-3) <= j <= k-1} indexes 1-based *prior* offers; in
    # 0-based Python terms this is "the most recent up-to-3 consecutive
    # agent-offer deltas", i.e. deltas between agent_offers[-4:].
    window = agent_offers[-4:]
    deltas = [
        s_a * (window[i] - window[i - 1]) for i in range(1, len(window))
    ]
    concede_speed = sum(delta / price_range for delta in deltas) / len(deltas)
    concede_magnitude = sum(max(0.0, delta) / price_range for delta in deltas) / len(
        deltas
    )
    last_delta = s_a * (agent_offers[-1] - agent_offers[-2])
    rigidity = 1.0 if (max(0.0, last_delta) / price_range) < TAU_RIGID else 0.0
    return HistoryFeatures(concede_magnitude, concede_speed, rigidity)


# ---------------------------------------------------------------------------
# Section 3.2 / Appendix C.2: acceptance and walk-away (eq. 5-7).
# ---------------------------------------------------------------------------


def counterpart_role_sign(counterpart_role: str) -> float:
    """s_B: +1 for a seller counterpart, -1 for a buyer counterpart."""
    if counterpart_role == "seller":
        return 1.0
    if counterpart_role == "buyer":
        return -1.0
    raise ValueError(f"counterpart_role must be 'buyer' or 'seller', got {counterpart_role!r}")


def normalized_favorability(
    agent_price: float, r_b: float, counterpart_role: str, price_range: float
) -> float:
    """Delta_bar_k (eq. 5, unnumbered display before eq. 5 in Sec. 3.2)."""
    if counterpart_role == "seller":
        return (agent_price - r_b) / price_range
    return (r_b - agent_price) / price_range


def deadline_clock(round_k: int, horizon: int) -> tuple[float, float]:
    """D_tilde_k = sqrt(k/K) and its complement D_tilde_bar_k = 1 - D_tilde_k."""
    d_tilde = math.sqrt(round_k / horizon)
    return d_tilde, 1.0 - d_tilde


def acceptance_probability(
    *,
    delta_bar: float,
    kappa_b: float,
    d_tilde_bar: float,
    rho: float,
    xi: float,
    concede_speed: float,
    rigidity: float,
) -> float:
    """a_k (eq. 5-6)."""
    if delta_bar < 0.0:
        return 0.0
    g_theta = (
        ALPHA * delta_bar
        + BETA * kappa_b
        - GAMMA * d_tilde_bar
        + rho * concede_speed
        + xi * rigidity
    )
    return sigmoid(g_theta)


def walkaway_clock(round_k: int, horizon: int, walk_round: int) -> float:
    """tau_k^W (eq. 7's display)."""
    if horizon == walk_round:
        return 1.0 if round_k >= walk_round else 0.0
    return clip((round_k - walk_round) / (horizon - walk_round), 0.0, 1.0)


def walkaway_hazard(
    *, round_k: int, horizon: int, delta_bar: float
) -> float:
    """omega_k (eq. 7)."""
    walk_round = k_walk(horizon)
    if round_k < walk_round or delta_bar >= 0.0:
        return 0.0
    shortfall = max(0.0, -delta_bar)
    tau_w = walkaway_clock(round_k, horizon, walk_round)
    return sigmoid(PHI_0 + PHI_DELTA * shortfall + PHI_T * tau_w)


# ---------------------------------------------------------------------------
# Section 3.2 / Appendix C.2.2: counter-offer rule (eq. 8-9).
# ---------------------------------------------------------------------------


def concession_rate(
    *,
    kappa_b: float,
    eta_b: StanceType,
    lambda2: float,
    concede_magnitude: float,
) -> float:
    """lambda_B (eq. 8), clipped to [0, 1]."""
    raw = (
        LAMBDA_0
        + LAMBDA_1 * kappa_b
        - lambda2 * concede_magnitude
        - LAMBDA_3 * (1.0 if eta_b == "aggressive" else 0.0)
        + LAMBDA_4 * (1.0 if eta_b == "conciliatory" else 0.0)
    )
    return clip(raw, 0.0, 1.0)


def monotone_feasible_interval(
    *, counterpart_role: str, r_b: float, prior_counterpart_price: float
) -> tuple[float, float]:
    """M_B(k) (eq. 9's display): [r_B, p_{k-1}^B] for a seller, reversed for a buyer."""
    if counterpart_role == "seller":
        return (r_b, prior_counterpart_price)
    return (prior_counterpart_price, r_b)


def counter_offer_price(
    *,
    counterpart_role: str,
    r_b: float,
    prior_counterpart_price: float,
    lambda_b: float,
    price_noise: float,
) -> float:
    """p_k^B (eq. 8-9): deterministic concession mean, projected onto M_B(k)."""
    mean = prior_counterpart_price - lambda_b * (prior_counterpart_price - r_b)
    raw = mean + price_noise
    lower, upper = monotone_feasible_interval(
        counterpart_role=counterpart_role, r_b=r_b, prior_counterpart_price=prior_counterpart_price
    )
    lower, upper = min(lower, upper), max(lower, upper)
    return clip(raw, lower, upper)


# ---------------------------------------------------------------------------
# Appendix C.4: opening-offer model (eq. 15-16).
# ---------------------------------------------------------------------------


def opening_slack(*, counterpart_role: str, r_b: float, p_min: float, p_max: float) -> float:
    """S_B^open."""
    if counterpart_role == "seller":
        return p_max - r_b
    return r_b - p_min


def opening_modulation(*, kappa_b: float, eta_b: StanceType) -> float:
    """phi(kappa_B, eta_B) (eq. 16)."""
    raw = (
        1.0
        - OMEGA_KAPPA * kappa_b
        + OMEGA_ETA * (1.0 if eta_b == "aggressive" else 0.0)
        - OMEGA_ETA_PRIME * (1.0 if eta_b == "conciliatory" else 0.0)
    )
    return clip(raw, PHI_MIN, PHI_MAX)


def opening_offer_price(
    *,
    counterpart_role: str,
    r_b: float,
    kappa_b: float,
    eta_b: StanceType,
    opening_harshness: float,
    p_min: float,
    p_max: float,
    opening_noise: float,
) -> float:
    """p_init^B (eq. 15), projected onto B_B = [r_B, p_max] or [p_min, r_B]."""
    s_b = counterpart_role_sign(counterpart_role)
    slack = opening_slack(counterpart_role=counterpart_role, r_b=r_b, p_min=p_min, p_max=p_max)
    phi = opening_modulation(kappa_b=kappa_b, eta_b=eta_b)
    raw = r_b + s_b * opening_harshness * phi * slack + opening_noise
    if counterpart_role == "seller":
        lower, upper = r_b, p_max
    else:
        lower, upper = p_min, r_b
    return clip(raw, lower, upper)


# ---------------------------------------------------------------------------
# Appendix C.5: cue generation (sentiment + strategic posture).
# ---------------------------------------------------------------------------

SentimentCue = str  # "positive" | "neutral" | "negative"
StrategicCue = str  # "Concede" | "Hold" | "Pressure"


def sentiment_cue_from_score(latent_score: float) -> SentimentCue:
    """s_tilde^base from the thresholded latent-score model (C.5.2)."""
    if latent_score > TAU_S:
        return "positive"
    if latent_score < -TAU_S:
        return "negative"
    return "neutral"


def sentiment_latent_mean(eta_b: StanceType) -> float:
    if eta_b == "conciliatory":
        return MU_S
    if eta_b == "aggressive":
        return -MU_S
    return 0.0


def counterpart_concession_magnitude(
    *, counterpart_price: float, prior_counterpart_price: float | None, r_b: float
) -> float:
    """C_k^B (eq. 33 / C.5's display), 0 under the boundary convention."""
    if prior_counterpart_price is None:
        return 0.0
    numerator = abs(counterpart_price - prior_counterpart_price)
    denominator = abs(prior_counterpart_price - r_b) + EPS_C
    return min(1.0, numerator / denominator)


_STANCE_BIAS: Mapping[StanceType, Mapping[StrategicCue, float]] = {
    "conciliatory": {"Concede": B_CONCEDE, "Hold": 0.0, "Pressure": -B_CONCEDE},
    "neutral": {"Concede": 0.0, "Hold": B_HOLD, "Pressure": 0.0},
    "aggressive": {"Concede": -B_PRESSURE, "Hold": 0.0, "Pressure": B_PRESSURE},
}


def strategic_cue_logits(
    *, eta_b: StanceType, concession_magnitude_b: float, deadline_tilde: float
) -> Mapping[StrategicCue, float]:
    """ell_k(.) (eq. 32's display) for the offer branch."""
    bias = _STANCE_BIAS[eta_b]
    return {
        "Concede": bias["Concede"] + ALPHA_C * (concession_magnitude_b - TAU_CONC),
        "Hold": bias["Hold"],
        "Pressure": bias["Pressure"]
        + ALPHA_P * (deadline_tilde - TAU_DEAD)
        - BETA_C * concession_magnitude_b,
    }


def softmax(logits: Mapping[str, float]) -> dict[str, float]:
    values = list(logits.values())
    m = max(values)
    exps = {key: math.exp(value - m) for key, value in logits.items()}
    total = sum(exps.values())
    return {key: value / total for key, value in exps.items()}


def sample_categorical(probabilities: Mapping[str, float], u: float) -> str:
    """Deterministic inverse-CDF categorical draw over a fixed key order."""
    cumulative = 0.0
    keys = list(probabilities)
    for key in keys:
        cumulative += probabilities[key]
        if u < cumulative:
            return key
    return keys[-1]


@dataclass(frozen=True, slots=True)
class CueDraw:
    sentiment_cue: SentimentCue
    strategic_cue: StrategicCue


def generate_cues(
    *,
    family: str,
    resolved_action: str,  # "accept" | "reject" | "offer"
    eta_b: StanceType,
    round_k: int,
    horizon: int,
    counterpart_price: float | None,
    prior_counterpart_price: float | None,
    r_b: float,
    sentiment_noise: float | None,
    posture_u: float | None,
) -> CueDraw:
    """(s_tilde_k, c_tilde_k) per Appendix C.5.1-C.5.3, restricted to the 3
    families implemented this cycle (Candid/Expressive: base cue model;
    Taciturn: collapsed to neutral/Hold)."""
    cue_channel = FAMILY_PRESETS[family]["cue_channel"]
    if cue_channel == "uninformative":
        return CueDraw("neutral", "Hold")

    if sentiment_noise is None:
        raise ValueError("sentiment_noise draw is required for an informative cue channel")
    latent_score = sentiment_latent_mean(eta_b) + sentiment_noise
    sentiment = sentiment_cue_from_score(latent_score)

    if resolved_action == "accept":
        return CueDraw(sentiment, "Concede")
    if resolved_action == "reject":
        return CueDraw(sentiment, "Pressure")

    if posture_u is None:
        raise ValueError("posture_u draw is required to sample the strategic cue for an offer")
    concession_magnitude_b = counterpart_concession_magnitude(
        counterpart_price=counterpart_price,
        prior_counterpart_price=prior_counterpart_price,
        r_b=r_b,
    )
    deadline_tilde, _ = deadline_clock(round_k, horizon)
    logits = strategic_cue_logits(
        eta_b=eta_b,
        concession_magnitude_b=concession_magnitude_b,
        deadline_tilde=deadline_tilde,
    )
    probabilities = softmax(logits)
    strategic = sample_categorical(probabilities, posture_u)
    return CueDraw(sentiment, strategic)


# ---------------------------------------------------------------------------
# Appendix G: difficulty grader (eq. 67, 69), computed only from
# pre-interaction instance properties (Gate 1 check #3).
# ---------------------------------------------------------------------------

_STANCE_HARDNESS_OVERLAP: Mapping[StanceType, float] = {
    "aggressive": 1.0,
    "neutral": 0.5,
    "conciliatory": 0.0,
}
_STANCE_SURFACE_NODEAL: Mapping[StanceType, float] = {
    "conciliatory": 1.0,
    "neutral": 0.5,
    "aggressive": 0.0,
}
_CUE_DIFFICULTY: Mapping[str, float] = {
    "accurate": 0.0,
    "uninformative": 0.5,
    "weak_noisy": 0.75,
    "pressuring": 1.0,
}

# eq. 67's weights (w_z, w_p, w_s); the K=10 fixed-horizon deadline term
# 1{Kmax>Kmin} w_k d_deadline is always omitted this cycle (every case shares
# DEFAULT_HORIZON), per the paper's own renormalization instruction.
_OVERLAP_WEIGHTS = (0.45, 0.25, 0.20)
# eq. 69's weights (v_delta, v_c, v_s), already normalized to sum to 1.
_NODEAL_WEIGHTS = (0.60, 0.25, 0.15)


def overlap_difficulty(
    *, delta: float, price_range: float, kappa_agent: float, kappa_counterpart: float, eta_b: StanceType
) -> float:
    """D_overlap^env (eq. 67), K fixed so the deadline term is dropped."""
    d_zopa = 1.0 - delta / price_range
    d_press = max(
        0.0,
        (kappa_agent - kappa_counterpart) / (kappa_agent + kappa_counterpart + EPS_KAPPA),
    )
    d_stance = _STANCE_HARDNESS_OVERLAP[eta_b]
    w_z, w_p, w_s = _OVERLAP_WEIGHTS
    return (w_z * d_zopa + w_p * d_press + w_s * d_stance) / (w_z + w_p + w_s)


def nodeal_difficulty(
    *, delta: float, sigma_scale: float, cue_channel: str, eta_b: StanceType
) -> float:
    """D_nodeal^env (eq. 69); delta < 0 for no-deal regimes."""
    d_gap = math.exp(delta / (sigma_scale + EPS_SIGMA))
    d_cue = _CUE_DIFFICULTY[cue_channel]
    d_surf = _STANCE_SURFACE_NODEAL[eta_b]
    v_delta, v_c, v_s = _NODEAL_WEIGHTS
    return v_delta * d_gap + v_c * d_cue + v_s * d_surf


# ---------------------------------------------------------------------------
# One counterpart logical action = one realization of the full stochastic
# kernel (docs/termsbench_adapter_spec.md section 3.1). This function is the
# single source of truth for that realization: the harness calls it with
# freshly drawn random numbers, and ``step()`` calls it again with the sealed
# recorded numbers to independently verify the harness's claimed action
# (mirroring tau3_retail's tool-execution replay-and-verify pattern). Every
# ``draws`` entry is a raw standard-normal (mean 0, std 1) or Uniform(0, 1)
# number; this function alone is responsible for scaling them to the model's
# units, so the *recorded evidence* never depends on family/price-scale
# parameters.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CounterpartDecision:
    resolved: str  # "accept" | "reject" | "offer" | "timeout"
    price: float | None
    sentiment_cue: SentimentCue | None
    strategic_cue: StrategicCue | None


def resolve_counterpart_turn(
    *,
    round_k: int,
    horizon: int,
    family: str,
    agent_role: str,
    counterpart_role: str,
    r_b: float,
    kappa_b: float,
    eta_b: StanceType,
    p_min: float,
    p_max: float,
    opening_harshness: float,
    agent_offers: Sequence[float],
    counterpart_offers: Sequence[float],
    draws: Mapping[str, float | None],
) -> CounterpartDecision:
    price_range = p_max - p_min
    preset_name = FAMILY_PRESETS[family]["economic_preset"]
    preset = ECONOMIC_PRESETS[preset_name]
    sigma_p = PRICE_NOISE_SCALE_BY_TIER[FAMILY_PRESETS[family]["price_noise_tier"]] * price_range
    sigma_0 = OPENING_NOISE_SCALE * price_range

    def _require(key: str) -> float:
        value = draws.get(key)
        if value is None:
            raise ValueError(f"{key} draw is required for this counterpart resolution branch")
        return value

    def _opening_price() -> float:
        return opening_offer_price(
            counterpart_role=counterpart_role,
            r_b=r_b,
            kappa_b=kappa_b,
            eta_b=eta_b,
            opening_harshness=opening_harshness,
            p_min=p_min,
            p_max=p_max,
            opening_noise=_require("opening_noise") * sigma_0,
        )

    def _cues(resolved_action: str, price: float | None, prior_price: float | None) -> CueDraw:
        sentiment_noise = draws.get("sentiment_noise")
        return generate_cues(
            family=family,
            resolved_action=resolved_action,
            eta_b=eta_b,
            round_k=round_k,
            horizon=horizon,
            counterpart_price=price,
            prior_counterpart_price=prior_price,
            r_b=r_b,
            sentiment_noise=(None if sentiment_noise is None else sentiment_noise * SIGMA_S),
            posture_u=draws.get("posture_u"),
        )

    if not agent_offers:
        # True counterpart-opens episode start: no agent offer to evaluate,
        # so accept/walk-away are not defined (Sec. 3.2, Appendix C.4).
        price = _opening_price()
        cues = _cues("offer", price, None)
        return CounterpartDecision("offer", price, cues.sentiment_cue, cues.strategic_cue)

    agent_price = agent_offers[-1]
    delta_bar = normalized_favorability(agent_price, r_b, counterpart_role, price_range)
    _d_tilde, d_tilde_bar = deadline_clock(round_k, horizon)
    history = agent_history_features(agent_offers, agent_role=agent_role, price_range=price_range)
    a_k = acceptance_probability(
        delta_bar=delta_bar,
        kappa_b=kappa_b,
        d_tilde_bar=d_tilde_bar,
        rho=preset["rho"][eta_b],
        xi=preset["xi"][eta_b],
        concede_speed=history.concede_speed,
        rigidity=history.rigidity,
    )
    prior_counterpart_price = counterpart_offers[-1] if counterpart_offers else None

    if _require("u_accept") < a_k:
        cues = _cues("accept", agent_price, prior_counterpart_price)
        return CounterpartDecision("accept", agent_price, cues.sentiment_cue, cues.strategic_cue)

    if round_k >= horizon:
        # App. C.2.3: at the terminal round, remaining non-accept/non-walk-away
        # mass is assigned to round-limit disagreement, not a K+1-th offer.
        return CounterpartDecision("timeout", None, None, None)

    omega_k = walkaway_hazard(round_k=round_k, horizon=horizon, delta_bar=delta_bar)
    if omega_k > 0.0 and _require("u_walkaway") < omega_k:
        cues = _cues("reject", None, prior_counterpart_price)
        return CounterpartDecision("reject", None, cues.sentiment_cue, cues.strategic_cue)

    if counterpart_offers:
        lambda_b = concession_rate(
            kappa_b=kappa_b,
            eta_b=eta_b,
            lambda2=preset["lambda2"][eta_b],
            concede_magnitude=history.concede_magnitude,
        )
        price = counter_offer_price(
            counterpart_role=counterpart_role,
            r_b=r_b,
            prior_counterpart_price=counterpart_offers[-1],
            lambda_b=lambda_b,
            price_noise=_require("price_noise") * sigma_p,
        )
    else:
        # Sec. 3.2: "absent acceptance or walk-away, it samples its first
        # price from the same opening model, since no previous counterpart
        # offer exists" -- the agent-opens counterpart's first substantive move.
        price = _opening_price()

    cues = _cues("offer", price, prior_counterpart_price)
    return CounterpartDecision("offer", price, cues.sentiment_cue, cues.strategic_cue)


__all__ = [
    "ALPHA",
    "BETA",
    "BETA_KAPPA_ALPHA",
    "BETA_KAPPA_BETA",
    "CueDraw",
    "DEFAULT_HORIZON",
    "ECONOMIC_PRESETS",
    "EPS_C",
    "EPS_D",
    "EPS_KAPPA",
    "EPS_SIGMA",
    "FAMILIES",
    "FAMILY_PRESETS",
    "GAMMA",
    "HistoryFeatures",
    "NODEAL_GAP_MAX",
    "NODEAL_GAP_MIN",
    "P_MAX",
    "P_MIN",
    "PRICE_NOISE_SCALE_BY_TIER",
    "STANCE_TYPES",
    "ZOPA_WIDTH_MAX",
    "ZOPA_WIDTH_MIN",
    "acceptance_probability",
    "agent_history_features",
    "agent_role_sign",
    "clip",
    "concession_rate",
    "counter_offer_price",
    "counterpart_concession_magnitude",
    "counterpart_role_sign",
    "CounterpartDecision",
    "deadline_clock",
    "generate_cues",
    "k_walk",
    "monotone_feasible_interval",
    "nodeal_difficulty",
    "norm_cdf",
    "normalized_favorability",
    "opening_modulation",
    "opening_offer_price",
    "opening_slack",
    "overlap_difficulty",
    "resolve_counterpart_turn",
    "sample_categorical",
    "sentiment_cue_from_score",
    "sentiment_latent_mean",
    "sigmoid",
    "softmax",
    "strategic_cue_logits",
    "walkaway_clock",
    "walkaway_hazard",
]
