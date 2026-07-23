"""Process-local execution guard for chat sessions and Projects."""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProjectLease:
    """Opaque lease returned by a Project-level guard acquisition."""

    project_id: str
    token: str
    exclusive: bool


class ChatExecutionGuard:
    """Coordinate session single-flight with Project readers/writers.

    Provider-native resume stores and OpenHarness engines are session-scoped and
    are not safe to mutate concurrently. Deployments currently run one backend
    process per user container, so a process-local guard matches that boundary.

    A chat execution owns its session exclusively and, when assigned, holds a
    shared lease on its Project. Short mutations such as creating or moving a
    session into a Project use an explicit shared lease. Destructive Project/file
    operations take an exclusive lease, which blocks both existing readers and
    new readers without serializing chats in different sessions of one Project.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[str] = set()
        self._session_project_leases: dict[str, ProjectLease] = {}
        self._project_readers: dict[str, set[str]] = {}
        self._project_writers: dict[str, str] = {}
        self._active_upload_users: set[str] = set()

    def try_acquire(
        self, session_id: str, *, project_id: Optional[str] = None
    ) -> bool:
        """Acquire a session and its optional Project reader atomically."""
        with self._lock:
            if session_id in self._active:
                return False
            if project_id is not None and project_id in self._project_writers:
                return False

            self._active.add(session_id)
            if project_id is not None:
                lease = ProjectLease(
                    project_id=project_id,
                    token=f"session:{session_id}",
                    exclusive=False,
                )
                self._project_readers.setdefault(project_id, set()).add(lease.token)
                self._session_project_leases[session_id] = lease
            return True

    def try_acquire_many(self, session_ids: list[str]) -> bool:
        unique_ids = set(session_ids)
        with self._lock:
            if self._active.intersection(unique_ids):
                return False
            self._active.update(unique_ids)
            return True

    def release(self, session_id: str) -> None:
        with self._lock:
            self._active.discard(session_id)
            lease = self._session_project_leases.pop(session_id, None)
            if lease is not None:
                self._release_project_lease_locked(lease)

    def release_many(self, session_ids: list[str]) -> None:
        with self._lock:
            for session_id in set(session_ids):
                self._active.discard(session_id)
                lease = self._session_project_leases.pop(session_id, None)
                if lease is not None:
                    self._release_project_lease_locked(lease)

    def try_acquire_project_shared(self, project_id: str) -> Optional[ProjectLease]:
        """Acquire a short Project reader lease, or return ``None`` if frozen."""
        with self._lock:
            if project_id in self._project_writers:
                return None
            lease = ProjectLease(
                project_id=project_id,
                token=f"shared:{uuid.uuid4().hex}",
                exclusive=False,
            )
            self._project_readers.setdefault(project_id, set()).add(lease.token)
            return lease

    def try_acquire_project_exclusive(self, project_id: str) -> Optional[ProjectLease]:
        """Freeze a Project when it has no readers; unrelated Projects remain free."""
        with self._lock:
            if project_id in self._project_writers:
                return None
            if self._project_readers.get(project_id):
                return None
            lease = ProjectLease(
                project_id=project_id,
                token=f"exclusive:{uuid.uuid4().hex}",
                exclusive=True,
            )
            self._project_writers[project_id] = lease.token
            return lease

    def release_project(self, lease: ProjectLease) -> None:
        """Release exactly the Project lease returned by this guard."""
        with self._lock:
            self._release_project_lease_locked(lease)

    def _release_project_lease_locked(self, lease: ProjectLease) -> None:
        if lease.exclusive:
            if self._project_writers.get(lease.project_id) == lease.token:
                del self._project_writers[lease.project_id]
            return

        readers = self._project_readers.get(lease.project_id)
        if readers is None:
            return
        readers.discard(lease.token)
        if not readers:
            del self._project_readers[lease.project_id]

    def is_active(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._active

    def is_project_frozen(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._project_writers

    def try_acquire_user_upload(self, user_id: str) -> bool:
        """Bound transient disk use to one Project upload/import per user."""
        with self._lock:
            if user_id in self._active_upload_users:
                return False
            self._active_upload_users.add(user_id)
            return True

    def release_user_upload(self, user_id: str) -> None:
        with self._lock:
            self._active_upload_users.discard(user_id)


_instance = ChatExecutionGuard()


def get_chat_execution_guard() -> ChatExecutionGuard:
    return _instance
