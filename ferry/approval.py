"""Shared, fail-closed approval waiting for hooks and protocol clients."""
import os
import time
import uuid

from .core import TERMINAL, one_line, read_json, write_json
from .notify import send


def wait_for_approval(store, run_id, description, requester):
    request = {"approval_id": "a_" + uuid.uuid4().hex, "run_id": run_id,
               "hook_pid": os.getpid(), "requester": requester, "created_at": time.time(),
               "expires_at": time.time() + store.config["approval_timeout_seconds"], **description}
    with store.transaction():
        meta = store.meta(run_id)
        if meta["status"] in TERMINAL or meta.get("cancel_requested") or not store.alive(meta):
            return {"behavior": "deny", "message": "Run inactive"}
        write_json(store.request_path(request["approval_id"]), request, exclusive=True)
    try:
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
                        return {"behavior": "allow"}
                    return {"behavior": "deny", "message": f'ferry approval {answer["decision"]}: {answer["note"]}'}
            time.sleep(store.config["poll_interval_seconds"])
    finally:
        # Also invalidate the request when the caller is cancelled or its protocol crashes.
        store.decide(request, "interrupted")
