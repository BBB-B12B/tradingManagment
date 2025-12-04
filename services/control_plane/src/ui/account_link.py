"""HTML view for linking Binance TH trading account."""

from __future__ import annotations

from typing import Dict, Union

StatusDict = Dict[str, Union[str, bool]]


def render_account_link(status: StatusDict) -> str:
    """Render a simple guide + status page for connecting BinanceTH keys."""
    connected = status.get("has_key") and status.get("has_secret")
    key_tail = status.get("api_key_tail", "") or ""
    secret_tail = status.get("api_secret_tail", "") or ""
    env_name = status.get("env_name", "dev")
    env_file = status.get("env_file", ".env/.env.dev")
    env_loaded = bool(status.get("env_loaded"))

    style = """
      .account-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; margin-top: 1rem; }
      .card { background: #fff; border-radius: 14px; box-shadow: 0 10px 28px rgba(15,23,42,0.08); padding: 1.2rem 1.3rem; }
      .card h2 { margin-top: 0; display: flex; align-items: center; gap: 0.4rem; font-size: 1.15rem; }
      .pill { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.35rem 0.65rem; border-radius: 999px; font-weight: 700; font-size: 0.9rem; }
      .pill.ready { background: #ecfdf3; color: #166534; border: 1px solid #22c55e; }
      .pill.pending { background: #fef3c7; color: #92400e; border: 1px solid #f59e0b; }
      .list { margin: 0.5rem 0 0 1.1rem; line-height: 1.6; color: #111827; }
      code { background: #0f172a; color: #e2e8f0; padding: 0.15rem 0.25rem; border-radius: 6px; font-size: 0.9rem; }
      .step { margin-bottom: 0.4rem; }
      .muted { color: #6b7280; font-size: 0.92rem; margin-top: 0.2rem; }
      .hl { font-weight: 700; color: #0f172a; }
      .btn { margin-top: 0.8rem; padding: 0.65rem 1rem; background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; border: none; border-radius: 10px; font-weight: 700; cursor: pointer; }
      .btn:disabled { opacity: 0.6; cursor: not-allowed; }
      #test-status { margin-top: 0.4rem; font-weight: 600; }
    """

    status_badge = (
        f'<span class="pill ready">✅ ผูกแล้ว (…{key_tail})</span>'
        if connected
        else '<span class="pill pending">⏳ ยังไม่ได้ผูก</span>'
    )

    key_state = "พบ API Key" if status.get("has_key") else "ไม่พบ API Key"
    secret_state = "พบ API Secret" if status.get("has_secret") else "ไม่พบ API Secret"
    masked_key = f"…{key_tail}" if key_tail else "-"
    masked_secret = f"…{secret_tail}" if secret_tail else "-"
    env_note = "โหลดแล้ว" if env_loaded else "ยังไม่พบไฟล์"

    return f"""
    <style>{style}</style>
    <div>
      <h1>🔑 ผูกบัญชี Binance TH</h1>
      <p>เตรียม API Key/Secret ให้พร้อมสำหรับยิงคำสั่งซื้อขายจาก orchestrator</p>
      <div class="account-grid">
        <div class="card">
          <h2>สถานะการเชื่อมต่อ {status_badge}</h2>
          <div class="step">• {key_state} <span class="muted">(แสดงเฉพาะท้าย): {masked_key}</span></div>
          <div class="step">• {secret_state} <span class="muted">(แสดงเฉพาะท้าย): {masked_secret}</span></div>
          <p class="muted" style="margin-top:0.8rem;">ระบบจะใช้ค่าใน environment variables <code>BINANCE_API_KEY</code> และ <code>BINANCE_API_SECRET</code> เท่านั้น</p>
          <p class="muted" style="margin-top:0.4rem;">Environment: <strong>{env_name}</strong> | ไฟล์: <code>{env_file}</code> ({env_note})</p>
          <button class="btn" id="test-order-btn">🚀 ทดสอบส่งคำสั่ง Testnet (0.0001 BTC/USDT)</button>
          <div id="test-status" class="muted"></div>
        </div>
        <div class="card">
          <h2>ขั้นตอนผูกบัญชี</h2>
          <ol class="list">
            <li class="step"><span class="hl">สร้าง API Key บน Binance TH</span> (Spot เทรดเท่านั้น, ปิดสิทธิ์ถอนเงิน, จำกัด IP ตามเซิร์ฟเวอร์นี้)</li>
            <li class="step"><span class="hl">โหลดไฟล์ secrets</span> ด้วย <code>scripts/setup_secrets.sh {env_name}</code></li>
            <li class="step"><span class="hl">เติมค่า</span> <code>BINANCE_API_KEY</code> / <code>BINANCE_API_SECRET</code> ในไฟล์ <code>{env_file}</code> แล้วรีสตาร์ท service</li>
            <li class="step"><span class="hl">ยืนยันอีกครั้ง</span> เปิดหน้านี้ใหม่ควรเห็นสถานะ “ผูกแล้ว”</li>
          </ol>
        </div>
        <div class="card">
          <h2>ความปลอดภัยที่แนะนำ</h2>
          <ul class="list">
            <li>ใช้ key เฉพาะ Spot Trading; ไม่เปิดสิทธิ์ถอน</li>
            <li>จำกัด IP ตรงกับ orchestrator/worker ที่อนุญาต</li>
            <li>จัดเก็บ secrets ใน Vault/Cloudflare ตาม runbook ไม่ commit ลง repo</li>
            <li>หมุนเวียน key เป็นระยะ และปิด key ทันทีเมื่อสงสัยว่ารั่ว</li>
          </ul>
        </div>
      </div>
    </div>
    <script>
      const testBtn = document.getElementById("test-order-btn");
      const testStatus = document.getElementById("test-status");

      if (testBtn) {{
        testBtn.addEventListener("click", async () => {{
          testBtn.disabled = true;
          testStatus.textContent = "กำลังส่งคำสั่ง testnet...";
          try {{
            const resp = await fetch("/test/binance-order", {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ symbol: "BTC/USDT", side: "buy", amount: 0.0001 }})
            }});
            const data = await resp.json();
            if (!resp.ok) {{
              throw new Error(data.detail || "ส่งคำสั่งไม่สำเร็จ");
            }}
            const tail = (data.order_id || "").slice(-6);
            testStatus.textContent = `✅ สำเร็จ (order ${'{'}tail{'}'} / ${'{'}data.symbol{'}'} ${'{'}data.side{'}'} ${'{'}data.amount{'}'})`;
            testStatus.style.color = "#166534";
          }} catch (err) {{
            testStatus.textContent = "💥 " + err.message;
            testStatus.style.color = "#b91c1c";
          }} finally {{
            testBtn.disabled = false;
          }}
        }});
      }}
    </script>
    """


__all__ = ["render_account_link"]
