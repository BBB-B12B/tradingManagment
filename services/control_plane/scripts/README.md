# Development Scripts

สคริปต์สำหรับ development และ debugging

---

## 🚀 การเริ่มต้น Development

### วิธีที่ 1: ใช้ `dev-all.sh` (แนะนำ)

สคริปต์นี้จะ:
1. **Kill processes เก่าทั้งหมดก่อนอัตโนมัติ** (ป้องกันการทำงานซ้ำซ้อน)
2. เริ่ม Cloudflare Worker (wrangler dev)
3. รอให้ Worker พร้อม
4. เริ่ม Control Plane (uvicorn)

```bash
cd "/Volumes/BriteBrain/Projects/Trading Tool/TradingTool/services/control_plane"
./scripts/dev-all.sh
```

**หยุดทำงาน**: กด `Ctrl + C` (จะ cleanup processes ทั้งหมดอัตโนมัติ)

**Restart**:
```bash
# วิธีที่ 1: กด Ctrl+C แล้วรันใหม่
./scripts/dev-all.sh

# วิธีที่ 2: Force kill ทุกอย่างก่อน
./scripts/kill-all.sh && ./scripts/dev-all.sh
```

---

## 🛑 Force Kill ทุกอย่าง

หากเกิดปัญหา processes ค้าง ใช้:

```bash
./scripts/kill-all.sh
```

สคริปต์นี้จะ kill:
- Wrangler dev processes
- esbuild processes
- workerd processes
- uvicorn processes (port 5001)
- Processes on port 8787

---

## 📊 ตรวจสอบ Processes ที่ทำงานอยู่

```bash
# ตรวจสอบ Wrangler/esbuild
ps aux | grep -E "(wrangler|esbuild|workerd)" | grep -v grep

# ตรวจสอบ processes บน port 8787
lsof -ti:8787

# ตรวจสอบ processes บน port 5001
lsof -ti:5001
```

---

## ⚙️ Configuration

สามารถปรับ environment variables ได้:

```bash
# เปลี่ยน port ของ Worker
WORKER_PORT=9000 ./scripts/dev-all.sh

# เปลี่ยน port ของ uvicorn
UVICORN_PORT=9001 ./scripts/dev-all.sh

# ปิด --remote flag (ใช้ local mode)
WRANGLER_DEV_FLAGS="" ./scripts/dev-all.sh
```

---

## 🔧 Troubleshooting

### ปัญหา: CPU สูงเกินไป (>100%)

**สาเหตุ**: Wrangler instances ซ้ำซ้อน

**วิธีแก้**:
```bash
./scripts/kill-all.sh
sleep 2
./scripts/dev-all.sh
```

### ปัญหา: Port 8787 หรือ 5001 ถูกใช้แล้ว

**วิธีแก้**:
```bash
# Kill processes บน port เฉพาะ
lsof -ti:8787 | xargs kill -9
lsof -ti:5001 | xargs kill -9
```

### ปัญหา: Worker ไม่ start หรือ hang

**วิธีแก้**:
1. กด `Ctrl + C` เพื่อหยุด
2. รัน `./scripts/kill-all.sh`
3. รัน `./scripts/dev-all.sh` ใหม่

---

## 📝 หมายเหตุ

- **Script จะ cleanup processes อัตโนมัติ** เมื่อกด Ctrl+C
- **ไม่ควร force quit terminal** (กด Cmd+Q) เพราะจะไม่ทำ cleanup
- หาก processes ค้าง ให้ใช้ `./scripts/kill-all.sh` เสมอ

---

## 🎯 Best Practices

1. **ใช้ `dev-all.sh` สำหรับ start** - จะ cleanup processes เก่าอัตโนมัติ
2. **ใช้ Ctrl+C สำหรับ stop** - จะ cleanup ให้เอง
3. **ใช้ `kill-all.sh` เมื่อเกิดปัญหา** - force kill ทุกอย่าง
4. **ตรวจสอบ processes ก่อน restart** - ใช้ `ps aux | grep wrangler`

---

## 🚨 คำเตือน

**อย่าเปิด multiple terminals และรัน `dev-all.sh` หลายครั้ง**
→ จะทำให้มี processes ซ้ำซ้อนและ CPU สูง

**ถ้าต้องการ restart:**
1. กด Ctrl+C ที่ terminal เดิม
2. รัน `./scripts/dev-all.sh` ใหม่
3. หรือใช้ `./scripts/kill-all.sh && ./scripts/dev-all.sh`
