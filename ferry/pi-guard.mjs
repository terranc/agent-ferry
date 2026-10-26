// Loaded explicitly by ferry's Pi RPC adapter, before any prompt is submitted.
import { spawn } from "node:child_process";

export default function (pi) {
  const entry = process.env.FERRY_ENTRY;
  const runId = process.env.FERRY_RUN_ID;
  if (!entry || !runId) throw new Error("Missing ferry guard configuration");

  pi.on("tool_call", async (event) => {
    try {
      const decision = await new Promise((resolve, reject) => {
        const child = spawn(entry, ["hook-tool"], { stdio: ["pipe", "pipe", "pipe"] });
        let output = "";
        child.on("error", reject);
        child.stdout.setEncoding("utf8");
        child.stdout.on("data", (data) => {
          output += data;
          if (output.length > 65536) { child.kill(); reject(new Error("Invalid guard output")); }
        });
        child.stderr.resume();
        child.stdin.on("error", reject);
        child.on("close", (code) => {
          try { if (code !== 0) throw new Error("Guard failed"); resolve(JSON.parse(output)); }
          catch (error) { reject(error); }
        });
        child.stdin.end(JSON.stringify({ tool_name: event.toolName, tool_input: event.input }));
      });
      if (decision.behavior === "allow") return;
      return { block: true, reason: decision.message || "ferry denied the operation" };
    } catch {
      return { block: true, reason: "ferry approval channel failed; operation denied" };
    }
  });
  pi.on("session_start", (_event, ctx) => {
    // Pi redirects extension stdout to stderr. Use its supported RPC UI channel.
    ctx.ui.notify("ferry_guard_ready:" + runId, "info");
  });
}
