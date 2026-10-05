"""Personal-device Topstep executor.

This package intentionally has no dependency on the hosted FastAPI application,
Railway database, or worker runtime.
"""

from ._version import __version__

__all__ = ["__version__"]
