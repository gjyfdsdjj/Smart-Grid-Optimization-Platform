# SGOP 작업자별 코드 흐름 정리

## 목적
- 이 문서는 `2026-05-17` 기준 Git 기록과 현재 코드 구조를 맞춰, 작업자별 산출물이 어떤 파일을 만들거나 바꿨고 그 파일들이 앱 안에서 어떻게 연결되는지 정리한다.
- 기준 명령은 `git log --all --date=iso-strict`, `git show --name-status`, `git show -m --name-status`다.
- 사용자가 언급한 `hss86212002@gmail.com`은 Git 기록에 없고, 실제 기록은 `hss85212002@gmail.com`이다.

## 전체 실행 구조
```text
app.py
  -> VWorldAdapter.get_map_capability(prefer_webgl=False)
  -> VWorld WMTS tile URL / Folium 2.5D fallback
  -> InstallationPoint / MapOverlayPoint
  -> MapOverlayService.build_simulation_overlay()
  -> 사용자가 선택한 x/y 설치 지점 session_state 저장
  -> pages/01_monitoring.py
       -> MonitoringService
       -> dc_power_flow / congestion_metrics
       -> MonitoringResult / LineStatus / CongestionSummary
  -> pages/02_simulation.py
       -> SimulationService
       -> MonitoringService baseline
       -> astar_router / score_function
       -> counterfactual dc_power_flow
       -> SimulationResult / RecommendationResult / SimulationDelta
       -> MapOverlayService.build_simulation_overlay()
       -> VWorld/Folium 2.5D 지도 또는 표 fallback
  -> pages/03_prediction.py
       -> PredictionService
       -> public_data_adapter / weather_adapter
       -> feature_builder
       -> baseline_forecaster / lstm_forecaster / gnn_forecaster
       -> PredictionResult / HourlyLoadPrediction / RiskLine
       -> MapOverlayService.build_prediction_overlay()
       -> VWorld/Folium 2.5D 지도 또는 표 fallback
```

## 공통 계약 계층
- `src/data/schemas.py`는 페이지와 서비스 사이의 기준 계약이다.
- Monitoring은 `MonitoringResult`, `MonitoringKpi`, `LineStatus`, `CongestionSummary`를 사용한다.
- Simulation은 `SimulationInput`, `SimulationResult`, `RouteResult`, `ScoreBreakdown`, `RecommendationResult`, `SimulationDelta`를 사용한다.
- Prediction은 `ForecastFeatureVector`, `HourlyLoadPrediction`, `RiskLine`, `PredictionResult`를 사용한다.
- 지도 동기화용으로 `MapOverlayPoint`, `MapOverlayLine`, `MapOverlayRoute`, `MapOverlayResult`가 추가되어 있다.
- 랜딩 설치 지점 저장용으로 `InstallationPoint`가 추가되었고, 설치 대상(`kind`)과 설치 모드(`mode`)를 계약 필드로 유지한다. 화면에는 x/y만 표시하되 내부 계약에는 `elevation_m=None`, `elevation_source="not_queried"`, `coordinate_system="EPSG:4326"`을 유지한다.
- 현재 `app.py` 랜딩과 `pages/02_simulation.py`는 `MapOverlayService.build_simulation_overlay()` 결과를 Folium/VWorld 2.5D 지도 또는 표 fallback으로 표시한다.
- `pages/01_monitoring.py`는 `MapOverlayService.build_monitoring_overlay()`를, `pages/03_prediction.py`는 `MapOverlayService.build_prediction_overlay()`를 같은 렌더러로 표시한다.

## 작업자 식별
| 역할 | Git author 기준 | 담당 축 |
|---|---|---|
| 박차오름 / waterspouut | `chaoreum0525@gmail.com`, `waterspouut@users.noreply.github.com` | 공통 계약, 서비스 통합, A*/score, fallback, overlay, scenario |
| 김도림 / Gamma | `hss85212002@gmail.com`, PR merge `gjyfdsdjj@users.noreply.github.com` | Prediction, KPX/날씨 데이터, baseline/LSTM/GNN, 예측 UI, 품질 테스트 |
| 권나현 / Beta | `Raychell123`, `chu040312@gmail.com` | Simulation 페이지, 지도 UI, 실행 버튼, 추천 결과 렌더링 |
| 김동근 / Alpha | `ehdrms3535`, `ehdrms3535@naver.com` | Monitoring 페이지, DC Power Flow, congestion metrics, 안정화 |

## 2026-04-02 Gamma Prediction 1주차
작업 기록:
- 작성: `PC12185\yanyo <hss85212002@gmail.com>`
- 병합: `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #1
- 커밋: `prediction 1주차 산출물`

변경 파일:
- `pages/03_prediction.py`
- `src/services/prediction_service.py`
- `src/engine/forecast/feature_builder.py`
- `src/data/schemas.py`
- `.gitignore`

동작 구조:
- `pages/03_prediction.py`가 Streamlit 예측 화면을 담당한다.
- 페이지는 모델/부하 배율/표시 노드 입력을 받은 뒤 `PredictionService`를 호출한다.
- `PredictionService.run_mock_prediction()`은 13개 버스 × 24시간 예측값을 합성한다.
- 서비스 결과는 `PredictionResult`로 반환되고, 페이지는 `predictions`를 그래프, `risk_lines`를 위험 카드/설명 카드로 렌더링한다.
- `feature_builder.py`는 이 시점에 실제 모델보다 먼저 피처 계약을 세우는 역할을 한다. 이후 baseline, LSTM, GNN 모두 이 계약을 재사용한다.

연결 포인트:
- `PredictionService`가 `schemas.py`의 dataclass를 직접 반환하므로 페이지가 ad hoc dict를 만들지 않는다.
- 이후 `MapOverlayService.build_prediction_overlay()`는 `PredictionResult.risk_lines`를 지도용 `MapOverlayLine(kind="risk_line")`으로 변환한다.

## 2026-04-05 Alpha Monitoring 1주차
작업 기록:
- 작성: `ehdrms3535 <ehdrms3535@naver.com>`
- 병합: `ehdrms3535 <88962038+ehdrms3535@users.noreply.github.com>` PR #3
- 커밋: `monitoring 1주차`

변경 파일:
- `pages/01_monitoring.py`
- `src/services/monitoring_service.py`
- `src/data/schemas.py`

동작 구조:
- `pages/01_monitoring.py`는 부하 배율과 데이터 소스 입력을 받고 Monitoring 결과를 렌더링한다.
- `MonitoringService.run_mock_monitoring()`은 mock 선로 정의에서 `LineStatus` 목록을 만든다.
- `_build_congestion_summary()`는 선로 상태를 집계해 `CongestionSummary`를 만든다.
- `_build_kpis()`는 `current_load`, `peak_utilization`, `danger_lines`, `operating_margin` KPI를 만든다.
- 페이지는 `MonitoringResult.kpis`, `trend_points`, `line_statuses`, `congestion_summary`만 읽어 차트와 표를 렌더링한다.

연결 포인트:
- `MonitoringResult`는 Simulation의 설치 전 baseline과 지도 overlay의 원천 데이터가 된다.
- `MapOverlayService.build_monitoring_overlay()`는 `LineStatus.line_id`, `from_bus`, `to_bus`, `utilization`, `risk_level`을 지도 선로 데이터로 바꾼다.

## 2026-04-06 Beta Simulation UI와 지도 뼈대
작업 기록:
- 작성: `Raychell123 <chu040312@gmail.com>`
- 커밋: `simulation/#1 UI뼈대 구현 및 실제 지도 연동`

변경 파일:
- `pages/02_simulation.py`

동작 구조:
- Simulation 페이지는 Streamlit sidebar에서 시작 버스, 종료 버스, 후보지, 부하 배율을 받는다.
- Folium 지도는 페이지 안의 좌표 딕셔너리와 선로 데이터를 사용해 직접 생성된다.
- 이후 `SimulationService`가 붙으면서 페이지는 서비스 결과의 `selected_route`, `recommendations`, `deltas`를 렌더링하게 되었다.

연결 포인트:
- 현재도 페이지가 `src.engine.powerflow.dc_power_flow.solve()`를 직접 호출해 지도 색상용 `pf_result`를 만든다.
- 서비스 계층 관점에서는 이 직접 호출을 `MapOverlayService` 또는 MonitoringService 기반 결과로 낮추는 것이 후속 정리 대상이다.

## 2026-04-08 Alpha DC Power Flow 실제 계산 연결
작업 기록:
- 작성: `ehdrms3535 <ehdrms3535@naver.com>`
- 중복/merge 기록: `ehdrms3535 <88962038+ehdrms3535@users.noreply.github.com>`
- 커밋: `monitoring 2주차: DC Power Flow 엔진 구현 및 모니터링 연결`

변경 파일:
- `src/engine/powerflow/dc_power_flow.py`
- `src/engine/powerflow/congestion_metrics.py`
- `src/services/monitoring_service.py`
- `pages/01_monitoring.py`
- `docs/dev_log.md`

동작 구조:
- `dc_power_flow.py`는 `BusInput`, `LineInput`, `DCFlowResult`와 `solve()`를 제공한다.
- `solve()`는 B 행렬을 만들고, 슬랙 버스 행/열을 제거한 뒤 `numpy.linalg.solve()`로 전압각을 구한다.
- 선로 조류는 `(theta_i - theta_j) / x_ij * BASE_MVA`로 계산된다.
- `congestion_metrics.py`는 `DCFlowResult.line_flows`와 `line_inputs`를 합쳐 `LineStatus`로 변환한다.
- `MonitoringService.run_dc_power_flow()`는 이 엔진을 호출하고, 실패하면 `run_mock_monitoring()`으로 fallback한다.
- `pages/01_monitoring.py`는 radio 선택에 따라 mock 또는 DC Power Flow 결과를 표시한다.

연결 포인트:
- SimulationService는 설치 전 baseline을 만들 때 `MonitoringService.run_dc_power_flow()`를 호출한다.
- Simulation counterfactual은 같은 `dc_power_flow.solve()`를 한 번 더 돌려 설치 후 상태를 계산한다.
- 따라서 Monitoring 엔진은 Monitoring 화면만이 아니라 Simulation 추천 점수와 delta 계산의 기반이다.

## 2026-04-10 Beta A* 경로 지도와 비교 지표 연결
작업 기록:
- 작성: `Raychell123 <chu040312@gmail.com>`
- 커밋: `simulation/#1 A* 최적 경로 시각화, 지도 범례 및 전/후 비교 지표 연동`

변경 파일:
- `pages/02_simulation.py`

동작 구조:
- `SimulationResult.selected_route.waypoints`를 Folium `PolyLine`으로 그린다.
- 각 waypoint는 Folium `CircleMarker`로 표시된다.
- 기존 선로는 페이지 내부 `bus_coords`와 `pf_result.line_flows`를 사용해 색을 정한다.
- `SimulationResult.deltas`는 오른쪽 패널의 설치 전/후 `st.metric`으로 표시된다.

연결 포인트:
- 지도에 보이는 추천 경로는 `src/engine/search/astar_router.py`가 만든 `RouteResult`와 직접 연결된다.
- 추천 사유와 점수는 `SimulationService`가 만든 `RecommendationResult.score`와 `rationale`을 사용한다.
- 후속 `MapOverlayService.build_simulation_overlay()`는 이 Folium 직접 렌더링을 대체할 수 있는 공통 데이터 계약이다.

## 2026-04-13 Gamma 실제 데이터 기반 Prediction 경로
작업 기록:
- 작성: `PC12185\yanyo <hss85212002@gmail.com>`
- 병합: `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #7
- 커밋: `김도림 2주차 산출물`

변경 파일:
- `data/raw/sukub*.csv`
- `data/weather/BUS_*.csv`
- `models/lstm/model.keras`
- `models/lstm/scalers.pkl`
- `src/data/adapters/public_data_adapter.py`
- `src/data/adapters/weather_adapter.py`
- `src/engine/forecast/baseline_forecaster.py`
- `src/engine/forecast/lstm_forecaster.py`
- `src/services/prediction_service.py`
- `pages/03_prediction.py`
- `requirements.txt`

동작 구조:
- `public_data_adapter.load_kpx_csvs(raw_dir)`는 `sukub*.csv`를 읽고 5분 데이터를 1시간 평균으로 리샘플한다.
- 전국 수요는 `_BUS_RATIO`에 따라 13개 버스별 `load_mw`로 분배된다.
- `weather_adapter.fetch_historical()`는 각 `BUS_*` 위치의 시간별 기온을 가져오고 `data/weather` 캐시를 사용한다.
- `public_data_adapter.load_kpx_with_weather()`는 부하와 기온을 병합한다.
- `BaselineForecaster.fit()`은 bus/hour별 평균과 표준편차를 저장하고, `predict()`는 feature timestamp 순서에 맞춰 예측을 만든다.
- `LSTMForecaster.fit()`은 `models/lstm/model.keras`, `models/lstm/scalers.pkl`를 저장하고, `predict()`는 저장 모델을 로드해 24시간 예측을 만든다.
- `PredictionService.run_baseline_prediction()`과 `run_lstm_prediction()`이 이 흐름을 감싼다.

연결 포인트:
- `PredictionService._build_target_features()`는 `feature_builder.build_prediction_feature_matrix()`를 호출한다.
- baseline/LSTM/GNN이 같은 `ForecastFeatureVector` 순서를 공유하기 때문에 hybrid 조합에서 `(timestamp, bus_id)` 키가 맞아야 한다.
- `pages/03_prediction.py`는 모델 선택 라디오로 Mock/Baseline/LSTM/GNN/LSTM+GNN 실행 경로를 바꾼다.

## 2026-05-04 Gamma Prediction 위험도·설명·시나리오 비교
작업 기록:
- 작성: `PC12185\yanyo <hss85212002@gmail.com>`
- 병합: `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #9
- 커밋: `prediction 3주차`

변경 파일:
- `data/raw/sukub (5).csv`
- `data/weather/BUS_*.csv`
- `pages/03_prediction.py`
- `src/services/prediction_service.py`

동작 구조:
- `PredictionService._compute_risk_lines()`는 예측 부하 차이를 기반으로 선로별 이용률을 근사한다.
- 위험도는 `critical`, `high`, `medium`, `low`로 분류하고 low는 결과에서 제외한다.
- `_build_explanation()`은 시간대, 부하 배율, 조치 권고를 포함한 설명 문장을 만든다.
- 페이지는 위험 선로를 카드와 expander로 렌더링한다.
- session state의 `pred_scenario_a`와 현재 결과를 비교해 A/B 총부하 그래프와 위험 선로 비교표를 만든다.

연결 포인트:
- `PredictionResult.risk_lines`는 UI 설명뿐 아니라 `MapOverlayService.build_prediction_overlay()`의 지도 위험 선로 입력이다.
- `PredictionResult.summary`와 `warnings`는 서비스 fallback 또는 정상 source 안내를 화면에 노출하는 공통 채널이다.

## 2026-05-08 Alpha 안정화와 호환성 보정
작업 기록:
- 작성: `ehdrms3535 <ehdrms3535@naver.com>`, `ehdrms3535 <88962038+ehdrms3535@users.noreply.github.com>`
- 커밋: `3주차 DC Power Flow 엔진 구현 및 slots 호환 수정`, `안정화 - deprecated 코드 및 미사용 변수 제거`

변경 파일:
- `pages/01_monitoring.py`
- `src/config/settings.py`
- `src/engine/search/astar_router.py`
- `src/engine/search/score_function.py`

동작 구조:
- Monitoring 페이지의 deprecated Streamlit 사용과 미사용 변수를 정리했다.
- `settings.py` 변경은 환경 설정 로딩의 호환성을 보정한다.
- A*/score dataclass 관련 호환 수정은 SimulationService가 route/score 결과를 안정적으로 소비하도록 한다.

연결 포인트:
- 작은 호환성 보정이지만 Monitoring 페이지, Simulation A* route, score calculation이 공통 schemas와 맞물리는 부분을 건드렸으므로 통합 테스트가 중요하다.
- 이후 `tests/test_service_integration_contract.py`가 이 계층 간 계약을 고정한다.

## 2026-05-10~05-11 Beta Simulation 실행 버튼과 AI 연결
작업 기록:
- 작성: `Raychell123 <chu040312@gmail.com>`
- 병합: `Raychell123 <165642963+Raychell123@users.noreply.github.com>` PR #13
- 커밋: `simulation/#1 실행 버튼 추가 인공지능 연결`, `충돌 해결`

변경 파일:
- `pages/02_simulation.py`

동작 구조:
- `st.form("simulation_form")`으로 입력 변경과 실행을 분리했다.
- `submitted`가 true일 때만 DC Power Flow와 SimulationService 계산을 실행한다.
- 계산 결과는 `st.session_state.pf_result`, `sim_result`, `lines`, `selected_candidates`, `sgop_shared_scenario`에 저장된다.
- 화면 렌더링은 session state 결과가 있을 때만 수행된다.

연결 포인트:
- `SimulationService.build_default_input()`은 shared `ScenarioContext`를 받아 `SimulationInput`을 만든다.
- `SimulationService.run_simulation()`은 A*/score/counterfactual delta를 계산한다.
- 페이지는 결과를 지도, delta metric, 추천 사유, 점수 세부표, 후보지별 추천 표로 렌더링한다.
- 직접 DC/Folium 조립과 서비스 결과 렌더링이 섞여 있으므로, 다음 구조 개선은 `MapOverlayService` 연결이다.

## 2026-05-14 Gamma LSTM 성능 품질과 시드 고정
작업 기록:
- 작성: `PC12185\yanyo <hss85212002@gmail.com>`
- 병합: `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #15/#16
- 커밋: `성능 품질 개선`, `lstm 시드 고정`

변경 파일:
- `data/raw/sukub (6).csv`
- `data/weather/BUS_*.csv`
- `models/lstm/model.keras`
- `models/lstm/scalers.pkl`
- `src/engine/forecast/lstm_forecaster.py`

동작 구조:
- 추가 raw/weather 데이터는 baseline/LSTM/GNN 학습/예측 입력 범위를 넓힌다.
- 저장 LSTM 모델과 scaler는 `LSTMForecaster.is_trained()`가 감지하는 기본 모델이다.
- `fit()` 내부에서 Python random, NumPy, TensorFlow seed를 고정해 재학습 결과의 흔들림을 줄인다.

연결 포인트:
- `PredictionService.run_lstm_prediction()`은 저장 모델 로드가 실패하면 재학습 후 예측하는 복구 경로를 갖고 있다.
- hybrid는 LSTM과 GNN 둘 다 성공하면 가중 평균을 쓰고, 하나라도 실패하면 baseline fallback으로 내려간다.

## 2026-05-15 Gamma 예측 모델 품질 테스트
작업 기록:
- 작성: `PC12185\yanyo <hss85212002@gmail.com>`
- 병합: `gimdorim <165128099+gjyfdsdjj@users.noreply.github.com>` PR #17
- 커밋: `test: 예측 모델 품질 검증 테스트 케이스 추가`

변경 파일:
- `tests/test_model_quality.py`

동작 구조:
- `mock_result` fixture는 `PredictionService.run_mock_prediction()`을 호출한다.
- `baseline_result` fixture는 `PredictionService.run_baseline_prediction(raw_dir=data/raw)`을 호출한다.
- 테스트는 예측 개수, 음수 부하 금지, confidence interval 순서, bus coverage, 위험 선로 정렬, 피크 시각, 부하 배율 효과, 도시 규모 순서를 검증한다.

연결 포인트:
- Prediction 페이지가 신뢰하는 `PredictionResult.predictions`와 `risk_lines`의 최소 품질을 테스트가 고정한다.
- 실제 repository data를 읽으므로 `integration` marker 적용 여부를 검토해야 한다.

## 2026-05-17 랜딩·Simulation 지도 연결 보강
- `app.py`는 VWorld 2.5D WMTS tile URL을 사용해 대한민국 중심 운영 지도를 표시한다.
- 사용자가 지도에서 선택한 지점은 `InstallationPoint`로 저장되며, 화면에는 x/y만 표시하고 내부에는 고도 미조회 상태를 남긴다.
- `pages/01_monitoring.py`는 `MonitoringService.run_dc_power_flow()`를 제품 기본 데이터 소스로 사용하고, 결과를 `MapOverlayService.build_monitoring_overlay()`에 연결해 선로 지도와 상태표를 같은 `line_id` 기준으로 동기화한다.
- `pages/02_simulation.py`는 더 이상 페이지 안에서 `dc_power_flow.solve()`와 선로 좌표 dict를 직접 조립하지 않고, `MonitoringService.run_dc_power_flow()` 결과를 `MapOverlayService.build_simulation_overlay(..., baseline_monitoring=...)`에 넘겨 기존 선로/후보지/추천 경로를 같은 overlay 계약으로 렌더링한다.
- `pages/02_simulation.py`의 로컬 Folium helper는 제거되었고, 지도 표시는 `src/ui/map_overlay_renderer.render_map_overlay()`가 맡는다. Folium이 없을 때도 후보지 point 표를 함께 보여주도록 `show_point_table=True`를 사용한다.
- `SimulationService.build_default_input(candidate_site_ids=[])`는 사용자의 빈 후보 선택을 보존한 뒤 `_normalize_input()`에서 기본 후보와 service warning으로 처리한다.
- `SimulationService`의 mock/actual/heuristic 손실 delta 단위는 모두 `MW`로 통일한다.
- `SimulationService`의 counterfactual delta는 raw DC Power Flow 결과가 주변 선로로 혼잡을 밀어내는 경우 후보지 휴리스틱 보정값을 하한으로 사용해 `peak_utilization`, `risk_lines`, `losses`가 후보지/부하 변화에 따라 안정적으로 움직이게 한다.
- `pages/03_prediction.py`는 `PredictionService` 결과의 위험 선로를 `MapOverlayService.build_prediction_overlay()`로 변환하고, 위험 선로 표에서 선택한 `line_id`를 카드와 지도 선로 강조에 함께 사용한다.
- `src/ui/map_overlay_renderer.py`는 `MapOverlayResult`를 Folium/VWorld 2.5D 지도 또는 표 fallback으로 렌더링하는 공통 UI helper다. 현재 Monitoring/Simulation/Prediction 페이지가 함께 사용한다.
- Folium 또는 `streamlit_folium`이 없으면 지도 대신 overlay 표를 표시한다.
- `tests/test_model_quality.py`는 `integration` marker가 적용되어 빠른 테스트 명령에서는 제외할 수 있다.

## 2026-05-17 ScenarioService UI 연결
- `src/services/scenario_service.py`는 `data/private/scenarios.json`에 `ScenarioContext`를 저장, 조회, 목록화, 삭제한다. 저장소 파일이 없으면 빈 목록으로 처리하고, 잘못된 JSON은 `ValueError`로 UI에 전달된다.
- `src/ui/scenario_controls.py`는 공통 sidebar의 `시나리오 관리` expander를 담당한다. 기본 시나리오 생성, 저장 입력 정규화, 저장 목록 라벨, 불러오기, 삭제 확인, 시나리오 변경 시 결과 캐시 초기화를 한 곳에 모았다.
- `app.py`, `pages/01_monitoring.py`, `pages/02_simulation.py`, `pages/03_prediction.py`는 더 이상 각자 `_get_shared_scenario()`를 만들지 않고 `render_scenario_sidebar()`에서 받은 `ScenarioContext`를 사용한다.
- 시나리오를 불러오거나 현재 시나리오를 삭제하면 Monitoring 결과/overlay, Simulation 결과/overlay, Prediction 결과/overlay, Prediction A/B 비교 캐시가 초기화된다. 따라서 새 `scenario_id`에서 이전 결과가 계속 표시되지 않는다.
- 같은 `scenario_id`로 저장하면 `ScenarioService.save_scenario()`가 기존 저장본을 덮어쓴다. 삭제는 checkbox 확인 후에만 실행된다.
- 저장된 시나리오를 불러온 뒤 Monitoring/Simulation/Prediction은 같은 `sgop_shared_scenario.scenario_id`를 서비스 입력으로 사용한다.

## 2026-05-17 지도/Overlay 전체 통합
- `src/services/map_overlay_service.py`는 app landing, Monitoring, Simulation, Prediction 결과를 모두 `MapOverlayResult`로 포장한다. landing 전용 `build_landing_overlay()`도 추가되어 app이 더 이상 지도 렌더링용 별도 구조를 만들지 않는다.
- `src/ui/map_overlay_renderer.py`는 네 화면의 공통 지도 렌더러다. VWorld WMTS tile, CartoDB fallback tile, 선로, 추천 경로, 발전소/송전탑/버스/후보지 marker, 표 fallback을 같은 색상/상태 규칙으로 처리한다.
- app landing은 `render_map_overlay(..., return_map_data=True)`로 지도 클릭 결과만 돌려받고, 클릭 좌표를 `MapOverlayPoint(kind="install_point")`와 `InstallationPoint`로 변환하는 책임만 가진다.
- Monitoring/Simulation/Prediction은 `render_map_overlay()` 반환값을 쓰지 않고 overlay 표시만 맡긴다. 선로 선택 동기화는 각 페이지의 표 selection 결과와 `selected_line_id` 인자로 유지된다.
- 페이지별 warning 중복 제거는 `overlay_warnings_for_display()` 공통 helper로 모았다. 서비스 warning은 페이지 상단, overlay/map warning은 지도 섹션 expander에서 다룬다.
- app에 있던 로컬 Folium helper, tile layer 조립, marker 색상 함수는 제거되었다. Folium 또는 `streamlit_folium`이 없으면 공통 renderer가 표 fallback을 표시한다.
- overlay metadata는 `rendering_mode`, `vworld_available`, `coordinate_system="EPSG:4326"`, `elevation_source="not_queried"`, `source_fallback_mode`, point/line/route count를 공통으로 남긴다.
- VWorld API key와 tile URL은 warning, fallback reason, fallback 표, overlay metadata에 노출하지 않는다.

## 2026-05-17 테스트/검증 체계 고정
- `pytest.ini`의 `integration`, `slow` marker를 검증 구분 기준으로 사용한다.
- 빠른 기본 검증은 `pytest -m "not integration and not slow"`로 수행해 repository raw data, 저장 모델, TensorFlow/LSTM 경로를 제외한다.
- `tests/test_model_quality.py`는 repository `data/raw`를 읽는 예측 품질 테스트이므로 `integration` 대상으로 유지한다.
- `tests/test_prediction_lstm_slow.py`는 실제 LSTM 저장 모델 로드 또는 재학습 smoke test이며 `integration`과 `slow`를 동시에 가진다. 기본 실행에서는 skip되고, `SGOP_RUN_SLOW_LSTM=1`을 명시했을 때만 실제 LSTM 경로를 돌린다.
- `tests/test_streamlit_import_safe.py`는 `app.py`, Monitoring, Simulation, Prediction 페이지를 별도 Python subprocess에서 bare-run해 import-safe 상태를 고정한다.
- Streamlit bare-run의 `missing ScriptRunContext` warning은 정상 warning으로 보고, subprocess return code와 success marker 출력으로 실패 여부를 판단한다.

## 현재 남은 구조적 갭
- `app.py`, Monitoring, Simulation, Prediction은 모두 공통 overlay 렌더러를 사용하지만, 실제 지도 클릭과 브라우저 렌더링은 Streamlit 런타임에서 추가 수동 검증이 필요하다.
- `MapOverlayService`는 app/Monitoring/Simulation/Prediction overlay 계약을 만들지만, 실제 VWorld 호출 품질과 고도 조회는 아직 붙어 있지 않다.
- `src/domain`, `src/utils`, `src/engine/explain`, `src/engine/optimize`, `src/engine/recommend`는 대부분 한 줄 스텁이다.
- LSTM 모델 로드/재학습 검증은 `slow` marker로 분리되었지만, 실제 실행은 `SGOP_RUN_SLOW_LSTM=1`을 명시해야 한다.

## 다음 구현 권장 순서
1. domain 스텁을 실제 `Bus`, `Line`, `Tower`, `Scenario` 모델로 정리하되, 먼저 `schemas.py`와 중복되는 책임 경계를 정한다.
2. ScenarioService가 현재는 `ScenarioContext`만 저장하므로, 설치 지점과 페이지 입력값까지 시나리오 저장 대상에 포함할지 후속 계약을 정한다.
3. 실제 VWorld 고도 조회를 붙이기 전 elevation_source, 조회 시각, fallback 여부를 service metadata로 확장한다.
