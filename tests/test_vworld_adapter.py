from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from src.config.settings import load_settings
from src.data.adapters.vworld_adapter import (
    VWORLD_WEBGL_SCRIPT_BASE_URL,
    VWORLD_WMTS_TILE_BASE_URL,
    build_webgl_script_url,
    build_wmts_tile_url,
    get_map_capability,
    has_vworld_key,
)


def test_build_webgl_script_url_includes_key_version_and_domain():
    url = build_webgl_script_url(
        api_key="test-vworld-key",
        domain="localhost:8501",
        use_settings=False,
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == VWORLD_WEBGL_SCRIPT_BASE_URL
    assert query["version"] == ["3.0"]
    assert query["apiKey"] == ["test-vworld-key"]
    assert query["domain"] == ["localhost:8501"]


def test_build_webgl_script_url_rejects_blank_key():
    with pytest.raises(ValueError, match="VWORLD_API_KEY"):
        build_webgl_script_url(api_key="   ", use_settings=False)


def test_build_wmts_tile_url_returns_folium_template():
    url = build_wmts_tile_url(api_key="test-vworld-key", use_settings=False)

    assert url == (
        f"{VWORLD_WMTS_TILE_BASE_URL}/"
        "test-vworld-key/Base/{z}/{y}/{x}.png"
    )


def test_build_wmts_tile_url_rejects_blank_key():
    with pytest.raises(ValueError, match="VWORLD_API_KEY"):
        build_wmts_tile_url(api_key="", use_settings=False)


def test_build_wmts_tile_url_rejects_path_segments():
    with pytest.raises(ValueError, match="path separators"):
        build_wmts_tile_url(
            api_key="test-vworld-key",
            layer="../Base",
            use_settings=False,
        )


def test_has_vworld_key_uses_explicit_value_without_settings_fallback():
    assert has_vworld_key(api_key="test-vworld-key", use_settings=False) is True
    assert has_vworld_key(api_key="", use_settings=False) is False


def test_map_capability_defaults_to_2_5d_when_key_exists():
    capability = get_map_capability(
        api_key="test-vworld-key",
        domain="localhost:8501",
        use_settings=False,
    )

    assert capability.vworld_available is True
    assert capability.rendering_mode == "map_2_5d"
    assert capability.webgl_script_url is not None
    assert capability.wmts_tile_url is not None
    assert capability.fallback.enabled is True
    assert capability.fallback.mode == "map_2_5d"
    assert capability.fallback.primary_path == "VWorld WebGL"
    assert capability.fallback.active_path == "Folium map_2_5d"


def test_map_capability_uses_webgl_only_when_explicitly_requested():
    capability = get_map_capability(
        api_key="test-vworld-key",
        domain="localhost:8501",
        prefer_webgl=True,
        use_settings=False,
    )

    assert capability.vworld_available is True
    assert capability.rendering_mode == "vworld_webgl"
    assert capability.webgl_script_url is not None
    assert capability.wmts_tile_url is not None
    assert capability.fallback.enabled is False
    assert capability.fallback.mode == "none"


def test_map_capability_falls_back_to_2_5d_when_key_is_missing():
    capability = get_map_capability(api_key="", use_settings=False)

    assert capability.vworld_available is False
    assert capability.rendering_mode == "map_2_5d"
    assert capability.webgl_script_url is None
    assert capability.wmts_tile_url is None
    assert capability.fallback.enabled is True
    assert capability.fallback.mode == "map_2_5d"
    assert capability.fallback.primary_path == "VWorld WebGL"
    assert capability.fallback.active_path == "Folium map_2_5d"


def test_forced_2_5d_fallback_does_not_expose_key_or_domain_in_messages():
    secret_key = "secret-vworld-key"
    secret_domain = "private.example.com"
    capability = get_map_capability(
        api_key=secret_key,
        domain=secret_domain,
        prefer_webgl=False,
        use_settings=False,
    )

    messages = [capability.fallback.reason, *capability.warnings]

    assert capability.vworld_available is True
    assert capability.rendering_mode == "map_2_5d"
    assert capability.webgl_script_url is not None
    assert capability.wmts_tile_url is not None
    assert capability.fallback.enabled is True
    assert all(secret_key not in message for message in messages)
    assert all(secret_domain not in message for message in messages)


def test_load_settings_reads_vworld_api_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("VWORLD_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("VWORLD_API_KEY=env-vworld-key\n", encoding="utf-8")

    loaded = load_settings(env_file)

    assert loaded.vworld_api_key == "env-vworld-key"
