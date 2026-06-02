"""Exception types raised by the Suma runtime."""

from __future__ import annotations


class VMError(Exception):
    """Raised for runtime errors that the VM cannot recover from."""
