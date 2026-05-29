# processed

이 디렉토리는 전처리와 변환이 끝난 데이터를 저장하는 곳이다.
앱이나 모델이 바로 사용할 수 있는 데이터가 위치한다.

현재 PredictionService는 `grid_node_load_history.csv`를 Baseline/LSTM/GNN 계열의 1순위 입력으로 사용하고, `grid_line_flow_history.csv`를 선로 이용률 평가 라벨 metadata로 연결한다. processed 파일이 없거나 현재 GridDataset과 node_id가 맞지 않으면 기존 KPX raw 재분배 경로로 fallback한다.

## 현재 산출물

- `national_load_hourly.csv`: `data/raw/sukub*.csv` 공공 전력 수급 CSV를 1시간 단위로 정리한 공식 기준 파일이다.
- `grid_node_weights.csv`: 공공 전국 수요를 SGOP GridNode별 부하/발전 가중치로 재분배하기 위한 기준 파일이다.
- `grid_node_load_history.csv`: 공공 전국 수급 시계열을 SGOP GridNode 36개에 시간별 부하/공급 가능량 proxy로 재분배한 학습 기준 파일이다.
- `grid_line_flow_history.csv`: GridNode 시간대 부하를 DC Power Flow에 넣어 만든 선로별 flow/utilization/risk 학습 라벨 파일이다.
- `model_evaluation_summary.csv`: 학습 모델별 holdout 평가 지표를 모아 app/발표 비교에 사용할 수 있게 정리한 요약 파일이다.

## national_load_hourly.csv

컬럼:

```text
timestamp
demand_mw
supply_mw
source_file
```

현재 파일 기준:

```text
기간: 2025-02-04 00:00:00 ~ 2026-05-14 12:00:00
데이터 행 수: 11,127
source_file: KPX_public_sukub_csv
```

## grid_node_weights.csv

컬럼:

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

현재 파일 기준:

```text
입력: data/grid/enhanced/*.csv
전체 노드 수: 36
부하 노드 수: 24
발전 노드 수: 12
load_weight 합계: 1.0
generation_weight 합계: 1.0
```

사용자 또는 xAI 승인 송전탑은 기본 processed 파일에 포함하지 않는다. app 실행 중에는 `build_grid_node_weights(user_installations=...)`로 동적 가중치표를 만들 수 있으며, 신규 송전탑은 기본적으로 경로 보강 노드로 취급해 부하/발전 가중치를 0으로 둔다.

## grid_node_load_history.csv

컬럼:

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

현재 파일 기준:

```text
입력 1: data/processed/national_load_hourly.csv
입력 2: data/processed/grid_node_weights.csv
기간: 2025-02-04 00:00:00 ~ 2026-05-14 12:00:00
데이터 행 수: 400,572
시간 수: 11,127
노드 수: 36
부하 노드 수: 24
발전 노드 수: 12
scale_to_grid: 0.114652
source: KPX_public_sukub_csv + SGOP_grid_node_weights
```

계산 공식:

```text
grid_total_load_mw = national_demand_mw x scale_to_grid
grid_total_generation_mw = national_supply_mw x scale_to_grid
load_mw = grid_total_load_mw x load_weight
generation_mw = grid_total_generation_mw x generation_weight
net_injection_mw = generation_mw - load_mw
```

`generation_mw`는 실제 발전소별 실측 발전량이 아니라 KPX 공개 공급능력 계열을 SGOP 발전소 가중치로 나눈 학습용 공급 가능량 proxy다.

## grid_line_flow_history.csv

컬럼:

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

현재 파일 기준:

```text
입력 1: data/processed/grid_node_load_history.csv
입력 2: data/grid/enhanced/*.csv
기간: 2025-02-04 00:00:00 ~ 2026-05-14 12:00:00
데이터 행 수: 489,588
시간 수: 11,127
선로 수: 44
최대 이용률: 0.9297
source: SGOP_grid_node_load_history + DC_power_flow_balanced_dispatch
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

`grid_node_load_history.csv`의 `generation_mw`는 공급능력 proxy이므로, 선로 라벨 생성 시에는 timestamp별 `grid_total_load_mw`를 `generation_weight`로 재배분한 balanced dispatch를 사용한다. 이 파일은 실제 선로별 계측 조류가 아니라 SGOP simulated grid에 DC Power Flow를 적용한 학습/검증용 라벨이다.

## model_evaluation_summary.csv

컬럼은 모델별로 달라질 수 있지만, app의 `Prediction 비교` 탭은 다음 핵심 필드를 읽어 모델 비교표와 막대 그래프를 만든다.

```text
model
data_source
graph_source
line_label_source
evaluation_kind
line_evaluation_method
node_count
history_rows
history_start
history_end
train_start
train_end
test_start
test_end
lookback_h
horizon_h
epochs_requested
epochs_trained
sample_count
forecast_start_count
mae_mw
rmse_mw
mape_pct
line_sample_count
line_utilization_mae_pp
line_utilization_rmse_pp
mean_future_risk_line_count
mean_max_line_utilization
model_path
scaler_path
training_history_path
evaluation_summary_path
```

이 파일은 실제 운영 성능 인증값이 아니라, 같은 processed grid history 기준으로 모델별 상대 비교를 하기 위한 재현 가능한 평가 요약이다.

현재 평가는 `scripts/evaluate_prediction_models_from_processed.py`로 수행한다. 노드 부하 지표는 holdout 구간 실제 `load_mw`와 예측 `load_mw`를 비교한다. 선로 이용률 지표는 예측된 endpoint node load로 계산한 선로 이용률 proxy를 `grid_line_flow_history.csv`의 DC Power Flow 라벨과 비교한 값이다. 따라서 선로 지표는 실제 계측 조류 인증값이 아니라 모델 간 상대 비교와 발표용 설명을 위한 보조 지표다.

현재 모델별 산출물:

```text
Baseline:
  evaluation_kind: holdout_rolling_24h
  MAE: 35.61 MW
  RMSE: 53.90 MW
  MAPE: 14.36%

LSTM:
  model_path: models/lstm/model.keras
  evaluation_summary_path: models/lstm/evaluation_summary.json
  training_history_path: models/lstm/training_history.csv
  MAE: 18.57 MW
  RMSE: 29.86 MW
  MAPE: 7.18%

Neural GNN:
  model_path: models/gnn/model.pt
  evaluation_summary_path: models/gnn/evaluation_summary.json
  training_history_path: models/gnn/training_history.csv
  node_error_summary_path: models/gnn/node_error_summary.csv
  MAE: 15.93 MW
  RMSE: 25.81 MW
  MAPE: 5.99%

LSTM+Neural GNN:
  model_path: models/lstm/model.keras + models/gnn/model.pt
  hybrid_primary_weight: 0.65
  hybrid_secondary_weight: 0.35
  MAE: 16.36 MW
  RMSE: 26.84 MW
  MAPE: 6.32%
```

Neural GNN의 `graph_edge_count`는 `data/grid/enhanced/lines.csv`의 활성 GridLine 수를 기준으로 기록한다. 실제 계산에서는 학습 대상 GridNode에 포함되지 않는 발전소-송전탑 edge는 adjacency 정규화 단계에서 제외될 수 있지만, 데이터 출처 기준으로는 전체 GridLine topology를 사용했다고 설명한다.
