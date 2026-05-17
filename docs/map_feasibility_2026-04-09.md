# 3D 지도 Feasibility 판단

## 결정
- 기준일: `2026-04-09`
- 현재 SGOP MVP 기준 판단: `정교한 3D 지도는 이번 사이클에서 보류`
- 기본 fallback: `map_2_5d`

## 근거
- `src/data/adapters/vworld_adapter.py`는 VWorld WebGL script URL 생성, WMTS 2.5D tile URL 생성, `map_2_5d` fallback 판단을 제공한다.
- `app.py`는 `get_map_capability(prefer_webgl=False)`를 사용해 제품 기본 지도 경로를 2.5D로 고정한다.
- `src/services/map_overlay_service.py`와 `src/ui/map_overlay_renderer.py`가 app/Monitoring/Simulation/Prediction의 지도 overlay 계약과 렌더링을 공통으로 담당한다.
- 고도 조회는 아직 실제 API로 연결하지 않았으며, 현재 내부 계약은 `elevation_m=None`, `elevation_source="not_queried"`, `coordinate_system="EPSG:4326"`를 유지한다.
- 회의안과 개발 흐름도 모두 `3D 실패 시 2.5D fallback`을 허용한다.

## 최종 판단
- 발표와 MVP 안정성을 우선하면 `3D 유지`보다 `2.5D/2D 오버레이 우선`이 맞다.
- 이후 지도 기능이 붙더라도 첫 연결은 `후보지`, `경로`, `상태 변화`를 보여주는 `map_2_5d` 기준으로 시작한다.
- `3D`는 `VWorld` 연결, 관심영역 기반 고도 조회, rerun-safe 지도 상태 관리가 갖춰진 뒤 다시 평가한다.

## 2026-05-11 VWorld 최소 계약
- `VWORLD_API_KEY`는 `src/config/settings.py`에서 환경 변수 또는 `.env`로 읽는다.
- `src/data/adapters/vworld_adapter.py`의 `build_webgl_script_url()`은 다음 형태의 WebGL script URL을 만든다.
  - `https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=...`
  - 필요하면 `domain=localhost:8501` 같은 도메인 파라미터를 함께 붙일 수 있다.
- `get_map_capability()`는 VWorld 키가 없으면 `FallbackInfo(mode="map_2_5d")`를 반환한다.
- VWorld 키가 있어도 MVP에서 WebGL 3D 검증을 보류하면 `prefer_webgl=False`로 `map_2_5d` fallback을 명시할 수 있다.
- warning과 fallback reason에는 API key 값을 노출하지 않는다.
- 현재 MVP 결론은 `VWorld 완전 3D 구현`이 아니라 `2.5D/Folium 유지 + VWorld WebGL 연결 준비`다.

## 2026-05-17 VWorld 2.5D 타일 계약
- 공식 V-world 교육 샘플의 Folium 배경지도 예시는 `https://api.vworld.kr/req/wmts/1.0.0/{apikey}/Base/{z}/{y}/{x}.png` 형식이다.
- `src/data/adapters/vworld_adapter.py`의 `build_wmts_tile_url()`은 같은 WMTS 템플릿을 반환한다.
- `get_map_capability()`의 기본 화면 경로는 VWorld 키가 있을 때도 `map_2_5d`이며, `wmts_tile_url`을 함께 제공한다.
- WebGL 3D는 검증 작업에서 `get_map_capability(prefer_webgl=True)`를 명시했을 때만 사용한다.
- VWorld 키가 없으면 `wmts_tile_url=None`으로 두고 앱/페이지는 Folium 기본 타일 또는 mock 지도 상태로 내려가야 한다.
- tile URL 자체에는 요청에 필요한 API key가 포함되므로 화면의 warning, fallback reason, overlay metadata에는 이 URL을 그대로 노출하지 않는다.

## 2026-05-17 제품 기본 지도 경로
- 현재 제품 기본 지도 경로는 VWorld WebGL/3D가 아니라 Folium/Leaflet 기반 2.5D 지도다.
- WebGL은 `get_map_capability(prefer_webgl=True)`를 명시한 경우에만 실험 경로로 사용한다.
- VWorld API key가 없거나 Folium 렌더링이 실패해도 앱은 중단되지 않고 `map_2_5d` 또는 표 fallback으로 내려간다.
- app landing, Monitoring, Simulation, Prediction은 모두 `MapOverlayResult`를 렌더링 입력으로 사용한다.
- app landing의 지도 클릭 결과는 `MapOverlayPoint(kind="install_point")`와 `InstallationPoint`로 변환되며, 화면에는 x/y만 표시한다.
- 향후 고도 조회를 붙일 때는 `elevation_source`, 조회 시각, fallback 여부를 overlay/service metadata에 추가한다.

## 후속 규칙
- 지도 계열 기능이 추가될 때 `warnings` 첫 문구와 `fallback.mode`는 `map_2_5d`를 사용한다.
- 계산용 좌표 계약은 계속 `x, y, z` 확장 가능성을 유지하고, 화면 렌더링만 `2.5D/2D`로 낮춘다.
- 지도 UI를 붙일 때는 기본적으로 `get_map_capability(prefer_webgl=False)`와 `wmts_tile_url`을 사용해 2.5D 지도를 만들고, 3D 검증 작업에서만 `get_map_capability(prefer_webgl=True)` 또는 `build_webgl_script_url()`을 사용한다.
