# 安装 ferry：一次配置，之后自然语言调用

仅在用户要求安装、配置或修复 ferry 接入时读取。日常执行按 `../SKILL.md`。
本引导负责把现有组件接起来；通知中继的详细流程由同仓库的 wake-on-done 提供。

## 1. 安装完整 skill 并选定 Mac

- 将本仓库 `skills/ferry/` 和 `skills/wake-on-done/` 两个完整目录放入 Grok Bot 的 skill 库，保留脚本执行权限和相邻目录布局，让 skill 的 name/description 可以被自动发现。
- 确认 Machine Shell 能访问用户选定的 Mac。只有一台 Mac 时直接使用；无法判断目标机器时再询问。平台没有机器访问能力时说明缺少的连接，不宣称已安装。
- 记录本次任务所在机器。命令里的 `--owner` 使用当前发起任务的 Bot 自己的真实 ID，不用中继 Bot ID、显示名或示例占位符。

完成标准：两个 skill 的正文和 references 可读取，目标 Mac 可通过 Machine Shell 执行命令。

## 2. 检查 Mac 上的 ferry

在目标 Mac 执行 `~/.local/bin/ferry doctor`。已有 CLI 时先复用；需要安装或升级时，检查本机项目目录（通常是 `~/www/agent-ferry`），在该仓库运行 `./install.sh`，然后重新检查。

不要把在线 Bot skill 库里的文件路径直接当成 Mac 路径。本仓库地址为 `https://github.com/terranc/agent-ferry.git`；本机没有源码时，可通过 Machine Shell 克隆到 `~/www/agent-ferry` 后运行安装。若该目录已有内容，先核对来源与当前改动，不覆盖或强制重置；确实无法判断源码位置时再询问用户。

逐项报告 doctor 结果。Claude/python/workspace/caffeinate 缺失时解决对应前置条件；用户 settings 有审批冲突时展示警告并说明影响，不擅自改用户 settings。

完成标准：ferry CLI 在目标 Mac 可执行，基础环境检查通过，已告知任何权限配置冲突。

## 3. 配置 wake-on-done

读取 [wake-on-done 安装流程](../../wake-on-done/references/setup.md)。本 Bot 按其 Main bot part 创建或复用中继 Bot；中继按 Relay part 配置 webhook 并把这台 Mac 接入。已完成的配置复用，不重复创建中继。

用户需要的卡片批准和密钥输入，按上游引导交给用户办理。密钥使用平台的安全输入与文件传递，不能放在普通聊天、命令行、日志或长期记忆里。不要因为当前机器缺配置，就替换其他机器或现有中继。

通知安装测试的成功标准以引导为准，不能只看脚本打印“已发送”。通知必须实际到达并唤醒目标 Bot；其安装测试故意使用非零退出码，不代表安装失败。

完成标准：目标 Mac 的安装测试通知被实际收到，`ferry doctor` 的 wake-on-done 项通过。仍不可用时明确报告，日常任务可以继续使用 status 查询，不能承诺自动回传。

## 4. 保存长期调用规则

用平台提供的用户长期记忆能力保存下面这条规则（支持时使用 `UpdateMemory` 的 user/profile），并读回核实。已有等价规则时更新或复用，保留其他无关偏好。

> 在已配置 ferry 的 Mac 上，用户要求用 Claude Code 写程序、修 bug 或继续任务时，自动加载 ferry skill 并通过 ferry 执行，用户无需提及 ferry。每轮 owner 使用当前 Bot 自己的 ID。ferry 自带 wake-on-done 通知，不再外包 notify-run。每个风险操作都先征求用户对本次审批的明确答复，Bot 不自行批准。用户明确指定其他方式时遵从用户选择。

保留 wake-on-done 对其他长任务的使用规则；上面这条是 Mac Claude Code 的具体路由规则。它不把 Codex、其他机器或普通问答改成 ferry。

如果平台只能保存当前 Bot 的长期指令，就将规则保存到那里，并说明只对该 Bot 生效。如果只有当前聊天上下文可用，明确说“当前对话可用，跨对话路由尚未配置”，不能用口头承诺代替持久化。

完成标准：可读回持久规则，skill 的 name/description 已登记。不要在长期记忆里存 run_id、prompt、密钥或其他 Bot 的 owner ID。

## 5. 验收并交接

用用户指定的测试任务验证；没有指定时，在 `~/www/ferry-e2e` 创建一个独立的 Hello World 测试。通过 ferry 调用真实 Claude Code，`--owner` 为本 Bot ID。记录 run_id/session_id，核对文件或运行结果，并等待完成通知回到原对话。需要验证远端命令返回后的存活时，让测试任务先等待约 30 秒。

Mac Machine Shell 可能回收后台进程；上游 wake-on-done 用 tmux 保活。ferry 本身的分离启动是否能在该远端环境存活也必须以此次测试为准。若返回后 run 立刻变成 interrupted，保留 status 和日志排查，不绕过 ferry 直接运行 Claude，也不要把这样的结果报成接入成功。

配置完成后，向用户分别报告：CLI、完成通知、长期路由、审批通知的验证状态。审批通知与完成通知分开验收，未实测的就标未验证。

让用户在新对话里只说“在我的 Mac 上用 Claude Code 写一个 Hello World”，验证 Bot 能自动选中 ferry；再说“继续刚才的任务”，验证续接同一 session。新对话行为尚未实测时明确注明。
