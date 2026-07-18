from __future__ import annotations


class HydrostationsError(Exception):
    """Base class for hydrostations errors."""


class AdapterNotImplementedError(HydrostationsError, NotImplementedError):
    """Raised when an adapter's data source isn't wired up yet."""
