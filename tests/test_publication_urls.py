from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = "https://contractplane.dev/openclip/"


def test_public_surfaces_use_contractplane_canonical_home() -> None:
    paths = (
        ROOT / "README.md",
        ROOT / "README.ko.md",
        ROOT / "README.ja.md",
        ROOT / "README.zh-CN.md",
        ROOT / "README.es.md",
        ROOT / "docs" / "index.html",
        ROOT / "llms.txt",
        ROOT / "pyproject.toml",
    )

    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert CANONICAL in text, path.name
        assert "https://wpti.dev/openclip" not in text, path.name


def test_legacy_pages_source_declares_the_new_canonical() -> None:
    site = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert f'<link rel="canonical" href="{CANONICAL}">' in site
    assert "v0.2.4" in site
