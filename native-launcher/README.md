# Eido OpenCode Native Launcher

一次性 Chrome Native Messaging Host，支持 macOS 与 Windows。它只检测 OpenCode、打开系统项目目录选择器、在用户选定的父目录下创建项目文件夹并启动 `opencode serve`；不监听本机端口，不代理聊天，也不接收网页、Prompt、附件或项目文件内容。

macOS 启动分为两段：Native Messaging 进程写入一次性 LaunchAgent 配置并通过 `launchctl bootstrap` 注册，由 `launchd` 拉起同一个已签名 launcher 的 helper 模式，helper 校验请求后启动 OpenCode。LaunchAgent 配置在注册后立即删除，任务结束时自动卸载。使用标准 LaunchAgent 可以切断 Chrome 的 `LSFileQuarantineEnabled` 责任链，避免 Bun 运行时解压的随机 `.dylib` 被标记成 Chrome 下载文件；`launchctl submit` 不能稳定切断这条责任链，因此不用于此路径。请求只存在于当前用户 `~/Library/Application Support/Eido/run`（目录 `0700`）中的随机 `0600` 文件，helper 打开后立即删除，再从内存设置工作区、回环端口与 Basic Auth 环境变量。

协议 `create_directory` 只接受不含路径分隔符的单段文件夹名；父目录必须由用户在系统选择器中显式确认，Launcher 不接受前端直接指定任意创建目标路径。

## macOS 普通用户安装

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

## Windows 普通用户安装

插件会根据浏览器提供的 CPU 架构信息下载稳定名称 `Eido-OpenCode-Launcher-Windows.exe`（x64）或 `Eido-OpenCode-Launcher-Windows-arm64.exe`。无法识别架构时使用 Windows on Arm 也可兼容运行的 x64 版本。安装器为当前用户安装，不要求管理员权限，写入：

```text
%LOCALAPPDATA%\Eido\bin\eido-opencode-launcher.exe
%LOCALAPPDATA%\Eido\ai.eido.opencode_launcher.json
HKCU\Software\Google\Chrome\NativeMessagingHosts\ai.eido.opencode_launcher
```

Windows Launcher 本体也包含图形化的当前用户安装/修复入口。用户直接双击时会显示安装确认和完成提示；Chrome 以 Native Messaging 参数和管道启动同一个文件时不会显示安装界面，而是执行一次请求后退出。发布构建必须使用 `-H windowsgui`，避免双击或 Chrome 调用时出现控制台窗口。

安装完成后需要完全退出并重新打开 Chrome。OpenCode 仍需单独安装；Launcher 会检查 `PATH`、`%USERPROFILE%\.opencode\bin\opencode.exe`、npm 全局包中的原生 Windows 二进制和 WinGet Links。Scoop、Chocolatey 与 Mise 的可执行 shim 可通过 `PATH` 检出；Launcher 不会通过 shell 执行 npm 的 `.cmd` 包装器。

自动唤起需要 Windows 原生 `opencode.exe`。仅安装在 WSL 内的 OpenCode 不在 Windows Launcher 的进程与路径边界内；这种情况下仍可在 WSL 手工启动服务后，通过插件连接其回环地址。

Windows 使用系统文件夹选择器。启动 OpenCode 时使用独立进程组与 detached process flags，且不继承 Native Messaging 的 stdin/stdout；日志写入 `%LOCALAPPDATA%\Eido\logs`。

自动发布工作流 [`.github/workflows/native-launcher-windows-release.yml`](../.github/workflows/native-launcher-windows-release.yml) 会构建并签名 x64、arm64 两种安装器，上传版本化产物，并把 x64 版本复制为插件使用的稳定下载名称。仓库需要额外配置：

| Secret | 内容 |
| --- | --- |
| `WINDOWS_CODE_SIGNING_PFX_BASE64` | Windows Authenticode 代码签名证书与私钥的 Base64 PFX |
| `WINDOWS_CODE_SIGNING_PASSWORD` | PFX 密码 |

发布工作流还会复用 `EIDO_CHROME_EXTENSION_ID` 与 `SMARTBROWSER_CHROME_EXTENSION_ID`。同一个 `native-launcher-v*` 标签会同时触发 macOS 与 Windows 发布；两个工作流安全地合并资产到同一个 GitHub Release。

## Windows 本地验证安装器

在安装了 Go 1.22+ 与 Inno Setup 6 的 Windows 环境中运行：

```powershell
$ids = @("EIDO_EXTENSION_ID", "SMARTBROWSER_EXTENSION_ID")
.\installers\windows\build-installer.ps1 `
  -ExtensionId $ids `
  -Version 0.1.4 `
  -Architecture amd64 `
  -Unsigned
```

构建结果位于 `dist\Eido-OpenCode-Launcher-0.1.4-Windows-x64.exe`。`--unsigned` 对应 PowerShell 的 `-Unsigned`，只用于本地和 CI 验证，不应分发给普通用户。

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

## Windows 开发安装

在 PowerShell 中传入一个或多个开发版插件 ID：

```powershell
$ids = @("EIDO_EXTENSION_ID", "SMARTBROWSER_EXTENSION_ID")
.\installers\windows\install-dev.ps1 -ExtensionId $ids
```

卸载开发版注册：

```powershell
.\installers\windows\uninstall-dev.ps1
```

安装或卸载后都应完全退出并重新打开 Chrome。Windows 上 OpenCode 的 stdout/stderr 写入 `%LOCALAPPDATA%\Eido\logs\opencode-<port>.log`。
