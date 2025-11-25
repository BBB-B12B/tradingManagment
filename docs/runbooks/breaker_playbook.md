# Circuit Breaker & Incident Playbook

## เมื่อ breaker/kill switch ทำงาน

1. ตรวจ alert จาก Prometheus (`KillSwitchTriggered`, `DailyBreakerClose`).
2. เข้าสู่ control plane `/kill-switch` ตรวจสถานะ `active`.
3. ตรวจ OrderHistory ว่ามีดีลล่าสุดค้างหรือไม่.

## ขั้นตอนแก้ไข

1. หยุด orchestrator/paper runner หากยังทำงาน.
2. ตรวจ risk metrics (`services/orchestrator/src/risk/risk_guard.py`).
3. วิเคราะห์เหตุจาก rule snapshot (W/V, Leading signal) ผ่านรายงาน.
4. หากเกิดจาก structural SL: ปรับ config หรือหยุดคู่เหรียญชั่วคราว.

## การเปิดกลับ

1. ทำ post-mortem ย่อ (timestamp, เหตุผล, action).
2. Reset breaker ผ่าน risk guard (`reset_daily`).
3. เปิด orchestrator ในโหมด monitor 1 รอบก่อน auto.
