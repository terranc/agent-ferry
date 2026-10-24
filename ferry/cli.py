"""JSON-only public CLI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .core import FerryError, Store, TERMINAL, executable, read_json
from .hook import approve, permission
from .notify import relay_config
from .runner import cancel, execute, launch


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FerryError("INVALID_ARGUMENT", message)


def status(store, run_id, full=False):
    with store.transaction():
        meta = store.reconcile(store.meta(run_id))
        pending = store.pending(run_id) if meta["status"] not in TERMINAL else []
    result = meta.get("result")
    truncated = bool(result and not full and len(result) > store.config["result_max_chars"])
    return {"run_id": run_id, "session_id": meta["session_id"], "cwd": meta["cwd"],
            "status": "waiting_approval" if pending else meta["status"],
            "created_at": meta["created_at"], "started_at": meta.get("started_at"), "ended_at": meta.get("ended_at"),
            "result": result[:store.config["result_max_chars"]] if truncated else result,
            "result_truncated": truncated, "cost_usd": meta.get("cost_usd"), "num_turns": meta.get("num_turns"),
            "error": meta.get("error"), "stderr_tail": meta.get("stderr_tail", ""),
            "pending_approvals": pending, "resume_cmd": store.resume_cmd(meta)}


def sessions(store, cwd=None):
    grouped = {}
    with store.transaction():
        # debt: linear scan of retained runs; add a session index if tens of thousands become slow.
        metas = sorted((read_json(p) for p in store.runs.glob("*/meta.json")), key=lambda m: m["created_at"])
        for raw in metas:
            meta = store.reconcile(raw)
            if cwd and Path(cwd).expanduser().resolve() != Path(meta["cwd"]):
                continue
            session_id = meta["session_id"]
            previous = grouped.get(session_id, {})
            grouped[session_id] = {
                "session_id": session_id, "cwd": meta["cwd"],
                "first_prompt": previous.get("first_prompt", meta["prompt"][:60]),
                "last_active_at": meta.get("ended_at") or meta.get("started_at") or meta["created_at"],
                "running": meta["status"] not in TERMINAL, "status": meta["status"],
                "resume_cmd": store.resume_cmd(meta),
            }
    return {"sessions": sorted(grouped.values(), key=lambda s: s["last_active_at"], reverse=True)}


def doctor(store):
    checks = []

    def add(name, state, detail):
        checks.append({"name": name, "status": state, "detail": detail})

    claude = executable(store.config["claude_bin"])
    if claude:
        try:
            version = subprocess.run([claude, "--version"], capture_output=True, text=True, timeout=5)
            add("claude", "pass" if version.returncode == 0 else "fail", version.stdout.strip()[:200])
        except (OSError, subprocess.TimeoutExpired):
            add("claude", "fail", "Claude version check failed")
    else:
        add("claude", "fail", "Claude Code not found")
    add("python3", "pass" if sys.version_info >= (3, 9) else "fail", sys.version.split()[0])
    ready = bool(executable(store.config["notify_run_bin"]) and relay_config(store))
    add("wake-on-done", "pass" if ready else "warn", "ready" if ready else "notify-run or relay URL/key missing; poll status")
    root = Path(store.config["workspace_root"]).expanduser()
    add("workspace_root", "pass" if root.is_dir() else "fail", str(root))
    add("caffeinate", "pass" if executable(store.config["caffeinate_bin"]) else "fail", "idle sleep prevention")
    settings_path = Path.home() / ".claude/settings.json"
    try:
        settings = read_json(settings_path) if settings_path.exists() else {}
        hooks = settings.get("hooks", {}).get("PermissionRequest", [])
        permissions = settings.get("permissions", {})
        rules = permissions.get("allow", [])
        broad = any(rule == "*" or rule.startswith("Bash") for rule in rules)
        mode = permissions.get("defaultMode", "default")
        conflicts = []
        if hooks:
            conflicts.append("PermissionRequest hooks may race ferry decisions")
        if broad:
            conflicts.append("Bash allow rules may bypass approvals for unsandboxed retries")
        if mode in ("bypassPermissions", "dontAsk", "auto"):
            conflicts.append("defaultMode may interfere with approvals")
        if settings.get("disableAllHooks"):
            conflicts.append("disableAllHooks disables the approval channel")
        add("user_settings", "warn" if conflicts else "pass", "; ".join(conflicts) or "no known conflicts")
    except (OSError, ValueError, AttributeError, TypeError):
        add("user_settings", "warn", "Cannot parse user settings")
    add("real_validation", "warn", "Claude hook/sandbox assumptions S1-S8/S10 and relay S9 await real validation")
    return {"checks": checks, "healthy": all(c["status"] != "fail" for c in checks)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Hook must fail closed even if configuration loading or CLI parsing fails.
    if argv == ["hook-permission"]:
        return permission()
    try:
        parser = Parser(prog="ferry", description="Run Claude Code in the background; public output is JSON")
        sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
        run = sub.add_parser("run")
        run.add_argument("--owner", required=True)
        run.add_argument("--cwd", required=True)
        run.add_argument("--session")
        run.add_argument("--model", help="Claude model alias or full model ID for this run")
        run.add_argument("--prompt-file")
        query = sub.add_parser("status")
        query.add_argument("run_id")
        query.add_argument("--full", action="store_true")
        approvals = sub.add_parser("approvals")
        approvals.add_argument("--run")
        answer = sub.add_parser("approve")
        answer.add_argument("approval_id")
        answer.add_argument("answer", choices=("allow", "deny"))
        answer.add_argument("--note", default="")
        stop = sub.add_parser("cancel")
        stop.add_argument("run_id")
        listing = sub.add_parser("sessions")
        listing.add_argument("--cwd")
        sub.add_parser("doctor")
        worker = sub.add_parser("_exec")
        worker.add_argument("run_id")
        args = parser.parse_args(argv)
        store = Store()
        if args.command == "run":
            if args.prompt_file:
                prompt = Path(args.prompt_file).read_bytes().decode("utf-8")
            else:
                if sys.stdin.isatty():
                    raise FerryError("EMPTY_PROMPT", "Use --prompt-file or pipe prompt on stdin")
                prompt = sys.stdin.read()
            result = launch(store, args.cwd, prompt, args.session, args.owner, model=args.model)
        elif args.command == "status":
            result = status(store, args.run_id, args.full)
        elif args.command == "approvals":
            with store.transaction():
                runs = {args.run} if args.run else {r["run_id"] for r in store.requests()}
                for run_id in runs:
                    store.reconcile(store.meta(run_id))
                result = {"approvals": store.pending(args.run)}
        elif args.command == "approve":
            result = approve(store, args.approval_id, args.answer, args.note)
        elif args.command == "cancel":
            result = cancel(store, args.run_id)
        elif args.command == "sessions":
            result = sessions(store, args.cwd)
        elif args.command == "doctor":
            result = doctor(store)
        else:
            return execute(store, args.run_id)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
        return 0
    except FerryError as exc:
        error = {"code": exc.code, "message": str(exc)}
    except (OSError, ValueError, TypeError) as exc:
        error = {"code": "IO_ERROR", "message": str(exc)}
    print(json.dumps({"ok": False, "error": error}, ensure_ascii=False))
    return 2
