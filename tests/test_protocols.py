import json
import os
from pathlib import Path
import signal
import subprocess
import time

from test_ferry import FixtureCase, REPO
from ferry.core import Store, process_birth, read_json
from ferry.agents import environment, cleanup_environment
from unittest import mock


class ProtocolTest(FixtureCase):
    def setUp(self):
        super().setUp()
        self.save_config(**{f"{agent}_bin": str(REPO / "tests/fake_agent.py") for agent in ("codex", "grok", "pi", "kimi")})

    def native(self, agent, prompt="hello", session=None, model=None):
        args = ["run", "--owner", "bot", "--cwd", str(self.cwd), "--agent", agent]
        if session:
            args += ["--session", session]
        if model:
            args += ["--model", model]
        return self.call(*args, prompt=prompt)

    def test_native_sessions_models_and_resume_for_every_protocol(self):
        for agent in ("codex", "grok", "pi", "kimi"):
            with self.subTest(agent=agent):
                first = self.native(agent, "first\n'\"$`😀", model="native/model-v1")
                status = self.finished(first)
                self.assertEqual(status["status"], "completed", status)
                self.assertEqual(status["agent"], agent)
                self.assertEqual(status["result"], "first\n'\"$`😀")
                self.assertIsNone(status["cost_usd"])
                invocation = self.invocation(first)
                self.assertEqual(invocation["model"], "native/model-v1")
                self.assertNotIn("--always-approve", invocation["argv"])
                if agent == "pi":
                    self.assertIn("--no-extensions", invocation["argv"])
                    self.assertIn("--extension", invocation["argv"])
                if agent == "codex":
                    params = next(r["params"] for r in invocation["messages"] if r.get("method") == "thread/start")
                    self.assertEqual(params["approvalPolicy"], "untrusted")
                    self.assertEqual(params["sandbox"], "workspace-write")
                if agent in ("grok", "kimi"):
                    self.assertEqual(invocation["mode"], "ask" if agent == "grok" else "default")
                if agent == "grok":
                    self.assertIn("disable_bypass_permissions_mode = true", invocation["grok_policy"])
                    self.assertFalse(Path(invocation["grok_home"]).exists())
                second = self.native(agent, "second", session=status["session_id"], model="native/model-v2")
                resumed = self.finished(second)
                self.assertEqual(resumed["session_id"], status["session_id"])
                self.assertEqual(resumed["result"], "second")
                self.assertEqual(self.invocation(second)["model"], "native/model-v2")
                self.assertIn(agent, resumed["resume_cmd"])

    def test_approvals_allow_and_deny_on_every_backend(self):
        for agent in ("codex", "grok", "pi", "kimi"):
            for answer in ("allow", "deny"):
                with self.subTest(agent=agent, answer=answer):
                    target = self.home / f"{agent}-{answer}"
                    run = self.native(agent, json.dumps({"target": str(target)}))
                    approval = self.approval(run)
                    self.assertNotIn("native_request", approval)
                    if agent != "pi":
                        raw = read_json(self.state / "approvals" / (approval["approval_id"] + ".json"))["native_request"]
                        self.assertIn("id", raw["request"])
                        self.assertIn("method", raw["request"])
                        self.assertIn("tool_input", raw["tool_request"])
                    self.assertFalse(target.exists())
                    self.call("approve", approval["approval_id"], answer)
                    self.assertEqual(self.finished(run)["status"], "completed")
                    self.assertEqual(target.exists(), answer == "allow")
                    self.assertEqual(self.call("approve", approval["approval_id"], answer, code=2)["error"]["code"], "ALREADY_ANSWERED")

    def test_native_approvals_expire_without_allowing(self):
        self.save_config(approval_timeout_seconds=0.3)
        for agent in ("codex", "grok", "pi", "kimi"):
            with self.subTest(agent=agent):
                target = self.home / f"expired-{agent}"
                run = self.native(agent, json.dumps({"target": str(target)}))
                status = self.finished(run)
                self.assertEqual(status["result"], "denied", status)
                self.assertFalse(target.exists())

    def test_protocol_failure_is_not_success(self):
        for agent in ("codex", "grok", "pi", "kimi"):
            for mode in ("failed", "bad-json", "exit"):
                with self.subTest(agent=agent, mode=mode):
                    status = self.finished(self.native(agent, json.dumps({"mode": mode})))
                    self.assertEqual(status["status"], "failed", status)
                    self.assertTrue(status["error"])

    def test_early_codex_completion_is_not_lost(self):
        status = self.finished(self.native("codex", json.dumps({"mode": "early-complete", "text": "early"})))
        self.assertEqual(status["result"], "early")

    def test_only_allow_once_options_are_accepted(self):
        for agent in ("grok", "kimi"):
            target = self.home / f"permanent-{agent}"
            status = self.finished(self.native(agent, json.dumps({"target": str(target), "permanent": True})))
            self.assertEqual(status["result"], "denied")
            self.assertFalse(target.exists())

    def test_unknown_client_side_write_request_is_denied(self):
        for agent in ("codex", "grok", "kimi"):
            status = self.finished(self.native(agent, json.dumps({"mode": "unknown-request"})))
            self.assertEqual(status["result"], "blocked")

    def test_pi_guard_is_required_before_prompt(self):
        self.env["FERRY_TEST_NO_GUARD"] = "1"
        self.save_config(agent_start_timeout_seconds=0.2)
        run = self.native("pi", "must not execute")
        status = self.finished(run)
        self.assertEqual(status["status"], "failed")
        self.assertIn("initialization timed out", status["error"])
        self.assertEqual(self.invocation(run)["stdin"], "")

    def test_installed_adapters_and_pi_guard_are_usable(self):
        proc = subprocess.run([str(REPO / "install.sh")], env=self.env, text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        installed = self.home / ".local/bin/ferry"
        guard = self.home / ".local/share/agent-ferry/ferry/pi-guard.mjs"
        self.assertEqual(guard.read_bytes(), (REPO / "ferry/pi-guard.mjs").read_bytes())
        for agent in ("codex", "grok", "pi", "kimi"):
            with self.subTest(agent=agent):
                run = self.call("run", "--owner", "bot", "--cwd", str(self.cwd), "--agent", agent,
                                "--model", "native/installed", prompt="installed adapter", entry=installed)
                self.assertEqual(self.finished(run)["result"], "installed adapter")
                if agent == "pi":
                    self.assertIn(str(guard), self.invocation(run)["argv"])

    def test_kimi_must_advertise_manual_mode(self):
        self.env["FERRY_TEST_NO_MODES"] = "1"
        run = self.native("kimi")
        status = self.finished(run)
        self.assertEqual(status["status"], "failed")
        self.assertIn("manual approval mode", status["error"])
        self.assertEqual(self.invocation(run)["stdin"], "")

    def test_unsupported_version_is_failed_before_any_prompt(self):
        self.env["FERRY_TEST_VERSION"] = "0.0.1"
        status = self.finished(self.native("pi"))
        self.assertEqual(status["status"], "failed")
        self.assertIn("Unsupported pi version", status["error"])

    def test_native_cancelled_turns_are_not_failed_or_completed(self):
        for agent in ("codex", "grok", "pi", "kimi"):
            with self.subTest(agent=agent):
                status = self.finished(self.native(agent, json.dumps({"mode": "cancelled"})))
                self.assertEqual(status["status"], "cancelled", status)

    def test_pi_reports_native_cost_when_available(self):
        status = self.finished(self.native("pi", json.dumps({"mode": "cost"})))
        self.assertEqual(status["cost_usd"], 0.025)

    def test_grok_user_config_is_preserved_and_policy_isolation_is_private(self):
        import tomllib
        source = self.home / ".grok"
        source.mkdir()
        original = source / "config.toml"
        original.write_text('[ui]\npermission_mode="always-approve"\n[models]\ndefault="native/default"\n[permission]\nallow=["Edit"]\ndeny=["Bash(rm *)"]\n')
        auth = source / "auth.json";auth.write_text("private-test-auth")
        sessions = source / "sessions"
        original_bytes = original.read_bytes()
        with mock.patch.dict(os.environ, self.env, clear=True):
            store = Store();store.ensure()
            run_id = "r_20261026-000000_123456789abc"
            store.run_dir(run_id).mkdir()
            meta = {"run_id": run_id, "agent": "grok", "cwd": str(self.cwd)}
            profile = Path(environment(store, meta)["GROK_HOME"])
            isolated = tomllib.loads((profile / "config.toml").read_text())
            self.assertEqual(isolated["ui"]["permission_mode"], "ask")
            self.assertNotIn("allow", isolated["permission"])
            self.assertEqual(isolated["permission"]["deny"], ["Bash(rm *)"])
            self.assertEqual(isolated["models"]["default"], "native/default")
            self.assertEqual((profile / "config.toml").stat().st_mode & 0o777, 0o600)
            self.assertTrue((profile / "auth.json").is_symlink())
            self.assertTrue((profile / "sessions").is_symlink())
            (profile / "sessions" / "new-session").write_text("persisted")
            cleanup_environment(store, meta)
        self.assertEqual(original.read_bytes(), original_bytes)
        self.assertEqual(auth.read_text(), "private-test-auth")
        self.assertEqual((sessions / "new-session").read_text(), "persisted")

    def test_grok_refuses_a_skipped_guard_rule(self):
        self.env["FERRY_TEST_SKIP_GUARD"] = "1"
        run = self.native("grok")
        status = self.finished(run)
        self.assertEqual(status["status"], "failed")
        self.assertIn("did not load", status["error"])
        self.assertFalse((self.directory(run) / "invocation.json").exists())

    def test_grok_does_not_replace_existing_requirements(self):
        source = self.home / ".grok";source.mkdir()
        policy = source / "requirements.toml";policy.write_text("# owner policy")
        status = self.finished(self.native("grok"))
        self.assertEqual(status["status"], "failed")
        self.assertIn("composition needs review", status["error"])
        self.assertEqual(policy.read_text(), "# owner policy")
        checks = self.call("doctor", "--agent", "grok")["checks"]
        self.assertEqual(next(c for c in checks if c["name"] == "grok_owner_policy")["status"], "fail")

    def test_same_native_id_in_different_agents_is_independent(self):
        first = self.native("codex", json.dumps({"sleep": 20}), session="same-id")
        second = self.native("grok", json.dumps({"sleep": 20}), session="same-id")
        self.invocation(first); self.invocation(second)
        result = self.call("run", "--owner", "bot", "--cwd", str(self.cwd), "--agent", "codex", "--session", "same-id", prompt="busy", code=2)
        self.assertEqual(result["error"]["code"], "SESSION_BUSY")
        self.assertEqual(len(self.call("sessions", "--agent", "grok")["sessions"]), 1)

    def test_cancel_invalidates_native_approvals(self):
        for agent in ("codex", "grok", "pi", "kimi"):
            with self.subTest(agent=agent):
                target = self.home / f"cancel-{agent}"
                run = self.native(agent, json.dumps({"target": str(target)}))
                approval = self.approval(run)
                meta = read_json(self.directory(run) / "meta.json")
                self.call("cancel", run["run_id"])
                self.assertEqual(self.finished(run)["status"], "cancelled")
                self.assertFalse(target.exists())
                self.assertNotEqual(process_birth(meta["agent_pid"]), meta["agent_birth"])
                self.assertEqual(self.call("approve", approval["approval_id"], "allow", code=2)["error"]["code"], "RUN_NOT_ACTIVE")

    def test_orphan_protocol_process_is_reaped_on_reconcile(self):
        run = self.native("codex", json.dumps({"sleep": 20}))
        self.invocation(run)
        meta = read_json(self.directory(run) / "meta.json")
        os.kill(meta["worker_pid"], signal.SIGKILL)
        self.wait_for(lambda: self.call("status", run["run_id"])["status"] == "interrupted")
        self.wait_for(lambda: process_birth(meta["agent_pid"]) != meta["agent_birth"])

    def test_pi_project_write_is_automatic_but_escape_is_not(self):
        target = self.cwd / "inside.txt"
        status = self.finished(self.native("pi", json.dumps({"target": str(target)})))
        self.assertEqual(status["status"], "completed")
        self.assertTrue(target.exists())
        link = self.cwd / "outside"
        link.symlink_to(self.home, target_is_directory=True)
        run = self.native("pi", json.dumps({"target": str(link / "escape.txt")}))
        approval = self.approval(run)
        self.assertFalse((self.home / "escape.txt").exists())
        self.call("approve", approval["approval_id"], "deny")
        self.finished(run)

    def test_doctor_checks_selected_agent_and_all(self):
        data = self.call("doctor", "--agent", "all")
        for agent in ("claude", "codex", "grok", "pi", "kimi"):
            self.assertEqual(next(c for c in data["checks"] if c["name"] == agent)["status"], "pass")
        self.save_config(kimi_bin="/missing")
        data = self.call("doctor", "--agent", "kimi")
        self.assertFalse(data["healthy"])

    def test_legacy_records_without_agent_still_resume_as_claude(self):
        run = self.run_task()
        self.finished(run)
        path = self.directory(run) / "meta.json"
        meta = read_json(path);meta.pop("agent")
        from ferry.core import write_json
        write_json(path, meta)
        self.assertEqual(self.call("status", run["run_id"])["agent"], "claude")
        self.assertIn("claude --resume", self.call("sessions")["sessions"][0]["resume_cmd"])
