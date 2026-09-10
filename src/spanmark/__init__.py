"""spanmark: a span annotation widget."""

from importlib.metadata import PackageNotFoundError, version

from spanmark._session import AnnotationSession

try:
    __version__ = version("spanmark")
except PackageNotFoundError:
    __version__ = "unknown"
finally:
    del PackageNotFoundError, version

__all__ = [
    "AnnotationSession",
    "__version__",
]
