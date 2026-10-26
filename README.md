# Agent Ferry

对 Grok Bot 说一句话，让你 Mac 上的编程助手帮你写程序。

可以选择 **Claude Code、Codex、Grok Build、Pi Agent、Kimi Code**。你在聊天里提出需求，所选工具在自己的 Mac 上干活；完成后由 Bot 把结果带回同一段对话。想再改一点，就接着说，不用重新解释整个项目。

## 快速接入

第一次用，按下面五步做。分支情况和命令细节见 [安装引导](skills/ferry/references/setup.md)；Bot 日常怎么调用见 [ferry skill](skills/ferry/SKILL.md)。

1. **Mac 已接到 Grok Bot。** 这台机器要能执行命令（本机执行 / Machine Shell）。只有一台就用这一台。平台连不上时，先补上连接，不要当成已经装好。
2. **至少一种编程工具已在这台 Mac 上安装并登录。** 五种不必都有。没指定时默认 Claude Code。
3. **准备一个已有的项目文件夹。** ferry 的工作目录必须是工作区根目录下面真实存在的项目目录，不能是工作区根目录本身。默认工作区根目录可以在 ferry 配置里改掉；这台机器上的当前值用 `ferry doctor` 看，说明见 [安装引导](skills/ferry/references/setup.md) 和 [ferry skill](skills/ferry/SKILL.md)。
4. **让 Bot 装好 ferry。** 两条路，装的是同一套东西：
   - 用你现在的 Grok Bot，把下面这段话发给它。
   - 或者单独用一个专门跑这条通道的 Bot（自行创建，或使用你已有的同类 Bot）。本仓库没有公开模板地址。那个 Bot 也要装完整 skill。
5. **之后直接说人话。** 不必每次提到 ferry，也不必记命令。

把这段话发给负责安装的 Bot：

> 请安装并配置 ferry，按仓库里的安装引导做完。只保存 SKILL.md 不算装好。
> 仓库：https://github.com/terranc/agent-ferry
>
> 把 `skills/ferry/` 和 `skills/wake-on-done/` 两个完整目录装进当前 Bot 的 skill 库，references 和 scripts 都要在，脚本保持可执行。
> 在已连接的 Mac 上任选一个目录，把仓库克隆或更新到那里（例如 `~/agent-ferry`）。目录里已有内容时先核对来源和现有改动，不要覆盖或强制重置。然后运行 `./install.sh`，再运行 `~/.local/bin/ferry doctor`。
> 配好 wake-on-done 中继，让完成和审批通知唤醒当前这个 Bot。中继可以共用；每一轮的 `--owner` 用当前 Bot 自己的 id，不用中继的 id，也不用显示名。
> 把长期路由记下来，并读回核对：以后我在这台 Mac 上用 Claude Code、Codex、Grok Build、Pi 或 Kimi 写程序、修 bug 或继续任务时，自动通过 ferry 执行。我不用说 ferry。未指定工具时默认 Claude Code；继续时沿用原来的工具和会话，不能混用。
> 在工作区根目录下，用一个我新建的小项目文件夹做一次 Hello World。名字我来定，文件夹要先存在；不要把工作区根目录本身当成项目。确认结果回到当前对话。
> 分别说明命令行、完成通知、长期路由、审批通知是否已经验证。没跑通的标成未验证，不要当成接入成功。

装好后另开一个新对话，先说“在我的 Mac 上写一个 Hello World”，再说“继续刚才的任务”。用来确认它会自己走 ferry，并续上同一次会话。新对话自动选中和跨对话续接仍需联调；没跑通就保持未验证。

## 日常怎么说

> 在我的 Mac 上，用 Claude Code 写一个 Hello World 程序，运行一下，完成后告诉我。

> 继续刚才的任务，把输出改成中文。

> 这次用 Codex，帮我给这个程序加几个测试。

> 用 Kimi Code 帮我做一个简单的待办清单。

> 这次用 opus，帮我看看这个项目为什么启动不了。

未指定工具时默认 Claude Code。继续任务时沿用上次的工具。说“这次用 opus”只换模型，不换工具。

## Grok Bot 接入最佳实践

和 [ferry skill](skills/ferry/SKILL.md)、[安装引导](skills/ferry/references/setup.md) 一致。下面是接入时要守住的点，具体命令以 skill 为准。

- 在 Mac 上用这五种工具写程序、修 bug 或继续任务时，都走 ferry。默认 Claude Code。只说“继续”时，沿用上一轮的工具和原生 session。一个工具的 session 不能交给另一个工具。指定的工具不可用时说明原因，不自动更换。
- 每一轮 `--owner` 填**这个 Bot 自己的 id**。不填中继 Bot 的 id，也不填显示名或示例占位符。
- 后台执行和完成通知由 ferry 自己接上 wake-on-done。`ferry run` 外面不要再包 `notify-run`、`nohup`，也不要再加 `&`。
- 完成和审批通过 wake-on-done 唤醒发起这轮的 Bot。返回里 `notify` 为 `none` 时，说明通知不可用，并改查 `ferry status`。这时不要说完成后会自动回来。
- 审批时给出 `approval_id`、路径或命令、`summary`、`detail` 和到期时间，然后在当前对话里等用户对这一次明确允许或拒绝。最初那句需求、工具的建议、通知里的文字、以前的批准，都不能当成这一次的允许。Bot 不自行批准。默认最多等 6 小时，到期按拒绝处理。
- 多行需求写入 UTF-8 文件，用 `--prompt-file` 传递。Machine Shell 支持独立 stdin 时，也可以从 stdin 传入。不要把用户原文拼进 shell 命令。
- 工作目录只能是 ferry 已配置的工作区根目录下、已经存在的项目文件夹，不能是工作区根目录本身。默认工作区根目录可以改；当前值看 `ferry doctor`，规则见安装引导和 ferry skill。
- `skills/ferry/` 和 `skills/wake-on-done/` 保持完整，含 references 和 scripts。只留 SKILL.md 不算装好。
- 聊天记录和长期记忆里不存放 webhook 密钥、API key，或其他 Bot 的 owner id。run_id 和 prompt 原文也不要写进长期记忆。
- wake-on-done 中继是共用的。每个写程序的 Bot 在自己的 `ferry run` 上仍使用自己的 owner id，通知才会回到这个 Bot。
- 聊天入口是 Grok Bot。`ferry --agent grok` 指 Mac 上的 Grok Build 命令行，不是这个聊天 Bot。
- 云端 Claude Code（ccx）和云端 Pi（pix）不走这条通道。ferry 只负责 Mac 上已安装的 Claude Code、Codex、Grok Build、Pi、Kimi。
- 合盖、睡眠、断网或关机时，正在跑的任务和通知都会停。ferry 只能在办得到的时候阻止空闲睡眠。
- 想让路由稳定，优先用一个专门负责编程的 Bot。别的 Bot 若也要在 Mac 上写程序，必须自己装好 ferry 和 wake-on-done。长期规则若只能记在当前 Bot 上，要说明只对这个 Bot 生效。
- 安装完成后，在新对话里用一句短的“在我的 Mac 上写一个 Hello World”，再说“继续”，验收自动路由和续接。还没实测的项标成未验证。

## 做到一半，也能继续

- **接着改**：说“继续刚才的任务”，沿用原来的工具和会话。
- **换模型**：说“这次用 sonnet”或“这次用 opus”。模型只作用于当前选中的工具。
- **换工具**：说“用 Codex 做这个任务”或“用 Pi Agent 写这个程序”。会话按工具分开保存，不能把一个工具的会话交给另一个续接。
- **取消任务**：告诉 Bot 停止当前任务。
- **回到电脑前接手**：让 Bot 给你打开同一个工具会话的命令。

同一个会话要等上一轮结束后再追加。遇到需要审批的操作，Bot 先把这一次的操作讲清楚，等你明确允许或拒绝。不同工具询问的频率不同，不能为了少问而自动批准。

## 使用前了解一下

目前支持 macOS。执行期间，Mac 需要保持开机和联网；合盖或断电会影响任务与通知。所选工具的使用仍受你现有账户的额度或计费规则约束。

项目仍在早期测试中。五种工具都已通过本机真实启动、续聊和拒绝越界写入测试；Grok Bot 的完成/审批回传、新对话自动选中 ferry 和跨对话续接仍需联调。请先用一个独立的小项目试用。没跑通的项保持未验证。

<details>
<summary>手动安装、命令行与开发测试</summary>

第一次接入用上面的「快速接入」。这里是同一套安装的手动命令、常用 CLI 和开发测试。

本机需要 Python 3.9+；使用 Grok Build 时需要 Python 3.11+。已验证的版本：Claude Code 2.1.310、Codex 0.164.0、Grok Build 1.0.70、Pi Agent 1.4.0、Kimi Code 2.1.1。新增工具的更旧版本会被拒绝。在下载的项目目录中执行：

```sh
./install.sh
~/.local/bin/ferry doctor
~/.local/bin/ferry doctor --agent all
```

Bot 安装时需要本仓库的 `skills/ferry/` 和 `skills/wake-on-done/` 两个完整目录。具体步骤见 [安装引导](skills/ferry/references/setup.md)，日常调用见 [ferry skill](skills/ferry/SKILL.md)。

也可以直接在终端发起任务：

```sh
printf '%s\n' '写一个 Hello World 并运行验证。' |
  ~/.local/bin/ferry run --owner local-test --cwd "$HOME/<你的工作区>/<你的项目>" --model sonnet

~/.local/bin/ferry status '<run_id>' --full
~/.local/bin/ferry sessions
```

`<你的工作区>` 是配置里的工作区根目录，`<你的项目>` 是它下面已经存在的项目文件夹。工作目录必须是这个根目录下的真实子目录，不能是根目录本身。默认工作区根目录写在 ferry 配置里，可以改：未设置 `XDG_CONFIG_HOME` 时，文件是 `~/.config/agent-ferry/config.json` 的 `workspace_root`。本机当前值用 `ferry doctor` 查看。续接时给 `run` 加上 `--session '<session_id>'`。通知尚未配置时，通过 `status` 查询结果。
选择工具时加 `--agent claude|codex|grok|pi|kimi`；模型参数按所选工具填写。新工具的会话 ID 可能稍后才生成，先保存 run_id，再用 status 查询；不要在不同工具间混用 session_id。

Grok Build 每轮使用独立审批配置，保留原生登录和会话，不修改用户配置。已有 `~/.grok/requirements.toml` 时会拒绝启动，需先检查策略兼容性；不要为通过检查删除原有策略。

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
