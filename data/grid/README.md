# Grid data

이 디렉토리는 새 Grid 전환용 CSV 데이터를 둔다.

- `mock/`: 3~4단계에서 사용하는 최소 예시 CSV다.
- `enhanced/`: 13단계에서 기본 실행 경로에 연결하는 현실성 강화 synthetic CSV다.
- 스키마 문서: `docs/GRID_CSV_SCHEMA_2026-05-29.md`

현재 기본 서비스 로더는 `enhanced/`를 우선 사용하고, CSV가 없거나 깨지면 기본 mock graph로 fallback한다. `mock/`은 최소 계약 검증과 fallback 비교용으로 유지한다.
