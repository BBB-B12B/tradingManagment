# Checklist: BinanceTH CDC Zone Bot (Planning Phase)

**วันที่**: 2025-11-24  
**สำหรับไฟล์**: [plan.md](../plan.md)

## Constitution Alignment

- [ ] ยืนยันว่า risk guardrails จากสเปคถูกบังคับใช้ (1% per trade, daily breaker 3%, drawdown 5%)
- [ ] ตรวจว่า signal engine ใช้โค้ดร่วมสำหรับ backtest/sim/live พร้อม snapshot metadata
- [ ] กำหนดแผน backtest ≥3 สภาวะตลาด + paper trade 2 สัปดาห์ก่อนเปิด live toggle
- [ ] ระบุการแยก environment (research, simulation, live) พร้อมการจัดการ secrets และ control plane approvals
- [ ] วาง observability plan: metrics, alerts, kill switch, และทีมรับผิดชอบตอบสนอง

## Technical Planning

- [ ] สรุปสถาปัตยกรรมบริการ (signal_engine, orchestrator, control_plane, Cloudflare API) และ boundary การสื่อสาร
- [ ] ระบุเครื่องมือ/ไลบรารีหลักสำหรับ indicator, Binance API, storage, monitoring
- [ ] กำหนด data flow: ingestion → signal calc → rule evaluation → order plan → execution → logging/report
- [ ] วางแผน state management (PositionState, OrderHistoryDB, PatternClassification) และ schema บน Cloudflare
- [ ] ออกแบบ risk enforcement pipeline (validation → breaker → order queue)

## Testing & Validation

- [ ] นิยาม test strategy สำหรับ unit (rule evaluation), integration (Binance Testnet), และ backtest harness
- [ ] ระบุวิธี replay historical data เพื่อพิสูจน์กฎ 4 ข้อก่อน live
- [ ] วาง plan สำหรับ observability tests (alert triggers, kill switch drill)
- [ ] ยืนยันว่ามี logging ครอบคลุม pass/fail ของกฎ 1–4 และเหตุผล exit

## Operational Readiness

- [ ] นิยามกระบวนการ deploy (research → sim → live) รวม gate/approval แต่ละขั้น
- [ ] กำหนด ownership และ on-call สำหรับ orchestrator/control plane
- [ ] วาง procedure เมื่อ circuit breaker หรือ structural SL ทำงาน (notifications + remediation)
- [ ] เตรียม quickstart / runbook สำหรับการตั้งค่า bot, เปิด/ปิด, และการตรวจสอบปัญหา

## Notes

- ใช้ checklist นี้ควบคู่กับ tasks.md เพื่อยืนยันว่าเฟสถัดไปไม่หลุดหลักการ
