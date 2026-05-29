# Grid 전환 기준선

## 목적
- 이 문서는 1~2번 작업의 기준선이다.
- 13~15번 작업 이후 실행 경로는 기존 `BUS_*`, `B*`, `SITE_*` 기준이 아니라 Grid CSV/기본 GridDataset 기준이다.
- 새 기능은 기본 발전소, 기본 송전탑, 사용자 추가 발전소, 사용자 추가 송전탑, 이후 CSV 데이터를 `GridNode`와 `GridLine` 기준으로 확장한다.
- Monitoring, Simulation, Prediction의 기본 계산 연결은 GridDataset을 사용한다.

## 1. Legacy 제거 상태

아래 항목은 14번 작업에서 실행 코드 기준으로 제거했다. 문서에는 추적을 위해 이름을 남긴다.

| Legacy 항목 | 현재 역할 | 대표 위치 | 처리 원칙 |
|---|---|---|---|
| `BUS_001~BUS_013` | 이전 Simulation/Prediction/날씨/KPX 분배용 버스 ID | 실행 코드 직접 의존 제거 | KPX는 전국 시계열로 읽고 GridNode 가중치로 재분배 |
| `B01~B13` | 이전 Monitoring/DC Power Flow 내부 버스 ID | 실행 코드 직접 의존 제거 | DC Power Flow 입력은 GridDataset 변환기에서 생성 |
| `SITE_NORTH`, `SITE_CENTRAL`, `SITE_SOUTH` | 이전 Simulation 기본 후보지 | 실행 코드 직접 의존 제거 | 후보지는 `tower_candidates.csv`와 사용자 송전탑에서 생성 |
| `_DEFAULT_CANDIDATES` | 이전 Simulation 후보지 하드코딩 | 삭제 | `TransmissionTowerSpec`/CSV 후보로 대체 |
| `_BUS_METADATA` | 이전 Simulation 버스 좌표/이름 하드코딩 | 삭제 | `GridNode` 목록으로 대체 |
| `_MONITORING_BUS_COORDINATES` | 이전 Monitoring overlay 좌표 하드코딩 | 삭제 | `GridDataset` metadata 좌표만 사용 |
| `_SIMULATION_BUS_COORDINATES` | 이전 Simulation/Prediction overlay 좌표 하드코딩 | 삭제 | `GridDataset` metadata 좌표만 사용 |
| `_CANDIDATE_COORDINATES` | 이전 Simulation 후보지 overlay 좌표 하드코딩 | 삭제 | 추천 경로 waypoint 좌표만 사용 |
| `_GRAPH_EDGE_DEFS` | 이전 GNN 고정 edge 목록 | 삭제 | `GridLine`에서 edge 생성 |
| Prediction `_BUSES`, `_LINES` | 이전 Prediction mock bus/line 정의 | 삭제 | 예측 노드와 위험 선로는 GridDataset에서 생성 |

## 2. 새 기준 데이터

새 Grid의 기본 seed는 다음 네 부류다.

1. 기본 발전소
2. 기본 송전탑
3. 사용자가 지도에서 추가한 발전소
4. 사용자가 지도에서 추가한 송전탑

이후 CSV가 붙으면 `nodes.csv`, `lines.csv`, `plants.csv`, `tower_candidates.csv`가 같은 계약을 채운다.

## 3. 기본 발전소 seed

| 기존 label | 제안 `node_id` | 노드 타입 | source |
|---|---|---|---|
| 인천 발전소 | `PLANT_INCHEON` | `power_plant` | `default_asset` |
| 광주 발전소 | `PLANT_GWANGJU` | `power_plant` | `default_asset` |
| 속초 발전소 | `PLANT_SOKCHO` | `power_plant` | `default_asset` |
| 부산 발전소 | `PLANT_BUSAN` | `power_plant` | `default_asset` |
| 울산 발전소 | `PLANT_ULSAN` | `power_plant` | `default_asset` |
| 포항 발전소 | `PLANT_POHANG` | `power_plant` | `default_asset` |

## 4. 기본 송전탑 seed

| 기존 label | 제안 `node_id` | 노드 타입 | source |
|---|---|---|---|
| 거창 송전탑 | `TOWER_GEOCHANG` | `transmission_tower` | `default_asset` |
| 서울 송전탑 | `TOWER_SEOUL` | `transmission_tower` | `default_asset` |
| 강릉 송전탑 | `TOWER_GANGNEUNG` | `transmission_tower` | `default_asset` |
| 대전 송전탑 | `TOWER_DAEJEON` | `transmission_tower` | `default_asset` |
| 춘천 송전탑 | `TOWER_CHUNCHEON` | `transmission_tower` | `default_asset` |
| 제주도 송전탑 | `TOWER_JEJU` | `transmission_tower` | `default_asset` |
| 구미 송전탑 | `TOWER_GUMI` | `transmission_tower` | `default_asset` |
| 대구 송전탑 | `TOWER_DAEGU` | `transmission_tower` | `default_asset` |
| 창원 송전탑 | `TOWER_CHANGWON` | `transmission_tower` | `default_asset` |
| 영천 송전탑 | `TOWER_YEONGCHEON` | `transmission_tower` | `default_asset` |
| 상주 송전탑 | `TOWER_SANGJU` | `transmission_tower` | `default_asset` |
| 해남 송전탑 | `TOWER_HAENAM` | `transmission_tower` | `default_asset` |

## 5. 사용자 추가 지점 ID 규칙

- 사용자 발전소: `USER_PLANT_<installation_id>`
- 사용자 송전탑: `USER_TOWER_<installation_id>`
- 원본 `InstallationPoint.installation_id`는 metadata에 보존한다.
- 사용자가 클릭한 좌표는 계속 `coordinate_system="EPSG:4326"`, `elevation_source="not_queried"`를 유지한다.

## 6. Grid 계약 원칙

- 발전소와 송전탑은 모두 `GridNode`다.
- 발전소 상세 능력치는 `PowerPlantSpec`에 둔다.
- 송전탑/후보지 상세 입지 정보는 `TransmissionTowerSpec`에 둔다.
- 선로는 `GridLine`이며 데이터 의미는 양방향을 기본으로 한다.
- DC Power Flow에는 후속 변환기에서 `GridDataset -> BusInput/LineInput`으로 넘긴다.
- GNN edge는 후속 전환에서 `GridLine`으로부터 생성한다.
- LSTM의 기존 `bus_id` 축은 후속 전환에서 `node_id` 축으로 바꾼다.

## 7. 13~15번 반영 사항

- `data/grid/enhanced/`에 12개 발전소, 24개 송전탑, 44개 송전선을 담은 synthetic 확장 CSV를 추가했다.
- 기본 CSV 로더는 `data/grid/enhanced/`를 우선 읽고, 실패 시 기본 Grid mock으로 내려간다.
- Monitoring mock/DC Power Flow, Simulation A*/추천, Prediction mock/baseline/LSTM/GNN은 GridDataset의 node/line을 기준으로 동작한다.
- GNN edge는 고정 목록이 아니라 GridLine에서 생성한다.
- KPX CSV는 기존 버스 분배가 아니라 전국 수급 시계열로 읽은 뒤 GridNode 부하 가중치로 재분배한다.

향후 실제 기관 데이터로 고품질 확장을 하더라도 같은 CSV 계약을 유지한다.
