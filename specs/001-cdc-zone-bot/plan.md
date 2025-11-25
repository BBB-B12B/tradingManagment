# แผนการพัฒนา: BinanceTH CDC Zone Bot

**สาขา**: `001-cdc-zone-bot` | **วันที่**: 2025-11-24 | **สเปค**: [spec.md](./spec.md)
**อินพุต**: Feature specification from `/specs/001-cdc-zone-bot/spec.md`

**หมายเหตุ**: เทมเพลตนี้ถูกเติมโดยคำสั่ง `/speckit.plan`. ดูเวิร์กโฟลว์ที่ `.specify/templates/commands/plan.md`

## สรุปภาพรวม

สร้างบอทสำหรับ BinanceTH ที่ทำงานตามระบบ “CDC สู่โซน” แบบ 3 ชั้นและกฎ 4 ข้อ (CDC สี, แดงนำหน้าแบบ Multi Timeframe, สัญญาณนำหน้า Momentum+Higher Low, รูปแบบราคา W) พร้อม stateful execution, การจัดการคำสั่ง ≤1% ต่อดีล, ตัวเลือก structural stop-loss, และฐานข้อมูลบน Cloudflare สำหรับ audit/report. โครงการต้องรองรับ research/backtest → paper trade → live orchestrator พร้อมแดชบอร์ดสถานะและ kill switch.

## บริบททางเทคนิค

**Language/Version**: Python 3.11 สำหรับ signal/orchestration, TypeScript (Cloudflare Workers) สำหรับ API เข้าถึง D1/KV  
**Primary Dependencies**: pandas, NumPy, TA-Lib/ta (indicator), ccxt (BinanceTH API wrapper), FastAPI (control plane API), Cloudflare Workers/D1 SDK  
**Storage**: Cloudflare D1 (OrderHistoryDB, configs), Cloudflare KV/Durable Objects สำหรับ state/locks, S3-compatible storage สำหรับ backtest snapshot  
**Testing**: pytest + hypothesis (logic), backtesting.py สำหรับ simulation, custom integration harness กับ Binance Testnet  
**Target Platform**: Ubuntu 22.04 server for orchestrator, Cloudflare Workers edge runtime for API/state, BinanceTH Spot/Testnet endpoints  
**Project Type**: multi-service (signal engine + orchestrator + Cloudflare worker API)  
**Performance Goals**: ประมวลผลสัญญาณทุก 1 นาทีสำหรับ TF 1H, latency ส่งคำสั่ง < 2 วินาทีหลังครบกฎ, รองรับ 10 คู่พร้อมกัน  
**Constraints**: Exposure ≤1% ต่อดีล, circuit breaker daily loss 3% / drawdown 5%, ต้องมี deterministic indicator pipelines (shared code path)  
**Scale/Scope**: เริ่ม 5-10 คู่สกุล, รองรับ 3 environment (research, simulation, live), รายงานย้อนหลังอย่างน้อย 1 ปี

## การตรวจตามรัฐธรรมนูญ

*ด่านบังคับ: ต้องผ่านก่อน Phase 0 และทบทวนอีกครั้งหลัง Phase 1*

- **รักษาทุน**: enforce 1% per-trade cap, 3% daily loss breaker, 5% drawdown stop ผ่าน config validation และ orchestrator guard. ต้องออกแบบ risk service ที่บังคับใช้ก่อนวาง order.
- **ความกำหนดซ้ำของ Indicator**: ออกแบบ signal-engine package ใช้ชุดโค้ดเดียวสำหรับ backtest/sim/live พร้อม snapshot metadata (source, timezone, hash). Cloud storage เก็บ raw candles + CDC outputs ที่เซ็นชื่อเวลา.
- **ด่านวิจัย**: pipeline backtest ≥3 market regimes + paper trade 2 สัปดาห์ก่อน live toggle. แผนต้องระบุ tooling (backtesting.py + historical Binance data) และการ log pass/fail ต่อกฎ.
- **การแยกสภาพแวดล้อม**: ระบุ infra สำหรับ research cluster, simulation service ที่ใช้ Binance Testnet, และ orchestrator live with control plane approvals. Secrets/keys ต้องแยก vault/namespace.
- **การสังเกตการณ์/ปุ่มหยุด**: ตั้ง metrics (signal latency, rule pass counts, blocked orders) ส่งไปที่ Grafana/Prometheus, alert บน breaker/kill switch. Control plane UI ต้องให้ manual kill + log เหตุการณ์.

## โครงสร้างโปรเจกต์

### Documentation (this feature)

```text
specs/001-cdc-zone-bot/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### ซอร์สโค้ด (รูทรายการ)

```text
services/
├── signal_engine/       # CDC indicators, MT/HT orchestration, W/V detection
├── orchestrator/        # Order manager, risk guardrails, Binance client
├── control_plane/       # FastAPI webhooks/UI for approvals + dashboards
└── cloudflare_api/      # Workers scripts exposing D1/KV endpoints

infra/
├── terraform/           # Cloudflare + secrets + monitoring resources
└── pipelines/           # CI/CD scripts, backtest runners

libs/
└── common/              # Shared models, DTOs, config schema

tests/
├── unit/
├── integration/
└── backtest/

scripts/
└── replay/              # Tools for research/paper trade replay
```

**เหตุผลการเลือกโครงสร้าง**: แยก signal calculation, orchestration, control plane, และ Cloudflare layer เพื่อตรงกับ segregation ของ environment และเพื่อให้ deterministic library ถูกใช้งานได้ทั้ง backtest/sim/live. โฟลเดอร์ infra/pipelines ครอบคลุม compliance (monitoring, deployment). tests/backtest รวบรวมการยืนยันกฎ 4 ข้อ.

## การติดตามความซับซ้อน

> **กรอกเฉพาะกรณีที่มีการละเมิดรัฐธรรมนูญและต้องขอยกเว้น**

| รายการละเมิด | เหตุจำเป็น | ทางเลือกที่ง่ายกว่าถูกปฏิเสธเพราะ |
|--------------|------------|------------------------------------|
| (ไม่มี)| - | - |

## Checklist ดำเนินงาน (อ้างอิง speckit.checklist)

- [ ] ยืนยันแผนแยก environment + secrets (research, simulation, live) พร้อม control plane approval flow
- [ ] กำหนด data flow ครบ: candle ingest → signal engine → rule eval → order plan → execution → Cloudflare logging
- [ ] ระบุ tooling backtest ≥3 ช่วงตลาด + paper trade 2 สัปดาห์ และวิธี log pass/fail ของกฎ 1–4
- [ ] ออกแบบ observability (metrics: signal latency, rule pass count, blocked orders; alert on breaker/kill switch)
- [ ] แผน risk enforcement: 1% cap, daily breaker 3%, DD 5%, structural SL option
- [ ] สรุป state schema บน Cloudflare (TradingConfiguration, IndicatorSnapshot, OrderHistoryDB, PositionState, PatternClassification)
- [ ] นิยาม deployment pipeline research → sim → live รวม gate/approval
- [ ] เตรียม quickstart / runbook สำหรับเปิด-ปิดบอท, ใช้งานแดชบอร์ด, และ handling incident
