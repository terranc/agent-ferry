# ferry

对 Grok Bot 说一句话，让你 Mac 上的编程助手帮你写程序。

可以选择 **Claude Code、Codex、Grok Build、Pi Agent、Kimi Code**。你在聊天里提出需求，所选工具在自己的 Mac 上干活；完成后由 Bot 把结果带回同一段对话。想再改一点，就接着说，不用重新解释整个项目。

## 可以这样用

> 在我的 Mac 上，用 Claude Code 写一个 Hello World 程序，运行一下，完成后告诉我。

> 继续刚才的任务，把输出改成中文。

> 这次用 Codex，帮我给这个程序加几个测试。

> 用 Kimi Code 帮我做一个简单的待办清单。

> 这次用 opus，帮我看看这个项目为什么启动不了。

ferry 帮你连接 Grok Bot 和这些本机工具，使用电脑上已有的登录。未指定工具时默认 Claude Code，继续任务时沿用上次的工具。

## 开始使用

先准备好：

- 一台能被 Grok Bot 访问的 Mac。
- Mac 上已经安装并登录你想用的编程工具，不需要五种都安装。
- 一个你平时使用的 Grok Bot。

把下面这段话发给 Bot：

> 请安装并配置 ferry：
> https://github.com/terranc/agent-ferry/tree/master/skills/ferry
>
> 按安装引导把我的 Mac 接入，配置好完成通知，并记住：以后我让你在 Mac 上用 Claude Code、Codex、Grok、Pi 或 Kimi 写程序、修 bug 或继续任务时，都通过 ferry 执行。
>
> 配置完成后，帮我写并运行一个 Hello World，确认结果能回到当前对话。

Bot 会引导你完成必要的确认。安装完成后，直接像上面的例子一样说需求即可，不用每次提 ferry，也不用记命令。

## 做到一半，也能继续聊

- **接着改**：说“继续刚才的任务”，沿用之前的对话。
- **换个模型**：说“这次用 sonnet”或“这次用 opus”。
- **选择工具**：说“用 Codex 做这个任务”或“用 Pi Agent 写这个程序”。不同工具的会话分开保存，不能把一个工具的会话交给另一个续接。
- **取消任务**：告诉 Bot 停止当前任务。
- **回到电脑前接手**：让 Bot 给你打开同一个工具会话的命令。

同一个任务需要等上一轮结束后再追加发言。遇到需要审批的操作，Bot 应先把操作内容告诉你，等你明确允许或拒绝。不同工具可能询问得更频繁，不能为减少询问而自动批准。

## 使用前了解一下

目前支持 macOS。执行期间，Mac 需要保持开机和联网；合盖或断电会影响任务与通知。所选工具的使用仍受你现有账户的额度或计费规则约束。

项目仍在早期测试中。五种工具都已通过本机真实启动、续聊和拒绝越界写入测试；Grok Bot 自动回传和跨对话调用仍需联调。请先用一个独立的小项目试用。

<details>
<summary>手动安装、命令行与开发测试</summary>

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
  ~/.local/bin/ferry run --owner local-test --cwd "$HOME/www/测试项目" --model sonnet

~/.local/bin/ferry status '<run_id>' --full
~/.local/bin/ferry sessions
```

工作目录必须是 `~/www` 下已经存在的项目目录。续接时给 `run` 加上 `--session '<session_id>'`。通知尚未配置时，通过 `status` 查询结果。
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
