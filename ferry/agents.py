"""Small differences between native command lines; no model/provider routing."""
from pathlib import Path
import datetime
import json
import os
import re
import subprocess
import shutil
import uuid

from .core import AGENTS, FerryError, executable

MIN_VERSIONS = {"codex": (0, 164, 0), "grok": (1, 0, 70), "pi": (1, 4, 0), "kimi": (2, 1, 1)}


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{toml_value(k)} = {toml_value(v)}" for k, v in value.items()) + " }"
    raise FerryError("INVALID_CONFIG", "Unsupported value in Grok configuration")


def environment(store, meta):
    if meta.get("agent") != "grok":
        return {}
    try:
        import tomllib
    except ImportError:
        raise FerryError("UNSUPPORTED_RUNTIME", "The Grok adapter requires Python 3.11+ for TOML policy isolation") from None
    source = Path(os.environ.get("GROK_HOME", str(Path.home() / ".grok"))).expanduser().resolve()
    if (source / "requirements.toml").exists():
        # Do not replace an owner's existing policy with a weaker or partially merged one.
        raise FerryError("UNSAFE_AGENT", "Grok already has requirements.toml; policy composition needs review")
    # First-run sessions must outlive the temporary policy profile, too.
    (source / "sessions").mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = store.run_dir(meta["run_id"]) / "grok-home"
    profile.mkdir(mode=0o700)
    if source.exists():
        # Keep native auth/history in their normal locations; isolate only policy/config.
        for path in source.iterdir():
            if path.name != "config.toml":
                (profile / path.name).symlink_to(path, target_is_directory=path.is_dir())
    try:
        original = tomllib.loads((source / "config.toml").read_text()) if (source / "config.toml").exists() else {}
    except (ValueError, OSError):
        raise FerryError("INVALID_CONFIG", "Cannot parse Grok user configuration") from None
    original.setdefault("ui", {}).update(permission_mode="ask", yolo=False, remember_tool_approvals=False)
    original["ui"].pop("approval_mode", None)
    original.setdefault("features", {}).update(remember_mode=False, support_permission=True)
    permissions = original.setdefault("permission", {})
    # The legacy allow list is independent of permission_mode and overrides prompts.
    permissions.pop("allow", None)
    rules = permissions.get("rules", [])
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise FerryError("INVALID_CONFIG", "Unsupported Grok permission rules")
    permissions["rules"] = [rule for rule in rules if rule.get("action") != "allow"] + [
        {"action": "ask", "tool": "bash", "pattern": "*"},
        {"action": "ask", "tool": "edit", "pattern": "*"},
    ]
    fd = os.open(profile / "config.toml", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(f"{toml_value(k)} = {toml_value(v)}" for k, v in original.items()) + "\n")
    policy = profile / "requirements.toml"
    fd = os.open(policy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write('[ui]\npermission_mode = "ask"\ndisable_bypass_permissions_mode = true\nyolo = false\nremember_tool_approvals = false\n'
                     '[features]\nsupport_permission = true\n'
                     '[permission]\nrules = [{ action = "ask", tool = "bash", pattern = "*" }, { action = "ask", tool = "edit", pattern = "*" }]\n')
    overlay = {"GROK_HOME": str(profile)}
    inspection = subprocess.run([executable(store.config["grok_bin"]), "inspect", "--json"],
                                env={**os.environ, **overlay}, cwd=meta["cwd"], capture_output=True, text=True, timeout=15)
    try:
        permissions = json.loads(inspection.stdout)["permissions"]
        config_path = str(profile / "config.toml")
        if (inspection.returncode or not any(config_path in s for s in permissions.get("sources", []))
                or any(config_path in str(s) for s in permissions.get("skipped", []))):
            raise ValueError("Guard rules were not loaded")
    except (ValueError, KeyError, TypeError):
        raise FerryError("UNSAFE_AGENT", "Grok did not load the required approval rules") from None
    return overlay


def cleanup_environment(store, meta):
    if meta.get("agent") == "grok":
        profile = store.run_dir(meta["run_id"]) / "grok-home"
        if profile.is_symlink():
            profile.unlink()
        elif profile.exists():
            # rmtree removes our links, never the native auth/history targets.
            shutil.rmtree(profile)


def supported_version(agent, text):
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", text)
    return agent not in MIN_VERSIONS or bool(match and tuple(map(int, match.groups())) >= MIN_VERSIONS[agent])


def check_version(store, agent):
    if agent == "claude":
        return
    result = subprocess.run([executable(store.config[f"{agent}_bin"]), "--version"],
                            capture_output=True, text=True, timeout=10)
    if result.returncode or not supported_version(agent, result.stdout):
        raise FerryError("UNSUPPORTED_AGENT", f"Unsupported {agent} version; run ferry doctor --agent {agent}")


def session_id(agent, value):
    if agent not in AGENTS:
        raise FerryError("INVALID_AGENT", "Unknown agent")
    if value is not None:
        if agent in ("claude", "pi"):
            try:
                return str(uuid.UUID(value))
            except ValueError:
                raise FerryError("INVALID_SESSION_ID", "session must be a UUID") from None
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", value):
            raise FerryError("INVALID_SESSION_ID", "Invalid native session id")
        return value
    return str(uuid.uuid4()) if agent in ("claude", "pi") else None


def argv(store, meta):
    agent = meta.get("agent", "claude")
    binary = executable(store.config[f"{agent}_bin"])
    if not binary:
        raise FerryError("AGENT_NOT_FOUND", f"{agent} executable not found")
    if agent == "claude":
        result = [binary, "-p", "--output-format", "json", "--permission-mode", "acceptEdits",
                  "--settings", str(store.config_dir / "claude-settings.json"), "--disallowedTools", "AskUserQuestion",
                  "--session-id" if meta["new_session"] else "--resume", meta["session_id"]]
    elif agent == "codex":
        result = [binary, "app-server", "--listen", "stdio://"]
    elif agent == "grok":
        result = [binary, "--permission-mode", "default", "agent", "--no-leader", "stdio"]
    elif agent == "kimi":
        result = [binary, "acp"]
    else:
        result = [binary, "--mode", "rpc", "--session-id" if meta["new_session"] else "--session", meta["session_id"], "--no-extensions",
                  "--extension", str(Path(__file__).with_name("pi-guard.mjs"))]
    if meta.get("model") is not None and agent in ("claude", "pi"):
        result += ["--model", meta["model"]]
    return result
