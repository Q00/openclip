from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKET_SCHEMA_VERSION = "subagent-packet-v1"
PACKET_DIR_NAME = "subagent_packets"
REVIEW_PHASES = ("collect", "verify", "design", "adversarial", "synthesize")
REQUIRED_PACKET_SECTIONS = [
    "TASK:",
    "DELIVERABLE:",
    "SCOPE:",
    "VERIFY:",
    "EVIDENCE:",
    "ADVERSARIAL_CHECKS:",
    "CLEANUP:",
]


@dataclass(frozen=True)
class SubagentRole:
    role_id: str
    group: str
    review_phase: str
    task: str
    scope: str
    verify: str
    focus_kinds: tuple[str, ...]
    adversarial_checks: tuple[str, ...]


SUBAGENT_ROLES = [
    SubagentRole(
        role_id="shorts_editor",
        group="editorial",
        review_phase="collect",
        task="Decide whether every short has a hook, enough context, and a payoff without relying on parent-thread explanation.",
        scope="Review only short outputs, their SRTs, candidate rationale, thumbnails, and source transcript windows.",
        verify="Open each short path, inspect the matching subtitles and candidate_selection entry, then mark each short PASS or NEEDS_CHANGES.",
        focus_kinds=("short",),
        adversarial_checks=(
            "A high heuristic score is not proof that the short is understandable.",
            "Reject shorts that begin after the setup or end before the payoff.",
            "Reject shorts whose 9:16 framing hides the primary visual context.",
        ),
    ),
    SubagentRole(
        role_id="longform_editor",
        group="editorial",
        review_phase="collect",
        task="Decide whether every long-form candidate has a coherent 8-12 minute arc with a natural start and ending.",
        scope="Review only long outputs, their SRTs, candidate rationale, and adjacent transcript context.",
        verify="Compare each long candidate against the transcript and ensure the ending feels intentional instead of an arbitrary 10 minute stop.",
        focus_kinds=("long",),
        adversarial_checks=(
            "A duration near 10 minutes is not proof of story completion.",
            "Reject candidates that end mid-explanation, mid-list, or before a promised takeaway.",
            "Flag candidates that need endpoint extension even if mechanical verification passed.",
        ),
    ),
    SubagentRole(
        role_id="retention_critic",
        group="editorial",
        review_phase="adversarial",
        task="Attack likely drop-off points, repetition, filler, and weak openings across shorts and long-form candidates.",
        scope="Review short and long outputs as a skeptical viewer optimizing for retention.",
        verify="List blocking retention problems by output_id with exact start/end suggestions when a fix is possible.",
        focus_kinds=("short", "long"),
        adversarial_checks=(
            "Do not count repeated wording as useful context.",
            "Treat polite but boring openings as failures when a stronger hook exists nearby.",
            "Look for stale-state success: old renders can survive after a rerun unless paths and timestamps match.",
        ),
    ),
    SubagentRole(
        role_id="continuity_editor",
        group="qa",
        review_phase="verify",
        task="Check cut continuity, subtitle alignment, speech-boundary starts/ends, and burned Korean short subtitles.",
        scope="Review MP4/SRT pairs, EDL, candidate boundaries, and playback validation results.",
        verify="For each output, confirm subtitle files map to the final output timeline and cuts do not start or stop mid-thought.",
        focus_kinds=("short", "long", "edited_original"),
        adversarial_checks=(
            "Passing ffprobe does not prove subtitle timing is readable.",
            "Reject zero-duration, overlapping, or ellipsis-truncated subtitle cues.",
            "Treat missing burned Korean subtitles on shorts as blocking when burn-in was requested.",
        ),
    ),
    SubagentRole(
        role_id="thumbnail_director",
        group="creative",
        review_phase="design",
        task="Check every short and long thumbnail for hook clarity, prompt faithfulness, aspect, and mismatch risk.",
        scope="Review thumbnail PNGs, prompt JSON files, representative frame metadata, and output subtitles.",
        verify="Confirm each thumbnail can plausibly be generated from the subtitle-summary hook and does not imply false content.",
        focus_kinds=("short", "long"),
        adversarial_checks=(
            "A generated PNG existing on disk is not proof it is a usable thumbnail.",
            "Reject thumbnails that advertise the scoring system instead of the video's hook.",
            "Reject unnecessary fake people or faces unless a lecturer photo was explicitly selected.",
        ),
    ),
    SubagentRole(
        role_id="playback_probe_shorts",
        group="playback",
        review_phase="verify",
        task="Audit short MP4 playback evidence for blank frames, duration drift, audio decode failures, and vertical framing problems.",
        scope="Review short outputs and analysis/playback_checks artifacts only.",
        verify="Use playback_check.json and contact sheet evidence, then spot-check suspicious short paths directly if needed.",
        focus_kinds=("short",),
        adversarial_checks=(
            "A timeout while waiting for a child reviewer is mailbox silence, not proof of failure.",
            "Blank end frames after 60 seconds are blocking even if the manifest says success.",
            "Reject any short outside the 30-60 second contract.",
        ),
    ),
    SubagentRole(
        role_id="playback_probe_longs",
        group="playback",
        review_phase="verify",
        task="Audit long-form MP4 playback evidence for blank frames, overlong renders, duration drift, and audio decode failures.",
        scope="Review long outputs and analysis/playback_checks artifacts only.",
        verify="Use playback_check.json and contact sheet evidence, then spot-check suspicious long paths directly if needed.",
        focus_kinds=("long",),
        adversarial_checks=(
            "Do not trust a successful render log if the final MP4 has black frames after the intended ending.",
            "Reject any long output outside the 8-12 minute contract.",
            "Reject source-aspect outputs that unexpectedly switch to a vertical or cropped composition.",
        ),
    ),
    SubagentRole(
        role_id="artifact_integrity_gate",
        group="gate",
        review_phase="verify",
        task="Verify the run's required files, manifests, sidecars, thumbnails, and playback evidence are complete and internally consistent.",
        scope="Review all manifest records and filesystem paths, but do not make editorial quality calls unless evidence is contradictory.",
        verify="Cross-check manifest.json, candidate_selection.json, edl.json, output files, SRTs, thumbnails, and playback_check.json.",
        focus_kinds=("short", "long", "edited_original"),
        adversarial_checks=(
            "Treat child PASS claims as untrusted until file evidence matches.",
            "Detect misleading success output where manifest success coexists with missing artifacts.",
            "Detect stale paths that point at a previous run directory.",
        ),
    ),
    SubagentRole(
        role_id="final_gate_reviewer",
        group="gate",
        review_phase="synthesize",
        task="Make the final publish/no-publish decision after all other reviewers and mechanical checks are complete.",
        scope="Review all artifacts, all reviewer outputs, and the user's explicit complaints as a release gate.",
        verify="Return PASS only when mechanical evidence and every editorial lane have no blocking issues.",
        focus_kinds=("short", "long", "edited_original"),
        adversarial_checks=(
            "Assume earlier reviewers may have missed issues.",
            "Reject if any required review lane is missing, ack-only, or inconclusive.",
            "Reject if cleanup accidentally removed evidence needed for audit.",
        ),
    ),
]


def build_subagent_packets(manifest: dict[str, Any], run_dir: str | Path) -> dict[str, Any]:
    run_path = Path(run_dir).expanduser().resolve()
    packet_dir = run_path / "analysis" / PACKET_DIR_NAME
    packet_dir.mkdir(parents=True, exist_ok=True)
    path_audit = audit_manifest_paths(manifest_without_prior_packet_index(manifest), run_path)

    packets = []
    for role in SUBAGENT_ROLES:
        outputs = focused_outputs(manifest, role.focus_kinds)
        evidence_paths = collect_evidence_paths(manifest, run_path, outputs)
        packet_path = packet_dir / f"{role.role_id}.md"
        packet_text = render_packet(role, manifest, run_path, outputs, evidence_paths, path_audit)
        assert_required_sections(packet_text, packet_path)
        packet_path.write_text(packet_text, encoding="utf-8")
        packets.append(
            {
                "role_id": role.role_id,
                "group": role.group,
                "review_phase": role.review_phase,
                "workflow_phase_order": REVIEW_PHASES.index(role.review_phase),
                "packet_path": str(packet_path),
                "fork_context": False,
                "requires_working_status": True,
                "ack_only_is_inconclusive": True,
                "timeout_is_mailbox_silence": True,
                "pass_is_untrusted_claim": True,
                "approval_dependencies": approval_dependencies_for(role),
                "required_sections": REQUIRED_PACKET_SECTIONS,
                "output_ids": [str(output.get("id")) for output in outputs],
                "evidence_paths": evidence_paths,
            }
        )

    index_path = packet_dir / "index.json"
    index = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "status": "ready",
        "packet_dir": str(packet_dir),
        "index_path": str(index_path),
        "packet_count": len(packets),
        "fork_context_default": False,
        "review_workflow": build_review_workflow(),
        "root_thread_obligations": [
            "Spawn actual Codex subagents with these packet files after mechanical gates pass.",
            "Run lanes in OpenClip evidence-review order: collect, verify, design, adversarial, then synthesize.",
            "Require WORKING: <role> - <phase> from long inspections and BLOCKED:<reason> only when progress stops.",
            "Treat subagent done claims as untrusted until the main thread verifies cited evidence.",
            "Treat timeout as mailbox silence, never approval or failure by itself.",
            "Respawn smaller scoped packets when a child result is ack-only, missing deliverables, or inconclusive.",
            "Run artifact and playback verification again after any rerender.",
            "Close or otherwise retire child agents after their deliverable has been integrated.",
        ],
        "required_subagents": [role.role_id for role in SUBAGENT_ROLES],
        "manifest_path_audit": path_audit,
        "packets": packets,
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return index


def build_review_workflow() -> dict[str, Any]:
    phase_roles = {
        phase: [role.role_id for role in SUBAGENT_ROLES if role.review_phase == phase]
        for phase in REVIEW_PHASES
    }
    return {
        "name": "openclip_evidence_review_loop",
        "phase_order": list(REVIEW_PHASES),
        "phase_roles": phase_roles,
        "phase_contracts": {
            "collect": "Gather independent editorial claims about hooks, arcs, context, and payoff.",
            "verify": "Check those claims against manifests, SRTs, EDL, playback probes, and filesystem evidence.",
            "design": "Review thumbnail and presentation decisions against subtitle-derived hooks and reference frames.",
            "adversarial": "Assume the candidate will fail retention or scope; look for the strongest blocking counterexamples.",
            "synthesize": "Approve only when every lane has a JSON deliverable, checked paths, and no blocking issues.",
        },
        "root_protocol": {
            "fork_context": False,
            "requires_working_status": True,
            "ack_only_is_inconclusive": True,
            "timeout_is_mailbox_silence": True,
            "pass_is_untrusted_claim": True,
            "fallback": "Respawn a smaller packet when the deliverable is missing, ack-only, BLOCKED, or inconclusive.",
        },
    }


def approval_dependencies_for(role: SubagentRole) -> list[str]:
    if role.role_id == "final_gate_reviewer":
        return [candidate.role_id for candidate in SUBAGENT_ROLES if candidate.role_id != role.role_id]
    if role.role_id == "artifact_integrity_gate":
        return ["playback_probe_shorts", "playback_probe_longs"]
    if role.review_phase == "adversarial":
        return ["shorts_editor", "longform_editor", "continuity_editor"]
    if role.review_phase == "design":
        return ["shorts_editor", "longform_editor"]
    return []


def focused_outputs(manifest: dict[str, Any], focus_kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        output
        for output in manifest.get("outputs", [])
        if str(output.get("kind")) in set(focus_kinds)
    ]


def manifest_without_prior_packet_index(manifest: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "subagent_packet_index"}


def collect_evidence_paths(manifest: dict[str, Any], run_dir: Path, outputs: list[dict[str, Any]]) -> list[str]:
    paths = [
        str(run_dir / "manifest.json"),
        str(manifest.get("packed_transcript_path") or run_dir / "analysis" / "takes_packed.md"),
        str(manifest.get("candidate_selection_path") or run_dir / "analysis" / "candidate_selection.json"),
        str(manifest.get("edl_path") or run_dir / "analysis" / "edl.json"),
        str(run_dir / "analysis" / "playback_checks" / "playback_check.json"),
        str(run_dir / "analysis" / "playback_checks" / "playback_contact_sheet.jpg"),
    ]
    for output in outputs:
        append_path(paths, output.get("path"))
        for subtitle_path in (output.get("subtitles") or {}).values():
            append_path(paths, subtitle_path)
        thumbnail = output.get("thumbnail") or {}
        append_path(paths, thumbnail.get("path"))
        append_path(paths, thumbnail.get("prompt_path"))
    return sorted(dict.fromkeys(path for path in paths if path))


def append_path(paths: list[str], value: Any) -> None:
    if value:
        paths.append(str(value))


def render_packet(
    role: SubagentRole,
    manifest: dict[str, Any],
    run_dir: Path,
    outputs: list[dict[str, Any]],
    evidence_paths: list[str],
    path_audit: dict[str, Any],
) -> str:
    output_summary = [
        {
            "id": output.get("id"),
            "kind": output.get("kind"),
            "path": output.get("path"),
            "duration_seconds": output.get("duration_seconds"),
            "thumbnail_path": (output.get("thumbnail") or {}).get("path"),
            "thumbnail_prompt_path": (output.get("thumbnail") or {}).get("prompt_path"),
            "subtitle_paths": output.get("subtitles") or {},
            "burned_subtitles": output.get("burned_subtitles") or {},
            "rationale": output.get("rationale"),
        }
        for output in outputs
    ]
    command_options = manifest.get("command_options") or (manifest.get("command") or {}).get("options") or {}
    known_complaints = [
        "Shorts must fit 9:16 without hiding the useful visual context.",
        "Shorts must stop at 30-60 seconds and never continue into black frames.",
        "Long-form candidates must be 8-12 minutes and feel like the idea actually ends.",
        "Use actual Codex subagents for editorial and gate review; Python persona JSON is only baseline evidence.",
        "Generated outputs must stay out of git; only harness code is committed.",
    ]
    expected_json = {
        "verdict": "PASS or NEEDS_CHANGES",
        "blocking_issues": [
            {
                "output_id": "short_001",
                "issue": "specific failure",
                "required_change": "specific edit, rerender, subtitle, thumbnail, or review fix",
                "suggested_start_seconds": None,
                "suggested_end_seconds": None,
                "evidence_path": "/absolute/path/to/evidence",
            }
        ],
        "non_blocking_notes": [],
        "approval_conditions": [],
        "checked_paths": [],
    }
    workflow = build_review_workflow()
    approval_dependencies = approval_dependencies_for(role)
    return "\n".join(
        [
            f"TASK: {role.task}",
            "",
            "DELIVERABLE:",
            "Return only a JSON object with this schema:",
            fenced_json(expected_json),
            "",
            "SCOPE:",
            role.scope,
            f"Review phase: {role.review_phase}",
            f"OpenClip review workflow phases: {', '.join(REVIEW_PHASES)}",
            f"Approval dependencies for this packet: {json.dumps(approval_dependencies, ensure_ascii=False)}",
            f"Run directory: {run_dir}",
            f"Fork context: false. This packet must be enough without parent-thread memory.",
            f"Command options: {json.dumps(command_options, ensure_ascii=False, sort_keys=True)}",
            "",
            "VERIFY:",
            role.verify,
            "Before a long inspection, emit or include `WORKING: "
            f"{role.role_id} - {role.review_phase}` so the root thread can distinguish progress from silence.",
            "Use `BLOCKED:<reason>` only when no meaningful progress is possible from this packet.",
            "Return NEEDS_CHANGES instead of BLOCKED when you can name concrete edits or rerender requirements.",
            "Do not count manifest success, Python persona review, or another child review as proof by itself.",
            "If a command or inspection times out, report it as inconclusive mailbox silence and request a smaller respawn packet.",
            "A PASS is only a claim until the root Codex thread verifies checked_paths or a gate reviewer validates the evidence.",
            "Mechanical commands the root thread must run or confirm before final PASS:",
            f"- python3 codex/skills/openclip/scripts/verify_run_artifacts.py {run_dir}",
            f"- python3 codex/skills/openclip/scripts/parallel_video_playback_check.py {run_dir} --workers 6 --full-decode --write-manifest",
            "",
            "EVIDENCE:",
            "Required artifact paths:",
            *[f"- {path}" for path in evidence_paths],
            "",
            "Manifest path audit:",
            fenced_json(path_audit),
            "",
            "Review workflow metadata:",
            fenced_json(workflow),
            "",
            "Focused outputs:",
            fenced_json(output_summary),
            "",
            "Known user complaints to test against:",
            *[f"- {complaint}" for complaint in known_complaints],
            "",
            "ADVERSARIAL_CHECKS:",
            *[f"- {check}" for check in role.adversarial_checks],
            "- Verify the collect, verify, design, adversarial, and synthesize lanes are not being collapsed into a single optimistic pass.",
            "- Reject final approval when any dependency lane is missing, ack-only, timeout-only, or lacks checked_paths.",
            "- Check for dirty-worktree confusion, stale run directories, misleading success output, hung commands, and repeated interruption.",
            "- A child result that is ack-only, lacks checked_paths, or omits evidence_path for a blocker is not a PASS.",
            "",
            "CLEANUP:",
            "Do not delete or rewrite media artifacts. Do not edit .env or reveal secrets. Leave outputs ignored by git.",
            "If temporary inspection files are created, write them under analysis/subagent_packets/tmp and list them in checked_paths.",
            "",
        ]
    )


def fenced_json(value: Any) -> str:
    return "```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```"


def assert_required_sections(packet_text: str, packet_path: Path) -> None:
    missing = [section for section in REQUIRED_PACKET_SECTIONS if section not in packet_text]
    if missing:
        raise ValueError(f"{packet_path} is missing packet sections: {', '.join(missing)}")


def audit_manifest_paths(manifest: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    external = []
    missing_current = []
    for location, value in walk_json_scalars(manifest):
        if not isinstance(value, str) or not value.startswith("/"):
            continue
        if is_allowed_external_provenance(location):
            continue
        path = Path(value)
        record = {"json_path": location, "path": value}
        try:
            path.relative_to(run_dir)
        except ValueError:
            external.append(record)
            continue
        if json_path_is_manifest_self_reference(location):
            continue
        if looks_like_artifact_path(path) and not path.exists():
            missing_current.append(record)
    return {
        "status": "pass" if not external and not missing_current else "needs_review",
        "run_dir": str(run_dir),
        "external_absolute_path_count": len(external),
        "missing_current_artifact_count": len(missing_current),
        "external_absolute_paths": external[:50],
        "missing_current_artifacts": missing_current[:50],
        "truncated": len(external) > 50 or len(missing_current) > 50,
        "note": (
            "External absolute paths can be legitimate source/cache provenance only when explicitly marked as such; "
            "otherwise they are stale-run risk for final approval."
        ),
    }


def walk_json_scalars(value: Any, prefix: str = "$") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        items: list[tuple[str, Any]] = []
        for key, child in value.items():
            items.extend(walk_json_scalars(child, f"{prefix}.{key}"))
        return items
    if isinstance(value, list):
        items = []
        for index, child in enumerate(value):
            items.extend(walk_json_scalars(child, f"{prefix}[{index}]"))
        return items
    return [(prefix, value)]


def looks_like_artifact_path(path: Path) -> bool:
    return path.suffix.lower() in {
        ".json",
        ".md",
        ".mp4",
        ".srt",
        ".png",
        ".jpg",
        ".jpeg",
        ".wav",
        ".m4a",
        ".txt",
    }


def is_allowed_external_provenance(json_path: str) -> bool:
    return (
        json_path == "$.input.path"
        or json_path.startswith("$.source_limits.")
        or json_path.startswith("$.dependency_checks.")
        or json_path in {"$.command.argv[0]", "$.command.argv[2]", "$.command.argv[4]"}
    )


def json_path_is_manifest_self_reference(json_path: str) -> bool:
    return json_path in {"$.success_manifest.path", "$.subagent_packet_index.index_path"}
