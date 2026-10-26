"""Configuration, private state files, and short state transactions."""
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import time


TERMINAL = {"completed", "failed", "cancelled", "interrupted"}
AGENTS = ("claude", "codex", "grok", "pi", "kimi")
DEFAULTS = {
    "workspace_root": "~/www", "approval_timeout_seconds": 21600,
    "retention_days": 7, "result_max_chars": 4000, "claude_bin": "claude",
    "notify_run_bin": "~/.local/bin/notify-run", "caffeinate_bin": "/usr/bin/caffeinate",
    "poll_interval_seconds": 2,
    "codex_bin": "codex", "grok_bin": "grok", "pi_bin": "pi", "kimi_bin": "kimi",
    "agent_start_timeout_seconds": 60,
}
ASK_RULES = [
    "Bash(git push*)", "Bash(sudo *)", "Bash(npm install -g *)", "Bash(npm i -g *)",
    "Bash(pnpm add -g *)", "Bash(yarn global add *)", "Bash(brew install *)",
    "Bash(pip install --user *)", "Bash(pip3 install --user *)", "Bash(pipx install *)",
    "Bash(uv tool install *)", "Bash(cargo install *)", "Bash(go install *)",
    "Bash(git reset --hard*)", "Bash(git clean *)",
]


class FerryError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def read_json(path):
    with open(path, encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path, value, exclusive=False):
    """Publish a complete file; exclusive publication never replaces a decision."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive:
            # O_EXCL alone exposes an empty/partial JSON file to other processes.
            os.link(name, path)
        else:
            os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def one_line(value):
    return " ".join(str(value).split())


def executable(value):
    return shutil.which(os.path.expanduser(value))


def process_matches(pid, *tokens):
    if not isinstance(pid, int) or pid <= 1:
        return False
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat=", "-o", "command="],
        capture_output=True, text=True, timeout=3,
    )
    parts = result.stdout.strip().split(maxsplit=1)
    if result.returncode or len(parts) != 2 or parts[0].startswith("Z"):
        return False
    try:
        argv = shlex.split(parts[1])
    except ValueError:
        return False
    return any(argv[i:i + len(tokens)] == list(tokens) for i in range(len(argv)))


def process_birth(pid):
    if not isinstance(pid, int) or pid <= 1:
        return None
    result = subprocess.run(["ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="],
                            capture_output=True, text=True, timeout=3)
    parts = result.stdout.strip().split(maxsplit=1)
    return parts[1] if result.returncode == 0 and len(parts) == 2 and not parts[0].startswith("Z") else None


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS may return EPERM, rather than ESRCH, for an already empty group.
        groups = subprocess.run(["ps", "-axo", "pgid=,stat="], capture_output=True, text=True, timeout=3)
        if groups.returncode or any(parts[0] == str(pgid) and not parts[1].startswith("Z")
                                    for line in groups.stdout.splitlines() if len(parts := line.split()) == 2):
            raise


class Store:
    def __init__(self):
        home = Path.home()
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        state_home = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
        self.config_dir = config_home / "agent-ferry"
        self.root = state_home / "agent-ferry"
        self.relay_file = config_home / "webhook-relay/url.env"
        self.config = DEFAULTS.copy()
        config_path = self.config_dir / "config.json"
        if config_path.exists():
            data = read_json(config_path)
            if not isinstance(data, dict) or data.keys() - DEFAULTS.keys():
                raise FerryError("INVALID_CONFIG", "config.json contains unknown fields or is not an object")
            self.config.update(data)
        for key, value in self.config.items():
            if isinstance(DEFAULTS[key], str):
                valid = isinstance(value, str) and bool(value.strip())
            else:
                valid = (type(value) in (int, float) and math.isfinite(value) and value > 0)
                if key == "result_max_chars":
                    valid = valid and type(value) is int
            if not valid:
                raise FerryError("INVALID_CONFIG", f"Invalid config field: {key}")
        self.entry = Path(__file__).resolve().parent.parent / "bin/ferry"
        self.runs = self.root / "runs"
        self.approvals = self.root / "approvals"
        self.sessions = self.root / "sessions"

    def ensure(self):
        for path in (self.root, self.runs, self.approvals, self.sessions):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.chmod(0o700)

    @contextlib.contextmanager
    def transaction(self):
        self.ensure()
        fd = os.open(self.root / ".mutation.lock", os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd, "r+") as stream:
            # debt: metadata writes serialize globally; use per-session locks if contention grows.
            # Never hold this lock during Claude execution or approval waits.
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def run_dir(self, run_id):
        if not re.fullmatch(r"r_[0-9]{8}-[0-9]{6}_[0-9a-f]{12}", run_id):
            raise FerryError("NOT_FOUND", "Unknown run id")
        return self.runs / run_id

    def meta(self, run_id):
        try:
            return read_json(self.run_dir(run_id) / "meta.json")
        except FileNotFoundError:
            raise FerryError("NOT_FOUND", "Run not found") from None

    def save(self, meta):
        write_json(self.run_dir(meta["run_id"]) / "meta.json", meta)

    def request_path(self, approval_id):
        if not re.fullmatch(r"a_[0-9a-f]{32}", approval_id):
            raise FerryError("NOT_FOUND", "Unknown approval id")
        return self.approvals / f"{approval_id}.json"

    def decision_path(self, approval_id):
        return self.request_path(approval_id).with_suffix(".decision.json")

    def requests(self, run_id=None):
        for path in self.approvals.glob("a_*.json"):
            if path.name.endswith(".decision.json"):
                continue
            request = read_json(path)
            if run_id is None or request["run_id"] == run_id:
                yield request

    def decide(self, request, decision, note=""):
        try:
            write_json(self.decision_path(request["approval_id"]), {
                "decision": decision, "note": note, "answered_at": time.time(),
            }, exclusive=True)
            return True
        except FileExistsError:
            return False

    def pending(self, run_id=None):
        return [{k: v for k, v in r.items() if k != "native_request"} for r in self.requests(run_id)
                if not self.decision_path(r["approval_id"]).exists()
                and r["expires_at"] > time.time()
                and self.request_alive(r)]

    def request_alive(self, request):
        command = request.get("requester", "hook-permission")
        if command == "_exec":
            return process_matches(request["hook_pid"], "_exec", request["run_id"])
        return command in ("hook-permission", "hook-tool") and process_matches(request["hook_pid"], command)

    def finish_approvals(self, run_id, decision):
        for request in self.requests(run_id):
            self.decide(request, decision)

    def release(self, meta):
        if not meta.get("session_id"):
            return
        lock = self.session_lock(meta.get("agent", "claude"), meta["session_id"])
        if lock.exists() and lock.read_text() == meta["run_id"]:
            lock.unlink()

    def session_lock(self, agent, session_id):
        if agent == "claude":
            return self.sessions / f"{session_id}.lock"
        return self.sessions / f'{agent}_{hashlib.sha256(session_id.encode()).hexdigest()}.lock'

    def bind_session(self, run_id, session_id):
        # Called by a protocol worker after the native tool allocates its ID.
        if not isinstance(session_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", session_id):
            raise FerryError("PROTOCOL_ERROR", "Agent returned an invalid session id")
        with self.transaction():
            meta = self.meta(run_id)
            if meta["status"] in TERMINAL or meta.get("cancel_requested"):
                raise FerryError("RUN_NOT_ACTIVE", "Run was cancelled during agent startup")
            if meta.get("session_id") and meta["session_id"] != session_id:
                raise FerryError("PROTOCOL_ERROR", "Agent resumed a different session")
            lock = self.session_lock(meta.get("agent", "claude"), session_id)
            if lock.exists() and lock.read_text() != run_id:
                previous = self.reconcile(self.meta(lock.read_text()))
                if previous["status"] not in TERMINAL:
                    raise FerryError("SESSION_BUSY", "Native session already has an active run")
                lock.unlink(missing_ok=True)
            if not lock.exists():
                fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as stream:
                    stream.write(run_id)
            meta["session_id"] = session_id
            self.save(meta)
        return session_id

    def child_alive(self, meta):
        if meta.get("agent_birth"):
            return process_birth(meta.get("agent_pid")) == meta["agent_birth"]
        pid = meta.get("claude_pid")
        sid = meta.get("session_id")
        return bool(sid and (process_matches(pid, "--session-id", sid) or process_matches(pid, "--resume", sid)))

    def alive(self, meta):
        if meta.get("worker_pid"):
            return process_matches(meta["worker_pid"], "_exec", meta["run_id"])
        return (process_matches(meta.get("launcher_pid"), "_exec", meta["run_id"])
                or process_matches(meta.get("launcher_pid"), "--task", f'ferry:{meta["run_id"]}'))

    def reconcile(self, meta):
        if meta["status"] not in TERMINAL and not self.alive(meta):
            # A killed worker must not leave Claude editing the same session after lock recovery.
            child_pid = meta.get("agent_pid", meta.get("claude_pid"))
            if self.child_alive(meta):
                signal_group(child_pid, signal.SIGKILL)
            meta.update(status="interrupted", ended_at=time.time())
            self.save(meta)
            self.finish_approvals(meta["run_id"], "interrupted")
            self.release(meta)
        return meta

    def resume_cmd(self, meta):
        if not meta.get("session_id"):
            return None
        agent = meta.get("agent", "claude")
        option = {"claude": "--resume", "codex": "resume", "grok": "--resume", "pi": "--session", "kimi": "--session"}[agent]
        return f'cd {shlex.quote(meta["cwd"])} && {agent} {option} {shlex.quote(meta["session_id"])}'

    def settings(self):
        return {
            "permissions": {"ask": ASK_RULES},
            "sandbox": {"enabled": True, "autoAllowBashIfSandboxed": True,
                        "network": {"allowedDomains": ["*"]}},
            "hooks": {"PermissionRequest": [{"matcher": "*", "hooks": [{
                "type": "command", "command": str(self.entry), "args": ["hook-permission"],
                "timeout": self.config["approval_timeout_seconds"] + 60, "onFailure": "block",
            }]}]},
        }

    def render(self):
        self.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_json(self.config_dir / "claude-settings.json", self.settings())

    def cleanup(self):
        cutoff = time.time() - self.config["retention_days"] * 86400
        for path in self.runs.glob("*/meta.json"):
            meta = self.reconcile(read_json(path))
            if meta["status"] in TERMINAL and meta.get("ended_at", time.time()) < cutoff:
                for request in self.requests(meta["run_id"]):
                    self.decision_path(request["approval_id"]).unlink(missing_ok=True)
                    self.request_path(request["approval_id"]).unlink()
                self.release(meta)
                shutil.rmtree(path.parent)
