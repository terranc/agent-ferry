"""JSONL clients for native Codex, ACP and Pi processes."""
import json
import math
import queue
import threading
import time

from .approval import wait_for_approval
from .core import FerryError, one_line
from .hook import summarize


class Peer:
    def __init__(self, child, store, meta, log):
        self.child, self.store, self.meta, self.log = child, store, meta, log
        self.agent = meta["agent"]
        self.events = queue.Queue(maxsize=256)
        self.next_id = 0
        self.deadline = time.monotonic() + store.config["agent_start_timeout_seconds"]
        self.text = []
        self.replaying = False
        self.last_error = None
        self.file_changes = {}
        self.completed_turn = None
        self.cost = None
        self.denied = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                raw = self.child.stdout.readline(16 * 1024 * 1024 + 1)
                if not raw:
                    self.events.put(EOFError("Agent exited before completing the protocol"))
                    return
                if len(raw) > 16 * 1024 * 1024:
                    raise ValueError("Agent protocol record exceeds 16 MB")
                self.log.write(raw)
                self.log.flush()
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError("Agent protocol record is not an object")
                self.events.put(event)
        except Exception as exc:
            self.events.put(exc)

    def read(self):
        timeout = max(0, self.deadline - time.monotonic()) if self.deadline is not None else None
        try:
            record = self.events.get(timeout=timeout)
        except queue.Empty:
            raise FerryError("AGENT_START_TIMEOUT", "Agent initialization timed out") from None
        if isinstance(record, Exception):
            raise FerryError("PROTOCOL_ERROR", str(record)) from record
        return record

    def send(self, record):
        self.child.stdin.write((json.dumps(record, ensure_ascii=False) + "\n").encode())
        self.child.stdin.flush()

    def wire(self, method, params, request_id=None):
        value = {"method": method, "params": params}
        if request_id is not None:
            value["id"] = request_id
        if self.agent in ("grok", "kimi"):
            value["jsonrpc"] = "2.0"
        return value

    def call(self, method, params):
        self.next_id += 1
        request_id = f"ferry-{self.next_id}"
        self.send(self.wire(method, params, request_id))
        while True:
            record = self.read()
            if "method" in record:
                self.dispatch(record)
            elif record.get("id") == request_id:
                if "error" in record:
                    raise FerryError("AGENT_PROTOCOL_ERROR", one_line(record["error"].get("message", "Agent request failed")))
                return record.get("result", {})

    def reply(self, record, result=None, error=None):
        response = {"id": record["id"]}
        if self.agent in ("grok", "kimi"):
            response["jsonrpc"] = "2.0"
        response["error" if error else "result"] = error if error else result
        self.send(response)

    def ask(self, payload, record):
        if not isinstance(payload, dict):
            raise FerryError("PROTOCOL_ERROR", "Malformed native approval request")
        description = summarize(payload)
        description["native_request"] = {"request": record, "tool_request": payload}
        started = time.monotonic()
        try:
            allowed = wait_for_approval(self.store, self.meta["run_id"], description, "_exec")["behavior"] == "allow"
            self.denied = self.denied or not allowed
            return allowed
        finally:
            if self.deadline is not None:
                self.deadline += time.monotonic() - started

    def dispatch(self, record):
        method, params = record["method"], record.get("params", {})
        if not isinstance(params, dict):
            raise FerryError("PROTOCOL_ERROR", "Invalid protocol params")
        if "id" in record:
            if self.agent == "codex" and method in ("item/commandExecution/requestApproval", "item/fileChange/requestApproval"):
                command = method.startswith("item/commandExecution")
                data = {"command": params.get("command", json.dumps(params, ensure_ascii=False))} if command else self.file_changes.get(params.get("itemId"), params)
                allowed = self.ask({"tool_name": "Bash" if command else "CodexFileChange", "tool_input": data}, record)
                self.reply(record, {"decision": "accept" if allowed else "decline"})
            elif self.agent in ("grok", "kimi") and method == "session/request_permission":
                options = params.get("options", [])
                allow = next((o for o in options if o.get("kind") == "allow_once"), None)
                deny = next((o for o in options if o.get("kind") == "reject_once"), None)
                if not allow:
                    self.reply(record, {"outcome": {"outcome": "cancelled"}})
                    return
                tool = params.get("toolCall", {})
                # Native requests are reviewed conservatively, never remembered for a session.
                raw = tool.get("rawInput", {})
                payload = {"tool_name": "ACP: " + str(tool.get("title", "Agent operation")), "tool_input": tool}
                if isinstance(raw, dict) and isinstance(raw.get("command"), str):
                    payload = {"tool_name": "Bash", "tool_input": raw}
                allowed = self.ask(payload, record)
                selected = allow if allowed else deny
                outcome = {"outcome": "selected", "optionId": selected["optionId"]} if selected else {"outcome": "cancelled"}
                self.reply(record, {"outcome": outcome})
            elif self.agent == "codex" and method == "item/permissions/requestApproval":
                # A turn-wide filesystem grant is broader than our single-operation approval.
                self.reply(record, {"permissions": {}})
            else:
                # No filesystem/terminal delegation was advertised. Unknown side effects fail closed.
                self.reply(record, error={"code": -32601, "message": "Unsupported ferry client request; operation denied"})
            return
        if self.agent == "codex":
            if method == "turn/completed":
                self.completed_turn = params.get("turn", {})
            elif method == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage":
                    self.text = [item.get("text", "")]
            elif method == "item/started" and params.get("item", {}).get("type") == "fileChange":
                item = params["item"]
                self.file_changes[item["id"]] = item
            elif method == "error":
                self.last_error = params.get("error", {}).get("message", "Agent error")
        elif method == "session/update" and not self.replaying:
            update = params.get("update", {})
            if update.get("sessionUpdate") == "agent_message_chunk":
                content = update.get("content", {})
                if content.get("type") == "text":
                    self.text.append(content.get("text", ""))

    def bind(self, session_id):
        self.meta["session_id"] = self.store.bind_session(self.meta["run_id"], session_id)

    def result(self, cancelled=False):
        if cancelled and not self.text and self.denied:
            self.text = ["该工具在审批被拒绝后结束了本轮。"]
        return {"session_id": self.meta["session_id"], "result": "".join(self.text),
                "is_error": False, "cancelled": cancelled, "total_cost_usd": self.cost, "num_turns": None}

    def codex(self):
        self.call("initialize", {"clientInfo": {"name": "agent-ferry", "version": "1"}})
        self.send({"method": "initialized"})
        params = {"cwd": self.meta["cwd"], "approvalPolicy": "untrusted", "sandbox": "workspace-write",
                  "config": {"sandbox_workspace_write.network_access": True}}
        if self.meta.get("model") is not None:
            params["model"] = self.meta["model"]
        if self.meta["new_session"]:
            thread = self.call("thread/start", params)["thread"]
        else:
            thread = self.call("thread/resume", {"threadId": self.meta["session_id"], **params})["thread"]
        self.bind(thread["id"])
        self.deadline = None
        self.call("turn/start", {"threadId": thread["id"], "input": [{"type": "text", "text": self.meta["prompt"]}]})
        while True:
            if self.completed_turn is not None:
                if self.completed_turn.get("status") == "interrupted":
                    return self.result(cancelled=True)
                if self.completed_turn.get("status") != "completed":
                    raise FerryError("AGENT_FAILED", one_line(self.completed_turn.get("error") or self.last_error or "Codex turn failed"))
                return self.result()
            record = self.read()
            self.dispatch(record) if "method" in record else None

    def acp(self):
        initialized = self.call("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                                              "clientInfo": {"name": "agent-ferry", "version": "1"}})
        if initialized.get("protocolVersion") != 1:
            raise FerryError("UNSUPPORTED_AGENT", "Unsupported ACP version")
        params = {"cwd": self.meta["cwd"], "mcpServers": [], "_meta": {"yoloMode": False}}
        if self.meta["new_session"]:
            created = self.call("session/new", params)
            self.bind(created["sessionId"])
        else:
            if not initialized.get("agentCapabilities", {}).get("loadSession"):
                raise FerryError("UNSUPPORTED_AGENT", "Agent cannot resume sessions")
            self.replaying = True
            created = self.call("session/load", {"sessionId": self.meta["session_id"], **params})
            self.replaying = False
            self.bind(self.meta["session_id"])
        sid = self.meta["session_id"]
        modes = created.get("modes", {})
        if self.agent == "kimi":
            safe = next((m for m in modes.get("availableModes", []) if m.get("id") == "default"), None)
            if not safe:
                raise FerryError("UNSAFE_AGENT", "Kimi does not advertise its manual approval mode")
        # Grok additionally needs its isolated policy; a mode change alone is insufficient.
        self.call("session/set_mode", {"sessionId": sid, "modeId": "ask" if self.agent == "grok" else "default"})
        if self.meta.get("model") is not None:
            configs = created.get("configOptions", [])
            model = next((c for c in configs if c.get("category") == "model"), None)
            if model:
                self.call("session/set_config_option", {"sessionId": sid, "configId": model["id"], "value": self.meta["model"]})
            elif "models" in created:
                self.call("session/set_model", {"sessionId": sid, "modelId": self.meta["model"]})
            else:
                raise FerryError("UNSUPPORTED_MODEL", "Agent does not expose model selection")
        self.text = []
        self.deadline = None
        done = self.call("session/prompt", {"sessionId": sid, "prompt": [{"type": "text", "text": self.meta["prompt"]}]})
        if done.get("stopReason") == "cancelled":
            return self.result(cancelled=True)
        if done.get("stopReason") != "end_turn":
            raise FerryError("AGENT_FAILED", f'Agent stopped: {done.get("stopReason", "unknown")}')
        return self.result()

    def pi(self):
        while True:
            record = self.read()
            if (record.get("type") == "extension_ui_request" and record.get("method") == "notify"
                    and record.get("message") == "ferry_guard_ready:" + self.meta["run_id"]):
                break
        self.deadline = None
        self.send({"id": "prompt", "type": "prompt", "message": self.meta["prompt"]})
        failed = False
        cancelled = False
        while True:
            record = self.read()
            if record.get("type") == "response" and record.get("success") is False:
                raise FerryError("AGENT_FAILED", one_line(record.get("error", "Pi request failed")))
            if record.get("type") == "extension_ui_request" and record.get("method") in ("confirm", "select", "input", "editor"):
                self.send({"type": "extension_ui_response", "id": record["id"], "cancelled": True})
            if record.get("type") == "message_end":
                message = record.get("message", {})
                if message.get("role") == "assistant":
                    cost = message.get("usage", {}).get("cost", {}).get("total")
                    if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
                        self.cost = (self.cost or 0) + cost
                    self.text = [p["text"] for p in message.get("content", []) if p.get("type") == "text"]
                    failed = message.get("stopReason") == "error"
                    cancelled = message.get("stopReason") == "aborted"
                    if failed:
                        self.last_error = message.get("errorMessage")
            if record.get("type") == "agent_settled":
                if cancelled:
                    return self.result(cancelled=True)
                if failed:
                    raise FerryError("AGENT_FAILED", self.last_error or "Pi turn failed")
                return self.result()


def execute_protocol(child, store, meta, log):
    peer = Peer(child, store, meta, log)
    result = peer.codex() if meta["agent"] == "codex" else peer.pi() if meta["agent"] == "pi" else peer.acp()
    child.stdin.close()
    try:
        child.wait(timeout=5)
    except Exception:
        raise FerryError("AGENT_FAILED", "Agent did not shut down after its completed turn") from None
    if child.returncode != 0:
        raise FerryError("AGENT_FAILED", f"Agent exited {child.returncode}")
    return result
