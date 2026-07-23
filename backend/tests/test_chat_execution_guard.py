"""Single-flight behavior for session-scoped agent executions."""

from app.services.chat_execution_guard import ChatExecutionGuard


def test_guard_rejects_same_session_until_release_but_allows_other_sessions():
    guard = ChatExecutionGuard()

    assert guard.try_acquire("session-a") is True
    assert guard.try_acquire("session-a") is False
    assert guard.try_acquire("session-b") is True

    guard.release("session-a")
    assert guard.try_acquire("session-a") is True

    guard.release("session-a")
    guard.release("session-b")


def test_guard_can_atomically_reserve_multiple_sessions():
    guard = ChatExecutionGuard()

    assert guard.try_acquire_many(["session-a", "session-b"]) is True
    assert guard.try_acquire("session-b") is False
    assert guard.try_acquire_many(["session-c", "session-a"]) is False

    guard.release_many(["session-a", "session-b"])
    assert guard.try_acquire_many(["session-a", "session-c"]) is True


def test_project_shared_leases_allow_parallel_sessions_but_block_exclusive_freeze():
    guard = ChatExecutionGuard()

    assert guard.try_acquire("session-a", project_id="project-a") is True
    assert guard.try_acquire("session-b", project_id="project-a") is True
    assert guard.try_acquire("session-c", project_id="project-b") is True

    assert guard.try_acquire_project_exclusive("project-a") is None
    project_c_freeze = guard.try_acquire_project_exclusive("project-c")
    assert project_c_freeze is not None

    guard.release("session-a")
    assert guard.try_acquire_project_exclusive("project-a") is None
    guard.release("session-b")

    project_a_freeze = guard.try_acquire_project_exclusive("project-a")
    assert project_a_freeze is not None
    guard.release_project(project_a_freeze)
    guard.release_project(project_c_freeze)
    guard.release("session-c")


def test_project_exclusive_freeze_blocks_new_chat_and_short_shared_lease():
    guard = ChatExecutionGuard()
    freeze = guard.try_acquire_project_exclusive("project-a")
    assert freeze is not None
    assert guard.is_project_frozen("project-a") is True

    assert guard.try_acquire("session-a", project_id="project-a") is False
    assert guard.try_acquire_project_shared("project-a") is None
    assert guard.try_acquire("session-b", project_id="project-b") is True

    guard.release_project(freeze)
    assert guard.is_project_frozen("project-a") is False
    shared = guard.try_acquire_project_shared("project-a")
    assert shared is not None
    assert guard.try_acquire_project_exclusive("project-a") is None
    guard.release_project(shared)
    guard.release("session-b")


def test_releasing_session_also_releases_its_project_reader():
    guard = ChatExecutionGuard()
    assert guard.try_acquire("session-a", project_id="project-a") is True

    guard.release_many(["session-a"])

    freeze = guard.try_acquire_project_exclusive("project-a")
    assert freeze is not None
    guard.release_project(freeze)


def test_user_upload_guard_serializes_one_users_transient_disk_writes():
    guard = ChatExecutionGuard()

    assert guard.try_acquire_user_upload("user-a") is True
    assert guard.try_acquire_user_upload("user-a") is False
    assert guard.try_acquire_user_upload("user-b") is True

    guard.release_user_upload("user-a")
    assert guard.try_acquire_user_upload("user-a") is True
    guard.release_user_upload("user-a")
    guard.release_user_upload("user-b")
