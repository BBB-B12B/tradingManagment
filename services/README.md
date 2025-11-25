# Services Overview

โครงสร้างบริการตามแผน BinanceTH CDC Zone Bot:

- `signal_engine/`: โมดูล ingestion + ประเมินกฎ (CDC, แดงนำหน้า, สัญญาณนำหน้า, pattern)
- `orchestrator/`: บริหารความเสี่ยง, order planner, execution ต่อ BinanceTH, paper trade runner
- `control_plane/`: API/แดชบอร์ดสำหรับ config, approvals, alert/kill switch
- `cloudflare_api/`: Worker/D1/KV/Durable Objects เป็นชั้น persistence/state

ไลบรารีและโฟลเดอร์ที่ใช้ร่วมกัน:

- `libs/common/`: config schema, data model, shared DTOs
- `infra/terraform`: provisioning Cloudflare, monitoring, secrets infra
- `infra/pipelines`: CI/CD scripts (lint/test/deploy)
- `tests/`: unit/integration/backtest + scenarios
- `scripts/replay`: เครื่องมือ replay/backtest
- `docs/runbooks`: runbook/quickstart/incident playbook
