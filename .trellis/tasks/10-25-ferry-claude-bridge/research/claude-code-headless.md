# Research: Claude Code 非交互模式（claude -p）相关事实

> 查证日期：2026-10-24 ~ 10-25。来源为 code.claude.com 官方文档，以及本机 `claude --help`（Claude Code 2.1.310）。
> 标「待 spike」的条目文档未写死，需要实测。

## CLI 参数（本机 `claude --help` 已确认存在）

- `-p/--print`、`--output-format json|stream-json`
- `--session-id <uuid>`：用指定 UUID 作为新会话 ID
- `--resume <id>`：按 ID 续接会话，可以跨目录找到会话
- `--permission-mode <mode>`：`default`(Manual) / `acceptEdits` / `auto` / `dontAsk` / `plan` / `bypassPermissions`
- `--settings <file-or-json>`：额外加载一份 settings
- `--setting-sources <sources>`：限定加载哪些 settings 来源
- `--permission-prompt-tool`、`--add-dir`、`--disallowedTools`

## 输出（headless 文档）

- `--output-format json` 的结果对象里有 `session_id`、`result`、`total_cost_usd`。
- 续接时报告的 cost 是整个会话的累计值。

## 会话与 /resume（sessions 文档）

- 用 `claude -p` 或 Agent SDK 创建的会话，**不会出现在 `/resume` 选择列表里**，也不会被 `claude --continue` 选中；只能用 `claude --resume <session-id>` 打开。
- 待 spike：在终端里交互式 `--resume` 过一次之后，这个会话会不会出现在列表里。

## 权限（headless / permission-modes 文档）

- v2.1.302 起，`claude -p` 在没有指定模式时以 Manual 模式启动。需要审批的调用会被**拒绝**，除非 `PermissionRequest` hook 或 `--permission-prompt-tool` 给出决定。
- `acceptEdits`：工作目录内的文件编辑不需要询问。目录外的编辑仍然需要审批。
- 规则优先级：deny > ask > allow。如果某条 allow 规则匹配一个命令，它同样会批准该命令的"沙盒外重试"，而且不提示。

## 沙盒（sandboxing 文档）

- macOS 上用 Seatbelt 实现。默认可写范围：cwd 及其子目录、`--add-dir` 加入的目录、`$TMPDIR`；默认可读范围：全盘，排除部分目录。
- 自动放行模式下，沙盒内的命令免审批运行。
- 命令在沙盒内失败时，Claude 可以带 `dangerouslyDisableSandbox` 重试。这次重试走常规权限流程。
- 网络：允许的域名列表初始为空。对不在列表里的主机，非 strict 模式下会弹出提示；`strictAllowlist: true` 时直接拒绝。
- 待 spike：`allowedDomains` 能否用通配符实现"完全放开"。注意 hooks 文档写明：**沙盒命令的网络请求提示不会触发 PermissionRequest hook**。也就是说在 `-p` 模式下，它可能被直接拒绝。

## Hooks（hooks 文档）

- `PermissionRequest`：在"即将向用户请求权限"时触发。无法展示提示的会话（例如 `-p`）同样会执行它；没有任何 hook 给出决定时，调用被拒绝。
  - 输出格式：`hookSpecificOutput.decision.behavior` 取 `allow` 或 `deny`。
  - 输入：`tool_name`、`tool_input`、可选的 `permission_suggestions`。
- `timeout`：单位是秒。`command` / `http` / `mcp_tool` 类型默认 600 秒，文档没有写上限。待 spike：21600 秒（6 小时）能否生效。
- HTTP hook 失败、超时、返回非 2xx 时，都算"非阻塞错误"，即没有给出决定。在 `PermissionRequest` 场景下，最终结果就是拒绝（fail closed）。
- 同一事件匹配到的多个 hook 并行执行，以最先给出决定的为准。用户 `~/.claude/settings.json` 里的 hook 也会参与。
- `Stop` hook 的输入里有 `last_assistant_message`。本方案不需要它：`-p` 每轮结束就退出，结果直接从 json 输出里取。

## 其他

- `-p` 模式下，`AskUserQuestion` 这类需要交互的工具无法正常工作。建议用 `--disallowedTools` 禁掉它，让 Claude 把问题写进最终回复。
- macOS 后台会话访问 `~/Desktop`、`~/Documents`、`~/Downloads` 需要单独授权。本项目的工作目录限定在 `~/www` 之下，不受影响。
