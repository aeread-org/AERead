"""Frozen transport limits for the separate Phase 2 timeout recovery."""

PROVIDER_TIMEOUT_SECONDS = 175.0
HARNESS_TIMEOUT_SECONDS = 180.0
RETRY_CONDITIONS = ("rate_limit", "timeout")
