# SGOP 데이터 보정 및 학습 데이터 기준

## 목적

이 문서는 SGOP가 사용하는 데이터의 객관성 범위와 한계를 고정한다. 핵심 기준은 실제 기관 송전망 원장 데이터를 사용했다고 주장하지 않으면서, 공공 전력 수요 데이터를 현실성 강화 simulated grid에 맞게 재구성했다는 점을 명확히 설명하는 것이다.

최종 표현은 다음 문장을 기준으로 한다.

> SGOP는 실제 기관 송전망 원장 데이터가 아닌, 공공 전력 수요 데이터를 기반으로 지역 부하 비중, 발전소 위치, 송전망 연결 구조를 반영해 재구성한 시뮬레이션용 계통 데이터셋을 사용한다.

발표용 문장은 다음처럼 쓴다.

> 실제 계통 원장 데이터는 접근 제한이 있어 확보하지 못했지만, 공공 전력 수요 데이터를 바탕으로 발전소, 송전탑, 선로 구조를 반영한 simulated grid에 매핑하여 LSTM/GNN 학습과 송전망 병목 분석을 수행했다.

## 데이터 출처와 성격

| 데이터 | 현재 파일 | 성격 | 주장 가능 범위 |
|---|---|---|---|
| 과거 전력 수요/공급 | `data/raw/sukub*.csv` | 공공 전력 수급 시계열 | 실제 과거 전력 수요/공급 기반 |
| 국가 단위 hourly 부하 | `public_data_adapter.load_kpx_national_hourly()` 산출 | 공공 데이터를 시간 단위로 정리한 중간 데이터 | 공개 수요 데이터를 학습 가능한 시간축으로 정규화 |
| 송전망 노드 | `data/grid/enhanced/nodes.csv` | 발전소 12개, 송전탑/부하 노드 24개 synthetic grid | 실제 지리와 발전소/부하권역을 참고한 시뮬레이션 노드 |
| 송전망 선로 | `data/grid/enhanced/lines.csv` | GridLine 44개, 용량/전압/거리/리액턴스 포함 | 시뮬레이션용 송전망 topology |
| 발전소 상세 | `data/grid/enhanced/plants.csv` | 발전소 용량, fuel type, availability 등 | 실제 발전소 특성을 참고한 모델링 데이터 |
| 송전탑 후보 | `data/grid/enhanced/tower_candidates.csv` | 후보 위치, 비용, 지형/환경/정책 리스크 | 입지 시뮬레이션용 후보 데이터 |
| LSTM 모델 | `models/lstm/model.keras`, `models/lstm/scalers.pkl` | 노드별 부하 시계열 예측 모델 | 재분배된 공공 수요 기반 node load 예측 |
| Neural GNN 모델 | `models/gnn/model.pt`, `models/gnn/metadata.json` | GridLine adjacency를 쓰는 PyTorch GNN | 송전망 연결 구조를 반영한 node load 예측 |

## 말할 수 있는 표현

- 공공 전력 수요 데이터를 사용했다.
- 공공 수요 데이터를 SGOP simulated grid의 노드 단위로 재분배했다.
- 발전소 위치, 발전소 용량, 지역 부하 특성, 송전망 연결 구조를 반영했다.
- LSTM은 노드별 과거 부하 시계열을 학습해 미래 부하를 예측한다.
- GNN/Neural GNN은 GridLine 연결 구조를 반영해 인접 노드 영향을 함께 고려한다.
- DC Power Flow로 입력 가정하의 선로별 조류와 이용률을 계산한다.
- 위험 선로와 병목 선로는 입력 데이터와 모델 가정 안에서 수치적으로 산출한 결과다.

## 피해야 하는 표현

- 실제 한국 송전망 원장 데이터를 그대로 사용했다.
- 실제 기관 계통 운영 데이터로 검증했다.
- 실제 송전탑별 실측 부하를 학습했다.
- 실제 선로별 실시간 조류 데이터를 사용했다.
- 실제 계통 운영 판단에 바로 적용할 수 있다.
- 특정 실제 선로가 현실에서도 위험하다고 단정한다.

대신 다음처럼 제한 조건을 붙인다.

> 본 결과는 공공 수요 데이터와 SGOP simulated grid 입력 가정하에서 산출된 시뮬레이션 결과다.

## 객관성 수준

| 항목 | 객관성 수준 | 근거 |
|---|---|---|
| 공공 전력 수요 원천 데이터 | 높음 | 외부 공개 데이터 기반의 과거 수요/공급 시계열 |
| hourly 전처리 데이터 | 높음 | timestamp 기준 집계와 결측/이상치 처리 규칙으로 재현 가능 |
| simulated grid topology | 중간 | 실제 지리/발전소/권역 특성을 참고했지만 기관 원장 복제는 아님 |
| 노드별 부하 배분 | 중간 | `base_load_mw`, 지역권, 부하 비중 기반 모델링 결과 |
| 발전소 출력 배분 | 중간 | 발전소 용량과 availability 기반 모델링 결과 |
| DC Power Flow 결과 | 중간~높음 | 입력 가정이 명확할 때 계산 방식은 객관적 |
| LSTM/GNN 예측 결과 | 중간~높음 | 학습 데이터와 모델 가정 안에서는 정량 비교 가능 |
| 실제 계통 재현성 | 낮음~중간 | 실제 선로별 계측/운영 이력이 없기 때문에 제한적 |

## 현재 데이터 변환 흐름

현재 Prediction 경로는 다음 구조다.

```text
data/raw/sukub*.csv
  -> public_data_adapter.load_kpx_national_hourly()
  -> timestamp, demand_mw, supply_mw
  -> data/processed/national_load_hourly.csv
  -> data/processed/grid_node_weights.csv
  -> data/processed/grid_node_load_history.csv
  -> PredictionService._load_grid_history()
  -> feature_builder
  -> Baseline / LSTM / GNN / Neural GNN
  -> PredictionResult.risk_lines
  -> app stress 분석과 지도 표시
```

`PredictionService._load_grid_history()`는 `data/processed/grid_node_load_history.csv`를 1순위 입력으로 사용한다. 파일이 없거나 현재 GridDataset과 node_id가 맞지 않으면 기존 `PredictionService._redistribute_kpx_history_to_grid()` 경로로 내려간다.

이 흐름에서 `data/grid/enhanced/lines.csv`는 GNN/Neural GNN의 graph edge와 Prediction 위험 선로 계산에 사용된다. `data/processed/grid_line_flow_history.csv`는 모델 결과를 선로 이용률 기준으로 비교할 수 있는 DC Power Flow 평가 라벨이다. `data/grid/enhanced/nodes.csv`의 `base_load_mw`와 `GridPowerProfile.load_weight`는 전국 부하를 노드별로 나누는 기준이다.

## 후속 가공 산출물 기준

데이터 객관성을 더 높이려면 다음 중간 산출물을 명시적으로 생성한다.

### 1. `data/processed/national_load_hourly.csv`

공공 수요 데이터를 시간 단위로 정리한 기준 파일이다.

필수 컬럼:

```text
timestamp
demand_mw
supply_mw
source_file
```

현재 생성 기준:

```text
입력: data/raw/sukub*.csv
전처리 함수: src.data.preprocess.build_national_load_hourly()
출력: data/processed/national_load_hourly.csv
행 수: 11,127
기간: 2025-02-04 00:00:00 ~ 2026-05-14 12:00:00
source_file: KPX_public_sukub_csv
처리 방식: 원본 5분 단위 수급 데이터를 1시간 평균으로 집계하고 timestamp 중복을 제거한다.
```

### 2. `data/processed/grid_node_weights.csv`

전국 수요를 SGOP GridNode로 재분배하는 근거 파일이다.

필수 컬럼:

```text
node_id
node_name
node_type
region
source
source_id
base_load_mw
load_weight
generation_capacity_mw
generation_weight
is_load_node
is_generation_node
calibration_reason
```

현재 생성 기준:

```text
입력: data/grid/enhanced/*.csv
전처리 함수: src.data.preprocess.build_grid_node_weights()
출력: data/processed/grid_node_weights.csv
전체 노드 수: 36
부하 노드 수: 24
발전 노드 수: 12
load_weight 합계: 1.0
generation_weight 합계: 1.0
```

계산 공식:

```text
load_weight = transmission_tower.base_load_mw / 전체 기본 송전탑 base_load_mw 합계
generation_weight = (plant.capacity_mw x plant.availability) / 전체 발전 가능 용량 합계
```

사용자 또는 xAI 승인 노드 처리:

```text
공식 grid_node_weights.csv는 기본 enhanced grid 기준으로 고정한다.
app 실행 중 사용자가 추가하거나 xAI 개선안에서 승인한 노드는 user_installations로 동적 가중치표를 재계산할 수 있다.
사용자/xAI 승인 송전탑은 기본적으로 경로 보강 노드로 취급해 load_weight=0, generation_weight=0으로 둔다.
사용자 추가 발전소는 capacity_mw x availability 기준으로 generation_weight를 재계산한다.
```

### 3. `data/processed/grid_node_load_history.csv`

LSTM/GNN 학습의 핵심 입력 파일이다.

필수 컬럼:

```text
timestamp
node_id
node_name
node_type
region
load_mw
generation_mw
net_injection_mw
load_weight
generation_weight
national_demand_mw
national_supply_mw
grid_total_load_mw
grid_total_generation_mw
scale_to_grid
source
```

현재 생성 기준:

```text
입력 1: data/processed/national_load_hourly.csv
입력 2: data/processed/grid_node_weights.csv
전처리 함수: src.data.preprocess.build_grid_node_load_history()
출력: data/processed/grid_node_load_history.csv
행 수: 400,572
시간 수: 11,127
노드 수: 36
부하 노드 수: 24
발전 노드 수: 12
기간: 2025-02-04 00:00:00 ~ 2026-05-14 12:00:00
scale_to_grid: 0.114652
source: KPX_public_sukub_csv + SGOP_grid_node_weights
```

계산 공식:

```text
scale_to_grid = DEFAULT_GRID_TOTAL_LOAD_MW / national_demand_mw 중앙값
grid_total_load_mw = national_demand_mw x scale_to_grid
grid_total_generation_mw = national_supply_mw x scale_to_grid
load_mw = grid_total_load_mw x load_weight
generation_mw = grid_total_generation_mw x generation_weight
net_injection_mw = generation_mw - load_mw
```

`national_supply_mw`는 KPX 공개 수급 데이터의 공급능력 계열이므로, 여기서 만든 `generation_mw`는 실제 발전소별 실측 발전량이 아니라 학습과 시뮬레이션을 위한 공급 가능량 proxy다.

검증 기준:

```text
timestamp/node_id 조합은 중복될 수 없다.
timestamp별 load_mw 합계는 grid_total_load_mw와 같아야 한다.
timestamp별 generation_mw 합계는 grid_total_generation_mw와 같아야 한다.
timestamp별 net_injection_mw 합계는 grid_total_generation_mw - grid_total_load_mw와 같아야 한다.
```

모델 호환을 위해 학습 함수에 넘길 때는 `node_id`를 `bus_id` alias로 변환할 수 있다. 이때 실제 값은 `TOWER_SEOUL`, `TOWER_DAEGU` 같은 GridNode ID를 유지한다.

### 4. `data/processed/grid_line_flow_history.csv`

시간별 DC Power Flow를 실행해 만든 선로 라벨 파일이다.

필수 컬럼:

```text
timestamp
line_id
from_node_id
to_node_id
from_node_name
to_node_name
flow_mw
abs_flow_mw
capacity_mw
utilization
status
risk_level
loss_mw
from_angle_deg
to_angle_deg
angle_delta_deg
slack_bus_id
reactance_pu
line_status_source
source
```

현재 생성 기준:

```text
입력 1: data/processed/grid_node_load_history.csv
입력 2: data/grid/enhanced/*.csv
전처리 함수: src.data.preprocess.build_grid_line_flow_history()
출력: data/processed/grid_line_flow_history.csv
행 수: 489,588
시간 수: 11,127
선로 수: 44
기간: 2025-02-04 00:00:00 ~ 2026-05-14 12:00:00
최대 이용률: 0.9297
source: SGOP_grid_node_load_history + DC_power_flow_balanced_dispatch
```

계산 흐름:

```text
timestamp별 GridNode load_mw를 읽는다.
generation_mw는 공급능력 proxy가 아니라 grid_total_load_mw x generation_weight로 재배분한다.
GridDataset.power_profiles를 timestamp별로 교체한다.
dc_power_flow.solve()를 실행한다.
compute_line_statuses()로 flow_mw, utilization, status, risk_level을 만든다.
```

상태 분포:

```text
normal: 487,414
warning: 2,161
critical: 13
overload: 0
```

위험도 분포:

```text
low: 481,337
medium: 7,031
high: 1,207
critical: 13
```

이 파일은 실제 선로별 계측 조류가 아니다. 공공 수요 기반 SGOP simulated grid 입력에 DC Power Flow를 적용해 만든 학습/검증용 선로 라벨이다.

이 파일이 생기면 GNN은 단순 node load 예측을 넘어 미래 선로 이용률 또는 위험 선로 예측까지 확장할 수 있다.

## LSTM 학습 데이터 정의

LSTM은 송전망 연결 구조 자체보다 노드별 시간 패턴을 학습한다.

입력 단위:

```text
timestamp
bus_id
load_mw
generation_mw
temperature_c optional
```

현재 모델 구조:

```text
최근 24시간 x [load_norm, hour_sin, hour_cos, is_weekend, temp_norm]
  -> LSTM
  -> 미래 24시간 load_mw
```

재학습 산출물:

```text
학습 스크립트: scripts/train_lstm_from_processed.py
입력: data/processed/grid_node_load_history.csv
대상 노드: node_type=transmission_tower, load_mw > 0
모델: models/lstm/model.keras
Scaler: models/lstm/scalers.pkl
학습 이력: models/lstm/training_history.csv
평가 요약: models/lstm/evaluation_summary.json
모델별 요약: data/processed/model_evaluation_summary.csv
```

평가 방식:

```text
timestamp 시간 순서를 유지해 마지막 holdout 구간을 테스트로 둔다.
학습 구간으로 LSTM을 fit한다.
테스트 구간의 forecast_start를 일정 간격으로 이동시키며 미래 24시간을 예측한다.
실제 재분배 load_mw와 예측 load_mw를 비교해 MAE, RMSE, MAPE를 계산한다.
```

주장 가능 범위:

> LSTM은 공공 수요 기반으로 재분배된 SGOP GridNode별 부하 시계열을 학습해 미래 노드 부하를 예측한다.

## GNN/Neural GNN 학습 데이터 정의

GNN은 `GridLine` 연결 구조를 graph edge로 사용한다.

노드:

```text
부하가 있는 transmission_tower GridNode
예: TOWER_SEOUL, TOWER_SUWON, TOWER_DAEJEON
```

엣지:

```text
data/grid/enhanced/lines.csv의 from_node_id, to_node_id
```

현재 Neural GNN 기준:

```text
node_count = 24
graph_edge_count = 44
lookback_h = 24
horizon_h = 24
```

재학습 산출물:

```text
학습 스크립트: scripts/train_neural_gnn_from_processed.py
입력: data/processed/grid_node_load_history.csv
Graph edge: data/grid/enhanced/lines.csv
대상 노드: node_type=transmission_tower, load_mw > 0
모델: models/gnn/model.pt
학습 이력: models/gnn/training_history.csv
평가 요약: models/gnn/evaluation_summary.json
노드별 평가: models/gnn/node_error_summary.csv
모델별 요약: data/processed/model_evaluation_summary.csv
```

평가 방식:

```text
timestamp 시간 순서를 유지해 마지막 holdout 구간을 테스트로 둔다.
학습 구간으로 Neural GNN을 fit한다.
테스트 구간의 forecast_start를 일정 간격으로 이동시키며 recursive 방식으로 미래 24시간을 예측한다.
실제 재분배 load_mw와 예측 load_mw를 비교해 MAE, RMSE, MAPE를 계산한다.
```

주장 가능 범위:

> Neural GNN은 SGOP simulated grid의 GridLine adjacency를 사용해 인접 노드 부하 영향을 반영한 graph-temporal 예측을 수행한다.

## 모델 비교 지표 기준

`data/processed/model_evaluation_summary.csv`는 Baseline, LSTM, Neural GNN, LSTM+Neural GNN을 같은 holdout 구간에서 비교하는 발표용 요약 파일이다.

평가 스크립트:

```text
scripts/evaluate_prediction_models_from_processed.py
```

평가 입력:

```text
노드 부하 실제값: data/processed/grid_node_load_history.csv
선로 이용률 라벨: data/processed/grid_line_flow_history.csv
Graph edge: data/grid/enhanced/lines.csv
```

현재 평가 방식:

```text
학습 구간: 2025-02-04 00:00:00 ~ 2026-03-05 00:00:00
테스트 구간: 2026-03-05 01:00:00 ~ 2026-05-14 12:00:00
forecast horizon: 24h
eval step: 24h
노드 평가 샘플: 40,056
선로 평가 샘플: 73,436
```

현재 모델별 결과:

| 모델 | MAE(MW) | RMSE(MW) | MAPE(%) | 선로 이용률 MAE(pp) | 평균 미래 위험 선로 |
|---|---:|---:|---:|---:|---:|
| Baseline | 35.61 | 53.90 | 14.36 | 15.98 | 4.00 |
| LSTM | 18.57 | 29.86 | 7.18 | 15.07 | 3.94 |
| Neural GNN | 15.93 | 25.81 | 5.99 | 14.85 | 3.82 |
| LSTM+Neural GNN | 16.36 | 26.84 | 6.32 | 14.98 | 3.94 |

주의할 점:

```text
노드 부하 MAE/RMSE/MAPE는 실제 holdout node load와 예측 node load를 직접 비교한 값이다.
선로 이용률 MAE는 예측 node load로 만든 endpoint pressure 기반 선로 이용률 proxy를 DC Power Flow 라벨과 비교한 값이다.
즉 선로 지표는 실제 계측 조류 인증값이 아니라 모델 간 상대 비교를 위한 보조 지표다.
```

app의 `Prediction 비교` 탭은 이 파일을 읽어 모델별 성능표와 막대 그래프를 표시한다. 이 표를 통해 Baseline 대비 LSTM/Neural GNN이 과거 재분배 GridNode 부하 패턴을 더 잘 학습했다는 점을 수치로 설명할 수 있다.

## 한계

- 실제 기관 송전망 원장 데이터는 사용하지 않았다.
- 실제 송전탑별 시간대 부하 실측값은 없다.
- 실제 선로별 시간대 조류 `flow_mw` 실측값은 없다.
- 실제 사고, 정비, 차단, 보호계전 상태는 반영하지 않았다.
- 선로 용량, 리액턴스, 지형 리스크 일부는 시뮬레이션용 가정값이다.
- 따라서 결과는 실제 계통 운영 판단이 아니라 MVP 검증과 의사결정 흐름 시연용이다.

## app 및 발표 표기 기준

짧은 UI 표기:

```text
데이터 기준: 공공 수요 데이터 기반 simulated grid
```

상세 UI 표기:

```text
실제 기관 원장 데이터가 아닌, 공공 수요 데이터와 SGOP simulated grid를 기반으로 구성한 시뮬레이션 데이터셋입니다.
```

발표 답변:

```text
실제 기관 계통 원장 데이터는 보안과 접근 제한으로 확보하지 못했습니다. 대신 공공 전력 수요 데이터를 사용했고, 이를 발전소 위치, 지역 부하 비중, 송전망 연결 구조를 반영한 simulated grid에 재분배해 LSTM/GNN 학습 데이터와 DC Power Flow 입력으로 사용했습니다.
```

## 1번 작업 완료 기준

- 데이터 출처별 성격을 구분했다.
- 말할 수 있는 표현과 피해야 하는 표현을 고정했다.
- 공공 데이터 기반 simulated grid라는 주장 범위를 문서화했다.
- 후속 `national_load_hourly`, `grid_node_weights`, `grid_node_load_history`, `grid_line_flow_history` 산출물 기준을 정의했다.
- LSTM/GNN 학습 데이터의 의미와 한계를 구분했다.
