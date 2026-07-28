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

__version__ = "0.1.0"
