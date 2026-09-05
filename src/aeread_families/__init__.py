"""External-benchmark family adapters for the AERead shared-runner kernel.

Each subpackage pins one upstream benchmark and adapts it onto
``aeread.shared_runner`` without reimplementing upstream's tools, scoring, or
database mutations.  See ``docs/families/tau3-retail/adapter_spec.md`` for the first
adapter (``tau3.retail``, pinned tau2-bench retail/base).
"""
