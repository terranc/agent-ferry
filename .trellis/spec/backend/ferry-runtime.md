# Ferry Runtime Contract

## 1. Scope / Trigger

Read before changing the Python CLI, file-backed state, approval hooks, process
lifecycle, installer, or wake-on-done integration. Runtime code is in `ferry/`;
`bin/ferry` is its executable entry. Use Python 3.9+ and the standard library.
The Grok adapter additionally requires Python 3.11+ (`tomllib`). No runtime SDKs.

## 2. Signatures

```text
ferry run --owner BOT --cwd DIRECTORY [--agent claude|codex|grok|pi|kimi] [--session NATIVE_ID] [--model MODEL] [--prompt-file FILE]
ferry status RUN_ID [--full]
ferry approvals [--run RUN_ID]
ferry approve APPROVAL_ID allow|deny [--note TEXT]
ferry cancel RUN_ID
ferry sessions [--cwd DIRECTORY] [--agent AGENT]
ferry doctor [--agent AGENT|all]
```

Internal entry points are `_exec RUN_ID` (one summary line for notify-run) and
`hook-permission` (Claude hook JSON only), and `hook-tool` (Pi guard decision).
Never emit public CLI envelopes from either hook; parsing/config errors deny.

## 3. Contracts

- Public commands emit one JSON object: `ok: true` plus command fields, or
  `ok: false, error: {code, message}` with exit code 2. `doctor` reports check
  failures inside `checks`/`healthy`.
- `run` returns `run_id`, `agent`, native `session_id`, `new_session`, `status`,
  `notify`, `next`, and `warning` when notification is unavailable. Prompt comes
  from a UTF-8 file or stdin, never shell interpolation.
- Default agent is Claude; missing agent in old metadata also means Claude.
  Claude/Pi IDs are UUIDs. Other native IDs are restricted non-path strings.
  Codex/ACP allocate new IDs after startup: session_id and resume_cmd may be null
  until status reports them. Never substitute a ferry ID for a native ID.
  Bind and lock `(agent, session_id)` atomically; retain legacy Claude lock paths.
- Optional `--model` accepts a model alias or full ID verbatim. Store it in this
  run's metadata and forward via native argv or protocol in new and resumed runs.
  Missing/null in metadata means omit the flag (including old records); let
  the selected agent choose. Do not enumerate model IDs, add a ferry default,
  or silently retry a different model. Missing native model selection fails.
- `status` exposes status, result/truncation, cost, turns, pending approvals,
  and a shell-quoted `resume_cmd`. Final states: completed, failed, cancelled,
  interrupted. waiting_approval is derived from live, unexpired hook requests.
- `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME` locate private config/state.
  Workers supply FERRY_RUN_ID and FERRY_ENTRY to the native subprocess/guard.
- State directories are 0700, metadata/results are 0600. Serialize short
  metadata mutations with `Store.transaction()`; never hold it while Claude,
  HTTP notification, or approval polling waits.
- Use `write_json(..., exclusive=True)` to publish decisions. It writes a
  complete temporary file and uses a non-overwriting hard link. Creating the
  public filename with O_EXCL then writing JSON exposes partial content.
- Only the first allowed/denied/expired/cancelled/interrupted decision wins.
  Return `hookSpecificOutput.hookEventName = PermissionRequest` and
  `decision.behavior = allow|deny`; never return persistent updatedPermissions.
- Launch Claude with an argv list and stdin, acceptEdits and sandbox settings;
  never add permission-bypass flags. Configure hook `onFailure: block`.
- Codex uses app-server stdio, untrusted approval and workspace-write sandbox.
  Reply accept/decline only for a single command/file change; deny turn-wide
  permission grants. Grok/Kimi use ACP manual mode and allow_once/reject_once.
  Do not advertise client filesystem/terminal delegation; unknown requests deny.
- Grok mode changes alone do not override permissive global configuration.
  Create a private per-run GROK_HOME with a copied, sanitized config and pinned
  requirements; preserve deny rules, drop allow rules, force ask for lowercase
  bash/edit. Native inspect must acknowledge the config without skipped rules
  before any prompt. Uppercase Bash/Edit are silently skipped by Grok 1.0.70.
  Never overwrite owner config/requirements. Existing owner requirements fail
  closed pending composition review. Symlink native state, ensure original
  sessions directory exists even on first use, and delete only the generated
  profile on exit. Never remove native login/history targets.
- Pi uses RPC and an explicitly loaded tool_call extension with other extensions
  disabled. Require the matching ready message via extension_ui_request notify
  before submitting a prompt (extension stdout goes to stderr). Guard helper
  failure denies. Readonly tools and realpath-contained writes may autoallow;
  shell/unknown/escaping operations require a one-operation decision.
- Codex completes at turn/completed; ACP at the prompt response; Pi only at
  agent_settled, not agent_end. Native cancelled/aborted is cancelled, not success.
  Suppress ACP history replay from the new result. Native cost stays null unless
  explicitly reported; do not invent zero. Startup has a deadline; model work
  has no total timeout. Approval waiting does not consume the startup deadline.
- Shared approvals record requester type: legacy hook-permission, hook-tool,
  or _exec for protocol workers. Validate that process identity, expire first
  decisions, retain raw native request privately, and omit it from public lists.
- Verify `_exec RUN_ID` tokens before trusting a worker PID. For interrupted
  runs, verify the child's birth fingerprint before killing its process group
  and releasing the session lock; old Claude records use session argv matching.
  PID existence alone cannot establish identity.
- Parse relay config without sourcing shell code. Never log relay keys or
  transport exceptions that may include credentials.
- `skills/ferry` is the Bot entry point for all five Mac coding tools and setup.
  Continuation retains tool identity; never resume a session in another tool.
  Keep onboarding in its linked `references/setup.md`; persist and read back
  routing preferences instead of claiming future selection from chat context.
  Validate fresh-conversation routing and relay delivery in the real Bot.
- `skills/wake-on-done` is an unchanged upstream snapshot. Record its revision
  and blob hashes in `skills/UPSTREAM.md`; keep ferry adaptations separate.
  Notification integration tests use this copy directly.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| cwd is root itself, outside real root, missing, or not a directory | INVALID_CWD; no Claude |
| Supplied session fails its backend's ID validation, including empty string | INVALID_SESSION_ID |
| Session already has a live run | SESSION_BUSY |
| Empty prompt or TTY without prompt file | EMPTY_PROMPT |
| Supplied model is empty or whitespace | INVALID_ARGUMENT; no Claude |
| Missing Claude binary | CLAUDE_NOT_FOUND |
| Missing other binary / version too old | AGENT_NOT_FOUND / UNSUPPORTED_AGENT |
| Grok guard skipped, owner requirements exist, or Kimi lacks manual mode | failed before prompt |
| Invalid run/approval identifier or missing record | NOT_FOUND |
| Second answer to an answered approval | ALREADY_ANSWERED |
| Deadline elapsed | APPROVAL_EXPIRED; deny |
| Approval hook/parent dead, cancelled run, or cancelling terminal run | RUN_NOT_ACTIVE |
| Hook config/stdin/I/O exception | Valid deny JSON, exit 0 |
| Bad Claude JSON, nonzero exit, or is_error | failed; preserve stderr tail |

## 5. Good / Base / Bad Cases

- Good: two concurrent launches on one session yield one successful run and one
  SESSION_BUSY; two competing answers yield exactly one durable decision.
- Base: a missing relay still permits execution with a warning and status polling.
- Bad: a worker is SIGKILLed while Claude is active. Reconciliation must stop
  the orphan before making the session available again.

## 6. Tests Required

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q ferry tests
node --check ferry/pi-guard.mjs
sh -n install.sh uninstall.sh
git diff --check
```

The complete suite requires Python 3.11+. Use isolated HOME/XDG directories,
fake native agents/caffeinate/notify-run, and local HTTP stubs. Claude/Pi fakes
invoke the real guard helper; Codex/ACP fakes exchange native requests.
Assert argv, exact prompt,
one winner in races, absent unapproved target files, cancelled hook deny output,
process cleanup, model alias/full ID forwarding on new/resumed/installed runs,
omitted and empty model arguments, retained records, installation idempotence and untouched
`.claude/settings.json`. Resolve temporary paths before macOS realpath assertions
(`/var` aliases `/private/var`). Tests require `ps` permission and should finish
within 60 seconds.

Minimum supported new CLI versions: Codex 0.164.0, Grok Build 1.0.70, Pi 1.4.0
(@earendil-works/pi-coding-agent), Kimi Code 2.1.1 (not legacy Python kimi-cli).
Test native IDs, per-agent locks, model selection, history replay, early completion,
guard readiness, allow-once only, expiry/cancel/orphans, malformed protocol, and
Grok config preservation/first-use session persistence/skipped-rule refusal.

Real CLI startup, same-session continuation and outside-write rejection passed
for all five on 2026-10-26. This does not validate the full command/sandbox matrix
or Grok Bot routing/relay delivery. Track those separately from fake results.

## 7. Wrong vs Correct

Wrong: delete a session lock as soon as its worker PID is absent; the old
Claude process may still be running. Create a public decision file, then write
its JSON; another reader can see an empty decision.

Correct: reconcile and verify/stop the orphan child first, then release only
the lock whose content equals this run ID. Publish fully written decision
files once using `Store.decide`, and let failures produce a deny.
