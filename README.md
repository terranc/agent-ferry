# Agent Ferry

对 Grok Bot 说一句话，让你 Mac 上的编程助手帮你写程序。

可以选择 **Claude Code、Codex、Grok Build、Pi Agent、Kimi Code**。你在聊天里提出需求，所选工具在自己的 Mac 上干活；完成后由 Bot 把结果带回同一段对话。想再改一点，就接着说，不用重新解释整个项目。

## 快速接入

先准备好：Mac 已接到 Grok Bot，并能执行命令（本机执行 / Machine Shell）；至少一种编程工具已安装并登录。项目放在工作区根目录下已有的文件夹里，不要用根目录本身。根目录可以改，当前值用 `ferry doctor` 看，配置见文末命令行。

用你现在的 Grok Bot，或单独用一个专门跑这条通道的 Bot（自行创建，或使用已有的同类 Bot）。本仓库没有公开模板地址。把下面这段话发给负责安装的那个 Bot。细节见 [安装引导](skills/ferry/references/setup.md)，日常调用见 [ferry skill](skills/ferry/SKILL.md)。

> 请安装并配置 ferry。只保存 SKILL.md 不算装好。
> 仓库：https://github.com/terranc/agent-ferry
>
> 把 `skills/ferry/` 和 `skills/wake-on-done/` 两个完整目录装进当前 Bot，references 和 scripts 都要在，脚本保持可执行。
> 在已连接的 Mac 上任选目录，克隆或更新本仓库（例如 `~/agent-ferry`）。目录里已有内容时先核对来源，不要覆盖或强制重置。然后运行 `./install.sh` 和 `~/.local/bin/ferry doctor`。
> 配好 wake-on-done 中继，让完成和审批通知唤醒当前这个 Bot。每一轮 `--owner` 用当前 Bot 自己的 id，不用中继的 id，也不用显示名。
> 把长期路由记下来并读回核对：以后我在这台 Mac 上用 Claude Code、Codex、Grok Build、Pi 或 Kimi 写程序、修 bug 或继续任务时，自动通过 ferry 执行。我不用说 ferry。未指定工具时默认 Claude Code；继续时沿用原来的工具和会话，不能混用。
> 分别说明命令行、完成通知、长期路由、审批通知是否已经验证。没跑通的标成未验证。

装好后直接说需求即可，不必每次提到 ferry。想试一句可以换一个新对话，这不是必做步骤。

## 日常怎么说

> 在我的 Mac 上，用 Claude Code 看看这个项目为什么启动不了。

> 继续刚才的任务，把输出改成中文。

> 这次用 Codex，帮我补几个测试。

> 这次用 opus。

未指定工具时默认 Claude Code。“继续”沿用上次的工具和会话。“opus”只换模型。

## Grok Bot 接入最佳实践

命令以 [ferry skill](skills/ferry/SKILL.md) 为准。

- `ferry run` 外面不要再包 `notify-run`、`nohup` 或 `&`。后台和通知由 ferry 接 wake-on-done。
- 返回里 `notify` 为 `none` 时，说明通知不可用，并改查 `ferry status`。
- 审批给出 `approval_id`、路径或命令、`summary`、`detail` 和到期时间，等当前对话里对这一次明确允许或拒绝。Bot 不自行批准。默认最多等 6 小时，到期按拒绝。
- 多行需求写入 UTF-8 文件，用 `--prompt-file` 或 stdin 传入，不要拼进 shell。
- 聊天记录和长期记忆里不存 webhook 密钥、API key，或其他 Bot 的 owner id。
- 聊天里的 Grok Bot 不是 `ferry --agent grok`。后者是 Mac 上的 Grok Build。云端 Claude Code（ccx）和云端 Pi（pix）不走 ferry。

## 做到一半，也能继续

- **接着改**：说“继续刚才的任务”。
- **换模型**：说“这次用 sonnet”或“这次用 opus”。
- **换工具**：说“用 Codex 做这个任务”或“用 Pi Agent 写这个程序”。会话不能交给另一个工具续接。
- **取消**：告诉 Bot 停止当前任务。
- **回到电脑前接手**：让 Bot 给出打开同一个工具会话的命令。

同一会话等上一轮结束再追加。需要审批时，按上一节对这一次单独确认。

## 使用前了解一下

目前支持 macOS。执行期间 Mac 需要开机、联网；合盖、睡眠或断网会停掉任务和通知。ferry 只能在办得到的时候阻止空闲睡眠。所选工具仍按你现有账户的额度或计费规则计算。

项目仍在早期测试中。五种工具都已通过本机真实启动、续聊和拒绝越界写入测试。Grok Bot 的完成/审批回传、新对话自动选中和跨对话续接仍需联调。

<details>
<summary>手动安装、命令行与开发测试</summary>

本机需要 Python 3.9+；使用 Grok Build 时需要 Python 3.11+。已验证的版本：Claude Code 2.1.310、Codex 0.164.0、Grok Build 1.0.70、Pi Agent 1.4.0、Kimi Code 2.1.1。新增工具的更旧版本会被拒绝。在克隆下来的仓库目录中执行：

```sh
./install.sh
~/.local/bin/ferry doctor
~/.local/bin/ferry doctor --agent all
```

也可以直接在终端发起任务：

```sh
printf '%s\n' '<这一轮要做的事>' |
  ~/.local/bin/ferry run --owner local-test --cwd "$HOME/<你的工作区>/<你的项目>" --model sonnet

~/.local/bin/ferry status '<run_id>' --full
~/.local/bin/ferry sessions
```

`<你的工作区>` 是配置里的工作区根目录，`<你的项目>` 是它下面已经存在的项目文件夹。不能把根目录本身当成工作目录。默认根目录可以改：未设置 `XDG_CONFIG_HOME` 时，编辑 `~/.config/agent-ferry/config.json` 的 `workspace_root`。当前值用 `ferry doctor` 看。续接时加上 `--session '<session_id>'`。通知尚未配置时，用 `status` 查询。
选择工具时加 `--agent claude|codex|grok|pi|kimi`。模型参数按所选工具填写。新工具的会话 ID 可能稍后才有，先留 run_id。不要混用不同工具的 session_id。

Grok Build 每轮使用独立审批配置，不改用户配置。已有 `~/.grok/requirements.toml` 时会拒绝启动，需先看策略是否兼容，不要为了通过检查删掉原策略。

卸载：

```sh
./uninstall.sh --keep-state  # 保留任务记录
./uninstall.sh               # 同时删除任务记录
```

开发测试：

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q ferry tests
sh -n install.sh uninstall.sh
git diff --check
```

完整测试需要 Python 3.11+。自动化测试使用隔离的临时目录和模拟程序，不会调用真实模型或生产通知地址；运行测试需要本机进程查询权限。

</details>

完成通知使用 [eze-is/eze-grokbot 的 wake-on-done](https://github.com/eze-is/eze-grokbot/tree/main/wake-on-done)。原文件与来源记录保留在仓库中，许可现状见 [UPSTREAM.md](skills/UPSTREAM.md)。
