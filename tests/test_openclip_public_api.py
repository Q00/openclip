from __future__ import annotations

from importlib.metadata import version


def test_openclip_public_package_exports_version() -> None:
    import openclip

    assert openclip.__version__ == version("openclip-agent")
