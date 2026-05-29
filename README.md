# SGOP - Smart Grid Optimization Platform

SGOP는 한국 송전망 혼잡을 지도 위에서 설명하고, 가상의 송전 시나리오와 AI 예측 결과를 비교해 보는 Streamlit 기반 의사결정 지원형 시뮬레이터다.

이 프로젝트는 실제 계통 운영·인허가·설비 투자 결정을 직접 대체하는 산업용 정밀 해석 도구가 아니다. 공공 전력 수요 데이터를 SGOP simulated grid에 재구성한 뒤, DC Power Flow, A* 탐색, LSTM/Neural GNN 예측, xAI 설명을 연결해 비전문가 교육, 정책 브리핑, 발표 데모, 컨설팅 초기 설명처럼 라이브로 이해를 돕는 상황에 맞춘 프로젝트다.

## 핵심 포지션

- 목적: 송전망 혼잡, 병목 선로, 예측 부하, 우회·신설 후보의 영향을 한 화면에서 설명한다.
- 대상: 전력계통 비전문가, 정책 담당자, 발표 청중, 교육·시연 사용자.
- 사용 방식: 지도 클릭, 부하 배율 조정, 예측 모델 선택, 시나리오 생성으로 결과 변화를 즉시 확인한다.
- 주장 범위: 실제 기관 송전망 원장 데이터가 아니라 공공 수요 데이터와 synthetic grid 기반 시뮬레이션 결과다.
- 금지 범위: 실제 송전탑 입지, 실제 선로 위험도, 실제 운영 지시, 투자 의사결정의 최종 근거로 사용하지 않는다.

## 현재 구현 상태

첫 화면인 `app.py`가 실질적인 통합 운영 콘솔이다. Streamlit multipage 파일도 유지하지만, 현재 데모 중심 흐름은 landing 운영 지도에서 Monitoring, Prediction, Stress 분석, 개선안, 시나리오 관리를 한 번에 연결한다.

주요 기능:

- 대한민국 중심 2.5D/Folium 지도와 VWorld WMTS tile fallback 계약
- 발전소, 송전탑, 선로, 위험 선로, 추천 경로, 신규 설치 지점 overlay
- 지도 클릭 기반 발전소/송전탑 가상 설치
- 지도 클릭 기반 송전 시작/종료 노드 선택과 다중 송전 시나리오 생성
- 전체 부하 배율 조정과 DC Power Flow 기반 선로 이용률 계산
- Prediction 모델 비교: Mock, Baseline, LSTM, GNN, Neural GNN(beta), Hybrid
- Baseline 대비 선택 모델의 선로 이용률 변화 브리핑
- 병목 선로 xAI 설명과 우회 경로·신규 송전탑 개선안 제안
- 시나리오 저장/불러오기/삭제
- 외부 API, 대용량 processed 파일, 모델 로드 실패 시 fallback 유지

## 실행 흐름

```text
app.py
  -> src/ui/scenario_controls.py
  -> src/data/loaders.py
  -> src/services/monitoring_service.py
  -> src/services/prediction_service.py
  -> src/engine/stress/route_stress_analyzer.py
  -> src/engine/recommend/grid_improvement_recommender.py
  -> src/services/map_overlay_service.py
  -> src/ui/map_overlay_renderer.py
```

legacy multipage 흐름도 유지된다.

```text
pages/01_monitoring.py   -> MonitoringService -> DC Power Flow / congestion metrics
pages/02_simulation.py   -> SimulationService -> A* route / score / counterfactual delta
pages/03_prediction.py   -> PredictionService -> Baseline / LSTM / GNN / Hybrid
pages/04_optimization.py -> ESS/Optimization 확장 자리, 현재 stub 수준
```

## 저장소 구조

```text
.
├── app.py                         # 통합 운영 콘솔 진입점
├── pages/                         # Streamlit multipage 화면
├── src/
│   ├── config/                    # 환경 변수와 경로 설정
│   ├── data/                      # 스키마, CSV 로더, 전처리, 외부 어댑터
│   ├── domain/                    # Bus/Line/Tower/Scenario 도메인 확장 자리
│   ├── engine/                    # 계산 엔진
│   │   ├── powerflow/             # DC Power Flow, congestion metrics
│   │   ├── search/                # A* 경로 탐색, 추천 점수
│   │   ├── forecast/              # Baseline, LSTM, GNN, Neural GNN, 평가 지표
│   │   ├── stress/                # 송전 시나리오별 선로 stress 분석
│   │   ├── recommend/             # 우회 경로와 신규 노드 개선안
│   │   ├── explain/               # xAI 설명 생성
│   │   └── optimize/              # ESS/최적화 후속 확장 자리
│   ├── services/                  # UI와 엔진을 연결하는 유스케이스 계층
│   ├── ui/                        # 지도 렌더러, 시나리오 UI, 테이블 선택
│   └── utils/                     # 공통 유틸리티
├── data/
│   ├── grid/enhanced/             # 기본 실행 Grid CSV, synthetic enhanced dataset
│   ├── grid/mock/                 # fallback mock grid
│   ├── processed/                 # 전처리·학습·평가 산출물
│   ├── raw/                       # KPX 공개 수급 CSV 원본
│   ├── weather/                   # BUS legacy 날씨 캐시
│   ├── geo/                       # 시군 대표 좌표와 클릭 지명 추천 데이터
│   ├── private/                   # 로컬 시나리오 저장소, git 제외
│   └── mock/                      # 초기 mock 데이터 자리
├── models/
│   ├── lstm/                      # Keras LSTM 모델, scaler, 평가 요약
│   ├── gnn/                       # PyTorch Neural GNN beta 모델, 평가 요약
│   └── heuristic/                 # heuristic 모델 확장 자리
├── scripts/                       # processed 생성, LSTM/GNN 학습, 모델 평가 스크립트
├── tests/                         # 계약·서비스·엔진·UI 회귀 테스트
├── docs/                          # 데이터 보정, Grid 스키마, 코드 흐름, 지도 판단 문서
├── meeting_plan/                  # 2026-03-30 회의안
├── presentation/                  # 발표 PDF/PPTX, 대본, 예상 질문
├── secrets/                       # 비밀정보 템플릿, 실제 키는 git 제외
├── 기획안/                        # 초기 기획안 PDF
└── WORK_TIMELINE.md               # 작업 기록과 검증 로그
```

로컬 개발용 `.venv/`, `.venv-tf/`, `.idea/`, `__pycache__/`, `.pytest_cache/`는 실행 환경 또는 캐시이며 제품 코드 구조의 핵심은 아니다.

## 데이터 기준과 한계

기본 실행 데이터는 `data/grid/enhanced/`다.

- 발전소: 12개
- 송전탑/부하 노드: 24개
- GridLine: 44개
- 후보지: `tower_candidates.csv`

이 값들은 실제 기관 원장 데이터를 복제한 것이 아니라, 공공 수요 데이터와 발표용 송전망 구조를 연결하기 위한 현실성 강화 synthetic dataset이다.

현재 데이터 변환 흐름:

```text
data/raw/sukub*.csv
  -> data/processed/national_load_hourly.csv
  -> data/processed/grid_node_weights.csv
  -> data/processed/grid_node_load_history.csv
  -> Baseline / LSTM / GNN / Neural GNN
  -> data/processed/grid_line_flow_history.csv
  -> 모델별 선로 이용률 proxy 평가
```

말할 수 있는 표현:

- 공공 전력 수요 데이터를 시간 단위로 정리했다.
- 공공 수요를 SGOP simulated grid의 노드 단위로 재분배했다.
- DC Power Flow로 입력 가정하의 선로별 조류와 이용률을 계산했다.
- LSTM/GNN 계열 모델은 같은 processed GridNode holdout 구간에서 상대 비교했다.

피해야 하는 표현:

- 실제 한국 송전망 원장 데이터를 그대로 사용했다.
- 실제 선로별 실시간 조류나 실제 송전탑별 실측 부하를 학습했다.
- 특정 실제 선로가 현실에서도 위험하다고 단정할 수 있다.
- 이 결과만으로 실제 운영·인허가·투자 결정을 할 수 있다.

자세한 기준은 `docs/DATA_CALIBRATION_METHOD.md`를 따른다.

## 대용량 CSV 데이터

GitHub 용량 제한 때문에 아래 2개 processed CSV는 저장소에 커밋하지 않는다.
필요하면 공유 드라이브에서 내려받아 같은 경로에 배치한다.

- 공유 드라이브: [SGOP 대용량 CSV 다운로드](https://drive.google.com/drive/folders/1TKxnsYvLy5WuF4A-5xA0Uj2z9QOxoyKj?usp=sharing)
- `data/processed/grid_node_load_history.csv`
- `data/processed/grid_line_flow_history.csv`

두 파일은 `.gitignore`에 등록되어 있다. 파일이 없거나 현재 GridDataset과 맞지 않으면 Prediction은 기존 KPX raw 재분배 또는 fallback 경로를 사용한다.

## 모델과 평가 지표

현재 저장 모델:

- `models/lstm/model.keras`: processed GridNode 송전탑 부하 이력으로 학습한 Keras LSTM
- `models/lstm/scalers.pkl`: LSTM 정규화 scaler와 학습 node 목록
- `models/gnn/model.pt`: GridLine adjacency를 반영한 PyTorch Neural GNN beta
- `models/gnn/metadata.json`: Neural GNN 구성과 평가 metadata

현재 `data/processed/model_evaluation_summary.csv` 기준 holdout 평가:

| 모델 | MAE(MW) | RMSE(MW) | MAPE(%) | 선로 이용률 MAE(pp) |
|---|---:|---:|---:|---:|
| Baseline | 35.61 | 53.90 | 14.36 | 2.27 |
| LSTM | 18.57 | 29.86 | 7.18 | 1.19 |
| Neural GNN | 15.93 | 25.81 | 5.99 | 1.00 |
| LSTM+Neural GNN | 16.36 | 26.84 | 6.32 | 1.04 |

이 지표는 실제 운영 성능 인증값이 아니라, 같은 simulated grid processed history에서 모델 간 상대 비교를 위한 재현 가능한 평가 요약이다.

## 실행 환경

검증 기준 Python은 3.10 계열이다. WSL/Linux 기준 명령:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
```

Windows `cmd` 기준 예시:

```cmd
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\streamlit.exe run app.py --server.port 8501 --server.address 127.0.0.1
```

브라우저:

```text
http://127.0.0.1:8501
```

HTTP 응답 확인:

```bash
curl -I http://127.0.0.1:8501
```

정상 기준은 `HTTP/1.1 200 OK`다.

## 환경 변수와 secrets

- `.env`: 로컬 개발용 환경 변수 파일, git 제외
- `secrets/`: 배포 또는 로컬 비밀정보 템플릿 위치, 실제 키는 git 제외
- `data/private/`: 로컬 시나리오 저장소, git 제외
- `VWORLD_API_KEY`: VWorld WMTS/WebGL API key
- `PUBLIC_DATA_API_KEY`: 공공데이터 연동 확장용 key
- `OPENAI_API_KEY`: 설명·브리핑 확장용 key

VWorld key가 없어도 앱은 Folium 기본 tile 또는 표 fallback으로 계속 동작해야 한다.

## 주요 명령

정적 컴파일 검증:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m compileall app.py pages src tests
```

빠른 기본 테스트:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m "not integration and not slow" -q
```

전체 테스트:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -q
```

repository data 또는 저장 모델을 읽는 테스트:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m integration -q
```

TensorFlow/LSTM 모델 로드 또는 재학습 smoke 테스트:

```bash
SGOP_RUN_SLOW_LSTM=1 PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m slow -q
```

processed 데이터 기반 모델 평가:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python scripts/evaluate_prediction_models_from_processed.py --eval-step-h 24
```

LSTM 재학습:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python scripts/train_lstm_from_processed.py --epochs 5 --batch-size 512 --eval-step-h 24
```

Neural GNN 재학습:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python scripts/train_neural_gnn_from_processed.py --epochs 5 --batch-size 512 --eval-step-h 24
```

## Fallback 정책

SGOP는 발표와 라이브 데모 중단을 막기 위해 fallback을 명시적으로 남긴다.

- `mock_data`: 실제 데이터, 엔진, 모델, 외부 연동이 없거나 실패할 때
- `baseline_model`: 고급 예측 모델 실패 시 baseline 예측 사용
- `cached_result`: 재계산이 불가능할 때 직전 유효 결과 사용
- `manual_override`: 운영자가 수동 조정해야 할 때
- `map_2_5d`: 3D/WebGL 지도 또는 VWorld 연동이 불안정할 때

서비스 결과는 `warnings`와 `fallback`에 어떤 경로가 사용됐는지 남긴다.

## 개발 원칙

이 저장소의 작업 흐름은 다음 순서를 따른다.

```text
계약 정의 -> mock -> 최소 구현 -> 실제 연결 -> 안정화
```

중요한 원칙:

- 페이지와 서비스 사이의 입출력은 `src/data/schemas.py` dataclass를 우선 사용한다.
- 페이지별 ad hoc dict 계약을 늘리지 않는다.
- `ScenarioContext`는 Monitoring, Simulation, Prediction이 공유한다.
- Streamlit rerun으로 인해 시나리오 ID, 지도 선택, 계산 결과가 불필요하게 초기화되지 않도록 한다.
- 외부 API, 실제 데이터, 저장 모델이 없어도 demo가 끊기지 않아야 한다.
- 새 작업을 마치면 `WORK_TIMELINE.md`에 작업 요약, 수정 파일, 검증, 다음 작업을 남긴다.

## 주요 문서

- `AGENTS.md`: 현재 저장소 작업 규칙과 최신 상태
- `WORK_TIMELINE.md`: 날짜별 작업 기록과 검증 내역
- `docs/WORK_OWNERSHIP_AND_CODE_FLOW_2026-05-17.md`: 작업자별 코드 흐름
- `docs/DATA_CALIBRATION_METHOD.md`: 데이터 객관성, 한계, 발표 표기 기준
- `docs/GRID_CSV_SCHEMA_2026-05-29.md`: Grid CSV 계약
- `docs/GRID_MIGRATION_BASELINE_2026-05-29.md`: legacy ID 제거와 GridDataset 기준선
- `docs/map_feasibility_2026-04-09.md`: VWorld/2.5D 지도 fallback 판단
- `meeting_plan/MEETING_PLAN_2026-03-30.md`: MVP 범위와 역할 배정
- `DEVELOPMENT_FLOW_2026-03-30.md`: 개발 단계와 운영 원칙
- `presentation/`: 발표 자료, 대본, 예상 질문

## 라이브 데모 시 권장 설명

SGOP는 정밀 계통 운영 시스템이 아니라, 송전망 병목 문제를 정책·교육·기획 단계에서 빠르게 설명하기 위한 시각적 시뮬레이터다. 실제 데이터 접근 제한이 있는 상황에서도 공공 수요 데이터와 simulated grid를 이용해 “부하가 증가하면 어떤 선로가 병목처럼 보이는지”, “예측 모델 선택에 따라 위험 선로 판단이 어떻게 달라지는지”, “우회 경로 또는 신규 송전탑 후보가 어떤 방식으로 제안되는지”를 라이브로 보여줄 수 있다.

따라서 발표에서는 “실제 운영 판단”보다 “데이터 기반 의사결정 흐름의 프로토타입”, “비전문가가 이해 가능한 송전망 브리핑 도구”, “정책 검토 전 단계의 탐색형 데모”로 설명하는 것이 맞다.
