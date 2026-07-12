# Eido OpenCode Native Launcher

一次性 Chrome Native Messaging Host。它只检测 OpenCode、打开 macOS 项目目录选择器并启动 `opencode serve`；不监听本机端口，不代理聊天，也不接收网页、Prompt、附件或项目文件内容。

## 开发测试

需要 Go 1.22 或更高版本：

```bash
go test ./...
go build ./cmd/eido-opencode-launcher
```

## macOS 开发安装

从 `chrome://extensions` 复制已加载开发版插件的 32 位 ID，然后执行：

```bash
./installers/macos/install-dev.sh EXTENSION_ID
```

脚本将 Launcher 安装到用户目录，并生成只允许该扩展 ID 调用的 Native Host Manifest。该脚本仅用于开发；普通用户版本应通过签名、公证的图形安装器完成相同注册，不要求用户使用命令行。

Launcher 的 stdout 仅用于 Native Messaging 长度前缀 JSON。OpenCode 的 stdout/stderr 写入 `~/Library/Logs/Eido/opencode-<port>.log`。
