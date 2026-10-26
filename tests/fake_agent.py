#!/usr/bin/env python3
"""Native protocol fixtures. This process never calls a model or network."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

if "--version" in sys.argv:
    print(os.environ.get("FERRY_TEST_VERSION", "9.9.9"))
    raise SystemExit(0)
if "inspect" in sys.argv:
    config = str(Path(os.environ["GROK_HOME"]) / "config.toml")
    print(json.dumps({"permissions": {"sources": [config + " (config)"], "skipped": [config] if os.environ.get("FERRY_TEST_SKIP_GUARD") else [], "loaded": 2}}))
    raise SystemExit(0)

args = sys.argv[1:]
agent = "codex" if "app-server" in args else "pi" if "rpc" in args else "grok" if "stdio" in args else "kimi"
run_id = os.environ["FERRY_RUN_ID"]
directory = Path(os.environ["XDG_STATE_HOME"]) / "agent-ferry/runs" / run_id
native_id = args[args.index("--session-id" if "--session-id" in args else "--session") + 1] if agent == "pi" else "native_" + run_id
seen = []
invocation = {"argv": args, "stdin": "", "cwd": os.getcwd(), "run_id": run_id,
              "pid": os.getpid(), "agent": agent, "messages": seen,
              "grok_home": os.environ.get("GROK_HOME")}
if agent == "grok":
    invocation["grok_policy"] = (Path(os.environ["GROK_HOME"]) / "requirements.toml").read_text()


def save():
    temp = directory / ".invocation.tmp"
    temp.write_text(json.dumps(invocation))
    temp.replace(directory / "invocation.json")


def emit(record):
    print(json.dumps(record, ensure_ascii=False), flush=True)


def receive():
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    record = json.loads(line)
    seen.append(record)
    save()
    return record


def reply(record, value):
    emit({"id": record["id"], "result": value})


def approval(target, permanent=False):
    if agent == "pi":
        proc = subprocess.run([os.environ["FERRY_ENTRY"], "hook-tool"], input=json.dumps({
            "tool_name": "write", "tool_input": {"path": target},
        }), capture_output=True, text=True)
        return json.loads(proc.stdout).get("behavior") == "allow"
    if agent == "codex":
        emit({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {
            "itemId": "tool-1", "command": f"echo approved > {target}", "cwd": os.getcwd(),
        }})
        return receive().get("result", {}).get("decision") == "accept"
    options = [{"kind": "allow_always" if permanent else "allow_once", "optionId": "yes"},
               {"kind": "reject_once", "optionId": "no"}]
    emit({"id": "approval-1", "method": "session/request_permission", "params": {
        "sessionId": native_id, "toolCall": {"title": "Write outside", "rawInput": {"path": target}},
        "options": options,
    }})
    answer = receive().get("result", {}).get("outcome", {})
    return answer.get("outcome") == "selected" and answer.get("optionId") == "yes"


def complete(record, prompt):
    invocation["stdin"] = prompt
    save()
    try:
        behavior = json.loads(prompt)
    except ValueError:
        behavior = {"text": prompt}
    if not isinstance(behavior, dict):
        behavior = {"text": prompt}
    mode = behavior.get("mode")
    if mode == "bad-json":
        print("not json", flush=True)
        raise SystemExit(0)
    if mode == "exit":
        print("native diagnostic", file=sys.stderr)
        raise SystemExit(1)
    if mode == "ignore-term":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if behavior.get("sleep"):
        time.sleep(behavior["sleep"])
    text = behavior.get("text", "native result")
    if behavior.get("target"):
        allowed = approval(behavior["target"], behavior.get("permanent", False))
        if allowed:
            Path(behavior["target"]).write_text("approved")
        text = "allowed" if allowed else "denied"
    if mode == "unknown-request":
        emit({"id": "unknown", "method": "fs/write_text_file", "params": {"path": "/never", "content": "x"}})
        text = "blocked" if "error" in receive() else "UNSAFE"
    if agent == "codex":
        emit({"method": "item/completed", "params": {"item": {"type": "agentMessage", "text": text}}})
        done = {"method": "turn/completed", "params": {"turn": {"status": "interrupted" if mode == "cancelled" else "failed" if mode == "failed" else "completed"}}}
        if mode == "early-complete":
            emit(done)
        reply(record, {"turn": {"id": "turn-1", "status": "inProgress"}})
        if mode != "early-complete":
            emit(done)
    elif agent == "pi":
        emit({"type": "response", "id": record["id"], "command": "prompt", "success": True})
        emit({"type": "agent_end"})
        time.sleep(0.05)
        emit({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": text}],
                                                  "usage": {"cost": {"total": 0.025}} if mode == "cost" else {},
                                                  "stopReason": "aborted" if mode == "cancelled" else "error" if mode == "failed" else "stop"}})
        emit({"type": "agent_settled"})
    else:
        emit({"method": "session/update", "params": {"sessionId": native_id, "update": {
            "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text},
        }}})
        reply(record, {"stopReason": "cancelled" if mode == "cancelled" else "max_turn_requests" if mode == "failed" else "end_turn"})


save()
if agent == "pi":
    if not os.environ.get("FERRY_TEST_NO_GUARD"):
        emit({"type": "extension_ui_request", "method": "notify", "message": "ferry_guard_ready:" + run_id})
    if "--model" in args:
        invocation["model"] = args[args.index("--model") + 1]
while True:
    record = receive()
    method = record.get("method", record.get("type"))
    if method == "initialize":
        reply(record, {"protocolVersion": 1, "agentCapabilities": {"loadSession": not os.environ.get("FERRY_TEST_NO_RESUME")}})
    elif method in ("thread/start", "thread/resume"):
        params = record["params"]
        native_id = params.get("threadId", native_id)
        invocation["model"] = params.get("model")
        reply(record, {"thread": {"id": native_id}})
    elif method in ("session/new", "session/load"):
        native_id = record["params"].get("sessionId", native_id)
        if method == "session/load":
            emit({"method": "session/update", "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "OLD HISTORY"}}}})
        result = {"sessionId": native_id, "modes": {"availableModes": [{"id": "default"}, {"id": "yolo"}]},
                  "configOptions": [{"category": "model", "id": "model"}]}
        if os.environ.get("FERRY_TEST_NO_MODES"):
            result.pop("modes")
        reply(record, result)
    elif method in ("session/set_config_option", "session/set_model"):
        invocation["model"] = record["params"].get("value", record["params"].get("modelId"))
        reply(record, {})
    elif method == "session/set_mode":
        invocation["mode"] = record["params"]["modeId"]
        reply(record, {})
    elif method == "turn/start":
        complete(record, record["params"]["input"][0]["text"])
    elif method == "session/prompt":
        complete(record, record["params"]["prompt"][0]["text"])
    elif method == "prompt":
        complete(record, record["message"])
