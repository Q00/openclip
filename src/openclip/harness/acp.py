"""Thin ACP (Agent Client Protocol) adapter for the OpenClip harness.

Scope (deliberately narrow — see the adversarial review): ACP is a TRANSPORT, not
a memory bus. This adapter does exactly one useful thing: it lets an ACP client
(Zed, or any JSON-RPC-over-stdio client) DRIVE the harness and answer the
human-in-the-loop steering / promotion gates via ``session/request_permission``.
It holds no trust decisions and no "memory" of its own — shared memory lives in
the git-tracked toolbox (see toolbox.py).

Protocol: newline-delimited JSON-RPC 2.0 over stdin/stdout.
  client → agent:  initialize, session/new, session/prompt, session/cancel
  agent  → client:  session/update (notifications), session/request_permission (request)

The creative planning backend (deciding cuts/hooks) is the LLM's job and is NOT
embedded here; this adapter runs the DETERMINISTIC flows (thumbnail, clip) and
gates every render behind a permission request, which is the genuine ACP win.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, TextIO

from . import tools

PROTOCOL_VERSION = "0.1"
AGENT_NAME = "openclip"


class AcpServer:
    def __init__(self, stdin: TextIO, stdout: TextIO):
        self._in = stdin
        self._out = stdout
        self._next_id = 1
        self._sessions: dict[str, dict[str, Any]] = {}

    # --- JSON-RPC framing (newline-delimited) --------------------------------
    def _send(self, obj: dict[str, Any]) -> None:
        self._out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._out.flush()

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict[str, Any]) -> Any:
        """Outbound request to the client; blocks for the matching response."""
        rid = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        for line in self._in:
            line = line.strip()
            if not line:
                continue
            msg = json.loads(line)
            if msg.get("id") == rid and ("result" in msg or "error" in msg):
                return msg.get("result")
            # a client may interleave notifications; ignore for this thin adapter
        return None

    # --- steering / permission ----------------------------------------------
    def request_permission(self, session_id: str, title: str, detail: dict[str, Any]) -> bool:
        """Surface a steering/render gate to the client. Also record it as a
        steering directive so the terminal path and ACP path share one channel."""
        result = self._request("session/request_permission", {
            "sessionId": session_id, "title": title, "detail": detail,
            "options": [{"id": "allow", "label": "Allow"}, {"id": "reject", "label": "Reject"}],
        })
        allowed = bool(result and result.get("outcome") == "allow")
        proj = self._sessions.get(session_id, {}).get("project")
        if proj:
            tools.steer(proj, f"[ACP permission] {title}: {'allowed' if allowed else 'rejected'}",
                        scope="global", status_value="resolved")
        return allowed

    def update(self, session_id: str, kind: str, payload: dict[str, Any]) -> None:
        self._notify("session/update", {"sessionId": session_id, "update": {"kind": kind, **payload}})

    # --- request handlers ----------------------------------------------------
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        method = msg.get("method")
        params = msg.get("params") or {}
        mid = msg.get("id")
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "agent": {"name": AGENT_NAME},
                    "capabilities": {
                        "flows": ["flow4-thumbnail", "clip", "verify"],
                        "tools": "oc --project <dir> <verb>",
                        "steering": "surfaced via session/request_permission",
                    },
                }
            elif method == "session/new":
                sid = f"sess_{len(self._sessions) + 1}"
                project = params.get("project") or f"out/acp_{sid}"
                self._sessions[sid] = {"project": project}
                result = {"sessionId": sid, "project": project}
            elif method == "session/prompt":
                result = self._run_prompt(params)
            elif method == "session/cancel":
                self._sessions.pop(params.get("sessionId", ""), None)
                result = {"cancelled": True}
            else:
                return _err(mid, -32601, f"method not found: {method}")
        except Exception as exc:  # noqa: BLE001
            return _err(mid, -32000, f"{exc.__class__.__name__}: {exc}")
        return {"jsonrpc": "2.0", "id": mid, "result": result} if mid is not None else None

    def _run_prompt(self, params: dict[str, Any]) -> dict[str, Any]:
        """Deterministic flows only. ``params.request`` = {"flow": ..., ...}."""
        sid = params.get("sessionId")
        if not sid or sid not in self._sessions:
            raise ValueError(f"unknown session {sid!r}; call session/new first")
        sess = self._sessions[sid]
        project = sess["project"]
        req = params.get("request") or {}
        flow = req.get("flow")
        if flow in ("clip", "flow4-thumbnail"):
            missing = [k for k in ("input", "start", "end") if k not in req]
            if missing:
                raise ValueError(f"flow '{flow}' request missing required fields: {missing}")

        if flow == "clip":
            self.update(sid, "plan", {"text": f"render clip {req['start']}–{req['end']} ({req.get('aspect', '9:16')})"})
            if not self.request_permission(sid, "Render this clip?", req):
                return {"status": "rejected"}
            # honor a caller id so successive clips in one session don't overwrite
            cid = req.get("id") or f"acp_{int(float(req['start']))}_{int(float(req['end']))}"
            out = req.get("out") or f"{project}/shorts/{cid}.mp4"
            r = tools.clip(project, req["input"], float(req["start"]), float(req["end"]),
                           aspect=req.get("aspect", "9:16"), out=out, burn_srt=req.get("burn_srt"))
            v = tools.verify(project, r["output"], kind="short",
                             expect_duration=float(req["end"]) - float(req["start"]),
                             expect_aspect=req.get("aspect", "9:16"))
            self.update(sid, "artifact", {"path": r["output"], "verdict": v["verdict"]})
            return {"status": "done", "output": r["output"], "verify": v["verdict"]}

        if flow == "flow4-thumbnail":
            self.update(sid, "plan", {"text": f"thumbnail for hook {req['start']}–{req['end']}"})
            if not self.request_permission(sid, "Generate this thumbnail?", req):
                return {"status": "rejected"}
            r = tools.thumbnail(project, req["input"], float(req["start"]), float(req["end"]),
                                aspect=req.get("aspect", "16:9"), title=req.get("title"),
                                generate=bool(req.get("generate")), mock=bool(req.get("mock")))
            self.update(sid, "artifact", {"path": r["output"]})
            return {"status": "done", "output": r["output"]}

        if flow == "verify":
            if "path" not in req:
                raise ValueError("flow 'verify' request missing required field: path")
            v = tools.verify(project, req["path"], kind=req.get("kind", "clip"),
                             expect_duration=req.get("expect_duration"),
                             expect_aspect=req.get("expect_aspect"), srt=req.get("srt"))
            self.update(sid, "verdict", {"path": req["path"], "verdict": v["verdict"],
                                         "failed_checks": v["failed_checks"]})
            return {"status": "done", "verdict": v["verdict"], "evidence": v["evidence"],
                    "failed_checks": v["failed_checks"]}

        raise ValueError(f"unsupported deterministic flow '{flow}'; creative flows need an LLM orchestrator")

    def serve(self) -> int:
        for line in self._in:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "method" not in msg:  # a response to our outbound request handled inline
                continue
            resp = self.handle(msg)
            if resp is not None:
                self._send(resp)
        return 0


def _err(mid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    return AcpServer(stdin or sys.stdin, stdout or sys.stdout).serve()
