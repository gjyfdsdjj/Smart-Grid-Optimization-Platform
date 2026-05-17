# VWorld API 데이터를 SGOP 내부 형식에 맞게 변환한다.
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urlencode

from src.config.settings import settings
from src.data.schemas import FallbackInfo


VWORLD_WEBGL_SCRIPT_BASE_URL = "https://map.vworld.kr/js/webglMapInit.js.do"
VWORLD_WMTS_TILE_BASE_URL = "https://api.vworld.kr/req/wmts/1.0.0"
DEFAULT_WEBGL_VERSION = "3.0"
DEFAULT_WMTS_LAYER = "Base"
DEFAULT_WMTS_FORMAT = "png"
MapRenderingMode = Literal["vworld_webgl", "map_2_5d"]


@dataclass(frozen=True)
class MapCapability:
    """현재 실행 환경에서 쓸 지도 렌더링 경로를 표현한다."""

    provider: str
    rendering_mode: MapRenderingMode
    vworld_available: bool
    webgl_script_url: str | None
    fallback: FallbackInfo
    warnings: list[str]
    wmts_tile_url: str | None = None


def has_vworld_key(api_key: str | None = None, *, use_settings: bool = True) -> bool:
    """VWorld API key를 사용할 수 있는지 확인한다."""

    return _resolve_api_key(api_key, use_settings=use_settings) is not None


def build_webgl_script_url(
    api_key: str | None = None,
    *,
    version: str = DEFAULT_WEBGL_VERSION,
    domain: str | None = None,
    use_settings: bool = True,
) -> str:
    """VWorld WebGL 초기화 script URL을 생성한다.

    반환 URL은 Streamlit custom component 또는 HTML 삽입 계층에서 그대로 쓸 수
    있는 최소 계약이다. API key 값은 호출자가 보관하고, warning/reason에는
    노출하지 않는다.
    """

    resolved_key = _resolve_api_key(api_key, use_settings=use_settings)
    if resolved_key is None:
        raise ValueError("VWORLD_API_KEY is missing; cannot build VWorld WebGL script URL.")

    resolved_version = _normalize_optional(version)
    if resolved_version is None:
        raise ValueError("VWorld WebGL version must not be empty.")

    query_params = {
        "version": resolved_version,
        "apiKey": resolved_key,
    }

    resolved_domain = _normalize_optional(domain)
    if resolved_domain is not None:
        query_params["domain"] = resolved_domain

    return f"{VWORLD_WEBGL_SCRIPT_BASE_URL}?{urlencode(query_params)}"


def build_wmts_tile_url(
    api_key: str | None = None,
    *,
    layer: str = DEFAULT_WMTS_LAYER,
    tile_format: str = DEFAULT_WMTS_FORMAT,
    use_settings: bool = True,
) -> str:
    """Folium/Leaflet에서 사용할 수 있는 VWorld WMTS tile URL 템플릿을 만든다.

    반환값은 ``{z}``, ``{y}``, ``{x}`` 플레이스홀더를 그대로 포함한다. 실제
    API key는 tile 요청 URL에만 들어가고 fallback reason/warning에는 노출하지
    않는다.
    """

    resolved_key = _resolve_api_key(api_key, use_settings=use_settings)
    if resolved_key is None:
        raise ValueError("VWORLD_API_KEY is missing; cannot build VWorld WMTS tile URL.")

    resolved_layer = _normalize_path_segment(layer, "WMTS layer")
    resolved_format = _normalize_path_segment(tile_format, "WMTS tile format")

    return (
        f"{VWORLD_WMTS_TILE_BASE_URL}/"
        f"{quote(resolved_key, safe='')}/"
        f"{quote(resolved_layer, safe='')}/"
        f"{{z}}/{{y}}/{{x}}."
        f"{quote(resolved_format, safe='')}"
    )


def get_map_capability(
    api_key: str | None = None,
    *,
    version: str = DEFAULT_WEBGL_VERSION,
    domain: str | None = None,
    prefer_webgl: bool = False,
    use_settings: bool = True,
) -> MapCapability:
    """VWorld 지도 사용 가능 여부와 제품 기본 2.5D 경로 판단을 반환한다."""

    key_present = has_vworld_key(api_key, use_settings=use_settings)
    script_url = (
        build_webgl_script_url(
            api_key,
            version=version,
            domain=domain,
            use_settings=use_settings,
        )
        if key_present
        else None
    )
    tile_url = (
        build_wmts_tile_url(api_key, use_settings=use_settings)
        if key_present
        else None
    )

    if not key_present:
        return _build_fallback_capability(
            reason=(
                "VWORLD_API_KEY가 없어 VWorld WebGL 3D 지도를 초기화하지 않고 "
                "Folium/2.5D 지도를 사용합니다."
            ),
            webgl_script_url=None,
            wmts_tile_url=None,
            vworld_available=False,
        )

    if not prefer_webgl:
        return _build_fallback_capability(
            reason=(
                "VWorld WebGL 3D 지도는 연결 준비 상태로만 유지하고, "
                "MVP 화면은 안정적인 Folium/2.5D 지도를 사용합니다."
            ),
            webgl_script_url=script_url,
            wmts_tile_url=tile_url,
            vworld_available=True,
        )

    return MapCapability(
        provider="vworld",
        rendering_mode="vworld_webgl",
        vworld_available=True,
        webgl_script_url=script_url,
        fallback=FallbackInfo(
            enabled=False,
            mode="none",
            reason="",
            primary_path="VWorld WebGL",
            active_path="VWorld WebGL",
        ),
        warnings=[],
        wmts_tile_url=tile_url,
    )


def _build_fallback_capability(
    *,
    reason: str,
    webgl_script_url: str | None,
    wmts_tile_url: str | None,
    vworld_available: bool,
) -> MapCapability:
    return MapCapability(
        provider="vworld",
        rendering_mode="map_2_5d",
        vworld_available=vworld_available,
        webgl_script_url=webgl_script_url,
        fallback=FallbackInfo(
            enabled=True,
            mode="map_2_5d",
            reason=reason,
            primary_path="VWorld WebGL",
            active_path="Folium map_2_5d",
        ),
        warnings=[
            "VWorldAdapter는 현재 `map_2_5d` fallback 결과를 반환합니다.",
            reason,
        ],
        wmts_tile_url=wmts_tile_url,
    )


def _resolve_api_key(api_key: str | None, *, use_settings: bool) -> str | None:
    if api_key is None and use_settings:
        return _normalize_optional(settings.vworld_api_key)
    return _normalize_optional(api_key)


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = value.strip()
    return normalized or None


def _normalize_path_segment(value: str | None, label: str) -> str:
    normalized = _normalize_optional(value)
    if normalized is None:
        raise ValueError(f"VWorld {label} must not be empty.")
    if "/" in normalized or "\\" in normalized:
        raise ValueError(f"VWorld {label} must not contain path separators.")
    return normalized
