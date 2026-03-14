from __future__ import annotations


class AdapterError(RuntimeError):
    """Base adapter exception for broker and market-data integrations."""


class AdapterAuthenticationError(AdapterError):
    """Raised when adapter credentials are missing or rejected."""


class AdapterRequestError(AdapterError):
    """Raised when an upstream HTTP request fails."""


class AdapterParseError(AdapterError):
    """Raised when an upstream payload cannot be normalized safely."""
