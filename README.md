# ferry

对 Grok Bot 说一句话，让你 Mac 上的 Claude Code 帮你写程序。

你可以在聊天里提出需求，让 Claude Code 在自己的电脑上干活；完成后由 Bot 把结果带回同一段对话。想再改一点，就接着说，不用重新解释整个项目。

## 可以这样用

> 在我的 Mac 上，用 Claude Code 写一个 Hello World 程序，运行一下，完成后告诉我。

> 继续刚才的任务，把输出改成中文。

> 这次用 opus，帮我看看这个项目为什么启动不了。

ferry 帮你连接 Grok Bot 和本机 Claude Code。Claude Code 在你的 Mac 上处理项目，使用电脑上已有的登录。

## 开始使用

先准备好：

- 一台能被 Grok Bot 访问的 Mac。
- Mac 上已经安装并登录 Claude Code。
- 一个你平时使用的 Grok Bot。

把下面这段话发给 Bot：

> 请安装并配置 ferry：
> https://github.com/terranc/agent-ferry/tree/master/skills/ferry
>
> 按安装引导把我的 Mac 接入，配置好完成通知，并记住：以后我让你在 Mac 上用 Claude Code 写程序、修 bug 或继续任务时，都通过 ferry 执行。
>
> 配置完成后，帮我写并运行一个 Hello World，确认结果能回到当前对话。

Bot 会引导你完成必要的确认。安装完成后，直接像上面的例子一样说需求即可，不用每次提 ferry，也不用记命令。

## 做到一半，也能继续聊

- **接着改**：说“继续刚才的任务”，沿用之前的对话。
- **换个模型**：说“这次用 sonnet”或“这次用 opus”。
- **取消任务**：告诉 Bot 停止当前任务。
- **回到电脑前接手**：让 Bot 给你打开同一段 Claude Code 会话的命令。

同一个任务需要等上一轮结束后再追加发言。遇到需要审批的操作，Bot 应先把操作内容告诉你，等你明确允许或拒绝。

## 使用前了解一下

目前支持 macOS。执行期间，Mac 需要保持开机和联网；合盖或断电会影响任务与通知。Claude Code 的使用仍受你现有账户的额度或计费规则约束。

项目仍在早期测试中。本地发言、续接和指定模型已得到使用反馈；Grok Bot 自动回传、跨对话调用及真实审批流程还在联调。请先用一个独立的小项目试用。

<details>
<summary>手动安装、命令行与开发测试</summary>

本机需要 Python 3.9+。在下载的项目目录中执行：

```sh
./install.sh
~/.local/bin/ferry doctor
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

自动化测试使用隔离的临时目录和模拟程序，不会调用真实 Claude 或生产通知地址；运行测试需要本机进程查询权限。

</details>

完成通知使用 [eze-is/eze-grokbot 的 wake-on-done](https://github.com/eze-is/eze-grokbot/tree/main/wake-on-done)。原文件与来源记录保留在仓库中，许可现状见 [UPSTREAM.md](skills/UPSTREAM.md)。
