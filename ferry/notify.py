"""wake-on-done wire format; configuration is parsed, never executed."""
import datetime
import json
import shlex
import socket
import sys
import time
import urllib.request


def relay_config(store):
    values = {}
    try:
        for line in store.relay_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:].strip()
            key, sep, value = line.partition("=")
            if sep and key in ("WEBHOOK_RELAY_URL", "WEBHOOK_RELAY_KEY"):
                tokens = shlex.split(value, comments=True)
                if len(tokens) == 1:
                    values[key] = tokens[0]
    except (OSError, ValueError):
        return None
    url, key = values.get("WEBHOOK_RELAY_URL", ""), values.get("WEBHOOK_RELAY_KEY", "")
    key = key.removeprefix("Authorization: ").removeprefix("Bearer ")
    if not url.startswith(("https://", "http://")) or not key or "\n" in key or "\r" in key:
        return None
    return url, key


def send(store, meta, task, status, tail, log_path, exit_code=0):
    config = relay_config(store)
    if not config:
        print("ferry: relay URL/key missing; query ferry status for updates", file=sys.stderr)
        return False
    url, key = config
    body = json.dumps({
        "owner": meta["owner"], "task": task, "status": status, "exit_code": exit_code,
        "machine": socket.gethostname(),
        "started_at": datetime.datetime.fromtimestamp(meta["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        "ended_at": datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z"),
        "log_path": str(log_path), "output_tail": tail[:300],
    }, ensure_ascii=False).encode()
    for attempt in range(3):
        request = urllib.request.Request(url, data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if 200 <= response.status < 300:
                    return True
        except Exception:
            # Do not log the URL, headers, exception, or response body: these can contain keys.
            pass
        if attempt < 2:
            time.sleep(min(store.config["poll_interval_seconds"], 5) * (attempt + 1))
    print("ferry: relay notification failed after 3 attempts", file=sys.stderr)
    return False
