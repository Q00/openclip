"""Inspect and export the self-contained OpenClip ContractPlane Domain Pack."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any

from openclip._domain_pack import LOCK_SHA256


EXPECTED_ROLES = {
    "oc-assembler",
    "oc-cut-judge",
    "oc-cut-proposer",
    "oc-hook-finder",
    "oc-orchestrator",
    "oc-proxy-converter",
    "oc-stt-worker",
    "oc-subtitle-agent",
    "oc-thumbnail-artist",
    "oc-thumbnail-designer",
    "oc-tool-auditor",
    "oc-toolsmith",
    "oc-verifier",
}


class DomainPackIntegrityError(RuntimeError):
    """The bundled pack differs from its generated resource lock."""


def _root():
    return resources.files("openclip._domain_pack")


def _safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ValueError(f"unsafe Domain Pack resource path: {value!r}")
    return path.as_posix()


def _bytes(relative: str) -> bytes:
    node = _root()
    for part in PurePosixPath(_safe_relative(relative)).parts:
        node = node.joinpath(part)
    return node.read_bytes()


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _plan_digest(payload: dict[str, Any]) -> str:
    without_digest = dict(payload)
    without_digest.pop("planDigest", None)
    canonical = json.dumps(
        without_digest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256(canonical)


def _inspect_bundle() -> tuple[dict[str, Any], dict[str, bytes], list[str]]:
    """Return parsed lock, verified resource bytes, and deterministic errors."""
    issues: list[str] = []
    bundle: dict[str, bytes] = {}
    try:
        lock_body = _bytes("lock.json")
    except Exception as exc:  # noqa: BLE001 - diagnostics must survive corruption
        return {}, {}, [f"lock.json unreadable: {exc}"]

    bundle["lock.json"] = lock_body
    actual_lock_sha = _sha256(lock_body)
    if actual_lock_sha != LOCK_SHA256:
        issues.append(f"lock.json sha256 mismatch: expected {LOCK_SHA256}, got {actual_lock_sha}")
    try:
        lock = json.loads(lock_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, bundle, [*issues, f"lock.json invalid JSON: {exc}"]
    if not isinstance(lock, dict):
        return {}, bundle, [*issues, "lock.json root must be an object"]

    if lock.get("schema") != "openclip-contractplane-lock-v2":
        issues.append(f"unsupported lock schema: {lock.get('schema')!r}")
    if lock.get("domain") != "openclip":
        issues.append(f"unexpected lock domain: {lock.get('domain')!r}")

    def read_locked(path_value: object, expected_sha: object, label: str) -> bytes | None:
        if not isinstance(path_value, str) or not isinstance(expected_sha, str):
            issues.append(f"{label} must declare string path and sha256")
            return None
        try:
            relative = _safe_relative(path_value)
        except ValueError as exc:
            issues.append(str(exc))
            return None
        if relative in bundle:
            issues.append(f"duplicate locked resource path: {relative}")
            return bundle[relative]
        try:
            body = _bytes(relative)
        except Exception as exc:  # noqa: BLE001 - report every missing resource
            issues.append(f"{relative} unreadable: {exc}")
            return None
        bundle[relative] = body
        actual_sha = _sha256(body)
        if actual_sha != expected_sha:
            issues.append(f"{relative} sha256 mismatch: expected {expected_sha}, got {actual_sha}")
        return body

    manifest = read_locked("openclip.domain.yaml", lock.get("packSha256"), "manifest")
    if manifest is None:
        issues.append("openclip.domain.yaml is required")

    locked_roles = lock.get("roleContracts")
    if not isinstance(locked_roles, list):
        issues.append("lock roleContracts must be an array")
        locked_roles = []
    role_ids: set[str] = set()
    for index, role in enumerate(locked_roles):
        if not isinstance(role, dict):
            issues.append(f"roleContracts[{index}] must be an object")
            continue
        role_id = role.get("role")
        if isinstance(role_id, str):
            role_ids.add(role_id)
        else:
            issues.append(f"roleContracts[{index}].role must be a string")
        body = read_locked(role.get("path"), role.get("sha256"), f"roleContracts[{index}]")
        if body is not None and isinstance(role_id, str):
            try:
                role_text = body.decode("utf-8")
            except UnicodeDecodeError as exc:
                issues.append(f"{role.get('path')} is not UTF-8: {exc}")
            else:
                if f"name: {role_id}" not in role_text:
                    issues.append(f"{role.get('path')} does not declare role name {role_id}")
    if role_ids != EXPECTED_ROLES:
        missing = sorted(EXPECTED_ROLES - role_ids)
        extra = sorted(role_ids - EXPECTED_ROLES)
        issues.append(f"role contract set mismatch: missing={missing}, extra={extra}")
    if manifest is not None:
        try:
            manifest_text = manifest.decode("utf-8")
        except UnicodeDecodeError as exc:
            issues.append(f"openclip.domain.yaml is not UTF-8: {exc}")
        else:
            for role_id in sorted(EXPECTED_ROLES):
                if f"roles/{role_id}.md" not in manifest_text:
                    issues.append(f"manifest does not reference roles/{role_id}.md")

    locked_plans = lock.get("compiledPlans")
    if not isinstance(locked_plans, list):
        issues.append("lock compiledPlans must be an array")
        locked_plans = []
    for index, plan in enumerate(locked_plans):
        if not isinstance(plan, dict):
            issues.append(f"compiledPlans[{index}] must be an object")
            continue
        body = read_locked(plan.get("path"), plan.get("sha256"), f"compiledPlans[{index}]")
        if body is None:
            continue
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            issues.append(f"{plan.get('path')} invalid JSON: {exc}")
            continue
        if not isinstance(payload, dict):
            issues.append(f"{plan.get('path')} root must be an object")
            continue
        embedded = payload.get("planDigest")
        locked = plan.get("planDigest")
        recomputed = _plan_digest(payload)
        if embedded != locked:
            issues.append(
                f"{plan.get('path')} embedded planDigest mismatch: lock {locked}, plan {embedded}"
            )
        if embedded != recomputed:
            issues.append(
                f"{plan.get('path')} planDigest invalid: embedded {embedded}, recomputed {recomputed}"
            )

    return lock, bundle, issues


def domain_pack_show() -> dict[str, Any]:
    lock, bundle, issues = _inspect_bundle()
    manifest_sha = (
        _sha256(bundle["openclip.domain.yaml"])
        if "openclip.domain.yaml" in bundle
        else None
    )
    return {
        "tool": "domain-pack",
        "action": "show",
        "domain": lock.get("domain", "openclip"),
        "domain_version": lock.get("domainVersion"),
        "openclip_version": lock.get("openclipVersion"),
        "contractplane_version": lock.get("contractplaneVersion"),
        "schema": lock.get("apiVersion", "contractplane.dev/v1alpha1"),
        "pack_sha256": manifest_sha,
        "expected_pack_sha256": lock.get("packSha256"),
        "lock_sha256": _sha256(bundle["lock.json"]) if "lock.json" in bundle else None,
        "integrity_ok": not issues,
        "integrity_errors": issues,
        "compiled_plans": lock.get("compiledPlans", []),
        "role_contracts": lock.get("roleContracts", []),
        "resource_count": len(bundle),
        "runtime_dependency_required": False,
    }


def _replace_directory(stage: Path, target: Path, *, force: bool) -> None:
    """Publish a complete staged directory with rollback for forced replacement."""
    if not target.exists():
        os.replace(stage, target)
        return
    if not any(target.iterdir()):
        target.rmdir()
        os.replace(stage, target)
        return
    if not force:
        raise FileExistsError(f"Domain Pack export target is not empty (pass --force): {target}")

    backup = Path(tempfile.mkdtemp(prefix=f".{target.name}.backup-", dir=target.parent))
    backup.rmdir()
    os.replace(target, backup)
    try:
        os.replace(stage, target)
    except Exception:
        os.replace(backup, target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def domain_pack_export(out: str, *, force: bool = False) -> dict[str, Any]:
    lock, bundle, issues = _inspect_bundle()
    if issues:
        raise DomainPackIntegrityError("bundled Domain Pack failed integrity: " + "; ".join(issues))

    target = Path(out).expanduser().resolve()
    if target.parent == target:
        raise ValueError("refusing to export a Domain Pack over a filesystem root")
    if target.is_symlink():
        raise ValueError(f"refusing to replace symlink export target: {target}")
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"Domain Pack export target is not a directory: {target}")
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(f"Domain Pack export target is not empty (pass --force): {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=target.parent))
    try:
        for relative, body in sorted(bundle.items()):
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(body)
        _replace_directory(stage, target, force=force)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    written = [str(target / relative) for relative in sorted(bundle)]
    return {
        "tool": "domain-pack",
        "action": "export",
        "domain": lock.get("domain", "openclip"),
        "out": str(target),
        "forced": force,
        "written": written,
    }
