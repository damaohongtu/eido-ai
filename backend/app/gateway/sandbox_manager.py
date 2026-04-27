"""
Sandbox Manager — 每用户独立 FastAPI 容器编排。

- ensure_running(user_id) 幂等启动并返回 SandboxHandle
- release(user_id) 标记最近一次活跃时间，由 idle_gc_loop 决定是否回收
- idle_gc_loop() 周期扫描 sandbox_registry.db，对 last_active_at 超过
  EIDO_SANDBOX_IDLE_TTL 的容器执行 stop+remove，volumes 永远保留

容器命名规则：`eido-user-<safe_user_id>`，user_id 走 _safe_user_id 白名单后再拼接，
原始 user_id 仍记录在 registry.user_id 字段中。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_SAFE_REPLACE_RE = re.compile(r"[^A-Za-z0-9_\-]")


def _safe_user_id(user_id: str) -> str:
    """把 CAS 用户 ID 规范化为 docker-friendly 字符集。
    规则：仅保留 [A-Za-z0-9_-]，其余替换为 -，截断到 32 位，再追加 8 位 hash 后缀
    避免冲突。"""
    if not user_id:
        raise ValueError("user_id 为空")
    if _USER_ID_RE.match(user_id):
        return user_id[:48]
    base = _SAFE_REPLACE_RE.sub("-", user_id)[:32].strip("-") or "user"
    import hashlib
    suffix = hashlib.sha1(user_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{suffix}"


@dataclass
class SandboxHandle:
    user_id: str
    container_name: str
    internal_host: str
    internal_port: int
    status: str
    last_active_at: float

    @property
    def base_url(self) -> str:
        return f"http://{self.internal_host}:{self.internal_port}"


_REGISTRY_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS sandbox_registry (
        user_id TEXT PRIMARY KEY,
        safe_user_id TEXT NOT NULL,
        container_name TEXT NOT NULL,
        internal_host TEXT NOT NULL,
        internal_port INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'unknown',
        last_active_at REAL NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SandboxManager:
    """Per-user docker sandbox lifecycle.

    Local mode：sandbox 关闭，调用方仍可通过 ensure_running 拿到一个指向自身的
    SandboxHandle，方便单租户走相同的代码路径。
    """

    def __init__(self, *, mode: Optional[str] = None):
        self._mode = (mode or settings.EIDO_SANDBOX_MODE or "local").lower()
        self._db_path = str(settings.sandbox_registry_db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._docker = None
        self._lock = threading.RLock()
        self._gc_task: Optional[asyncio.Task] = None
        self._gc_stop = asyncio.Event()
        self._user_locks: dict[str, asyncio.Lock] = {}

    # -------------------------------------------------------------- #
    #  Lifecycle                                                       #
    # -------------------------------------------------------------- #

    def connect(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        for sql in _REGISTRY_SCHEMA:
            self._conn.execute(sql)
        self._conn.commit()
        logger.info(f"SandboxManager registry connected: {self._db_path} mode={self._mode}")

        if self._mode == "docker":
            secret = (settings.EIDO_GATEWAY_SECRET or "").strip()
            if not secret or len(secret) < 16:
                # 没有共享密钥则受信网关头会被 user 容器拒绝，业务全报 401
                logger.error(
                    "✗ EIDO_SANDBOX_MODE=docker 但 EIDO_GATEWAY_SECRET 未配置/过短（< 16 字符）"
                )
                raise RuntimeError(
                    "EIDO_GATEWAY_SECRET 未配置或过短，gateway 拒绝以 docker 模式启动"
                )
            if (settings.SESSION_SECRET_KEY or "") in (
                "", "dev-secret-change-in-production"
            ):
                raise RuntimeError(
                    "docker 沙箱模式禁止使用默认 SESSION_SECRET_KEY，请显式配置随机密钥"
                )
            try:
                import docker  # type: ignore
                self._docker = docker.from_env()
                self._docker.ping()
                logger.info("✓ Docker SDK 就绪")
            except Exception as e:
                logger.error(f"✗ Docker SDK 初始化失败，sandbox 将退化为 local 模式: {e}")
                self._mode = "local"
                self._docker = None

        if self._mode == "docker":
            try:
                self._ensure_network()
            except Exception as e:
                logger.warning(f"创建 docker network 失败（继续运行）：{e}")

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def mode(self) -> str:
        return self._mode

    # -------------------------------------------------------------- #
    #  Public API                                                      #
    # -------------------------------------------------------------- #

    async def ensure_running(self, user_id: str) -> SandboxHandle:
        """幂等启动并返回 user 容器句柄；本地模式返回指向自身的 handle。"""
        if not user_id:
            raise ValueError("user_id 为空")

        lock = self._user_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            if self._mode != "docker":
                return self._build_local_handle(user_id)

            handle = await asyncio.to_thread(self._ensure_running_docker, user_id)
            await asyncio.to_thread(self._wait_health, handle)
            return handle

    def release(self, user_id: str) -> None:
        """更新 last_active_at（无副作用）。"""
        with self._lock:
            row = self._select_row(user_id)
            if not row:
                return
            self._touch(user_id)

    async def stop(self, user_id: str) -> bool:
        """显式停止 + 移除容器。volume 不删除。"""
        if self._mode != "docker":
            return False
        return await asyncio.to_thread(self._stop_docker, user_id)

    def list_active(self) -> list[SandboxHandle]:
        rows = self._conn.execute(
            "SELECT * FROM sandbox_registry WHERE status = 'running' ORDER BY last_active_at DESC"
        ).fetchall() if self._conn else []
        return [self._row_to_handle(r) for r in rows]

    # -------------------------------------------------------------- #
    #  Idle GC                                                         #
    # -------------------------------------------------------------- #

    async def start_idle_gc(self) -> None:
        if self._mode != "docker":
            return
        if self._gc_task is not None and not self._gc_task.done():
            return
        self._gc_stop.clear()
        self._gc_task = asyncio.create_task(self._idle_gc_loop())
        logger.info(f"sandbox idle gc started, ttl={settings.EIDO_SANDBOX_IDLE_TTL}s")

    async def stop_idle_gc(self) -> None:
        self._gc_stop.set()
        if self._gc_task:
            try:
                await asyncio.wait_for(self._gc_task, timeout=5)
            except Exception:
                pass
            self._gc_task = None

    async def _idle_gc_loop(self) -> None:
        ttl = max(60, int(settings.EIDO_SANDBOX_IDLE_TTL or 900))
        try:
            while not self._gc_stop.is_set():
                try:
                    await asyncio.wait_for(self._gc_stop.wait(), timeout=60)
                    break  # stop signaled
                except asyncio.TimeoutError:
                    pass
                try:
                    await asyncio.to_thread(self._run_gc_pass, ttl)
                except Exception as e:
                    logger.warning(f"sandbox gc 异常：{e}")
        except asyncio.CancelledError:
            pass

    def _run_gc_pass(self, ttl: int) -> None:
        if not self._conn:
            return
        cutoff = time.time() - ttl
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_id FROM sandbox_registry WHERE status = 'running' AND last_active_at < ?",
                (cutoff,),
            ).fetchall()
            stale_users = [r["user_id"] for r in rows]

        for uid in stale_users:
            try:
                self._stop_docker(uid)
                logger.info(f"[sandbox-gc] 回收闲置容器 user={uid}")
            except Exception as e:
                logger.warning(f"[sandbox-gc] 回收 {uid} 失败: {e}")

    # -------------------------------------------------------------- #
    #  Internal                                                        #
    # -------------------------------------------------------------- #

    def _build_local_handle(self, user_id: str) -> SandboxHandle:
        """local 模式：所有用户共享当前进程，handle 指向自身。"""
        h = SandboxHandle(
            user_id=user_id,
            container_name="eido-local",
            internal_host="127.0.0.1",
            internal_port=settings.EIDO_USER_INTERNAL_PORT,
            status="running",
            last_active_at=time.time(),
        )
        return h

    def _ensure_network(self) -> None:
        if not self._docker:
            return
        net = settings.EIDO_NET
        existing = self._docker.networks.list(names=[net])
        if not existing:
            self._docker.networks.create(net, driver="bridge")
            logger.info(f"docker network 创建: {net}")

    def _ensure_running_docker(self, user_id: str) -> SandboxHandle:
        assert self._docker is not None
        safe = _safe_user_id(user_id)
        container_name = f"eido-user-{safe}"

        existing = self._find_container(container_name)
        if existing is not None:
            existing.reload()
            if existing.status == "running":
                self._upsert_row(user_id, safe, container_name, container_name)
                return self._build_handle_from_row(user_id)
            try:
                existing.start()
                logger.info(f"复用已停止容器: {container_name}")
                self._upsert_row(user_id, safe, container_name, container_name)
                return self._build_handle_from_row(user_id)
            except Exception as e:
                logger.warning(f"启动停止中的容器失败 {container_name}: {e}; 将重建")
                try:
                    existing.remove(force=True)
                except Exception:
                    pass

        return self._create_container(user_id, safe, container_name)

    def _find_container(self, name: str):
        try:
            return self._docker.containers.get(name)  # type: ignore
        except Exception:
            return None

    def _host_claude_dir_from_gateway_mount(self) -> str | None:
        """Return the host-side source path mounted at /workspace/.claude.

        The Docker daemon validates bind sources on the host, not inside the
        gateway container. Inspecting the gateway container's own mounts gives
        us the real host path even when CLAUDE_DIR was configured as "~/.claude".
        """
        if not self._docker:
            return None
        container_id = os.environ.get("HOSTNAME", "").strip()
        if not container_id:
            return None
        try:
            current = self._docker.containers.get(container_id)  # type: ignore
            current.reload()
            for mount in current.attrs.get("Mounts", []):
                if (
                    mount.get("Destination") == "/workspace/.claude"
                    and mount.get("Type") == "bind"
                ):
                    source = mount.get("Source")
                    return str(source) if source else None
        except Exception as e:
            logger.warning("反查 gateway .claude 宿主挂载失败: %s", e)
        return None

    def _resolve_host_skills_dir(self) -> str | None:
        """Resolve a host-side path suitable for Docker bind-mount Source."""
        skills_dir = settings.SKILLS_DIR
        if not skills_dir or not Path(skills_dir).exists():
            return None

        mounted_claude_dir = self._host_claude_dir_from_gateway_mount()
        if mounted_claude_dir:
            return str(Path(mounted_claude_dir) / "skills")

        host_claude_dir = os.environ.get("CLAUDE_DIR", "").strip()
        if host_claude_dir:
            if host_claude_dir.startswith("~"):
                logger.warning(
                    "CLAUDE_DIR=%r 仍包含 ~，无法作为 Docker daemon 的宿主机路径；"
                    "请在启动 compose 前展开为绝对路径",
                    host_claude_dir,
                )
                return None
            candidate = Path(host_claude_dir)
            candidate_str = str(candidate)
            if (
                candidate.is_absolute()
                and candidate_str != "/workspace"
                and not candidate_str.startswith("/workspace/")
            ):
                return str(candidate / "skills")
            logger.warning(
                "CLAUDE_DIR=%r 不是可传给 Docker daemon 的宿主机绝对路径，跳过 user skills bind-mount",
                host_claude_dir,
            )
            return None

        logger.warning(
            "未配置 CLAUDE_DIR，且无法从 gateway 容器挂载中反查宿主机 .claude；跳过 user skills bind-mount"
        )
        return None

    def _create_container(self, user_id: str, safe: str, name: str) -> SandboxHandle:
        assert self._docker is not None
        from docker.types import Mount  # type: ignore

        env = {
            "EIDO_USER_ID": user_id,
            "EIDO_DATA_ROOT": "/data",
            "EIDO_TRUST_GATEWAY": "1",
            "AUTH_DISABLED": "True",
            "WORKSPACE_ROOT": "/workspace",
            "EIDO_GATEWAY_SECRET": settings.EIDO_GATEWAY_SECRET,
        }
        # 透传 LLM 凭据
        for k in (
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_MODEL",
            "ANTHROPIC_SMALL_FAST_MODEL",
            "API_TIMEOUT_MS",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
        ):
            v = os.environ.get(k)
            if v:
                env[k] = v

        volume_name = f"eido-user-{safe}"
        mounts: list[Mount] = [Mount("/data", volume_name, type="volume")]
        # 技能库分两区挂载：
        #   - system（admin 上传 / 内置）：ro，所有用户共享只读
        #   - users/<safe>：rw，只挂当前用户私有目录，避免泄露其他用户技能
        # Docker bind-mount Source 必须是宿主侧路径，不能是容器内路径；
        # 优先从 gateway 自身 mount 反查宿主路径，避免误用 /workspace/.claude/skills。
        host_skills = self._resolve_host_skills_dir()
        if host_skills:
            host_system = str(Path(host_skills) / "system")
            host_user = str(Path(host_skills) / "users" / safe)
            # gateway 容器内通过挂载视图等价创建宿主目录，确保 bind-mount 能找到 source
            try:
                local_skills = Path(settings.SKILLS_DIR)
                (local_skills / "system").mkdir(parents=True, exist_ok=True)
                (local_skills / "users" / safe).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning("准备 skills 子目录失败（继续尝试挂载）: %s", e)
            mounts.append(
                Mount(
                    "/workspace/.claude/skills/system",
                    host_system,
                    type="bind",
                    read_only=True,
                )
            )
            mounts.append(
                Mount(
                    f"/workspace/.claude/skills/users/{safe}",
                    host_user,
                    type="bind",
                    read_only=False,
                )
            )

        try:
            cpus = float(settings.EIDO_USER_CPUS or 1.0)
        except Exception:
            cpus = 1.0
        nano_cpus = int(cpus * 1e9)
        mem = settings.EIDO_USER_MEM or "2g"
        pids = int(settings.EIDO_USER_PIDS_LIMIT or 500)

        kwargs = dict(
            image=settings.EIDO_USER_IMAGE,
            name=name,
            detach=True,
            network=settings.EIDO_NET,
            environment=env,
            mounts=mounts,
            mem_limit=mem,
            nano_cpus=nano_cpus,
            pids_limit=pids,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            tmpfs={"/tmp": "size=64m,mode=1777"},
            restart_policy={"Name": "unless-stopped"},
            labels={
                "io.eido.role": "user-sandbox",
                "io.eido.user_id": user_id,
            },
        )
        logger.info(f"启动 user 容器 user={user_id} name={name} image={settings.EIDO_USER_IMAGE}")
        c = self._docker.containers.run(**kwargs)
        host = name  # docker DNS：容器名即可解析
        self._upsert_row(user_id, safe, name, host)
        return self._build_handle_from_row(user_id)

    def _stop_docker(self, user_id: str) -> bool:
        assert self._docker is not None
        row = self._select_row(user_id)
        if not row:
            return False
        name = row["container_name"]
        c = self._find_container(name)
        if c is not None:
            try:
                c.stop(timeout=5)
            except Exception:
                pass
            try:
                c.remove(force=True)
            except Exception:
                pass
        self._mark_status(user_id, "stopped")
        return True

    def _wait_health(self, handle: SandboxHandle, *, timeout: float = 30.0) -> None:
        """轮询 user 容器的 /health；超时抛 RuntimeError。"""
        if self._mode != "docker":
            return
        import httpx
        deadline = time.time() + timeout
        url = f"{handle.base_url}/health"
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                with httpx.Client(timeout=2.0) as client:
                    r = client.get(url)
                    if r.status_code == 200:
                        self._mark_status(handle.user_id, "running")
                        return
            except Exception as e:
                last_err = e
            time.sleep(0.4)
        raise RuntimeError(
            f"user 容器健康检查超时: {handle.container_name} ({last_err})"
        )

    # -------------------------------------------------------------- #
    #  SQLite helpers                                                  #
    # -------------------------------------------------------------- #

    def _upsert_row(self, user_id: str, safe: str, name: str, host: str) -> None:
        if not self._conn:
            return
        now_iso = _now_iso()
        now_ts = time.time()
        with self._lock:
            self._conn.execute(
                "INSERT INTO sandbox_registry (user_id, safe_user_id, container_name, internal_host,"
                " internal_port, status, last_active_at, created_at, updated_at) VALUES"
                " (?, ?, ?, ?, ?, 'running', ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET"
                " safe_user_id=excluded.safe_user_id,"
                " container_name=excluded.container_name,"
                " internal_host=excluded.internal_host,"
                " internal_port=excluded.internal_port,"
                " status='running',"
                " last_active_at=excluded.last_active_at,"
                " updated_at=excluded.updated_at",
                (
                    user_id, safe, name, host,
                    settings.EIDO_USER_INTERNAL_PORT,
                    now_ts, now_iso, now_iso,
                ),
            )
            self._conn.commit()

    def _select_row(self, user_id: str):
        if not self._conn:
            return None
        return self._conn.execute(
            "SELECT * FROM sandbox_registry WHERE user_id = ?", (user_id,)
        ).fetchone()

    def _touch(self, user_id: str) -> None:
        if not self._conn:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sandbox_registry SET last_active_at=?, updated_at=? WHERE user_id=?",
                (time.time(), _now_iso(), user_id),
            )
            self._conn.commit()

    def _mark_status(self, user_id: str, status: str) -> None:
        if not self._conn:
            return
        with self._lock:
            self._conn.execute(
                "UPDATE sandbox_registry SET status=?, updated_at=? WHERE user_id=?",
                (status, _now_iso(), user_id),
            )
            self._conn.commit()

    def _build_handle_from_row(self, user_id: str) -> SandboxHandle:
        row = self._select_row(user_id)
        if not row:
            raise RuntimeError(f"sandbox registry 缺失 user_id={user_id}")
        return self._row_to_handle(row)

    def _row_to_handle(self, row) -> SandboxHandle:
        return SandboxHandle(
            user_id=row["user_id"],
            container_name=row["container_name"],
            internal_host=row["internal_host"],
            internal_port=int(row["internal_port"] or settings.EIDO_USER_INTERNAL_PORT),
            status=row["status"] or "unknown",
            last_active_at=float(row["last_active_at"] or 0),
        )


_instance: Optional[SandboxManager] = None


def get_sandbox_manager() -> SandboxManager:
    if _instance is None:
        raise RuntimeError("SandboxManager 尚未初始化")
    return _instance


def init_sandbox_manager(*, mode: Optional[str] = None) -> SandboxManager:
    global _instance
    _instance = SandboxManager(mode=mode)
    _instance.connect()
    return _instance
