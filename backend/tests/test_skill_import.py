"""Skill package import through the HTTP entry point."""

import io
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import skills
from app.core.auth import get_current_user_id
from app.services.skills.catalog import SkillCatalog
from app.services.skills.management import SkillManagementService


def test_import_nested_skill_package_and_list_it(tmp_path, monkeypatch):
    changes = []
    catalog = SkillCatalog(tmp_path, changes.append)
    service = SkillManagementService(catalog)
    monkeypatch.setattr(skills, "get_skill_management_service", lambda: service)
    app = FastAPI()
    app.include_router(skills.router, prefix="/skills")
    app.dependency_overrides[get_current_user_id] = lambda: "skill-import-user"

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr(
            "bundle/research/SKILL.md",
            "---\nname: Research Notes\ndescription: Extract notes\n---\n",
        )
        archive.writestr("bundle/research/references/example.md", "Example")
    client = TestClient(app)
    response = client.post(
        "/skills/upload", files={"file": ("bundle.skill", bundle.getvalue(), "application/zip")}
    )
    assert response.status_code == 200
    assert response.json()["id"] == "research-notes"
    assert response.json()["owner_type"] == "user"
    assert changes == ["skill-import-user"]
    assert client.get("/skills/").json()["total"] == 1
    root = catalog.user_private_dir("skill-import-user")
    assert (root / "research-notes" / "references" / "example.md").read_text() == "Example"

    invalid = client.post(
        "/skills/upload", files={"file": ("invalid.zip", b"invalid archive", "application/zip")}
    )
    assert invalid.status_code == 400
    assert [path.name for path in root.iterdir()] == ["research-notes"]
