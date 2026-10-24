# Development Workflow

---

## Core Principles

1. **Plan before code** — figure out what to do before you start
2. **Specs injected, not remembered** — guidelines are injected via hook/skill, not recalled from memory
3. **Persist everything** — research, decisions, and lessons all go to files; conversations get compacted, files don't
4. **Incremental development** — one task at a time
5. **Capture learnings** — after each task, review and write new knowledge back to spec

---

## Trellis System

### Developer Identity

On first use, initialize your identity:

```bash
python3 ./.trellis/scripts/init_developer.py <your-name>
```

Creates `.trellis/.developer` (gitignored) + `.trellis/workspace/<your-name>/`.

### Spec System

`.trellis/spec/` holds coding guidelines organized by package and layer.

- `.trellis/spec/<package>/<layer>/index.md` — entry point with **Pre-Development Checklist** + **Quality Check**. Actual guidelines live in the `.md` files it points to.
- `.trellis/spec/guides/index.md` — cross-package thinking guides.

```bash
python3 ./.trellis/scripts/get_context.py --mode packages   # list packages / layers
```

**When to update spec**: new pattern/convention found · bug-fix prevention to codify · new technical decision.

### Task System

Every task has its own directory under `.trellis/tasks/{MM-DD-name}/` holding `task.json`, `prd.md`, `design.md`, and optional `research/`. In Native AI mode the directory does not contain `implement.md`, `implement.jsonl`, or `check.jsonl`; those exist only when a task is explicitly switched to sub-agent dispatch.

```bash
# Task lifecycle
python3 ./.trellis/scripts/task.py create "<title>" [--slug <name>] [--parent <dir>]
python3 ./.trellis/scripts/task.py start <name>          # set active task (session-scoped when available)
python3 ./.trellis/scripts/task.py current --source      # show active task and source
python3 ./.trellis/scripts/task.py finish                # clear active task (triggers after_finish hooks)
python3 ./.trellis/scripts/task.py archive <name>        # move to archive/{year-month}/
python3 ./.trellis/scripts/task.py list [--mine] [--status <s>]
python3 ./.trellis/scripts/task.py list-archive

# Code-spec context (injected into implement/check agents via JSONL).
# `implement.jsonl` / `check.jsonl` are seeded (empty) on `task create` for sub-agent-capable
# platforms; the AI curates real spec + research entries during planning. `validate` fails
# and `start` refuses while a seeded manifest is still empty — sub-agents would run with
# zero spec context. Pass `start --allow-empty-context` when that is intentional.
python3 ./.trellis/scripts/task.py add-context <name> <action> <file> <reason>
python3 ./.trellis/scripts/task.py list-context <name> [action]
python3 ./.trellis/scripts/task.py validate <name>

# Task metadata
python3 ./.trellis/scripts/task.py set-branch <name> <branch>
python3 ./.trellis/scripts/task.py set-base-branch <name> <branch>    # PR target
python3 ./.trellis/scripts/task.py set-scope <name> <scope>

# Hierarchy (parent/child)
python3 ./.trellis/scripts/task.py add-subtask <parent> <child>
python3 ./.trellis/scripts/task.py remove-subtask <parent> <child>

# PR creation
python3 ./.trellis/scripts/task.py create-pr [name] [--dry-run]
```

> Run `python3 ./.trellis/scripts/task.py --help` to see the authoritative, up-to-date list.

**Current-task mechanism**: `task.py create` creates the task directory and (when session identity is available) auto-sets the per-session active-task pointer so the planning breadcrumb fires immediately. `task.py start` writes the same pointer (idempotent if already set) and flips `task.json.status` from `planning` to `in_progress`. State is stored under `.trellis/.runtime/sessions/`. If no context key is available from hook input, `TRELLIS_CONTEXT_ID`, or a platform-native session environment variable, there is no active task and `task.py start` fails with a session identity hint. `task.py finish` deletes the current session file (status unchanged). `task.py archive <task>` writes `status=completed`, moves the directory to `archive/`, and deletes any runtime session files that still point at the archived task.

### Task Hold

A hold pauses a task without touching its state machine. It is metadata in
`task.json.meta`, so `status`, the phase breadcrumbs, and the board columns all
stay as they are.

```bash
# Mark on hold — status stays in_progress
python3 ./.trellis/scripts/task.py set-meta <task-dir> hold blocked
python3 ./.trellis/scripts/task.py set-meta <task-dir> hold_reason "waiting on PR #123"

# Clear the hold
python3 ./.trellis/scripts/task.py set-meta <task-dir> hold ""
```

- `meta.hold` reads as held when it is `blocked` or `paused`; any other value,
  including an empty string, means not held.
- `meta.hold_reason` is free text shown next to the hold badge.
- Use hold for work blocked on something outside the session. Do not invent a
  status for it: unknown statuses land in the board's `other` column and drop the
  per-turn breadcrumb.
- `task.py set-meta` ships with Trellis 0.6.15+. On older projects, write the same
  two keys into `task.json` directly; nothing else reads them.

### Workspace System

Records every AI session for cross-session tracking under `.trellis/workspace/<developer>/`.

- `journal-N.md` — session log. **Max 2000 lines per file**; a new `journal-(N+1).md` is auto-created when exceeded.
- `index.md` — personal index (total sessions, last active).

```bash
python3 ./.trellis/scripts/add_session.py --title "Title" --commit "hash" --summary "Summary"
```

### Context Script

```bash
python3 ./.trellis/scripts/get_context.py                            # full session runtime
python3 ./.trellis/scripts/get_context.py --mode packages            # available packages + spec layers
python3 ./.trellis/scripts/get_context.py --mode phase --step <X.Y>  # detailed guide for a workflow step
```

---

<!--
  WORKFLOW-STATE BREADCRUMB CONTRACT (read this before editing the tag blocks below)

  The [workflow-state:STATUS] blocks embedded in the ## Phase Index section
  below are the SINGLE source of truth for the per-turn `<workflow-state>`
  breadcrumb that every supported AI platform's UserPromptSubmit hook
  reads. inject-workflow-state.py (Python platforms) and
  inject-workflow-state.js (OpenCode plugin) only parse them — there is no
  fallback dict baked into the scripts after v0.5.0-rc.0.

  STATUS charset: [A-Za-z0-9_-]+. When the hook can't find a tag, it
  degrades to a generic "Refer to workflow.md for current step." line —
  intentionally visible so users notice and fix a broken workflow.md.

  INVARIANT (test/regression.test.ts):
    Every workflow-walkthrough step marked `[required · once]` must have a
    matching enforcement line in its phase's [workflow-state:*] block. The
    breadcrumb is the only per-turn channel; if a mandatory step isn't
    mentioned there, the AI silently skips it (Phase 1 planning gate
    skip and Phase 3.4 commit skip both manifested via this gap).

  TAG ↔ PHASE scoping:
    [workflow-state:no_task]      → no active task; before Phase 1
    [workflow-state:task_error]   → active task record is unreadable; repair it before continuing
    [workflow-state:planning]     → all of Phase 1 (status='planning')
    [workflow-state:planning-inline] → Codex inline variant of Phase 1
    [workflow-state:in_progress]  → Phase 2 + Phase 3.2-3.4
                                    (status stays 'in_progress' from
                                    task.py start until task.py archive)
    [workflow-state:in_progress-inline] → Codex inline variant of Phase 2/3
    [workflow-state:completed]    → currently DEAD: cmd_archive flips
                                    status and moves the dir in the same
                                    call, so the resolver loses the
                                    pointer (block kept for a future
                                    explicit in_progress→completed
                                    transition)

  Editing checklist:
    - When you change a [workflow-state:STATUS] block, also check the
      matching phase's `[required · once]` walkthrough steps for sync
    - Run `trellis update` after editing to push the new bodies to
      downstream user projects (block-level managed replacement)
    - Full runtime contract:
      .trellis/spec/cli/backend/workflow-state-contract.md
-->

## Phase Index

```
Phase 1: Plan    → classify, get task-creation consent, then write prd.md + design.md
Phase 2: Native  → main session implements directly after status is in_progress
Phase 3: Finish  → verify with project commands, optional spec update, commit, wrap up
```

### Native AI Mode

This project uses Trellis for **requirements and design alignment**. The main session
(the high-capability model) owns implementation and verification.

- `prd.md` and `design.md` are the deliverables of Phase 1.
- Do not create `implement.md`, `implement.jsonl`, or `check.jsonl` unless the user
  explicitly asks for them in that task.
- After PRD + design are approved, run `task.py start --allow-empty-context` and implement
  directly in the main session — no `trellis-implement` / `trellis-check` sub-agents.
- Verify with the project's own build / lint / test commands.

### Request Triage

- Simple conversation or small task: ask only whether this turn should create a Trellis task. If the user says no, skip Trellis for this session.
- Complex task: ask whether you may create a Trellis task and align requirements + design. If the user says no, do not do broad inline implementation; explain, clarify scope, or suggest a smaller split.
- User approval to create a task is not approval to start implementation. PRD and design still need review first.

### Planning Artifacts

- `prd.md` — requirements, constraints, acceptance criteria, and out-of-scope.
- `design.md` — technical design: boundaries, contracts, data flow, compatibility/migration, tradeoffs, and rollout/rollback shape. Required in Native AI mode.
- `research/*.md` — optional evidence gathered during requirement or design work.
- `implement.md` — **not used**. Execution order and validation steps are derived by the main session at implementation time; they are not persisted as a task artifact.
- `implement.jsonl` / `check.jsonl` — **not used**; there are no implement/check sub-agents to feed.
- Do not classify tasks as "lightweight" vs "complex" to decide artifact depth. Every task follows the same PRD + design path; scale the depth of `design.md` to the task.

### Parent / Child Task Trees

Use a parent task when one user request contains several independently verifiable deliverables. The parent task owns the source requirement set, the task map, cross-child acceptance criteria, and final integration review; it normally should not be the implementation target unless it also has direct work.

Use child tasks for deliverables that can be planned and archived independently. Parent/child structure is not a dependency system: if one child must wait for another, write that ordering in the child `prd.md` / `design.md` and keep each child's acceptance criteria testable.

Create new children with `task.py create "<title>" --slug <name> --parent <parent-dir>`. Link existing tasks with `task.py add-subtask <parent> <child>`, and unlink mistakes with `task.py remove-subtask <parent> <child>`.

<!-- Per-turn breadcrumb: shown when there is no active task (before Phase 1) -->

[workflow-state:no_task]
No active task. First classify the current turn and ask for task-creation consent before creating any Trellis task.
Trellis aligns requirements and design in this repo: a task produces `prd.md` + `design.md`, then implementation is Native AI in the main session.
Simple conversation / small task: ask only whether this turn should create a Trellis task. If the user says no, skip Trellis for this session.
Complex task: ask the user if you can create a Trellis task and align requirements + design. If the user says no, explain, clarify scope, or suggest a smaller split.
[/workflow-state:no_task]

<!-- Per-turn breadcrumb: shown when the active task record cannot be read. -->

[workflow-state:task_error]
The active task record could not be read. Do not create or activate another task.
Inspect the task directory named above and repair its task.json. It must be a valid JSON object with a non-empty status.
Preserve existing task fields and artifacts. If the correct status cannot be determined safely, ask the user before reconstructing the record.
[/workflow-state:task_error]

### Phase 1: Plan
- 1.0 Create task `[required · once]` (only after task-creation consent)
- 1.1 Requirement + design exploration `[required · repeatable]` (`prd.md`, then `design.md`)
- 1.2 Research `[optional · repeatable]`
- 1.3 Configure context `[optional · skipped in Native AI mode]` — no JSONL manifests
- 1.4 Activate task `[required · once]` (PRD + design review gate, then `task.py start --allow-empty-context`; status → in_progress)
- 1.5 Completion criteria

<!-- Per-turn breadcrumb: shown throughout Phase 1 (status='planning') -->

[workflow-state:planning]
Load `trellis-brainstorm`; align requirements and design.
Write `prd.md` first, then `design.md` (boundaries, contracts, compatibility, tradeoffs).
Do NOT create `implement.md` or curate `implement.jsonl` / `check.jsonl`.
Do not classify the task as lightweight/complex. Every task follows the same PRD + design path; keep `design.md` proportionate to the task.
Multi-deliverable scope: consider a parent task plus independently verifiable child tasks; dependencies must be written in child PRDs/designs, not implied by tree position.
After the user approves the PRD + design summary, run `task.py start <task-dir> --allow-empty-context`.
Then stop planning and hand off to Native AI implementation in the main session.
[/workflow-state:planning]

<!-- Per-turn breadcrumb: shown throughout Phase 1 when codex.dispatch_mode=inline.
     Codex-only alternate to [workflow-state:planning]. Same PRD + design contract. -->

[workflow-state:planning-inline]
Load `trellis-brainstorm`; align requirements and design.
Write `prd.md` first, then `design.md` (boundaries, contracts, compatibility, tradeoffs).
Do NOT create `implement.md` or curate `implement.jsonl` / `check.jsonl`.
Do not classify the task as lightweight/complex. Every task follows the same PRD + design path; keep `design.md` proportionate to the task.
Multi-deliverable scope: consider a parent task plus independently verifiable child tasks; dependencies must be written in child PRDs/designs, not implied by tree position.
After the user approves the PRD + design summary, run `task.py start <task-dir> --allow-empty-context`.
Then stop planning and hand off to Native AI implementation in the main session.
[/workflow-state:planning-inline]

### Phase 2: Native Execute
- 2.1 Implement directly in the main session `[required · repeatable]`
- 2.2 Verify with project commands `[required · repeatable]`
- 2.3 Rollback `[on demand]`

<!-- Per-turn breadcrumb: shown while status='in_progress'.
     Scope: all of Phase 2 + Phase 3.2-3.4 (status stays 'in_progress' from
     task.py start until task.py archive; only archive flips it). The body
     therefore must cover every required step from implementation through
     commit, including Phase 3.3 spec update and Phase 3.4 commit. -->

[workflow-state:in_progress]
Native AI mode: the main session implements the code directly. Do NOT dispatch
`trellis-implement`, `trellis-check`, or `trellis-research` sub-agents unless the
user explicitly asks for one.
Read context in this order: `prd.md` -> `design.md` -> relevant `.trellis/spec/**/index.md` -> existing code.
There is no `implement.md` or JSONL manifest to read; derive the execution order in the main session.
Verify with the project's own build / lint / test commands. `trellis-update-spec` and
`/trellis:finish-work` are optional. Commit per normal repo conventions (Phase 3.4).
[/workflow-state:in_progress]

<!-- Per-turn breadcrumb: shown while status='in_progress' when
     codex.dispatch_mode=inline. Codex-only alternate to
     [workflow-state:in_progress]. Same Native AI contract. -->

[workflow-state:in_progress-inline]
Native AI mode: the main session implements the code directly. Do NOT dispatch
`trellis-implement`, `trellis-check`, or `trellis-research` sub-agents unless the
user explicitly asks for one.
Read context in this order: `prd.md` -> `design.md` -> relevant `.trellis/spec/**/index.md` -> existing code.
There is no `implement.md` or JSONL manifest to read; derive the execution order in the main session.
Verify with the project's own build / lint / test commands. `trellis-update-spec` and
`/trellis:finish-work` are optional. Commit per normal repo conventions (Phase 3.4).
[/workflow-state:in_progress-inline]

### Phase 3: Finish
- 3.2 Debug retrospective `[on demand]`
- 3.3 Spec update `[optional · once]`
- 3.4 Commit changes `[required · once]`
- 3.5 Wrap-up reminder

> Note: step 3.1 was folded into 2.2 (last-iteration full-scope check) and 3.4 (commit preamble). Numbering kept stable to avoid breaking external references.

<!-- Per-turn breadcrumb: shown while status='completed'.
     Currently DEAD in normal flow: cmd_archive writes status='completed' in
     the same call that moves the task dir to archive/, so the active-task
     resolver loses the pointer and the hook never fires on archived tasks.
     Block preserved for a future status-transition redesign (e.g. an
     explicit in_progress→completed command). Edit through the same spec
     channel as the live blocks. -->

[workflow-state:completed]
Code committed. Optionally run `/trellis:finish-work` to archive the task and record the session.
[/workflow-state:completed]

### Rules

1. Identify which Phase you're in, then continue from the next step there
2. Run steps in order inside each Phase; `[required]` steps can't be skipped
3. Phases can roll back (e.g., Native Execute reveals a PRD/design defect → return to Plan to fix, then re-enter Execute)
4. Steps tagged `[once]` are skipped if the output already exists; don't re-run
5. Artifact presence informs the next step. `prd.md` + `design.md` are the required artifacts; `implement.md` and JSONL manifests are intentionally absent in Native AI mode.

### Active Task Routing

When a user request matches one of these intents inside an active task, route first, then load the detailed phase step if needed.

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, Pi, Oh My Pi, ZCode, Snow, Reasonix, Trae, Grok, Kimi Code]

- Planning or unclear requirements -> `trellis-brainstorm`.
- `in_progress` implementation -> implement directly in the main session; do not dispatch sub-agents.
- Before editing -> optional `trellis-before-dev`; after editing -> project build/lint/test.
- Repeated debugging -> `trellis-break-loop`; spec updates -> optional `trellis-update-spec`.

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, Pi, Oh My Pi, ZCode, Snow, Reasonix, Trae, Grok, Kimi Code]

[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

- Planning or unclear requirements -> `trellis-brainstorm`.
- Before editing -> optional `trellis-before-dev`; after editing -> project build/lint/test.
- Repeated debugging -> `trellis-break-loop`; spec updates -> optional `trellis-update-spec`.

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

### Guardrails

- Task creation approval is not implementation approval; implementation waits for the PRD + design review and `task.py start`.
- PRD + design are the rule. Never create `implement.md` or JSONL manifests unless the user explicitly asks.
- Implementation is Native AI: the main session writes code; project commands verify it.

### Loading Step Detail

At each step, run this to fetch detailed guidance:

```bash
python3 ./.trellis/scripts/get_context.py --mode phase --step <step>
# e.g. python3 ./.trellis/scripts/get_context.py --mode phase --step 1.1
```

---

## Phase 1: Plan

Goal: classify the request, get task-creation consent when a task is needed, and produce the planning artifacts required before implementation.

#### 1.0 Create task `[required · once]`

Create the task directory only after task-creation consent. The command sets status to `planning`, writes `task.json`, creates a default `prd.md`, and auto-targets the new task when session identity is available:

```bash
python3 ./.trellis/scripts/task.py create "<task title>" --slug <name>
```

`--slug` is the human-readable name only. Do **not** include the `MM-DD-` date prefix; `task.py create` adds that prefix automatically.

For task trees, create the parent task first and then create each child with `--parent <parent-dir>`. Do not start the parent just because children exist; start the child that owns the next independently verifiable deliverable.

After this command succeeds, the per-turn breadcrumb auto-switches to `[workflow-state:planning]`, telling the AI to stay in planning.

Run only `create` here — do not also run `start`. `start` flips status to `in_progress`, which switches the breadcrumb to the implementation phase before planning artifacts are reviewed. Save `start` for step 1.4.

Skip when `python3 ./.trellis/scripts/task.py current --source` already points to a task.

#### 1.1 Requirement + design exploration `[required · repeatable]`

Load the `trellis-brainstorm` skill and explore requirements and design interactively with the user per the skill's guidance.

The brainstorm skill will guide you to:
- Ask one question at a time
- Prefer researching over asking the user
- Prefer offering options over open-ended questions
- Update `prd.md` immediately after each user answer
- Split large scopes into a parent task plus child tasks when the deliverables can be verified independently
- Keep `prd.md` focused on requirements and acceptance criteria
- After the requirements converge, write `design.md`: boundaries, contracts, data flow, compatibility/migration, tradeoffs, rollout/rollback shape
- Do not produce `implement.md`; Native AI mode derives the execution order at implementation time

When considering a parent/child split:
- Use a parent task when one request contains several independently verifiable deliverables.
- Parent tasks own source requirements, child-task mapping, cross-child acceptance criteria, and final integration review.
- Child tasks own actual deliverables that can be planned and archived independently.
- Parent/child structure is not a dependency system. If child B depends on child A, write that ordering in child B's `prd.md` / `design.md`.
- Start the child task that owns the next deliverable. Do not start the parent unless the parent itself has direct implementation work.

Return to this step whenever requirements or the design change, and revise the relevant artifact.

#### 1.2 Research `[optional · repeatable]`

Research can happen at any time during requirement exploration. It isn't limited to local code — you can use any available tool (MCP servers, skills, web search, etc.) to look up external information, including third-party library docs, industry practices, API references, etc.

[Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, Pi, Oh My Pi, ZCode, Snow, Reasonix, Trae, Grok, Kimi Code]

Spawn the research sub-agent:

- **Agent type**: `trellis-research`
- **Task description**: Research <specific question>
- **Key requirement**: Research output MUST be persisted to `{TASK_DIR}/research/`

[/Claude Code, Cursor, OpenCode, codex-sub-agent, Kiro, Gemini, Qoder, CodeBuddy, Copilot, Droid, Pi, Oh My Pi, ZCode, Snow, Reasonix, Trae, Grok, Kimi Code]

[codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

Do the research in the main session directly and write findings into `{TASK_DIR}/research/`. `codex-inline` is the explicit mode that keeps work in the main session.

[/codex-inline, Kilo, Antigravity, Devin, DeepSeek Harness]

**Research artifact conventions**:
- One file per research topic (e.g. `research/auth-library-comparison.md`)
- Record third-party library usage examples, API references, version constraints in files
- Note relevant spec file paths you discovered for later reference

Brainstorm and research can interleave freely — pause to research a technical question, then return to talk with the user.

**Key principle**: Research output must be written to files, not left only in the chat. Conversations get compacted; files don't.

#### 1.3 Configure context `[optional · skipped in Native AI mode]`

Skip this step. Native AI mode has no implement/check sub-agents, so `implement.jsonl`
and `check.jsonl` are not curated and must not gate `task.py start`. Leave the seeded
files untouched (or delete them); nothing consumes them in this mode.

Only if the user explicitly switches a task to sub-agent dispatch, curate the manifests
then — the native template documents the JSONL contract.

#### 1.4 Activate task `[required · once]`

After the PRD + design review, flip the task status to `in_progress`:

```bash
python3 ./.trellis/scripts/task.py start <task-dir> --allow-empty-context
```

`prd.md` and `design.md` are the required artifacts. `--allow-empty-context` is required
because Native AI mode never curates the JSONL manifests; without it, `start` refuses on
sub-agent-capable platforms.

After this command succeeds, the breadcrumb auto-switches to
`[workflow-state:in_progress]`, and the main session implements directly.

If `task.py start` errors with a session-identity message (no context key from hook input, `TRELLIS_CONTEXT_ID`, or platform-native session env), follow the hint in the error to set up session identity, then retry.

#### 1.5 Completion criteria

| Condition | Required |
|------|:---:|
| `prd.md` exists and its acceptance criteria are testable | ✅ |
| `design.md` exists and covers boundaries/contracts/tradeoffs | ✅ |
| User confirms the PRD + design summary | ✅ |
| `task.py start --allow-empty-context` has been run (status = in_progress) | ✅ |
| `research/` has artifacts | optional |

`implement.md` and the JSONL manifests are intentionally absent in Native AI mode and
are not completion criteria.

---

## Phase 2: Native Execute

Goal: implement the approved PRD + design directly in the main session, then verify it.

#### 2.1 Implement directly in the main session `[required · repeatable]`

Do not dispatch `trellis-implement` (or any sub-agent) in Native AI mode.

1. Optionally load the `trellis-before-dev` skill and read the spec index for affected packages.
2. Read `{TASK_DIR}/prd.md`, then `{TASK_DIR}/design.md`; consult `{TASK_DIR}/research/` if present.
3. Implement the code directly in the main session. Derive the execution order yourself; do not persist it as `implement.md`.
4. Keep changes scoped to the PRD's in-scope requirements; ask before expanding scope.
5. Run the project's lint / type-check (and relevant tests) before reporting progress.

Context order: `prd.md` -> `design.md` -> relevant `.trellis/spec/**/index.md` -> existing code.
There is no `implement.md` or JSONL manifest to read.

#### 2.2 Verify with project commands `[required · repeatable]`

Do not spawn `trellis-check` unless the user explicitly asks for it. Verify directly:

- Re-read `prd.md` and check each acceptance criterion.
- Re-read `design.md` and check the implemented contracts, boundaries, and compatibility notes.
- Run the project's build / lint / type-check / test commands for affected packages.
- Check cross-layer consistency when changes span layers.
- Fix findings and re-run until green.

**Final pass (before Phase 3.4 commit)**: run the full verification command for every
affected package, not just the last changed file. List packages with
`python3 ./.trellis/scripts/get_context.py --mode packages`.

#### 2.3 Rollback `[on demand]`

- Verification reveals a PRD defect → return to Phase 1, fix `prd.md`, then redo 2.1
- Implementation went wrong → revert code, redo 2.1
- Need more research → research (same as Phase 1.2), write findings into `research/`

---

## Phase 3: Finish

Goal: ensure code quality, capture lessons, record the work.

#### 3.2 Debug retrospective `[on demand]`

If this task involved repeated debugging (the same issue was fixed multiple times), load the `trellis-break-loop` skill to:
- Classify the root cause
- Explain why earlier fixes failed
- Propose prevention

The goal is to capture debugging lessons so the same class of issue doesn't recur.

#### 3.3 Spec update `[optional · once]`

If this task produced durable team knowledge — a new convention, a repeated pitfall, or a
non-obvious technical decision — load the `trellis-update-spec` skill and record it under
`.trellis/spec/`. Skip this step when the work was routine or task-local.

Specs remain useful in Native AI mode: they are the conventions the main session reads
before writing code, not sub-agent-only context.

#### 3.4 Commit changes `[required · once]`

**Spec-sync preamble**: before drafting commits, ask: did this task fix a bug or surface non-obvious knowledge that should land in `.trellis/spec/` so future-you (or future-AI) doesn't repeat the mistake? If yes, return to Phase 3.3 first — spec writes belong in the same task's commit batch, not as a forgotten follow-up.

The AI drives a batched commit of this task's code changes so `/finish-work` can run cleanly afterwards. Goal: produce work commits FIRST, then bookkeeping (archive + journal) commits land after — never interleaved.

**Step-by-step**:

1. **Inspect dirty state**:
   ```bash
   git status --porcelain
   ```
   Snapshot every dirty path. If the working tree is clean, skip to 3.5.

2. **Learn commit style** from recent history (so drafted messages blend in):
   ```bash
   git log --oneline -5
   ```
   Note the prefix convention (`feat:` / `fix:` / `chore:` / `docs:` ...), language (中文/English), and length style.

3. **Classify dirty files into two groups**:
   - **AI-edited this session** — files you wrote/edited via Edit/Write/Bash tool calls in this session. You know what changed and why.
   - **Unrecognized** — dirty files you did NOT touch this session (could be the user's manual edits, leftover WIP from a previous session, or unrelated work). Do NOT silently include these.

4. **Draft a commit plan**. Group AI-edited files into logical commits (1 commit per coherent change unit, not 1 commit per file). Each entry: `<commit message>` + file list. List unrecognized files separately at the bottom.

5. **Present the plan once, ask for one-shot confirmation**. Format:
   ```
   Proposed commits (in order):
     1. <message>
        - <file>
        - <file>
     2. <message>
        - <file>

   Unrecognized dirty files (NOT in any commit — confirm include/exclude):
     - <file>
     - <file>

   Reply 'ok' / '行' to execute. Reply with edits, or '我自己来' / 'manual' to abort.
   ```

6. **On confirmation**: run `git add <files>` + `git commit -m "<msg>"` for each batch in order. Do not amend. Do not push.

7. **On rejection** (user replies "不行" / "我自己来" / "manual" / any pushback on the plan): stop. Do not attempt a second plan. The user will commit by hand; you skip ahead to 3.5 once they confirm.

**Rules**:
- No `git commit --amend` anywhere — three-stage three-commit flow (work commits → archive commit → journal commit).
- Never push to remote in this step.
- If the user wants different message wording but accepts the file grouping, edit the message and re-confirm once — but if they reject the grouping, exit to manual mode.
- The batched plan is one prompt; do not prompt per commit.

#### 3.5 Wrap-up reminder

After the above, remind the user they can optionally run `/finish-work` to archive the task and record the session. In Native AI mode this is bookkeeping, not a completion gate.

---

## Customizing Trellis (for forks)

This section is for developers who want to modify the Trellis workflow itself. All customization is done by editing this file; the scripts are parsers only.

### Changing what a step means

Edit the corresponding step's walkthrough body in the Phase 1 / 2 / 3 sections above. Critical invariants:
- No active task must triage first and ask for task-creation consent before creating a Trellis task.
- Native AI mode: planning produces `prd.md` + `design.md`; `implement.md` and JSONL manifests are not created unless the user explicitly asks.
- Every required execution path must keep the Phase 3.4 commit reminder reachable before `/trellis:finish-work`.

All tag blocks live in the `## Phase Index` section above, immediately after each phase summary:

| Scope | Corresponding tag |
|---|---|
| No active task (before Phase 1) | `[workflow-state:no_task]` (after the Phase Index ASCII art) |
| Active task record unreadable | `[workflow-state:task_error]` (repair the existing task before continuing) |
| All of Phase 1 (task created → ready for implementation) | `[workflow-state:planning]` (after Phase 1 summary) |
| Codex inline Phase 1 | `[workflow-state:planning-inline]` |
| Phase 2 + Phase 3.2–3.4 (implementation + check + wrap-up) | `[workflow-state:in_progress]` (after Phase 2 summary) |
| Codex inline Phase 2 + Phase 3.2–3.4 | `[workflow-state:in_progress-inline]` |
| After Phase 3.5 (archived) | `[workflow-state:completed]` (after Phase 3 summary; **currently DEAD**) |

### Changing the per-turn prompt text

Directly edit the body of the corresponding `[workflow-state:STATUS]` block. After editing, run `trellis update` (if you're a template maintainer) or restart your AI session (if you're customizing your own project) — no script changes required.

### Adding a custom status

Add a new block:

```
[workflow-state:my-status]
your per-turn prompt text
[/workflow-state:my-status]
```

Constraints:
- STATUS charset: `[A-Za-z0-9_-]+` (underscores and hyphens allowed, e.g. `in-review`, `blocked-by-team`)
- A lifecycle hook must write `task.json.status` to your custom value, otherwise the tag is never read
- Lifecycle hooks live in `task.json.hooks.after_*` and bind to one of `after_create / after_start / after_finish / after_archive`

### Adding a lifecycle hook

Add a `hooks` field to your `task.json`:

```json
{
  "hooks": {
    "after_finish": [
      "your-script-or-command-here"
    ]
  }
}
```

Supported events: `after_create / after_start / after_finish / after_archive`. Note that `after_finish` ≠ a status change (it only clears the active-task pointer); use `after_archive` for "task is done" notifications.

### Full contract

For the workflow state machine's runtime contract, the locations of all status writers, pseudo-statuses (`no_task` / `stale_<source_type>`), the hook reachability matrix, and other deep details, see:

- `.trellis/spec/cli/backend/workflow-state-contract.md` — runtime contract + writer table + test invariants
- `.trellis/scripts/inject-workflow-state.py` — actual parser (reads workflow.md only, no embedded text)
