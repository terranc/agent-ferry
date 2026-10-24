# Grok Bot 驱动本机 Claude Code 的执行通道 ferry

## Goal

用户在 Grok Bot 里提出软件需求或报 bug，Grok Bot 让 Mac 上的 Claude Code 在指定项目目录里干活。一轮结束后，结果自动回到原来那段 Grok Bot 对话里。用户再说话时，Bot 可以在同一个 Claude 会话里继续。途中如果 Claude 要做有风险的操作，先问用户，用户在 Grok Bot 里答复后 Claude 再继续。用户回到电脑前，可以找到这些会话并在终端里接着聊。

## Background

- Grok Bot 是在线服务，通过 Machine Shell 在用户 Mac 上执行命令，所以能直接调用本机 CLI，不需要 MCP 服务或公网 Tunnel。
- "把结果送回 Bot 原对话"借用 wake-on-done：`notify-run` 包住命令，命令结束后通过中继 Bot 唤醒发起任务的 Bot。详见 `research/wake-on-done.md`。
- Claude Code 走 `claude -p` 非交互模式，审批通过 `PermissionRequest` hook 接入。详见 `research/claude-code-headless.md`。
- 职责划分：
  - **Grok Bot**：理解意图、决定续接哪个会话还是新开一个、和用户对话。
  - **ferry**：执行任务、执行权限策略、把审批挂起并等待答复。

## Requirements

### R1 发起与续接
- R1.1 Bot 用一条命令发起任务，参数是工作目录、prompt，以及可选的 `session_id`。命令立即返回 `run_id` 和 `session_id`，Claude 在后台执行。
- R1.2 不传 `session_id` 就新开会话。传入时在该会话中续接，Claude 保留之前的上下文。
- R1.3 `session_id` 就是 Claude 的原生会话 ID，不另造映射。
- R1.4 prompt 支持多行和任意字符，避免因 shell 引号转义导致内容损坏。

### R2 结果回传
- R2.1 一轮结束时（成功、失败、取消都算），通过 wake-on-done 唤醒发起任务的 Bot。通知里带 run_id，以及状态和结果摘要。
- R2.2 Bot 用一条命令取回这一轮的完整状态：状态、最终回复、`session_id`、费用、待审批项、续接命令。
- R2.3 wake-on-done 未安装时 ferry 仍可使用：任务照常执行，命令输出中给出明确警告，Bot 改为主动查询状态。

### R3 权限策略
- R3.1 工作目录内的文件可以任意修改，不需要审批。
- R3.2 全盘文件可读，不需要审批。
- R3.3 修改工作目录外的文件，**每次**都需要审批。批准只对这一次操作生效，不会变成"以后都允许"。
- R3.4 普通命令由 Claude 自行决定是否执行。命令一旦要写入工作目录外，同样需要审批。
- R3.5 以下危险命令需要审批：`git push`（含 force）、`sudo`、全局安装（如 `npm i -g`、`brew install`、`pip install --user`）、`git reset --hard`、`git clean`。
- R3.6 命令联网不设限。
- R3.7 工作目录必须位于 `~/www` 之下，不能等于 `~/www` 本身，路径按 realpath 判断。不满足就拒绝，且不启动 Claude。

### R4 审批
- R4.1 需要审批时，Claude 挂起这次操作并等待。ferry 记录待审批项，然后通过同一中继唤醒 Bot。通知里写明要做什么：路径或完整命令，以及原因。
- R4.2 Bot 用一条命令提交 allow 或 deny。Claude 拿到结果后，从挂起处继续。
- R4.3 每个审批只有第一次答复生效。重复答复、答复已失效的审批，都返回明确错误。
- R4.4 最长等待 6 小时，超时按 deny 处理。
- R4.5 审批通道本身出错（脚本异常、超时）时一律按 deny 处理，绝不误放行。

### R5 运行管理
- R5.1 同一个 `session_id` 同时只允许一个 run 在执行，冲突时立即报错。
- R5.2 支持取消一个 run：Claude 停止，挂起的审批作废，并发出通知。
- R5.3 有 run 在执行或在等审批时，阻止 Mac 空闲睡眠。
- R5.4 Mac 重启或进程意外退出后，查询状态时把这类 run 标记为 `interrupted`，不留下"永远 running"的僵尸状态。
- R5.5 run 记录保留 7 天。

### R6 回到 Mac 接手
- R6.1 用一条本地命令列出 ferry 创建过的会话：目录、首条 prompt 摘要、最后活跃时间、是否正在执行，以及可以直接复制运行的 `cd <dir> && claude --resume <id>`。
- R6.2 Bot 也可以续接用户在 Mac 上手动创建的会话，只要传入它的 session_id。

### R7 交付给 Bot
- R7.1 提供一份 Grok Bot skill 文档（SKILL.md），说明以下内容：
  - 怎么发起任务、续接会话、查询状态；
  - 收到完成通知或审批通知后各自该做什么；
  - 审批必须由用户在对话里明确答复，Bot 不得自行批准。
- R7.2 提供 `doctor` 自检：Claude Code 版本、python3、wake-on-done 是否就绪、`~/www` 是否存在，以及用户 settings 里可能干扰审批的配置。

## Acceptance Criteria

- [ ] AC1（R1.1）`ferry run` 在 2 秒内返回 JSON，包含 `run_id` 和 `session_id`；此时后台已有 `claude -p` 进程在运行。
- [ ] AC2（R1.2）第一轮让 Claude 记住一个随机词，第二轮带上第一轮的 `session_id` 续接，Claude 能答出这个词。
- [ ] AC3（R1.4）prompt 包含多行、单引号、双引号、`$`、反引号时，传到 Claude 的内容与原文一致。
- [ ] AC4（R2.1）wake-on-done 已配置时，任务完成后 Bot 收到通知，`task` 字段含 run_id，`output_tail` 含状态和结果摘要。
- [ ] AC5（R2.2）`ferry status <run_id>` 返回 `completed`、最终回复、`session_id`，以及可执行的 resume 命令。
- [ ] AC6（R2.3）删掉 url.env 后，`ferry run` 仍能完成任务，输出里带警告，`ferry status` 能取回结果。
- [ ] AC7（R3.1）让 Claude 在工作目录内新建和修改文件，全程不产生审批，文件内容正确。
- [ ] AC8（R3.3/R4）让 Claude 写入 `~/www` 外的一个测试文件：
  - 产生一个待审批项，并发出审批通知；
  - 答复前该文件不存在；
  - `ferry approve <id> allow` 之后文件被写入；
  - 换一次测试，答复 `deny` 后文件始终不存在，Claude 的回复说明被拒。
- [ ] AC9（R3.4）让 Claude 用 shell 命令（如 `echo x > <目录外路径>`）写目录外文件，同样产生审批。
- [ ] AC10（R3.5）对清单里的每类危险命令，包括 `cd x && git push` 这类复合写法，都产生审批。测试用不会真正生效的目标，例如不存在的 remote。
- [ ] AC11（R3.6）在工作目录里执行 `npm install <一个小包>`，不产生审批且能成功。
- [ ] AC12（R3.7）`--cwd` 为 `~/www`、`~`、`/tmp`，或指向 `~/www` 外部的软链接时，`ferry run` 都报错退出，且没有启动 Claude。
- [ ] AC13（R4.3）同一个审批答复两次，第二次报错；对已超时或已取消的审批答复，也报错。
- [ ] AC14（R4.4）把超时调短（例如 60 秒）且不答复，到期按 deny 处理，Claude 继续执行并在回复中说明被拒。
- [ ] AC15（R4.5）让审批脚本异常退出（测试开关），结果是 deny 而不是放行。
- [ ] AC16（R5.1）同一个 session 的第一个 run 还在执行时，第二个 `ferry run --session <同一 id>` 立即报错。
- [ ] AC17（R5.2）`ferry cancel <run_id>` 之后：Claude 进程退出，挂起中的审批变为 cancelled，状态为 `cancelled`，并发出通知。
- [ ] AC18（R5.3）run 执行期间，`pmset -g assertions` 里能看到 ferry 持有的阻止空闲睡眠断言；run 结束后断言消失。
- [ ] AC19（R5.4）`kill -9` 掉 run 的进程后，`ferry status` 显示 `interrupted`，且该 session 可以重新发起 run。
- [ ] AC20（R6.1）`ferry sessions` 列出会话和 resume 命令；在终端执行该命令能打开同一会话并看到历史。
- [ ] AC21（R7）SKILL.md 涵盖 R7.1 列出的全部内容；`ferry doctor` 能逐项报告 R7.2 的检查结果。
- [ ] AC22 自动化测试（用假的 claude 桩程序）覆盖以下逻辑：cwd 校验、session 锁、审批状态机、超时、取消、僵尸 run 回收。全部通过。

## Out of Scope

- MCP 服务、公网 Tunnel、Webhook 签名服务端。
- herdr，以及任何终端或 TUI 托管方案。
- Claude Code 之外的 Agent（Codex、Grok CLI、Kimi 等）。
- 意图识别、会话轮换、上下文管理、跨 Agent 交接。
- 让会话出现在 Claude 的 `/resume` 选择列表里（官方行为不支持，由 R6 代替）。
- 实时进度流（Bot 只拿每一轮的最终结果）。
- 并发任务总数限制、多机器、Web 界面、Windows / Linux 支持。
- wake-on-done 本身的安装与中继 Bot 配置（前置条件，由用户通过 Grok Bot 完成）。

## Constraints & Assumptions

- 以用户本人账户运行，使用本机 Claude Code 的登录，会话保存在 `~/.claude` 下。
- **接受的风险**：Grok Bot 本身拥有 shell 权限，它可以绕过 ferry 直接改文件，也可以自行执行 `ferry approve`。审批只约束 Claude，不约束 Bot；"不得自行批准"靠 SKILL.md 的规则和对 Bot 的信任来保证。
- **已知上限**：危险命令按命令文本匹配。藏在脚本里的危险操作拦不住，例如 `npm run deploy` 内部执行 `git push`。其中写目录外文件的部分仍会被沙盒拦下。
- 合盖睡眠或断电期间无法收发审批，这不在 ferry 的控制范围内。
- 前置条件：用户通过 Grok Bot 完成 wake-on-done 的安装（中继 Bot + 本机 `notify-run`）。本机目前未安装。
