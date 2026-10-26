# 安装 ferry：一次配置，之后自然语言调用

仅在用户要求安装、配置或修复 ferry 接入时读取。日常执行按 `../SKILL.md`。
本引导是安装清单的依据。通知中继的详细流程由同仓库的 wake-on-done 提供。

按顺序做完下面五节：装完整 skill、在 Mac 上克隆或更新仓库并安装命令行、配好 wake-on-done、写入长期路由、分别报告验证状态。不要把 Hello World 或新建演示项目当成必做步骤。

## 1. 安装完整 skill 并选定 Mac

- 将本仓库 `skills/ferry/` 和 `skills/wake-on-done/` 两个完整目录放入 Grok Bot 的 skill 库，含 references 和 scripts，保留脚本执行权限和相邻目录布局，让 skill 的 name/description 可以被自动发现。只保存 SKILL.md 不算装好。
- 确认 Machine Shell 能访问用户选定的 Mac。只有一台 Mac 时直接使用；无法判断目标机器时再询问。平台没有机器访问能力时说明缺少的连接，不宣称已安装。
- 记录本次任务所在机器。命令里的 `--owner` 使用当前发起任务的 Bot 自己的真实 ID，不用中继 Bot ID、显示名或示例占位符。

完成标准：两个 skill 的正文和 references 可读取，目标 Mac 可通过 Machine Shell 执行命令。

## 2. 检查 Mac 上的 ferry

在目标 Mac 执行 `~/.local/bin/ferry doctor --agent all` 查看已安装工具。按用户选择检查 claude/codex/grok/pi/kimi；未选择的工具缺失不阻止其他工具使用。默认使用 Claude Code，用户指定其他工具时保留选择。已有 ferry CLI 时先复用。

需要安装或升级时，在这台 Mac 上任选一个目录，克隆或更新 `https://github.com/terranc/agent-ferry.git`（例如 `~/agent-ferry`）。目录里已有内容时先核对来源和现有改动，不覆盖或强制重置；确实无法判断源码位置时再询问用户。不要把在线 Bot skill 库里的文件路径直接当成 Mac 路径。在该仓库目录运行 `./install.sh`，然后运行 `~/.local/bin/ferry doctor`。

逐项报告 doctor 结果。所选编程工具、python、workspace、caffeinate 缺失时解决对应前置条件；用户配置有审批冲突时展示警告并说明影响，不擅自改用户设置。

工作目录必须是 ferry 已配置的工作区根目录下、已经存在的项目文件夹，不能是工作区根目录本身。默认根目录可以改。未设置 `XDG_CONFIG_HOME` 时，编辑 `~/.config/agent-ferry/config.json` 的 `workspace_root`。当前值看 `ferry doctor` 的 workspace_root 项。

基础运行需要 Python 3.9+，Grok Build 接入需要 Python 3.11+。已验证版本为 Claude Code 2.1.310、Codex 0.164.0、Grok Build 1.0.70、Pi Agent 1.4.0、Kimi Code 2.1.1；新增后端会拒绝更旧版本。Grok 的每轮独立审批配置不修改用户 config.toml；存在用户 requirements.toml 时会拒绝运行，需先评估策略兼容性，不能擅自删除原策略。

完成标准：ferry CLI 在目标 Mac 可执行，基础环境检查通过，已告知任何权限配置冲突。

## 3. 配置 wake-on-done

读取 [wake-on-done 安装流程](../../wake-on-done/references/setup.md)。本 Bot 按其 Main bot part 创建或复用中继 Bot；中继按 Relay part 配置 webhook 并把这台 Mac 接入。已完成的配置复用，不重复创建中继。中继可以共用。完成和审批通知要唤醒当前这个 Bot；每一轮 `--owner` 用当前 Bot 自己的 id，不用中继的 id，也不用显示名。

用户需要的卡片批准和密钥输入，按上游引导交给用户办理。密钥使用平台的安全输入与文件传递，不能放在普通聊天、命令行、日志或长期记忆里。不要因为当前机器缺配置，就替换其他机器或现有中继。

通知安装测试的成功标准以引导为准，不能只看脚本打印“已发送”。通知必须实际到达并唤醒目标 Bot；其安装测试故意使用非零退出码，不代表安装失败。

完成标准：目标 Mac 的安装测试通知被实际收到，`ferry doctor` 的 wake-on-done 项通过。仍不可用时明确报告，日常任务可以继续使用 status 查询，不能承诺自动回传。

## 4. 保存长期调用规则

用平台提供的用户长期记忆能力保存下面这条规则（支持时使用 `UpdateMemory` 的 user/profile），并读回核实。已有等价规则时更新或复用，保留其他无关偏好。

> 在已配置 ferry 的 Mac 上，用户要求用 Claude Code、Codex、Grok Build、Pi Agent 或 Kimi Code 写程序、修 bug 或继续任务时，自动加载 ferry skill 并通过 ferry 执行，用户无需提及 ferry。未指定工具时默认 Claude Code；继续任务时沿用原工具和原生会话，不能混用。每轮 owner 使用当前 Bot 自己的 ID，ferry 自带通知，不再外包 notify-run。风险操作等用户对本次审批明确答复，Bot 不自行批准。用户明确指定其他方式时遵从用户选择。

保留 wake-on-done 对其他长任务的使用规则；上面这条只针对 Mac 上这五种编程工具，不改变其他机器或普通问答的处理方式。

如果平台只能保存当前 Bot 的长期指令，就将规则保存到那里，并说明只对该 Bot 生效。如果只有当前聊天上下文可用，明确说“当前对话可用，跨对话路由尚未配置”，不能用口头承诺代替持久化。

完成标准：可读回持久规则，skill 的 name/description 已登记。不要在长期记忆里存 run_id、prompt、密钥或其他 Bot 的 owner ID。

## 5. 验收并交接

不要把 Hello World 或新建演示项目当成安装必做步骤。用户指定了验证任务时，用指定的工具和任务，通过 ferry 调用真实工具，`--owner` 为本 Bot 自己的 id。工作目录必须是工作区根目录下已经存在的项目文件夹。记录 agent、run_id、session_id。需要验证远端命令返回后是否仍存活时，让该任务先等待约 30 秒。用户没有指定验证任务时，不要擅自开项目或跑一轮编程任务。

Mac Machine Shell 可能回收后台进程；上游 wake-on-done 用 tmux 保活。只有在实际跑了一轮时，才用该轮判断 ferry 的分离启动能否在远端存活。若返回后 run 立刻变成 interrupted，保留 status 和日志排查，不绕过 ferry 直接运行 Claude，也不要把这样的结果报成接入成功。

配置完成后，向用户分别报告这四项是否已经验证：命令行、完成通知、长期路由、审批通知。审批通知与完成通知分开验收。没跑通的标成未验证，不要当成接入成功。

可选：用户愿意的话，让其在新对话里说一句很小的改动，看会不会自动走 ferry，再说“继续刚才的任务”，看能否续上同一 session。这不是必做步骤。新对话行为尚未实测时明确注明。
