"""Framework integrations.

- ``rllm_flow`` / ``rllm_eval`` / ``rllm_dataset``: rLLM (Berkeley Sky Lab)
  AgentFlow + evaluator + dataset rows. Exposed via setuptools entry points
  (``rllm.agents`` / ``rllm.evaluators``) so an installed ``rllm`` discovers
  them by name. Experimental.
- ``pooled_aer``: the pooled-AER aggregation formula, factored out so every
  reporting surface -- ``rllm_eval``'s evaluation post-processor today, a
  future unification with ``exchange_v1_submit.py``'s submission report --
  computes the same number. No rLLM dependency.

Planned: a ``generate_rollout`` adapter for miles/slime, and a Harbor task
adapter (rLLM's on-disk task format is Harbor-compatible, so the dataset work
is shared).
"""

from aeread.integrations.failure_taxonomy import (
    EmptyModelResponse,
    EpisodeMeasurement,
    FailureClass,
    IntegrationConfigurationError,
    IntegrationError,
    InvalidMeasurementError,
    RetryableInfrastructureError,
)


__all__ = [
    "EmptyModelResponse",
    "EpisodeMeasurement",
    "FailureClass",
    "IntegrationConfigurationError",
    "IntegrationError",
    "InvalidMeasurementError",
    "RetryableInfrastructureError",
]
