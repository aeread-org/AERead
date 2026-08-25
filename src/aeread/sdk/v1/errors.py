"""Errors raised by the AERead v1 public SDK."""


class SDKError(Exception):
    """Base class for public SDK errors."""


class CanonicalizationError(SDKError, ValueError):
    """A value cannot be represented by AERead canonical JSON."""


class BundleValidationError(SDKError, ValueError):
    """An action bundle does not satisfy its decision slot contract."""


class UntrustedPluginReference(SDKError):
    """A plugin reference is not a safe, version-pinned registry key."""
