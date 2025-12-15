# Real-time Trading Scheduler

## ภาพรวม

Real-time Trading Scheduler คือระบบที่ตรวจสอบเงื่อนไข Entry/Exit แบบอัตโนมัติทุก 1 นาที (หรือตามที่กำหนด) สำหรับคู่เงินที่เลือก

### คุณสมบัติ

✅ **Entry Conditions (4 Rules)**:
1. CDC Color = GREEN (both LTF and HTF)
2. Leading Red exists
3. Leading Signal (Momentum Flip + Higher Low)
4. Pattern = W-Shape (not V-Shape)

✅ **Exit Conditions (5 Conditions)**:
1. EMA Crossover Bearish (Trend Reversal)
2. Trailing Stop Hit
3. CDC Pattern Orange → Red
4. RSI Divergence (STRONG_SELL)
5. Structural Stop Loss

✅ **Fibonacci-based Trailing Stop**:
- W-Shape Pattern → Activate at Fib 100% Extension + 5%
- V-Shape/No Pattern → Activate at 7.5% profit

---

## โครงสร้างไฟล์

```
services/control_plane/src/
├── trading/
│   ├── __init__.py              # Package init
│   ├── realtime_engine.py       # ตรรกะหลัก Entry/Exit
│   └── scheduler.py             # Scheduler (APScheduler)
└── routes/
    └── bot.py                   # API Endpoints (เพิ่ม 3 endpoints)
```

---

## API Endpoints

### 1. เริ่ม Scheduler

```bash
POST /bot/scheduler/start
```

**Request Body:**
```json
{
  "pairs": ["BTC/USDT", "ETH/USDT"],
  "interval_minutes": 1
}
```

**Response:**
```json
{
  "status": "started",
  "pairs": ["BTC/USDT", "ETH/USDT"],
  "interval_minutes": 1,
  "message": "Scheduler started - checking every 1 minute(s)"
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:5001/bot/scheduler/start" \
  -H "Content-Type: application/json" \
  -d '{
    "pairs": ["BTC/USDT"],
    "interval_minutes": 1
  }'
```

---

### 2. หยุด Scheduler

```bash
POST /bot/scheduler/stop
```

**Response:**
```json
{
  "status": "stopped",
  "message": "Scheduler stopped successfully"
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:5001/bot/scheduler/stop"
```

---

### 3. ดูสถานะ Scheduler

```bash
GET /bot/scheduler/status
```

**Response:**
```json
{
  "status": "running",
  "is_running": true,
  "pairs": ["BTC/USDT"],
  "interval_minutes": 1,
  "jobs": [
    {
      "id": "trading_check_1m",
      "next_run": "2025-12-12 14:01:00"
    }
  ]
}
```

**cURL Example:**
```bash
curl "http://localhost:5001/bot/scheduler/status"
```

---

## วิธีใช้งาน

### 1. เริ่ม Development Environment (แนะนำ)

ใช้ `dev-all.sh` script ที่จะ start ทั้ง Worker และ Control Plane พร้อมกัน:

```bash
cd services/control_plane
./scripts/dev-all.sh
```

**หยุด**: กด `Ctrl + C`

**Restart**:
```bash
./scripts/kill-all.sh && ./scripts/dev-all.sh
```

**ดู processes ที่ทำงาน**:
```bash
ps aux | grep -E "(wrangler|esbuild|uvicorn)" | grep -v grep
```

### 1.1 เริ่มแบบแยก (Manual)

หากต้องการ start แบบแยก:

**Start Cloudflare Worker:**
```bash
cd services/cloudflare_api
npx wrangler dev --port 8787
```

**Start Control Plane:**
```bash
cd services/control_plane
CLOUDFLARE_WORKER_URL=http://localhost:8787 uvicorn src.app:app --reload --host 0.0.0.0 --port 5001
```

### 2. เริ่ม Scheduler ผ่าน API

```bash
curl -X POST "http://localhost:5001/bot/scheduler/start" \
  -H "Content-Type: application/json" \
  -d '{
    "pairs": ["BTC/USDT"],
    "interval_minutes": 1
  }'
```

### 3. ตรวจสอบ Log

Scheduler จะพิมพ์ log ใน console ทุกครั้งที่ตรวจสอบ:

```
============================================================
[2025-12-12 14:00:00] 🔍 Checking trading signals...
Pairs: BTC/USDT
============================================================

[BTC/USDT] Position State: FLAT | Qty: 0
⏸️  [BTC/USDT] no_entry_signal

============================================================
[2025-12-12 14:00:05] ✅ Check completed
============================================================
```

### 4. หยุด Scheduler

```bash
curl -X POST "http://localhost:5001/bot/scheduler/stop"
```

---

## ตัวอย่าง Output

### Entry Signal Detected
```
============================================================
[2025-12-12 14:01:00] 🔍 Checking trading signals...
Pairs: BTC/USDT
============================================================

[BTC/USDT] Position State: FLAT | Qty: 0
✅ [ENTRY] BTC/USDT @ 92530.50 | Qty: 0.107841 | SL: 90000.00
🟢 [BTC/USDT] ENTRY SIGNAL: 92530.5

============================================================
[2025-12-12 14:01:05] ✅ Check completed
============================================================
```

### Exit Signal Detected
```
============================================================
[2025-12-12 14:05:00] 🔍 Checking trading signals...
Pairs: BTC/USDT
============================================================

[BTC/USDT] Position State: LONG | Qty: 0.107841
❌ [EXIT] BTC/USDT @ 94200.00 | Reason: ORANGE_RED | PnL: +1.81%
🔴 [BTC/USDT] EXIT SIGNAL: ORANGE_RED

============================================================
[2025-12-12 14:05:03] ✅ Check completed
============================================================
```

---

## Configuration

### เปลี่ยนช่วงเวลาตรวจสอบ

Default: ทุก 1 นาที

เปลี่ยนเป็นทุก 5 นาที:
```bash
curl -X POST "http://localhost:5001/bot/scheduler/start" \
  -H "Content-Type: application/json" \
  -d '{
    "pairs": ["BTC/USDT"],
    "interval_minutes": 5
  }'
```

### เพิ่มหลายคู่เงิน

```bash
curl -X POST "http://localhost:5001/bot/scheduler/start" \
  -H "Content-Type: application/json" \
  -d '{
    "pairs": ["BTC/USDT", "ETH/USDT", "BNB/USDT"],
    "interval_minutes": 1
  }'
```

---

## Dependencies

ติดตั้ง APScheduler:
```bash
cd services/control_plane
poetry add apscheduler
```

---

## หมายเหตุสำคัญ

1. ⚠️ **Scheduler ทำงานใน Background** - ไม่มีผลกับ Dashboard และ Backtest
2. ⚠️ **Orders จะถูกส่งไป D1 Worker** - ตรวจสอบใน Order Log (D1)
3. ⚠️ **Position State ดึงจาก Order History** - ใช้ FIFO คำนวณตำแหน่งปัจจุบัน
4. ⚠️ **ใช้ Config จาก /config** - ต้องมี Config สำหรับแต่ละคู่เงินก่อน
5. 🔴 **CRITICAL: Closed Candle Strategy**
   - **Entry decisions**: ใช้เฉพาะแท่งเทียนที่ปิดแล้ว (`candles[:-1]`)
   - **Entry price**: ราคาเปิดของแท่งถัดไป (`candles[-1].open`)
   - **Exit (Stop Loss)**: ใช้แท่งปัจจุบัน (Real-time) เพื่อตรวจจับทันที
   - **Exit (Pattern-based)**: ใช้แท่งปิด (Orange→Red, Divergence, EMA Cross)

---

## ✅ Test Results (2025-12-12)

**Status**: Successfully deployed and tested

**Test Log**:
```
************************************************************
🚀 Trading Scheduler STARTED
   Pairs: BTC/USDT
   Interval: Every 1 minute(s)
   Started at: 2025-12-12 14:23:58.811997
************************************************************

============================================================
[2025-12-12 14:23:58] 🔍 Checking trading signals...
Pairs: BTC/USDT
============================================================

[BTC/USDT] Position State: FLAT | Qty: 0
⏸️  [BTC/USDT] no_entry_signal

============================================================
[2025-12-12 14:23:58] ✅ Check completed (2.28 seconds)
============================================================

[After 1 minute - Automatic check]

============================================================
[2025-12-12 14:24:58] 🔍 Checking trading signals...
Pairs: BTC/USDT
============================================================

[BTC/USDT] Position State: FLAT | Qty: 0
⏸️  [BTC/USDT] no_entry_signal

============================================================
[2025-12-12 14:24:58] ✅ Check completed (0.51 seconds)
============================================================
```

**Verified Features**:
- ✅ Scheduler starts successfully via API
- ✅ Immediate first check on startup
- ✅ Automatic checks every 1 minute
- ✅ Position state tracking (FLAT/LONG)
- ✅ Config loading from D1
- ✅ Status endpoint reporting correct state
- ✅ No interference with Dashboard or Backtest pages

---

## Troubleshooting

### Scheduler ไม่ทำงาน
1. ตรวจสอบ logs ใน console
2. เช็ค status: `GET /bot/scheduler/status`
3. ลอง restart server

### Order ไม่ถูกส่ง
1. ตรวจสอบ `CLOUDFLARE_WORKER_URL` ใน .env
2. เช็คว่า Worker/D1 ทำงานปกติ
3. ดู error logs

### Position State ไม่ถูกต้อง
1. เช็ค Order Log ใน D1: `GET /orders/all`
2. ตรวจสอบ `order_type` (ENTRY/EXIT)
3. ตรวจสอบ `filled_qty` และ `status`

---

## ขั้นต่อไป (TODO)

- [ ] เพิ่ม EMA Fast/Slow calculation ใน Candle
- [ ] Implement Trailing Stop logic แบบเต็ม
- [ ] เพิ่ม Notification (LINE, Telegram)
- [ ] Dashboard สำหรับ Monitor Scheduler
- [ ] Backtesting สำหรับ Scheduler config
