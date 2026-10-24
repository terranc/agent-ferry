# Ferry Runtime Contract

## 1. Scope / Trigger

Read before changing the Python CLI, file-backed state, approval hooks, process
lifecycle, installer, or wake-on-done integration. Runtime code is in `ferry/`;
`bin/ferry` is its executable entry. Use Python 3.9+ and the standard library.

## 2. Signatures

```text
ferry run --owner BOT --cwd DIRECTORY [--session UUID] [--model MODEL] [--prompt-file FILE]
ferry status RUN_ID [--full]
ferry approvals [--run RUN_ID]
ferry approve APPROVAL_ID allow|deny [--note TEXT]
ferry cancel RUN_ID
ferry sessions [--cwd DIRECTORY]
ferry doctor
```

Internal entry points are `_exec RUN_ID` (one summary line for notify-run) and
`hook-permission` (Claude hook JSON only). Never emit public CLI envelopes from
the permission hook, including when config or stdin parsing fails.

## 3. Contracts

- Public commands emit one JSON object: `ok: true` plus command fields, or
  `ok: false, error: {code, message}` with exit code 2. `doctor` reports check
  failures inside `checks`/`healthy`.
- `run` returns `run_id`, native Claude `session_id`, `new_session`, `status`,
  `notify`, `next`, and `warning` when notification is unavailable. Prompt comes
  from a UTF-8 file or stdin, never shell interpolation.
- Optional `--model` accepts a model alias or full ID verbatim. Store it in this
  run's metadata and pass `--model VALUE` as argv in both new and resumed runs.
  Missing/null in metadata means omit the flag (including old records); let
  Claude choose. Do not enumerate model IDs, add a ferry default, or silently
  retry a different model. Availability validation belongs to Claude Code.
- `status` exposes status, result/truncation, cost, turns, pending approvals,
  and a shell-quoted `resume_cmd`. Final states: completed, failed, cancelled,
  interrupted. waiting_approval is derived from live, unexpired hook requests.
- `HOME`, `XDG_CONFIG_HOME`, `XDG_STATE_HOME` locate private config/state.
  `FERRY_RUN_ID` is required only by the permission hook; the worker supplies it.
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
- Verify `_exec RUN_ID` tokens before trusting a worker PID. For interrupted
  runs, verify the child's session arguments before killing its process group
  and releasing the session lock. PID existence alone cannot establish identity.
- Parse relay config without sourcing shell code. Never log relay keys or
  transport exceptions that may include credentials.
- `skills/ferry` is the Bot entry point for Mac Claude coding requests and setup.
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
| Supplied session is not a UUID, including empty string | INVALID_SESSION_ID |
| Session already has a live run | SESSION_BUSY |
| Empty prompt or TTY without prompt file | EMPTY_PROMPT |
| Supplied model is empty or whitespace | INVALID_ARGUMENT; no Claude |
| Missing Claude binary | CLAUDE_NOT_FOUND |
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
sh -n install.sh uninstall.sh
git diff --check
```

Use isolated HOME/XDG directories, fake Claude/caffeinate/notify-run, and local
HTTP stubs. The fake invokes the rendered real hook. Assert argv, exact prompt,
one winner in races, absent unapproved target files, cancelled hook deny output,
process cleanup, model alias/full ID forwarding on new/resumed/installed runs,
omitted and empty model arguments, retained records, installation idempotence and untouched
`.claude/settings.json`. Resolve temporary paths before macOS realpath assertions
(`/var` aliases `/private/var`). Tests require `ps` permission and should finish
within 60 seconds.

Fake results do not validate real Claude permission/sandbox/session behavior
or Grok relay routing. Keep S1–S10 explicitly pending until real evidence exists.

## 7. Wrong vs Correct

Wrong: delete a session lock as soon as its worker PID is absent; the old
Claude process may still be running. Create a public decision file, then write
its JSON; another reader can see an empty decision.

Correct: reconcile and verify/stop the orphan child first, then release only
the lock whose content equals this run ID. Publish fully written decision
files once using `Store.decide`, and let failures produce a deny.
