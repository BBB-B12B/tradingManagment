"""HTML renderer for Bot Runner UI."""

from __future__ import annotations

from typing import List


def render_bot_runner(pairs: List[str]) -> str:
    if not pairs:
        return """
        <div class="card">
          <h2>🚀 Run Bot</h2>
          <p>ยังไม่มี Config ให้รันบอท กรุณาเพิ่มคู่เทรดในหน้า Config ก่อน</p>
        </div>
        """

    options = "".join(f'<option value="{pair}">{pair}</option>' for pair in pairs)
    style = """
      .bot-container { display: flex; flex-direction: column; gap: 0.9rem; }
      .card { background: #fff; border-radius: 12px; box-shadow: 0 8px 20px rgba(15,23,42,0.06); padding: 1rem 1.1rem; }
      .card h2 { margin-top: 0; margin-bottom: 0.6rem; display: flex; align-items: center; gap: 0.4rem; font-size: 1.3rem; }
      .controls { display: flex; flex-wrap: wrap; gap: 0.7rem 1rem; align-items: flex-end; }
      .form-field { display: flex; flex-direction: column; gap: 0.3rem; min-width: 180px; }
      .form-field label { font-weight: 600; color: #0f172a; font-size: 0.95rem; }
      .form-field input, .form-field select { padding: 0.55rem 0.65rem; border: 1px solid #d5dbe3; border-radius: 8px; background: #f8fafc; font-size: 0.95rem; }
      .btn-primary { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; border: none; border-radius: 8px; padding: 0.7rem 1.2rem; cursor: pointer; font-weight: 700; white-space: nowrap; font-size: 0.95rem; }
      .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
      .btn-secondary { background: #f1f5f9; color: #0f172a; border: 1px solid #cbd5e1; border-radius: 8px; padding: 0.7rem 1.1rem; cursor: pointer; font-weight: 600; }
      .status { font-weight: 600; }
      .log { background: #0f172a; color: #e2e8f0; padding: 0.75rem; border-radius: 10px; font-family: "IBM Plex Mono", Menlo, monospace; font-size: 0.9rem; max-height: 320px; overflow: auto; white-space: pre-wrap; }
      .modal-backdrop { position: fixed; inset: 0; background: rgba(15,23,42,0.55); display: none; align-items: center; justify-content: center; z-index: 9999; }
      .modal { background: #fff; padding: 1.2rem 1.4rem; border-radius: 12px; width: 480px; max-width: 95%; box-shadow: 0 20px 60px rgba(0,0,0,0.15); }
      .modal h3 { margin-top: 0; margin-bottom: 0.6rem; }
      .modal-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 0.8rem; }
      .modal-grid label { display: flex; flex-direction: column; gap: 0.3rem; font-weight: 600; color: #0f172a; }
      .modal-grid input, .modal-grid select { padding: 0.5rem 0.65rem; border: 1px solid #d5dbe3; border-radius: 8px; background: #f8fafc; font-size: 0.95rem; }
      .modal-actions { display: flex; gap: 0.6rem; margin-top: 0.8rem; justify-content: flex-end; }
      .table-card { background: #fff; border-radius: 12px; box-shadow: 0 8px 20px rgba(15,23,42,0.06); padding: 1rem 1.1rem; }
      .table-wrapper { width: 100%; overflow-x: auto; }
      table { width: 100%; border-collapse: collapse; }
      th, td { padding: 0.55rem 0.4rem; border-bottom: 1px solid #e5e7eb; text-align: left; font-size: 0.92rem; }
      th { background: #f8fafc; font-weight: 700; color: #0f172a; }
      .badge { display: inline-flex; align-items: center; gap: 0.25rem; padding: 0.15rem 0.55rem; border-radius: 999px; font-size: 0.82rem; font-weight: 700; }
      .badge-open { background: #fff3cd; color: #92400e; }
      .badge-filled { background: #ecfdf3; color: #166534; }
      .badge-canceled { background: #fef2f2; color: #b91c1c; }
    """

    return f"""
    <style>{style}</style>
    <div class="bot-container">
      <div class="card">
        <h2>🚀 Run Bot</h2>
        <p>รันบอทแบบ realtime: ใช้ logic เดียวกับ backtest แต่ประเมินสัญญาณจากข้อมูลปัจจุบัน (ไม่ไล่ย้อนหลัง) แล้วบันทึก ENTRY/EXIT ลง D1 ผ่าน worker</p>
        <form id="bot-form" class="controls">
          <div class="form-field">
            <label for="pair">Pair</label>
            <select id="pair" name="pair">{options}</select>
          </div>
          <div class="form-field">
            <label for="limit">จำนวนแท่งที่ใช้วิเคราะห์</label>
            <input id="limit" name="limit" type="number" value="240" min="50" max="1000" />
          </div>
          <div class="form-field">
            <label for="capital">เงินต้น (หน่วย quote)</label>
            <input id="capital" name="capital" type="number" value="10000" min="0" step="1" />
          </div>
          <button class="btn-primary" type="submit" id="run-btn">▶️ Run Bot</button>
          <button class="btn-secondary" type="button" id="force-order-btn">⚡ Force Order</button>
          <span id="status" class="status"></span>
        </form>
      </div>
      <div id="force-modal" class="modal-backdrop">
        <div class="modal">
          <h3>⚡ สร้างคำสั่ง Force Order</h3>
          <div class="modal-grid">
            <label>Pair
              <select id="force-pair">{options}</select>
            </label>
            <label>Side
              <select id="force-side">
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </label>
            <label>Type
              <select id="force-type">
                <option value="market">Market</option>
                <option value="limit">Limit</option>
              </select>
            </label>
            <label>Amount
              <input id="force-amount" type="number" step="0.00001" value="0.00008" />
            </label>
            <label id="price-wrapper">Price (Market จะใช้ราคาตลาด)
              <input id="force-price" type="number" step="0.01" placeholder="กำลังโหลด..." />
            </label>
          </div>
          <div class="modal-actions">
            <button class="btn-primary" type="button" id="force-submit">ส่งคำสั่ง</button>
            <button class="btn-secondary" type="button" id="force-cancel">ยกเลิก</button>
          </div>
          <div id="force-status" class="status" style="margin-top:0.4rem;"></div>
        </div>
      </div>
      <div class="card">
        <h2>📜 Log</h2>
        <div id="log" class="log">ยังไม่มีการรัน</div>
      </div>
      <div class="table-card">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:0.5rem;">
          <h2 style="margin:0;">📦 Order Log (D1)</h2>
          <div style="display:flex; gap:0.5rem; align-items:center;">
            <button class="btn-secondary" type="button" id="refresh-orders">🔄 Refresh</button>
            <span id="orders-status" class="status"></span>
          </div>
        </div>
        <div class="table-wrapper">
          <table id="orders-table">
            <thead>
              <tr><th>เวลา</th><th>Pair</th><th>Type</th><th>Side</th><th>Qty</th><th>ราคา</th><th>สถานะ</th><th>Order ID</th></tr>
            </thead>
            <tbody id="orders-body"><tr><td colspan="8" style="text-align:center; padding:0.6rem;">ยังไม่มีข้อมูล</td></tr></tbody>
          </table>
        </div>
      </div>
    </div>
    <script>
      const form = document.getElementById("bot-form");
      const statusEl = document.getElementById("status");
      const logEl = document.getElementById("log");
      const runBtn = document.getElementById("run-btn");
      const forceBtn = document.getElementById("force-order-btn");
      const modal = document.getElementById("force-modal");
      const forceSubmit = document.getElementById("force-submit");
      const forceCancel = document.getElementById("force-cancel");
      const forceStatus = document.getElementById("force-status");
      const forceType = document.getElementById("force-type");
      const priceWrapper = document.getElementById("price-wrapper");
      const priceInput = document.getElementById("force-price");
      const refreshOrdersBtn = document.getElementById("refresh-orders");
      const ordersBody = document.getElementById("orders-body");
      const ordersStatus = document.getElementById("orders-status");

      function appendLog(text) {{
        const timestamp = new Date().toLocaleTimeString();
        logEl.textContent = `[${{timestamp}}] ${{text}}\\n` + logEl.textContent;
      }}

      form.addEventListener("submit", async (e) => {{
        e.preventDefault();
        const pair = document.getElementById("pair").value;
        const limit = parseInt(document.getElementById("limit").value, 10);
        const capital = parseFloat(document.getElementById("capital").value);
        statusEl.textContent = "⏳ Running bot...";
        statusEl.style.color = "#0f172a";
        runBtn.disabled = true;
        appendLog(`เริ่มรันบอทสำหรับ ${{pair}} (limit=${{limit}}, capital=${{capital}})`);
        try {{
          const resp = await fetch("/bot/run-live", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ pair, limit, initial_capital: capital }})
          }});
          const data = await resp.json();
          if (!resp.ok) {{
            const detail = data?.detail ?? data;
            const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
            throw new Error(msg);
          }}
          const mode = data.mode || "ENTRY/EXIT";
          statusEl.textContent = `✅ สำเร็จ (${{mode}}) orders=${{data.orders_logged}}`;
          statusEl.style.color = "#166534";
          appendLog(`สำเร็จ (${{mode}}) orders=${{data.orders_logged}} balance=${{JSON.stringify(data.balance || {{}})}}`);
        }} catch (err) {{
          statusEl.textContent = "💥 " + err.message;
          statusEl.style.color = "#b91c1c";
          appendLog("ล้มเหลว: " + err.message);
        }} finally {{
          runBtn.disabled = false;
        }}
      }});

      function badge(status) {{
        const s = (status || "").toUpperCase();
        if (s === "FILLED") return `<span class="badge badge-filled">FILLED</span>`;
        if (s === "CANCELED") return `<span class="badge badge-canceled">CANCELED</span>`;
        if (s === "PARTIALLY_FILLED") return `<span class="badge badge-open">PARTIAL</span>`;
        return `<span class="badge badge-open">${{s || 'OPEN'}}</span>`;
      }}

      let lastOrdersKey = "";
      let lastSyncAt = 0;

      function computeKey(orders) {{
        return JSON.stringify(
          (orders || []).map(o => [o.order_id, o.status, o.filled_qty, o.avg_price, o.created_at])
        );
      }}

      async function refreshOrders({{ forceSync = false }} = {{}}, fromTimer = false) {{
        ordersStatus.textContent = "⏳ โหลด...";
        ordersStatus.style.color = "#0f172a";
        try {{
          const now = Date.now();
          if (forceSync || now - lastSyncAt > 5 * 60 * 1000) {{
            await fetch("/orders/sync", {{ method: "POST" }});
            lastSyncAt = now;
          }}
          const resp = await fetch("/orders/all");
          const data = await resp.json();
          const orders = data.orders || [];
          const key = computeKey(orders);
          if (key === lastOrdersKey && fromTimer) {{
            ordersStatus.textContent = `✅ ไม่มีการเปลี่ยนแปลง (${{orders.length}} รายการ)`;
            ordersStatus.style.color = "#166534";
            return;
          }}
          lastOrdersKey = key;
          const rows = orders.map(o => {{
            return `<tr>
              <td>${{o.created_at || ''}}</td>
              <td>${{o.pair || '-'}} </td>
              <td>${{o.order_type || '-'}} </td>
              <td>${{o.side || '-'}} </td>
              <td>${{o.requested_qty || '-'}} </td>
              <td>${{o.avg_price != null ? o.avg_price : '-'}} </td>
              <td>${{badge(o.status)}}</td>
              <td>${{o.order_id || '-'}} </td>
            </tr>`;
          }});
          ordersBody.innerHTML = rows.length ? rows.join("") : '<tr><td colspan="8" style="text-align:center; padding:0.6rem;">ไม่มีรายการ</td></tr>';
          const ts = new Date().toLocaleTimeString();
          ordersStatus.textContent = `✅ อัปเดตแล้ว (${{orders.length}} รายการ) ${{ts}}`;
          ordersStatus.style.color = "#166534";
        }} catch (err) {{
          ordersStatus.textContent = "💥 " + err.message;
          ordersStatus.style.color = "#b91c1c";
        }}
      }}

      refreshOrdersBtn.addEventListener("click", () => refreshOrders({{ forceSync: true }}));
      setInterval(() => refreshOrders({{ forceSync: false }}, true), 10000); // check ทุก 10 วิ
      refreshOrders({{ forceSync: true }});

      async function setDefaultPrice() {{
        const pair = document.getElementById("force-pair").value;
        try {{
          const resp = await fetch(`/market/last?pair=${{encodeURIComponent(pair)}}&interval=1h`);
          const data = await resp.json();
          if (resp.ok && data.price != null) {{
            priceInput.value = data.price;
          }}
        }} catch (err) {{
          console.error("Failed to fetch last price", err);
        }}
      }}

      forceBtn.addEventListener("click", () => {{
        modal.style.display = "flex";
        forceStatus.textContent = "";
        setDefaultPrice();
      }});
      forceCancel.addEventListener("click", () => {{
        modal.style.display = "none";
      }});
      document.getElementById("force-pair").addEventListener("change", setDefaultPrice);

      forceSubmit.addEventListener("click", async () => {{
        const pair = document.getElementById("force-pair").value;
        const side = document.getElementById("force-side").value;
        const type = document.getElementById("force-type").value;
        const amount = parseFloat(document.getElementById("force-amount").value);
        const priceVal = document.getElementById("force-price").value;
        const price = priceVal ? parseFloat(priceVal) : undefined;
        forceStatus.textContent = "⏳ ส่งคำสั่ง...";
        forceStatus.style.color = "#0f172a";
        try {{
          const payload = {{ symbol: pair, side, amount, type }};
          if (type === "limit") payload["price"] = price;
          const resp = await fetch("/test/binance-order", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});
          const data = await resp.json();
          if (!resp.ok) {{
            const detail = data?.detail ?? data;
            const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
            throw new Error(msg);
          }}
          forceStatus.textContent = `✅ สำเร็จ: ${{data.symbol}} ${{data.side}} (${{data.order_id}})`;
          forceStatus.style.color = "#166534";
          appendLog(`Force order OK: ${{data.symbol}} ${{data.side}} ${{type}} amount=${{data.amount}} id=${{data.order_id}}`);
          modal.style.display = "none";
        }} catch (err) {{
          forceStatus.textContent = "💥 " + err.message;
          forceStatus.style.color = "#b91c1c";
          appendLog("Force order fail: " + err.message);
        }}
      }});
    </script>
    """


__all__ = ["render_bot_runner"]
