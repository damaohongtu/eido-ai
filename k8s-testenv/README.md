# Eido 沙盒多用户 · 测试环境部署包（DaoCloud DCE 5.0）

把本地 kind 验证过的 K8s 部署迁移到**真实测试环境集群**：CAS 使用真实服务
`http://192.168.127.32:60333/cas/`，镜像来自 `192.168.98.65/molt-dev` 仓库，
其余配置（模型凭据、会话密钥、资源限额、TTL、管理员、存储大小、NodePort
端口）与本地部署完全一致。

本目录自包含，不依赖 `k8s/` 目录；与本地版的差异只有 3 处（见下表）。

## 文件清单

| 文件 | 内容 | 部署顺序 |
|---|---|---|
| `00-namespace.yaml` | 命名空间 `eido-system` | 1 |
| `10-rbac.yaml` | ServiceAccount / Role / RoleBinding | 2 |
| `20-storage.yaml` | `eido-gateway-data` + `eido-skills` 两个 PVC | 3 |
| `30-secret.yaml` | 模型凭据 + 会话密钥（`gen-secret.sh` 生成，已 gitignore） | 4 |
| `gen-secret.sh` | 从 `../docker/.env` 生成上表文件 | — |
| `40-gateway.yaml` | gateway Deployment + NodePort Service | 5 |

## 〇、与本地部署的差异总览

| 项 | 本地 kind | 测试环境 |
|---|---|---|
| CAS | 内置 `apereo/cas`（`50-cas.yaml`） | 真实 CAS `http://192.168.127.32:60333/cas/`（/cas 上下文，已实测确认） |
| 访问入口 | `http://localhost:19080/ai-eido/`（kind 端口映射） | `http://<节点IP>:30080/ai-eido/`（NodePort 直连） |
| 镜像 | 本机 arm64 构建 | `192.168.98.65/molt-dev` 仓库（架构需与集群一致） |

本地环境的两个特殊处理在测试环境**不再需要**：`/etc/hosts` 加 CAS 域名（真实
CAS 有正常可解析的 IP）、19080 socat 转发（NodePort 30080 直连）。

## 一、前置检查（部署前必做）

### 1. 确认镜像架构与集群一致

镜像已推送至 `192.168.98.65/molt-dev`（清单默认 tag `:latest`，与实际推送
的 tag 不一致时改 `40-gateway.yaml` 两处）。确认推送的镜像架构与集群匹配：

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,ARCH:.status.nodeInfo.architecture
```

x86（amd64）集群拉到 arm64 镜像会报 `exec format error`；重新构建用
buildx（见第二节）。

### 2. CAS 地址（已确认）

CAS 部署在 `/cas` 上下文（`http://192.168.127.32:60333/cas/login` 实测可
访问），`40-gateway.yaml` 已填 `http://192.168.127.32:60333/cas/`。

背景：后端把 `CAS_SERVER_URL` 规范化为以 `/` 结尾后直接拼 `login` /
`serviceValidate`（`config.py` 的 `normalize_cas_server_url`），上下文路径
必须包含在内，否则登录跳转 404。日后 CAS 地址变更时，用 curl 重新判定。

### 3. 网络连通性（4 条独立链路，缺一不可）

| 链路 | 用途 |
|---|---|
| 浏览器 → `节点IP:30080` | 访问前端、CAS 回调 |
| 浏览器 → `192.168.127.32:60333` | CAS 登录页 |
| gateway Pod → `192.168.127.32:60333` | ticket 服务端校验（与浏览器可达无关） |
| gateway/user Pod → `ANTHROPIC_BASE_URL`（bigmodel） | 模型 API 出网 |

Pod 内验证（部署 gateway 后，或用 `kubectl run` 临时 Pod）：

```bash
kubectl exec -n eido-system deploy/eido-gateway -- \
  curl -s -o /dev/null -w '%{http_code}\n' http://192.168.127.32:60333/cas/login
```

### 4. 存储就绪

```bash
kubectl get sc
```

- 必须存在**默认 StorageClass**（带 `(default)` 标记），否则 gateway 启动时
  动态创建用户 PVC 会失败。无默认 SC 时，在 `40-gateway.yaml` 取消注释
  `EIDO_K8S_STORAGE_CLASS` 并填入实际名称。
- **多节点集群**：`eido-skills` 需被 gateway 与所有 user Pod 同时挂载，RWO
  只能同节点挂载。若 user Pod 可能调度到其他节点，必须改用支持 RWX 的
  StorageClass（NFS/CephFS）——修改 `20-storage.yaml` 中 `eido-skills` 的
  `accessModes` 为 `ReadWriteMany` 并指定 `storageClassName`（见该文件头注释）。

### 5. NodePort 30080 未被占用

```bash
kubectl get svc -A | grep 30080
```

## 二、构建并分发镜像

镜像仓库为 `192.168.98.65/molt-dev`（清单已指向，默认 tag `:latest`）。
重新构建/更新镜像时在**本机仓库根目录**执行（amd64 集群为例，集群架构见
前置检查第 1 项）：

```bash
docker buildx build --platform linux/amd64 -f docker/gateway.Dockerfile \
  -t 192.168.98.65/molt-dev/eido-gateway:latest --push .
docker buildx build --platform linux/amd64 -f docker/user.Dockerfile \
  -t 192.168.98.65/molt-dev/eido-user:latest --push .
```

若仓库需要认证：gateway Deployment 的 `spec.template.spec` 加
`imagePullSecrets`；user Pod 的拉取凭据取消注释 `EIDO_K8S_IMAGE_PULL_SECRET`
（两处位置见 `40-gateway.yaml` 注释）。

### 备选：无仓库时逐节点导入（每个节点都要执行）

```bash
docker buildx build --platform linux/amd64 -f docker/gateway.Dockerfile \
  -t damaohongtu/eido-gateway:latest --load .
docker buildx build --platform linux/amd64 -f docker/user.Dockerfile \
  -t damaohongtu/eido-user:latest --load .
docker save damaohongtu/eido-gateway:latest damaohongtu/eido-user:latest \
  | gzip > eido-images.tar.gz
# 拷到每个节点后执行：
gunzip -c eido-images.tar.gz | sudo ctr -n k8s.io images import -
```

> **更新陷阱**：清单使用 `:latest` + `imagePullPolicy: IfNotPresent`，节点上
> 已有同名镜像就不会重新拉取。后续更新版本请改用具体 tag（如 `:test`），或
> 更新前删除节点旧镜像。

## 三、生成 Secret（复用本地凭据）

```bash
cd k8s-testenv && ./gen-secret.sh
```

- 读取 `../docker/.env`：`ANTHROPIC_BASE_URL` / `ANTHROPIC_API_KEY` 与
  `SESSION_SECRET_KEY` / `EIDO_GATEWAY_SECRET` 全部复用本地环境的值。
- 产出 `30-secret.yaml`（敏感文件，已 gitignore，勿提交）。
- kubectl 仅用于 `--dry-run=client` 生成 YAML，**不会连接集群**。

## 四、DCE 控制台界面部署（按序操作）

前提：**容器管理** → 左侧集群列表中已接入测试集群。以下操作均在选中该集群
后进行；菜单名称可能随 DCE 版本略有差异，找不到时统一走「YAML 创建」入口
粘贴对应文件全文，效果等价。

1. **命名空间**：集群详情 → 命名空间 → 创建 → 名称 `eido-system`（其余默认）
2. **RBAC**：集群详情 → 右上角「YAML 创建」→ 粘贴 `10-rbac.yaml` 全文 → 确定
3. **存储声明**：存储 → 存储声明 → 创建（`eido-gateway-data`，2Gi，RWO）；
   再建 `eido-skills`（2Gi，单节点 RWO / 多节点 RWX）。或直接「YAML 创建」
   粘贴 `20-storage.yaml`
4. **密钥**：配置与密钥 → 密钥 → 创建 → 切到 YAML 编辑（命名空间选
   `eido-system`）→ 粘贴 `30-secret.yaml` 全文
5. **工作负载**：无状态负载 → YAML 创建 → 粘贴 `40-gateway.yaml` 全文
   （文件内含 Deployment 与 Service 两段，一次粘贴即可）。
   **粘贴前确认 `<节点IP>` 占位符已替换**
6. **等待就绪**：无状态负载 `eido-gateway` 副本 1/1、Pod Running、两个 PVC
   均已绑定（事件里无 Warning）

### kubectl 等价操作（有 kubeconfig 时）

```bash
kubectl apply -f k8s-testenv/00-namespace.yaml
kubectl apply -f k8s-testenv/10-rbac.yaml
kubectl apply -f k8s-testenv/20-storage.yaml
kubectl apply -f k8s-testenv/30-secret.yaml
kubectl apply -f k8s-testenv/40-gateway.yaml
```

## 五、部署后验证清单

- [ ] gateway Pod `Running 1/1`，事件无 Warning
- [ ] `eido-gateway-data` / `eido-skills` 均已绑定（Bound）
- [ ] `curl http://<节点IP>:30080/ai-eido/health` 返回 ok
- [ ] 浏览器打开 `http://<节点IP>:30080/ai-eido/` → 跳转 CAS → 登录 → 回调 → 工作台
- [ ] 发起会话 → 容器管理界面 `eido-system` 下出现 `eido-user-<用户名>` Pod 与同名 PVC
- [ ] 聊天 SSE 流式输出正常（模型凭据经 gateway provider relay，不落 user Pod）
- [ ] 技能库为空属正常（新集群）：`EIDO_ADMIN_USERS` 对应的 CAS 账号登录后安装技能
- [ ] 空闲 15 分钟（`EIDO_SANDBOX_IDLE_TTL=900`）后 user Pod 被回收、PVC 保留

## 六、常见问题

| 现象 | 原因与处理 |
|---|---|
| 登录跳转 404 | `CAS_SERVER_URL` 上下文路径不对 → 按前置检查第 2 项重新判定 |
| CAS 登录成功但回调 401「ticket 验证失败」 | gateway Pod → CAS 网络不通（与浏览器可达是两条独立链路）→ Pod 内 curl 验证 |
| ImagePullBackOff / `exec format error` | 镜像架构不符（arm64 镜像用于 x86 集群）或仓库凭据缺失 |
| ImagePullBackOff 且报 `server gave HTTP response to HTTPS client` | 仓库为 HTTP 明文（IP 直连、无 TLS），节点 containerd 需把 `192.168.98.65` 配置为 insecure registry 后才能拉取 |
| user Pod 一直 Pending / 卷挂载失败 | 无默认 StorageClass；或多节点 + skills 卷 RWO 跨节点 → 改 RWX |
| 更新镜像后行为没变 | `:latest` + `IfNotPresent` 命中节点缓存 → 换具体 tag 或删旧镜像 |
| Pod 内解析不了模型 API 域名 | 集群 egress/DNS 限制（本地 kind 靠 rproxy 出网，真实集群一般无此问题） |
| 限制 namespace 总资源（可选加固） | 另加 ResourceQuota 限制 `eido-system` 的 pods / storage 总量；本包未内置，按需补充 |

## 与 `k8s/` 目录的关系

`k8s/` 是本地 kind 验证清单（含内置 CAS、建集群、rproxy 附录）。本目录面向
测试环境：不含 CAS 部署（用真实 CAS）、镜像需按集群架构重建、访问入口为
节点 NodePort 直连。后续配置变更请修改本目录文件后重新 apply（或界面更新）。
