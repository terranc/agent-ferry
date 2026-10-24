#!/usr/bin/env python3
"""A local wake-on-done process wrapper, preserving argv and completion status."""
import json
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
separator = args.index("--")
log = Path(args[args.index("--log") + 1])
(log.parent / "notify-argv.json").write_text(json.dumps(args))
with log.open("w") as stream:
    result = subprocess.run(args[separator + 1:], stdout=stream, stderr=stream)
(log.parent / "notification.json").write_text(json.dumps({
    "owner": args[args.index("--owner") + 1], "task": args[args.index("--task") + 1],
    "status": "succeeded" if result.returncode == 0 else "failed",
    "output_tail": log.read_text()[-300:], "exit_code": result.returncode,
}))
raise SystemExit(result.returncode)
