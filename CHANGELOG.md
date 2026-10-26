# 更新记录

## [0.1.0] - 2026-10-26

首个公开版本：在 Grok Bot 里提出需求，让 Mac 上的编程工具执行任务。

### Added

- 支持 Claude Code、Codex、Grok Build、Pi Agent、Kimi Code，默认使用 Claude Code。
- 支持选择模型、续接原生会话、后台执行、查询结果、取消任务，以及回到本机接手。
- 统一逐次审批：允许或拒绝只对本次操作生效；超时和通道异常时拒绝。
- 接入 wake-on-done 完成与审批通知，并提供 Grok Bot skill、安装引导和长期调用规则。
- 提供安装、卸载、环境自检、会话列表和中断任务回收。
- Grok 使用每轮独立审批配置，Pi 使用显式工具调用门禁。

### 验证与使用范围

- 64 项自动化测试通过；五种工具均通过本机真实启动、同会话续聊和拒绝项目外写入测试。
- 当前支持 macOS；Linux、WSL2 和原生 Windows 尚未支持。
- Grok Bot 完成/审批通知、远程后台存活和跨对话自动路由仍需真实联调。
- 所选工具须已在 Mac 上安装并登录。基础运行需要 Python 3.9+，Grok Build 需要 Python 3.11+。
- 已验证版本：Claude Code 2.1.310、Codex 0.164.0、Grok Build 1.0.70、Pi Agent 1.4.0、Kimi Code 2.1.1。
- 新增工具可能询问更多审批。Grok 已有用户 requirements.toml 时拒绝启动，需评估策略兼容性；Codex 的整轮权限扩展会被拒绝。
- 第三方 wake-on-done 保留原始来源和许可状态说明，见 [UPSTREAM.md](skills/UPSTREAM.md)。

安装与使用见 [README](README.md)。已有用户更新本机 CLI 后，还需更新 Grok Bot 中的完整 ferry skill。

[0.1.0]: https://github.com/terranc/agent-ferry/releases/tag/v0.1.0
