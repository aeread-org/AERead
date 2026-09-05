"""AERead — an agentic economic environment and benchmark for LLM agents.

Multi-agent exchange arenas (bilateral, multiparty clearing, hidden discovery,
consent-under-hidden-information, procurement, bundle worlds) with:

- deterministic seeded cases (JSON configs, strict role tables),
- one seat under test against a frozen panel (temp-0, pinned, cached),
- welfare-based AER scoring (raw ratio of realized to attainable welfare,
  negatives preserved, denominator tiers never mixed),
- byte-replayable runs (inference manifest + response snapshots),
- a text-boundary submission harness for foreign agents, and
- RL hooks (structured bilateral env; rLLM integration in
  ``aeread.integrations``).

Start with ``aeread --help`` or the README quickstart.
"""

from importlib import import_module
from types import ModuleType


__version__ = "0.1.0"


_LEGACY_MODULE_ALIASES = {
    "aer_scorer": "aeread.exchange_v1.aer_scorer",
    "agentecon_oracle": "aeread.exchange_v1.agentecon_oracle",
    "bundle_bayes_oracle": "aeread.exchange_v1.bundle_bayes_oracle",
    "capture_share": "aeread.exchange_v1.capture_share",
    "delta_inf_oracle": "aeread.exchange_v1.delta_inf_oracle",
    "exchange_counterpart_frozen": "aeread.exchange_v1.counterpart_frozen",
    "exchange_economy": "aeread.exchange_v1.economy",
    "exchange_economy_adversarial": "aeread.exchange_v1.economy_adversarial",
    "exchange_procurement": "aeread.exchange_v1.procurement",
    "exchange_rl_env": "aeread.exchange_v1.rl_env",
    "exchange_subgame_oracles": "aeread.exchange_v1.subgame_oracles",
    "exchange_v1_baselines": "aeread.exchange_v1.baselines",
    "exchange_v1_candidates": "aeread.exchange_v1.candidates",
    "exchange_v1_filters": "aeread.exchange_v1.filters",
    "exchange_v1_pilot": "aeread.exchange_v1.pilot",
    "exchange_v1_roles": "aeread.exchange_v1.roles",
    "exchange_v1_runner": "aeread.exchange_v1.runner",
    "exchange_v1_scoring": "aeread.exchange_v1.scoring",
    "exchange_v1_submit": "aeread.exchange_v1.submit",
    "exchange_v1_sweep": "aeread.exchange_v1.sweep",
    "exchange_v1_validity": "aeread.exchange_v1.validity",
    "gemini_batch_pool": "aeread.inference.gemini_batch_pool",
    "gemini_llm": "aeread.inference.gemini",
    "housing_env": "aeread_families.housing.environment",
    "llm_agent": "aeread.inference.llm_agent",
    "nonir_classifier": "aeread.exchange_v1.nonir_classifier",
}


def __getattr__(name: str) -> ModuleType:
    """Resolve historical package attributes without retaining root shim files."""

    target = _LEGACY_MODULE_ALIASES.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(target)
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted({*globals(), *_LEGACY_MODULE_ALIASES})
