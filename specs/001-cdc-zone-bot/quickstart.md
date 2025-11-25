# Quickstart: BinanceTH CDC Zone Bot

## 1. เตรียมสภาพแวดล้อม

1. `python3.11` ติดตั้งพร้อม Poetry
2. รัน `scripts/setup_secrets.sh dev` แล้วเติมคีย์ Binance, Cloudflare
3. `poetry install` ใน `services/signal_engine` และ `services/orchestrator`

## 2. รัน backtest & paper trade

```bash
cd services/signal_engine && poetry run pytest tests/backtest
scripts/replay/run_backtest.py data/sample_windows.json
cd services/orchestrator && poetry run python -m src.simulation.paper_trade_runner
```

## 3. ตั้งค่า Bot

1. รัน `scripts/quickstart/config_wizard.py`
2. ส่งผลลัพธ์ไปยัง control plane API `/config`
3. ตรวจ dashboard (`services/control_plane/src/ui/dashboard.py`) ว่า rule pass ครบ

## 4. เปิดโหมด Semi-auto

1. เริ่ม orchestrator และ control plane API/UI (`cd services/control_plane && poetry run uvicorn src.app:app --reload`)
2. Monitor metrics ที่ Prometheus และ alerts ใน `infra/monitoring/alerts.yml`
3. ใช้ kill switch `/kill-switch` หากต้องหยุดทันที

## 5. เปิดโหมด Auto (หลัง paper trade 2 สัปดาห์)

- ย้าย secrets -> live
- เปิด breaker monitoring
- บันทึก approval ใน OrderHistory
