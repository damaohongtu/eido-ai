"""
K8s 沙盒编排后端 — EIDO_SANDBOX_MODE=k8s 时 SandboxManager 的执行层。

与 docker 后端的语义对齐：
- 每用户一个 Pod `eido-user-<safe>` + 一个 PVC `eido-user-<safe>`
- PVC 永远保留（stop 只删 Pod），等价 docker 模式 "volumes 永远保留"
- 资源限额（EIDO_USER_MEM / EIDO_USER_CPUS）→ resources.limits；
  requests 保持较小以允许超卖（docker mem_limit 亦无预留语义）
- read_only / cap_drop ALL / no-new-privileges → securityContext
- tmpfs /tmp → emptyDir(Memory, sizeLimit)
- 归属校验：Pod / PVC 均带 io.eido.user_id label，拒绝复用他人资源

网络差异：docker 模式靠 per-user bridge + docker DNS（容器名）寻址；
K8s 模式直接以 Pod IP 寻址（registry 记录 IP，Pod 重建后刷新），
user Pod 访问 gateway 走集群 Service DNS（EIDO_GATEWAY_INTERNAL_URL）。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_LABEL_ROLE = "io.eido.role"
_LABEL_ISOLATION = "io.eido.isolation_version"
_LABEL_USER = "io.eido.user_id"


@dataclass(frozen=True)
class PodState:
    """user Pod 的观测状态。"""

    phase: str
    pod_ip: Optional[str]
    ready: bool


def _pod_state(pod) -> PodState:
    """从 K8s Pod 对象提取 phase / IP / Ready。"""
    phase = pod.status.phase or "Unknown"
    pod_ip = (pod.status.pod_ip or "").strip() or None
    ready = False
    for cond in pod.status.conditions or []:
        if cond.type == "Ready":
            ready = bool(cond.status == "True")
            break
    return PodState(phase=phase, pod_ip=pod_ip, ready=ready)


def _parse_mem_limit(value: str) -> str:
    """校验 K8s 可接受的内存 quantity（Ki/Mi/Gi/Ti 等）。"""
    v = (value or "").strip()
    if not v:
        return "2Gi"
    return v


class K8sSandboxClient:
    """通过 Kubernetes API 管理每用户沙盒 Pod / PVC。"""

    def __init__(self, *, namespace: Optional[str] = None):
        self._namespace = namespace or settings.EIDO_K8S_NAMESPACE
        self._core = None

    # -------------------------------------------------------------- #
    #  连接                                                           #
    # -------------------------------------------------------------- #

    def connect(self) -> None:
        """加载集群凭据并做一次轻量连通性检查。

        优先 in-cluster ServiceAccount；本地调试时回退 kubeconfig。
        连接失败抛 RuntimeError，由 SandboxManager 终止 gateway 启动
        （与 docker 模式 "Docker 不可用，拒绝退回共享进程" 行为一致）。
        """
        try:
            import urllib3

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        except Exception:  # pragma: no cover - 仅静音告警
            pass

        try:
            from kubernetes import client as k8s_client
            from kubernetes import config as k8s_config

            try:
                k8s_config.load_incluster_config()
                logger.info("K8s 沙盒后端：使用 in-cluster ServiceAccount 凭据")
            except Exception:
                k8s_config.load_kube_config()
                logger.warning(
                    "K8s 沙盒后端：in-cluster 凭据不可用，回退本机 kubeconfig（仅限调试）"
                )
            self._core = k8s_client.CoreV1Api()
            self._core.list_namespaced_pod(
                self._namespace, limit=1, _request_timeout=10
            )
        except Exception as e:
            self._core = None
            raise RuntimeError(
                f"Kubernetes API 不可用（namespace={self._namespace}），"
                "拒绝以 k8s 沙盒模式启动"
            ) from e
        logger.info(f"✓ K8s 沙盒后端就绪 namespace={self._namespace}")

    def close(self) -> None:
        self._core = None

    @property
    def namespace(self) -> str:
        return self._namespace

    # -------------------------------------------------------------- #
    #  PVC                                                            #
    # -------------------------------------------------------------- #

    def _ensure_pvc(self, user_id: str, safe: str) -> str:
        """幂等创建用户数据 PVC；沿用 docker 模式的归属校验语义。"""
        from kubernetes import client as k8s_client
        from kubernetes.client import ApiException

        name = f"eido-user-{safe}"
        try:
            pvc = self._core.read_namespaced_persistent_volume_claim(
                name, self._namespace
            )
            owner = (pvc.metadata.labels or {}).get(_LABEL_USER)
            if owner and owner != user_id:
                raise RuntimeError("拒绝挂载其他用户的数据卷")
            if not owner:
                raise RuntimeError("无法确认旧数据卷归属，拒绝自动挂载")
            return name
        except ApiException as e:
            if e.status != 404:
                raise

        pvc = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                labels={
                    _LABEL_ROLE: "user-data",
                    _LABEL_USER: user_id,
                },
            ),
            spec=k8s_client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                storage_class_name=settings.EIDO_K8S_STORAGE_CLASS or None,
                resources=k8s_client.V1ResourceRequirements(
                    requests={"storage": _parse_mem_limit(settings.EIDO_K8S_USER_STORAGE)}
                ),
            ),
        )
        try:
            self._core.create_namespaced_persistent_volume_claim(
                self._namespace, pvc
            )
            logger.info(f"创建用户 PVC {name}（{settings.EIDO_K8S_USER_STORAGE}）")
        except ApiException as e:
            # 并发创建竞态：已存在则复用（重新读取并校验归属）
            if e.status != 409:
                raise
            created = self._core.read_namespaced_persistent_volume_claim(
                name, self._namespace
            )
            owner = (created.metadata.labels or {}).get(_LABEL_USER)
            if owner != user_id:
                raise RuntimeError("拒绝挂载其他用户的数据卷")
        return name

    # -------------------------------------------------------------- #
    #  Pod                                                            #
    # -------------------------------------------------------------- #

    def _get_pod(self, name: str):
        from kubernetes.client import ApiException

        try:
            return self._core.read_namespaced_pod(name, self._namespace)
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def _build_pod(self, user_id: str, safe: str, name: str, env: dict):
        from kubernetes import client as k8s_client

        try:
            cpus = float(settings.EIDO_USER_CPUS or 1.0)
        except Exception:
            cpus = 1.0
        mem = _parse_mem_limit(settings.EIDO_USER_MEM or "2g")
        # K8s quantity 用 Mi/Gi；兼容 docker 风格的 m/g 后缀
        mem = mem.replace("g", "Gi").replace("m", "Mi")
        tmpfs = (settings.EIDO_USER_TMPFS_SIZE or "512m").replace("m", "Mi")

        env_vars = [k8s_client.V1EnvVar(name=k, value=str(v)) for k, v in env.items()]
        pull_secrets = (
            [
                k8s_client.V1LocalObjectReference(
                    name=settings.EIDO_K8S_IMAGE_PULL_SECRET
                )
            ]
            if settings.EIDO_K8S_IMAGE_PULL_SECRET.strip()
            else []
        )

        container = k8s_client.V1Container(
            name="eido-user",
            image=settings.EIDO_USER_IMAGE,
            # :latest 标签默认策略为 Always，本地 kind load 的镜像会被强制拉取失败
            image_pull_policy="IfNotPresent",
            env=env_vars,
            ports=[k8s_client.V1ContainerPort(container_port=8000)],
            resources=k8s_client.V1ResourceRequirements(
                requests={"cpu": "100m", "memory": "256Mi"},
                limits={"cpu": cpus, "memory": mem},
            ),
            readiness_probe=k8s_client.V1Probe(
                http_get=k8s_client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=3,
                period_seconds=2,
                timeout_seconds=2,
                failure_threshold=30,
            ),
            liveness_probe=k8s_client.V1Probe(
                http_get=k8s_client.V1HTTPGetAction(path="/health", port=8000),
                initial_delay_seconds=20,
                period_seconds=15,
                timeout_seconds=3,
                failure_threshold=3,
            ),
            security_context=k8s_client.V1SecurityContext(
                run_as_non_root=True,
                read_only_root_filesystem=True,
                allow_privilege_escalation=False,
                capabilities=k8s_client.V1Capabilities(drop=["ALL"]),
            ),
            volume_mounts=[
                k8s_client.V1VolumeMount(name="data", mount_path="/data"),
                k8s_client.V1VolumeMount(
                    name="skills",
                    mount_path="/workspace/.claude/skills/system",
                    sub_path="system",
                    read_only=True,
                ),
                k8s_client.V1VolumeMount(
                    name="skills",
                    mount_path=f"/workspace/.claude/skills/users/{safe}",
                    sub_path=f"users/{safe}",
                    read_only=True,
                ),
                k8s_client.V1VolumeMount(name="tmp", mount_path="/tmp"),
            ],
        )

        return k8s_client.V1Pod(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                labels={
                    "app.kubernetes.io/name": "eido-user",
                    "app.kubernetes.io/managed-by": "eido-gateway",
                    _LABEL_ROLE: "user-sandbox",
                    _LABEL_ISOLATION: "2",
                    _LABEL_USER: user_id,
                },
            ),
            spec=k8s_client.V1PodSpec(
                restart_policy="Always",
                image_pull_secrets=pull_secrets or None,
                service_account_name=None,
                security_context=k8s_client.V1PodSecurityContext(
                    run_as_user=10001,
                    run_as_group=10001,
                    fs_group=10001,
                ),
                containers=[container],
                volumes=[
                    k8s_client.V1Volume(
                        name="data",
                        persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=f"eido-user-{safe}"
                        ),
                    ),
                    k8s_client.V1Volume(
                        name="skills",
                        persistent_volume_claim=k8s_client.V1PersistentVolumeClaimVolumeSource(
                            claim_name=settings.EIDO_K8S_SKILLS_CLAIM
                        ),
                    ),
                    k8s_client.V1Volume(
                        name="tmp",
                        empty_dir=k8s_client.V1EmptyDirVolumeSource(
                            medium="Memory",
                            size_limit=tmpfs,
                        ),
                    ),
                ],
            ),
        )

    def _wait_ready(self, name: str, *, timeout: float) -> PodState:
        """轮询直至 Pod 分配 IP 且 Ready；超时抛 RuntimeError。"""
        from kubernetes.client import ApiException

        deadline = time.monotonic() + timeout
        last: Optional[PodState] = None
        while time.monotonic() < deadline:
            try:
                pod = self._get_pod(name)
            except ApiException as e:
                raise RuntimeError(f"读取 user Pod 失败: {name} ({e.reason})") from e
            if pod is None:
                raise RuntimeError(f"user Pod 意外消失: {name}")
            labels = pod.metadata.labels or {}
            if labels.get(_LABEL_ISOLATION) != "2":
                raise RuntimeError("旧版用户容器仍在运行，请先停止旧容器再升级；数据卷会保留")
            state = _pod_state(pod)
            last = state
            if state.ready and state.pod_ip:
                return state
            # Failed/Succeeded 不会自愈到 Ready（restart_policy 只管容器重启）
            if state.phase in ("Failed", "Succeeded"):
                break
            time.sleep(1.0)
        phase = last.phase if last else "Unknown"
        raise RuntimeError(
            f"user Pod 未在 {int(timeout)}s 内就绪: {name} phase={phase} "
            f"(events: kubectl -n {self._namespace} describe pod {name})"
        )

    def ensure(self, user_id: str, safe: str, env: dict) -> str:
        """幂等启动 user Pod，返回可寻址的 Pod IP。

        - 已存在且归属匹配：等待 Ready 并返回当前 IP（IP 可能因重建而变化）
        - 已存在但非隔离版本 v2 / 归属不符：直接报错（与 docker 模式一致）
        - 不存在：创建 PVC + Pod 后等待 Ready
        """
        from kubernetes.client import ApiException

        name = f"eido-user-{safe}"
        self._ensure_pvc(user_id, safe)

        existing = self._get_pod(name)
        if existing is not None:
            labels = existing.metadata.labels or {}
            if labels.get(_LABEL_USER) != user_id:
                raise RuntimeError("拒绝复用不属于当前用户的容器")
            if labels.get(_LABEL_ISOLATION) != "2":
                raise RuntimeError("旧版用户容器仍在运行，请先停止旧容器再升级；数据卷会保留")
            if existing.metadata.deletion_timestamp is None and _pod_state(existing).phase in (
                "Failed",
                "Succeeded",
            ):
                # 终态 Pod 不会恢复，删除后走重建
                self._delete_pod(name)
            else:
                state = self._wait_ready(name, timeout=settings.EIDO_K8S_POD_READY_TIMEOUT)
                logger.info(f"复用 user Pod {name} ip={state.pod_ip}")
                return state.pod_ip

        pod = self._build_pod(user_id, safe, name, env)
        try:
            self._core.create_namespaced_pod(self._namespace, pod)
        except ApiException as e:
            if e.status != 409:
                raise
            # 并发竞态：另一请求已创建，等待其就绪即可
            logger.info(f"user Pod 已被并发创建: {name}")
        state = self._wait_ready(name, timeout=settings.EIDO_K8S_POD_READY_TIMEOUT)
        logger.info(f"启动 user Pod user={user_id} name={name} ip={state.pod_ip}")
        return state.pod_ip

    def _delete_pod(self, name: str) -> None:
        from kubernetes.client import ApiException

        try:
            self._core.delete_namespaced_pod(
                name,
                self._namespace,
                grace_period_seconds=30,  # 与 docker stop timeout=30 对齐
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def stop(self, user_id: str, safe: str) -> bool:
        """删除 user Pod（PVC 保留）。归属不符时抛错。"""
        name = f"eido-user-{safe}"
        pod = self._get_pod(name)
        if pod is None:
            return False
        labels = pod.metadata.labels or {}
        if labels.get(_LABEL_USER) != user_id:
            raise RuntimeError("拒绝停止归属不匹配的容器")
        self._delete_pod(name)
        return True

    def is_running(self, user_id: str, safe: str) -> bool:
        """Pod 存在且未处于删除中。"""
        name = f"eido-user-{safe}"
        pod = self._get_pod(name)
        if pod is None:
            return False
        return pod.metadata.deletion_timestamp is None and _pod_state(pod).phase in (
            "Pending",
            "Running",
        )
