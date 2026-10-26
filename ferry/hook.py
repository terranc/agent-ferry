"""A blocking PermissionRequest hook with single-operation decisions."""
import json
import os
import signal
import sys
import time
from pathlib import Path

from .core import FerryError, Store, TERMINAL, one_line, read_json
from .approval import wait_for_approval


def summarize(payload):
    tool = payload["tool_name"]
    data = payload["tool_input"]
    if not isinstance(tool, str) or not isinstance(data, dict):
        raise ValueError("Invalid tool request")
    if tool in ("Edit", "Write", "NotebookEdit", "edit", "write"):
        detail = str(data.get("file_path", data.get("notebook_path", data.get("path", ""))))
        kind, summary = "file_write", f"写入 {detail}"
    elif tool in ("Bash", "bash"):
        detail = str(data.get("command", ""))
        kind, summary = "command", f"执行 {detail[:200]}"
        if data.get("description"):
            detail += "\n" + str(data["description"])
    else:
        detail = json.dumps(data, ensure_ascii=False)
        kind, summary = "other", f"{tool} {detail}"
    return {"kind": kind, "tool": tool, "summary": one_line(summary)[:240], "detail": detail[:2000]}


def approve(store, approval_id, answer, note):
    with store.transaction():
        try:
            request = read_json(store.request_path(approval_id))
        except FileNotFoundError:
            raise FerryError("NOT_FOUND", "Approval not found") from None
        path = store.decision_path(approval_id)
        decision = read_json(path) if path.exists() else None
        if (decision and decision["decision"] == "expired") or (not decision and time.time() >= request["expires_at"]):
            store.decide(request, "expired")
            raise FerryError("APPROVAL_EXPIRED", "Approval expired")
        if decision:
            code = "ALREADY_ANSWERED" if decision["decision"] in ("allowed", "denied") else "RUN_NOT_ACTIVE"
            raise FerryError(code, f'Approval is {decision["decision"]}')
        meta = store.reconcile(store.meta(request["run_id"]))
        if (meta["status"] in TERMINAL or meta.get("cancel_requested")
                or not store.request_alive(request)):
            raise FerryError("RUN_NOT_ACTIVE", "Run or hook is no longer active")
        if not store.decide(request, "allowed" if answer == "allow" else "denied", note):
            raise FerryError("ALREADY_ANSWERED", "Approval already answered")
    return {"approval_id": approval_id, "decision": answer}


class HookCancelled(Exception):
    pass


def permission(tool_gate=False):
    decision = {"behavior": "deny", "message": "ferry approval channel failed; operation denied"}
    store = None

    def cancelled(_signum, _frame):
        raise HookCancelled()

    signal.signal(signal.SIGTERM, cancelled)
    try:
        store = Store()
        run_id = os.environ.get("FERRY_RUN_ID", "")
        if not run_id:
            raise ValueError("Missing FERRY_RUN_ID")
        payload = json.load(sys.stdin)
        description = summarize(payload)
        if tool_gate:
            with store.transaction():
                meta = store.meta(run_id)
                if meta.get("agent") != "pi" or meta["status"] in TERMINAL or not store.alive(meta) or meta.get("cancel_requested"):
                    raise ValueError("Pi run inactive")
            tool, data = payload["tool_name"], payload["tool_input"]
            if tool in ("read", "grep", "find", "ls"):
                decision = {"behavior": "allow"}
            elif tool in ("write", "edit") and isinstance(data.get("path"), str):
                path = Path(meta["cwd"]) / data["path"]
                if Path(meta["cwd"]) in path.resolve().parents:
                    decision = {"behavior": "allow"}
                else:
                    decision = wait_for_approval(store, run_id, description, "hook-tool")
            else:
                decision = wait_for_approval(store, run_id, description, "hook-tool")
        else:
            decision = wait_for_approval(store, run_id, description, "hook-permission")
    except (Exception, HookCancelled):
        # Malformed stdin/config/state, cancellation, and I/O errors all return a deny.
        pass
    result = decision if tool_gate else {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}
    print(json.dumps(result, ensure_ascii=False))
    return 0
