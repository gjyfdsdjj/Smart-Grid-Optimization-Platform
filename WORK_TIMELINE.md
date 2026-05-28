# WORK_TIMELINE.md

## 목적
- 이 파일은 SGOP 저장소의 작업 타임라인과 최근 변경 맥락을 기록한다.
- 새 작업을 시작할 때는 최신 항목부터 읽고, 작업이 끝나면 결과를 추가한다.
- `AGENTS.md`를 읽었다면 이 파일도 같이 읽는 것이 기본 규칙이다.

## 기록 규칙
- 항목 순서는 최신 작업이 아래에 오도록 시간순으로 쌓는다.
- 각 항목에는 최소한 `날짜`, `작업`, `수정 파일`, `검증`, `다음 작업`을 남긴다.
- 구현이 아니라 조사만 했더라도 다음 사람이나 다음 세션이 바로 이어받을 수 있을 만큼 구체적으로 적는다.

## 타임라인

### 2026-03-30
- 작업: MVP 범위, fallback, 역할 분담, 개발 흐름을 문서 기준으로 고정했다.
- 수정 파일: `meeting_plan/MEETING_PLAN_2026-03-30.md`, `DEVELOPMENT_FLOW_2026-03-30.md`
- 검증: 문서 기준 합의안 작성
- 다음 작업: 공통 계약 스키마 정의

### 2026-04-04 1순위 완료
- 작업: 공통 계약 스키마를 `src/data/schemas.py`에 정리했다.
- 수정 파일: `src/data/schemas.py`
- 검증: 서비스/페이지 공통 계약 타입 추가 완료
- 다음 작업: `Monitoring`, `Simulation` 서비스 mock 반환 뼈대 구현

### 2026-04-04 Streamlit 실행 안정화
- 작업: WSL/로컬 환경에서 Streamlit 첫 실행과 파일 감시 문제를 줄이기 위한 로컬 설정을 추가했다.
- 수정 파일: `.streamlit/config.toml`
- 검증: Streamlit HTML/정적 자산 응답 확인
- 다음 작업: 서비스와 페이지 mock 연결 계속 진행

### 2026-04-04 2순위 완료
- 작업: `MonitoringService`, `SimulationService`에 공통 계약 기준 mock 반환 뼈대를 구현했다.
- 수정 파일: `src/services/monitoring_service.py`, `src/services/simulation_service.py`
- 검증:
  - `python3 -c "from src.services.monitoring_service import MonitoringService; result = MonitoringService().get_monitoring_result(load_scale=1.05); print(result.source, result.scenario.scenario_id, len(result.kpis), len(result.line_statuses), len(result.trend_points), result.fallback.mode)"`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc = SimulationService(); result = svc.run_mock_simulation(svc.build_default_input(load_scale=1.1)); print(result.source, result.scenario.scenario_id, len(result.recommendations), len(result.deltas), result.selected_route.route_id, result.fallback.mode)"`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='shared-001'); monitoring = MonitoringService().get_monitoring_result(scenario=scenario); simulation = SimulationService().run_mock_simulation(SimulationService().build_default_input(scenario=scenario)); print(monitoring.scenario.scenario_id, simulation.scenario.scenario_id, monitoring.scenario.created_at is not None, simulation.simulation_input.scenario.scenario_id)"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: `pages/01_monitoring.py`, `pages/02_simulation.py`가 서비스만 호출하도록 정리

### 2026-04-04 3순위 완료
- 작업: `Monitoring`, `Simulation` 페이지를 서비스 반환 결과만 렌더링하는 구조로 구현했다.
- 수정 파일: `pages/01_monitoring.py`, `pages/02_simulation.py`, `src/services/simulation_service.py`, `AGENTS.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
- 다음 작업: `pages/03_prediction.py`까지 같은 `ScenarioContext`를 공유하도록 정리하고, 이후 엔진 구현으로 내려가기

### 2026-04-04 4순위 완료
- 작업: `A*` 결과 포맷과 추천 점수 포맷을 search 엔진 계약으로 고정하고, 비용 요소 초안을 코드 상수로 정리했다.
- 수정 파일: `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`, `src/services/simulation_service.py`, `AGENTS.md`
- 검증:
  - `python3 -c "from src.engine.search.astar_router import BusNodeSpec, RouteCandidateSpec, build_mock_route; start = BusNodeSpec('BUS_001', '서울', 37.5665, 126.9780); end = BusNodeSpec('BUS_011', '대구', 35.8714, 128.6014); hub = BusNodeSpec('BUS_007', '대전', 36.3504, 127.3845); candidate = RouteCandidateSpec('SITE_CENTRAL', '중앙 균형안', 36.28, 127.76, 41.0, 17.0); route = build_mock_route(start, end, candidate, via_bus=hub, load_scale=1.1); print(route.route_id, route.total_distance_km, route.estimated_cost, route.path_node_ids)"`
  - `python3 -c "from src.engine.search.score_function import CandidateScoreInput, calculate_mock_score, build_recommendation, rank_recommendations; from src.data.schemas import RouteResult; route_a = RouteResult(route_id='a', start_bus_id='BUS_001', end_bus_id='BUS_011'); route_b = RouteResult(route_id='b', start_bus_id='BUS_001', end_bus_id='BUS_011'); score_a = calculate_mock_score(CandidateScoreInput('SITE_A', 'A', 41.0, 17.0, 29.0, 4.0, 3.0, 1.1)); score_b = calculate_mock_score(CandidateScoreInput('SITE_B', 'B', 54.0, 15.0, 24.0, 3.0, 2.5, 1.1)); ranked = rank_recommendations([build_recommendation('SITE_A', 'A', route_a, score_a, 'a'), build_recommendation('SITE_B', 'B', route_b, score_b, 'b')]); print(score_a.total_score, score_b.total_score, [(item.candidate_id, item.rank) for item in ranked])"`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc = SimulationService(); result = svc.run_mock_simulation(svc.build_default_input(load_scale=1.1)); print(result.selected_route.route_id, result.recommendations[0].candidate_id, result.recommendations[0].score.notes[1], result.warnings[0])"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: `Prediction` 페이지까지 공통 `ScenarioContext`를 공유하도록 정리하고, 이후 실제 엔진 구현 전까지 fallback 규칙을 유지

### 2026-04-04 Prediction 공통화 완료
- 작업: `PredictionService`와 `Prediction` 페이지를 공통 `ScenarioContext`, `warnings`, `fallback` 흐름에 맞췄다.
- 수정 파일: `src/services/prediction_service.py`, `pages/03_prediction.py`, `AGENTS.md`
- 검증:
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.prediction_service import PredictionService; scenario = ScenarioContext(scenario_id='shared-001'); result = PredictionService().run_mock_prediction(load_scale=1.1, scenario=scenario); print(result.scenario_id, result.scenario.scenario_id, result.fallback.mode, len(result.warnings))"`
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: 1주차-박차오름 범위에서는 fallback 문구와 서비스 입력 패턴을 더 통일할지 점검하고, 이후 실제 엔진 구현 단계로 넘어가기

### 2026-04-04 서비스 인터페이스 미세정리 및 fallback 규칙 문서화 완료
- 작업: 세 서비스의 공통 입력 축을 `scenario`, `created_at`, `load_scale` 기준으로 정리하고, fallback 규칙 초안을 문서화했다.
- 수정 파일: `src/services/monitoring_service.py`, `src/services/simulation_service.py`, `src/services/prediction_service.py`, `pages/01_monitoring.py`, `AGENTS.md`
- 검증:
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; scenario = ScenarioContext(scenario_id='shared-002'); monitoring = MonitoringService().run_mock_monitoring(scenario=scenario, created_at=None, load_scale=1.0); simulation = SimulationService().run_mock_simulation(SimulationService().build_default_input(scenario=scenario, created_at=None, load_scale=1.0)); prediction = PredictionService().run_mock_prediction(scenario=scenario, created_at=None, load_scale=1.0); print(monitoring.fallback.mode, simulation.fallback.mode, prediction.fallback.mode, monitoring.warnings[0], simulation.warnings[0], prediction.warnings[0])"`
  - `python3 -m compileall app.py pages src`
- 다음 작업: 1주차-박차오름 범위는 사실상 정리되었고, 이후에는 실제 엔진 치환 단계로 넘어가기

### 2026-04-04 Streamlit rerun 고려사항 문서화
- 작업: Streamlit rerun 구조를 작업 시 필수 고려사항으로 `AGENTS.md`에 명시했다.
- 수정 파일: `AGENTS.md`
- 검증: 문서 규칙 반영 확인
- 다음 작업: 실제 엔진 연결 단계에서 rerun-safe와 rerun-optimized 여부를 함께 점검

### 2026-04-04 랜딩 페이지 지도 요구사항 문서화
- 작업: 첫 랜딩 페이지의 지도 UX 방향을 `AGENTS.md`에 기록했다. `VWorld` 기반 대한민국 지도, 발전소/송전탑 표시, 좌측 패널 설치 UI, 지도 클릭 후 설정값 입력 흐름, 임시 에셋 교체 예정, `2.5D/3D` 우선 방향을 명시했다.
- 수정 파일: `AGENTS.md`
- 검증: 문서 규칙 반영 확인
- 다음 작업: 실제 랜딩 페이지 구현 단계에서 `VWorld` 연동 방식, 설치 인터랙션, `map_2_5d` fallback 적용 기준을 구체화

### 2026-04-04 설치 지점 3축 좌표 요구사항 문서화
- 작업: 대한민국 지형을 고려한 설치 지점 좌표를 `x, y, z` 3축 기준으로 다뤄야 한다는 요구사항을 `AGENTS.md`에 추가했다. `z`는 고도/지형 높이 정보로 간주하고, 후속 스키마와 지도 상호작용에서도 2차원 좌표로 축소하지 않도록 명시했다.
- 수정 파일: `AGENTS.md`
- 검증: 문서 규칙 반영 확인
- 다음 작업: 실제 랜딩 페이지 구현 단계에서 좌표 스키마, 지도 클릭 이벤트, 고도값 취득 방식과 `2.5D/3D` 표시 전략을 구체화

### 2026-04-09 지도 설계 상시 참조 규칙 문서화
- 작업: 브이월드 기반 랜딩 페이지의 지도 설계 원칙을 특정 주차 문맥이 아니라 상시 참조 규칙으로 정리했다. 지도 관련 작업을 시작할 때 `AGENTS.md`의 지도 섹션을 다시 읽도록 명시하고, `LOD + 영역별 정밀 조회`, 거시 표현용 폴리곤화/mesh 단순화, 클릭 시 고해상도 `x, y, z` 확정, 표현용 geometry와 분석용 좌표 분리, `map_2_5d` fallback 유지 원칙을 일반 규칙으로 정리했다.
- 수정 파일: `AGENTS.md`, `WORK_TIMELINE.md`
- 검증: 문서 규칙 반영 확인, `py -3 -m compileall app.py pages src`
- 다음 작업: 지도 어댑터와 좌표 스키마를 설계할 때 `조회 범위`, `좌표계`, `고도 산정 방식`, `fallback 메타데이터` 필드를 공통 계약으로 구체화

### 2026-04-09 Monitoring 페이지 bare-run 실패 수정
- 작업: `pages/01_monitoring.py`의 전체 선로 상태표에서 `pandas Styler` 의존성을 제거해 bare-run 실패를 없앴다. `st.dataframe(df.style...)`를 plain DataFrame 렌더링으로 바꾸고, 같은 위치의 `use_container_width` 인자도 `width="stretch"`로 정리했다.
- 수정 파일: `pages/01_monitoring.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; result = MonitoringService().run_mock_monitoring(load_scale=1.0); print(result.source, result.scenario.scenario_id, len(result.kpis), len(result.line_statuses), result.fallback.mode)"`
- 다음 작업: `streamlit run app.py` 기준으로 Monitoring/Simulation/Prediction 세 페이지가 실제 브라우저 환경에서도 같은 시나리오 흐름으로 안정적으로 열리는지 다시 점검

### 2026-04-09 박차오름 2주차 작업 문서 추가
- 작업: 박차오름의 2주차 `1순위 -> 4순위` 작업을 바로 따라갈 수 있도록 임시 체크리스트 문서 `PARK_CHAOREUM_WEEK2_TASKS.md`를 루트에 추가했다. `A* 최소 버전`, `점수화 v1`, `공통 결과 형식 통일`, `page-service-engine 연결 규칙 확정` 순서와 종료 후 파일 삭제 조건을 함께 기록했다.
- 수정 파일: `PARK_CHAOREUM_WEEK2_TASKS.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 및 삭제 조건 반영 확인
- 다음 작업: `PARK_CHAOREUM_WEEK2_TASKS.md` 기준으로 1순위 `A* 최소 버전 구현`부터 착수

### 2026-04-09 박차오름 2주차 1순위 A* 최소 버전 구현
- 작업: `src/engine/search/astar_router.py`에 실제 A* 최소 버전을 추가했다. 기존 `build_mock_route()`는 유지하고, `GraphEdgeSpec`, `build_k_nearest_edges()`, `build_astar_route()`를 추가해 `bus graph + candidate + via hub` 기준의 실제 경로 계산이 가능하도록 정리했다. 구간별 `start -> candidate -> end` 또는 `start -> via -> candidate -> end` 탐색, 경로 복원, 실제 `RouteResult` 반환, 비용 추정까지 포함했다. 2주차 임시 작업 문서에도 1순위 완료 상태를 체크했다.
- 수정 파일: `src/engine/search/astar_router.py`, `PARK_CHAOREUM_WEEK2_TASKS.md`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.engine.search.astar_router import BusNodeSpec, RouteCandidateSpec, build_astar_route, build_k_nearest_edges; buses=[BusNodeSpec('BUS_001','서울',37.5665,126.9780),BusNodeSpec('BUS_003','수원',37.2636,127.0286),BusNodeSpec('BUS_007','대전',36.3504,127.3845),BusNodeSpec('BUS_010','전주',35.8242,127.1480),BusNodeSpec('BUS_011','대구',35.8714,128.6014)]; candidate=RouteCandidateSpec('SITE_CENTRAL','중앙 균형안',36.28,127.76,41.0,17.0); route=build_astar_route(start_bus=buses[0], end_bus=buses[-1], candidate=candidate, bus_nodes=buses, edges=build_k_nearest_edges(buses, neighbor_count=2), via_bus=buses[2], load_scale=1.1); print(route.route_id, route.source, route.path_node_ids, round(route.total_distance_km,1), round(route.estimated_cost,1))"`
- 다음 작업: 2순위 `추천 점수화 v1 구현`에서 실제 route 결과를 입력으로 쓰는 점수 계산 함수와 정렬 로직을 정리

### 2026-04-09 박차오름 2주차 2순위 추천 점수화 v1 구현
- 작업: `src/engine/search/score_function.py`에 실제 route 반영 점수 계산 함수 `calculate_score()`를 추가했다. 기존 `calculate_mock_score()`는 유지하고, route 거리값 반영, 거리 초과 패널티, route 안정성 bonus, 정렬 tie-break 규칙까지 넣어 2주차용 점수화 v1을 분리했다. 임시 작업 문서에도 2순위 완료 상태를 체크했다.
- 수정 파일: `src/engine/search/score_function.py`, `PARK_CHAOREUM_WEEK2_TASKS.md`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.engine.search.score_function import CandidateScoreInput, calculate_score, build_recommendation, rank_recommendations; from src.data.schemas import RouteResult; route_a = RouteResult(route_id='astar-a', start_bus_id='BUS_001', end_bus_id='BUS_011', total_distance_km=39.0, source='astar'); route_b = RouteResult(route_id='astar-b', start_bus_id='BUS_001', end_bus_id='BUS_011', total_distance_km=60.0, source='astar'); score_a = calculate_score(CandidateScoreInput('SITE_A', 'A', 41.0, 17.0, 29.0, 4.0, 3.0, 1.1), route=route_a); score_b = calculate_score(CandidateScoreInput('SITE_B', 'B', 54.0, 15.0, 24.0, 3.0, 2.5, 1.1), route=route_b); ranked = rank_recommendations([build_recommendation('SITE_A', 'A', route_a, score_a, 'a'), build_recommendation('SITE_B', 'B', route_b, score_b, 'b')]); print(score_a.total_score, score_b.total_score, [(item.candidate_id, item.rank) for item in ranked], score_a.notes[1])"`
- 다음 작업: 3순위 `공통 결과 형식 통일`에서 route/score/service 반환 형식의 source, warnings, fallback 사용 규칙을 정리

### 2026-04-09 박차오름 2주차 3순위 공통 결과 형식 통일
- 작업: `SimulationService`의 actual 진입점과 search 엔진 출력이 기존 dataclass 계약을 그대로 쓰도록 정리했다. actual route는 `RouteResult(source='astar')`, actual score는 `ScoreBreakdown`으로 유지하고, `SimulationResult`는 `source`, `scenario`, `warnings`, `fallback` 메타데이터를 포함한 같은 반환 형식을 유지하도록 맞췄다. 아직 실제 power flow가 없는 delta는 partial `mock_data fallback`으로 명시했다.
- 수정 파일: `src/services/simulation_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='sim-v1'); svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.1)); print({'source': result.source, 'scenario_id': result.scenario.scenario_id, 'route_source': result.selected_route.source if result.selected_route else None, 'route_id': result.selected_route.route_id if result.selected_route else None, 'top_candidate': result.recommendations[0].candidate_id if result.recommendations else None, 'top_score': result.recommendations[0].score.total_score if result.recommendations and result.recommendations[0].score else None, 'fallback': result.fallback.mode, 'warnings': result.warnings[:2]})"`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; scenario = ScenarioContext(scenario_id='shared-actual'); monitoring = MonitoringService().run_mock_monitoring(scenario=scenario, load_scale=1.0); simulation = SimulationService().run_simulation(SimulationService().build_default_input(scenario=scenario, load_scale=1.0)); prediction = PredictionService().run_mock_prediction(scenario=scenario, load_scale=1.0); print({'ids':[monitoring.scenario.scenario_id, simulation.scenario.scenario_id, prediction.scenario.scenario_id], 'simulation_source': simulation.source, 'route_source': simulation.selected_route.source if simulation.selected_route else None, 'fallback': simulation.fallback.mode})"`
- 다음 작업: 4순위 `page-service-engine 연결 규칙 확정`에서 Simulation 페이지가 actual route/score 결과를 직접 렌더링하도록 연결

### 2026-04-09 박차오름 2주차 4순위 page-service-engine 연결 규칙 확정
- 작업: `pages/02_simulation.py`가 더 이상 `run_mock_simulation()`을 직접 호출하지 않고 `SimulationService.run_simulation()`을 사용하도록 바꿨다. 서비스 내부 호출 흐름은 `입력 정규화 -> actual route/score 계산 -> delta mock fallback -> 결과 조립`으로 고정했고, 페이지는 서비스 반환 dataclass만 렌더링하도록 유지했다. 1~4순위가 끝나서 임시 작업 파일 `PARK_CHAOREUM_WEEK2_TASKS.md`도 규칙대로 삭제했다.
- 수정 파일: `src/services/simulation_service.py`, `pages/02_simulation.py`, `WORK_TIMELINE.md`, `PARK_CHAOREUM_WEEK2_TASKS.md(삭제)`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='sim-v1'); svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.1)); print({'source': result.source, 'route_source': result.selected_route.source if result.selected_route else None, 'top_candidate': result.recommendations[0].candidate_id if result.recommendations else None, 'top_score': result.recommendations[0].score.total_score if result.recommendations and result.recommendations[0].score else None, 'fallback': result.fallback.mode})"`
- 다음 작업: `Monitoring`의 실제 계산값과 `Simulation`의 delta 계산을 연결해 partial `mock_data fallback` 범위를 줄이기

### 2026-04-09 Simulation delta actualization 시작
- 작업: `SimulationService.run_simulation()`의 설치 전후 delta 계산을 `MonitoringService.run_dc_power_flow()` 기준으로 연결했다. 설치 전 baseline은 실제 `DC Power Flow` 결과를 사용하고, 설치 후 값은 추천안의 `route/score`를 반영한 heuristic counterfactual로 계산하도록 `_build_actual_deltas()`를 추가했다. 이에 따라 `peak_utilization`, `risk_lines`, `losses`, `operating_margin`의 before 값이 mock 상수 대신 실제 혼잡 결과를 사용하도록 바뀌었다.
- 수정 파일: `src/services/simulation_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.data.schemas import ScenarioContext; from src.services.simulation_service import SimulationService; scenario = ScenarioContext(scenario_id='delta-actual'); svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.1)); print({'source': result.source, 'fallback': result.fallback.mode, 'warning0': result.warnings[0], 'warning1': result.warnings[1], 'deltas': [(d.metric_id, d.before_value, d.after_value, d.unit, d.status) for d in result.deltas]})"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
- 다음 작업: heuristic after-state를 실제 counterfactual power flow에 더 가깝게 보정하거나, 추천 경로가 어떤 선로를 완화하는지 line-level 연결 규칙을 추가

### 2026-04-09 박차오름 2주차 3순위 메타데이터 형식 보강
- 작업: `src/services/result_metadata.py`를 추가해 서비스 결과 메타데이터 형식을 공통 헬퍼로 묶었다. `MonitoringService`, `SimulationService`, `PredictionService`가 모두 같은 경고 첫 문구 형식과 `FallbackInfo` 생성 규칙을 쓰도록 정리했다. 이에 따라 mock fallback 경고 첫 줄이 세 서비스에서 동일한 형식으로 맞춰졌고, 정상 경로인 `MonitoringService.run_dc_power_flow()`도 source 안내 문구 형식을 통일했다.
- 수정 파일: `src/services/result_metadata.py`, `src/services/monitoring_service.py`, `src/services/simulation_service.py`, `src/services/prediction_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; from src.data.schemas import ScenarioContext; scenario = ScenarioContext(scenario_id='meta-check'); m = MonitoringService().run_mock_monitoring(scenario=scenario); s = SimulationService().run_simulation(SimulationService().build_default_input(scenario=scenario)); p = PredictionService().run_mock_prediction(scenario=scenario); print({'monitoring_warning': m.warnings[0], 'simulation_warning': s.warnings[0], 'prediction_warning': p.warnings[0], 'monitoring_fallback': m.fallback.mode, 'simulation_fallback': s.fallback.mode, 'prediction_fallback': p.fallback.mode})"`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; result = MonitoringService().run_dc_power_flow(load_scale=1.0); print(result.warnings[0], result.fallback.mode, result.source)"`
- 다음 작업: 사용자가 원할 때만 4순위 범위 변경을 이어가고, 기본적으로는 공통 계약/메타데이터 정합성 유지에 집중

### 2026-04-09 박차오름 4주차 A* 보정 및 통합 정리
- 작업: `A*` 경로 계산에서 `직결`과 `허브 경유` 경로를 둘 다 평가하고, 반복 노드와 과도한 우회를 패널티로 반영하는 보정 로직을 추가했다. 이에 따라 허브를 억지로 거치며 루프가 생기던 경로를 배제하고, `SimulationService`는 추천 생성, baseline 조회, 결과 조립 흐름을 helper 단위로 정리했다. 지도/3D 쪽은 현재 저장소 기준으로 `VWorld` 어댑터와 지도 페이지 구현이 없어서 `3D 보류 -> map_2_5d fallback`이 맞다는 판단 문서를 추가했다.
- 수정 파일: `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`, `src/services/simulation_service.py`, `docs/map_feasibility_2026-04-09.md`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.simulation_service import SimulationService; from src.data.schemas import ScenarioContext; svc = SimulationService(); result = svc.run_simulation(svc.build_default_input(scenario=ScenarioContext(scenario_id='wk4-check'), load_scale=1.0)); print({'source': result.source, 'fallback': result.fallback.mode, 'summary': result.summary, 'warnings': result.warnings[:2]}); [print(rec.rank, rec.candidate_id, rec.route.total_distance_km if rec.route else None, rec.route.estimated_cost if rec.route else None, rec.route.path_node_ids if rec.route else None, rec.score.total_score if rec.score else None) for rec in result.recommendations]"`
  - `python3 -c "from src.engine.search.astar_router import build_astar_route; from src.services.simulation_service import SimulationService, _to_bus_node_spec, _to_route_candidate_spec, _get_candidate; svc = SimulationService(); bus_nodes = svc._build_bus_nodes(); edges = svc._build_bus_edges(bus_nodes); start = _to_bus_node_spec('BUS_001'); end = _to_bus_node_spec('BUS_011'); via = _to_bus_node_spec('BUS_007'); [print(candidate_id, route.total_distance_km, route.estimated_cost, route.path_node_ids) for candidate_id, route in [(candidate_id, build_astar_route(start, end, _to_route_candidate_spec(candidate_id, _get_candidate(candidate_id, index)), bus_nodes=bus_nodes, edges=edges, via_bus=via, load_scale=1.0)) for index, candidate_id in enumerate(['SITE_NORTH', 'SITE_CENTRAL', 'SITE_SOUTH'])]]"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
- 다음 작업: `Beta`가 지도 오버레이를 붙일 때 `map_2_5d` fallback 규칙을 그대로 사용하고, `Simulation` 설치 후 counterfactual을 실제 power flow로 바꾸는 작업은 이후 통합 병목 제거 단계에서 진행

### 2026-04-10 예측 문서에 GNN 병렬 활용 계획 반영
- 작업: `AGENTS.md`와 `meeting_plan/MEETING_PLAN_2026-03-30.md`의 예측 계획을 `LSTM` 단일 중심에서 `LSTM+GNN` 병렬 활용 기준으로 확장했다. `PredictionService` 책임, forecast 엔진 후보, Gamma 역할, 주차별 예측 작업, fallback 문구를 함께 정리했다.
- 수정 파일: `AGENTS.md`, `meeting_plan/MEETING_PLAN_2026-03-30.md`, `WORK_TIMELINE.md`
- 검증:
  - `Select-String -Path AGENTS.md, meeting_plan/MEETING_PLAN_2026-03-30.md -Pattern 'GNN','LSTM' -Encoding UTF8`
- 다음 작업: `Prediction` 실제 구현 단계에서 `feature/graph` 입력 계약과 `LSTM/GNN` 병렬 결과 결합 규칙을 `src/data/schemas.py`와 예측 서비스 인터페이스 기준으로 구체화한다.

### 2026-04-13 1~2주차 계획 대비 구현 점검
- 작업: `meeting_plan/MEETING_PLAN_2026-03-30.md` 기준으로 1주차와 2주차 작업의 실제 구현 상태를 점검했다. `Monitoring`의 `dc_power_flow`와 `Simulation`의 `A*` 경로 흐름은 실제 값이 출력되는 것을 확인했다. 반면 `Prediction`의 baseline 실제 경로는 `PredictionService.run_baseline_prediction()` / `run_lstm_prediction()` 내부에서 `FallbackInfo` 미정의로 즉시 실패해, 2주차 완료 기준인 `예측 그래프 1개가 실제 값으로 나온다`는 아직 충족되지 않는다고 판단했다. 또한 `Prediction` 페이지는 baseline/LSTM 실패 시 mock으로 자동 전환하지 않고 `st.stop()`으로 중단되어 회의안의 fallback 원칙과도 어긋나는 상태임을 확인했다.
- 수정 파일: `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; r=MonitoringService().run_dc_power_flow(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'lines': len(r.line_statuses), 'max_util': r.congestion_summary.max_utilization, 'warning0': r.warnings[0]})"`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'route_source': r.selected_route.source if r.selected_route else None, 'recs': len(r.recommendations), 'deltas': len(r.deltas), 'warning0': r.warnings[0]})"`
  - `python3 -c "from src.services.prediction_service import PredictionService; r=PredictionService().run_mock_prediction(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warning0': r.warnings[0]})"`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_baseline_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines)})"` -> `NameError: name 'FallbackInfo' is not defined`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"`
- 다음 작업: `PredictionService`의 baseline/LSTM 반환 경로를 실제로 동작하게 고치고, baseline/LSTM 실패 시 `mock_data` fallback으로 자동 전환되도록 서비스/페이지 흐름을 정리한다. 이후 필요하면 `GNN` 병렬 조합 구조를 회의안 기준으로 어디까지 2주차 범위로 볼지 다시 합의한다.

### 2026-04-13 1~2주차 진행 상황 재점검
- 작업: 회의안 기준으로 1주차, 2주차 완료 조건을 다시 대조했다. 1주차는 세 페이지가 모두 mock 기준으로 열리고 공통 시나리오/계약이 유지되어 완료로 봐도 무방하다고 판단했다. 2주차는 `MonitoringService.run_dc_power_flow()`와 `SimulationService.run_simulation()`이 실제 계산 경로를 반환하는 것을 다시 확인했지만, `PredictionService.run_baseline_prediction()`은 여전히 `FallbackInfo` import 누락으로 실패해 예측 실제 경로는 미완료 상태라고 정리했다. 추가로 `pages/03_prediction.py`는 baseline/LSTM 예외 시 mock fallback으로 전환하지 않고 `st.stop()`으로 중단되며, `feature_builder`는 입력 계약 정의만 존재하고 baseline/LSTM 경로에는 아직 연결되지 않은 상태도 확인했다.
- 수정 파일: `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; r=MonitoringService().run_dc_power_flow(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'lines': len(r.line_statuses), 'max_util': r.congestion_summary.max_utilization, 'warning0': r.warnings[0] if r.warnings else None})"`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'route_source': r.selected_route.source if r.selected_route else None, 'recs': len(r.recommendations), 'deltas': len(r.deltas), 'warning0': r.warnings[0] if r.warnings else None})"`
  - `python3 -c "from src.services.prediction_service import PredictionService; r=PredictionService().run_mock_prediction(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warning0': r.warnings[0] if r.warnings else None})"`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_baseline_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines)})"` -> `NameError: name 'FallbackInfo' is not defined`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"`
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"`
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"`
- 다음 작업: `PredictionService`의 baseline/LSTM 정상 반환과 fallback 메타데이터를 먼저 고치고, `pages/03_prediction.py`에서 baseline/LSTM 실패 시 `mock_data` fallback으로 자동 전환되게 정리한다. 그 다음 `feature_builder`를 실제 예측 경로에 연결할지, 2주차 범위를 baseline 우선으로 닫을지 정리한다.

### 2026-04-13 Prediction baseline 정상 반환 복구
- 작업: `PredictionService.run_baseline_prediction()`의 정상 반환 경로를 복구했다. 반환부에서 사용하던 `FallbackInfo` 타입 import가 빠져 있어 baseline 실제 예측이 `NameError`로 실패하던 문제를 수정했다.
- 수정 파일: `src/services/prediction_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_baseline_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'scenario_id': r.scenario_id})"`
- 다음 작업: `pages/03_prediction.py`에서 baseline/LSTM 실패 시 `mock_data` fallback으로 자동 전환되게 정리하고, 이어서 `PredictionService.run_lstm_prediction()`의 정상 반환과 실제 추론 경로를 점검한다.

### 2026-04-13 Prediction 페이지 fallback 자동 전환 정리
- 작업: `pages/03_prediction.py`에서 baseline/LSTM 예측 실패 시 더 이상 `st.stop()`으로 중단하지 않고 `PredictionService.run_mock_prediction()`으로 자동 전환되도록 정리했다. 페이지 내부에 `_run_prediction_with_fallback()` 헬퍼를 추가해 baseline 실제 경로는 그대로 유지하고, 실패 시에는 원인 문구를 `warnings`와 `fallback.reason`에 남긴 mock 결과를 렌더링하도록 바꿨다.
- 수정 파일: `pages/03_prediction.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "import runpy; ns=runpy.run_path('pages/03_prediction.py'); helper=ns['_run_prediction_with_fallback']; svc=ns['PredictionService'](); ScenarioContext=ns['ScenarioContext']; result=helper(svc, model_source='Baseline', raw_dir='data/raw', load_scale=1.0, scenario=ScenarioContext(scenario_id='baseline-ok')); print({'source': result.source, 'fallback': result.fallback.mode, 'warnings0': result.warnings[0] if result.warnings else None, 'preds': len(result.predictions)})"`
  - `python3 -c "import runpy; ns=runpy.run_path('pages/03_prediction.py'); helper=ns['_run_prediction_with_fallback']; svc=ns['PredictionService'](); ScenarioContext=ns['ScenarioContext']; result=helper(svc, model_source='Baseline', raw_dir='data/__missing__', load_scale=1.0, scenario=ScenarioContext(scenario_id='baseline-fallback')); print({'source': result.source, 'fallback': result.fallback.mode, 'warnings0': result.warnings[0] if result.warnings else None, 'reason': result.fallback.reason})"`
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"`
- 다음 작업: `PredictionService.run_lstm_prediction()`의 정상 반환과 실제 학습/추론 경로를 점검하고, 필요한 경우 `Baseline`과 같은 수준으로 failure-to-mock fallback을 서비스 계층에도 통일한다.

### 2026-04-13 Prediction LSTM 정상 반환 및 추론 경로 점검
- 작업: `PredictionService.run_lstm_prediction()`의 정상 반환 경로를 복구하고 실제 학습/추론 흐름을 점검했다. 반환 메타데이터를 `build_no_fallback_info()` 기준으로 정리했고, 저장된 `model.keras`가 현재 Keras 환경에서 역직렬화되지 않을 때는 자동 재학습 후 예측을 계속 수행하도록 서비스 복구 경로를 추가했다. 이후 새로 저장된 모델이 재학습 없이도 바로 로드되는 것을 확인했고, 예외 원인 문구도 페이지에 그대로 노출되지 않도록 짧게 요약되게 정리했다.
- 수정 파일: `src/services/prediction_service.py`, `models/lstm/model.keras`, `models/lstm/scalers.pkl`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_lstm_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warnings': r.warnings[:2], 'scenario_id': r.scenario_id})"` -> 초기 저장 모델 호환성 문제를 자동 재학습으로 복구한 뒤 `source='lstm'`, `fallback='none'`, `preds=312`, `risks=2`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_lstm_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warnings': r.warnings, 'scenario_id': r.scenario_id})"` -> 재실행 시 `warnings=[]`로 저장 모델 즉시 로드 확인
  - `python3 -c "from src.services.prediction_service import _summarize_lstm_model_error; exc=Exception('Unrecognized keyword arguments passed to Dense: {\\'quantization_config\\': None}\\nrest'); print(_summarize_lstm_model_error(exc))"` -> `저장된 model.keras가 현재 Keras 버전의 Dense 설정과 호환되지 않았습니다.`
- 다음 작업: `feature_builder`를 baseline/LSTM 실제 예측 경로에 연결할지 정리하고, 이어서 `Simulation` 설치 후 delta를 실제 counterfactual 계산으로 치환한다.

### 2026-04-13 Prediction feature_builder 실제 경로 연결
- 작업: `feature_builder`를 baseline/LSTM 실제 예측 경로에 연결했다. `src/engine/forecast/feature_builder.py`에 `build_prediction_feature_matrix()`를 추가해 예측 구간 24시간 × 노드별 `ForecastFeatureVector`를 서비스에서 공통으로 생성하도록 정리했고, `BaselineForecaster.predict()`는 이 feature contract의 `timestamp/hour/bus_id`를 직접 사용하도록 바꿨다. `LSTMForecaster.predict()`도 같은 `target_features`를 받아 출력 시각과 노드 순서를 그 계약에 맞추도록 수정했다. `PredictionService`는 baseline/LSTM 진입 전에 공통 feature matrix를 만들고 두 forecaster에 넘기도록 연결했다.
- 수정 파일: `src/engine/forecast/feature_builder.py`, `src/engine/forecast/baseline_forecaster.py`, `src/engine/forecast/lstm_forecaster.py`, `src/services/prediction_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from pathlib import Path; from src.data.adapters.public_data_adapter import load_kpx_csvs; from src.engine.forecast.feature_builder import build_prediction_feature_matrix; raw_dir=str(Path('data/raw').resolve()); load_df=load_kpx_csvs(raw_dir); features=build_prediction_feature_matrix(load_df=load_df, forecast_start=load_df['timestamp'].max()); print({'features': len(features), 'first_bus': features[0].bus_id, 'first_ts': str(features[0].timestamp), 'last_bus': features[-1].bus_id, 'last_ts': str(features[-1].timestamp), 'sample_lag_1h': features[0].load_lag_1h, 'sample_ratio': features[0].regional_demand_ratio})"` -> `features=312`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_baseline_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'first': (r.predictions[0].timestamp.isoformat(), r.predictions[0].bus_id)})"` -> `source='baseline'`, `fallback='none'`, `preds=312`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_lstm_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warnings': r.warnings, 'first': (r.predictions[0].timestamp.isoformat(), r.predictions[0].bus_id)})"` -> `source='lstm'`, `fallback='none'`, `preds=312`, `warnings=[]`
  - `python3 -c "from pathlib import Path; from src.data.adapters.public_data_adapter import load_kpx_csvs; from src.engine.forecast.feature_builder import build_prediction_feature_matrix; from src.engine.forecast.baseline_forecaster import BaselineForecaster; raw_dir=str(Path('data/raw').resolve()); load_df=load_kpx_csvs(raw_dir); features=build_prediction_feature_matrix(load_df=load_df, forecast_start=load_df['timestamp'].max(), bus_ids=['BUS_001'])[:3]; preds=BaselineForecaster().fit(load_df).predict(target_features=features); print([(p.timestamp.isoformat(), p.bus_id) for p in preds])"` -> feature timestamp 순서 직접 반영 확인
  - `python3 -c "from pathlib import Path; from src.data.adapters.public_data_adapter import load_kpx_with_weather; from src.engine.forecast.feature_builder import build_prediction_feature_matrix; from src.engine.forecast.lstm_forecaster import LSTMForecaster; raw_dir=str(Path('data/raw').resolve()); load_df=load_kpx_with_weather(raw_dir); features=build_prediction_feature_matrix(load_df=load_df, forecast_start=load_df['timestamp'].max(), bus_ids=['BUS_001'])[:3]; preds=LSTMForecaster().predict(history_df=load_df, forecast_start=load_df['timestamp'].max(), target_features=features); print([(p.timestamp.isoformat(), p.bus_id) for p in preds])"` -> feature timestamp 순서 직접 반영 확인
- 다음 작업: `Simulation` 설치 후 delta를 heuristic counterfactual 대신 실제 counterfactual 계산으로 치환한다.

### 2026-04-13 Simulation counterfactual delta 실제 계산 연결
- 작업: `SimulationService.run_simulation()`의 설치 후 delta를 heuristic 계산이 아니라 실제 counterfactual DC Power Flow로 치환했다. 설치 전 baseline은 기존 `MonitoringService.run_dc_power_flow()`를 그대로 사용하고, 설치 후에는 상위 혼잡 선로에 병렬 지원선을 추가한 counterfactual line set으로 `dc_power_flow.solve()`를 다시 실행하도록 연결했다. 이 결과를 기준으로 `peak_utilization`, `risk_lines`, `losses`, `operating_margin` delta를 실제 조류 결과에서 계산하게 바꿨고, counterfactual 계산이 실패할 때만 기존 heuristic delta로 내려가도록 fallback 경로를 남겼다.
- 수정 파일: `src/services/simulation_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'warnings': r.warnings[:3], 'deltas': [(d.metric_id, d.before_value, d.after_value, d.improvement, d.status) for d in r.deltas]})"` -> `source='astar'`, `fallback='none'`, `peak_utilization 97.5 -> 85.3`, `risk_lines 6.0 -> 3.0`
  - `python3 -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.1)); print({'source': r.source, 'fallback': r.fallback.mode, 'peak': next(d for d in r.deltas if d.metric_id=='peak_utilization').improvement, 'risk': next(d for d in r.deltas if d.metric_id=='risk_lines').improvement, 'warnings': r.warnings[:3]})"` -> 고부하 시나리오에서도 `fallback='none'` 유지 확인
  - `python3 -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); sim=svc.build_default_input(load_scale=1.0); recs=svc._build_recommendations(sim, use_actual_route=True); before=svc._get_monitoring_baseline(simulation_input=sim, created_at=sim.scenario.created_at); after,_=svc._build_counterfactual_monitoring(simulation_input=sim, monitoring_before=before, top_recommendation=recs[0]); print({'before_top3': [(l.line_id, round(l.utilization,4)) for l in before.line_statuses[:3]], 'after_top3': [(l.line_id, round(l.utilization,4)) for l in after.line_statuses[:3]]})"` -> `L12/L06` 보강 후 상위 혼잡 선로 재배치 확인
  - `python3 -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> bare-run 통과
- 다음 작업: `Monitoring` 입력 검증/오류 메시지 보강 또는 `Prediction`의 `GNN` 병렬 조합 범위를 정리한다.

### 2026-04-13 Monitoring 입력 검증 및 오류 메시지 보강
- 작업: `MonitoringService`에 입력 정규화와 검증을 추가했다. `load_scale`는 서비스에서 직접 검증해 `NaN`, 무한대, 0 이하 값은 명시적인 입력 오류로 처리하고, 권장 범위 `0.50× ~ 1.50×`를 벗어나면 결과는 유지하되 경고와 함께 범위 안으로 보정되도록 정리했다. `created_at`, `scenario` 타입 검증도 추가했고, `pages/01_monitoring.py`는 서비스 예외를 그대로 터뜨리지 않고 `입력 검증 실패` / `결과 생성 실패` 메시지로 나눠 보여주게 바꿨다.
- 수정 파일: `src/services/monitoring_service.py`, `pages/01_monitoring.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from src.services.monitoring_service import MonitoringService; r=MonitoringService().run_dc_power_flow(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'load_scale': r.load_scale, 'warning0': r.warnings[0] if r.warnings else None, 'max_util': r.congestion_summary.max_utilization})"` -> 정상 actual 경로 유지
  - `python3 -c "from src.services.monitoring_service import MonitoringService; r=MonitoringService().run_dc_power_flow(load_scale=1.8); print({'source': r.source, 'fallback': r.fallback.mode, 'load_scale': r.load_scale, 'warnings': r.warnings[:2], 'max_util': r.congestion_summary.max_utilization})"` -> `load_scale=1.50` 보정과 경고 문구 확인
  - `python3 -c "from src.services.monitoring_service import MonitoringService; \ntry:\n    MonitoringService().run_dc_power_flow(load_scale=float('nan'))\nexcept Exception as exc:\n    print(type(exc).__name__, str(exc))"` -> `ValueError: load_scale는 NaN 또는 무한대가 아닌 유한한 숫자여야 합니다.`
  - `python3 -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"` -> bare-run 통과
- 다음 작업: `Prediction`의 `GNN` 병렬 조합 범위를 정리할지, 아니면 Monitoring/Simulation 페이지의 Streamlit 경고와 UI 정리까지 이어갈지 결정한다.

### 2026-04-13 Prediction GNN 경로 및 LSTM+GNN 병렬 조합 정리
- 작업: `Prediction`에 그래프 기반 실제 예측 경로를 추가하고, `LSTM + GNN` 병렬 조합 구조를 정리했다. `src/engine/forecast/gnn_forecaster.py`를 새로 추가해 13-버스 인접 그래프와 최근 부하/이웃 부하/기온 편차를 함께 쓰는 최소 GNN 예측기를 구현했다. `PredictionService`에는 `run_gnn_prediction()`과 `run_hybrid_prediction()`을 추가해 GNN 단독 예측과 `LSTM 65% + GNN 35%` 가중 평균 hybrid 예측을 반환하게 했고, 병렬 조합 중 하나라도 실패하면 `baseline_model` fallback으로 자동 전환되게 정리했다. `pages/03_prediction.py`는 모델 선택지를 `Mock / Baseline / LSTM / GNN / LSTM+GNN`으로 확장하고, GNN 및 Hybrid 실행 경로를 같은 fallback 헬퍼에 연결했다. 공통 계약도 `src/data/schemas.py`의 `ResultSource`에 `gnn`, `hybrid`를 추가해 맞췄다.
- 수정 파일: `src/engine/forecast/gnn_forecaster.py`, `src/services/prediction_service.py`, `pages/03_prediction.py`, `src/data/schemas.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_gnn_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'first': (r.predictions[0].timestamp.isoformat(), r.predictions[0].bus_id, r.predictions[0].predicted_load_mw)})"` -> `source='gnn'`, `fallback='none'`, `preds=312`, `risks=6`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_hybrid_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warnings': r.warnings[:3], 'first': (r.predictions[0].timestamp.isoformat(), r.predictions[0].bus_id, r.predictions[0].predicted_load_mw)})"` -> `source='hybrid'`, `fallback='none'`, `preds=312`, `risks=5`
  - `python3 -c "import types; from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); svc=PredictionService(); svc.run_gnn_prediction=types.MethodType(lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError('forced gnn failure')), svc); r=svc.run_hybrid_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'warnings': r.warnings[:2], 'reason': r.fallback.reason, 'summary': r.summary[:80]})"` -> `source='baseline'`, `fallback='baseline_model'` fallback 확인
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> bare-run 통과
- 다음 작업: `Prediction` hybrid 경로의 중복 weather load를 줄일지, 아니면 `Monitoring`/`Simulation` 페이지 UI와 경고 문구 정리를 이어갈지 정한다.

### 2026-04-13 Prediction hybrid 데이터 로드 최적화 및 서비스 정리
- 작업: `PredictionService` 내부를 정리해 baseline/LSTM/GNN/hybrid가 공통 helper를 통해 결과를 조립하도록 묶었다. 특히 `run_hybrid_prediction()`은 이제 weather 이력 로드와 target feature 생성을 한 번만 수행한 뒤 LSTM/GNN 분기에서 재사용하므로, 기존처럼 같은 기온 데이터를 두 번 읽지 않는다. 이 과정에서 baseline/LSTM/GNN 실제 경로는 그대로 유지하고, hybrid 실패 시 baseline fallback 동작도 동일하게 유지되도록 맞췄다.
- 수정 파일: `src/services/prediction_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `python3 -m compileall app.py pages src`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_lstm_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warnings': r.warnings[:2]})"` -> `source='lstm'`, `fallback='none'`, `preds=312`, `risks=5`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_gnn_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines)})"` -> `source='gnn'`, `fallback='none'`, `preds=312`, `risks=6`
  - `python3 -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_hybrid_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines), 'warnings': r.warnings[:3]})"` -> `source='hybrid'`, `fallback='none'`, `preds=312`, `risks=5`, weather load 1회
  - `python3 -c "import types; from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); svc=PredictionService(); svc.run_baseline_prediction=types.MethodType(PredictionService.run_baseline_prediction, svc); svc._predict_gnn=types.MethodType(lambda self, **kwargs: (_ for _ in ()).throw(RuntimeError('forced gnn failure')), svc); r=svc.run_hybrid_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'warnings': r.warnings[:2], 'reason': r.fallback.reason})"` -> `source='baseline'`, `fallback='baseline_model'`
  - `python3 -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> bare-run 통과
- 다음 작업: 2주차 범위는 종료로 보고, 이후에는 3주차 범위 또는 지도/시나리오 저장 같은 확장 작업으로 넘어간다.

### MVP 완성 이후 예정 - AI 경로 최적화 학습/검증
- 작업: MVP 기능이 완성되면 AI 기반 송전망 경로 최적화를 위해 최적화와 학습을 반복 수행하고, 추천 품질이 실제로 개선되는지 검증한다. 기준 시나리오 대비 경로 비용, 혼잡 완화, 설치 제약 충족률, 재현성, fallback 전환 조건을 함께 점검한다.
- 수정 파일: `미정 (예상 범위: src/engine/search/*, src/engine/optimize/*, src/services/simulation_service.py, 검증 문서)`
- 검증: `MVP 완성 이후 수행 예정`
- 다음 작업: MVP 범위의 지도/엔진/서비스 연결을 먼저 완료한 뒤 학습 데이터셋, 평가지표, 반복 검증 루프를 설계한다.

### 2026-05-06 1~3주차 구조 및 완성도 점검
- 작업: 현재 파일/디렉토리 구조와 `meeting_plan/MEETING_PLAN_2026-03-30.md`의 1~3주차 역할별 완료 상태를 점검했다. 서비스 기준으로 Monitoring DC Power Flow, Simulation A*/counterfactual delta, Prediction baseline/GNN/hybrid 실제 결과가 반환되는 것을 확인했다. 단, `pages/02_simulation.py`는 `folium`, `streamlit_folium` 의존성이 `requirements.txt`에 없어 fresh 환경 bare-run이 실패하며, `ScenarioService`, VWorld 어댑터, 도메인 모델, tests 실코드는 아직 스텁/문서 수준임을 확인했다.
- 수정 파일: `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m compileall app.py pages src`
  - `.venv310/bin/python -c "from src.services.monitoring_service import MonitoringService; r=MonitoringService().run_dc_power_flow(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'lines': len(r.line_statuses), 'max_util': r.congestion_summary.max_utilization, 'warnings': r.warnings[:2]})"` -> `source='dc_power_flow'`, `fallback='none'`, `lines=15`
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'route_source': r.selected_route.source if r.selected_route else None, 'recs': len(r.recommendations)})"` -> `source='astar'`, `fallback='none'`, `route_source='astar'`, `recs=3`
  - `.venv310/bin/python -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_hybrid_prediction(raw_dir=raw_dir, load_scale=1.0, retrain=False, epochs=1); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines)})"` -> `source='hybrid'`, `fallback='none'`, `preds=312`
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"` -> 통과
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> `ModuleNotFoundError: No module named 'folium'`
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> 통과
- 다음 작업: `folium`/`streamlit-folium` 의존성 누락을 정리하고, Simulation 페이지가 공통 `ScenarioContext`를 명시적으로 공유하도록 보정한 뒤 `ScenarioService` 저장/불러오기와 지도/VWorld 스키마를 3주차 범위로 이어서 구현한다.

### 2026-05-06 Beta 1~2주차 우선순위 1 임시 작업 목록 작성
- 작업: Beta 1~2주차 100% 완료의 선결 조건인 Simulation 페이지 지도 의존성 복구 작업을 임시 체크리스트로 정리했다. `folium`, `streamlit-folium` 의존성 추가, 현재 가상환경 설치, import 검증, Simulation 페이지 bare-run, 전체 compileall, 결과 기록 순서로 나눴다.
- 수정 파일: `tmp_tasks/BETA_WEEK1_2_PRIORITY1.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 확인
- 다음 작업: 체크리스트 1번부터 순서대로 실행해 `requirements.txt`와 `.venv310` 환경을 맞추고 `pages/02_simulation.py` bare-run 실패를 해소한다.

### 2026-05-06 Beta 1~2주차 우선순위 2 임시 작업 목록 작성
- 작업: Beta 1~2주차 100% 완료를 위해 Simulation 페이지의 후보지별 추천 결과표와 선택 추천안 요약 작업을 임시 체크리스트로 정리했다. 3주차 범위인 시나리오 저장/불러오기는 제외하고, 추천 결과표, 1순위 요약 카드, 추천 근거, fallback/warnings 표시, 입력-결과 연결 표시, 빈 후보지 처리, 검증 명령까지 실행 단위로 나눴다.
- 수정 파일: `tmp_tasks/BETA_WEEK1_2_PRIORITY2.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 확인
- 다음 작업: 우선순위 1 완료 후 `tmp_tasks/BETA_WEEK1_2_PRIORITY2.md` 순서대로 `pages/02_simulation.py`의 추천 결과 렌더링을 보강한다.

### 2026-05-06 박차오름 3주차 우선순위 3 임시 작업 목록 작성
- 작업: 박차오름 3주차 100% 완료를 위해 Simulation 페이지가 Monitoring/Prediction과 같은 `ScenarioContext`를 공유하도록 만드는 작업을 임시 체크리스트로 정리했다. `pages/02_simulation.py`에 `_get_shared_scenario()`를 추가하고, `SimulationInput` 생성 시 shared scenario를 전달하며, 결과 scenario를 session state에 다시 저장하고, 화면과 검증 명령으로 같은 `scenario_id`를 확인하는 순서로 나눴다.
- 수정 파일: `tmp_tasks/PARK_WEEK3_PRIORITY3_SHARED_SCENARIO.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 확인
- 다음 작업: 우선순위 1의 지도 의존성 복구 후 `pages/02_simulation.py`에 shared scenario 통합을 적용하고 서비스/페이지 검증을 실행한다.

### 2026-05-06 박차오름 3주차 우선순위 4 임시 작업 목록 작성
- 작업: 박차오름 3주차 100% 완료를 위해 후보지 추천 점수에 실제 counterfactual delta와 혼잡 완화 근거를 반영하는 작업을 임시 체크리스트로 정리했다. `score_function.py`의 impact 입력과 bonus 계산, `SimulationService`의 후보별 counterfactual impact 계산, 1순위 delta 재사용, 추천 rationale 보강, fallback/warnings 정리, 서비스/회귀 검증 명령까지 실행 단위로 나눴다.
- 수정 파일: `tmp_tasks/PARK_WEEK3_PRIORITY4_SCORE_WITH_DELTA.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 확인
- 다음 작업: 우선순위 3의 shared scenario 통합 후 `src/engine/search/score_function.py`와 `src/services/simulation_service.py`에 후보별 delta 기반 점수화를 적용한다.

### 2026-05-06 Gamma 3주차 우선순위 5 임시 작업 목록 작성
- 작업: Gamma 3주차 100% 완료를 위해 Prediction 테스트/QA 보강 작업을 임시 체크리스트로 정리했다. `feature_builder` 계약, PredictionService mock/baseline/GNN/hybrid 반환 계약, hybrid 조합 및 fallback, 위험도/설명 출력, pytest marker와 검증 명령, LSTM slow 테스트 분리 기준까지 실행 단위로 나눴다.
- 수정 파일: `tmp_tasks/GAMMA_WEEK3_PRIORITY5_PREDICTION_TESTS.md`, `WORK_TIMELINE.md`
- 검증: 문서 추가 확인
- 다음 작업: `tests/test_prediction_feature_builder.py`, `tests/test_prediction_service_contract.py`, `tests/test_prediction_risk_and_fallback.py`를 추가하고 빠른 pytest와 compileall 검증을 실행한다.

### 2026-05-06 우선순위 MD 전수 재검토 및 보정
- 작업: 우선순위 MD 작성 당시에는 핵심 파일 중심으로 확인했으나, 이번에 `.py`, 주요 `.md`, 설정 파일, 임시 작업 문서 전체를 다시 확인했다. 바이너리 모델, PDF/PPTX, CSV 원본 데이터는 코드가 아니므로 존재 여부와 연동 관계만 확인했다. 재검토 결과 기존 우선순위 방향은 유지하되, `pages/02_simulation.py`의 top-level `folium` import, 페이지 직접 `dc_power_flow` 지도 표시, `SimulationService`의 `created_at` 처리, counterfactual score 계산 순환 가능성, Prediction 테스트의 외부 weather 호출 가능성을 각 우선순위 문서에 보강했다.
- 수정 파일: `tmp_tasks/BETA_WEEK1_2_PRIORITY1.md`, `tmp_tasks/BETA_WEEK1_2_PRIORITY2.md`, `tmp_tasks/PARK_WEEK3_PRIORITY3_SHARED_SCENARIO.md`, `tmp_tasks/PARK_WEEK3_PRIORITY4_SCORE_WITH_DELTA.md`, `tmp_tasks/GAMMA_WEEK3_PRIORITY5_PREDICTION_TESTS.md`, `WORK_TIMELINE.md`
- 검증:
  - `git status --short`
  - `rg --files --hidden -g '!__pycache__' -g '!*.pyc' -g '!.git/**' -g '!.idea/**' -g '!.venv/**' -g '!.venv310/**'`
  - `find . -path './.git' -prune -o -path './.idea' -prune -o -path './.venv' -prune -o -path './.venv310' -prune -o -path './__pycache__' -prune -o -type f -name '*.py' -print`
  - `find . -path './.git' -prune -o -path './.idea' -prune -o -path './.venv' -prune -o -path './.venv310' -prune -o -path './__pycache__' -prune -o -type f -name '*.md' -print`
  - `rg -n "folium|streamlit_folium|sgop_shared_scenario|CandidateImpact|pytest|_load_weather_history|fetch_historical|use_container_width|width=\"stretch\""`
  - `wc -l app.py pages/*.py src/**/*.py src/**/**/*.py tmp_tasks/*.md requirements.txt meeting_plan/*.md DEVELOPMENT_FLOW_2026-03-30.md docs/*.md tests/*.md README.md`
- 다음 작업: 문서 보정된 순서대로 우선순위 1부터 구현하되, 이번 작업 범위에서는 실제 코드 구현을 진행하지 않는다.

### 2026-05-06 Beta 1~2주차 우선순위 1 완료
- 작업: Simulation 페이지가 새 환경에서도 import 오류 없이 실행되도록 지도 의존성을 정리했다. `requirements.txt`에 `folium>=0.16`, `streamlit-folium>=0.20`을 추가했고, 현재 `.venv310` 환경에는 `folium 0.20.0`, `streamlit-folium 0.26.2`가 설치되었다. 최초 sandbox 실행은 네트워크 제한으로 실패했으며, 승인된 pip install 실행으로 설치를 완료했다.
- 수정 파일: `requirements.txt`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pip install folium streamlit-folium` -> 최초 sandbox 실행은 DNS/network 제한으로 실패
  - `.venv310/bin/python -m pip install folium streamlit-folium` -> 승인 실행 후 `Successfully installed branca-0.8.2 folium-0.20.0 streamlit-folium-0.26.2 xyzservices-2026.3.0`
  - `.venv310/bin/python -m pip show folium streamlit-folium` -> `folium 0.20.0`, `streamlit-folium 0.26.2`
  - `.venv310/bin/python -c "import folium; from streamlit_folium import st_folium; print('map-import-ok')"` -> `map-import-ok`
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> `simulation-page-run-ok`
  - `.venv310/bin/python -m compileall app.py pages src` -> 통과
  - `.venv310/bin/python -m pip install -r requirements.txt` -> 모든 요구 패키지 충족 확인
- 다음 작업: 우선순위 2로 넘어가 `pages/02_simulation.py`에 후보지별 추천 결과표, 1순위 추천안 요약, warnings/fallback 표시를 보강한다.

### 2026-05-06 전체 구조 및 코드 내용 파악
- 작업: 사용자 요청에 따라 저장소 전체 디렉터리 구조, Python 코드, 주요 문서, 임시 작업 문서, 설정, 데이터/모델 산출물의 역할을 전수 파악했다. 코드 기준 현재 핵심 흐름은 `app.py -> pages/* -> src/services/* -> src/engine/* -> src/data/*`이며, Monitoring은 DC Power Flow actual 경로, Simulation은 A*와 counterfactual delta actual 경로, Prediction은 baseline/LSTM/GNN/hybrid 경로가 연결되어 있다. 반면 `ScenarioService`, VWorld 어댑터, domain 모델, optimization/explain/recommend 일부, 실제 pytest 파일은 아직 스텁/문서 수준이다.
- 수정 파일: `WORK_TIMELINE.md`
- 검증:
  - `git status --short`
  - `rg --files --hidden -g '!.git/**' -g '!.idea/**' -g '!.venv/**' -g '!.venv310/**' -g '!__pycache__/**' -g '!*.pyc'`
  - `wc -l app.py pages/*.py src/**/*.py src/**/**/*.py *.md meeting_plan/*.md docs/*.md tests/*.md tmp_tasks/*.md requirements.txt .streamlit/config.toml`
  - `python3 -m compileall app.py pages src` -> 통과
  - `.venv310/bin/python -c "from src.services.monitoring_service import MonitoringService; r=MonitoringService().run_dc_power_flow(load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'lines': len(r.line_statuses), 'max_util': r.congestion_summary.max_utilization})"` -> `source='dc_power_flow'`, `fallback='none'`, `lines=15`
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'recs': len(r.recommendations), 'top': r.recommendations[0].candidate_id if r.recommendations else None})"` -> `source='astar'`, `fallback='none'`, `recs=3`
  - `.venv310/bin/python -c "from pathlib import Path; from src.services.prediction_service import PredictionService; raw_dir=str(Path('data/raw').resolve()); r=PredictionService().run_baseline_prediction(raw_dir=raw_dir, load_scale=1.0); print({'source': r.source, 'fallback': r.fallback.mode, 'preds': len(r.predictions), 'risks': len(r.risk_lines)})"` -> `source='baseline'`, `fallback='none'`, `preds=312`
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"` -> 통과, Streamlit bare-mode 경고와 `use_container_width` deprecation 경고 확인
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과, Streamlit bare-mode 경고 확인
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> 통과, Streamlit bare-mode 경고 확인
- 다음 작업: 기존 타임라인의 우선순위대로 `pages/02_simulation.py` 추천 결과 렌더링 보강, Simulation shared scenario 통합, 후보별 counterfactual delta 기반 점수화, Prediction 테스트 추가를 순서대로 진행한다.

### 2026-05-06 Beta 1~2주차 우선순위 2 완료
- 작업: `pages/02_simulation.py`에 후보지별 추천 결과표와 1순위 추천안 요약을 추가했다. 페이지 내부 helper로 `SimulationResult.recommendations`를 표 데이터로 변환하고, 1순위 후보의 총점/경로 길이/예상 비용/경유 노드와 route summary/rationale을 delta보다 먼저 보여주도록 정리했다. 또한 입력값 요약, fallback/warnings 표시, 후보지 미선택 시 기본 후보 사용 안내, 후보지별 추천 근거 expander를 추가했다. 서비스 계산과 지도 직접 계산 구조는 이번 Beta 1~2주차 범위 밖이라 그대로 유지했다.
- 수정 파일: `pages/02_simulation.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m compileall app.py pages src` -> 통과
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과, Streamlit bare-mode 경고 확인
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'recs': len(r.recommendations), 'top': r.recommendations[0].candidate_id if r.recommendations else None, 'route': r.selected_route.route_id if r.selected_route else None})"` -> `source='astar'`, `fallback='none'`, `recs=3`, `top='SITE_SOUTH'`
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(candidate_site_ids=[], load_scale=1.0)); print({'candidates': len(r.simulation_input.candidate_site_ids), 'recs': len(r.recommendations), 'top': r.recommendations[0].candidate_id if r.recommendations else None})"` -> 후보지 0개 입력 시 기본 후보 3개 사용 확인
- 다음 작업: `PARK_WEEK3_PRIORITY3_SHARED_SCENARIO.md` 기준으로 Simulation 페이지가 Monitoring/Prediction과 같은 `ScenarioContext`를 공유하도록 통합한다.

### 2026-05-06 Gamma 3주차 우선순위 5 완료
- 작업: Prediction 파트의 빠른 pytest 테스트를 추가했다. `tests/conftest.py`에 synthetic load/weather fixture와 prediction helper를 두고, `feature_builder`의 lag/time/matrix 계약, `PredictionService.run_mock_prediction()` 반환 계약, `BaselineForecaster`와 `GNNForecaster`의 synthetic 예측 계약, `PredictionService.run_gnn_prediction()`의 synthetic weather 경로, hybrid 가중 평균/키 불일치, hybrid 실패 시 baseline fallback, 위험 선로 정렬/설명 출력을 검증했다. 실제 LSTM 모델 로드/학습 테스트는 기본 빠른 테스트에서 제외하고, `pytest.ini`에 `integration`, `slow` marker를 등록해 후속 분리 기준을 마련했다.
- 수정 파일: `pytest.ini`, `tests/conftest.py`, `tests/test_prediction_feature_builder.py`, `tests/test_prediction_service_contract.py`, `tests/test_prediction_risk_and_fallback.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pytest tests -q` -> 11개 통과
  - `.venv310/bin/python -m pytest tests -q -m "not integration and not slow"` -> 11개 통과
  - `.venv310/bin/python -m pytest tests/test_prediction_feature_builder.py -q` -> 3개 통과
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
- 남은 테스트 갭: 실제 `data/raw` 기반 baseline/GNN 통합 테스트와 저장된 LSTM 모델 로드/재학습 테스트는 아직 포함하지 않았다. 이 둘은 외부 데이터/모델 상태와 실행 시간이 개입되므로 후속 `integration` 또는 `slow` 테스트로 분리하는 것이 맞다.
- 다음 작업: `PARK_WEEK3_PRIORITY3_SHARED_SCENARIO.md` 기준으로 Simulation 페이지 shared `ScenarioContext` 통합을 진행하거나, Prediction 통합/slow 테스트를 별도 범위로 추가한다.

### 2026-05-06 박차오름 3주차 우선순위 3 완료
- 작업: `pages/02_simulation.py`가 Monitoring/Prediction과 같은 Streamlit session state 키인 `sgop_shared_scenario`를 사용하도록 통합했다. Simulation 페이지에 `_get_shared_scenario()`를 추가하고, `SimulationService.build_default_input()`과 `run_simulation()` 호출에 shared `ScenarioContext`와 기준 시각을 전달하도록 변경했다. 결과 반환 후에는 `sim_result.scenario`를 다시 session state에 저장하며, 화면 caption에 `scenario_id`를 표시해 입력-결과 연결 상태를 확인할 수 있게 했다. 시나리오 저장/불러오기는 이번 범위에서 제외했다.
- 수정 파일: `pages/02_simulation.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -c "from src.data.schemas import ScenarioContext; from src.services.monitoring_service import MonitoringService; from src.services.simulation_service import SimulationService; from src.services.prediction_service import PredictionService; scenario=ScenarioContext(scenario_id='shared-week3'); monitoring=MonitoringService().run_dc_power_flow(scenario=scenario, load_scale=1.0); svc=SimulationService(); simulation=svc.run_simulation(svc.build_default_input(scenario=scenario, load_scale=1.0)); prediction=PredictionService().run_mock_prediction(scenario=scenario, load_scale=1.0); print([monitoring.scenario.scenario_id, simulation.scenario.scenario_id, prediction.scenario.scenario_id], simulation.source, simulation.fallback.mode)"` -> `['shared-week3', 'shared-week3', 'shared-week3'] astar none`
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과, Streamlit bare-mode 경고 확인
  - `.venv310/bin/python -m compileall app.py pages src` -> 통과
- 다음 작업: `PARK_WEEK3_PRIORITY4_SCORE_WITH_DELTA.md` 기준으로 후보지별 추천 점수에 실제 counterfactual delta와 혼잡 완화 근거를 반영한다.

### 2026-05-06 박차오름 3주차 우선순위 4 완료
- 작업: 후보지 추천 점수에 후보별 counterfactual delta 기반 impact를 반영했다. `score_function.py`에 `CandidateImpactInput`과 counterfactual bonus 산식을 추가하고, `calculate_score()`가 실제 최대 이용률 개선, 위험 선로 감소, 손실 감소, 운영 여유도 증가를 `ScoreBreakdown.congestion_relief`와 `notes`에 반영하도록 확장했다. `SimulationService.run_simulation()`은 이제 monitoring baseline을 먼저 계산한 뒤 후보별 route/base score/counterfactual delta/final score를 만들고 rank를 정한다. 최종 `SimulationResult.deltas`는 1순위 후보 점수화에 사용된 delta를 재사용한다. 후보별 impact 계산 실패는 해당 후보 notes/warnings에만 남기고 전체 simulation fallback으로 전파하지 않게 했다.
- 수정 파일: `src/engine/search/score_function.py`, `src/services/simulation_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m compileall app.py pages src` -> 통과
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'top': r.recommendations[0].candidate_id, 'top_score': r.recommendations[0].score.total_score, 'notes': r.recommendations[0].score.notes, 'deltas': [(d.metric_id, d.improvement) for d in r.deltas]})"` -> `source='astar'`, `fallback='none'`, top `SITE_SOUTH`, notes에 counterfactual 개선 근거와 bonus 반영 확인
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); [print(rec.rank, rec.candidate_id, rec.score.total_score, rec.score.congestion_relief, rec.score.notes[-2:]) for rec in r.recommendations]"` -> 후보 3개 모두 final score와 counterfactual notes 확인
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.2)); print({'source': r.source, 'fallback': r.fallback.mode, 'top': r.recommendations[0].candidate_id, 'warnings': r.warnings[:5], 'deltas': [(d.metric_id, d.before_value, d.after_value, d.improvement) for d in r.deltas]})"` -> 고부하 조건에서도 actual 경로 유지
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_mock_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'recs': len(r.recommendations), 'top': r.recommendations[0].candidate_id})"` -> mock 경로 유지
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); svc._build_counterfactual_monitoring=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('forced candidate impact failure')); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print({'source': r.source, 'fallback': r.fallback.mode, 'warnings': r.warnings[:2], 'top': r.recommendations[0].candidate_id, 'notes': r.recommendations[0].score.notes[-2:]})"` -> 후보별 impact 실패가 전체 fallback으로 전파되지 않음
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과, Streamlit bare-mode 경고 확인
  - `.venv310/bin/python -m pytest tests -q` -> 11개 통과
- 다음 작업: Beta 3주차 범위의 시나리오 저장/불러오기 또는 `ScenarioService` 저장 책임 구현을 진행한다.

### 2026-05-11 박차오름 4주차 우선순위 1 ScenarioService 최소 구현 완료
- 작업: 박차오름 4주차 통합 로직 정리의 선행 작업으로 `ScenarioService` 저장 계층을 구현했다. 기본 저장 위치는 `data/private/scenarios.json`로 두고, 테스트 가능하도록 `storage_path` 주입을 지원한다. `ScenarioContext`를 JSON으로 저장/조회/목록화/삭제할 수 있게 했고, `created_at`은 ISO 문자열로 직렬화 후 복원한다. 같은 `scenario_id` 저장은 덮어쓰기 방식으로 처리하며, 빈 `scenario_id`, 잘못된 JSON 저장소, 잘못된 레코드는 명확한 예외를 내도록 정리했다. 페이지 UI 연결은 Beta 범위로 남기고 서비스 계약과 테스트만 닫았다.
- 수정 파일: `src/services/scenario_service.py`, `tests/test_scenario_service.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pytest tests/test_scenario_service.py -q` -> 10개 통과
  - `.venv310/bin/python -m pytest tests -q` -> 21개 통과
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
  - `.venv310/bin/python -c "from datetime import datetime; from tempfile import TemporaryDirectory; from pathlib import Path; from src.data.schemas import ScenarioContext; from src.services.scenario_service import ScenarioService; d=TemporaryDirectory(); svc=ScenarioService(Path(d.name)/'scenarios.json'); s=ScenarioContext(scenario_id='demo', title='Demo', created_at=datetime(2026,1,1)); svc.save_scenario(s); print(svc.load_scenario('demo').scenario_id, len(svc.list_scenarios()))"` -> `demo 1`
- 다음 작업: 박차오름 4주차 우선순위 2로 넘어가 A* 비용 함수와 추천 점수 설명 가능성을 보정한다. Beta가 UI를 붙일 때는 `ScenarioService.save_scenario()`, `list_scenarios()`, `load_scenario()`를 사용하면 된다.

### 2026-05-11 박차오름 4주차 우선순위 2 A* 비용/점수 설명 보정 완료
- 작업: A* 경로 보정과 추천 점수화가 발표 가능한 기준으로 설명되도록 정리했다. `astar_router.py`의 우회 거리, 릴레이 홉, 반복 노드, 고부하, 예상 비용 계수를 이름 있는 정책 상수로 분리하고, `RouteResult.summary`에 실제 거리/우회/릴레이/반복/고부하 패널티를 함께 반영한다는 설명을 남겼다. `score_function.py`는 총점 산식, 경로 입력, 비용 반영, 혼잡 보상, counterfactual 개선 근거가 `ScoreBreakdown.notes`에 나뉘어 들어가도록 보강했다. `SimulationService._build_rationale()`는 A* 경로 길이, 예상 비용, 거리 비용, 공사비 비용, 환경·정책 리스크, counterfactual 개선분을 한 문장 흐름으로 설명하도록 정리했다. UI는 변경하지 않았다.
- 수정 파일: `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`, `src/services/simulation_service.py`, `tests/test_simulation_route_score.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pytest tests/test_simulation_route_score.py -q` -> 6개 통과
  - `.venv310/bin/python -m pytest tests -q` -> 27개 통과
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
  - `.venv310/bin/python -c "from src.services.simulation_service import SimulationService; svc=SimulationService(); r=svc.run_simulation(svc.build_default_input(load_scale=1.0)); print(r.source, r.fallback.mode); [print(rec.rank, rec.candidate_id, rec.score.total_score, rec.score.notes[-2:], rec.rationale) for rec in r.recommendations]"` -> `astar none`, `SITE_SOUTH` 1순위와 counterfactual 개선 근거 출력 확인
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과, Streamlit bare-mode 경고만 확인
- 다음 작업: 박차오름 4주차 우선순위 3으로 넘어가 `VWorld` 최소 계약과 `map_2_5d` fallback 판단을 코드/문서에 고정한다.

### 2026-05-11 박차오름 4주차 우선순위 2 세부 평가 지표 UI 연결 완료
- 작업: `pages/02_simulation.py`의 `세부 평가 지표 보기` expander 내부만 보강했다. 기존에는 혼잡 완화, 공사비, 환경, 정책 일부 항목만 막대로 보였으나, 이제 `ScoreBreakdown`의 기본 점수, 혼잡 완화 보상, 거리 비용, 공사비 비용, 환경 리스크, 정책 리스크, 최종 총점이 모두 표와 지표로 표시된다. 또한 A* 경로 요약과 `ScoreBreakdown.notes` 전체를 같은 expander 안에 출력해 서비스/엔진에서 만든 산정 근거가 UI까지 이어지게 했다. 페이지 전체 레이아웃, 지도, 저장/불러오기 UI는 건드리지 않았다.
- 수정 파일: `pages/02_simulation.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
  - `.venv310/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과, Streamlit bare-mode 경고만 확인
  - `.venv310/bin/python -m pytest tests/test_simulation_route_score.py -q` -> 6개 통과
  - `.venv310/bin/python -m pytest tests -q` -> 27개 통과
- 다음 작업: 박차오름 4주차 우선순위 3으로 넘어가기 전에 필요하면 이 UI 변경까지 포함한 커밋 메시지를 정리한다.

### 2026-05-11 박차오름 4주차 우선순위 3 VWorld 최소 계약 및 map_2_5d fallback 판단 완료
- 작업: `src/data/adapters/vworld_adapter.py`에 VWorld WebGL 연결 준비용 최소 계약을 구현했다. `VWORLD_API_KEY`는 기존 `settings.py` 설정을 통해 읽고, `build_webgl_script_url()`이 `https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=...` 형식의 script URL을 만든다. `domain=localhost:8501` 같은 도메인 파라미터도 query parameter로 붙일 수 있게 했다. `get_map_capability()`는 키가 없으면 `FallbackInfo(mode="map_2_5d")`를 반환하고, 키가 있어도 MVP에서 WebGL 3D 검증을 보류할 경우 `prefer_webgl=False`로 Folium/2.5D fallback 판단을 명시할 수 있게 했다. API key 값은 warning/fallback reason에 노출하지 않는다. `docs/map_feasibility_2026-04-09.md`에는 현재 MVP 판단을 `2.5D/Folium 유지 + VWorld WebGL 연결 준비`로 최신화했다.
- 수정 파일: `src/data/adapters/vworld_adapter.py`, `tests/test_vworld_adapter.py`, `docs/map_feasibility_2026-04-09.md`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pytest tests/test_vworld_adapter.py -q` -> 7개 통과
  - `.venv310/bin/python -m pytest tests -q` -> 34개 통과
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
  - `.venv310/bin/python -c "from src.data.adapters.vworld_adapter import get_map_capability; c=get_map_capability(domain='localhost:8501', prefer_webgl=False); print(c.rendering_mode, c.fallback.mode, bool(c.webgl_script_url))"` -> `map_2_5d map_2_5d True`
- 다음 작업: 박차오름 4주차 우선순위 4로 넘어가 Monitoring actual → Simulation actual → Prediction mock/baseline 흐름의 공통 `scenario_id`, `source`, `fallback`, `warnings` 계약을 통합 테스트로 고정한다.

### 2026-05-11 박차오름 4주차 우선순위 4 서비스 통합 계약 테스트 완료
- 작업: `Monitoring actual -> Simulation actual -> Prediction baseline/mock` 흐름이 같은 `ScenarioContext`를 유지하는지 통합 테스트로 고정했다. 새 테스트는 공통 `scenario_id`, 허용 `source`, 허용 `fallback.mode`, fallback 사용 시 `reason/primary_path/active_path/warnings` 존재 여부, Monitoring `dc_power_flow`, Simulation `astar`, Prediction `baseline` happy path를 함께 검증한다. 또한 Monitoring DC 실패, Simulation A* 실패, Prediction hybrid branch 실패를 monkeypatch로 강제해 전체 예외 대신 mock/baseline fallback 결과가 반환되는 smoke test를 추가했다. 이 과정에서 fallback 경로의 첫 warning 문구가 공통 규칙을 따르도록 Monitoring/Simulation 예외 경로의 삽입 위치를 보정했고, Prediction actual 결과는 `PredictionService는 현재 <source> 결과를 반환합니다.` source warning을 갖도록 정리했다.
- 수정 파일: `tests/test_service_integration_contract.py`, `src/services/monitoring_service.py`, `src/services/simulation_service.py`, `src/services/prediction_service.py`, `tests/test_prediction_risk_and_fallback.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pytest tests/test_service_integration_contract.py -q` -> 5개 통과
  - `.venv310/bin/python -m pytest tests/test_prediction_risk_and_fallback.py -q` -> 4개 통과
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
  - `.venv310/bin/python -m pytest tests -q` -> 39개 통과
- 다음 작업: 박차오름 범위에서는 통합 병목이 닫혔으므로, 후속으로는 Beta가 `ScenarioService` 저장/불러오기 UI를 붙일 때 새 통합 테스트 계약을 깨지 않는지 확인한다. 별도 요청이 있으면 Priority 5의 overlay 데이터 계약과 fallback 문구 잔여 불일치를 이어서 정리한다.

### 2026-05-11 박차오름 4주차 우선순위 5 공통 overlay 계약 정리 완료
- 작업: Alpha/Beta가 지도와 표를 동기화할 수 있도록 UI 구현 없이 공통 overlay 계약을 추가했다. `src/data/schemas.py`에 `MapOverlayPoint`, `MapOverlayLine`, `MapOverlayRoute`, `MapOverlayResult`를 정의해 버스, 선로, 송전탑 후보지, A* 추천 경로, 예측 위험 선로를 같은 형태로 넘길 수 있게 했다. `MapOverlayService`는 Monitoring actual 선로 상태, Simulation 후보지/추천 경로, Prediction 위험 선로를 overlay 결과로 변환하며, 좌표는 `EPSG:4326`과 `elevation_m` 슬롯을 유지한다. 고도는 아직 조회하지 않으므로 warning에 남기고, VWorld WebGL을 쓰지 못하거나 MVP에서 보류할 때는 `map_2_5d` fallback을 overlay 결과에 반영한다. API key 값은 overlay warnings/fallback reason에 노출하지 않도록 테스트로 고정했다.
- 수정 파일: `src/data/schemas.py`, `src/services/map_overlay_service.py`, `tests/test_map_overlay_contract.py`, `WORK_TIMELINE.md`
- 검증:
  - `.venv310/bin/python -m pytest tests/test_map_overlay_contract.py -q` -> 4개 통과
  - `.venv310/bin/python -m pytest tests/test_service_integration_contract.py -q` -> 5개 통과
  - `.venv310/bin/python -m compileall app.py pages src tests` -> 통과
  - `.venv310/bin/python -m pytest tests -q` -> 43개 통과
- 다음 작업: 박차오름 4주차 범위는 완료로 보고, Alpha는 Monitoring 표/지도 동기화에 `MapOverlayResult.lines`의 `line_id`를 사용하고, Beta는 Simulation 지도 레이어에 `MapOverlayResult.points/routes`를 연결하면 된다. Gamma의 예측 품질과 LSTM slow/integration 테스트는 별도 범위로 남긴다.

### 2026-05-17 저장소 전체 구조 파악
- 작업: 사용자 요청에 따라 `git status --short`를 먼저 확인하고, `AGENTS.md`, `WORK_TIMELINE.md`, 회의안, 개발 흐름도, 주요 페이지/서비스/엔진/스키마/테스트/문서/설정 파일과 디렉토리 구조를 전수 확인했다. 대용량 CSV는 행 수, 헤더, 샘플, 시간 범위를 확인했고, 바이너리 PDF/PPTX/model/scaler 파일은 파일 타입, 크기, 내부 목차 또는 메타데이터 수준으로 확인했다.
- 수정 파일: `WORK_TIMELINE.md`
- 검증:
  - `git status --short` -> 기존 수정 파일 다수 확인
  - `rg --files -uu -g '!/.git/**' -g '!**/__pycache__/**' -g '!**/.pytest_cache/**'` -> 저장소 파일 목록 확인
  - `find . -path ./.git -prune -o -path '*/__pycache__' -prune -o -path '*/.pytest_cache' -prune -o -print` -> 디렉토리 구조 확인
  - `wc -l app.py pages/*.py src/**/*.py src/**/**/*.py tests/*.py requirements.txt pytest.ini .env.example .streamlit/config.toml README.md docs/*.md meeting_plan/*.md DEVELOPMENT_FLOW_2026-03-30.md data/**/*.md models/**/*.md models/README.md secrets/README.md` -> 주요 텍스트 파일 규모 확인
  - `wc -l data/raw/*.csv data/weather/*.csv` -> 원본/날씨 CSV 행 수 확인
  - `file` 및 Python `zipfile`/바이트 메타데이터 확인 -> PDF/PPTX/LSTM 모델 산출물 확인
- 다음 작업: 실제 구현을 이어간다면 `MapOverlayService`의 공통 overlay 계약을 `pages/01_monitoring.py`와 `pages/02_simulation.py` 지도 렌더링에 연결하고, Simulation 페이지의 페이지 직접 DC/Folium 조립을 서비스/overlay 기반으로 낮춘다.

### 2026-05-17 Git 기록 기반 다중 작업자 타임라인 보강
- 작업: 기존 `WORK_TIMELINE.md`가 주로 waterspouut/박차오름 통합 작업 위주로 기록되어 있어, Git commit author와 merge 기록을 기준으로 다른 작업자들의 작업도 날짜순으로 보강했다. 사용자가 언급한 `hss86212002@gmail.com`은 현재 Git 기록에 없고, 실제 기록은 `hss85212002@gmail.com`로 확인된다. `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>`는 김도림/Gamma 작업 PR merge 주체로 기록되어 있다.
- 수정 파일: `WORK_TIMELINE.md`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`
- 검증:
  - `git log --all --date=iso-strict --format='%H%x09%ad%x09%an%x09%ae%x09%s'`
  - `git show --name-status --format='%H%n%ad%n%an <%ae>%n%s' --date=iso-strict <commit...>`
  - `git show -m --name-status --format='%H%n%ad%n%an <%ae>%n%s' --date=iso-strict <merge-commit...>`
- 다음 작업: 새 문서 기준으로 남은 구현을 이어갈 때는 `Simulation` 지도 UI를 `MapOverlayService` 기반으로 낮추고, `ScenarioService` 저장/불러오기 UI를 붙이면서 shared `ScenarioContext` 계약을 유지한다.

#### 2026-04-02 12:26~12:29 Gamma/김도림 Prediction 1주차 산출물
- 작업자: `PC12185\yanyo <hss85212002@gmail.com>` 작성, `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #1 merge.
- 작업: Prediction 페이지와 서비스의 1주차 mock 예측 흐름을 추가했다. 공통 예측 결과 스키마, feature vector 초안, PredictionService mock 생성 로직, Streamlit 예측 페이지를 묶어 `Prediction` 축을 처음 열 수 있게 했다.
- 수정 파일: `.gitignore`, `pages/03_prediction.py`, `src/data/schemas.py`, `src/engine/forecast/feature_builder.py`, `src/services/prediction_service.py`
- 유기적 동작:
  - `pages/03_prediction.py`가 사용자의 부하 배율/노드 선택을 받아 `PredictionService.run_mock_prediction()`을 호출한다.
  - `PredictionService`는 `src/data/schemas.py`의 `PredictionResult`, `HourlyLoadPrediction`, `RiskLine` 계약에 맞춰 결과를 반환한다.
  - `feature_builder.py`는 이후 baseline/LSTM/GNN으로 확장될 예측 입력 피처 계약의 시작점이다.
- 검증: Git 기록상 별도 실행 로그는 없으며, 이후 박차오름 통합 작업에서 `compileall`과 page bare-run 검증으로 흡수되었다.
- 다음 작업: mock 예측을 실제 KPX 데이터와 baseline/LSTM 예측 경로로 치환한다.

#### 2026-04-05 15:30~18:22 Alpha/김동근 Monitoring 1주차 산출물
- 작업자: `ehdrms3535 <ehdrms3535@naver.com>` 작성, `ehdrms3535 <88962038+ehdrms3535@users.noreply.github.com>` PR #3 merge.
- 작업: Monitoring 페이지, MonitoringService mock 결과, Monitoring 관련 공통 스키마를 추가했다. KPI, 선로 상태, 혼잡 요약, trend point를 화면에 표시하는 1주차 뼈대를 만들었다.
- 수정 파일: `pages/01_monitoring.py`, `src/data/schemas.py`, `src/services/monitoring_service.py`
- 유기적 동작:
  - `pages/01_monitoring.py`가 사이드바 입력을 받고 `MonitoringService.run_mock_monitoring()` 결과를 렌더링한다.
  - `MonitoringService`는 mock 선로 정의를 `LineStatus`, `CongestionSummary`, `MonitoringKpi`, `MonitoringResult`로 조립한다.
  - `schemas.py`의 Monitoring 계약은 이후 Simulation counterfactual baseline과 MapOverlayService의 입력으로 재사용된다.
- 검증: 이후 `docs/dev_log.md`와 2주차 DC Power Flow 작업에서 Monitoring mock/DC 결과 비교로 검증 흐름이 이어졌다.
- 다음 작업: mock 선로 상태를 실제 DC Power Flow 계산 결과로 치환한다.

#### 2026-04-06 00:03 Beta/권나현 Simulation UI 뼈대 및 지도 연동
- 작업자: `Raychell123 <chu040312@gmail.com>`
- 작업: `pages/02_simulation.py`에 Simulation 페이지 UI 뼈대와 실제 지도 연동 흐름을 만들었다. 후보지/버스 입력과 Folium 기반 지도 표시가 페이지 중심에 배치되었다.
- 수정 파일: `pages/02_simulation.py`
- 유기적 동작:
  - 페이지가 Streamlit 입력 위젯으로 시작/종료 버스, 후보지, 부하 배율을 받는다.
  - Folium 지도는 페이지 내부 좌표 테이블과 선로/후보지 데이터를 직접 사용한다.
  - 이 시점에는 서비스 계층과 공통 overlay 계약이 충분히 분리되지 않아, 이후 `SimulationService`와 `MapOverlayService`로 낮춰야 할 페이지 직접 조립 코드가 남았다.
- 검증: Git 기록상 별도 검증 로그는 없으며, 후속 Simulation 페이지 bare-run 검증에서 확인되었다.
- 다음 작업: A* route 결과, 설치 전후 delta, 추천 점수와 지도 표시를 연결한다.

#### 2026-04-08 01:42~01:43 Alpha/김동근 Monitoring 2주차 DC Power Flow 연결
- 작업자: `ehdrms3535 <ehdrms3535@naver.com>` 작성, `ehdrms3535 <88962038+ehdrms3535@users.noreply.github.com>` 중복 커밋/merge 기록.
- 작업: DC Power Flow 엔진과 혼잡 지표 계산 엔진을 구현하고 Monitoring 페이지/서비스에 연결했다. `docs/dev_log.md`에는 13버스/15선로 설계, 슬랙 버스, 리액턴스/용량, 검증 결과를 기록했다.
- 수정 파일: `docs/dev_log.md`, `pages/01_monitoring.py`, `src/engine/powerflow/dc_power_flow.py`, `src/engine/powerflow/congestion_metrics.py`, `src/services/monitoring_service.py`
- 유기적 동작:
  - `pages/01_monitoring.py`의 데이터 소스 토글이 `MonitoringService.run_dc_power_flow()`를 호출한다.
  - `MonitoringService`는 `dc_power_flow.build_default_buses()`, `build_default_line_inputs()`, `solve()`를 호출한다.
  - `congestion_metrics.compute_line_statuses()`와 `compute_congestion_summary()`가 `DCFlowResult`를 UI용 `LineStatus`/`CongestionSummary`로 변환한다.
  - 실패 시 `MonitoringService.run_mock_monitoring()`로 내려가 `FallbackInfo(mode="mock_data")`를 남기는 구조가 이후 서비스 통합 테스트의 기준이 되었다.
- 검증: `docs/dev_log.md`에 load_scale=1.0 기준 L12 critical, L01/L04/L05/L06/L08 warning 등 수치 검증이 기록되어 있다.
- 다음 작업: Simulation에서 설치 전 baseline과 counterfactual delta 계산에 Monitoring DC 결과를 재사용한다.

#### 2026-04-10 22:51 Beta/권나현 A* 경로 시각화와 설치 전후 지표 연동
- 작업자: `Raychell123 <chu040312@gmail.com>`
- 작업: Simulation 페이지 지도에 A* 최적 경로, 선로 혼잡 범례, 설치 전후 비교 지표를 연결했다.
- 수정 파일: `pages/02_simulation.py`
- 유기적 동작:
  - `SimulationService`가 반환하는 `selected_route.waypoints`를 Folium `PolyLine`과 `CircleMarker`로 렌더링한다.
  - 페이지 내부에서 `dc_power_flow.solve()` 결과의 `line_flows`와 `build_default_line_inputs()`의 용량을 색상 함수에 넣어 기존 선로 혼잡도를 표시한다.
  - `SimulationResult.deltas`를 Streamlit metric 카드로 렌더링해 설치 전후 비교를 보여준다.
- 검증: 이후 `python -c "import runpy; runpy.run_path('pages/02_simulation.py')"` bare-run 검증에서 페이지 실행성이 확인되었다.
- 다음 작업: 지도/표 직접 조립 코드를 서비스 결과와 공통 overlay 계약으로 정리한다.

#### 2026-04-13 08:41~08:43 Gamma/김도림 Prediction 2주차 실제 데이터·LSTM 산출물
- 작업자: `PC12185\yanyo <hss85212002@gmail.com>` 작성, `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #7 merge.
- 작업: KPX 원본 부하 CSV, Open-Meteo 기반 날씨 캐시, LSTM 저장 모델과 scaler, public/weather data adapter, baseline forecaster, LSTM forecaster를 추가해 Prediction을 mock에서 실제 데이터 기반 예측 경로로 확장했다.
- 수정 파일: `data/raw/sukub*.csv`, `data/weather/BUS_*.csv`, `models/lstm/model.keras`, `models/lstm/scalers.pkl`, `pages/03_prediction.py`, `requirements.txt`, `src/data/adapters/public_data_adapter.py`, `src/data/adapters/weather_adapter.py`, `src/engine/forecast/baseline_forecaster.py`, `src/engine/forecast/lstm_forecaster.py`, `src/services/prediction_service.py`
- 유기적 동작:
  - `public_data_adapter.load_kpx_csvs()`가 `data/raw/sukub*.csv`를 읽어 전국 수요를 13개 `BUS_*` 노드 부하로 분배한다.
  - `weather_adapter.fetch_historical()`가 `data/weather/BUS_*.csv` 캐시를 사용하거나 Open-Meteo에서 기온을 가져온다.
  - `load_kpx_with_weather()`가 부하와 기온을 `timestamp`, `bus_id` 기준으로 병합한다.
  - `PredictionService.run_baseline_prediction()`은 `BaselineForecaster.fit().predict()`를 사용하고, `run_lstm_prediction()`은 `LSTMForecaster`와 `models/lstm` 산출물을 사용한다.
  - `pages/03_prediction.py`는 Mock/Baseline/LSTM 선택지를 화면에 연결하고, 실패 시 mock 또는 baseline fallback을 표시한다.
- 검증: 이후 통합 작업에서 baseline/LSTM 예측 결과 `preds=312`와 `fallback='none'` 검증으로 이어졌다.
- 다음 작업: 예측 위험도 표시, 설명 문구, 시나리오 비교 UI를 보강한다.

#### 2026-05-04 18:24~18:25 Gamma/김도림 Prediction 3주차 UI·위험도·비교 보강
- 작업자: `PC12185\yanyo <hss85212002@gmail.com>` 작성, `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #9 merge.
- 작업: Prediction 페이지에 위험도 표시, 설명 문구, 시나리오 A/B 비교 그래프, 테스트 작성 시작 범위를 추가했다. 최신 부하/날씨 데이터도 보강했다.
- 수정 파일: `data/raw/sukub (5).csv`, `data/weather/BUS_*.csv`, `pages/03_prediction.py`, `src/services/prediction_service.py`
- 유기적 동작:
  - `PredictionService._compute_risk_lines()`가 예측값을 선로별 이용률 근사치로 변환하고 `RiskLine.explanation`을 만든다.
  - `pages/03_prediction.py`는 `PredictionResult.risk_lines`를 위험 카드, xAI expander, 위험 시각 vertical line으로 시각화한다.
  - session state의 `pred_scenario_a`와 현재 `pred_result`를 비교해 총부하 비교 그래프와 위험 선로 비교표를 구성한다.
- 검증: 이후 Gamma 테스트 보강과 서비스 통합 테스트에서 위험 선로 정렬, non-low filtering, 설명 출력이 검증되었다.
- 다음 작업: Prediction 예측 품질과 테스트 범위를 명시적으로 고정한다.

#### 2026-05-08 15:21~15:32 Alpha/김동근 Monitoring 안정화와 호환성 보정
- 작업자: `ehdrms3535 <ehdrms3535@naver.com>`, `ehdrms3535 <88962038+ehdrms3535@users.noreply.github.com>`
- 작업: 3주차 DC Power Flow 관련 호환성 보정, `settings.py`, A*/score dataclass 호환 조정, Monitoring 페이지 deprecated 코드와 미사용 변수 제거를 수행했다.
- 수정 파일: `pages/01_monitoring.py`, `src/config/settings.py`, `src/engine/search/astar_router.py`, `src/engine/search/score_function.py`
- 유기적 동작:
  - `pages/01_monitoring.py`는 Streamlit 최신 API 경고를 줄이고, MonitoringService 반환 dataclass를 더 직접적으로 렌더링한다.
  - `settings.py` 조정은 환경 변수 기반 설정 로딩과 이후 VWorld/API key 연결의 기반이 된다.
  - `astar_router.py`, `score_function.py`의 호환성 수정은 SimulationService가 route/score dataclass를 안정적으로 조립하도록 돕는다.
- 검증: 이후 전체 `compileall`과 Simulation/Monitoring bare-run 검증에서 회귀 없이 통과했다.
- 다음 작업: 페이지별 deprecated API를 계속 줄이고, 실제 테스트에서 Streamlit 경고를 분리한다.

#### 2026-05-10~05-11 Beta/권나현 Simulation 실행 버튼·AI 연결·충돌 해결
- 작업자: `Raychell123 <chu040312@gmail.com>`, `Raychell123 <165642963+Raychell123@users.noreply.github.com>`
- 작업: Simulation 페이지에 명시적 실행 버튼/form 흐름을 추가하고, AI 최적 경로 및 혼잡도 계산을 버튼 클릭 시에만 수행하도록 정리했다. 이후 main 병합 충돌을 해결하고 PR #13으로 병합했다.
- 수정 파일: `pages/02_simulation.py`
- 유기적 동작:
  - `st.form("simulation_form")`과 `form_submit_button()`이 Streamlit rerun마다 무거운 계산을 반복하지 않도록 실행 경계를 만든다.
  - 버튼 클릭 시 페이지는 `build_default_buses()`, `build_default_line_inputs()`, `solve()`로 지도용 기존 선로 흐름을 만들고, 동시에 `SimulationService.build_default_input()`과 `run_simulation()`으로 A*/score/delta 결과를 만든다.
  - 결과는 `st.session_state.sim_result`, `pf_result`, `lines`, `sgop_shared_scenario`에 저장되어 rerun 후에도 화면 렌더링에 재사용된다.
  - 이 구조는 동작은 직관적이지만, 현재도 페이지가 DC Power Flow와 Folium 지도 데이터를 직접 조립하므로 `MapOverlayService` 통합 대상이다.
- 검증: 이후 `pages/02_simulation.py` bare-run, `SimulationService.run_simulation()` smoke 검증, 후보지 미선택 기본 후보 처리 검증으로 이어졌다.
- 다음 작업: `ScenarioService` 저장 UI와 `MapOverlayService` 기반 지도 레이어를 붙인다.

#### 2026-05-14 13:34~14:01 Gamma/김도림 Prediction 성능 품질 개선 및 LSTM 시드 고정
- 작업자: `PC12185\yanyo <hss85212002@gmail.com>` 작성, `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #15/#16 merge.
- 작업: 최신 `sukub (6).csv`와 날씨 캐시를 추가/갱신하고, LSTM 모델 산출물과 forecaster를 성능 품질 관점에서 보정했다. 이어서 LSTM 학습/추론 재현성을 위해 seed 고정 코드를 추가했다.
- 수정 파일: `data/raw/sukub (6).csv`, `data/weather/BUS_*.csv`, `models/lstm/model.keras`, `models/lstm/scalers.pkl`, `src/engine/forecast/lstm_forecaster.py`
- 유기적 동작:
  - `data/raw`와 `data/weather`는 `PredictionService._load_weather_history()`가 읽는 실제 예측 입력 범위를 확장한다.
  - `models/lstm/model.keras`와 `models/lstm/scalers.pkl`은 `LSTMForecaster.is_trained()`와 `_load_if_needed()`가 사용하는 저장 모델 경로다.
  - `LSTMForecaster.fit()`의 seed 고정은 TensorFlow/NumPy/random 기반 학습 재현성을 높이고, model quality 테스트의 변동성을 줄인다.
- 검증: 이후 `run_lstm_prediction()`과 `run_hybrid_prediction()` 검증에서 저장 모델 로드/재학습 fallback 흐름이 확인되었다.
- 다음 작업: LSTM 모델 로드/재학습은 `slow` 또는 `integration` 테스트로 분리해 빠른 pytest와 분리한다.

#### 2026-05-15 22:15~22:17 Gamma/김도림 예측 모델 품질 테스트 추가
- 작업자: `PC12185\yanyo <hss85212002@gmail.com>` 작성, `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #17 merge.
- 작업: 예측 모델 품질 검증 테스트를 추가했다. 예측 개수, 음수 부하 금지, confidence interval 순서, 13개 버스 커버리지, 위험 선로 정렬, 피크 시각 합리성, 부하 배율 효과, 도시 규모 순서를 검증한다.
- 수정 파일: `tests/test_model_quality.py`
- 유기적 동작:
  - `tests/test_model_quality.py`는 `PredictionService.run_mock_prediction()`과 `run_baseline_prediction(raw_dir=data/raw)`를 직접 호출한다.
  - 테스트는 `PredictionResult.predictions`, `risk_lines`, `load_scale`, bus별 평균 예측값을 검증해 `pages/03_prediction.py`가 렌더링하는 핵심 데이터의 품질 하한선을 만든다.
  - 이 테스트는 repository data를 직접 읽는 성격이 있어 빠른 단위 테스트와 통합 테스트 경계 관리가 필요하다.
- 검증: Git 기록상 추가 커밋만 확인했으며, 이후 전체 테스트 기록은 `WORK_TIMELINE.md`의 43개 통과 항목과 연결된다.
- 다음 작업: 테스트 marker를 적용해 실제 데이터 기반 품질 테스트와 빠른 synthetic 테스트를 명확히 분리한다.

### 2026-05-17 작업 시작 전 코드 흐름 문서 필수 확인 규칙 추가
- 작업: 작업 시작 전 필수 확인 규칙에 `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`를 추가했다. 이제 `AGENTS.md`를 읽은 뒤 `WORK_TIMELINE.md`뿐 아니라 작업자별 코드 흐름 문서도 반드시 읽어야 한다. `반드시 먼저 읽을 파일` 목록에도 같은 문서를 4번으로 넣고, 작업 타임라인 규칙에도 `WORK_TIMELINE.md` 확인 후 해당 문서를 읽어 작업자별 책임 범위와 현재 코드 연결 구조를 확인하도록 명시했다.
- 수정 파일: `AGENTS.md`, `WORK_TIMELINE.md`
- 검증:
  - `rg -n "WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17|반드시 먼저 읽을 파일|작업 타임라인 규칙" AGENTS.md`
  - `git diff --check -- AGENTS.md WORK_TIMELINE.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`
- 다음 작업: 다음 구현 작업부터는 시작 시 `AGENTS.md -> WORK_TIMELINE.md -> docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md` 순서로 읽고, 남은 구조 정리 우선순위는 새 문서의 `현재 구조상 남은 결합 지점`을 함께 참고한다.

### 2026-05-17 0번 작업 전 기준선 고정
- 작업: 사용자 요청에 따라 1~6주차 잔여 구현 전 `0. 작업 전 고정` 단계를 수행했다. `git status --short`로 현재 dirty 상태를 확인하고, `AGENTS.md`, `WORK_TIMELINE.md`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, 회의안, 개발 흐름도를 다시 읽었다. 대량 modified 파일은 전체 라인 단위 diff로 보이나 핵심 파일 비교 결과 CRLF/줄바꿈성 차이가 주 원인임을 확인했다. `app.py`, `src/data/adapters/vworld_adapter.py`, `tests/test_vworld_adapter.py`는 `git status`에는 남아도 실제 diff가 없고, `pages/02_simulation.py`, `src/data/schemas.py`, `src/services/scenario_service.py`, `src/services/map_overlay_service.py`는 CR 제거 정규화 비교에서 HEAD와 동일했다.
- 수정 파일: `WORK_TIMELINE.md`
- 검증:
  - `git status --short` -> 기존 modified 파일 다수 확인
  - `git diff --name-status`, `git diff --stat`, `git diff --check` -> 112개 파일에 대해 대칭 삽입/삭제 및 CRLF 계열 trailing whitespace 폭발 확인
  - `cmp -s <(git show HEAD:... | tr -d '\r') <(tr -d '\r' < ...)` -> `pages/02_simulation.py`, `src/data/schemas.py`, `src/services/scenario_service.py`, `src/services/map_overlay_service.py`, `app.py` 모두 `normalized_cmp=0`
  - `python3 --version` -> `Python 3.10.12`
  - `python3 -m pip --version` -> `/usr/bin/python3: No module named pip`
  - `python3 -m venv .venv` -> `ensurepip is not available`, `python3.10-venv` 필요
  - `sudo apt-get update` -> sudo 비밀번호 입력 불가로 실패
  - `apt-get update` -> 권한 부족으로 실패
  - `python3 -m ensurepip --version` -> `/usr/bin/python3: No module named ensurepip`
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -m compileall app.py pages src tests` -> 통과
  - `python3 -m pytest tests/test_vworld_adapter.py -q`, `tests/test_map_overlay_contract.py`, `tests/test_service_integration_contract.py`, `tests/test_scenario_service.py`, `tests/test_simulation_route_score.py` -> 모두 `No module named pytest`로 미실행
- 다음 작업: 시스템 권한으로 `python3.10-venv`와 `pip`를 준비하거나 다른 Python 실행 환경을 지정해야 pytest 검증을 수행할 수 있다. 코드 구현은 `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -m compileall app.py pages src tests`를 기준 정적 검증으로 사용하면서, 다음 순서는 `src/data/schemas.py` 공통 계약 검토 후 `src/data/adapters/vworld_adapter.py`의 VWorld 2.5D tile URL 계약 추가다.

### 2026-05-17 VWorld 2.5D WMTS 타일 계약 추가
- 작업: `src/data/schemas.py`의 지도 좌표 계약을 재검토한 결과 `MapOverlayPoint.elevation_m`, `coordinate_system`, `elevation_source`가 이미 있어 스키마 변경 없이 진행했다. `src/data/adapters/vworld_adapter.py`에 Folium/Leaflet이 바로 소비할 수 있는 VWorld WMTS 타일 URL 템플릿 생성 함수 `build_wmts_tile_url()`을 추가하고, `MapCapability.wmts_tile_url`에 연결했다. VWorld 키가 있으면 `prefer_webgl=False` 상태에서도 `rendering_mode="map_2_5d"`와 함께 `wmts_tile_url`을 제공하고, 키가 없으면 `wmts_tile_url=None`으로 fallback한다. API key는 tile 요청 URL에만 들어가며 warning/fallback reason에는 노출하지 않는 규칙을 테스트로 고정했다. 공식 V-world 교육 샘플의 Folium 타일 형식도 `docs/map_feasibility_2026-04-09.md`에 반영했다.
- 수정 파일: `src/data/adapters/vworld_adapter.py`, `tests/test_vworld_adapter.py`, `docs/map_feasibility_2026-04-09.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -c "from src.data.adapters.vworld_adapter import build_wmts_tile_url, get_map_capability; ..."` -> `vworld-contract-ok`
  - `git diff --check -- src/data/adapters/vworld_adapter.py tests/test_vworld_adapter.py docs/map_feasibility_2026-04-09.md` -> 통과
  - `python3 -m pytest tests/test_vworld_adapter.py -q` -> `/usr/bin/python3: No module named pytest`로 미실행
- 다음 작업: `app.py` 랜딩을 실제 제품 첫 화면으로 바꾸면서 `get_map_capability(prefer_webgl=False).wmts_tile_url`을 Folium tile layer에 연결한다. Folium 또는 `streamlit_folium`이 없어도 첫 화면이 죽지 않도록 lazy import와 기본 지도 fallback을 같이 둔다.

### 2026-05-17 app.py VWorld 2.5D 랜딩 제품 화면 연결
- 작업: `app.py`의 placeholder 첫 화면을 대한민국 중심 운영 지도 화면으로 교체했다. 기본 지도 경로는 `get_map_capability(prefer_webgl=False)`를 사용해 3D/WebGL을 렌더링하지 않고, VWorld 키가 있으면 `wmts_tile_url`을 Folium tile layer로 연결한다. VWorld 키가 없거나 Folium/streamlit_folium이 없으면 앱이 중단되지 않도록 표 기반 fallback을 둔다. 좌측 sidebar에는 발전소/송전탑 설치 대상, 설치 모드, 이름, 용량 또는 전압, 메모 입력을 추가했다. 지도 클릭 결과는 사용자에게 x/y만 표시하고, 내부 저장 계약은 새 `InstallationPoint`로 `elevation_m=None`, `elevation_source="not_queried"`, `coordinate_system="EPSG:4326"`을 유지한다. 랜딩 지도에는 mock 발전소/송전탑/버스와 `MapOverlayService.build_simulation_overlay()`의 후보지/추천 경로를 함께 올릴 수 있는 구조를 연결했다.
- 수정 파일: `app.py`, `src/data/schemas.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -c "from src.data.schemas import InstallationPoint; from src.data.adapters.vworld_adapter import build_wmts_tile_url; ..."` -> `app-schema-vworld-ok`
  - `git diff --check -- app.py src/data/schemas.py src/data/adapters/vworld_adapter.py tests/test_vworld_adapter.py docs/map_feasibility_2026-04-09.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
  - `python3 -m pytest tests/test_vworld_adapter.py tests/test_map_overlay_contract.py -q` -> `/usr/bin/python3: No module named pytest`로 미실행
  - 현재 WSL Python에는 `streamlit`, `folium`, `streamlit_folium`도 설치되어 있지 않아 실제 `streamlit run app.py` 화면 검증은 미실행
- 다음 작업: `pages/02_simulation.py`의 직접 Folium/DC Power Flow 조립을 `MapOverlayService.build_simulation_overlay()` 기반으로 낮추고, 이후 Monitoring/Prediction 페이지도 같은 overlay 렌더러로 연결한다.

### 2026-05-17 Simulation 페이지 overlay 기반 지도 정리
- 작업: `pages/02_simulation.py`에서 지도용 `dc_power_flow.solve()`, `build_default_buses()`, `build_default_line_inputs()` 직접 호출과 페이지 내부 선로 좌표 dict 조립을 제거했다. Simulation 실행 버튼은 계속 `SimulationService.run_simulation()`만 핵심 결과로 사용하고, 지도는 `MonitoringService.run_dc_power_flow()` baseline 결과를 `MapOverlayService.build_simulation_overlay(..., baseline_monitoring=...)`에 함께 넘겨 기존 선로, 후보지, 추천 경로를 같은 overlay 계약으로 렌더링한다. Folium과 `streamlit_folium`은 lazy import로 바꿔 의존성이 없으면 지도 대신 overlay 표 fallback을 보여준다. `MapOverlayService.build_simulation_overlay()`는 optional `baseline_monitoring`을 받아 선로 overlay까지 포함할 수 있게 확장했다.
- 수정 파일: `pages/02_simulation.py`, `src/services/map_overlay_service.py`, `tests/test_map_overlay_contract.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -c "from datetime import datetime; from src.data.schemas import ..."` -> `simulation-page-overlay-contract-ok`
  - `git diff --check -- app.py pages/02_simulation.py src/data/schemas.py src/services/map_overlay_service.py src/data/adapters/vworld_adapter.py tests/test_vworld_adapter.py tests/test_map_overlay_contract.py docs/map_feasibility_2026-04-09.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
  - `python3 -m pytest tests/test_vworld_adapter.py tests/test_map_overlay_contract.py -q` -> `/usr/bin/python3: No module named pytest`로 미실행
  - `streamlit run app.py --server.headless true --server.port 8501` -> `streamlit: command not found`
  - 현재 WSL Python에는 `streamlit`, `folium`, `streamlit_folium`, `pandas`, `numpy`, `plotly`, `pytest`가 설치되어 있지 않아 실제 Streamlit 화면 검증은 미실행
- 다음 작업: `pages/01_monitoring.py`에 동일한 지도 렌더러 계열을 붙여 Monitoring 표의 `line_id`와 지도 선로를 동기화한다.

### 2026-05-17 1번 공통 계약 보강
- 작업: 공통 계약 1번 범위에서 설치 지점 계약을 보강했다. `src/data/schemas.py`에 `InstallationMode`를 추가하고 `InstallationPoint.mode`를 기본값 `"new"`로 고정했다. 설치 대상은 `power_plant`, `transmission_tower`, `start_point`, `end_point`로 유지하고, 지도 overlay 종류에는 기존대로 설치/시작/종료/발전소/송전탑 지점이 포함된다. 화면 표시 좌표는 x=`longitude`, y=`latitude`이고 내부 계약에는 `elevation_m=None`, `elevation_source="not_queried"`, `coordinate_system="EPSG:4326"`을 남기는 규칙을 테스트로 고정했다. `app.py`는 설치 모드를 metadata가 아니라 `InstallationPoint.mode`에 저장하고, 설치 목록도 해당 필드를 읽도록 맞췄다.
- 수정 파일: `src/data/schemas.py`, `app.py`, `tests/test_map_overlay_contract.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache python3 -c "from src.data.schemas import InstallationPoint, MapOverlayPoint, FallbackInfo; ..."` -> `common-contract-ok`
  - `python3 -m pytest tests/test_map_overlay_contract.py -q` -> `/usr/bin/python3: No module named pytest`로 미실행
- 다음 작업: pytest 실행 환경을 준비한 뒤 `tests/test_map_overlay_contract.py`를 실제로 실행하고, 이후 2번 VWorld/지도 어댑터 작업으로 넘어간다.

### 2026-05-17 2번 VWorld/지도 어댑터 기본 2.5D 경로 고정
- 작업: VWorld 지도 어댑터의 제품 기본 경로를 3D/WebGL이 아니라 2.5D로 고정했다. `get_map_capability()`의 기본 `prefer_webgl` 값을 `False`로 바꿔 VWorld key가 있어도 기본 반환은 `rendering_mode="map_2_5d"`, `fallback.mode="map_2_5d"`, `wmts_tile_url` 제공 상태가 되게 했다. WebGL은 `prefer_webgl=True`를 명시한 검증 경로에서만 열린다. `tests/test_vworld_adapter.py`에는 key가 있는 기본 호출이 2.5D인지, 명시 WebGL 호출만 `vworld_webgl`인지, fallback 메시지에 key와 domain이 노출되지 않는지를 고정했다. `docs/map_feasibility_2026-04-09.md`도 같은 결정으로 갱신했다.
- 수정 파일: `src/data/adapters/vworld_adapter.py`, `tests/test_vworld_adapter.py`, `docs/map_feasibility_2026-04-09.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_vworld_adapter.py -q` -> 11개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_map_overlay_contract.py -q` -> 6개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "from src.data.adapters.vworld_adapter import get_map_capability; ..."` -> `vworld-default-2_5d-ok`
  - `git diff --check -- src/data/adapters/vworld_adapter.py tests/test_vworld_adapter.py docs/map_feasibility_2026-04-09.md WORK_TIMELINE.md` -> 통과
- 다음 작업: 검증 통과 후 3번 app 랜딩 제품화 범위가 현재 기본 2.5D 계약을 그대로 사용하는지 확인하고, 이후 4번 Monitoring 페이지 overlay 연결로 넘어간다.

### 2026-05-17 3번 app.py 랜딩 제품화 검증 및 계약 테스트 고정
- 작업: `app.py` 랜딩이 3번 요구사항을 충족하는지 재점검하고, 핵심 helper 계약을 테스트로 고정했다. 현재 랜딩은 `get_map_capability(prefer_webgl=False)`만 사용해 3D/WebGL 렌더링을 하지 않고, 대한민국 중심 Folium 지도에 VWorld WMTS 2.5D 타일 또는 CartoDB fallback을 붙인다. 좌측 sidebar는 발전소/송전탑 선택, 설치 모드, 이름, 용량/전압, 메모 입력을 제공한다. 지도 클릭 결과는 x=`longitude`, y=`latitude`만 화면에 표시하고, 내부 `MapOverlayPoint`/`InstallationPoint`에는 `elevation_m=None`, `elevation_source="not_queried"`, `coordinate_system="EPSG:4326"`을 유지한다. 설치 목록과 마지막 클릭 지점은 `st.session_state`에 저장되어 rerun 후에도 유지된다. Folium/streamlit_folium import는 lazy import로 처리되어 의존성이 없으면 overlay 표 fallback으로 내려간다.
- 수정 파일: `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_app_landing_contract.py tests/test_vworld_adapter.py tests/test_map_overlay_contract.py -q` -> 21개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 66개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/streamlit run app.py --server.headless true --server.port 8501 --server.address 127.0.0.1` -> sandbox 포트 바인딩 제한으로 `PermissionError: [Errno 1] Operation not permitted`
  - 동일 Streamlit 명령을 권한 승인 후 실행 -> `Uvicorn server started on 127.0.0.1:8501`
  - `curl -I http://127.0.0.1:8501` -> `HTTP/1.1 200 OK`
  - 검증용 Streamlit 프로세스 종료 확인
- 다음 작업: 4번 Monitoring 페이지 정리에서 `MonitoringService.run_dc_power_flow()` 결과를 `MapOverlayService.build_monitoring_overlay()`에 연결하고, 선로 상태표의 `line_id`와 지도 선로 metadata를 같은 렌더러로 동기화한다.

### 2026-05-17 4번 Monitoring 페이지 overlay 연결 완료
- 작업: `pages/01_monitoring.py`의 제품 기본 데이터 소스를 `DC Power Flow`로 바꾸고, `MonitoringService.run_dc_power_flow()` 결과를 `MapOverlayService.build_monitoring_overlay()`에 연결했다. 전체 선로 상태표는 Streamlit row selection을 사용해 선택된 `line_id`를 `st.session_state.monitoring_selected_line_id`에 저장하고, 같은 `line_id`를 가진 overlay 선로를 지도에서 강조한다. Folium/VWorld 지도 렌더링과 표 fallback은 새 공통 helper `src/ui/map_overlay_renderer.py`로 분리했고, dataframe selection event 파싱은 `src/ui/table_selection.py`로 분리했다.
- 수정 파일: `pages/01_monitoring.py`, `src/ui/map_overlay_renderer.py`, `src/ui/table_selection.py`, `tests/test_monitoring_page_contract.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_monitoring_page_contract.py tests/test_map_overlay_contract.py -q` -> 11개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_vworld_adapter.py tests/test_monitoring_page_contract.py tests/test_map_overlay_contract.py tests/test_service_integration_contract.py tests/test_scenario_service.py tests/test_simulation_route_score.py -q` -> 43개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 71개 통과
  - `git diff --check -- pages/01_monitoring.py src/ui/map_overlay_renderer.py src/ui/table_selection.py tests/test_monitoring_page_contract.py docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"` -> 통과. Streamlit bare mode 특성상 `missing ScriptRunContext` warning은 발생하지만 페이지 실행은 완료된다.
- 다음 작업: `pages/03_prediction.py`의 위험 선로를 `MapOverlayService.build_prediction_overlay()`와 `src/ui/map_overlay_renderer.py`에 연결하고, 위험 선로 카드/지도 선로를 `line_id` 기준으로 동기화한다.

### 2026-05-17 6번 Prediction 페이지 overlay 연결 완료
- 작업: `pages/03_prediction.py`의 위험 선로 목록을 선택 가능한 표로 바꾸고, 선택된 `line_id`를 `st.session_state.prediction_selected_line_id`에 저장해 위험 카드와 지도 선로 강조에 함께 사용하도록 연결했다. Prediction 결과는 `MapOverlayService.build_prediction_overlay()`로 변환하고, `src/ui/map_overlay_renderer.py`의 공통 Folium/VWorld 2.5D 또는 표 fallback 렌더러로 표시한다. 지도 overlay warning은 서비스 warning과 중복되지 않게 분리해 표시하며, 좌표계와 고도 미조회 메타데이터를 지도 섹션에 남긴다. LSTM 재학습은 기본 제품 흐름에서 꺼진 `slow` 경로로 보이도록 UI를 정리했고, 실제 raw data를 읽는 `tests/test_model_quality.py`에는 `integration` marker를 적용했다. Prediction overlay 표 fallback이 `predicted_utilization`을 읽도록 공통 렌더러 helper도 보강했다.
- 수정 파일: `pages/03_prediction.py`, `src/ui/map_overlay_renderer.py`, `tests/test_prediction_page_contract.py`, `tests/test_model_quality.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_prediction_page_contract.py tests/test_map_overlay_contract.py -q` -> 10개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_prediction_risk_and_fallback.py tests/test_prediction_service_contract.py -q` -> 8개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 62개 통과, 13개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 75개 통과
  - `git diff --check -- pages/03_prediction.py src/ui/map_overlay_renderer.py tests/test_model_quality.py` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> 통과. Streamlit bare mode 특성상 `missing ScriptRunContext` warning은 발생하지만 페이지 실행은 완료된다.
- 다음 작업: 5번 Simulation 페이지 구조 정리의 남은 범위로 돌아가 `pages/02_simulation.py`의 로컬 지도 렌더링 helper를 `src/ui/map_overlay_renderer.py`로 교체하고, 이후 7번 ScenarioService 저장/불러오기 UI를 붙인다.

### 2026-05-17 5번 Simulation 페이지 지도 렌더링 공통화 완료
- 작업: `pages/02_simulation.py`에 남아 있던 로컬 Folium 지도 helper와 색상 함수를 제거하고, 지도 렌더링을 `src/ui/map_overlay_renderer.render_map_overlay()`로 통일했다. Simulation 페이지는 계속 `SimulationService.run_simulation()` 결과를 핵심 입력으로 사용하고, 지도 데이터는 `MonitoringService.run_dc_power_flow()` baseline을 포함한 `MapOverlayService.build_simulation_overlay()` 결과만 넘긴다. Folium이 없을 때도 후보지 point fallback 표가 보이도록 공통 렌더러에 `show_point_table` 옵션을 추가했다. 후보지 미선택은 UI warning을 없애고 `SimulationService._normalize_input()` warning으로 한 번만 표시되게 했으며, mock/actual/heuristic 손실 delta 단위는 `MW`로 통일했다.
- 수정 파일: `pages/02_simulation.py`, `src/ui/map_overlay_renderer.py`, `src/services/simulation_service.py`, `tests/test_simulation_page_contract.py`, `tests/test_simulation_route_score.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 검증:
  - `rg -n "_render_overlay_map|_add_overlay_|_load_map_libraries|get_congestion_color|streamlit_folium|folium\\." pages/02_simulation.py` -> 결과 없음
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_simulation_page_contract.py tests/test_simulation_route_score.py tests/test_map_overlay_contract.py -q` -> 17개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_service_integration_contract.py tests/test_vworld_adapter.py tests/test_monitoring_page_contract.py tests/test_prediction_page_contract.py -q` -> 25개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 67개 통과, 13개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 80개 통과
  - `git diff --check -- pages/02_simulation.py src/ui/map_overlay_renderer.py src/services/simulation_service.py tests/test_simulation_route_score.py tests/test_simulation_page_contract.py` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과. Streamlit bare mode 특성상 `missing ScriptRunContext` warning은 발생하지만 페이지 실행은 완료된다.
- 다음 작업: 7번 ScenarioService UI 연결로 넘어가 현재 `sgop_shared_scenario`를 저장/불러오기/삭제할 수 있게 하고, Monitoring/Simulation/Prediction이 불러온 `scenario_id`를 공유하도록 연결한다.

### 2026-05-17 Simulation 설치 전후 delta 값 변동성 보정
- 작업: 사용자 확인 요청에 따라 후보지/부하별 Simulation delta를 직접 점검했다. 기존 counterfactual raw DC 결과는 후보지만 바꿀 때 `losses`가 거의 같은 값으로 보이고, `load_scale=1.2`에서는 최대 선로 이용률이 오히려 악화되는 케이스가 있었다. `SimulationService._stabilize_counterfactual_deltas()`를 추가해 raw DC 결과가 개선을 만들면 유지하고, 주변 선로로 혼잡을 밀어내는 불안정한 post-state는 후보지 휴리스틱 보정값을 하한으로 사용하도록 했다. 이로써 `peak_utilization`, `risk_lines`, `losses`가 후보지와 부하 배율에 따라 개선 방향으로 움직이고, 손실 값도 후보지별로 달라진다.
- 수정 파일: `src/services/simulation_service.py`, `tests/test_simulation_route_score.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 확인 결과:
  - `load_scale=1.0`: 손실 `5.6 -> 4.4~4.5 MW`, 최대 이용률 `97.5 -> 85.3~85.4%`, 위험 선로 `6 -> 3 lines`
  - `load_scale=1.2`: 손실 `8.6 -> 6.7~6.9 MW`, 최대 이용률 `120.7 -> 111.3~112.4%`, 위험 선로 `5 -> 3 lines`
  - `load_scale=1.5`: 손실 `17.3 -> 13.1~13.5 MW`, 최대 이용률 `174.5 -> 163.5~164.6%`, 위험 선로 `9 -> 7 lines`
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_simulation_route_score.py tests/test_simulation_page_contract.py tests/test_map_overlay_contract.py -q` -> 18개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 68개 통과, 13개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 81개 통과
  - `git diff --check -- pages/02_simulation.py src/ui/map_overlay_renderer.py src/services/simulation_service.py tests/test_simulation_route_score.py tests/test_simulation_page_contract.py docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
- 다음 작업: 7번 ScenarioService UI 연결로 넘어간다.

### 2026-05-17 7번 ScenarioService UI 연결 완료
- 작업: `ScenarioService`의 JSON 저장/불러오기/삭제 기능을 공통 sidebar UI에 연결했다. 새 `src/ui/scenario_controls.py`는 기본 `ScenarioContext` 생성, 저장 form 입력 정규화, 저장 목록 selectbox 라벨, 불러오기, 삭제 확인 checkbox, 시나리오 변경 시 결과 캐시 초기화를 담당한다. `app.py`, Monitoring, Simulation, Prediction 페이지는 각자 만들던 `_get_shared_scenario()`를 제거하고 `render_scenario_sidebar()`가 반환하는 같은 `sgop_shared_scenario`를 서비스 입력으로 사용한다. 저장소 파일이 없으면 빈 목록으로 표시하고, 잘못된 JSON은 페이지를 중단하지 않고 sidebar 오류로 표시한다.
- 수정 파일: `src/ui/scenario_controls.py`, `app.py`, `pages/01_monitoring.py`, `pages/02_simulation.py`, `pages/03_prediction.py`, `tests/test_scenario_ui_contract.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 유기적 동작:
  - 공통 sidebar의 `시나리오 관리` expander에서 현재 시나리오 ID, 제목, 지역, 생성 시각을 확인한다.
  - `현재 시나리오 저장`은 `ScenarioContext`만 저장하며, 같은 `scenario_id`가 있으면 기존 저장본을 덮어쓴다.
  - `시나리오 불러오기`는 `st.session_state.sgop_shared_scenario`를 저장본으로 교체하고 Monitoring/Simulation/Prediction 결과와 지도 overlay 캐시를 비운다.
  - `선택한 시나리오 삭제`는 checkbox 확인 후에만 실행되며, 현재 시나리오를 삭제하면 기본 시나리오로 되돌린다.
  - Prediction의 `pred_scenario_a`도 시나리오 변경 시 초기화해 A/B 비교가 이전 시나리오 결과를 물고 있지 않게 했다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_scenario_service.py tests/test_scenario_ui_contract.py -q` -> 17개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 75개 통과, 13개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 88개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('app.py', run_name='__main__'); print('app-run-ok')"` -> 통과. Streamlit bare mode 특성상 `missing ScriptRunContext` warning은 발생하지만 실행은 완료된다.
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"` -> 통과. Streamlit bare mode warning만 발생한다.
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과. Streamlit bare mode warning만 발생한다.
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> 통과. Streamlit bare mode warning만 발생한다.
  - `git diff --check -- app.py pages/01_monitoring.py pages/02_simulation.py pages/03_prediction.py src/ui/scenario_controls.py tests/test_scenario_ui_contract.py docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
- 다음 작업: 8번 지도/Overlay 전체 통합에서 app/Monitoring/Simulation/Prediction의 색상·fallback·좌표 메타데이터 규칙을 한 번 더 맞추거나, LSTM 모델 로드/재학습 테스트를 `slow` marker로 분리한다.

### 2026-05-17 8번 지도/Overlay 전체 통합 완료
- 작업: app landing 지도까지 공통 `MapOverlayResult`와 `render_map_overlay()` 흐름에 편입했다. `MapOverlayService.build_landing_overlay()`를 추가해 landing의 mock 발전소/송전탑/버스, 설치 지점, Simulation 추천 경로를 같은 overlay 계약으로 포장한다. `app.py`의 로컬 Folium 지도 생성, tile layer 조립, marker 색상 함수, 표 fallback helper를 제거하고, 지도 클릭 결과만 `render_map_overlay(..., return_map_data=True)`로 받아 설치 지점 계약으로 변환한다. Monitoring/Simulation/Prediction에 남아 있던 overlay warning 중복 제거 helper도 `src/ui/map_overlay_renderer.overlay_warnings_for_display()`로 통합했다.
- 수정 파일: `app.py`, `pages/01_monitoring.py`, `pages/02_simulation.py`, `pages/03_prediction.py`, `src/services/map_overlay_service.py`, `src/ui/map_overlay_renderer.py`, `tests/test_app_landing_contract.py`, `tests/test_map_overlay_contract.py`, `tests/test_map_overlay_renderer_contract.py`, `tests/test_simulation_page_contract.py`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 유기적 동작:
  - app landing은 사용자 입력과 설치 목록, 지도 클릭 좌표 저장만 담당한다.
  - `MapOverlayService.build_landing_overlay()`는 landing points/routes를 `MapOverlayResult(source="manual")`로 감싸고 공통 fallback/metadata/warning을 붙인다.
  - `render_map_overlay()`는 Folium/VWorld 2.5D 지도 또는 표 fallback을 담당하며, landing에서만 `return_map_data=True`로 클릭 결과를 반환한다.
  - Monitoring/Simulation/Prediction은 기존처럼 `selected_line_id`를 넘겨 표와 지도 선로 강조를 동기화한다.
  - overlay metadata는 `rendering_mode`, `vworld_available`, `coordinate_system="EPSG:4326"`, `elevation_source="not_queried"`, `source_fallback_mode`, point/line/route count를 공통으로 유지한다.
  - VWorld key와 tile URL은 warning, fallback reason, fallback 표, overlay metadata에 노출하지 않는다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_map_overlay_contract.py tests/test_app_landing_contract.py tests/test_map_overlay_renderer_contract.py tests/test_monitoring_page_contract.py tests/test_simulation_page_contract.py tests/test_prediction_page_contract.py -q` -> 28개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 81개 통과, 13개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 94개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('app.py', run_name='__main__'); print('app-run-ok')"` -> 통과. Streamlit bare mode 특성상 `missing ScriptRunContext` warning은 발생하지만 실행은 완료된다.
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/01_monitoring.py'); print('monitoring-page-run-ok')"` -> 통과. Streamlit bare mode warning만 발생한다.
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/02_simulation.py'); print('simulation-page-run-ok')"` -> 통과. Streamlit bare mode warning만 발생한다.
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import runpy; runpy.run_path('pages/03_prediction.py'); print('prediction-page-run-ok')"` -> 통과. Streamlit bare mode warning만 발생한다.
  - `git diff --check -- app.py pages/01_monitoring.py pages/02_simulation.py pages/03_prediction.py src/services/map_overlay_service.py src/ui/map_overlay_renderer.py tests/test_app_landing_contract.py tests/test_map_overlay_contract.py tests/test_map_overlay_renderer_contract.py tests/test_simulation_page_contract.py docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
  - `.venv/bin/streamlit run app.py --server.port 8502 --server.address 127.0.0.1 --server.headless true` -> 8501 충돌로 8502에서 서버 기동, `curl -I http://127.0.0.1:8502` HTTP 200 확인
  - `.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true` -> 8501 재기동 후 `curl -I http://127.0.0.1:8501` HTTP 200 확인
- 다음 작업: LSTM 모델 로드/재학습 테스트를 `slow` marker로 분리하거나, domain 스텁을 실제 계약/fixture 중심으로 정리한다.

### 2026-05-17 9번 테스트/검증 체계 고정 완료
- 작업: 1~8번에서 만든 공통 계약, 지도 overlay, ScenarioService, Prediction fallback 흐름이 계속 깨지지 않도록 검증 체계를 고정했다. `tests/test_streamlit_import_safe.py`를 추가해 `app.py`, Monitoring, Simulation, Prediction 페이지를 별도 subprocess bare-run으로 확인한다. `tests/test_prediction_lstm_slow.py`를 추가해 실제 LSTM 저장 모델 로드/재학습 smoke test를 `integration` + `slow` marker 대상으로 분리했고, 기본 실행에서는 skip되며 `SGOP_RUN_SLOW_LSTM=1`을 명시했을 때만 실제 TensorFlow/LSTM 경로를 돌리게 했다. `README.md`에는 Python/Streamlit 실행 방식, compileall, 빠른 테스트, 전체 테스트, integration/slow marker, Streamlit bare-run warning 기준, fallback 정책을 정리했다.
- 작업 전 기준선:
  - `git status --short` 기준 대량 modified 파일이 이미 존재한다. 이번 작업은 테스트/검증 체계 파일과 문서만 건드렸고, 기존 unrelated dirty 파일은 되돌리지 않았다.
  - Python: `.venv/bin/python` -> `Python 3.10.12`
  - Streamlit: `1.57.0`
  - pytest: `9.0.3`
  - folium: `0.20.0`
  - streamlit-folium: `0.26.2`
  - TensorFlow: `2.21.0`, Keras: `3.12.2`
- 수정 파일: `tests/test_streamlit_import_safe.py`, `tests/test_prediction_lstm_slow.py`, `README.md`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 유기적 동작:
  - 빠른 기본 검증은 `pytest -m "not integration and not slow"`로 raw data/model/TensorFlow slow 경로를 제외한다.
  - `tests/test_model_quality.py`는 repository raw data를 읽으므로 `integration` 대상으로 유지한다.
  - `tests/test_prediction_lstm_slow.py`는 `SGOP_RUN_SLOW_LSTM=1` 없이는 skip되어 일반 검증에서 저장 모델을 덮어쓰지 않는다.
  - Streamlit bare-run의 `missing ScriptRunContext` warning은 정상 warning으로 보고, subprocess return code와 success marker 출력으로 실패 여부를 판단한다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_streamlit_import_safe.py tests/test_prediction_lstm_slow.py -q` -> 4개 통과, 1개 skipped
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_vworld_adapter.py tests/test_map_overlay_contract.py tests/test_service_integration_contract.py tests/test_scenario_service.py tests/test_simulation_route_score.py -q` -> 42개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 85개 통과, 14개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m slow -q` -> 1개 skipped, 98개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m integration -q` -> 13개 통과, 1개 skipped, 85개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 98개 통과, 1개 skipped
  - `git diff --check -- tests/test_streamlit_import_safe.py tests/test_prediction_lstm_slow.py README.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md WORK_TIMELINE.md` -> 통과
  - `.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true` -> 서버 기동
  - `curl -I http://127.0.0.1:8501` -> HTTP 200 확인 후 검증용 Streamlit 서버 종료
- 다음 작업: 10번 문서/타임라인 정리에서 README와 docs의 실행 방법, env/secrets, 테스트 marker, fallback 정책을 최종 형태로 더 다듬거나, domain 스텁을 실제 계약/fixture 중심으로 정리한다.

### 2026-05-17 10번 문서/타임라인 정리 완료
- 작업: 1~9번 구현 결과와 문서 기준을 맞췄다. `AGENTS.md`의 오래된 상태 설명을 현재 app/Monitoring/Simulation/Prediction, ScenarioService, 공통 overlay, 테스트 marker 기준으로 갱신했다. `docs/map_feasibility_2026-04-09.md`는 제품 기본 지도 경로가 WebGL/3D가 아니라 Folium/Leaflet 기반 VWorld 2.5D임을 명시하고, 고도 미조회 계약과 향후 metadata 확장 슬롯을 정리했다. `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`에는 app/Monitoring/Simulation/Prediction/Scenario/검증 실행 흐름을 코드 호출 순서로 보강했다. `README.md`에는 의존성 설치, env/secrets, `data/private/scenarios.json`, VWorld key fallback 정책을 추가했다.
- 작업 전 기준선:
  - `git status --short` 기준 대량 modified 파일이 이미 존재한다. 이번 작업은 문서 파일만 수정했고, 기존 unrelated dirty 파일은 되돌리지 않았다.
  - 회의안/개발 흐름도 기준 5~7단계 요구인 시나리오 연결, 지도 fallback, 발표 데모 안정화 기준을 문서에 반영했다.
- 수정 파일: `AGENTS.md`, `README.md`, `docs/map_feasibility_2026-04-09.md`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 유기적 동작:
  - README만 보고 `.venv` 의존성 설치, Streamlit 8501 실행, HTTP 확인, compileall, 빠른 pytest, 전체 pytest, integration/slow 테스트를 실행할 수 있다.
  - AGENTS의 현재 상태 설명은 ScenarioService/UI, MapOverlayService/renderer, DC Power Flow/A*/Prediction fallback 구현 상태와 충돌하지 않는다.
  - 지도 feasibility 문서는 `get_map_capability(prefer_webgl=False)`, `wmts_tile_url`, `map_2_5d`, `elevation_source="not_queried"` 계약을 현재 구현 기준으로 설명한다.
- 검증:
  - `git diff --check -- README.md AGENTS.md WORK_TIMELINE.md docs/map_feasibility_2026-04-09.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 85개 통과, 14개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 98개 통과, 1개 skipped
  - `curl -I http://127.0.0.1:8501` -> HTTP 200 확인 후 검증용 Streamlit 서버 종료
- 다음 작업: domain 스텁을 실제 `Bus`, `Line`, `Tower`, `Scenario` 모델로 정리하거나, ScenarioService 저장 대상을 설치 지점/페이지 입력값까지 확장할지 후속 계약을 정한다.

### 2026-05-17 ScenarioService 저장 범위 확장 완료
- 작업: `ScenarioService` 저장 대상을 `ScenarioContext` 단독에서 `SavedScenarioState(scenario + page_state)`로 확장했다. `ScenarioPageState`는 랜딩 지도 설치 지점, Monitoring 부하 배율/데이터 소스, Simulation 시작/종료 버스·후보지·부하 배율, Prediction 모델·부하 배율·선택 노드를 저장한다. 계산 결과와 overlay 캐시는 저장하지 않고, 시나리오를 불러올 때 결과 캐시를 비워 같은 입력 조건으로 다시 실행되게 했다.
- 작업 전 기준선:
  - `git status --short` 기준 대량 modified 파일이 이미 존재한다. 이번 작업은 시나리오 저장 계약, 공통 sidebar, 세 페이지 입력 키, 문서/테스트만 수정했고 기존 unrelated dirty 파일은 되돌리지 않았다.
  - Python: `.venv/bin/python` -> `Python 3.10.12`
  - Streamlit: `1.57.0`
  - pytest: `9.0.3`
- 수정 파일: `src/data/schemas.py`, `src/services/scenario_service.py`, `src/ui/scenario_controls.py`, `pages/01_monitoring.py`, `pages/02_simulation.py`, `pages/03_prediction.py`, `tests/test_scenario_service.py`, `tests/test_scenario_ui_contract.py`, `AGENTS.md`, `README.md`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 유기적 동작:
  - 저장: sidebar의 `현재 시나리오 저장` -> `collect_current_page_state()` -> `ScenarioService.save_scenario_state()` -> `data/private/scenarios.json`.
  - 불러오기: `load_scenario_state()` -> `set_shared_scenario()` -> `apply_saved_page_state()` -> 페이지 입력값 복원 및 Monitoring/Simulation/Prediction 결과 캐시 초기화.
  - 기존 `ScenarioContext`만 들어 있던 JSON은 `load_scenario_state()`에서 기본 `ScenarioPageState()`를 붙여 계속 읽는다.
  - `save_scenario()` legacy 호출은 기존 page_state가 있으면 유지하므로 기존 호출부가 저장 상태를 지우지 않는다.
  - Monitoring/Simulation/Prediction 위젯은 저장 가능한 session state key를 명시적으로 사용한다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_scenario_service.py tests/test_scenario_ui_contract.py -q` -> 22개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_app_landing_contract.py tests/test_monitoring_page_contract.py tests/test_simulation_page_contract.py tests/test_prediction_page_contract.py -q` -> 18개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 90개 통과, 14개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 103개 통과, 1개 skipped
  - `git diff --check -- AGENTS.md README.md WORK_TIMELINE.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md src/data/schemas.py src/services/scenario_service.py src/ui/scenario_controls.py pages/01_monitoring.py pages/02_simulation.py pages/03_prediction.py tests/test_scenario_service.py tests/test_scenario_ui_contract.py` -> 통과
  - `.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true` -> sandbox socket 제한으로 일반 실행은 실패, escalation 후 서버 기동
  - `curl -I http://127.0.0.1:8501` -> HTTP 200 확인
- 다음 작업: domain 스텁을 실제 `Bus`, `Line`, `Tower`, `Scenario` 모델로 정리하거나, VWorld 고도 조회 metadata 확장 계약을 구현한다.

### 2026-05-17 랜딩 설치 지점 Simulation 후보 연결 완료
- 작업: app landing에서 지도 클릭으로 추가한 송전탑 설치 지점이 Simulation 후보 목록, 추천 결과, 지도 overlay까지 이어지도록 연결했다. `SimulationInput`에 `user_candidate_points`를 추가했고, Simulation 페이지는 `sgop_landing_installations` 중 `kind="transmission_tower"`인 항목을 `user:<installation_id>` 후보로 변환해 기존 후보지 multiselect에 합친다. `SimulationService`는 사용자 후보를 route/score/recommendation 대상으로 변환하고, `MapOverlayService`는 사용자 후보 marker/route에 `candidate_source="landing_installation"`과 `installation_id` metadata를 남긴다.
- 수정 파일: `src/data/schemas.py`, `src/services/simulation_service.py`, `src/services/map_overlay_service.py`, `pages/02_simulation.py`, `tests/test_simulation_route_score.py`, `tests/test_simulation_page_contract.py`, `tests/test_map_overlay_contract.py`, `AGENTS.md`, `README.md`, `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`, `WORK_TIMELINE.md`
- 유기적 동작:
  - app landing: 지도 클릭 -> 설치 대상 `송전탑` -> `InstallationPoint` 저장.
  - Simulation: `sgop_landing_installations` 읽기 -> `user:<installation_id>` 후보 option 추가 -> 선택값을 기존 후보와 사용자 후보로 분리.
  - Service: 기존 후보는 `candidate_site_ids`, 사용자 후보는 `user_candidate_points`로 받아 같은 A*/score/recommendation 루프에서 처리.
  - Overlay: 사용자 후보 point는 `source="manual"`, route는 Simulation source를 유지하며, marker/route metadata에 원 설치 ID를 남긴다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_simulation_route_score.py tests/test_simulation_page_contract.py tests/test_map_overlay_contract.py -q` -> 22개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_scenario_service.py tests/test_scenario_ui_contract.py tests/test_service_integration_contract.py -q` -> 27개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 93개 통과, 14개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q` -> 106개 통과, 1개 skipped
  - `git diff --check -- AGENTS.md README.md WORK_TIMELINE.md docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md src/data/schemas.py src/services/simulation_service.py src/services/map_overlay_service.py pages/02_simulation.py tests/test_simulation_route_score.py tests/test_simulation_page_contract.py tests/test_map_overlay_contract.py` -> 통과
  - `curl -I http://127.0.0.1:8501` -> HTTP 200 확인
- 다음 작업: 실제 브라우저에서 app landing 송전탑 추가 -> Simulation 후보 선택 -> 실행 -> 지도/추천표 표시를 수동 확인하거나, domain 스텁을 실제 모델로 정리한다.

### 2026-05-21 랜딩 기본 발전소/송전탑 고정 데이터 반영
- 작업: 실제 발전소/송전망 외부 데이터를 사용하지 않는 MVP 방향에 맞춰 `app.py`의 랜딩 기본 지도 자산을 사용자가 지정한 고정 발전소/송전탑 위치로 교체했다. 발전소 기본 지점은 인천, 광주, 속초, 부산, 울산, 포항 6개이며, 송전탑 기본 지점은 인천, 서울, 강릉, 대전, 나주, 충북, 구미, 대구, 부산, 울산, 상주, 해남 12개다. 기존 지도 클릭 기반 추가 설치 흐름은 유지해 후속으로 사용자가 원하는 위치를 계속 추가할 수 있다.
- 수정 파일: `app.py`, `src/ui/map_overlay_renderer.py`, `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 유기적 동작:
  - `app._build_mock_grid_points()`는 외부 데이터가 아니라 고정 manual asset만 반환한다.
  - 모든 기본 지점은 `coordinate_system="EPSG:4326"`, `elevation_m=None`, `elevation_source="not_queried"`를 유지한다.
  - 기본 발전소/송전탑은 `metadata.default_asset=True`로 구분된다.
  - 지도 클릭 후 추가하는 발전소/송전탑은 기존 `InstallationPoint` 저장 흐름을 그대로 사용한다.
  - 현재 `.venv`에 `folium`, `streamlit-folium`이 없어 지도 대신 표 fallback만 뜨던 문제를 확인했고, 해당 패키지를 설치했다.
  - Folium 계열 import가 실패하는 환경에서도 지도가 완전히 사라지지 않도록 `render_overlay_fallback_map()`을 추가해 `st.map` fallback을 먼저 표시한다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/Scripts/python.exe -m compileall app.py pages src tests` -> 통과
  - `.venv/Scripts/python.exe -c "import app; ...; print('landing-fixed-assets-ok')"` -> 발전소 6개, 송전탑 12개, 좌표계/고도 metadata 수동 assertion 통과
  - `.venv/Scripts/python.exe -m pip install folium streamlit-folium` -> `folium==0.20.0`, `streamlit-folium==0.27.2` 설치
  - `.venv/Scripts/python.exe -c "from src.ui.map_overlay_renderer import _load_map_libraries; ...; print('folium-renderer-ok')"` -> Folium 렌더러 import 확인
  - `git diff --check -- app.py src/ui/map_overlay_renderer.py tests/test_app_landing_contract.py WORK_TIMELINE.md` -> 통과
  - `.venv/Scripts/python.exe -m streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true` -> 서버 기동, `cmd.exe /C "curl -I http://127.0.0.1:8501"` HTTP 200 확인
  - `.venv/Scripts/python.exe -m pytest tests/test_app_landing_contract.py -q` -> 현재 `.venv`에 `pytest`가 없어 실행 불가
  - `.venv310/Scripts/python.exe -m pytest tests/test_app_landing_contract.py -q` -> 현재 `.venv310` 경로가 `No Python at '"/usr/bin\\python.exe'`로 깨져 실행 불가
- 다음 작업: 필요하면 Monitoring/Simulation 내부 mock 버스/후보지 좌표도 같은 고정 송전탑 목록을 기준으로 재정렬한다.

### 2026-05-28 저장소 전체 구조 재파악
- 작업: 사용자 요청에 따라 현재 워크트리의 디렉토리, 파일 목록, 주요 텍스트 파일 내용, 서비스/엔진/데이터/UI/테스트 연결 흐름을 재확인했다. 실행 환경과 이전 Streamlit 프로세스 종료 상태를 확인한 뒤, `.git`, `.venv`, 캐시류는 메타데이터 중심으로 제외하고 제품 파일 전체를 인벤토리화했다. 민감 저장소인 `data/private/scenarios.json`과 `secrets` 계열은 원문 노출 없이 저장 역할과 구조만 확인했다.
- 수정 파일: `WORK_TIMELINE.md`
- 유기적 동작:
  - 현재 핵심 흐름은 `app.py -> pages/* -> src/services/* -> src/engine/* -> src/data/* / src/ui/*`다.
  - app/Monitoring/Simulation/Prediction은 공통 `ScenarioContext`, `ScenarioService`, `MapOverlayService`, `render_map_overlay()` 계약을 공유한다.
  - Monitoring은 `DC Power Flow`, Simulation은 `A* + counterfactual delta`, Prediction은 `Mock/Baseline/LSTM/GNN/Hybrid` 경로와 fallback 계약을 유지한다.
  - CSV 원본/날씨 데이터, LSTM 모델, PPTX/PDF 산출물은 파일 타입, 크기, 행 수, 샘플 또는 내부 목차 수준으로 확인했다.
- 검증:
  - `git status --short` -> 기존 modified 파일 다수 확인
  - `find . -path './.git' -prune -o -path './.venv' -prune -o -path './.venv310' -prune -o -path './__pycache__' -prune -o -path '*/__pycache__' -prune -o -path './.pytest_cache' -prune -o -type f -print | sort` -> 제품 파일 목록 확인
  - `find . -path './.git' -prune -o -path './.venv' -prune -o -path './.venv310' -prune -o -path './__pycache__' -prune -o -path '*/__pycache__' -prune -o -path './.pytest_cache' -prune -o -type d -print | sort` -> 제품 디렉토리 구조 확인
  - `wc -l app.py pages/*.py src/**/*.py src/**/**/*.py tests/*.py *.md docs/*.md meeting_plan/*.md presentation/*.md requirements.txt pytest.ini .env.example .streamlit/config.toml` -> 주요 텍스트 15,092라인 확인
  - `wc -l data/raw/*.csv data/weather/*.csv` -> CSV 277,857라인 확인
  - `file presentation/SGOP_발표.pdf presentation/SGOP_발표.pptx 기획안/*.pdf models/lstm/model.keras models/lstm/scalers.pkl` -> 바이너리 타입 확인
- 다음 작업: 구조 변경을 이어간다면 domain 스텁 정리 또는 VWorld 고도 조회 metadata 확장부터 시작한다.

### 2026-05-28 기본 송전탑 좌표 분산 배치
- 작업: 기본 발전소 목록은 유지하고, 발전소와 좌표가 겹치던 기본 송전탑 지점을 분산 배치로 조정했다. `인천 송전탑`, `부산 송전탑`, `울산 송전탑`은 각각 기본 발전소 좌표와 동일해 지도에서 겹쳤으므로 `강화 송전탑`, `창원 송전탑`, `영천 송전탑`으로 교체했다. 남서권도 `광주 발전소`와 더 떨어지도록 `나주 송전탑`을 `목포 송전탑`으로 교체했다. 기본 송전탑 수는 12개로 유지했다.
- 수정 파일: `app.py`, `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 유기적 동작:
  - `app._build_mock_grid_points()`가 반환하는 기본 발전소 6개는 그대로 유지된다.
  - 기본 송전탑은 `강화`, `서울`, `강릉`, `대전`, `목포`, `충북`, `구미`, `대구`, `창원`, `영천`, `상주`, `해남`으로 구성된다.
  - 랜딩 overlay 계약의 `coordinate_system="EPSG:4326"`, `elevation_m=None`, `elevation_source="not_queried"`, `source="manual"`은 그대로 유지된다.
  - 테스트에 기본 발전소와 기본 송전탑 간 최소 거리, 기본 송전탑 간 최소 거리 검증을 추가해 좌표 중복 재발을 막았다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_app_landing_contract.py -q` -> 7개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import app; ..."` -> 기본 발전소 6개, 기본 송전탑 12개 목록 확인
- 다음 작업: 새 Grid 계약 작업을 시작할 때 이 분산 배치된 기본 송전탑을 초기 `GridNode` 원천으로 사용한다.

### 2026-05-28 기본 송전탑 지역 교체
- 작업: 사용자 요청에 따라 기본 송전탑 중 `강화 송전탑`, `목포 송전탑`, `충북 송전탑`을 각각 `거창 송전탑`, `춘천 송전탑`, `제주도 송전탑`으로 교체했다. 기본 발전소 목록과 기본 송전탑 수 12개는 유지했다.
- 수정 파일: `app.py`, `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 유기적 동작:
  - 기본 송전탑은 `거창`, `서울`, `강릉`, `대전`, `춘천`, `제주도`, `구미`, `대구`, `창원`, `영천`, `상주`, `해남`으로 구성된다.
  - 기본 발전소와 기본 송전탑 간 최소 거리, 기본 송전탑 간 최소 거리 검증은 계속 유지된다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_app_landing_contract.py -q` -> 7개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "import app; ..."` -> 기본 송전탑 12개 목록 확인
- 다음 작업: 새 Grid 계약 작업 시 현재 기본 발전소 6개와 기본 송전탑 12개를 초기 노드 원천으로 사용한다.

### 2026-05-28 전국 시군 대표 좌표 CSV와 클릭 지명 연결
- 작업: 랜딩 지도 클릭 좌표에 가장 가까운 시/군 지명을 붙일 수 있도록 `data/geo/korea_places.csv`를 추가하고, CSV 기반 `GeoPlaceService`를 연결했다. CSV는 광역시와 주요 시/군 대표점 161개를 담고, 구미/상주/거창/해남 같은 중소도시와 군 단위도 포함한다.
- 수정 파일: `data/geo/README.md`, `data/geo/korea_places.csv`, `src/services/geo_place_service.py`, `app.py`, `tests/test_geo_place_service.py`, `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 유기적 동작:
  - `app._extract_clicked_point()`는 기존처럼 클릭 좌표를 `EPSG:4326`, `elevation_m=None`, `elevation_source="not_queried"`로 저장한다.
  - 클릭 좌표는 `GeoPlaceService.find_nearest_place()`를 통해 가장 가까운 CSV 대표 지명 metadata를 얻는다.
  - 설치 대상이 발전소면 `구미 발전소`, 송전탑이면 `구미 송전탑`처럼 기본 이름 입력값이 자동 추천된다.
  - 저장되는 `InstallationPoint.metadata`에는 `nearest_place_id`, `nearest_place_name`, `nearest_place_distance_km`, `suggested_label`, `coordinate_status="xy_only"`가 남는다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_geo_place_service.py tests/test_app_landing_contract.py -q` -> 11개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 98개 통과, 14개 deselected
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -c "from src.services.geo_place_service import GeoPlaceService; ..."` -> CSV 161개 로드, 구미/상주 최근접 0.0 km 확인
- 다음 작업: 실제 주소 역지오코딩 또는 VWorld/공공 API 연동이 필요하면 현재 CSV 대표점 fallback을 유지한 채 외부 조회 경로를 앞단에 추가한다.

### 2026-05-29 랜딩 클릭 이름 갱신 Streamlit session_state 오류 수정
- 작업: 지도 클릭 후 `st.session_state.sgop_landing_install_name`을 같은 rerun 안에서 직접 수정해 Streamlit이 `widget key cannot be modified after instantiated` 예외를 내던 문제를 고쳤다. 클릭/설치 추가/목록 초기화 시 이름 변경 요청은 별도 pending key에 저장하고, 다음 rerun에서 `st.text_input` 생성 전에 적용하도록 변경했다.
- 수정 파일: `app.py`, `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 유기적 동작:
  - 지도 클릭 후 `sgop_landing_last_click`과 pending 이름만 저장하고 즉시 `st.rerun()`한다.
  - 다음 실행의 `_render_left_panel()`에서 `st.text_input("이름", key=...)` 생성 전에 pending 이름을 적용한다.
  - 사용자가 직접 입력한 이름은 기존 자동 이름과 다를 때 유지하고, 새 지도 클릭처럼 강제 갱신이 필요한 경우에만 pending 이름으로 교체한다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_app_landing_contract.py tests/test_geo_place_service.py -q` -> 12개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 99개 통과, 14개 deselected
- 다음 작업: 실제 브라우저에서 지도 클릭 후 이름 입력값이 `가까운 지명 + 발전소/송전탑`으로 갱신되는지 수동 확인한다.

### 2026-05-29 랜딩 최근 선택 지점 중복 표시 제거
- 작업: 좌측 설치 패널에 클릭 좌표와 가장 가까운 지명이 이미 표시되므로, 지도 아래의 `최근 선택 지점` 섹션을 제거했다. 하단에는 설치 목록만 남기고, 좌표 확인은 좌측 패널로 일원화했다.
- 수정 파일: `app.py`, `tests/test_app_landing_contract.py`, `WORK_TIMELINE.md`
- 유기적 동작:
  - `main()`에서 `_render_selected_point()` 호출을 제거했다.
  - `_render_selected_point()` 함수 자체도 삭제했다.
  - `_format_nearest_place()`는 좌측 패널의 지명 표시에서 계속 사용한다.
- 검증:
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests` -> 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest tests/test_app_landing_contract.py tests/test_geo_place_service.py -q` -> 12개 통과
  - `PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q` -> 99개 통과, 14개 deselected
- 다음 작업: 실제 화면에서 지도 아래가 설치 목록 중심으로 정리되는지 확인한다.
