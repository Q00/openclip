from __future__ import annotations

import json
from pathlib import Path

from openclip.subagent_packets import REQUIRED_PACKET_SECTIONS, SUBAGENT_ROLES, build_subagent_packets


def test_subagent_packets_are_self_contained_openclip_review_assignments(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "analysis").mkdir(parents=True)
    (run_dir / "shorts").mkdir()
    (run_dir / "long").mkdir()
    (run_dir / "work" / "thumbnails").mkdir(parents=True)

    manifest = {
        "status": "success",
        "external_cache_path": "/tmp/previous-run/cache.json",
        "command_options": {
            "all_short_candidates": True,
            "all_long_candidates": True,
            "burn_short_ko_subtitles": True,
        },
        "packed_transcript_path": str(run_dir / "analysis" / "takes_packed.md"),
        "candidate_selection_path": str(run_dir / "analysis" / "candidate_selection.json"),
        "edl_path": str(run_dir / "analysis" / "edl.json"),
        "outputs": [
            {
                "id": "short_001",
                "kind": "short",
                "path": str(run_dir / "shorts" / "short_001.mp4"),
                "duration_seconds": 42.0,
                "subtitles": {"ko": str(run_dir / "shorts" / "short_001.ko.srt")},
                "burned_subtitles": {"ko": str(run_dir / "shorts" / "short_001.ko.srt")},
                "thumbnail": {
                    "path": str(run_dir / "shorts" / "short_001.thumbnail.png"),
                    "prompt_path": str(run_dir / "work" / "thumbnails" / "short_001.prompt.json"),
                },
                "rationale": "Hook and payoff.",
            },
            {
                "id": "long_001",
                "kind": "long",
                "path": str(run_dir / "long" / "long_001.mp4"),
                "duration_seconds": 600.0,
                "subtitles": {"ko": str(run_dir / "long" / "long_001.ko.srt")},
                "thumbnail": {
                    "path": str(run_dir / "long" / "long_001.thumbnail.png"),
                    "prompt_path": str(run_dir / "work" / "thumbnails" / "long_001.prompt.json"),
                },
                "rationale": "Complete chapter.",
            },
        ],
    }

    index = build_subagent_packets(manifest, run_dir)

    assert index["status"] == "ready"
    assert index["fork_context_default"] is False
    assert index["packet_count"] == len(SUBAGENT_ROLES)
    assert index["review_workflow"]["phase_order"] == [
        "collect",
        "verify",
        "design",
        "adversarial",
        "synthesize",
    ]
    assert index["review_workflow"]["phase_roles"]["collect"] == ["shorts_editor", "longform_editor"]
    assert index["review_workflow"]["phase_roles"]["synthesize"] == ["final_gate_reviewer"]
    assert index["review_workflow"]["root_protocol"]["ack_only_is_inconclusive"] is True
    assert index["manifest_path_audit"]["status"] == "needs_review"
    assert index["manifest_path_audit"]["external_absolute_path_count"] == 1
    assert index["manifest_path_audit"]["external_absolute_paths"][0]["json_path"] == "$.external_cache_path"
    assert "Treat subagent done claims as untrusted until the main thread verifies cited evidence." in index[
        "root_thread_obligations"
    ]

    index_path = Path(index["index_path"])
    assert json.loads(index_path.read_text(encoding="utf-8"))["packet_count"] == len(SUBAGENT_ROLES)

    for packet in index["packets"]:
        assert packet["fork_context"] is False
        assert packet["review_phase"] in index["review_workflow"]["phase_order"]
        assert packet["requires_working_status"] is True
        assert packet["ack_only_is_inconclusive"] is True
        assert packet["timeout_is_mailbox_silence"] is True
        assert packet["pass_is_untrusted_claim"] is True
        packet_path = Path(packet["packet_path"])
        text = packet_path.read_text(encoding="utf-8")
        assert text.startswith("TASK:")
        for section in REQUIRED_PACKET_SECTIONS:
            assert section in text
        assert "Fork context: false" in text
        assert "WORKING:" in text
        assert "BLOCKED:" in text
        assert "OpenClip review workflow phases: collect, verify, design, adversarial, synthesize" in text
        assert "Do not count manifest success" in text
        assert "Manifest path audit:" in text
        assert "Review workflow metadata:" in text
        assert "ack-only" in text
        assert str(run_dir / "manifest.json") in text

    final_gate = next(packet for packet in index["packets"] if packet["role_id"] == "final_gate_reviewer")
    assert sorted(final_gate["approval_dependencies"]) == sorted(
        role.role_id for role in SUBAGENT_ROLES if role.role_id != "final_gate_reviewer"
    )
    final_gate_text = Path(final_gate["packet_path"]).read_text(encoding="utf-8")
    assert "Reject final approval when any dependency lane is missing" in final_gate_text


def test_subagent_packets_focus_reviewers_on_relevant_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    manifest = {
        "outputs": [
            {"id": "short_001", "kind": "short", "path": str(run_dir / "shorts" / "short_001.mp4")},
            {"id": "long_001", "kind": "long", "path": str(run_dir / "long" / "long_001.mp4")},
            {"id": "edited_original", "kind": "edited_original", "path": str(run_dir / "edited" / "edited_original.mp4")},
        ]
    }

    index = build_subagent_packets(manifest, run_dir)
    by_role = {packet["role_id"]: packet for packet in index["packets"]}

    assert by_role["shorts_editor"]["output_ids"] == ["short_001"]
    assert by_role["longform_editor"]["output_ids"] == ["long_001"]
    assert by_role["playback_probe_shorts"]["output_ids"] == ["short_001"]
    assert by_role["playback_probe_longs"]["output_ids"] == ["long_001"]
    assert by_role["artifact_integrity_gate"]["output_ids"] == ["short_001", "long_001", "edited_original"]


def test_manifest_self_reference_is_not_flagged_missing_before_write(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    manifest = {
        "success_manifest": {"path": str(run_dir / "manifest.json")},
        "outputs": [],
    }

    index = build_subagent_packets(manifest, run_dir)

    assert index["manifest_path_audit"]["status"] == "pass"
    assert index["manifest_path_audit"]["missing_current_artifact_count"] == 0


def test_manifest_audit_allows_wrapper_output_root_argument(tmp_path: Path) -> None:
    run_dir = tmp_path / "out" / "demo"
    manifest = {
        "command": {"argv": ["openclip", "run", "/tmp/source.mp4", "--out", str(run_dir.parent)]},
        "outputs": [],
    }

    index = build_subagent_packets(manifest, run_dir)

    assert index["manifest_path_audit"]["status"] == "pass"
    assert index["manifest_path_audit"]["external_absolute_path_count"] == 0
