from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import openclip.domain_pack as domain_pack

ROOT = Path(__file__).resolve().parents[1]


def _copy_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = ROOT / "src" / "openclip" / "_domain_pack"
    copied = tmp_path / "bundle"
    shutil.copytree(source, copied)
    monkeypatch.setattr(domain_pack, "_root", lambda: copied)
    return copied


def test_repo_level_contractplane_bundle_is_self_contained() -> None:
    root = ROOT / "contractplane"
    lock = json.loads((root / "lock.json").read_text(encoding="utf-8"))

    assert hashlib.sha256((root / "openclip.domain.yaml").read_bytes()).hexdigest() == lock["packSha256"]
    assert len(lock["roleContracts"]) == 13
    for role in lock["roleContracts"]:
        path = root / role["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == role["sha256"]
    for plan in lock["compiledPlans"]:
        path = root / plan["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == plan["sha256"]


def test_bundle_integrity_covers_all_roles_and_compiled_plans() -> None:
    shown = domain_pack.domain_pack_show()

    assert shown["integrity_ok"] is True
    assert shown["integrity_errors"] == []
    assert len(shown["role_contracts"]) == 13
    assert {item["role"] for item in shown["role_contracts"]} == domain_pack.EXPECTED_ROLES
    assert shown["compiled_plans"][0]["sha256"]
    assert shown["resource_count"] == 16  # lock + manifest + 13 roles + shorts plan

    plan = json.loads(
        (ROOT / "contractplane" / "compiled" / "shorts.plan.json").read_text(encoding="utf-8")
    )
    stages = {
        stage["id"]: stage
        for wave in plan["waves"]
        for stage in wave["stages"]
    }
    transcript_schema = stages["merge"]["evidenceContracts"][0]["schema"]
    assert {tuple(branch["required"]) for branch in transcript_schema["anyOf"]} == {
        ("missing_chunks",),
        ("missingChunks",),
    }
    assert stages["thumbnails"]["role"] == "oc-thumbnail-artist"
    assert "process.ffprobe" in stages["thumbnails"]["permissions"]


@pytest.mark.parametrize("mutation", ["missing", "corrupt"])
def test_missing_or_corrupt_plan_fails_show_and_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    bundle = _copy_bundle(tmp_path, monkeypatch)
    plan = bundle / "compiled" / "shorts.plan.json"
    if mutation == "missing":
        plan.unlink()
    else:
        plan.write_text('{"corrupt": true}\n', encoding="utf-8")

    shown = domain_pack.domain_pack_show()
    assert shown["integrity_ok"] is False
    assert any("compiled/shorts.plan.json" in issue for issue in shown["integrity_errors"])

    target = tmp_path / "out"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("untouched", encoding="utf-8")
    with pytest.raises(domain_pack.DomainPackIntegrityError):
        domain_pack.domain_pack_export(str(target), force=True)
    assert sentinel.read_text(encoding="utf-8") == "untouched"


def test_plan_digest_is_recomputed_not_only_compared_to_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _copy_bundle(tmp_path, monkeypatch)
    plan_path = bundle / "compiled" / "shorts.plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["flow"] = "tampered-flow"
    plan_body = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    plan_path.write_text(plan_body, encoding="utf-8")

    lock_path = bundle / "lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["compiledPlans"][0]["sha256"] = hashlib.sha256(plan_body.encode()).hexdigest()
    lock_body = json.dumps(lock, ensure_ascii=False, indent=2) + "\n"
    lock_path.write_text(lock_body, encoding="utf-8")
    monkeypatch.setattr(domain_pack, "LOCK_SHA256", hashlib.sha256(lock_body.encode()).hexdigest())

    shown = domain_pack.domain_pack_show()
    assert shown["integrity_ok"] is False
    assert any("planDigest invalid" in issue for issue in shown["integrity_errors"])


def test_lock_hash_is_verified(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = _copy_bundle(tmp_path, monkeypatch)
    lock = bundle / "lock.json"
    lock.write_bytes(lock.read_bytes() + b"\n")

    shown = domain_pack.domain_pack_show()
    assert shown["integrity_ok"] is False
    assert any("lock.json sha256 mismatch" in issue for issue in shown["integrity_errors"])


def test_export_refuses_nonempty_target_unless_forced(tmp_path: Path) -> None:
    target = tmp_path / "pack"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError, match="--force"):
        domain_pack.domain_pack_export(str(target))
    assert sentinel.read_text(encoding="utf-8") == "old"

    exported = domain_pack.domain_pack_export(str(target), force=True)
    assert exported["forced"] is True
    assert not sentinel.exists()
    assert (target / "openclip.domain.yaml").is_file()
    assert (target / "compiled" / "shorts.plan.json").is_file()
    assert len(list((target / "roles").glob("oc-*.md"))) == 13


def test_forced_export_rolls_back_when_publish_rename_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "pack"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("old", encoding="utf-8")
    real_replace = domain_pack.os.replace
    calls = 0

    def fail_publish_once(source: Path, destination: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated publish failure")
        real_replace(source, destination)

    monkeypatch.setattr(domain_pack.os, "replace", fail_publish_once)
    with pytest.raises(OSError, match="simulated publish failure"):
        domain_pack.domain_pack_export(str(target), force=True)

    assert sentinel.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(".pack.tmp-*"))
    assert not list(tmp_path.glob(".pack.backup-*"))
