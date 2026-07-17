"""slowlog-agent: on-demand MySQL slow query log analysis."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("slowlog-agent")
except PackageNotFoundError:  # pragma: no cover - only hit when running from source without install
    __version__ = "0.0.0.dev0"
