import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_DIR = ROOT / "umdu_haos_updater"


def test_dockerfile_uses_explicit_home_assistant_base_image():
    dockerfile = (ADDON_DIR / "Dockerfile").read_text(encoding="utf-8")
    from_lines = re.findall(r"(?m)^FROM\s+(.+)$", dockerfile)

    assert from_lines == ["ghcr.io/home-assistant/base:3.23"]
    assert "BUILD_FROM" not in dockerfile


def test_dockerfile_accepts_supervisor_build_args_as_metadata_only():
    dockerfile = (ADDON_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert 'ARG BUILD_VERSION="0.0.0"' in dockerfile
    assert 'ARG BUILD_ARCH="aarch64"' in dockerfile
    assert 'io.hass.version="${BUILD_VERSION}"' in dockerfile
    assert 'io.hass.arch="${BUILD_ARCH}"' in dockerfile
    assert not re.search(r"FROM\s+.*BUILD_(VERSION|ARCH)", dockerfile)


def test_dockerfile_uses_regional_package_mirrors():
    dockerfile = (ADDON_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "dl-cdn.alpinelinux.org" not in dockerfile
    assert 'ARG ALPINE_MIRROR="https://mirror.yandex.ru/mirrors/alpine"' in dockerfile
    assert "${ALPINE_MIRROR}/v3.23/main" in dockerfile
    assert "${ALPINE_MIRROR}/v3.23/community" in dockerfile
    assert '--repository="${ALPINE_MIRROR}/edge/testing"' in dockerfile
    assert 'ARG PIP_INDEX_URL="https://mirror.yandex.ru/pypi/web/simple"' in dockerfile
    assert '--index-url "${PIP_INDEX_URL}"' in dockerfile


def test_addon_config_supports_aarch64_without_ingress_or_extra_privileges():
    config = (ADDON_DIR / "config.yaml").read_text(encoding="utf-8")

    assert re.search(r"(?m)^slug:\s+[\"']?umdu_haos_updater[\"']?\s*$", config)
    assert re.search(r"(?m)^version:\s+[\"']?1\.0\.0[\"']?\s*$", config)
    assert re.search(r"(?m)^\s*-\s+aarch64\s*$", config)
    assert re.search(r"(?m)^hassio_role:\s+admin\s*$", config)
    assert "ingress: true" not in config
    for forbidden_key in ("privileged", "full_access", "host_network", "docker_api"):
        assert not re.search(rf"(?m)^{forbidden_key}\s*:", config)
