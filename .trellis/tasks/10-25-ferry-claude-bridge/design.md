# Design: ferry

> 对应 `prd.md` 的 R1–R7。外部事实见 `research/`；标「S#」的条目由 `implement.md` 第 0 步的 spike 验证。

## 1. 架构与边界

```
Grok Bot（在线）──Machine Shell──► ferry run …        立即返回 {run_id, session_id}
                                     │ 以新会话分离启动
                                     ▼
                   notify-run --owner <bot> --task ferry:<run_id> --log <run>/notify.log --
                     └─ ferry _exec <run_id>
                          ├─ caffeinate -i -w <claude pid>          （R5.3）
                          └─ claude -p …  cwd=<工作目录>  env: FERRY_RUN_ID
                               └─ PermissionRequest hook ─► ferry hook-permission   阻塞 ≤ 6h（R4）
                                                              ├─ 写审批请求文件
                                                              ├─ POST 审批通知 → 中继 Bot → 唤醒 Bot
                                                              └─ 轮询决定文件
Grok Bot ──Machine Shell──► ferry status / approve / cancel / sessions
```

- **没有常驻进程，也没有网络服务端。** 进程之间只通过 `~/.local/state/agent-ferry/` 下的文件通信。
- ferry **不修改**用户的 `~/.claude/settings.json`。所有策略都通过每次运行时的 `--settings` 注入，所以卸载时只需删掉 ferry 自己的文件。
- 职责边界：ferry 不判断意图，也不决定续接哪个会话还是新开一个。它只执行 Bot 给出的参数。

## 2. 技术选型与取舍

| 决策 | 选择 | 理由 / 放弃的方案 |
|---|---|---|
| 执行方式 | `claude -p --output-format json` | 用户已定。每轮结束进程即退出，正好对上 notify-run "命令结束即通知"的模型。放弃 Agent SDK、交互式 TUI 和 herdr |
| 审批接入 | `PermissionRequest` **command** hook | 不需要 HTTP 服务端。hook 进程本身就是那个"挂起的请求"。放弃 HTTP hook 和 `--permission-prompt-tool`，两者都需要常驻服务 |
| 进程间通信 | 文件 + `O_EXCL` 原子创建 | 个人单机规模足够，靠"首个写入者胜出"化解答复与超时之间的竞争。放弃 SQLite 和本地 socket |
| 结果回传 | 复用 wake-on-done 的 notify-run 与中继 | 已经解决"回到原对话"。ferry 只补一个审批通知的发送函数，复用同一份 url.env |
| 语言 | Python 3，只用标准库 | notify-run 本身已依赖 python3，不新增依赖。JSON 解析、进程组、`O_EXCL` 都由标准库直接支持。放弃 bash（JSON 处理脆弱）和 Node（新增运行时） |
| prompt 传递 | 写入 claude 的 stdin 后关闭（S7） | 避开 shell 引号和以 `-` 开头被当成参数的问题（R1.4）。备选：放到 `--` 之后作为位置参数 |
| `waiting_approval` 状态 | 读取时推导，不落盘 | 避免 hook 和 `_exec` 同时写 meta 产生竞争 |

## 3. 文件与配置布局

```
~/.local/share/agent-ferry/        安装后的代码（install.sh 复制，不用软链接，见 §9）
~/.local/bin/ferry                 入口
~/.config/agent-ferry/config.json
~/.config/agent-ferry/claude-settings.json
~/.local/state/agent-ferry/        权限 0700
  runs/<run_id>/meta.json          运行元数据（含 prompt，权限 0600）
  runs/<run_id>/claude.json        claude 的 stdout，即 json 结果
  runs/<run_id>/claude.stderr.log
  runs/<run_id>/notify.log         notify-run 的 --log，内容是 _exec 的 stdout/stderr
  approvals/<approval_id>.json           审批请求（hook 写入，此后不再修改）
  approvals/<approval_id>.decision.json  决定（O_EXCL 创建，先到先得）
  sessions/<session_id>.lock       内容为 run_id
```

`config.json`（由 install.sh 生成；缺失的字段用默认值）：

```json
{
  "workspace_root": "~/www",
  "approval_timeout_seconds": 21600,
  "retention_days": 7,
  "result_max_chars": 4000,
  "claude_bin": "claude"
}
```

`claude-settings.json`（install.sh 按 config 渲染）：

```json
{
  "permissions": {
    "ask": [
      "Bash(git push*)", "Bash(sudo *)",
      "Bash(npm install -g *)", "Bash(npm i -g *)", "Bash(pnpm add -g *)", "Bash(yarn global add *)",
      "Bash(brew install *)", "Bash(pip install --user *)", "Bash(pip3 install --user *)",
      "Bash(pipx install *)", "Bash(uv tool install *)", "Bash(cargo install *)", "Bash(go install *)",
      "Bash(git reset --hard*)", "Bash(git clean *)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "autoAllowBashIfSandboxed": true,
    "network": { "allowedDomains": ["*"] }
  },
  "hooks": {
    "PermissionRequest": [
      { "matcher": "*",
        "hooks": [ { "type": "command", "command": "<HOME>/.local/bin/ferry",
                     "args": ["hook-permission"], "timeout": 21660 } ] }
    ]
  }
}
```

- hook 的 `timeout` 设为审批超时加 60 秒。这样总是 ferry 自己先判定超时并给出 deny，不会撞上 Claude 取消 hook。
- 普通的 `pip install`（不在 venv 里）会写入 cwd 之外的 site-packages。这类操作由沙盒拦下，再进入审批，所以 ask 规则只需要列出必定是全局写入的写法。
- `allowedDomains: ["*"]` 待 S6 验证。如果不成立，退而列出常用的包源和代码托管域名。这会让 R3.6 退化，需要在 doctor 和 SKILL.md 里写明。

## 4. CLI 契约

所有子命令都向 stdout 输出**一个 JSON 对象**。成功时带 `"ok": true`。失败时输出 `{"ok": false, "error": {"code", "message"}}`，退出码为 2。

| 命令 | 作用 |
|---|---|
| `ferry run --owner <bot_id> --cwd <dir> [--session <uuid>] [--prompt-file <f>]` | 校验参数并启动 run。prompt 从 `--prompt-file` 读取；没有该参数时从 stdin 读取，此时 stdin 不能是 TTY |
| `ferry status <run_id> [--full]` | 查看状态。`result` 默认截断到 `result_max_chars`，`--full` 返回全文 |
| `ferry approvals [--run <run_id>]` | 列出待审批项 |
| `ferry approve <approval_id> allow\|deny [--note <text>]` | 提交决定 |
| `ferry cancel <run_id>` | 取消 run |
| `ferry sessions [--cwd <dir>]` | 列出会话和 resume 命令，按最后活跃时间倒序 |
| `ferry doctor` | 自检 |
| `ferry _exec <run_id>`、`ferry hook-permission` | 内部命令，不写进 SKILL.md |

`run` 的输出示例：

```json
{"ok": true, "run_id": "r_20261025-101500_a1b2c3", "session_id": "3f2c…", "new_session": true,
 "status": "starting", "notify": "wake-on-done",
 "next": "收到 ferry:<run_id> 通知后执行 ferry status <run_id>"}
```

wake-on-done 未就绪时，`notify` 的值为 `"none"`，同时附带 `warning` 字段（R2.3）。

`status` 的输出示例：

```json
{"ok": true, "run_id": "…", "status": "waiting_approval", "session_id": "…", "cwd": "/Users/terranc/www/app",
 "started_at": "…", "ended_at": null,
 "result": null, "result_truncated": false, "cost_usd": null, "num_turns": null,
 "pending_approvals": [
   {"approval_id": "a_9f…", "kind": "file_write", "tool": "Write",
    "summary": "写入 /Users/terranc/.zshrc", "detail": "<完整路径或命令，最多 2000 字符>",
    "expires_at": "…"}],
 "resume_cmd": "cd '/Users/terranc/www/app' && claude --resume 3f2c…"}
```

错误码：`INVALID_CWD`、`INVALID_SESSION_ID`、`SESSION_BUSY`、`EMPTY_PROMPT`、`NOT_FOUND`、`ALREADY_ANSWERED`、`APPROVAL_EXPIRED`、`RUN_NOT_ACTIVE`、`CLAUDE_NOT_FOUND`。

## 5. 运行流程

### 5.1 `ferry run`
1. **校验 cwd**（R3.7）：对 `realpath(cwd)` 和 `realpath(workspace_root)` 做比较，必须严格位于后者之下，且是一个已存在的目录。否则返回 `INVALID_CWD`。
2. **校验 session**：`--session` 必须是 UUID。没有该参数时生成 uuid4，并标记 `new_session`。
3. **读取 prompt**：为空则返回 `EMPTY_PROMPT`。
4. **加 session 锁**（R5.1）：用 `O_EXCL` 创建 `sessions/<id>.lock`。如果锁已存在，读出其中的 run_id：
   - 该 run 仍然存活：返回 `SESSION_BUSY`；
   - 该 run 已不存活：视为陈旧锁，删除后重试一次。
5. **写入元数据**：`meta.json` 记录 run_id、session_id、new_session、cwd、owner、prompt、created_at，状态为 `starting`。
6. **清理旧 run**：删除超过 `retention_days` 的 run 目录（R5.5）。
7. **分离启动**：用 `start_new_session=True`、stdin 指向 `/dev/null` 启动以下命令，并把进程组 ID 记进 meta：
   - `notify-run --owner <owner> --task ferry:<run_id> --log runs/<id>/notify.log -- ferry _exec <run_id>`；
   - 如果 notify-run 或 url.env 缺失，就直接启动 `ferry _exec <run_id>`（R2.3）。
8. **输出** run JSON 后立即退出（AC1）。

### 5.2 `ferry _exec`
1. 状态改为 `running`，记录自身 pid。
2. 组装 argv（argv 数组，不经过 shell）：
   ```
   claude -p --output-format json --permission-mode acceptEdits
          --settings ~/.config/agent-ferry/claude-settings.json
          --disallowedTools AskUserQuestion
          (--session-id <id> | --resume <id>)
   ```
   - 子进程 cwd 设为工作目录，环境变量加上 `FERRY_RUN_ID=<run_id>`（S2）。
   - prompt 写入 stdin 后关闭（S7）。
   - stdout 写入 `claude.json`，stderr 写入 `claude.stderr.log`。
3. 启动 `caffeinate -i -w <claude pid>`。claude 进程退出时，这个断言会自动释放。
4. 等待 claude 退出，然后解析 `claude.json`，从中取出 `result`、`session_id`、`is_error`、`total_cost_usd`、`num_turns`。最终状态的判定：
   - 退出码为 0 且 `is_error` 不为真：`completed`；
   - 收到 SIGTERM：`cancelled`；
   - 其他情况：`failed`，并记录 stderr 的末尾部分。
5. 写入终态、`ended_at` 和结果摘要；释放 session 锁（只删除内容等于自己 run_id 的锁）。
6. **向 stdout 打印一行摘要**，这一行会成为 notify-run 通知里的 `output_tail`：
   `ferry <run_id> <status> session=<id> | <result 去掉换行后的前 180 字>`
7. 退出码：`completed` 为 0，其余为非 0，对应 notify-run 的 succeeded / failed。
8. SIGTERM 处理：先向 claude 进程组转发信号，再把本 run 所有待审批项写成 `cancelled` 决定，然后走第 5–7 步。

### 5.3 `ferry status` 的推导规则
- meta 中的状态不是终态，但 `_exec` 的 pid 已不存活（用 `ps -p <pid> -o command=` 核对，命令行中必须含 `_exec <run_id>`，以防 pid 被复用）：报告为 `interrupted`（R5.4）。
- 状态为 `running`，且存在没有决定、未过期、hook 进程仍存活的审批请求：报告为 `waiting_approval`。

## 6. 审批（R4）

### 6.1 `ferry hook-permission`（由 Claude 调用，stdin 是 hook 输入的 JSON）
1. 从环境变量读取 `FERRY_RUN_ID`。如果没有这个变量，说明 hook 被别的会话误用了：立即输出 deny 并退出。ferry 的 settings 只通过 `--settings` 注入，正常情况下不会发生。
2. 根据 `tool_name` 和 `tool_input` 生成摘要：
   - Edit / Write / NotebookEdit：`kind=file_write`，`summary="写入 <file_path>"`；
   - Bash：`kind=command`，`summary="执行 <command 前 200 字>"`，detail 里附上完整命令和 description；
   - 其他工具：`kind=other`，摘要为工具名加截断后的输入。
3. 写入 `approvals/<a_id>.json`，内容包括 run_id、hook pid、摘要、created_at、expires_at。
4. **发送审批通知**：读取 url.env，按 notify-run 的通知格式 POST，最多重试 3 次。
   - 字段：`task="ferry-approval:<a_id>"`，`status="waiting_approval"`，`exit_code=0`，`log_path=<请求文件路径>`，`output_tail="<run_id> 需要审批：<summary>"`。
   - 发送失败只记日志，不影响继续等待。Bot 仍可通过 `ferry status` 看到这条待审批项（S9）。
5. 每 2 秒检查一次是否出现 `decision.json`，直到 `expires_at` 为止：
   - 读到 `allowed`：输出 `{"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}`；
   - 读到 `denied`、`cancelled`：输出 `behavior: "deny"`，并在 `message` 字段写明原因和备注；
   - 到期：用 `O_EXCL` 写入 `expired` 决定。写入失败说明决定刚好已经到了，就以已有的决定为准。然后输出 deny。
6. **兜底**：任何未捕获的异常都输出 deny，退出码为 0（R4.5）。即使脚本彻底崩溃、什么都没输出，Claude 也会因为没有拿到决定而拒绝（fail closed）。
7. 只返回单次允许，不带 `updatedPermissions`，也就不会产生"以后都允许"的规则（R3.3）。

### 6.2 `ferry approve`
依次校验：请求存在；决定尚不存在；没有过期；hook 进程仍存活，否则返回 `RUN_NOT_ACTIVE`。然后用 `O_EXCL` 创建决定文件，内容为 `{decision, note, answered_at}`。创建失败，说明已经有了决定，返回 `ALREADY_ANSWERED` 并附上已有的决定（R4.3）。

### 6.3 审批状态机
```
pending ──approve──► allowed | denied
   │──超时────────► expired
   │──cancel──────► cancelled
   └──hook 进程消失（读取时推导）──► interrupted
```
答复、超时、取消三方的竞争，统一由"决定文件只能用 `O_EXCL` 创建一次"来裁决。

## 7. 取消（R5.2）
`ferry cancel <run_id>`：如果 run 不是活跃状态，返回 `RUN_NOT_ACTIVE`。否则向 meta 中记录的进程组发送 SIGTERM。
- notify-run 捕获 TERM 后，以退出码 130 发出通知。
- `_exec` 按 §5.2 第 8 步的流程收尾。

5 秒后如果仍有进程存活，再发送 SIGKILL。

## 8. 会话列表（R6）
`ferry sessions` 扫描所有 `runs/*/meta.json`，按 session_id 聚合出：cwd、首条 prompt 的前 60 字、最近一个 run 的时间和状态、是否有正在执行的 run、`resume_cmd`。
- 这是 debt：每次都全量扫描 run 目录，run 数量上万时会变慢，到时改为维护一个 sessions 索引文件。
- Bot 续接用户在 Mac 上手动创建的会话时（R6.2），ferry 不检查这个会话是否存在，由 `claude --resume` 自己报错。

## 9. 安全与已知风险

- **信任边界**：Bot 拥有 shell 权限，所以 ferry 的校验只约束 Claude，不约束 Bot（见 PRD 的 Constraints）。
- **防止自改**：代码装在 `~/.local/share` 下，配置放在 `~/.config` 下，两者都在 `~/www` 之外。即使 Bot 在 `~/www/agent-ferry` 里让 Claude 干活，Claude 要改已安装的 ferry 或策略文件，也必须经过审批。
- **用户 settings 的干扰**（S8，由 doctor 检查）：
  - 用户 settings 里如果也有 `PermissionRequest` hook，会和 ferry 的 hook 抢着给出决定；
  - 用户 settings 里宽泛的 `Bash` allow 规则，会让匹配命令的沙盒外重试免审批，从而绕过 R3.4。

  doctor 发现这两类配置时都要给出警告。
- **项目内配置**：Claude 可以改 cwd 下的 `.claude/settings*.json`。这类改动只在下一次会话生效，而且属于受保护路径，应该会触发审批（S5 一并验证）。
- **数据保护**：state 目录权限 0700，meta 文件 0600；通知里的摘要不超过 300 字。
- **已知上限**：命令文本匹配拦不住脚本内部的危险操作；合盖睡眠期间无法审批。

## 10. 测试策略

- **单元和集成测试**：用 `unittest` 加一个假的 claude（`tests/fake_claude.py`，通过 `config.claude_bin` 注入）。桩程序按 prompt 里的标记模拟各种行为：
  - 直接成功；
  - 以非零码失败；
  - 长时间运行；
  - 用 PermissionRequest 格式的输入调用 `ferry hook-permission`，再按返回的决定写或不写文件。

  这些场景覆盖 AC22 列出的全部逻辑。测试时用临时的 `HOME` / `XDG_*` 目录隔离，绝不碰真实的 state。
- **真实 E2E**：在 `~/www/ferry-e2e/` 下用真 claude 逐条跑 AC1–AC21，费用很低。通知相关的验收（AC4、S9）需要先装好 wake-on-done。

## 11. 安装、升级与回滚

- `install.sh`：
  1. 把仓库里的 `ferry/` 和 `bin/ferry` 复制到 `~/.local/share/agent-ferry`；
  2. 在 `~/.local/bin/ferry` 放一个指向那里的入口；
  3. 渲染 config 和 claude-settings；
  4. 运行 `ferry doctor`。

  重复执行不会出问题，可以直接当升级用。
- `uninstall.sh`：删除上面这几个位置，state 目录是否保留由参数决定。用户的 `~/.claude` 从未被改动，所以回滚就是删除文件。
- SKILL.md 由用户交给 Grok Bot 安装。安装方式与 wake-on-done 相同：发给 Bot，或放进 Bot 可读取的 skills 目录。
