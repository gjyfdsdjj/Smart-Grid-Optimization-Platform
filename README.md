# Smart-Grid-Optimization-Platform

이 디렉토리는 SGOP 프로젝트의 루트다.
앱 실행 파일과 전체 소스 코드, 데이터, 모델, 테스트 폴더를 포함한다.

민감 정보는 `.env`, `secrets/`, `data/private/`에서 별도로 관리한다.

## 실행 환경

- Python: `.venv/bin/python` 기준, 현재 검증 버전은 Python 3.10.12다.
- Streamlit 앱 실행:

```bash
.venv/bin/streamlit run app.py --server.port 8501 --server.address 127.0.0.1 --server.headless true
```

- 브라우저 확인:

```text
http://127.0.0.1:8501
```

- HTTP 응답 확인:

```bash
curl -I http://127.0.0.1:8501
```

정상 기준은 `HTTP/1.1 200 OK`다.

## 테스트 명령

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

실데이터 또는 저장 모델을 읽는 테스트:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m integration -q
```

LSTM 로드/재학습 slow smoke 테스트:

```bash
SGOP_RUN_SLOW_LSTM=1 PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python -m pytest -m slow -q
```

`integration` marker는 repository raw data 또는 저장 모델을 읽는 테스트에 사용한다.
`slow` marker는 TensorFlow/LSTM 모델 로드 또는 재학습처럼 기본 제품 흐름보다 오래 걸릴 수 있는 테스트에 사용한다.

Streamlit 페이지 import-safe 검증은 `tests/test_streamlit_import_safe.py`에서 bare-run으로 수행한다. 이때 `missing ScriptRunContext` warning은 Streamlit bare mode 특성이므로 return code가 0이면 통과로 본다.

## Fallback 정책

- 외부 API 또는 실제 데이터가 없어도 mock 기준으로 앱이 중단되지 않아야 한다.
- VWorld 3D/WebGL은 기본 제품 경로가 아니며, 기본 지도 경로는 `map_2_5d`다.
- Folium 또는 `streamlit_folium`이 없으면 지도 대신 overlay 표 fallback을 표시한다.
- Prediction의 LSTM/GNN/Hybrid 경로가 실패하면 baseline 또는 mock fallback으로 내려가고, fallback 이유는 서비스 결과의 `warnings`와 `fallback`에 남긴다.
