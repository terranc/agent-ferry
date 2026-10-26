"""JSON-only public CLI."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from .core import AGENTS, FerryError, Store, TERMINAL, executable, read_json
from .agents import supported_version
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
            "status": "waiting_approval" if pending else meta["status"], "agent": meta.get("agent", "claude"),
            "model": meta.get("model"),
            "created_at": meta["created_at"], "started_at": meta.get("started_at"), "ended_at": meta.get("ended_at"),
            "result": result[:store.config["result_max_chars"]] if truncated else result,
            "result_truncated": truncated, "cost_usd": meta.get("cost_usd"), "num_turns": meta.get("num_turns"),
            "error": meta.get("error"), "stderr_tail": meta.get("stderr_tail", ""),
            "pending_approvals": pending, "resume_cmd": store.resume_cmd(meta)}


def sessions(store, cwd=None, agent=None):
    grouped = {}
    with store.transaction():
        # debt: linear scan of retained runs; add a session index if tens of thousands become slow.
        metas = sorted((read_json(p) for p in store.runs.glob("*/meta.json")), key=lambda m: m["created_at"])
        for raw in metas:
            meta = store.reconcile(raw)
            if agent and meta.get("agent", "claude") != agent:
                continue
            if cwd and Path(cwd).expanduser().resolve() != Path(meta["cwd"]):
                continue
            session_id = meta["session_id"]
            if not session_id:
                continue
            key = (meta.get("agent", "claude"), session_id)
            previous = grouped.get(key, {})
            grouped[key] = {
                "agent": key[0],
                "session_id": session_id, "cwd": meta["cwd"],
                "first_prompt": previous.get("first_prompt", meta["prompt"][:60]),
                "last_active_at": meta.get("ended_at") or meta.get("started_at") or meta["created_at"],
                "running": meta["status"] not in TERMINAL, "status": meta["status"],
                "resume_cmd": store.resume_cmd(meta),
            }
    return {"sessions": sorted(grouped.values(), key=lambda s: s["last_active_at"], reverse=True)}


def doctor(store, agent="claude"):
    checks = []

    def add(name, state, detail):
        checks.append({"name": name, "status": state, "detail": detail})

    for selected in AGENTS if agent == "all" else (agent,):
        binary = executable(store.config[f"{selected}_bin"])
        if binary:
            try:
                version = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=10)
                valid = version.returncode == 0 and supported_version(selected, version.stdout)
                add(selected, "pass" if valid else "fail", version.stdout.strip()[:200] or "Version check failed")
            except (OSError, subprocess.TimeoutExpired):
                add(selected, "fail", "Agent version check failed")
        else:
            add(selected, "fail", f"{selected} executable not found")
        if selected == "grok":
            add("grok_policy_runtime", "pass" if sys.version_info >= (3, 11) else "fail", "Grok policy isolation requires Python 3.11+")
            grok_home = Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))).expanduser()
            owner_policy = (grok_home / "requirements.toml").exists()
            add("grok_owner_policy", "fail" if owner_policy else "pass",
                "Existing requirements.toml needs policy composition review" if owner_policy else "Per-run approval policy can be isolated")
    add("python3", "pass" if sys.version_info >= (3, 9) else "fail", sys.version.split()[0])
    ready = bool(executable(store.config["notify_run_bin"]) and relay_config(store))
    add("wake-on-done", "pass" if ready else "warn", "ready" if ready else "notify-run or relay URL/key missing; poll status")
    root = Path(store.config["workspace_root"]).expanduser()
    add("workspace_root", "pass" if root.is_dir() else "fail", str(root))
    add("caffeinate", "pass" if executable(store.config["caffeinate_bin"]) else "fail", "idle sleep prevention")
    if agent in ("claude", "all"):
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
    add("real_validation", "warn", "Check selected agent permissions and completion/approval delivery in your real Bot; doctor does not run model tasks")
    return {"checks": checks, "healthy": all(c["status"] != "fail" for c in checks)}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Hook must fail closed even if configuration loading or CLI parsing fails.
    if argv in (["hook-permission"], ["hook-tool"]):
        return permission(tool_gate=argv == ["hook-tool"])
    try:
        parser = Parser(prog="ferry", description="Run local coding agents in the background; public output is JSON")
        sub = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
        run = sub.add_parser("run")
        run.add_argument("--owner", required=True)
        run.add_argument("--cwd", required=True)
        run.add_argument("--session")
        run.add_argument("--agent", choices=AGENTS, default="claude")
        run.add_argument("--model", help="Native agent model alias or full model ID for this run")
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
        listing.add_argument("--agent", choices=AGENTS)
        diagnostics = sub.add_parser("doctor")
        diagnostics.add_argument("--agent", choices=(*AGENTS, "all"), default="claude")
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
            result = launch(store, args.cwd, prompt, args.session, args.owner, model=args.model, agent=args.agent)
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
            result = sessions(store, args.cwd, args.agent)
        elif args.command == "doctor":
            result = doctor(store, args.agent)
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
