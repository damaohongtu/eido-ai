"""K8s 沙盒编排后端单元测试（纯 mock，无需真实集群）。

覆盖：
- ensure() 创建 PVC + Pod 的规格（env 透传 / mounts / securityContext / resources）
- 幂等复用、归属校验（拒绝复用他人 Pod / PVC）
- stop() 只删 Pod 保留 PVC
- _wait_ready 超时与终态分支
- SandboxManager k8s 模式分派（registry 记录 Pod IP、_stop_backend 走 K8s）
"""

from __future__ import annotations

import pytest
from kubernetes import client as k8s_client
from kubernetes.client import ApiException

from app.gateway import sandbox_k8s
from app.gateway.sandbox_k8s import K8sSandboxClient
from app.gateway.sandbox_manager import SandboxManager

USER_ENV = {
    "EIDO_USER_ID": "alice",
    "EIDO_TRUST_GATEWAY": "1",
    "EIDO_GATEWAY_SECRET": "unit-test-secret",
}


class FakeCluster:
    """内存版 Pod / PVC 存储，记录创建与删除动作。"""

    def __init__(self):
        self.pods: dict[str, object] = {}
        self.pvcs: dict[str, object] = {}
        self.created_pods: list = []
        self.created_pvcs: list = []
        self.deleted_pods: list = []

    def add_ready_pod(self, name: str, user_id: str, ip: str, *, version: str = "2"):
        self.pods[name] = make_pod(name, user_id, ip, phase="Running", version=version)
        return self.pods[name]

    def add_pvc(self, name: str, user_id: str | None):
        self.pvcs[name] = k8s_client.V1PersistentVolumeClaim(
            metadata=k8s_client.V1ObjectMeta(
                name=name,
                labels={"io.eido.user_id": user_id} if user_id else {},
            )
        )
        return self.pvcs[name]


class FakeCoreV1Api:
    def __init__(self, cluster: FakeCluster):
        self.cluster = cluster

    def list_namespaced_pod(self, namespace, **kwargs):
        return list(self.cluster.pods.values())

    def read_namespaced_pod(self, name, namespace):
        pod = self.cluster.pods.get(name)
        if pod is None:
            raise ApiException(status=404, reason="Not Found")
        return pod

    def create_namespaced_pod(self, namespace, pod):
        if pod.metadata.name in self.cluster.pods:
            raise ApiException(status=409, reason="Conflict")
        # 模拟调度器 + kubelet：创建后分配 IP 并转 Ready
        pod.status = k8s_client.V1PodStatus(
            phase="Running",
            pod_ip="10.42.0.99",
            conditions=[k8s_client.V1PodCondition(type="Ready", status="True")],
        )
        self.cluster.pods[pod.metadata.name] = pod
        self.cluster.created_pods.append(pod)
        return pod

    def delete_namespaced_pod(self, name, namespace, **kwargs):
        if name not in self.cluster.pods:
            raise ApiException(status=404, reason="Not Found")
        self.cluster.deleted_pods.append(name)
        del self.cluster.pods[name]
        return None

    def read_namespaced_persistent_volume_claim(self, name, namespace):
        pvc = self.cluster.pvcs.get(name)
        if pvc is None:
            raise ApiException(status=404, reason="Not Found")
        return pvc

    def create_namespaced_persistent_volume_claim(self, namespace, pvc):
        if pvc.metadata.name in self.cluster.pvcs:
            raise ApiException(status=409, reason="Conflict")
        self.cluster.pvcs[pvc.metadata.name] = pvc
        self.cluster.created_pvcs.append(pvc)
        return pvc


def make_pod(
    name: str,
    user_id: str,
    ip: str | None,
    *,
    phase: str = "Running",
    version: str = "2",
    ready: bool = True,
):
    return k8s_client.V1Pod(
        metadata=k8s_client.V1ObjectMeta(
            name=name,
            labels={
                "io.eido.role": "user-sandbox",
                "io.eido.isolation_version": version,
                "io.eido.user_id": user_id,
            },
        ),
        status=k8s_client.V1PodStatus(
            phase=phase,
            pod_ip=ip,
            conditions=[k8s_client.V1PodCondition(type="Ready", status="True" if ready else "False")],
        ),
    )


@pytest.fixture
def cluster():
    return FakeCluster()


@pytest.fixture
def k8s_sandbox(cluster, monkeypatch: pytest.MonkeyPatch):
    """绕过 connect()，直接注入 FakeCoreV1Api 的客户端。"""
    client = K8sSandboxClient(namespace="eido-test")
    client._core = FakeCoreV1Api(cluster)
    return client


# ------------------------------------------------------------------ #
#  PVC + Pod 创建规格                                                 #
# ------------------------------------------------------------------ #


def test_ensure_creates_pvc_and_pod(k8s_sandbox, cluster):
    ip = k8s_sandbox.ensure("alice", "alice", USER_ENV)

    assert ip  # 返回可寻址 Pod IP
    assert len(cluster.created_pvcs) == 1
    pvc = cluster.created_pvcs[0]
    assert pvc.metadata.name == "eido-user-alice"
    assert pvc.metadata.labels["io.eido.user_id"] == "alice"
    assert pvc.spec.access_modes == ["ReadWriteOnce"]

    assert len(cluster.created_pods) == 1
    pod = cluster.created_pods[0]
    assert pod.metadata.name == "eido-user-alice"
    labels = pod.metadata.labels
    assert labels["io.eido.role"] == "user-sandbox"
    assert labels["io.eido.isolation_version"] == "2"
    assert labels["io.eido.user_id"] == "alice"

    (container,) = pod.spec.containers
    assert container.image_pull_policy == "IfNotPresent"
    env = {e.name: e.value for e in container.env}
    assert env == USER_ENV
    assert container.ports[0].container_port == 8000
    # resources：limits 来自 EIDO_USER_MEM / EIDO_USER_CPUS
    assert container.resources.limits["memory"] == "2Gi"
    assert float(container.resources.limits["cpu"]) == 1.0
    assert container.resources.requests["memory"] == "256Mi"

    # securityContext：docker read_only/cap_drop/no-new-privileges 的映射
    sec = container.security_context
    assert sec.run_as_non_root is True
    assert sec.read_only_root_filesystem is True
    assert sec.allow_privilege_escalation is False
    assert sec.capabilities.drop == ["ALL"]
    pod_sec = pod.spec.security_context
    assert (pod_sec.run_as_user, pod_sec.run_as_group, pod_sec.fs_group) == (10001, 10001, 10001)

    # 卷挂载：数据 PVC、共享 skills（subPath 双挂载）、内存 /tmp
    mounts = {m.name: m for m in container.volume_mounts}
    assert mounts["data"].mount_path == "/data"
    assert mounts["tmp"].mount_path == "/tmp"
    skill_mounts = sorted(
        (m for m in container.volume_mounts if m.name == "skills"),
        key=lambda m: m.sub_path,
    )
    assert [m.sub_path for m in skill_mounts] == ["system", "users/alice"]
    assert [m.read_only for m in skill_mounts] == [True, True]
    assert [m.mount_path for m in skill_mounts] == [
        "/workspace/.claude/skills/system",
        "/workspace/.claude/skills/users/alice",
    ]
    volumes = {v.name: v for v in pod.spec.volumes}
    assert volumes["data"].persistent_volume_claim.claim_name == "eido-user-alice"
    assert volumes["tmp"].empty_dir.medium == "Memory"
    assert pod.spec.restart_policy == "Always"


def test_ensure_reuses_ready_pod_without_recreate(k8s_sandbox, cluster):
    cluster.add_pvc("eido-user-alice", "alice")
    cluster.add_ready_pod("eido-user-alice", "alice", ip="10.1.2.3")

    ip = k8s_sandbox.ensure("alice", "alice", USER_ENV)

    assert ip == "10.1.2.3"
    assert cluster.created_pods == []
    assert cluster.created_pvcs == []


def test_ensure_rejects_foreign_pod(k8s_sandbox, cluster):
    cluster.add_ready_pod("eido-user-alice", "bob", ip="10.1.2.3")
    with pytest.raises(RuntimeError, match="拒绝复用不属于当前用户的容器"):
        k8s_sandbox.ensure("alice", "alice", USER_ENV)


def test_ensure_rejects_foreign_pvc(k8s_sandbox, cluster):
    cluster.add_pvc("eido-user-alice", "bob")
    with pytest.raises(RuntimeError, match="拒绝挂载其他用户的数据卷"):
        k8s_sandbox.ensure("alice", "alice", USER_ENV)


def test_ensure_rejects_unowned_pvc(k8s_sandbox, cluster):
    cluster.add_pvc("eido-user-alice", None)
    with pytest.raises(RuntimeError, match="无法确认旧数据卷归属"):
        k8s_sandbox.ensure("alice", "alice", USER_ENV)


def test_ensure_rejects_legacy_isolation_pod(k8s_sandbox, cluster):
    cluster.add_ready_pod("eido-user-alice", "alice", ip="10.1.2.3", version="1")
    with pytest.raises(RuntimeError, match="旧版用户容器"):
        k8s_sandbox.ensure("alice", "alice", USER_ENV)


# ------------------------------------------------------------------ #
#  stop / 等待就绪                                                     #
# ------------------------------------------------------------------ #


def test_stop_deletes_pod_preserves_pvc(k8s_sandbox, cluster):
    cluster.add_pvc("eido-user-alice", "alice")
    cluster.add_ready_pod("eido-user-alice", "alice", ip="10.1.2.3")

    assert k8s_sandbox.stop("alice", "alice") is True

    assert cluster.deleted_pods == ["eido-user-alice"]
    assert "eido-user-alice" in cluster.pvcs  # PVC 永远保留


def test_stop_missing_pod_returns_false(k8s_sandbox, cluster):
    assert k8s_sandbox.stop("alice", "alice") is False


def test_stop_rejects_foreign_pod(k8s_sandbox, cluster):
    cluster.add_ready_pod("eido-user-alice", "bob", ip="10.1.2.3")
    with pytest.raises(RuntimeError, match="拒绝停止归属不匹配的容器"):
        k8s_sandbox.stop("alice", "alice")


def test_wait_ready_times_out_on_pending_pod(k8s_sandbox, cluster, monkeypatch):
    cluster.pods["eido-user-alice"] = make_pod(
        "eido-user-alice", "alice", None, phase="Pending", ready=False
    )
    with pytest.raises(RuntimeError, match="未在 .* 内就绪"):
        k8s_sandbox._wait_ready("eido-user-alice", timeout=0.3)


def test_wait_ready_fails_fast_on_terminal_pod(k8s_sandbox, cluster):
    cluster.pods["eido-user-alice"] = make_pod(
        "eido-user-alice", "alice", None, phase="Failed", ready=False
    )
    with pytest.raises(RuntimeError, match="phase=Failed"):
        k8s_sandbox._wait_ready("eido-user-alice", timeout=30)


# ------------------------------------------------------------------ #
#  SandboxManager k8s 分派                                             #
# ------------------------------------------------------------------ #


@pytest.fixture
def k8s_manager(tmp_path, monkeypatch: pytest.MonkeyPatch, cluster):
    """k8s 模式的 SandboxManager，K8sSandboxClient 连接被替换为 Fake 注入。"""
    monkeypatch.setattr(settings_module(), "SANDBOX_REGISTRY_DB", str(tmp_path / "registry.db"))
    monkeypatch.setattr(K8sSandboxClient, "connect", lambda self: None)
    monkeypatch.setattr(
        settings_module(), "EIDO_GATEWAY_SECRET", "unit-test-gateway-secret-0123456789"
    )
    monkeypatch.setattr(settings_module(), "SESSION_SECRET_KEY", "unit-test-session-secret")
    monkeypatch.setattr(
        settings_module(),
        "CLAUDE_MODEL_CATALOG_JSON",
        '{"default":"m","models":[{"id":"m","label":"M","model":"test-model"}]}',
    )
    monkeypatch.setattr(settings_module(), "EIDO_USER_TOKEN_SECRET", "")

    manager = SandboxManager(mode="k8s")
    manager.connect()
    manager._k8s._core = FakeCoreV1Api(cluster)
    return manager


def settings_module():
    from app.core.config import settings

    return settings


def test_manager_k8s_dispatch_records_pod_ip(k8s_manager, cluster):
    handle = k8s_manager._ensure_running_k8s("alice")

    assert handle.internal_host  # Pod IP，非容器名
    assert handle.base_url == f"http://{handle.internal_host}:8000"
    assert handle.container_name == "eido-user-alice"
    row = k8s_manager._select_row("alice")
    assert row["internal_host"] == handle.internal_host
    assert row["status"] == "running"


def test_manager_k8s_stop_backend(k8s_manager, cluster):
    k8s_manager._ensure_running_k8s("alice")

    assert k8s_manager._stop_backend("alice") is True

    assert cluster.deleted_pods == ["eido-user-alice"]
    assert "eido-user-alice" in cluster.pvcs
    assert k8s_manager._select_row("alice")["status"] == "stopped"


def test_manager_k8s_stop_skipped_when_lease_held(k8s_manager, cluster):
    k8s_manager._ensure_running_k8s("alice")
    k8s_manager.retain("alice")  # 活跃请求租约

    assert k8s_manager._stop_backend("alice") is False
    assert cluster.deleted_pods == []


def test_manager_user_env_shared_between_backends(k8s_manager):
    """_build_user_env 同时服务 docker / k8s：关键注入项齐全。"""
    env = k8s_manager._build_user_env("alice")
    assert env["EIDO_USER_ID"] == "alice"
    assert env["EIDO_TRUST_GATEWAY"] == "1"
    assert env["EIDO_DATA_ROOT"] == "/data"
    assert env["EIDO_API_URL"]  # gateway 内部地址
    assert env["EIDO_GATEWAY_SECRET"]
    assert env["EIDO_USER_TOKEN_SECRET"]
    assert "CLAUDE_MODEL_CATALOG_JSON" in env
