#!/usr/bin/env python3
"""Contract fake: invokes the rendered hook rather than mocking its result."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

if "--version" in sys.argv:
    print("2.1.310 (fake Claude Code)")
    raise SystemExit(0)

args = sys.argv[1:]
prompt = sys.stdin.read()
session_id = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
run_id = os.environ["FERRY_RUN_ID"]
state = Path(os.environ["XDG_STATE_HOME"]) / "agent-ferry/runs" / run_id
(state / "invocation.json").write_text(json.dumps({
    "argv": args, "stdin": prompt, "cwd": os.getcwd(), "run_id": run_id, "pid": os.getpid(),
}))
if prompt.startswith("@@ignore-term"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    (state / "ignoring-term").touch()
    time.sleep(60)
if prompt.startswith("@@sleep:"):
    time.sleep(float(prompt.split(":", 1)[1]))
if prompt == "@@bad-json":
    print("invalid json")
    print("bad json diagnostic", file=sys.stderr)
    raise SystemExit(0)
if prompt == "@@array-json":
    print("[]")
    raise SystemExit(0)
if prompt == "@@fail":
    print("fake failure", file=sys.stderr)
    raise SystemExit(1)
result = prompt
if prompt.startswith("@@ask:"):
    # JSON holds requests so arbitrary ':' characters in paths are preserved.
    requests = json.loads(prompt[len("@@ask:"):])
    results = []
    settings = json.loads(Path(args[args.index("--settings") + 1]).read_text())
    handler = settings["hooks"]["PermissionRequest"][0]["hooks"][0]
    for index, request in enumerate(requests):
        hook = subprocess.run([handler["command"], *handler["args"]], input=json.dumps({
            "hook_event_name": "PermissionRequest", "session_id": session_id,
            "tool_name": request["tool"], "tool_input": request["input"],
        }), text=True, capture_output=True)
        (state / f"hook-{index}.json").write_text(hook.stdout)
        try:
            decision = json.loads(hook.stdout)["hookSpecificOutput"]["decision"]
        except (ValueError, KeyError):
            decision = {"behavior": "deny", "message": "invalid hook result"}
        if decision["behavior"] == "allow":
            Path(request["target"]).write_text("approved")
            results.append("allowed")
        else:
            results.append(decision.get("message", "denied"))
    result = "\n".join(results)
if prompt == "@@error-result":
    print("fake error result", file=sys.stderr)
print(json.dumps({"type": "result", "subtype": "success", "is_error": prompt == "@@error-result",
                  "session_id": session_id, "result": result, "total_cost_usd": 0.01, "num_turns": 1}))
