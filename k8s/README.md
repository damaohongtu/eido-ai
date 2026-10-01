# Eido 沙盒多用户 · K8s（DaoCloud DCE 5.0）部署

沙盒多用户模式的 K8s 编排：gateway 以 `EIDO_SANDBOX_MODE=k8s` 运行，通过
K8s API 为每个登录用户动态创建 **Pod + PVC**（不再依赖 docker.sock）。
所有用户沙盒 Pod / PVC 都在 DCE 控制台可见、可观测。

```
浏览器 ──NodePort 30080──▶ eido-gateway (nginx+FastAPI)
                              │  CAS 鉴权 / 路由 / provider relay（唯一出网点）
                              │  K8s API（ServiceAccount: eido-gateway）
                              ├──▶ Pod eido-user-<safe> + PVC eido-user-<safe>（每用户）
                              └──▶ 共享技能库 PVC eido-skills（user 以 subPath 只读挂载）
```

## 文件清单

| 文件 | 内容 |
|---|---|
| `00-namespace.yaml` | namespace `eido-system` |
| `10-rbac.yaml` | gateway ServiceAccount + 最小 Role（pods / pvc） |
| `20-storage.yaml` | gateway 数据 PVC + 共享技能库 PVC |
| `30-secret.yaml` | 凭据（由 `gen-secret.sh` 生成，勿提交 git） |
| `40-gateway.yaml` | gateway Deployment（**单副本**）+ NodePort Service 30080 |
| `50-cas.yaml` | 可选 CAS（本地验证用）+ NodePort 31443 |
| `gen-secret.sh` | 从 `docker/.env` 生成 `30-secret.yaml` |
| `kind-eido-dce.yaml` | 本地 kind 集群配置（DCE + eido 端口映射） |

## 一、本地 kind 验证（macOS / Apple Silicon）

前置：Docker Desktop（内存 ≥ 12GB）、kubectl、kind。

### 1. 建集群

```bash
kind create cluster --config k8s/kind-eido-dce.yaml
kubectl config use-context kind-eido-dce
```

（可选）在同一 kind 集群安装 DaoCloud DCE 5.0 社区版，见下文
[附录：DCE 社区版安装（Apple Silicon 实测）](#附录dce-社区版安装apple-silicon-实测)；
安装后 DCE 控制台 `http://localhost:8888`。

### 2. 构建并加载镜像（不依赖 DCE 镜像构建）

```bash
# 仓库根目录
docker build -f docker/gateway.Dockerfile -t damaohongtu/eido-gateway:latest .
docker build -f docker/user.Dockerfile    -t damaohongtu/eido-user:latest .

kind load docker-image damaohongtu/eido-gateway:latest --name eido-dce
kind load docker-image damaohongtu/eido-user:latest    --name eido-dce
kind load docker-image apereo/cas:6.6.10               --name eido-dce
```

> 镜像 tag 为 `:latest` 时 K8s 默认 `imagePullPolicy: Always`，清单里已显式
> 设为 `IfNotPresent`，否则 `kind load` 的本地镜像会拉取失败。

### 3. 部署

```bash
cd k8s
./gen-secret.sh                       # 生成 30-secret.yaml（含模型凭据）
kubectl apply -f 00-namespace.yaml
kubectl apply -f 10-rbac.yaml -f 20-storage.yaml -f 30-secret.yaml
kubectl apply -f 40-gateway.yaml -f 50-cas.yaml
kubectl -n eido-system get po,pvc     # 等待全部 Running / Bound
```

### 4. 浏览器访问（CAS 双 reachable 的关键）

`/etc/hosts` 增加一行（验证完删掉）：

```
127.0.0.1 cas.eido-system.svc.cluster.local
```

打开 `http://localhost:19080/ai-eido/` → 跳转 CAS 登录（test1/123456）→
回调建会话。首次访问自动创建 `eido-user-test1` Pod + PVC。

### 5. 验收清单

```bash
kubectl -n eido-system get po -w                # 观察 eido-user-* 动态创建
kubectl -n eido-system logs -f deploy/eido-gateway
```

- [ ] CAS 登录 → 回调 → 工作台可用
- [ ] 发起会话，SSE 流式回复（模型经 gateway provider relay）
- [ ] 两个账号（test1/test2）各自 Pod + PVC，数据互相不可见
- [ ] 技能库共享只读；admin 上传技能进 system 区
- [ ] 闲置 15min（EIDO_SANDBOX_IDLE_TTL）后 Pod 被回收、PVC 保留
- [ ] DCE 控制台 → 容器管理 → eido-system：可见 gateway Deployment 与
      动态创建的用户沙盒 Pod（日志 / 终端 / 监控）

## 二、生产 DCE 部署

与本地验证的差异：

1. **镜像仓库**：把 gateway / user 镜像推到 DCE 可拉取的仓库（如 DCE 自带
   Harbor 或内网 registry），修改 `40-gateway.yaml` 的 `image` 与
   `EIDO_USER_IMAGE`；私有仓库需建 imagePullSecret 并：
   - gateway Deployment 加 `imagePullSecrets`
   - 设置 `EIDO_K8S_IMAGE_PULL_SECRET`（gateway 会把它注入 user Pod）
2. **多节点**：`eido-skills` PVC 改 `ReadWriteMany`（NFS/CephFS SC）；
   `EIDO_K8S_STORAGE_CLASS` 指定用户 PVC 的 StorageClass。
3. **CAS**：删除 `50-cas.yaml`，`CAS_SERVER_URL` 指向企业 CAS；
   `CAS_SERVICE_URL` / `FRONTEND_URL` 改为正式域名（走 Ingress/网关时同步调整）。
4. **访问入口**：NodePort 换成 DCE 的 Ingress /负载均衡；对应修改
   `EIDO_GATEWAY_INTERNAL_URL` 保持集群内 Service 地址即可。

## 三、约束与差异（相对 docker 沙盒模式）

| 项 | docker 模式 | k8s 模式 |
|---|---|---|
| 沙盒载体 | 容器 + bridge 网络 + volume | Pod + ServiceAccount + PVC |
| 寻址 | 容器名（docker DNS） | Pod IP（registry 记录，Pod 重建自动刷新） |
| user → gateway | `http://eido-gateway/ai-eido` | `EIDO_GATEWAY_INTERNAL_URL`（Service DNS） |
| pids_limit | 支持 | **无 K8s 等价物**，由 resources + secContext 兜底 |
| 僵尸进程回收 | docker `--init` | 镜像内置 tini ENTRYPOINT |
| gateway 副本 | 单容器 | **必须单副本**（SQLite registry），扩容先迁库 |

gateway 每用户 Pod 的安全上下文与 docker 模式对齐：非 root（10001）、
只读 rootfs、drop ALL capabilities、禁止提权、`/tmp` 用内存 emptyDir。

## 附录：DCE 社区版安装（Apple Silicon 实测）

在 kind 集群内安装 DCE 5.0 社区版（2026-10 实测，installer v0.44.0），
坑主要在下载源与依赖版本：

1. **installer 二进制**：官方文档给的无架构后缀 URL 是 amd64；
   arm64 需带 `-linux-arm64` 后缀：
   `https://qiniu-download-public.daocloud.io/DaoCloud_Enterprise/dce5/dce5-installer-v0.44.0-linux-arm64`
   该 CDN 前置雷池 WAF，curl/wget/Node 一律被拦（curl 403 / Node 468），
   仅浏览器可过 JS 挑战——在浏览器下载后 `docker cp` 进 kind 节点。
2. **前置依赖**在 kind 节点内安装（社区模式只需 helm/skopeo/kubectl/yq/charts-syncer）：
   官方 `install_prerequisite.sh` 从 `files.m.daocloud.io` 下载（该镜像源 curl 可达），
   但节点内直接跑易因限速/HTTP2 中断失败——建议宿主机下载后 `docker cp`。
3. **helm 必须 ≥ v3.14.0**（`install_prerequisite.sh` 装的 v3.11.1 会被
   installer v0.44.0 预检拒绝），手动升级：
   `https://files.m.daocloud.io/get.helm.sh/helm-v3.16.3-linux-arm64.tar.gz`
4. **节点内下载被限速是最大拦路虎**：`*.m.daocloud.io` 会 302 到 Cloudflare R2
   （`files-mirror.r2.daocloud.vip`），kind 节点内直连只有 ~500B/s 且 HTTP/2 频繁
   断流（curl 18/EOF），宿主机访问同一 URL 却是 MB/s 级。**解法：宿主机起一个
   HTTP CONNECT 代理，节点内所有下载经宿主机隧道出去**（30 行 Node 脚本即可，
   监听 0.0.0.0:3128；节点访问宿主机用 `host.docker.internal`，LAN IP 不通）：

   ```bash
   # 宿主机：node rproxy.js &   （CONNECT-only 代理，见本仓库 k8s/scripts 或自写）
   # 节点内 containerd 拉镜像也走代理（镜像拉取偶发 EOF 用重试兜底）：
   docker exec <node> sh -c 'mkdir -p /etc/systemd/system/containerd.service.d && \
     printf "[Service]\nEnvironment=\"HTTPS_PROXY=http://host.docker.internal:3128\"\nEnvironment=\"NO_PROXY=localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16\"\n" \
     > /etc/systemd/system/containerd.service.d/proxy.conf && \
     systemctl daemon-reload && systemctl restart containerd'
   ```

   注意 NO_PROXY 必须包含 API server 地址（`eido-dce-control-plane`），否则
   kubectl/helm 对集群的请求也会被代理。
5. **运行安装**（kind 节点内，`-z` 最小化副本适配 12GB 内存，带代理环境变量）：

   ```bash
   docker exec -e KUBECONFIG=/etc/kubernetes/admin.conf <node> \
     sh -c 'cd /root && nohup env HTTPS_PROXY=http://host.docker.internal:3128 \
            NO_PROXY="localhost,127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,eido-dce-control-plane" \
            ./dce5-installer install-app -z -k <宿主IP>:8888 -j 8+ \
            > /root/dce5-install.log 2>&1 &'
   # 轮询：docker exec <node> tail /root/dce5-install.log
   ```

   全程 30 分钟以上，务必用 nohup 分离运行（docker exec 会话断开会杀进程）。
   12GB Docker Desktop 内存下预检报"差 290Mi"但可 Pass 通过。
   安装失败可 `-j <step>+` 从断点续装（步骤号看日志 "failed at step [N]"）。
6. **16GB Mac 内存上限**：DCE 全家桶（ghippo+kpanda+insight+中间件 operators）
   在 12GB VM 内会把宿主机 swap 打满（节点 load 100+，kube-scheduler 因 API
   server 超时反复丢锁）。**insight（可观测套件）是最大头且非演示必需，建议
   安装完成后 `helm uninstall insight -n insight-system` 并删除该命名空间**，
   保留 ghippo（控制台/登录）+ kpanda（容器管理）即可稳定运行。
7. **License（社区免费授权，三步）**：见官方文档
   <https://docs.daocloud.io/dce/license0/>。
   ① `https://license.daocloud.io/dce5-license`（单数）申请**许可证密钥**
   （注意 `dce5-licenses` 复数是查询页，没有提交入口）→ ② 邮箱收密钥 →
   ③ 同站"换取离线授权码"：新密钥 + 本集群 ESN → 离线授权码，写入
   `docker/daocloud.conf` 后 `kubectl apply`。
   **ESN = kube-system 命名空间 UID**（`kubectl get ns kube-system -o
   jsonpath='{.metadata.uid}'`，kind 集群重建才会变）。密钥首次换码时即与
   ESN 绑定，**换环境必须重新申请**（旧密钥换码会报 "Cluster id not
   match"）。未激活时控制台被"您需要完成正版授权"遮罩，但不影响 eido
   自身运行。

## 控制台访问

- **DCE 控制台是 HTTPS**：`https://localhost:8888`（kind 8888 → NodePort 32088 →
  istio gateway 443）。用 http 访问会得到空响应。默认账号 admin/changeme。
- eido 入口：`http://localhost:19080/ai-eido/`（kind 19080 → NodePort 30080）。
  **不能用 10080 等浏览器封禁端口**（10080 是 amanda 协议端口，Chrome/Safari
  直接报 ERR_UNSAFE_PORT，curl 却正常——已踩坑）。老集群若已映射 10080，可加
  socat 边车容器补一个安全端口（`docker run -d --name eido-web-proxy
  --network kind --restart unless-stopped -p 19080:30080
  docker.m.daocloud.io/alpine/socat tcp-listen:30080,fork,reuseaddr
  tcp-connect:eido-dce-control-plane:30080`），并把 `40-gateway.yaml` 的
  `CAS_SERVICE_URL`/`FRONTEND_URL` 同步改为新端口。
- **注意**：DCE 控制台里 Service 的"外部访问"显示为 `172.18.0.2:<NodePort>`
  （kind 节点容器的 Docker 内网 IP，浏览器不可达，点击会超时）——kind 下一律
  用上表的宿主机映射端口访问；真实机器部署时该地址才是可用的。

## 实测已验证项（2026-10-01，kind + DCE 5.0 社区版）

CAS 认证（test1/test2/admin 多账号登录回调）、per-user Pod+PVC 动态创建
（warmup 10s 内 Ready）、SSE 聊天（模型经 gateway provider relay，GLM 流式回复）、
双用户会话/数据隔离、闲置 GC（TTL 900s 回收 Pod、保留 PVC、registry 置 stopped）、
GC 后 re-warm 复用同一 PVC（数据持久）、DCE 控制台 License 激活（三模块 Using）。

注意：用户沙盒是 gateway 直接创建的**裸 Pod**（无 Deployment），在 DCE
"容器组/Pod"列表查看，不在"无状态负载"里。

**坑**：`kind load docker-image` 偶发 `ctr: content digest ... not found`（与
镜像无关，重试或改用 `docker save <img> | docker exec -i <node> ctr -n k8s.io
images import -` 直导）；`gen-secret.sh` 在 macOS bash 3.2 下 `source <(管道)`
不生效（zsh 正常），已改用 `eval`。

