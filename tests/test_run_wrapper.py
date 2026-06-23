from __future__ import annotations

import importlib.util
from pathlib import Path


def load_wrapper_module():
    path = Path("codex/skills/openclip/scripts/run_openclip.py")
    spec = importlib.util.spec_from_file_location("run_openclip_wrapper", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wrapper_maps_legacy_open_api_key_from_dotenv(tmp_path: Path) -> None:
    module = load_wrapper_module()
    (tmp_path / ".env").write_text("OPEN_API_KEY=secret-value\nOPENAI_BASE_URL=https://proxy.example\n", encoding="utf-8")

    env = module.apply_local_openai_env({"OPENAI_BASE_URL": "https://proxy.example"}, tmp_path)

    assert env["OPENAI_API_KEY"] == "secret-value"
    assert "OPENAI_BASE_URL" not in env


def test_wrapper_prefers_dotenv_key_over_existing_environment_key(tmp_path: Path) -> None:
    module = load_wrapper_module()
    (tmp_path / ".env").write_text("OPEN_API_KEY=dotenv-value\n", encoding="utf-8")

    env = module.apply_local_openai_env({"OPENAI_API_KEY": "env-value"}, tmp_path)

    assert env["OPENAI_API_KEY"] == "dotenv-value"
