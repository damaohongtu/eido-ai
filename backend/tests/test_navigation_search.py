from pathlib import Path

from app.services.chat_session_store import ChatSessionStore


def test_search_navigation_finds_projects_titles_and_message_content(tmp_path: Path):
    store = ChatSessionStore(tmp_path / "sessions.db")
    store.connect()
    try:
        project = store.create_project("u1", name="Alpha 研究", description="半导体行业")
        session = store.create_session("u1", title="供应链讨论", project_id=project["id"])
        store.append_message(
            "u1", session["id"], role="user", content="重点分析先进封装", message_id="m1"
        )
        store.create_project("u2", name="Alpha private")

        by_project = store.search_navigation("u1", "半导体")
        assert [item["id"] for item in by_project["projects"]] == [project["id"]]
        assert by_project["sessions"] == []

        by_message = store.search_navigation("u1", "先进封装")
        assert [item["id"] for item in by_message["sessions"]] == [session["id"]]
        assert "先进封装" in by_message["sessions"][0]["match_snippet"]
        assert store.search_navigation("u2", "先进封装")["sessions"] == []
    finally:
        store.close()
