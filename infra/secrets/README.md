# Secrets & Key Management

Environment segregation:

- **Research**: local .env stored in 1Password vault `CDC-Research`
- **Simulation**: Binance Testnet keys stored in Cloudflare Secrets manager (`CDC_SIM_BINANCE_KEY`), read-only access for simulation runner
- **Live**: BinanceTH production keys + Cloudflare D1 credentials stored in hardware-backed secret manager (e.g., HashiCorp Vault or AWS Secrets Manager). Access restricted to orchestrator service account via control plane approval.

Workflow:

1. ใช้ `scripts/setup_secrets.sh` เพื่อโหลด secrets ตาม environment (ต้องมีสิทธิ์ก่อน)
2. ห้าม commit ไฟล์ `.env.*`; Git ignore จะป้องกัน
3. ทุกครั้งที่ rotate keys ต้องอัปเดต Vault + Cloudflare secrets และบันทึกใน runbook

Control Plane Approval:

- การเปิดโหมด auto/live ต้องได้รับ 2FA approval และบันทึกลง OrderHistory/ControlPlaneLog

TODO: เติมรายละเอียด Vault endpoint และ mapping ชื่อ secret เมื่อ infrastructure พร้อม
