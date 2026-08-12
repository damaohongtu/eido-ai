"""Static deployment invariants required for persistent Project data."""
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_default_compose_persists_eido_data_root():
    compose_path = REPOSITORY_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    service = compose["services"]["eido"]

    assert "EIDO_DATA_ROOT=/data" in service["environment"]
    assert "eido-data:/data" in service["volumes"]
    assert compose["volumes"]["eido-data"]["name"] == "eido-data"


def test_sandbox_volumes_remain_separate_from_single_container_data():
    compose_path = REPOSITORY_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    gateway = compose["services"]["eido-gateway"]

    assert "eido-gateway-data:/workspace/.eido" in gateway["volumes"]
    assert "eido-data:/data" not in gateway["volumes"]
    assert compose["volumes"]["eido-gateway-data"]["name"] == "eido-gateway-data"


def test_project_quota_configuration_is_available_in_both_compose_profiles():
    compose_path = REPOSITORY_ROOT / "docker" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    keys = {
        "EIDO_PROJECT_MAX_FILES",
        "EIDO_PROJECT_MAX_BYTES",
        "EIDO_USER_PROJECT_MAX_FILES",
        "EIDO_USER_PROJECT_MAX_BYTES",
    }

    for service_name in ("eido", "eido-gateway"):
        configured = {
            item.split("=", 1)[0]
            for item in compose["services"][service_name]["environment"]
        }
        assert keys <= configured

    sandbox_manager = (
        REPOSITORY_ROOT / "backend" / "app" / "gateway" / "sandbox_manager.py"
    ).read_text(encoding="utf-8")
    for key in keys:
        assert f'"{key}"' in sandbox_manager


def test_container_proxy_accepts_project_file_limit_with_multipart_overhead():
    nginx = (REPOSITORY_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")

    assert "client_max_body_size 25M;" in nginx


def test_runtime_images_include_pdf_tooling_and_cjk_fonts():
    requirements = (REPOSITORY_ROOT / "backend" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    for package in (
        "PyMuPDF==",
        "pypdf==",
        "pdfplumber==",
        "reportlab==",
        "fpdf2==",
        "python-docx==",
        "python-pptx==",
    ):
        assert package in requirements

    for filename in ("app.Dockerfile", "gateway.Dockerfile", "user.Dockerfile"):
        dockerfile = (REPOSITORY_ROOT / "docker" / filename).read_text(
            encoding="utf-8"
        )
        assert "poppler-utils" in dockerfile
        assert "fonts-noto-cjk" in dockerfile


def test_frontend_and_backend_share_the_same_rich_file_extensions():
    from app.services.supported_files import SUPPORTED_FILE_EXTENSIONS

    source = (
        REPOSITORY_ROOT / "frontend" / "utils" / "supportedFiles.ts"
    ).read_text(encoding="utf-8")
    frontend_extensions = {
        token
        for token in source.replace("'", '"').split('"')[1::2]
        if token.isalnum() and token.lower() == token
    }
    assert frontend_extensions == {
        extension.removeprefix(".") for extension in SUPPORTED_FILE_EXTENSIONS
    }

    mobile_source = (
        REPOSITORY_ROOT / "frontend-mobile" / "src" / "utils" / "supportedFiles.ts"
    ).read_text(encoding="utf-8")
    assert "../../../frontend/utils/supportedFiles" in mobile_source
