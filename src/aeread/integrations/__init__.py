"""Framework integrations.

- ``rllm_flow`` / ``rllm_eval`` / ``rllm_dataset``: rLLM (Berkeley Sky Lab)
  AgentFlow + evaluator + dataset rows. Exposed via setuptools entry points
  (``rllm.agents`` / ``rllm.evaluators``) so an installed ``rllm`` discovers
  them by name. Experimental.

Planned: a ``generate_rollout`` adapter for miles/slime, and a Harbor task
adapter (rLLM's on-disk task format is Harbor-compatible, so the dataset work
is shared).
"""
