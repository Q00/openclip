from __future__ import annotations


def test_openclip_public_package_exports_version() -> None:
    import openclip

    assert openclip.__version__
