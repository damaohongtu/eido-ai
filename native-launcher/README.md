# Eido OpenCode Native Launcher

一次性 Chrome Native Messaging Host。它只检测 OpenCode、打开 macOS 项目目录选择器、在用户选定的父目录下创建项目文件夹并启动 `opencode serve`；不监听本机端口，不代理聊天，也不接收网页、Prompt、附件或项目文件内容。

macOS 启动分为两段：Native Messaging 进程写入一次性 LaunchAgent 配置并通过 `launchctl bootstrap` 注册，由 `launchd` 拉起同一个已签名 launcher 的 helper 模式，helper 校验请求后启动 OpenCode。LaunchAgent 配置在注册后立即删除，任务结束时自动卸载。使用标准 LaunchAgent 可以切断 Chrome 的 `LSFileQuarantineEnabled` 责任链，避免 Bun 运行时解压的随机 `.dylib` 被标记成 Chrome 下载文件；`launchctl submit` 不能稳定切断这条责任链，因此不用于此路径。请求只存在于当前用户 `~/Library/Application Support/Eido/run`（目录 `0700`）中的随机 `0600` 文件，helper 打开后立即删除，再从内存设置工作区、回环端口与 Basic Auth 环境变量。

协议 `create_directory` 只接受不含路径分隔符的单段文件夹名；父目录必须由用户在系统选择器中显式确认，Launcher 不接受前端直接指定任意创建目标路径。

## 普通用户安装

正式发布产物为 Apple Developer ID 签名并公证的 universal macOS `.pkg`，同时支持 Intel 与 Apple Silicon。用户从插件“我的设置 -> 本机 -> 安装启动组件”下载安装包，双击后按 macOS Installer 向导完成安装，不需要使用命令行。

安装器写入：

```text
/Library/Application Support/Eido/bin/eido-opencode-launcher
/Library/Google/Chrome/NativeMessagingHosts/ai.eido.opencode_launcher.json
```

安装完成后需要重新打开 Chrome。Installer 会清理当前登录用户可能残留的开发版 Host 注册，避免用户级 Manifest 覆盖系统正式版本；不会停止任何已运行的 OpenCode 进程。

OpenCode 仍需单独安装。Launcher 不下载、安装或升级 OpenCode。

## 自动发布

GitHub Actions 工作流 [`.github/workflows/native-launcher-macos-release.yml`](../.github/workflows/native-launcher-macos-release.yml) 完成以下操作：

1. 运行 Go 单元测试。
2. 构建 `darwin/amd64` 与 `darwin/arm64`，合成为 universal 二进制。
3. 使用 Developer ID Application 对 Launcher 启用 hardened runtime 签名。
4. 使用 Developer ID Installer 签名图形安装包。
5. 提交 Apple Notary service，等待通过后 staple 公证票据。
6. 验证签名、架构、安装路径、扩展 ID 和 Manifest。
7. 上传版本化产物与稳定名称 `Eido-OpenCode-Launcher-macOS.pkg`。
8. `native-launcher-v*` 标签会自动创建或更新 GitHub Release 资产。

仓库需要配置以下 Actions Secrets：

| Secret | 内容 |
| --- | --- |
| `EIDO_CHROME_EXTENSION_ID` | Eido Chrome Web Store 正式扩展的固定 32 位 ID |
| `SMARTBROWSER_CHROME_EXTENSION_ID` | SmartBrowser Chrome Web Store 正式扩展的固定 32 位 ID |
| `MACOS_DEVELOPER_ID_APPLICATION_P12_BASE64` | Developer ID Application 证书与私钥的 Base64 P12 |
| `MACOS_DEVELOPER_ID_INSTALLER_P12_BASE64` | Developer ID Installer 证书与私钥的 Base64 P12 |
| `MACOS_CERTIFICATE_PASSWORD` | 两个 P12 的导出密码 |
| `MACOS_KEYCHAIN_PASSWORD` | CI 临时 Keychain 密码 |
| `MACOS_DEVELOPER_ID_APPLICATION` | 完整 Application 签名身份名称 |
| `MACOS_DEVELOPER_ID_INSTALLER` | 完整 Installer 签名身份名称 |
| `APPLE_ID` | Apple Developer 账号 |
| `APPLE_TEAM_ID` | Apple Developer Team ID |
| `APPLE_APP_PASSWORD` | Apple ID app-specific password |

推荐使用版本标签发布：

```text
native-launcher-v0.1.4
```

也可以从 Actions 页面手工运行工作流并填写数字版本及两个扩展 ID。正式包把每个调用方都写成精确来源；Native Messaging 不允许通配符来源。

同一个安装包、同一个 `ai.eido.opencode_launcher` host 可以同时服务 Eido 和 SmartBrowser。Launcher 的进程、协议和安装路径没有分叉，只有 `allowed_origins` 同时列出两个发布扩展的固定 ID。

## 本地验证安装包

发布工程师可以显式生成未签名测试包。该模式只用于检查 Installer 内容，不能分发给普通用户：

```bash
GO_BINARY=/path/to/go \
  ./installers/macos/build-package.sh \
  --extension-id EIDO_EXTENSION_ID \
  --extension-id SMARTBROWSER_EXTENSION_ID \
  --version 0.1.4 \
  --unsigned
```

默认构建模式要求签名和公证配置，缺少凭据时会直接失败。需要调试签名但暂不提交公证时，可使用 `--skip-notarization`。

已生成的包可再次验证：

```bash
./installers/macos/verify-package.sh \
  dist/Eido-OpenCode-Launcher-0.1.4.pkg \
  --extension-id EIDO_EXTENSION_ID \
  --extension-id SMARTBROWSER_EXTENSION_ID \
  --require-signed
```

## 开发测试

需要 Go 1.22 或更高版本：

```bash
go test ./...
go build ./cmd/eido-opencode-launcher
```

## macOS 开发安装

从 `chrome://extensions` 复制已加载开发版插件的 32 位 ID，然后执行：

```bash
./installers/macos/install-dev.sh EIDO_EXTENSION_ID SMARTBROWSER_EXTENSION_ID
```

也可以只传当前正在调试的一个 ID；单 ID 调用保持兼容。开发脚本将 Launcher 安装到当前用户目录，并生成只允许所传开发扩展 ID 调用的 Host Manifest。它与正式 `.pkg` 分发相互独立，仅供开发调试。修改授权列表后，需从 `chrome://extensions` 重载扩展。

Launcher 的 stdout 仅用于 Native Messaging 长度前缀 JSON。OpenCode 的 stdout/stderr 写入 `~/Library/Logs/Eido/opencode-<port>.log`。
