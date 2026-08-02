# Eido 浏览器扩展：Windows AD + Nginx 部署包

这个目录用于在不依赖 Google Admin、Chrome Web Store 和现有业务后端的情况下，通过 Windows AD/GPO 强制安装 Eido 扩展，并由 Nginx 静态托管更新清单和 CRX。

## 默认参数

| 项目 | 值 |
| --- | --- |
| 扩展 ID | `oggjajedgdgedecijokcknbbmfnpfjnc` |
| 策略值名称 | `1001` |
| Nginx 地址 | `192.168.127.32:60088` |
| 更新地址 | `http://192.168.127.32:60088/extensions/eido/update.xml` |
| 首个部署版本 | `0.1.7` |
| Nginx 静态根目录 | `/srv/eido-extension-root` |

Nginx 地址已经按实际环境固定为 `192.168.127.32:60088`。如果后续切换为内网域名，需要同时修改注册表、CRX manifest、`update.xml` 和客户端验证脚本。

## 目录结构

```text
eido-extension-windows-nginx/
├── README.md
├── nginx/
│   ├── eido-extension.conf
│   └── eido-extension-locations.conf
├── registry/
│   ├── install-eido-extension.reg
│   └── remove-eido-extension.reg
├── scripts/
│   └── verify-client.ps1
└── www/
    └── extensions/
        └── eido/
            ├── update.xml
            └── releases/
                └── 0.1.7/
                    └── eido-extension.crx
```

## 1. 验证内网地址

在一台域内 Windows 测试机确认 IP 和端口可达：

```powershell
Test-NetConnection 192.168.127.32 -Port 60088
```

## 2. 打包首个内网版本

更新地址是扩展包的一部分，因此首次部署应提升到一个新版本，例如 `0.1.7`，并继续使用原私钥：

```bash
cd /Users/mao/workspace/eido-ai/frontend-extension

EIDO_EXTENSION_UPDATE_URL='http://192.168.127.32:60088/extensions/eido/update.xml' \
EIDO_EXTENSION_PRIVATE_KEY='/Users/mao/workspace/eido-ai/frontend-extension/dist.pem' \
npm run pack:release
```

确认打包输出的扩展 ID 仍为：

```text
oggjajedgdgedecijokcknbbmfnpfjnc
```

将 CRX 放入：

```text
www/extensions/eido/releases/0.1.7/eido-extension.crx
```

部署包中已经包含使用原私钥生成的 `0.1.7` CRX。

## 3. 发布静态文件

在 Nginx 服务器上执行：

```bash
sudo install -d -m 0755 /srv/eido-extension-root/extensions/eido/releases/0.1.7
sudo install -m 0644 www/extensions/eido/update.xml \
  /srv/eido-extension-root/extensions/eido/update.xml
sudo install -m 0644 www/extensions/eido/releases/0.1.7/eido-extension.crx \
  /srv/eido-extension-root/extensions/eido/releases/0.1.7/eido-extension.crx
```

私钥 `dist.pem` 绝对不能上传到 Nginx 服务器。

## 4. 安装 Nginx 配置

如果使用独立虚拟主机：

```bash
sudo install -m 0644 nginx/eido-extension.conf \
  /etc/nginx/conf.d/eido-extension.conf
sudo nginx -t
sudo systemctl reload nginx
```

如果现有 Nginx 已经有监听 `60088` 的 `server`，不要再安装独立 `server` 配置。改为在现有 `server` 块中加入：

```nginx
include /etc/nginx/snippets/eido-extension-locations.conf;
```

并把 `nginx/eido-extension-locations.conf` 安装到上述路径。

## 5. 服务端验证

```bash
curl -i http://192.168.127.32:60088/healthz
curl -i 'http://192.168.127.32:60088/extensions/eido/update.xml?x=id%3Doggjajedgdgedecijokcknbbmfnpfjnc%26v%3D0.1.6'
curl -I http://192.168.127.32:60088/extensions/eido/releases/0.1.7/eido-extension.crx
```

预期：

- `/healthz` 返回 `200` 和 `{"status":"ok"}`。
- `update.xml` 返回 `Content-Type: application/xml`。
- CRX 返回 `Content-Type: application/x-chrome-extension`。
- 三个地址均不跳转到登录页，不要求 Cookie、CAS 或其他身份认证。

## 6. 部署 Windows 策略

`registry/install-eido-extension.reg` 可用于单台域内测试机验证。正式环境建议创建独立 GPO：

```text
Eido Browser Extension
```

在以下位置使用 Registry Preference 的 `Update` 操作：

```text
Computer Configuration
-> Preferences
-> Windows Settings
-> Registry
```

Chrome：

```text
Hive: HKEY_LOCAL_MACHINE
Key: SOFTWARE\Policies\Google\Chrome\ExtensionInstallForcelist
Value name: 1001
Value type: REG_SZ
Value data: oggjajedgdgedecijokcknbbmfnpfjnc;http://192.168.127.32:60088/extensions/eido/update.xml
```

Edge：

```text
Hive: HKEY_LOCAL_MACHINE
Key: SOFTWARE\Policies\Microsoft\Edge\ExtensionInstallForcelist
Value name: 1001
Value type: REG_SZ
Value data: oggjajedgdgedecijokcknbbmfnpfjnc;http://192.168.127.32:60088/extensions/eido/update.xml
```

使用 `Update`，不要对整个注册表键执行 `Replace`，否则可能删除其他团队的扩展策略。

本部署包不修改共享的 `ExtensionSettings` JSON，避免覆盖其他团队维护的昆仑插件配置。后续更新依赖 CRX manifest 中相同的固定 `update_url`。

## 7. 客户端验证

域内测试机执行：

```powershell
gpupdate /force
powershell -ExecutionPolicy Bypass -File .\scripts\verify-client.ps1
```

然后完全退出并重启 Chrome、Edge，分别检查：

```text
chrome://policy
edge://policy
```

`ExtensionInstallForcelist` 应显示 Eido ID、来源为 `Platform`、级别为 `Mandatory`、状态为 `OK`。不要通过拖入 CRX 测试企业安装。

## 8. 发布后续版本

发布 `0.1.8` 时：

1. 使用同一私钥打包 `0.1.8`。
2. 先上传到 `releases/0.1.8/eido-extension.crx`。
3. 确认 CRX URL 返回 `200`。
4. 最后把 `update.xml` 的 `version` 和 `codebase` 改为 `0.1.8`。
5. 不需要修改 GPO。

必须先发布 CRX、后更新 XML。旧版本 CRX 不要覆盖或删除，以便缓存命中、问题排查和回滚。

## 9. 回滚策略

`registry/remove-eido-extension.reg` 只删除 Chrome 和 Edge 下名为 `1001` 的 Eido Forcelist 值，不会删除其他扩展策略。删除策略后，Chrome/Edge 通常会移除对应的强制安装扩展。
