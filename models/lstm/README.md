# lstm

이 디렉토리는 LSTM 기반 예측 모델 파일을 저장하는 곳이다.
학습 가중치, 체크포인트, 관련 산출물을 둘 수 있다.

## 현재 산출물

- `model.keras`: `data/processed/grid_node_load_history.csv`의 송전탑 부하 이력으로 학습한 Keras LSTM 모델이다.
- `scalers.pkl`: GridNode별 `load_mw` 정규화 scaler와 학습 node_id 목록을 담는다.
- `training_history.csv`: epoch별 `loss`, `mae`, `val_loss`, `val_mae`, `learning_rate`를 기록한다.
- `evaluation_summary.json`: 시간 순서 holdout 구간에서 계산한 MAE, RMSE, MAPE와 학습/평가 범위를 기록한다.

재학습 명령:

```bash
PYTHONPYCACHEPREFIX=/tmp/sgop_pycache .venv/bin/python scripts/train_lstm_from_processed.py --epochs 5 --batch-size 256
```

이 모델은 실제 송전탑별 실측 부하가 아니라 공공 수요 데이터를 SGOP simulated grid의 송전탑 노드로 재분배한 학습 데이터를 사용한다.
