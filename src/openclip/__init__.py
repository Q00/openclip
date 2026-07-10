"""OpenClip: OpenAI-assisted local video clipping and review harness."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__ = version("openclip-agent")
except PackageNotFoundError:  # source tree without an installed distribution
    __version__ = "0+unknown"
