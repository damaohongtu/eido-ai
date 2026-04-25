# Eido

面向多种应用场景的 AI 智能体平台，通过 Claude Code SDK 实现自主规划与执行复杂任务，支持多技能串联与多轮对话协作。

## 特性

- **自主规划执行**：基于 Claude Code SDK，AI 自主拆解任务、调用工具、多轮迭代直至完成
- **技能系统**：通过 SKILL.md 定义技能，支持工具白名单、自然语言指引，无需编码即可扩展
- **多 LLM 支持**：兼容 DeepSeek、MiniMax 等 Anthropic API 兼容服务
- **开箱即用**：Docker 一键部署，支持 amd64 / arm64 多架构

详见 [quick-start.md](quick-start.md)


## TODO
- [x] 结果文件要能够下载
- [x] 添加plugin
- [ ] 多模态数据支持
- [x] 历史消息存储：文件或者数据库
- [x] sandbox 支持：基于沙盒机制，将不同的用户在物理上进行隔离（gateway + per-user 容器，详见 docs/architecture.md §7）
- [ ] 沙盒文件目录树：用户能够查看自己沙盒中的文件 
- [ ] 核心对话完善