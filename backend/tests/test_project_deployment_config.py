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
