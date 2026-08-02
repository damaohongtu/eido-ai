# Eido Extension Update Server

独立的 Chrome 扩展更新服务，不依赖 Eido 现有后端、数据库或用户认证。服务直接托管服务器本地的 CRX，并为 Chrome 原生更新器返回 Update Manifest XML。

## 接口

```text
GET /healthz
GET /updates.xml?x=id%3D<extension-id>%26v%3D<current-version>
```

当配置版本高于客户端版本时，`updates.xml` 返回本服务上的版本化 CRX 下载 URL；否则返回 `status="noupdate"`。

## 启动

```bash
cd extension-update-server
cp .env.example .env
# 编辑 .env
docker compose up --build -d
```

本机启动：

```bash
cd extension-update-server
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
set -a
. ./.env
set +a
uvicorn extension_updater.main:app --host 0.0.0.0 --port 8090
```

检查响应：

```bash
curl --get 'http://127.0.0.1:8090/updates.xml' \
  --data-urlencode 'x=id=abcdefghijklmnopabcdefghijklmnop&v=0.1.2'
```

## 发布一个新版本

1. 在 `frontend-extension` 生成新 CRX，详见该目录 README 的“私有自动更新构建”。
2. 把 CRX 复制到独立服务器，例如 `/srv/eido-extension/eido-extension.crx`，确保容器用户可读（例如文件权限 `0644`），并只读挂载到容器 `/data/eido-extension.crx`。
3. 修改独立服务的环境变量：

```text
EIDO_EXTENSION_VERSION=<新版本>
EIDO_EXTENSION_PACKAGE_PATH=/data/eido-extension.crx
EIDO_EXTENSION_PUBLIC_BASE_URL=https://updates.eido.example.com
EIDO_EXTENSION_MIN_CHROME_VERSION=<最低 Chrome 版本>
```

4. 重新创建服务，使新环境变量和文件同时生效：

```bash
docker compose up -d --force-recreate
```

服务启动时会校验文件存在且具有 CRX 文件头。Chrome 会在启动时或周期检查时获取更新；扩展收到 `onUpdateAvailable` 后自动重载并应用。每次内容变化都必须增加版本号，不能用新内容覆盖同版本 URL。

## 反向代理

生产环境应把固定 HTTPS 地址直接转发到 `/updates.xml`，且不接入 CAS：

```nginx
location = /v1/chrome/stable {
    proxy_pass http://extension-update-server:8090/updates.xml;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}

location /releases/ {
    proxy_pass http://extension-update-server:8090/releases/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

然后发布扩展时使用：

```text
EIDO_EXTENSION_UPDATE_URL=https://updates.eido.example.com/v1/chrome/stable
```

Windows/macOS 上的非商店 CRX 仍必须通过 Chrome 企业策略首次安装。策略中的扩展 ID 必须由用于打包 CRX 的同一私钥生成。

## 测试

```bash
cd extension-update-server
pip install -r requirements-dev.txt
pytest
ruff check extension_updater tests
```
