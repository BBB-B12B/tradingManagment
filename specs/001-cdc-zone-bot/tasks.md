# Tasks: BinanceTH CDC Zone Bot

**Input**: Design documents from `/specs/001-cdc-zone-bot/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: สร้างเฉพาะเมื่อจำเป็น/ระบุในสเปค; งานทดสอบในที่นี้จะเกิดเมื่อฟีเจอร์ต้อง พิสูจน์ logic โดยตรง (เช่น backtest harness)

**Organization**: Tasks แบ่งตาม User Story เพื่อให้ส่งมอบได้เป็นอิสระ

## Format: `[ID] [P?] [Story] Description`

- **[P]**: งานทำขนานได้ (ไฟล์ต่าง, ไม่มี dependency)
- **[Story]**: ป้าย User Story (US1, US2, ...)
- ระบุ path ชัดเจนในคำอธิบาย

## Path Conventions

- โครงสร้างจาก plan.md: `services/`, `infra/`, `libs/`, `tests/`, `scripts/`
- Cloudflare assets อยู่ภายใต้ `services/cloudflare_api/`

## Constitution Traceability (MANDATORY)

- มีงานสำหรับ risk guardrails (1% cap, breakers)
- มีงานบังคับ determinism ของ indicator/data
- มีงานบังคับ research gates (backtest + paper trade)
- มีงานสำหรับ segregation/env + secrets
- มีงาน observability + kill switch

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: เตรียมสภาพแวดล้อม, โครงสร้าง และเครื่องมือกลาง

- [x] T001 สร้างโครงสร้างโฟลเดอร์และไฟล์เริ่มต้นตาม plan (`services/*`, `libs/common`, `infra/terraform`, `tests/`) ใน `services/README.md`
- [x] T002 ตั้งค่า Python env/Poetry สำหรับ signal engine และ orchestrator (`services/signal_engine/pyproject.toml`, `services/orchestrator/pyproject.toml`) พร้อม dependency หลัก (pandas, numpy, ta-lib, ccxt, FastAPI)
- [x] T003 Bootstrap โครงการ Cloudflare Workers/D1/KV (`services/cloudflare_api/wrangler.toml`, `services/cloudflare_api/src/index.ts`) พร้อมสิทธิ์เข้าถึง D1+KV
- [x] T004 เตรียมไฟล์ config รวม (`libs/common/config/schema.py`) เพื่อแชร์ schema ระหว่าง service และกำหนดค่า default (1% cap, breaker)
- [x] T005 สร้างเครื่องมือ CI เบื้องต้น (`infra/pipelines/github-actions.yml`) เพื่อ lint/test services และ deploy Cloudflare
- [x] T006 เพิ่ม Secrets/Key management doc และสคริปต์โหลด (`infra/secrets/README.md`, `scripts/setup_secrets.sh`) เพื่อรองรับการแยก environment

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: งานหลักที่ต้องเสร็จก่อนเริ่ม User Story ใด ๆ

- [x] T007 พัฒนาโมดูล ingestion สำหรับ Binance candles + CDC snapshot (`services/signal_engine/src/ingestion/binance_feed.py`) รองรับ historical + live พร้อมตรวจ hash/metadata
- [x] T008 สร้าง library ประมวลผล CDC/W/V/Leading signal (`libs/common/cdc_rules/__init__.py`) ให้ deterministic ใช้งานร่วม backtest/live
- [x] T009 ออกแบบ schema Cloudflare D1 สำหรับ TradingConfiguration, OrderHistory, PositionState, PatternClassification (`services/cloudflare_api/migrations/001_init.sql`)
- [x] T010 ตั้งค่า state storage ผ่าน Durable Objects/KV สำหรับ locks และ breaker flag (`services/cloudflare_api/src/state/positionState.ts`)
- [x] T011 พัฒนา risk enforcement service ใน orchestrator (`services/orchestrator/src/risk/risk_guard.py`) บังคับ 1% cap, breaker 3%/5%
- [x] T012 เตรียม observability stack (Prometheus exporters + alert definitions) (`infra/monitoring/prometheus.yml`, `infra/monitoring/alerts.yml`) สำหรับ metrics ตามสเปค
- [x] T013 เขียน backtest harness + dataset config (`tests/backtest/test_cdc_rules.py`, `scripts/replay/run_backtest.py`) รองรับ ≥3 ช่วงตลาด
- [x] T014 ตั้งค่า paper-trade simulation service ที่ใช้ Binance Testnet (`services/orchestrator/src/simulation/paper_trade_runner.py`)
- [x] T015 จัดทำ kill-switch control endpoint skeleton (`services/control_plane/src/routes/kill_switch.py`) พร้อม audit log
- [x] T043 สร้าง feed watchdog + alert เมื่อ websocket/candle feed ขาดหาย (`services/signal_engine/src/ingestion/feed_watchdog.py`) เชื่อมกับ `infra/monitoring/alerts.yml`

---

## Phase 3: User Story 1 - ตั้งค่า CDC Zone Bot (Priority: P1) 🎯 MVP

**Goal**: ผู้ใช้ตั้งค่า per-pair (timeframe, budget ≤1%, toggle W/leading signal, breaker) ได้พร้อม validation

**Independent Test**: เติม config สำหรับคู่ BTC/THB แล้วตรวจว่าถูกบันทึกใน D1 + sync สู่ orchestrator โดยไม่ยิงคำสั่ง

### Implementation

- [x] T016 [US1] สร้าง REST API สำหรับ CRUD TradingConfiguration (`services/control_plane/src/routes/config.py`)
- [x] T017 [US1] พัฒนา validation layer ที่ enforce 1% cap/breaker (`services/control_plane/src/validators/config_validator.py`)
- [x] T018 [P] [US1] เชื่อม API เข้ากับ Cloudflare D1 (ผ่าน worker endpoint) (`services/control_plane/src/clients/cloudflare_config_client.py`)
- [x] T019 [US1] อัปเดต orchestrator ให้ subscribe การเปลี่ยน config ผ่าน queue/Webhook (`services/orchestrator/src/config/config_sync.py`)
- [x] T020 [US1] สร้าง CLI/quickstart สำหรับตั้งค่าเบื้องต้น (`scripts/quickstart/config_wizard.py`)

---

## Phase 4: User Story 2 - ตรวจสัญญาณและอนุมัติคำสั่ง (Priority: P1)

**Goal**: แดชบอร์ดและ engine ตัดสินใจจาก CDC สี + แดงนำหน้า MTF + สัญญาณนำหน้า + pattern และรู้สถานะถือ/ว่าง

**Independent Test**: Feed ชุดข้อมูลย้อนหลังที่มีลำดับ แดง→W→เขียว แล้วตรวจว่าแดชบอร์ดไฮไลต์ครบ 4 กฎ เปิดปุ่ม “วางออเดอร์” เฉพาะเมื่อ state ว่าง

### Implementation

- [x] T021 [US2] พัฒนาโมดูล multi-timeframe evaluator (`services/signal_engine/src/rules/leading_red.py`) ใช้พารามิเตอร์ lead_red_min/max
- [x] T022 [US2] พัฒนา momentum flip + higher-low detector (`services/signal_engine/src/rules/leading_signal.py`) พร้อม config
- [x] T023 [US2] พัฒนา pattern classifier W/V/NONE (`services/signal_engine/src/rules/pattern_classifier.py`)
- [x] T024 [US2] รวม rule engine เพื่อให้ Boolean pass/fail + บันทึกลง IndicatorSnapshot (`services/signal_engine/src/pipeline/evaluate_rules.py`)
- [x] T025 [US2] อัปเดต PositionState manager ให้ติดตามถือ/ว่าง + จุดตัดล่าสุด (`services/orchestrator/src/state/position_state_store.py`)
- [x] T026 [US2] พัฒนาแดชบอร์ด/หน้า console แสดง rule status + state (`services/control_plane/src/ui/dashboard.py`)
- [x] T027 [US2] เพิ่ม alert/notification เมื่อ Week เปลี่ยนแดงหรือ rule fail (`services/control_plane/src/alerting/rule_alerts.py`)

---

## Phase 5: User Story 3 - ส่งคำสั่ง BinanceTH แบบปลอดภัย (Priority: P2)

**Goal**: สร้าง/ส่ง order plan ≤1%, รองรับ split order, stop-loss/take-profit อิง CDC, structural SL option, และจัดการ error Binance

**Independent Test**: ใช้ Binance Testnet จำลองเมื่อ rule ผ่านครบและตรวจว่ามี order plan, stop-loss, logs ครบ พร้อม retry/alert เมื่อ API error

### Implementation

- [x] T028 [US3] พัฒนา order planner (`services/orchestrator/src/orders/order_planner.py`) คำนวณจำนวนซื้อ, TP/SL, split plan
- [x] T029 [US3] สร้าง structural SL manager (optional) (`services/orchestrator/src/risk/structural_sl.py`)
- [x] T030 [US3] เชื่อม ccxt/BinanceTH client และ queue execution (`services/orchestrator/src/execution/binance_client.py`)
- [x] T031 [US3] จัดการ retry policy + error handling (`services/orchestrator/src/execution/retry_policy.py`)
- [x] T032 [US3] บันทึก order detail + pass/fail rule ลง D1 (`services/cloudflare_api/src/handlers/order_history.ts`)
- [x] T033 [US3] เพิ่ม alert เมื่อ breaker/SL ทำงาน (`services/control_plane/src/alerting/risk_alerts.py`)
- [x] T044 [US3] พัฒนา order gating service ตรวจ Boolean rule ครบก่อนเรียก order planner (`services/orchestrator/src/orders/order_gate.py`)
- [x] T045 [US3] เพิ่ม integration test ยืนยันว่ากฎไม่ครบแล้วบล็อกคำสั่ง (`tests/integration/test_order_gating.py`)
- [x] T046 [US3] จัดการ partial fills และอัปเดต PositionState/Exposure (`services/orchestrator/src/execution/partial_fill_handler.py`)
- [x] T047 [US3] เพิ่ม exposure ledger รวมทุกคู่เพื่อตรวจไม่ให้เกินทุนรวม (`services/orchestrator/src/risk/exposure_ledger.py`)

---

## Phase 6: User Story 4 - วิเคราะห์ผลและปรับแต่ง (Priority: P3)

**Goal**: รายงาน/แดชบอร์ดหลังเทรด แสดงกฎที่ผ่าน, เวลา buy/sell, PnL, ธงเตือน และ export CSV/PDF

**Independent Test**: หลังเทรดจำลอง 10 ดีล ตรวจว่า report UI/CSV มีข้อมูล pass/fail กฎ, เวลาซื้อ/ขาย, PnL และเตือนคู่ที่ขาด W

### Implementation

- [x] T034 [US4] สร้างรายงาน aggregator ดึงข้อมูลจาก OrderHistoryDB (`services/control_plane/src/reports/order_report_service.py`)
- [x] T035 [US4] พัฒนา UI/endpoint สำหรับกรองดีลและแสดงธงเตือน (`services/control_plane/src/ui/report_views.py`)
- [x] T036 [P] [US4] สร้าง CSV/PDF exporter (`services/control_plane/src/reports/exporter.py`)
- [x] T037 [US4] เพิ่ม logic วิเคราะห์กฎที่ผิด + ข้อเสนอแนะปิดออโต้ (`services/control_plane/src/reports/rule_audit.py`)

---

## Phase N: Polish & Cross-Cutting Concerns

- [x] T038 [P] เพิ่มเอกสาร quickstart/runbook สำหรับเปิด/ปิดบอท, ดูแดชบอร์ด, ใช้ kill switch (`specs/001-cdc-zone-bot/quickstart.md`)
- [x] T039 ทำ security review (secrets rotation, least privilege) (`infra/security/review.md`)
- [x] T040 [P] Refactor/optimize performance ของ signal engine (vectorized calc) (`services/signal_engine/src/pipeline/optimize.py`)
- [x] T041 เพิ่ม integration tests ครอบคลุม flow เต็ม (ingest → rule → order → log) (`tests/integration/test_end_to_end.py`)
- [x] T042 วาง procedure สำหรับ circuit breaker/incident response และซ้อม drill (`docs/runbooks/breaker_playbook.md`)
- [x] T048 [P] บันทึก metric เวลา/ความสำเร็จการตั้งค่า config (รองรับ SC-001) (`services/control_plane/src/telemetry/config_metrics.py`)
- [x] T049 [P] บันทึกอัตราการ block สัญญาณ/false signal (รองรับ SC-002/SC-003) (`services/control_plane/src/telemetry/rule_metrics.py`)
- [x] T050 สร้างรายงาน success criteria dashboard ที่รวมเวลาตั้งค่า, บล็อกสัญญาณ, SLA รายงาน (รองรับ SC-004) (`services/control_plane/src/reports/success_dashboard.py`)

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1) → Foundations (Phase 2) → US1 → US2 → US3 → US4 → Polish
- US1 ต้องเสร็จเพื่อให้ config/state พร้อมก่อน evaluate signals
- US2 ต้องเสร็จก่อนส่ง order (US3)
- US3 ต้องเสร็จก่อนสร้างรายงานเต็ม (US4)

### User Story Dependencies

- **US1 (P1)**: ไม่มี dependency ชี้ตรงหลัง foundational
- **US2 (P1)**: พึ่ง config/state จาก US1 และ rule libs จาก foundational
- **US3 (P2)**: พึ่ง US1+US2 เนื่องจากต้องการ config + signals
- **US4 (P3)**: พึ่ง order history จาก US3

### Within Each User Story

- ทำโมดูล rule/logic → integrate → UI/alert (ตามลำดับที่ให้) เพื่อให้ทดสอบได้อิสระ

### Parallel Opportunities

- [P] งานใน Phase 1 (T018 เป็นต้น) สามารถทำคู่กันเพราะอยู่คนละไฟล์
- ใน US1, การเชื่อม API กับ D1 (T018) ทำคู่กับ config sync (T019)
- ใน US4, exporter (T036) ทำคู่กับ rule audit (T037)

---

## Parallel Example: User Story 2

```bash
# เริ่มทำ rule modules พร้อมกัน
Task: "T021 [US2] พัฒนา leading_red"
Task: "T022 [US2] พัฒนา leading_signal"
Task: "T023 [US2] พัฒนา pattern classifier"
```

---

## Implementation Strategy

### MVP (US1 เท่านั้น)

1. จบ Setup + Foundational
2. ทำ US1 เพื่อให้ config-ready + validation
3. ใช้ manual monitoring เปิดบอทแบบ semi-auto (ไม่มี order อัตโนมัติ) เพื่อเก็บ feedback

### Incremental Delivery

1. เพิ่ม US2 เพื่อสร้างสัญญาณ + dashboard
2. ขยายสู่ US3 เพื่อส่งออเดอร์ automated พร้อม risk guard
3. เสริม US4 เพื่อรายงาน/ปรับแต่ง และ Polish สำหรับ runbook + security
