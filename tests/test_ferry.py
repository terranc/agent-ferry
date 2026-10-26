import concurrent.futures
import contextlib
import http.server
import io
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

from ferry.cli import doctor, main
from ferry.core import DEFAULTS, Store, process_matches, read_json, write_json
from ferry.hook import summarize
from ferry.notify import relay_config, send


REPO = Path(__file__).resolve().parents[1]
ENTRY = REPO / "bin/ferry"


class FixtureCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ferry-tests-")
        self.home = Path(self.temp.name).resolve()
        self.config_home = self.home / "config"
        self.state = self.home / "state/agent-ferry"
        self.workspace = self.home / "www"
        self.cwd = self.workspace / "app"
        self.cwd.mkdir(parents=True)
        self.config_dir = self.config_home / "agent-ferry"
        self.config_dir.mkdir(parents=True)
        self.config = {**DEFAULTS, "workspace_root": str(self.workspace),
                       "claude_bin": str(REPO / "tests/fake_claude.py"),
                       "notify_run_bin": str(REPO / "tests/fake_notify.py"),
                       "caffeinate_bin": str(REPO / "tests/fake_caffeinate.py"),
                       "approval_timeout_seconds": 3, "poll_interval_seconds": 0.05}
        self.env = {**os.environ, "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.config_home),
                    "XDG_STATE_HOME": str(self.home / "state"), "PYTHONPATH": str(REPO),
                    "PYTHONDONTWRITEBYTECODE": "1"}
        for key in ("WEBHOOK_RELAY_URL", "WEBHOOK_RELAY_KEY", "FERRY_RUN_ID"):
            self.env.pop(key, None)
        self.save_config()

    def tearDown(self):
        # Always stop owned test descendants, including intentionally killed workers.
        for path in self.state.glob("runs/*/meta.json"):
            meta = read_json(path)
            for key in ("agent_pid", "claude_pid", "pgid"):
                pid = meta.get(key)
                if pid:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.temp.cleanup()

    def save_config(self, **changes):
        self.config.update(changes)
        write_json(self.config_dir / "config.json", self.config)

    def call(self, *args, prompt=None, code=0, entry=ENTRY):
        proc = subprocess.run([str(entry), *args], input=prompt, text=True, capture_output=True, env=self.env, timeout=15)
        self.assertEqual(proc.returncode, code, (args, proc.stdout, proc.stderr))
        result = json.loads(proc.stdout)
        self.assertEqual(result["ok"], code == 0, result)
        return result

    def run_task(self, prompt="hello", session=None, cwd=None, code=0, model=None):
        args = ["run", "--owner", "bot-id", "--cwd", str(cwd or self.cwd)]
        if session is not None:
            args += ["--session", session]
        if model is not None:
            args += ["--model", model]
        return self.call(*args, prompt=prompt, code=code)

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.03)
        self.fail("Timed out waiting for test condition")

    def finished(self, run):
        def query():
            result = self.call("status", run["run_id"], "--full")
            return result if result["status"] in ("completed", "failed", "cancelled", "interrupted") else None
        return self.wait_for(query)

    def directory(self, run):
        return self.state / "runs" / run["run_id"]

    def invocation(self, run):
        path = self.directory(run) / "invocation.json"
        self.wait_for(path.exists)
        return read_json(path)

    def approval(self, run, count=1):
        def query():
            status = self.call("status", run["run_id"])
            pending = status["pending_approvals"]
            return pending[0] if pending and len(list(self.state.glob("approvals/a_*.json"))) >= count else None
        return self.wait_for(query)

    def ask(self, tool="Write", data=None, count=1):
        target = self.home / f"outside-{uuid.uuid4().hex}"
        requests = [{"tool": tool, "input": {"file_path": str(target)} if data is None else data,
                     "target": str(target)} for _ in range(count)]
        return self.run_task("@@ask:" + json.dumps(requests)), target

    def relay(self, url="http://127.0.0.1:1", key="test-key"):
        path = self.config_home / "webhook-relay/url.env"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"export WEBHOOK_RELAY_URL={shlex.quote(url)}\nWEBHOOK_RELAY_KEY={shlex.quote(key)}\n")
        return path

    @contextlib.contextmanager
    def local_http(self, codes=(200,)):
        records = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                records.append((dict(self.headers), data))
                self.send_response(codes[min(len(records) - 1, len(codes) - 1)])
                self.end_headers()

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", records
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

class FerryTest(FixtureCase):
    def test_cwd_rejections_do_not_start_claude(self):
        outside = self.home / "outside"
        outside.mkdir()
        link = self.workspace / "escape"
        link.symlink_to(outside)
        file = self.workspace / "file"
        file.touch()
        for cwd in (self.workspace, self.home, Path("/tmp"), self.workspace / "absent", file, link,
                    self.cwd / "../.."):
            with self.subTest(cwd=cwd):
                self.assertEqual(self.run_task(cwd=cwd, code=2)["error"]["code"], "INVALID_CWD")
        self.assertFalse(list(self.state.glob("runs/*/invocation.json")))

    def test_cwd_realpath_allows_inward_symlink_and_root_symlink(self):
        alias = self.home / "inward"
        alias.symlink_to(self.cwd)
        root_alias = self.home / "root-alias"
        root_alias.symlink_to(self.workspace)
        self.save_config(workspace_root=str(root_alias))
        run = self.run_task(cwd=alias)
        self.assertEqual(self.finished(run)["status"], "completed")
        self.assertEqual(self.invocation(run)["cwd"], str(self.cwd))

    def test_prompt_round_trip_and_large_prompt(self):
        prompt = "- leading\n'quotes' \"double\" $HOME `echo no` 中文😀\r\n" + "x" * 102400
        run = self.run_task(prompt)
        self.assertEqual(self.finished(run)["result"], prompt)
        self.assertEqual(self.invocation(run)["stdin"], prompt)

    def test_prompt_file_and_empty_prompt(self):
        file = self.home / "prompt.txt"
        file.write_text("multi\nline '$`中文")
        run = self.call("run", "--owner", "bot", "--cwd", str(self.cwd), "--prompt-file", str(file))
        self.assertEqual(self.finished(run)["result"], file.read_text())
        self.assertEqual(self.run_task(" \n", code=2)["error"]["code"], "EMPTY_PROMPT")

    def test_tty_requires_prompt_file(self):
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch("sys.stdin") as stdin, contextlib.redirect_stdout(io.StringIO()) as stdout:
            stdin.isatty.return_value = True
            self.assertEqual(main(["run", "--owner", "bot", "--cwd", str(self.cwd)]), 2)
            self.assertEqual(json.loads(stdout.getvalue())["error"]["code"], "EMPTY_PROMPT")

    def test_new_and_resumed_sessions_and_argv(self):
        run = self.run_task()
        uuid.UUID(run["session_id"])
        self.finished(run)
        first = self.invocation(run)
        self.assertIn("--session-id", first["argv"])
        self.assertEqual(first["run_id"], run["run_id"])
        expected = ["-p", "--output-format", "json", "--permission-mode", "acceptEdits", "--settings",
                    str(self.config_dir / "claude-settings.json"), "--disallowedTools", "AskUserQuestion"]
        self.assertEqual(first["argv"][:len(expected)], expected)
        self.assertNotIn("--dangerously-skip-permissions", first["argv"])
        self.assertNotIn("bypassPermissions", first["argv"])
        self.assertNotIn("--model", first["argv"])
        resumed = self.run_task(session=run["session_id"])
        self.finished(resumed)
        self.assertEqual(self.invocation(resumed)["argv"][-2:], ["--resume", run["session_id"]])
        self.assertFalse(resumed["new_session"])
        self.assertEqual(self.run_task(session="not-a-uuid", code=2)["error"]["code"], "INVALID_SESSION_ID")
        self.assertEqual(self.run_task(session="", code=2)["error"]["code"], "INVALID_SESSION_ID")

    def test_model_forwarded_for_new_and_resumed_runs(self):
        first = self.run_task(model="sonnet")
        self.assertEqual(self.finished(first)["status"], "completed")
        for model in ("opus", "provider/custom-model-v1"):
            with self.subTest(model=model):
                run = self.run_task(session=first["session_id"], model=model)
                self.assertEqual(self.finished(run)["status"], "completed")
                argv = self.invocation(run)["argv"]
                self.assertEqual(argv[argv.index("--model") + 1], model)
                self.assertIn("--resume", argv)
                self.assertEqual(read_json(self.directory(run) / "meta.json")["model"], model)
        argv = self.invocation(first)["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_empty_model_rejected_before_launch(self):
        for model in ("", " \t"):
            with self.subTest(model=model):
                result = self.run_task(model=model, code=2)
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse(list(self.state.glob("runs/*/invocation.json")))

    def test_session_busy_and_concurrent_session_acquisition(self):
        session = str(uuid.uuid4())
        def start():
            return subprocess.run([str(ENTRY), "run", "--owner", "b", "--cwd", str(self.cwd), "--session", session],
                                  input="@@sleep:5", text=True, capture_output=True, env=self.env)
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            results = list(executor.map(lambda _: start(), range(2)))
        self.assertEqual(sorted(p.returncode for p in results), [0, 2])
        failure = next(json.loads(p.stdout) for p in results if p.returncode == 2)
        self.assertEqual(failure["error"]["code"], "SESSION_BUSY")
        self.assertEqual(self.run_task(session=session, code=2)["error"]["code"], "SESSION_BUSY")

    def test_stale_lock_and_lock_ownership(self):
        session = str(uuid.uuid4())
        with mock.patch.dict(os.environ, self.env, clear=True):
            store = Store()
            store.ensure()
            lock = store.sessions / f"{session}.lock"
            lock.write_text("r_20261025-000000_000000000000")
        run = self.run_task(session=session)
        self.finished(run)
        with mock.patch.dict(os.environ, self.env, clear=True):
            lock.write_text("another-run")
            store.release(store.meta(run["run_id"]))
            self.assertEqual(lock.read_text(), "another-run")

    def test_background_return_and_state_transitions(self):
        started = time.monotonic()
        run = self.run_task("@@sleep:0.8")
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(run["status"], "starting")
        invocation = self.invocation(run)
        self.assertTrue(process_matches(invocation["pid"], "--session-id", run["session_id"]))
        self.assertEqual(self.call("status", run["run_id"])["status"], "running")
        self.assertEqual(self.finished(run)["status"], "completed")

    def test_failures_and_stderr_diagnostics(self):
        for prompt in ("@@fail", "@@error-result", "@@bad-json", "@@array-json"):
            with self.subTest(prompt=prompt):
                run = self.run_task(prompt)
                result = self.finished(run)
                self.assertEqual(result["status"], "failed", result)
                self.assertTrue(result["error"])
                if prompt != "@@array-json":
                    self.assertTrue(result["stderr_tail"])

    def test_truncation_full_status_and_single_line_summary(self):
        self.save_config(result_max_chars=10)
        run = self.run_task("many\nlines\n" * 100)
        full = self.finished(run)
        result = self.call("status", run["run_id"])
        self.assertEqual(len(result["result"]), 10)
        self.assertTrue(result["result_truncated"])
        self.assertFalse(full["result_truncated"])
        self.assertGreater(len(full["result"]), 10)
        log = (self.directory(run) / "notify.log").read_text()
        self.assertEqual(len(log.splitlines()), 1)
        self.assertLessEqual(len(log.strip()), 300)
        self.assertIn("completed", log)
        self.assertEqual(full["cost_usd"], 0.01)
        self.assertEqual(full["num_turns"], 1)

    def test_notification_wrapper_and_missing_config_fallback(self):
        self.relay()
        run = self.run_task()
        self.assertEqual(run["notify"], "wake-on-done")
        self.finished(run)
        path = self.directory(run) / "notification.json"
        self.wait_for(path.exists)
        result = read_json(path)
        self.assertEqual(result["task"], "ferry:" + run["run_id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertIn("completed", result["output_tail"])
        argv = read_json(self.directory(run) / "notify-argv.json")
        self.assertEqual(argv[-3:], [str(ENTRY), "_exec", run["run_id"]])
        self.relay().unlink()
        run2 = self.run_task()
        self.assertEqual(run2["notify"], "none")
        self.assertIn("warning", run2)
        self.assertEqual(self.finished(run2)["status"], "completed")
        self.assertFalse((self.directory(run2) / "notify-argv.json").exists())
        self.relay()
        self.save_config(notify_run_bin="/missing-notify-run")
        run3 = self.run_task()
        self.assertEqual(run3["notify"], "none")
        self.assertIn("warning", run3)
        self.assertEqual(self.finished(run3)["status"], "completed")

    def test_approvals_reconciles_dead_parent(self):
        run, _ = self.ask()
        request = self.approval(run)
        meta = read_json(self.directory(run) / "meta.json")
        os.kill(meta["worker_pid"], signal.SIGKILL)
        self.wait_for(lambda: not process_matches(meta["worker_pid"], "_exec", run["run_id"]))
        self.assertEqual(self.call("approvals")["approvals"], [])
        decision = read_json(self.state / "approvals" / f'{request["approval_id"]}.decision.json')
        self.assertEqual(decision["decision"], "interrupted")

    def test_failed_notification_exit_code(self):
        self.relay()
        run = self.run_task("@@fail")
        self.finished(run)
        path = self.directory(run) / "notification.json"
        self.wait_for(path.exists)
        self.assertEqual(read_json(path)["status"], "failed")
        self.assertNotEqual(read_json(path)["exit_code"], 0)

    def test_retention_cleans_terminal_runs_but_keeps_active_runs(self):
        old = self.run_task()
        self.finished(old)
        path = self.directory(old) / "meta.json"
        meta = read_json(path)
        meta["ended_at"] = time.time() - 8 * 86400
        write_json(path, meta)
        active = self.run_task("@@sleep:5")
        new = self.run_task()
        self.finished(new)
        self.assertFalse(path.exists())
        self.assertTrue(self.directory(active).exists())

    def test_settings_contract(self):
        run = self.run_task()
        self.finished(run)
        data = read_json(self.config_dir / "claude-settings.json")
        self.assertEqual(data["permissions"]["ask"], [
            "Bash(git push*)", "Bash(sudo *)", "Bash(npm install -g *)", "Bash(npm i -g *)",
            "Bash(pnpm add -g *)", "Bash(yarn global add *)", "Bash(brew install *)",
            "Bash(pip install --user *)", "Bash(pip3 install --user *)", "Bash(pipx install *)",
            "Bash(uv tool install *)", "Bash(cargo install *)", "Bash(go install *)",
            "Bash(git reset --hard*)", "Bash(git clean *)"])
        self.assertTrue(data["sandbox"]["enabled"])
        self.assertTrue(data["sandbox"]["autoAllowBashIfSandboxed"])
        hook = data["hooks"]["PermissionRequest"][0]["hooks"][0]
        self.assertTrue(Path(hook["command"]).is_absolute())
        self.assertEqual(hook["args"], ["hook-permission"])
        self.assertEqual(hook["timeout"], self.config["approval_timeout_seconds"] + 60)
        self.assertEqual(hook["onFailure"], "block")

    def test_approval_allow_deny_and_duplicate(self):
        for answer in ("allow", "deny"):
            with self.subTest(answer=answer):
                run, target = self.ask()
                request = self.approval(run)
                self.assertFalse(target.exists())
                self.assertEqual(self.call("status", run["run_id"])["status"], "waiting_approval")
                self.assertEqual(len(self.call("approvals", "--run", run["run_id"])["approvals"]), 1)
                self.call("approve", request["approval_id"], answer, "--note", "user response")
                result = self.finished(run)
                self.assertEqual(target.exists(), answer == "allow")
                if answer == "deny":
                    self.assertIn("user response", result["result"])
                duplicate = self.call("approve", request["approval_id"], answer, code=2)
                self.assertEqual(duplicate["error"]["code"], "ALREADY_ANSWERED")
                hook = read_json(self.directory(run) / "hook-0.json")["hookSpecificOutput"]["decision"]
                self.assertEqual(hook["behavior"], answer)
                self.assertNotIn("updatedPermissions", hook)

    def test_approval_timeout_and_late_answer(self):
        self.save_config(approval_timeout_seconds=0.3)
        run, target = self.ask()
        request = self.approval(run)
        result = self.finished(run)
        self.assertFalse(target.exists())
        self.assertIn("expired", result["result"])
        self.assertEqual(self.call("approve", request["approval_id"], "allow", code=2)["error"]["code"], "APPROVAL_EXPIRED")

    def test_answer_expiry_race_publishes_one_complete_decision(self):
        self.save_config(approval_timeout_seconds=0.3)
        run, target = self.ask()
        request = self.approval(run)
        time.sleep(max(0, request["expires_at"] - time.time() - 0.03))
        result = subprocess.run([str(ENTRY), "approve", request["approval_id"], "allow"], env=self.env, capture_output=True, text=True)
        self.finished(run)
        path = self.state / "approvals" / f'{request["approval_id"]}.decision.json'
        decision = read_json(path)
        self.assertIn(decision["decision"], ("allowed", "expired"))
        self.assertEqual(target.exists(), decision["decision"] == "allowed")
        self.assertIn(result.returncode, (0, 2))
        self.assertEqual(len(list(self.state.glob("approvals/*.decision.json"))), 1)

    def test_two_competing_answers_have_one_winner(self):
        run, target = self.ask()
        request = self.approval(run)
        def answer(value):
            return subprocess.run([str(ENTRY), "approve", request["approval_id"], value], env=self.env, capture_output=True, text=True)
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            results = list(executor.map(answer, ("allow", "deny")))
        self.assertEqual(sorted(p.returncode for p in results), [0, 2])
        self.finished(run)
        winner = next(json.loads(p.stdout)["decision"] for p in results if p.returncode == 0)
        self.assertEqual(target.exists(), winner == "allow")

    def test_missing_environment_malformed_hook_and_exception_fail_closed(self):
        for payload in ("{}", "not JSON", '{"tool_name":"Write","tool_input": []}'):
            result = subprocess.run([str(ENTRY), "hook-permission"], env=self.env, input=payload,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")
        run, target = self.ask(data=[])
        self.assertIn("denied", self.finished(run)["result"])
        self.assertFalse(target.exists())

    def test_hook_gone_rejects_answer(self):
        run, _ = self.ask()
        request = self.approval(run)
        os.kill(request["hook_pid"], signal.SIGKILL)
        self.assertEqual(self.call("approve", request["approval_id"], "allow", code=2)["error"]["code"], "RUN_NOT_ACTIVE")

    def test_two_sequential_approvals_are_independent(self):
        run, target = self.ask(count=2)
        first = self.approval(run)
        self.call("approve", first["approval_id"], "deny")
        second = self.approval(run, count=3)  # one request + one decision + the next request
        self.assertNotEqual(first["approval_id"], second["approval_id"])
        self.call("approve", second["approval_id"], "allow")
        self.finished(run)
        self.assertTrue(target.exists())

    def test_summary_classification_and_limits(self):
        for tool in ("Edit", "Write", "NotebookEdit", "Bash", "OtherTool"):
            data = {"file_path": "x\ny" * 2000, "notebook_path": "z", "command": "echo\nfoo" * 1000}
            item = summarize({"tool_name": tool, "tool_input": data})
            expected = "command" if tool == "Bash" else "other" if tool == "OtherTool" else "file_write"
            self.assertEqual(item["kind"], expected)
            self.assertLessEqual(len(item["detail"]), 2000)
            self.assertNotIn("\n", item["summary"])
        item = summarize({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "book.ipynb"}})
        self.assertEqual(item["detail"], "book.ipynb")

    def test_approval_notification_retries_and_auth_normalization(self):
        with self.local_http((500, 503, 200)) as (url, records):
            self.relay(url, "Authorization: Bearer test-key")
            run, _ = self.ask(tool="Bash", data={"command": "echo x > outside"})
            request = self.approval(run)
            self.wait_for(lambda: len(records) == 3)
            self.assertEqual(len(records), 3)
            headers, body = records[-1]
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertEqual(set(body), {"owner", "task", "status", "exit_code", "machine", "started_at", "ended_at", "log_path", "output_tail"})
            self.assertEqual(body["task"], "ferry-approval:" + request["approval_id"])
            self.assertEqual(body["status"], "waiting_approval")
            self.assertIsInstance(body["started_at"], str)
            self.assertIsInstance(body["ended_at"], str)
            self.assertIn(run["run_id"], body["output_tail"])
            self.call("approve", request["approval_id"], "deny")
            self.finished(run)

    def test_failed_notification_keeps_waiting_and_logs_no_secrets(self):
        with self.local_http((503,)) as (url, records):
            self.relay(url, "TOP-SECRET")
            run, _ = self.ask()
            request = self.approval(run)
            self.wait_for(lambda: len(records) == 3)
            self.assertEqual(self.call("status", run["run_id"])["status"], "waiting_approval")
            self.call("approve", request["approval_id"], "deny")
            self.finished(run)
            # Hook diagnostics are private to the fake; the permission response stays valid JSON.
            self.assertNotIn("TOP-SECRET", (self.directory(run) / "hook-0.json").read_text())

    def test_missing_relay_and_parser_never_executes_shell(self):
        path = self.relay(key="$(touch SHOULD_NOT_EXIST)")
        with mock.patch.dict(os.environ, self.env, clear=True):
            store = Store()
            self.assertEqual(relay_config(store)[1], "$(touch SHOULD_NOT_EXIST)")
            path.unlink()
            with contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertFalse(send(store, {"owner": "bot", "created_at": 0}, "task", "waiting_approval", "x", path))
                self.assertIn("missing", stderr.getvalue())
        self.assertFalse((self.cwd / "SHOULD_NOT_EXIST").exists())

    def test_upstream_notify_run_completion_to_local_http(self):
        with self.local_http() as (url, records):
            self.relay(url, "Authorization: Bearer test-key")
            self.save_config(notify_run_bin=str(REPO / "skills/wake-on-done/scripts/notify-run"))
            run = self.run_task()
            self.finished(run)
            self.wait_for(lambda: records)
            headers, body = records[0]
            self.assertEqual(headers["Authorization"], "Bearer test-key")
            self.assertEqual(body["task"], "ferry:" + run["run_id"])
            self.assertIn("completed", body["output_tail"])
            self.assertEqual(body["status"], "succeeded")

    def test_cancel_running_worker_and_notify(self):
        self.relay()
        run = self.run_task("@@sleep:20")
        invocation = self.invocation(run)
        self.call("cancel", run["run_id"])
        self.assertEqual(self.finished(run)["status"], "cancelled")
        self.wait_for(lambda: not process_matches(invocation["pid"], "--session-id", run["session_id"]))
        path = self.directory(run) / "notification.json"
        self.wait_for(path.exists)
        self.assertIn("cancelled", read_json(path)["output_tail"])
        self.assertEqual(self.call("cancel", run["run_id"], code=2)["error"]["code"], "RUN_NOT_ACTIVE")

    def test_cancel_invalidates_pending_approval(self):
        run, target = self.ask()
        request = self.approval(run)
        self.call("cancel", run["run_id"])
        self.assertEqual(self.finished(run)["status"], "cancelled")
        path = self.state / "approvals" / f'{request["approval_id"]}.decision.json'
        self.assertEqual(read_json(path)["decision"], "cancelled")
        self.assertFalse(target.exists())
        hook_result = self.directory(run) / "hook-0.json"
        self.assertEqual(read_json(hook_result)["hookSpecificOutput"]["decision"]["behavior"], "deny")
        self.assertEqual(self.call("approve", request["approval_id"], "allow", code=2)["error"]["code"], "RUN_NOT_ACTIVE")

    def test_cancel_kills_child_ignoring_sigterm(self):
        run = self.run_task("@@ignore-term")
        invocation = self.invocation(run)
        self.wait_for((self.directory(run) / "ignoring-term").exists)
        start = time.monotonic()
        self.call("cancel", run["run_id"])
        self.assertGreaterEqual(time.monotonic() - start, 4.9)
        self.assertEqual(self.finished(run)["status"], "cancelled")
        self.wait_for(lambda: not process_matches(invocation["pid"], "--session-id", run["session_id"]))

    def test_reconcile_killed_worker_and_reused_pid(self):
        run = self.run_task("@@sleep:20")
        self.invocation(run)
        meta = read_json(self.directory(run) / "meta.json")
        os.kill(meta["worker_pid"], signal.SIGKILL)
        self.wait_for(lambda: not process_matches(meta["worker_pid"], "_exec", run["run_id"]))
        self.assertEqual(self.call("status", run["run_id"])["status"], "interrupted")
        self.wait_for(lambda: not process_matches(meta["claude_pid"], "--session-id", run["session_id"]))
        resumed = self.run_task(session=run["session_id"])
        self.assertEqual(self.finished(resumed)["status"], "completed")
        path = self.directory(run) / "meta.json"
        meta.update(status="running", worker_pid=os.getpid())
        write_json(path, meta)
        self.assertEqual(self.call("status", run["run_id"])["status"], "interrupted")

    def test_caffeinate_arguments(self):
        run = self.run_task()
        self.finished(run)
        path = self.state / "caffeinate.json"
        self.wait_for(path.exists)
        self.assertEqual(read_json(path), ["-i", "-w", str(self.invocation(run)["pid"])])

    def test_session_listing_grouping_filter_sort_and_shell_quoting(self):
        first = self.run_task("first prompt")
        self.finished(first)
        second = self.run_task("second prompt", session=first["session_id"])
        self.finished(second)
        odd = self.workspace / "Bob's app $x"
        odd.mkdir()
        third = self.run_task("@@sleep:20", cwd=odd)
        self.invocation(third)
        data = self.call("sessions")["sessions"]
        self.assertEqual([s["session_id"] for s in data], [third["session_id"], first["session_id"]])
        self.assertTrue(data[0]["running"])
        self.assertEqual(shlex.split(data[0]["resume_cmd"]), ["cd", str(odd), "&&", "claude", "--resume", third["session_id"]])
        self.assertEqual(data[1]["first_prompt"], "first prompt")
        self.assertEqual(len(self.call("sessions", "--cwd", str(self.cwd))["sessions"]), 1)

    def test_doctor_checks_and_conflicting_settings(self):
        self.relay(key="TOP-SECRET")
        claude_dir = self.home / ".claude"
        claude_dir.mkdir()
        path = claude_dir / "settings.json"
        path.write_text(json.dumps({"hooks": {"PermissionRequest": [{}]},
                                    "permissions": {"allow": ["Bash(*)"], "defaultMode": "bypassPermissions"}}))
        result = self.call("doctor")
        checks = {c["name"]: c for c in result["checks"]}
        for name in ("claude", "python3", "wake-on-done", "workspace_root", "caffeinate"):
            self.assertEqual(checks[name]["status"], "pass")
        self.assertEqual(checks["user_settings"]["status"], "warn")
        self.assertNotIn("TOP-SECRET", json.dumps(result))
        path.unlink()
        self.assertEqual(next(c for c in self.call("doctor")["checks"] if c["name"] == "user_settings")["status"], "pass")
        self.save_config(claude_bin="/missing", notify_run_bin="/missing", workspace_root="/missing", caffeinate_bin="/missing")
        checks = {c["name"]: c for c in self.call("doctor")["checks"]}
        self.assertEqual(checks["claude"]["status"], "fail")
        self.assertEqual(checks["workspace_root"]["status"], "fail")
        self.assertEqual(checks["caffeinate"]["status"], "fail")
        self.assertEqual(checks["wake-on-done"]["status"], "warn")
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch("ferry.cli.sys.version_info", (3, 8)):
            checks = {c["name"]: c for c in doctor(Store())["checks"]}
            self.assertEqual(checks["python3"]["status"], "fail")

    def test_doctor_invalid_settings_and_failed_version(self):
        directory = self.home / ".claude"
        directory.mkdir()
        (directory / "settings.json").write_text("not json")
        self.assertEqual(next(c for c in self.call("doctor")["checks"] if c["name"] == "user_settings")["status"], "warn")
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch("ferry.cli.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 5)):
            result = doctor(Store())
            self.assertEqual(next(c for c in result["checks"] if c["name"] == "claude")["status"], "fail")

    def test_private_file_modes_and_identifier_validation(self):
        run = self.run_task()
        self.finished(run)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        for path in (self.directory(run) / "meta.json", self.directory(run) / "claude.json"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(self.call("status", "../../etc/passwd", code=2)["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.call("approve", "../../x", "allow", code=2)["error"]["code"], "NOT_FOUND")
        self.assertEqual(self.call("run", code=2)["error"]["code"], "INVALID_ARGUMENT")

    def test_invalid_config_denies_hook_and_returns_json(self):
        self.save_config(approval_timeout_seconds=-1)
        self.assertEqual(self.call("doctor", code=2)["error"]["code"], "INVALID_CONFIG")
        proc = subprocess.run([str(ENTRY), "hook-permission"], env=self.env, input="{}", text=True, capture_output=True)
        self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["decision"]["behavior"], "deny")

    def test_prompt_file_preserves_crlf(self):
        path = self.home / "crlf.txt"
        path.write_bytes(b"first\r\nsecond\r\n")
        run = self.call("run", "--owner", "bot", "--cwd", str(self.cwd), "--prompt-file", str(path))
        self.assertEqual(self.finished(run)["result"], "first\r\nsecond\r\n")

    def test_install_upgrade_uninstall_and_claude_settings_untouched(self):
        claude_dir = self.home / ".claude"
        claude_dir.mkdir()
        settings = claude_dir / "settings.json"
        settings.write_text('{"marker": "keep me"}')
        for _ in range(2):
            proc = subprocess.run([str(REPO / "install.sh")], env=self.env, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            json.loads(proc.stdout)
        installed = self.home / ".local/bin/ferry"
        self.assertTrue(os.access(installed, os.X_OK))
        destination = self.home / ".local/share/agent-ferry"
        self.assertFalse(installed.is_symlink())
        self.assertTrue((destination / "ferry/cli.py").is_file())
        hook = read_json(self.config_dir / "claude-settings.json")["hooks"]["PermissionRequest"][0]["hooks"][0]
        self.assertEqual(hook["command"], str(destination / "bin/ferry"))
        run = self.call("run", "--owner", "bot", "--cwd", str(self.cwd), "--model", "sonnet", prompt="installed", entry=installed)
        self.assertEqual(self.finished(run)["status"], "completed")
        argv = self.invocation(run)["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        proc = subprocess.run([str(REPO / "uninstall.sh"), "--keep-state"], env=self.env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(self.state.exists())
        self.assertFalse(installed.exists())
        self.assertFalse(destination.exists())
        self.assertFalse(self.config_dir.exists())
        subprocess.run([str(REPO / "uninstall.sh")], env=self.env, check=True, capture_output=True)
        self.assertFalse(self.state.exists())
        self.assertEqual(settings.read_text(), '{"marker": "keep me"}')


if __name__ == "__main__":
    unittest.main()
