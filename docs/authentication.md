# 登录认证

CAS、GitHub OAuth 和通用 OIDC 共用 Eido 的浏览器会话、固定 API Key 与用户数据隔离。
未登录时展示已配置的登录方式。CAS 的 `/api/v1/auth/login`、`/callback` 和 ticket
验证配置保持兼容；OAuth/OIDC 使用 `/login/{provider}` 与 `/callback/{provider}`。

认证逻辑集中在 `backend/app/services/auth/`。`cas.py` 处理 CAS 协议，`providers.py`
使用 Authlib 处理 OAuth/OIDC 的 state、PKCE 和 ID token 验证。
`api/v1/endpoints/auth.py` 处理 HTTP 跳转、浏览器会话和 API Key。

## GitHub

在 [GitHub OAuth Apps](https://github.com/settings/developers) 创建 OAuth App。
本地 Docker 的 Homepage URL 填写 `http://localhost:19080/ai-eido/`，
Authorization callback URL 填写
`http://localhost:19080/ai-eido/api/v1/auth/callback/github`。

在本地环境文件中配置以下值，然后重新创建应用或网关容器。

```dotenv
AUTH_DISABLED=False
FRONTEND_URL=http://localhost:19080/ai-eido/
SESSION_SECRET_KEY=replace-with-a-random-secret
GITHUB_CLIENT_ID=your-oauth-app-client-id
GITHUB_CLIENT_SECRET=your-oauth-app-client-secret
GITHUB_REDIRECT_URI=http://localhost:19080/ai-eido/api/v1/auth/callback/github
```

继续保留原有的 `CAS_SERVER_URL`、`CAS_INTERNAL_URL` 和 `CAS_SERVICE_URL`。
GitHub 只请求 `read:user` 资料权限，访问令牌仅在后端回调期间使用，不写入浏览器会话。

## 其他 OIDC 提供方

Auth0、Keycloak、Google、Microsoft Entra ID 等支持 OIDC 的服务可通过配置增加，
无需增加路由。先在认证服务中创建 Web 应用，注册对应的回调地址；OIDC issuer
必须与服务发布的 discovery 文档一致。以下示例接入 Auth0。

```dotenv
OIDC_PROVIDERS_JSON='[{"id":"auth0","name":"企业账号","issuer":"https://your-tenant.auth0.com/","client_id":"your-client-id","client_secret":"your-client-secret","redirect_uri":"http://localhost:19080/ai-eido/api/v1/auth/callback/auth0"}]'
```

每项配置包含 `id`、`name`、`issuer`、`client_id`、`client_secret`；
`redirect_uri` 可省略，默认按 `FRONTEND_URL` 生成。
`scope` 默认为 `openid profile`，可按服务要求增加 `email` 等权限。
`token_endpoint_auth_method` 默认为 `client_secret_basic`，可配置为
`client_secret_post`，需与认证服务中该应用的凭据验证方式一致。
`id` 必须唯一，使用小写字母开头的 1–32 位字母、数字、下划线、连字符，
`cas`、`github`、`dev` 为保留名称。

Keycloak 的 issuer 通常为 `https://sso.example.com/realms/<realm>`；Entra ID 为
`https://login.microsoftonline.com/<tenant-id>/v2.0`。如果服务不支持 OIDC，
则需像 CAS 一样增加对应协议的适配器，并复用现有会话和 API Key。

## 身份与退出

CAS 的现有用户 ID 保持不变。GitHub 使用不可变的数字用户 ID 构造
`oauth_github_<id>`；OIDC 使用提供方 ID 与 `iss`、`sub` 构造稳定标识。
不会根据用户名或邮箱自动合并账号。修改提供方 `id`、issuer 或 subject 会视为新身份。
配置 `EIDO_ADMIN_USERS` 时使用 Eido 实际返回的 `user_id`。
公网单租户部署可通过 `AUTH_ALLOWED_USER_IDS` 配置逗号分隔的用户 ID 白名单；
限制同时用于登录、浏览器会话、API Key 和任务 Token。留空时允许任意已认证用户。
如需按 GitHub 账号限制，可配置 `AUTH_ALLOWED_GITHUB_USERS`（GitHub 资料中的
`login`，逗号分隔、大小写不敏感），该检查只在 GitHub 回调换取资料后执行，
不匹配返回 403；两个白名单可同时使用，取交集效果。

`GET /api/v1/auth/providers` 只返回公开的登录名称和 ID。
登录后可通过原有 `/api/v1/auth/me`、`/api-key` 接口获取身份和固定 API Key。
CAS 退出继续跳转 CAS；OAuth/OIDC 退出清除 Eido 会话，不清除认证服务自身的登录会话。
凭据仅配置在应用或网关中，不下发到用户沙盒。

Docker Compose 的单机与网关配置均透传这些变量。Kubernetes 的
`k8s/gen-secret.sh` 与 `k8s-testenv/gen-secret.sh` 会从环境文件写入
`eido-secrets`，由网关通过 `envFrom` 读取；更新 Secret 后需重启网关。

## mao 单机部署

`docker/docker-compose.mao.yml` 部署多租户网关，用户容器按登录身份自动创建。
网关限制为 384MB，每个用户容器默认为 512MB、0.75 CPU，闲置 180 秒后回收，
用户数据卷保留。网关使用 `eido-gateway-data`，每位用户使用独立的
`eido-user-<safe-user-id>` 数据卷和网络；旧单租户 `eido-data` 卷保留。
私有变量通过 `EIDO_ENV_FILE` 指定，镜像通过 `EIDO_GATEWAY_IMAGE` 和
`EIDO_USER_IMAGE` 指定。网关持有 Docker socket，用户容器不挂载该 socket，
也不接收 GitHub Secret、部署签名密钥或真实模型密钥。
公网部署设置 `FRONTEND_URL=http://8.134.83.141/ai-eido/` 和
`GITHUB_REDIRECT_URI=http://8.134.83.141/ai-eido/api/v1/auth/callback/github`。
CAS 需要配置公网浏览器可访问的 `CAS_SERVER_URL`，可另设 `CAS_INTERNAL_URL`
供后端校验 ticket，并设置 `CAS_SERVICE_URL` 为公网 `/api/v1/auth/callback`。
未配置 CAS 时登录页隐藏 CAS，保留的接口返回 503；GitHub 登录仍可使用。
