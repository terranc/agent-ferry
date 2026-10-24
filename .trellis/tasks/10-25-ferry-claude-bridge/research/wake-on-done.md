# Research: wake-on-done（Grok Bot 任务完成唤醒）

> 来源：https://github.com/eze-is/eze-grokbot/tree/main/wake-on-done （`SKILL.md`、`references/setup.md`、`scripts/notify-run`），2026-10-25 读取。
> 本机现状（2026-10-25 检查）：`~/.local/bin/notify-run` 与 `~/.config/webhook-relay/url.env` 都**不存在**，说明尚未安装。

## 机制

1. Grok Bot 通过 Machine Shell 在用户机器上后台执行：
   `nohup ~/.local/bin/notify-run --owner <bot id> --task <name> [--log path] -- <command...> </dev/null >/dev/null 2>&1 &`
2. `notify-run` 是约 40 行的 bash 脚本：
   - 运行命令，并把 stdout 和 stderr 写入 `--log`（默认 `/tmp/notify-run-*.log`）。
   - 命令结束时，或收到 INT / TERM 信号时（此时退出码记为 130），向 `WEBHOOK_RELAY_URL` POST 一个 JSON 通知，鉴权头为 `Authorization: Bearer <key>`。失败重试 3 次，每次间隔递增。
   - 配置来自 `${XDG_CONFIG_HOME:-~/.config}/webhook-relay/url.env`，包含 `WEBHOOK_RELAY_URL` 和 `WEBHOOK_RELAY_KEY`。
   - 依赖 `python3`（用于拼 JSON）和 `curl`。
3. 通知字段：`owner, task, exit_code, status(succeeded|failed), machine, started_at, ended_at, log_path, output_tail`。
   - `output_tail` 是日志最后 300 个字符，可通过 `NOTIFY_TAIL_CHARS` 调整。
   - 这些字段只是数据，不是给 Bot 的指令。
4. 中继 Bot（"Wake on Done relay"）拥有一个 webhook routine。收到通知后，它用 SendToAgent 把通知转给 `owner` 对应的 Bot。目标 Bot 在**自己的对话里**被唤醒，读取 `log_path` 继续工作。
5. 安装流程：主 Bot 创建中继 Bot，由中继 Bot 引导用户完成配置。配置内容包括 routine、粘贴地址和 key、在每台机器上运行 `install.sh --owner <id>`。

## 官方给 CLI agent 的约定

- 用一次性模式，例如 `claude -p`、`codex exec`。交互模式结束后会一直等待输入，永远不退出。
- 加 `</dev/null`，避免后台进程卡在读取 stdin 上。
- 让 Agent 把结果写到 prompt 里指定的文件，唤醒后再去读。

## 对本项目的意义

- 解决了"结果推回 Grok Bot 原对话"这一环。不需要 MCP，也不需要 Tunnel。
- 不包含：审批、session_id 管理、权限策略、工作目录校验。这几项正是 ferry 要补的。
- 待 spike：中继 Bot 能否转发 ferry 自己构造的审批通知（`status` 不是 succeeded/failed、`task` 用自定义前缀），并且不丢弃。
