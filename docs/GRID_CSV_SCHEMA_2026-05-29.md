# Grid CSV 스키마 초안

## 목적
- 이 문서는 3번 작업의 CSV 계약 초안이다.
- 기준 코드는 `src/data/schemas.py`의 `GridNode`, `GridLine`, `PowerPlantSpec`, `TransmissionTowerSpec`다.
- 최소 예시 파일은 `data/grid/mock/` 아래에 둔다.
- 현재 단계에서는 CSV 로더와 서비스 연결을 구현하지 않는다. 연결은 후속 단계에서 진행한다.

## 파일 구성

| 파일 | 역할 | 기준 계약 |
|---|---|---|
| `data/grid/mock/nodes.csv` | 발전소, 송전탑, 사용자 추가 지점을 모두 담는 공통 노드 | `GridNode` |
| `data/grid/mock/lines.csv` | 노드와 노드를 잇는 양방향 송전망 | `GridLine` |
| `data/grid/mock/plants.csv` | 발전소 상세 능력치 | `PowerPlantSpec` |
| `data/grid/mock/tower_candidates.csv` | 기본 송전탑과 후속 후보지 상세 입지 정보 | `TransmissionTowerSpec` |

`latitude`, `longitude`, `coordinate_system`, `elevation_source`는 노드 공통 속성이므로 `nodes.csv`에 둔다. `plants.csv`와 `tower_candidates.csv`는 `node_id`로 위치 노드를 참조한다.

## 공통 규칙
- 모든 ID는 대문자 snake case를 기본으로 한다.
- 기본 발전소 ID는 `PLANT_*`, 기본 송전탑 ID는 `TOWER_*`를 쓴다.
- 사용자 추가 발전소는 `USER_PLANT_<installation_id>`, 사용자 추가 송전탑은 `USER_TOWER_<installation_id>` 형식으로 변환한다.
- 좌표계는 현재 `EPSG:4326`을 기본값으로 둔다.
- 고도 조회 전 값은 `elevation_m`을 비워두고 `elevation_source=not_queried`로 둔다.
- `lines.csv`의 선로 의미는 양방향이다. DC Power Flow 입력은 후속 변환기에서 방향 있는 `from/to` 입력으로 변환한다.
- 빈 숫자값은 `None`으로 읽는다.
- 현재 mock 값은 구조 검증용이며 실제 송전망, 실제 설비 용량, 실제 비용 데이터가 아니다.

## nodes.csv

공통 전력망 노드다. 기존 `BUS_*`, `B*`를 늘리는 대신 발전소와 송전탑을 모두 노드로 다룬다.

| 컬럼 | 필수 | 타입 | 설명 |
|---|---|---|---|
| `node_id` | Y | string | 새 Grid 노드 ID |
| `node_name` | Y | string | 화면 표시 이름 |
| `node_type` | Y | enum | `power_plant`, `transmission_tower`, `user_power_plant`, `user_transmission_tower` |
| `latitude` | Y | float | 위도 |
| `longitude` | Y | float | 경도 |
| `voltage_kv` | Y | float | 대표 전압 |
| `region` | N | string | 권역 |
| `base_load_mw` | N | float | 기본 부하. 발전소 노드는 0으로 둔다 |
| `elevation_m` | N | float | 고도. 미조회면 빈 값 |
| `coordinate_system` | Y | string | 기본 `EPSG:4326` |
| `elevation_source` | Y | string | 기본 `not_queried` |
| `source` | Y | enum | `default_asset`, `user_installation`, `csv`, `fallback_mock`, `legacy` |
| `source_id` | N | string | 원본 asset ID 또는 설치 ID |

헤더:

```csv
node_id,node_name,node_type,latitude,longitude,voltage_kv,region,base_load_mw,elevation_m,coordinate_system,elevation_source,source,source_id
```

## lines.csv

`GridNode` 사이의 송전망 연결이다. 하나의 행은 기본적으로 양방향 연결을 의미한다.

| 컬럼 | 필수 | 타입 | 설명 |
|---|---|---|---|
| `line_id` | Y | string | 선로 ID |
| `from_node_id` | Y | string | 시작 노드 ID |
| `to_node_id` | Y | string | 종료 노드 ID |
| `voltage_kv` | Y | float | 선로 전압 |
| `capacity_mw` | Y | float | 열용량 또는 전송 한계 |
| `reactance_pu` | Y | float | DC Power Flow용 리액턴스 |
| `distance_km` | Y | float | 선로 거리 |
| `resistance_pu` | N | float | 저항 |
| `loss_factor` | N | float | 손실 계수 |
| `terrain_risk` | N | float | 지형 위험도 0~1 |
| `is_bidirectional` | Y | bool | 기본 `true` |
| `status` | Y | enum | `active`, `planned`, `candidate`, `out_of_service` |
| `source` | Y | enum | `default_asset`, `user_installation`, `csv`, `fallback_mock`, `legacy` |

헤더:

```csv
line_id,from_node_id,to_node_id,voltage_kv,capacity_mw,reactance_pu,distance_km,resistance_pu,loss_factor,terrain_risk,is_bidirectional,status,source
```

## plants.csv

발전소 상세 능력치다. 위치와 전압은 같은 `node_id`의 `nodes.csv` 행을 참조한다.

| 컬럼 | 필수 | 타입 | 설명 |
|---|---|---|---|
| `plant_id` | Y | string | 발전소 상세 ID |
| `plant_name` | Y | string | 발전소 이름 |
| `node_id` | Y | string | 연결된 `GridNode.node_id` |
| `capacity_mw` | Y | float | 설비 용량 |
| `fuel_type` | Y | string | 연료 또는 발전원 |
| `min_output_mw` | Y | float | 최소 출력 |
| `max_output_mw` | Y | float | 최대 출력 |
| `ramp_rate_mw_per_h` | N | float | 시간당 출력 변화 가능량 |
| `availability` | N | float | 가용률 0~1 |
| `operating_cost` | N | float | 상대 운영비 또는 비용 계수 |
| `emission_factor` | N | float | 배출 계수 |
| `source` | Y | enum | `default_asset`, `user_installation`, `csv`, `fallback_mock`, `legacy` |

헤더:

```csv
plant_id,plant_name,node_id,capacity_mw,fuel_type,min_output_mw,max_output_mw,ramp_rate_mw_per_h,availability,operating_cost,emission_factor,source
```

## tower_candidates.csv

송전탑 상세와 후보지 평가 속성이다. 기본 송전탑도 이 파일에 넣어 후속 Simulation 후보지 전환의 기준으로 쓴다.

| 컬럼 | 필수 | 타입 | 설명 |
|---|---|---|---|
| `tower_id` | Y | string | 송전탑 또는 후보지 상세 ID |
| `tower_name` | Y | string | 송전탑 또는 후보지 이름 |
| `node_id` | Y | string | 연결된 `GridNode.node_id` |
| `voltage_kv` | Y | float | 대표 전압 |
| `elevation_m` | N | float | 고도. 미조회면 빈 값 |
| `height_m` | N | float | 탑 높이 |
| `terrain_slope_deg` | N | float | 지형 경사도 |
| `install_cost_billion` | N | float | 설치비, 십억 원 단위 |
| `land_type` | N | string | 토지 유형 |
| `environment_risk` | N | float | 환경 리스크 0~1 |
| `policy_risk` | N | float | 정책/인허가 리스크 0~1 |
| `accessibility_score` | N | float | 접근성 점수 0~1 |
| `nearest_node_id` | N | string | 기준이 되는 인접 노드 |
| `source` | Y | enum | `default_asset`, `user_installation`, `csv`, `fallback_mock`, `legacy` |

헤더:

```csv
tower_id,tower_name,node_id,voltage_kv,elevation_m,height_m,terrain_slope_deg,install_cost_billion,land_type,environment_risk,policy_risk,accessibility_score,nearest_node_id,source
```

## 최소 검증 규칙
- 네 파일은 헤더 순서까지 고정한다.
- `nodes.csv.node_id`는 중복될 수 없다.
- `lines.csv.from_node_id`, `lines.csv.to_node_id`는 모두 `nodes.csv.node_id`에 존재해야 한다.
- `plants.csv.node_id`는 `nodes.csv`에 존재하고 `node_type=power_plant`이어야 한다.
- `tower_candidates.csv.node_id`는 `nodes.csv`에 존재하고 `node_type=transmission_tower`이어야 한다.
- `lines.csv`를 무방향 그래프로 보았을 때 최소 mock 데이터는 연결 그래프여야 한다.
- `capacity_mw`, `reactance_pu`, `distance_km`, `voltage_kv`는 양수여야 한다.
- `environment_risk`, `policy_risk`, `accessibility_score`, `terrain_risk`는 값이 있으면 0~1 범위여야 한다.

## 후속 단계에서 할 일
- CSV 로더에서 타입 변환과 오류 메시지를 만든다.
- `GridDataset`으로 묶어 Monitoring, Simulation, Prediction 변환기에 넘긴다.
- 실제 데이터셋 확장 시 mock 값과 실제 값을 분리한다.
- 기존 KPX CSV는 부하 시계열 보정용으로 유지하고, Grid CSV는 노드/선로/설비 구조용으로 사용한다.
