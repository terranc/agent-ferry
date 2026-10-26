"""Detached workers and process lifecycle management."""
import datetime
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

from .core import FerryError, TERMINAL, executable, one_line, process_birth, read_json
from .core import signal_group as kill_group
from .notify import relay_config, send
from . import agents
from .protocols import execute_protocol


def launch(store, cwd, prompt, session_id, owner, model=None, agent="claude"):
    root = Path(store.config["workspace_root"]).expanduser().resolve()
    cwd = Path(cwd).expanduser().resolve()
    if cwd == root or root not in cwd.parents or not cwd.is_dir():
        raise FerryError("INVALID_CWD", f"cwd must be an existing directory strictly below {root}")
    new_session = session_id is None
    session_id = agents.session_id(agent, session_id)
    if not prompt.strip():
        raise FerryError("EMPTY_PROMPT", "Prompt must not be empty")
    if not owner.strip():
        raise FerryError("INVALID_ARGUMENT", "owner must not be empty")
    if model is not None and not model.strip():
        raise FerryError("INVALID_ARGUMENT", "model must not be empty")
    if not executable(store.config[f"{agent}_bin"]):
        raise FerryError("CLAUDE_NOT_FOUND" if agent == "claude" else "AGENT_NOT_FOUND", f"{agent} executable not found")
    run_id = "r_" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S_") + uuid.uuid4().hex[:12]
    notify = bool(executable(store.config["notify_run_bin"]) and relay_config(store))
    with store.transaction():
        store.cleanup()
        lock = store.session_lock(agent, session_id) if session_id else None
        if lock and lock.exists():
            try:
                previous = store.reconcile(store.meta(lock.read_text()))
                if previous["status"] not in TERMINAL:
                    raise FerryError("SESSION_BUSY", "Session already has an active run")
            except FerryError as exc:
                if exc.code != "NOT_FOUND":
                    raise
            lock.unlink(missing_ok=True)
        if lock:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                stream.write(run_id)
        meta = {"run_id": run_id, "session_id": session_id, "new_session": new_session,
                "cwd": str(cwd), "owner": owner, "prompt": prompt, "model": model, "agent": agent, "created_at": time.time(),
                "started_at": None, "ended_at": None, "status": "starting", "notify": notify}
        try:
            store.run_dir(run_id).mkdir(mode=0o700)
            store.save(meta)
            if agent == "claude":
                store.render()
            argv = [str(store.entry), "_exec", run_id]
            if notify:
                argv = [executable(store.config["notify_run_bin"]), "--owner", owner,
                        "--task", f"ferry:{run_id}", "--log", str(store.run_dir(run_id) / "notify.log"), "--", *argv]
            fd = os.open(store.run_dir(run_id) / "notify.log", os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            with os.fdopen(fd, "ab") as log:
                proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            meta.update(launcher_pid=proc.pid, pgid=proc.pid)
            store.save(meta)
        except BaseException:
            meta.update(status="failed", ended_at=time.time())
            store.save(meta)
            store.release(meta)
            raise
    result = {"run_id": run_id, "session_id": session_id, "new_session": new_session, "agent": agent,
              "status": "starting", "notify": "wake-on-done" if notify else "none",
              "next": f"收到 ferry:{run_id} 通知后执行 ferry status {run_id}"}
    if not notify:
        result["warning"] = "wake-on-done is not ready; poll ferry status for results and approvals"
    # Wait briefly for worker publication so a successful launch normally already has Claude.
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        current = store.meta(run_id)
        if current.get("agent_pid") or current.get("claude_pid") or current["status"] in TERMINAL:
            break
        time.sleep(0.01)
    result["session_id"] = store.meta(run_id).get("session_id")
    return result


class Cancelled(Exception):
    pass


def stop_child(child):
    if child is None:
        return
    kill_group(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        kill_group(child.pid, signal.SIGKILL)
        child.wait()
    # A child shell may have exited while its descendants ignored TERM.
    kill_group(child.pid, signal.SIGKILL)


def summary(meta):
    prefix = f'ferry {meta["run_id"]} {meta["status"]} session={meta["session_id"]} | '
    return (prefix + one_line(meta.get("result") or meta.get("error", ""))[:180])[:300]


def execute(store, run_id):
    child = None
    caffeine = None
    meta = None
    status, error, output = "failed", None, {}

    def cancelled(_signum, _frame):
        raise Cancelled()

    signal.signal(signal.SIGTERM, cancelled)
    try:
        meta = store.meta(run_id)
        agents.check_version(store, meta.get("agent", "claude"))
        agent_env = agents.environment(store, meta)
        with store.transaction():
            meta = store.meta(run_id)
            if meta.get("cancel_requested") or meta["status"] in TERMINAL:
                raise Cancelled()
            meta.update(status="running", started_at=time.time(), worker_pid=os.getpid())
            store.save(meta)
            agent = meta.get("agent", "claude")
            argv = agents.argv(store, meta)
            env = {**os.environ, "FERRY_RUN_ID": run_id, "FERRY_ENTRY": str(store.entry)}
            env.update(agent_env)
            directory = store.run_dir(run_id)
            out_fd = os.open(directory / ("claude.json" if agent == "claude" else "agent.jsonl"), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            err_fd = os.open(directory / f"{agent}.stderr.log", os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(out_fd, "wb") as stdout, os.fdopen(err_fd, "wb") as stderr:
                child = subprocess.Popen(argv, cwd=meta["cwd"], env=env, stdin=subprocess.PIPE,
                                         stdout=stdout if agent == "claude" else subprocess.PIPE, stderr=stderr, start_new_session=True)
            meta.update(agent_pid=child.pid, agent_birth=process_birth(child.pid))
            if agent == "claude":
                meta["claude_pid"] = child.pid
            store.save(meta)
        caffeine_bin = executable(store.config["caffeinate_bin"])
        if caffeine_bin:
            caffeine = subprocess.Popen([caffeine_bin, "-i", "-w", str(child.pid)],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if agent == "claude":
            child.communicate(meta["prompt"].encode("utf-8"))
            candidate = read_json(directory / "claude.json")
        else:
            with (directory / "agent.jsonl").open("ab") as log:
                candidate = execute_protocol(child, store, meta, log)
            meta = store.meta(run_id)
        if (not isinstance(candidate, dict) or not isinstance(candidate.get("result"), str)
                or candidate.get("session_id") != meta["session_id"]):
            raise ValueError("Invalid Claude JSON result or session_id")
        output = candidate
        status = "completed" if child.returncode == 0 and not output.get("is_error") else "failed"
        if agent != "claude" and output.get("cancelled") is True:
            status = "cancelled"
        if status == "failed":
            error = f"{agent} exited {child.returncode}; is_error={output.get('is_error')}"
    except Cancelled:
        status = "cancelled"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if meta and status == "cancelled":
            with store.transaction():
                current = store.meta(run_id)
                current["cancel_requested"] = True
                store.save(current)
                store.finish_approvals(run_id, "cancelled")
                hooks = list(store.requests(run_id))
            # Let a waiting hook return its deny before stopping Claude and its process group.
            deadline = time.monotonic() + min(store.config["poll_interval_seconds"] + 0.2, 2.2)
            while time.monotonic() < deadline and any(
                    r.get("requester", "hook-permission") != "_exec" and store.request_alive(r) for r in hooks):
                time.sleep(0.03)
        if status != "completed":
            stop_child(child)
        if caffeine:
            try:
                caffeine.wait(timeout=1)
            except subprocess.TimeoutExpired:
                caffeine.terminate()
                caffeine.wait()
        if meta:
            agents.cleanup_environment(store, meta)
            with store.transaction():
                meta = store.meta(run_id)
                if meta.get("cancel_requested") or meta["status"] == "cancelled":
                    status = "cancelled"
                stderr_path = store.run_dir(run_id) / f'{meta.get("agent", "claude")}.stderr.log'
                stderr_tail = ""
                if stderr_path.exists() and status == "failed":
                    with stderr_path.open("rb") as stream:
                        stream.seek(max(0, stderr_path.stat().st_size - 4000))
                        stderr_tail = stream.read().decode("utf-8", errors="replace")
                meta.update(status=status, ended_at=time.time(), result=output.get("result"),
                            cost_usd=output.get("total_cost_usd"), num_turns=output.get("num_turns"),
                            error=error, stderr_tail=stderr_tail)
                store.save(meta)
                store.finish_approvals(run_id, "cancelled" if status == "cancelled" else "interrupted")
                store.release(meta)
            print(summary(meta), flush=True)
    return 0 if status == "completed" else 1


def cancel(store, run_id):
    with store.transaction():
        meta = store.reconcile(store.meta(run_id))
        if meta["status"] in TERMINAL or meta.get("cancel_requested"):
            raise FerryError("RUN_NOT_ACTIVE", "Run is no longer active")
        meta["cancel_requested"] = True
        store.save(meta)
        store.finish_approvals(run_id, "cancelled")
        worker_pid = meta.get("worker_pid")
        if worker_pid:
            os.kill(worker_pid, signal.SIGTERM)
        else:
            kill_group(meta["pgid"], signal.SIGTERM)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and store.alive(meta):
        time.sleep(0.05)
    with store.transaction():
        current = store.meta(run_id)
        if current["status"] not in TERMINAL:
            # Worker did not complete cleanup (e.g. child ignores TERM).
            child_pid = current.get("agent_pid", current.get("claude_pid"))
            if store.child_alive(current):
                kill_group(child_pid, signal.SIGKILL)
            if store.alive(current):
                kill_group(current["pgid"], signal.SIGKILL)
            current.update(status="cancelled", ended_at=time.time())
            store.save(current)
            store.release(current)
            fallback = bool(current["notify"])
        else:
            fallback = False
    if fallback:
        send(store, current, f"ferry:{run_id}", "failed", summary(current), store.run_dir(run_id) / "notify.log", 130)
    return {"run_id": run_id, "status": "cancelled"}
