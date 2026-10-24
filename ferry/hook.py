"""A blocking PermissionRequest hook with single-operation decisions."""
import json
import os
import signal
import sys
import time
import uuid

from .core import FerryError, Store, TERMINAL, one_line, read_json, write_json
from .notify import send


def summarize(payload):
    tool = payload["tool_name"]
    data = payload["tool_input"]
    if not isinstance(tool, str) or not isinstance(data, dict):
        raise ValueError("Invalid tool request")
    if tool in ("Edit", "Write", "NotebookEdit"):
        detail = str(data.get("file_path", data.get("notebook_path", "")))
        kind, summary = "file_write", f"写入 {detail}"
    elif tool == "Bash":
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
        from .core import process_matches
        if (meta["status"] in TERMINAL or meta.get("cancel_requested")
                or not process_matches(request["hook_pid"], "hook-permission")):
            raise FerryError("RUN_NOT_ACTIVE", "Run or hook is no longer active")
        if not store.decide(request, "allowed" if answer == "allow" else "denied", note):
            raise FerryError("ALREADY_ANSWERED", "Approval already answered")
    return {"approval_id": approval_id, "decision": answer}


class HookCancelled(Exception):
    pass


def permission():
    decision = {"behavior": "deny", "message": "ferry approval channel failed; operation denied"}
    request = None
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
        request = {"approval_id": "a_" + uuid.uuid4().hex, "run_id": run_id,
                   "hook_pid": os.getpid(), "created_at": time.time(),
                   "expires_at": time.time() + store.config["approval_timeout_seconds"],
                   **summarize(payload)}
        with store.transaction():
            meta = store.meta(run_id)
            if meta["status"] in TERMINAL or meta.get("cancel_requested") or not store.alive(meta):
                raise ValueError("Run inactive")
            write_json(store.request_path(request["approval_id"]), request, exclusive=True)
        send(store, meta, f'ferry-approval:{request["approval_id"]}', "waiting_approval",
             one_line(f'{run_id} 需要审批：{request["summary"]}'), store.request_path(request["approval_id"]))
        path = store.decision_path(request["approval_id"])
        while True:
            with store.transaction():
                meta = store.meta(run_id)
                if meta.get("cancel_requested") or meta["status"] == "cancelled":
                    store.decide(request, "cancelled")
                elif meta["status"] in TERMINAL or not store.alive(meta):
                    store.decide(request, "interrupted")
                elif time.time() >= request["expires_at"]:
                    store.decide(request, "expired")
                if path.exists():
                    answer = read_json(path)
                    if answer["decision"] == "allowed" and not meta.get("cancel_requested") and meta["status"] not in TERMINAL:
                        decision = {"behavior": "allow"}
                    else:
                        decision = {"behavior": "deny", "message":
                                    f'ferry approval {answer["decision"]}: {answer["note"]}'}
                    break
            time.sleep(store.config["poll_interval_seconds"])
    except (Exception, HookCancelled):
        # Malformed stdin/config/state, cancellation, and I/O errors all return a deny.
        if store and request:
            try:
                if store.request_path(request["approval_id"]).exists():
                    store.decide(request, "cancelled")
            except Exception:
                pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}, ensure_ascii=False))
    return 0
