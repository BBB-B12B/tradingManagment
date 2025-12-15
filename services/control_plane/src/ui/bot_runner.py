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
      .log { background: #0f172a; color: #e2e8f0; padding: 0.75rem; border-radius: 10px; font-family: "IBM Plex Mono", Menlo, monospace; font-size: 0.9rem; height: 280px; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column-reverse; }
      .rule-item { margin: 0.4rem 0; padding: 0.4rem 0.6rem; background: rgba(255,255,255,0.05); border-radius: 6px; border-left: 3px solid #64748b; cursor: pointer; transition: all 0.2s; }
      .rule-item:hover { background: rgba(255,255,255,0.1); }
      .rule-item.passed { border-left-color: #10b981; }
      .rule-item.failed { border-left-color: #ef4444; }
      .rule-header { display: flex; align-items: center; justify-content: space-between; font-weight: 600; }
      .rule-detail { margin-top: 0.3rem; padding-top: 0.3rem; border-top: 1px solid rgba(255,255,255,0.1); font-size: 0.85rem; color: #94a3b8; display: none; }
      .rule-item.expanded .rule-detail { display: block; }
      .rule-item.expanded .toggle-icon { transform: rotate(180deg); }
      .toggle-icon { font-size: 0.8rem; color: #64748b; transition: transform 0.2s; }
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
      <div class="card" style="background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%); border: 2px solid #f59e0b; margin-bottom: 1rem;">
        <h2>🔧 Process Manager</h2>
        <p style="margin-bottom: 0.8rem; color: #92400e;">จัดการ Background Processes ที่กำลังทำงานอยู่</p>
        <div id="process-list">
          <p style="color: #64748b;">⏳ กำลังโหลด...</p>
        </div>
        <button class="btn-secondary" type="button" id="refresh-processes-btn" style="margin-top: 0.5rem;">🔄 Refresh Processes</button>
      </div>
      <div class="card" style="background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%); border: 2px solid #0ea5e9;">
        <h2>🤖 Real-time Auto Trading</h2>
        <p style="margin-bottom: 0.8rem; color: #475569;">ระบบเทรดอัตโนมัติ: ตรวจสอบเงื่อนไข Entry/Exit ทุก 1 นาที และส่ง Order ไปยัง D1 Worker</p>
        <div class="controls" style="margin-bottom: 0.8rem;">
          <div class="form-field">
            <label for="pair">Pair</label>
            <select id="pair" name="pair">{options}</select>
          </div>
          <div class="form-field">
            <label for="interval">Interval (minutes)</label>
            <input id="interval" name="interval" type="number" value="1" min="0.1" max="60" step="0.1" />
          </div>
        </div>
        <div id="scheduler-status-card">
          <p style="color: #64748b;">⏳ กำลังโหลดสถานะ...</p>
        </div>
        <div style="display: flex; gap: 0.7rem; margin-top: 0.8rem;">
          <button class="btn-primary" type="button" id="start-scheduler-btn">▶️ Start Auto Trading</button>
          <button class="btn-secondary" type="button" id="stop-scheduler-btn" style="background: #fef2f2; color: #b91c1c; border-color: #fca5a5;">⏹️ Stop</button>
          <button class="btn-secondary" type="button" id="refresh-scheduler-btn">🔄 Refresh</button>
          <button class="btn-secondary" type="button" id="force-order-btn">⚡ Force Order</button>
        </div>
      </div>
      <div class="card">
        <h2>📜 Trading Log</h2>
        <div id="trading-log" class="log">รอการเริ่มต้น Auto Trading...</div>
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
        <h2>🧩 Rule Check Log</h2>
        <div id="rule-log" class="log">ยังไม่มีการรัน</div>
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
      const logEl = document.getElementById("trading-log");
      const ruleLogEl = document.getElementById("rule-log");
      const forceBtn = document.getElementById("force-order-btn");
      const processListEl = document.getElementById("process-list");
      const refreshProcessesBtn = document.getElementById("refresh-processes-btn");
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
      const seenLogKeys = new Set();

      function appendLog(text) {{
        const timestamp = new Date().toLocaleTimeString();
        logEl.textContent = logEl.textContent + `[${{timestamp}}] ${{text}}\\n`;
        logEl.scrollTop = 0;
      }}

      function appendRuleLog(text) {{
        const timestamp = new Date().toLocaleTimeString();
        const wrapper = document.createElement("div");
        wrapper.style.marginBottom = "0.3rem";
        wrapper.style.color = "#cbd5e1";
        wrapper.innerHTML = `<span style="color: #64748b;">[${{timestamp}}]</span> ${{text}}`;

        // เช็คว่า user กำลัง scroll อยู่หรือไม่
        const isAtBottom = ruleLogEl.scrollTop === 0;

        if (ruleLogEl.firstChild) {{
          ruleLogEl.insertBefore(wrapper, ruleLogEl.firstChild);
        }} else {{
          ruleLogEl.appendChild(wrapper);
        }}

        // Auto-scroll เฉพาะถ้า user อยู่ที่ล่างสุดอยู่แล้ว
        if (isAtBottom) {{
          ruleLogEl.scrollTop = 0;
        }}
      }}

      function appendRuleLogHTML(htmlContent) {{
        const timestamp = new Date().toLocaleTimeString();
        const wrapper = document.createElement("div");
        wrapper.style.marginBottom = "0.5rem";
        wrapper.innerHTML = `<span style="color: #64748b;">[${{timestamp}}]</span> ${{htmlContent}}`;

        // เช็คว่า user กำลัง scroll อยู่หรือไม่
        const isAtBottom = ruleLogEl.scrollTop === 0;

        if (ruleLogEl.firstChild) {{
          ruleLogEl.insertBefore(wrapper, ruleLogEl.firstChild);
        }} else {{
          ruleLogEl.appendChild(wrapper);
        }}

        // Auto-scroll เฉพาะถ้า user อยู่ที่ล่างสุดอยู่แล้ว
        if (isAtBottom) {{
          ruleLogEl.scrollTop = 0;
        }}
      }}

      function formatRuleFlags(rules = {{}}) {{
        const icons = (passed) => passed ? "✅" : "❌";
        const r1 = icons(rules.rule_1_cdc_green) + " 🔵→🟢 CDC Transition";
        const r2 = "ℹ️ 📐 Pattern: " + (rules.rule_2_pattern ? "detected" : "checking");
        return r1 + " | " + r2;
      }}

      function badge(status) {{
        const s = (status || "").toUpperCase();
        if (s === "FILLED") return `<span class="badge badge-filled">FILLED</span>`;
        if (s === "CLOSED") return `<span class="badge badge-filled">CLOSED</span>`;
        if (s === "CANCELED") return `<span class="badge badge-canceled">CANCELED</span>`;
        if (s === "PARTIALLY_FILLED") return `<span class="badge badge-open">PARTIAL</span>`;
        if (s === "PENDING") return `<span class="badge badge-open">PENDING</span>`;
        return `<span class="badge badge-open">${{s || 'UNKNOWN'}}</span>`;
      }}

      const fmtNum = (v, digits = 4) => (v === undefined || v === null ? "-" : Number(v).toFixed(digits));
      const fmtPct = (v) => (v === undefined || v === null ? "-" : `${{v >= 0 ? "+" : ""}}${{v.toFixed(2)}}%`);
      const logKey = (l) => {{
        // สำหรับ position_state ให้ใช้แค่ pair + action (ไม่รวม ts เพื่อไม่ให้ซ้ำทุกวินาที)
        if (l.action === "position_state") {{
          return `${{l.pair}}|position_state`;
        }}
        return [l.ts, l.pair, l.action, l.status, l.reason, l.entry_price, l.exit_price].join("|");
      }};

      let lastOrdersKey = "";
      let lastSyncAt = 0;

      function computeKey(orders) {{
        return JSON.stringify(
          (orders || []).map(o => [o.order_id, o.status, o.filled_qty, o.avg_price, o.created_at])
        );
      }}

      async function refreshOrders({{ forceSync = false }} = {{}}, fromTimer = false) {{
        console.log(`[refreshOrders] Called (forceSync=${{forceSync}}, fromTimer=${{fromTimer}})`);
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
      setInterval(() => refreshOrders({{ forceSync: false }}, true), 60000); // check ทุก 1 นาที
      refreshOrders({{ forceSync: true }});
      // ===========================
      // Scheduler Logs (Rule / Trading)
      // ===========================

      function formatMetadataValue(key, value, ruleName) {{
        // แปลค่า metadata เป็นภาษาไทยที่อ่านง่าย
        if (typeof value === "object" && value !== null) {{
          // W-Shape details - แสดงเป็นกราฟ ASCII Art
          // ตรวจสอบ 2 กรณี: (1) key === "details" หรือ (2) มี field low1, mid_high, low2
          const hasWShapeData = value.low1 !== undefined && value.mid_high !== undefined && value.low2 !== undefined;

          if (hasWShapeData) {{
            const low1 = value.low1 || 0;
            const midHigh = value.mid_high || 0;
            const low2 = value.low2 || 0;
            const leg1Bars = value.leg1_bars || 0;
            const leg2Bars = value.leg2_bars || 0;
            const heightDiffPct = value.height_diff_pct || 0;
            const low2VsLow1Pct = value.low2_vs_low1_pct || 0;

            // คำนวณส่วนสูง (H) - แสดงเป็น %
            const heightPctDisplay = (heightDiffPct * 100);

            // สร้างกราฟแบบ ASCII Art (ใช้ String.raw เพื่อไม่ให้ escape backslash)
            const line1 = `$<span style="color: #f59e0b;">${{midHigh.toFixed(0)}}</span>     (H) ← สูงขึ้นแค่ <span style="color: #ef4444;">${{heightPctDisplay.toFixed(1)}}%</span>`;
            const line2 = `            /   ${{String.fromCharCode(92)}}`; // backslash
            const line3 = `           /     ${{String.fromCharCode(92)}}`;
            const line4 = `          /       ${{String.fromCharCode(92)}}`;
            const line5 = `$<span style="color: #22c55e;">${{low1.toFixed(0)}}</span> (L1)   (L2) $<span style="color: #22c55e;">${{low2.toFixed(0)}}</span>`;

            const graph = `
<pre style="font-family: 'IBM Plex Mono', Menlo, monospace; line-height: 1.6; color: #cbd5e1; margin: 0.5rem 0;">${{line1}}
${{line2}}
${{line3}}
${{line4}}
${{line5}}</pre>
            `.trim();

            const low2VsLow1PctDisplay = (low2VsLow1Pct * 100);
            const details = `
<div style="margin-top: 0.3rem; font-size: 0.85rem;">
  • <strong>รูปแบบ:</strong> W
  • <strong>ขาที่ 1:</strong> ${{leg1Bars}} แท่ง
  • <strong>ขาที่ 2:</strong> ${{leg2Bars}} แท่ง
  • <strong>จุดต่ำ 2 vs จุดต่ำ 1:</strong> <span style="color: ${{low2VsLow1PctDisplay >= 0 ? '#22c55e' : '#ef4444'}};">${{low2VsLow1PctDisplay >= 0 ? '+' : ''}}${{low2VsLow1PctDisplay.toFixed(2)}}%</span>
</div>
            `.trim();

            return graph + details;
          }}
          // Transition details
          if ((key === "htf_transition" || key === "ltf_transition") && value.found) {{
            const prevColor = value.prev_color === "blue" ? "🔵 น้ำเงิน" : value.prev_color === "lblue" ? "🔵 น้ำเงินอ่อน" : value.prev_color;
            const currColor = value.curr_color === "green" ? "🟢 เขียว" : value.curr_color;
            const barsAgo = value.bars_ago || 0;
            return `✅ พบการเปลี่ยน: ${{prevColor}} → ${{currColor}} (${{barsAgo}} แท่งก่อน)`;
          }}
          if ((key === "htf_transition" || key === "ltf_transition") && value === null) {{
            return "❌ ไม่พบการเปลี่ยนสี";
          }}
          return JSON.stringify(value);
        }}

        // แปลชื่อ field และค่า
        const translations = {{
          "ltf_color": "LTF สี",
          "htf_color": "HTF สี",
          "ltf_current_color": "LTF สีปัจจุบัน",
          "htf_current_color": "HTF สีปัจจุบัน",
          "htf_transition": "Day TF การเปลี่ยน",
          "ltf_transition": "Hour TF การเปลี่ยน",
          "momentum_passed": "Momentum ผ่าน",
          "higher_low_passed": "Higher Low ผ่าน",
          "momentum_reason": "เหตุผล Momentum",
          "higher_low_reason": "เหตุผล Higher Low",
          "pattern": "รูปแบบ",
          "green": "เขียว",
          "red": "แดง",
          "orange": "ส้ม",
          "blue": "น้ำเงิน",
          "lblue": "น้ำเงินอ่อน",
          "true": "✅ ใช่",
          "false": "❌ ไม่ใช่",
        }};

        const displayKey = translations[key] || key;
        let displayValue = String(value);

        // แปลค่า boolean
        if (value === true) displayValue = "✅ ใช่";
        if (value === false) displayValue = "❌ ไม่ใช่";

        // แปลสี
        if (displayValue === "green") displayValue = "🟢 เขียว";
        if (displayValue === "red") displayValue = "🔴 แดง";
        if (displayValue === "orange") displayValue = "🟠 ส้ม";
        if (displayValue === "blue") displayValue = "🔵 น้ำเงิน";
        if (displayValue === "lblue") displayValue = "🔵 น้ำเงินอ่อน";

        // แปลข้อความเฉพาะ
        if (displayValue.includes("No momentum flip")) {{
          displayValue = "❌ ไม่มีการกลับตัวของ Momentum (MACD ยังไม่เปลี่ยนจากลบ→บวก)";
        }}
        if (displayValue.includes("Higher low found:")) {{
          displayValue = displayValue.replace("Higher low found:", "✅ พบ Higher Low:");
        }}

        return `<strong>${{displayKey}}:</strong> ${{displayValue}}`;
      }}

      function createExpandableRuleItem(ruleName, ruleData, icon) {{
        const passed = ruleData.passed;
        const reason = ruleData.reason || "";
        const metadata = ruleData.metadata || {{}};
        const statusClass = passed ? "passed" : "failed";
        const statusIcon = passed ? "✅" : "❌";

        const itemId = `rule-${{Date.now()}}-${{Math.random()}}`;

        // แปล reason เป็นภาษาไทย
        let reasonThai = reason;
        const reasonMap = {{
          "HTF has no BLUE→GREEN transition in last 5 bars": "❌ Day TF ไม่มีการเปลี่ยนจาก น้ำเงิน→เขียว ใน 5 แท่งล่าสุด",
          "LTF has no BLUE→GREEN transition in last 5 bars": "❌ Hour TF ไม่มีการเปลี่ยนจาก น้ำเงิน→เขียว ใน 5 แท่งล่าสุด",
          "Both HTF and LTF have BLUE→GREEN transition": "✅ ทั้ง Day และ Hour TF มีการเปลี่ยนจาก น้ำเงิน→เขียว",
          "LTF CDC is not GREEN": "LTF CDC ไม่เป็นสีเขียว",
          "HTF CDC is not GREEN": "HTF CDC ไม่เป็นสีเขียว",
          "Both LTF and HTF are GREEN": "ทั้ง LTF และ HTF เป็นสีเขียว",
          "HTF is not GREEN": "HTF ไม่เป็นสีเขียว",
          "Leading signal incomplete: missing momentum flip": "สัญญาณนำไม่ครบ: ขาด Momentum Flip (MACD ยังไม่กลับจากลบเป็นบวก)",
          "W-shape detected - valid base building": "✅ พบรูป W-Shape (ฐานรองรับที่ถูกต้อง)",
        }};
        reasonThai = reasonMap[reason] || reason;

        // Format metadata สำหรับแสดงรายละเอียด
        let detailHTML = `<div><strong>📌 เหตุผล:</strong> ${{reasonThai}}</div>`;
        if (Object.keys(metadata).length > 0) {{
          detailHTML += `<div style="margin-top:0.5rem;"><strong>📊 รายละเอียด:</strong></div>`;
          for (const [key, value] of Object.entries(metadata)) {{
            const formattedValue = formatMetadataValue(key, value, ruleName);
            detailHTML += `<div style="margin-left:1rem; margin-top:0.2rem;">• ${{formattedValue}}</div>`;
          }}
        }}

        return `
          <div class="rule-item ${{statusClass}}" id="${{itemId}}" onclick="toggleRuleDetail('${{itemId}}')">
            <div class="rule-header">
              <span>${{statusIcon}} ${{icon}} ${{ruleName}}</span>
              <span class="toggle-icon">▼</span>
            </div>
            <div class="rule-detail">
              ${{detailHTML}}
            </div>
          </div>
        `;
      }}

      function toggleRuleDetail(itemId) {{
        const element = document.getElementById(itemId);
        if (element) {{
          element.classList.toggle("expanded");
        }}
      }}

      function renderLogEntry(log) {{
        const pair = log.pair || "-";
        const action = (log.action || "").toLowerCase();
        const status = log.status || "";
        const reason = log.reason || "";
        const rules = log.rules || {{}};
        const rulesDetail = log.rules_detail || null;
        const position = log.position || {{}};
        const posStatus = (position.status || "FLAT").toUpperCase();

        // Scheduler Start Log
        if (action === "scheduler_start") {{
          const intervalMin = log.interval_minutes || 1;
          appendLog(`🚀 Trading Scheduler เริ่มทำงาน - ตรวจสอบทุก ${{intervalMin}} นาที`);
          appendLog(`📊 คู่เงิน: ${{pair}}`);
          return;
        }}

        // Position State Log
        if (action === "position_state") {{
          const qty = position.qty || 0;
          const binanceBalance = log.binance_balance || 0;

          // ใช้ qty เป็นตัวตัดสินว่าเป็น Entry หรือ Exit mode (ไม่ใช่ posStatus)
          // ถือว่า qty < 0.000001 เป็น dust และนับเป็น FLAT
          const MIN_QTY = 0.000001;
          const hasPosition = qty >= MIN_QTY;
          const actualStatus = hasPosition ? "LONG" : "FLAT";
          const mode = hasPosition ? "EXIT" : "ENTRY";
          const modeIcon = hasPosition ? "🔓" : "🔍";

          // สร้าง HTML แบบสวยงามเหมือน CLI
          const html = `
            <div style="background: rgba(14, 165, 233, 0.1); padding: 0.6rem; border-radius: 8px; border-left: 3px solid #0ea5e9;">
              <div style="font-weight: 700; color: #0ea5e9; margin-bottom: 0.4rem;">
                ${{modeIcon}} [${{pair}}] สถานะ: ${{actualStatus}} | โหมด: ${{mode}}
              </div>
              <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.3rem; font-size: 0.9rem;">
                <div>💰 <strong>Binance Balance:</strong> ${{binanceBalance.toFixed(8)}} BTC</div>
                <div>🔒 <strong>Position:</strong> ${{qty < MIN_QTY ? "0.00000000" : qty.toFixed(8)}} BTC</div>
              </div>
            </div>
          `;

          appendRuleLogHTML(html);
          return;
        }}

        if (action === "buy" || status === "entry_signal_detected") {{
          // สร้างข้อความ log พร้อม Binance Order Info
          let logMsg = "✅ เข้า " + pair + " @ " + fmtNum(log.entry_price, 2) + " | SL " + fmtNum(log.sl_price, 2) + " | Qty " + fmtNum(log.qty, 6);

          // เพิ่มข้อมูล Binance Order ID และ Status ถ้ามี
          if (log.binance_order_id) {{
            logMsg += " | 🔗 Order#" + log.binance_order_id;
          }}
          if (log.binance_status) {{
            const statusBadge = log.binance_status === "FILLED"
              ? '<span style="color: #22c55e; font-weight: 700;">✅ FILLED</span>'
              : '<span style="color: #f59e0b; font-weight: 700;">⏳ ' + log.binance_status + '</span>';
            logMsg += " | " + statusBadge;
          }}
          if (log.filled_qty && log.filled_qty !== log.qty) {{
            logMsg += " (Filled: " + fmtNum(log.filled_qty, 6) + ")";
          }}
          if (log.avg_price && log.avg_price !== log.entry_price) {{
            logMsg += " (Avg: " + fmtNum(log.avg_price, 2) + ")";
          }}

          appendLog(logMsg);

          if (rulesDetail) {{
            let html = `<div style="font-weight:700;">📈 ${{pair}} LONG - Entry Signal</div>`;
            html += createExpandableRuleItem("🔵→🟢 CDC Transition", rulesDetail.rule_1_cdc_green, "🔵");
            html += createExpandableRuleItem("ℹ️ 📐 Pattern (Info)", rulesDetail.rule_4_pattern, "📐");
            appendRuleLogHTML(html);
          }} else {{
            appendRuleLog("📈 " + pair + " LONG | " + formatRuleFlags(rules));
          }}
          return;
        }}
        if (action === "sell" || status === "exit_signal_detected") {{
          // สร้างข้อความ log พร้อม Binance Order Info
          let logMsg = "❌ ออก " + pair + " @ " + fmtNum(log.exit_price, 2) + " | เหตุผล " + (reason || "-") + " | PnL " + fmtPct(log.pnl_pct || 0);

          // เพิ่มข้อมูล Binance Order ID และ Status ถ้ามี
          if (log.binance_order_id) {{
            logMsg += " | 🔗 Order#" + log.binance_order_id;
          }}
          if (log.binance_status) {{
            const statusBadge = log.binance_status === "FILLED"
              ? '<span style="color: #22c55e; font-weight: 700;">✅ FILLED</span>'
              : '<span style="color: #f59e0b; font-weight: 700;">⏳ ' + log.binance_status + '</span>';
            logMsg += " | " + statusBadge;
          }}
          if (log.filled_qty) {{
            logMsg += " (Filled: " + fmtNum(log.filled_qty, 6) + ")";
          }}
          if (log.avg_price && log.avg_price !== log.exit_price) {{
            logMsg += " (Avg: " + fmtNum(log.avg_price, 2) + ")";
          }}

          appendLog(logMsg);
          return;
        }}
        if (action === "error" || status === "error") {{
          appendRuleLog("💥 " + pair + " error: " + (log.error || "unknown"));
          return;
        }}

        // Exit Mode: แสดง Exit Checks
        if (status === "monitoring_exit" && log.exit_checks) {{
          const exitChecks = log.exit_checks;
          const currentPrice = log.current_price || 0;

          let html = `<div style="font-weight:700;">⏳ ${{pair}} ถือ LONG - กำลังตรวจสอบเงื่อนไข Exit</div>`;

          // Create expandable items for each exit check
          html += `
            <div class="rule-item" onclick="this.classList.toggle('expanded')">
              <div class="rule-header">
                <span>📊 Exit Checks (4 เงื่อนไข)</span>
                <span class="toggle-icon">▼</span>
              </div>
              <div class="rule-detail">
                <div style="margin: 0.3rem 0;">
                  <strong>1️⃣ EMA Crossover (Bearish):</strong> ${{exitChecks.ema_crossover || 'N/A'}}
                </div>
                <div style="margin: 0.3rem 0;">
                  <strong>2️⃣ Trailing Stop:</strong> ${{exitChecks.trailing_stop || 'N/A'}}
                </div>
                <div style="margin: 0.3rem 0;">
                  <strong>3️⃣ Orange → Red Pattern:</strong> ${{exitChecks.orange_red || 'N/A'}}
                </div>
                <div style="margin: 0.3rem 0;">
                  <strong>4️⃣ Strong Sell Signal:</strong> ${{exitChecks.strong_sell || 'None'}}
                </div>
                <div style="margin-top: 0.5rem; padding-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.1); color: #0ea5e9;">
                  <strong>💰 Current Price:</strong> ${{currentPrice.toFixed(2)}}
                </div>
              </div>
            </div>
          `;

          appendRuleLogHTML(html);
          return;
        }}

        // default: rule check / wait (Entry Mode)
        let modeIcon = "";
        let modeText = "";
        if (posStatus === "FLAT") {{
          modeIcon = "🔍";
          modeText = "รอซื้อ";
        }} else if (posStatus === "LONG") {{
          modeIcon = "⏳";
          modeText = "ถือ LONG";
        }}

        if (rulesDetail) {{
          let html = `<div style="font-weight:700;">${{modeIcon}} ${{pair}} ${{modeText}}</div>`;
          html += createExpandableRuleItem("🔵→🟢 CDC Transition", rulesDetail.rule_1_cdc_green, "🔵");
          html += createExpandableRuleItem("ℹ️ 📐 Pattern (Info)", rulesDetail.rule_4_pattern, "📐");
          appendRuleLogHTML(html);
        }} else {{
          const ruleText = formatRuleFlags(rules);
          appendRuleLog(modeIcon + " " + pair + " " + modeText + " | " + ruleText);
        }}
      }}

      async function refreshSchedulerLogs(fromTimer = false) {{
        try {{
          console.log(`[refreshSchedulerLogs] Called (fromTimer=${{fromTimer}})`);
          const resp = await fetch("/bot/scheduler/logs");
          const data = await resp.json();
          const logs = data.logs || [];
          for (const log of logs) {{
            const key = logKey(log);
            if (seenLogKeys.has(key)) continue;
            seenLogKeys.add(key);
            renderLogEntry(log);
          }}
        }} catch (err) {{
          if (!fromTimer) appendRuleLog(`ดึง log ไม่สำเร็จ: ${{err.message}}`);
        }}
      }}

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

      // ===========================
      // Scheduler Status Functions
      // ===========================

      const schedulerCard = document.getElementById("scheduler-status-card");
      const startSchedulerBtn = document.getElementById("start-scheduler-btn");
      const stopSchedulerBtn = document.getElementById("stop-scheduler-btn");
      const refreshSchedulerBtn = document.getElementById("refresh-scheduler-btn");

      let nextRunTime = null;
      let countdownInterval = null;

      function updateCountdown() {{
        if (!nextRunTime) return;

        const now = new Date();
        const diffMs = nextRunTime - now;

        if (diffMs <= 0) {{
          const countdownEl = document.getElementById("countdown-display");
          if (countdownEl) {{
            countdownEl.textContent = "(running now...)";
            countdownEl.style.color = "#ea580c";
          }}
          return;
        }}

        const diffSec = Math.floor(diffMs / 1000);
        const diffMin = Math.floor(diffSec / 60);
        const diffSecRem = diffSec % 60;

        const countdownEl = document.getElementById("countdown-display");
        if (countdownEl) {{
          countdownEl.textContent = `(in ${{diffMin}}m ${{diffSecRem}}s)`;
        }}
      }}

      function renderSchedulerStatus(data) {{
        const isRunning = data.is_running || false;
        const status = data.status || "not_initialized";
        const pairs = data.pairs || [];
        const interval = data.interval_minutes || 1;
        const jobs = data.jobs || [];

        let statusBadge = "";
        let statusColor = "";
        let statusIcon = "";

        if (status === "running") {{
          statusBadge = "🟢 RUNNING";
          statusColor = "#166534";
          statusIcon = "🟢";
        }} else if (status === "stopped") {{
          statusBadge = "🔴 STOPPED";
          statusColor = "#b91c1c";
          statusIcon = "🔴";
        }} else {{
          statusBadge = "⚪ NOT INITIALIZED";
          statusColor = "#64748b";
          statusIcon = "⚪";
        }}

        let nextRunInfo = "";
        if (jobs.length > 0 && jobs[0].next_run) {{
          const nextRun = new Date(jobs[0].next_run);
          nextRunTime = nextRun;

          const now = new Date();
          const diffSec = Math.floor((nextRun - now) / 1000);
          const diffMin = Math.floor(diffSec / 60);
          const diffSecRem = diffSec % 60;

          nextRunInfo = `
            <div style="margin-top: 0.5rem; padding: 0.5rem; background: #fff; border-radius: 6px; border-left: 3px solid #0ea5e9;">
              <strong>⏱️ Next Run:</strong> ${{nextRun.toLocaleString()}}
              <span id="countdown-display" style="color: #0ea5e9; font-weight: 600;">(in ${{diffMin}}m ${{diffSecRem}}s)</span>
            </div>
          `;

          // Start countdown timer
          if (countdownInterval) clearInterval(countdownInterval);
          countdownInterval = setInterval(updateCountdown, 1000);
        }} else {{
          nextRunTime = null;
          if (countdownInterval) {{
            clearInterval(countdownInterval);
            countdownInterval = null;
          }}
        }}

        const pairsDisplay = pairs.length > 0 ? pairs.join(", ") : "-";

        schedulerCard.innerHTML = `
          <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.8rem;">
            <div>
              <strong style="color: #64748b;">Status:</strong>
              <div style="font-size: 1.1rem; font-weight: 700; color: ${{statusColor}}; margin-top: 0.2rem;">
                ${{statusBadge}}
              </div>
            </div>
            <div>
              <strong style="color: #64748b;">Pairs:</strong>
              <div style="font-size: 0.95rem; margin-top: 0.2rem; color: #0f172a;">
                ${{pairsDisplay}}
              </div>
            </div>
            <div>
              <strong style="color: #64748b;">Interval:</strong>
              <div style="font-size: 0.95rem; margin-top: 0.2rem; color: #0f172a;">
                ${{interval >= 1 ? `Every ${{interval}} minute(s)` : `Every ${{(interval * 60).toFixed(0)}} second(s)`}}
              </div>
            </div>
            <div>
              <strong style="color: #64748b;">Jobs:</strong>
              <div style="font-size: 0.95rem; margin-top: 0.2rem; color: #0f172a;">
                ${{jobs.length}} active
              </div>
            </div>
          </div>
          ${{nextRunInfo}}
        `;

        // Update button states
        startSchedulerBtn.disabled = isRunning;
        stopSchedulerBtn.disabled = !isRunning;
      }}

      // ===========================
      // Process Manager Functions
      // ===========================

      async function refreshProcesses() {{
        try {{
          // Fetch system processes
          const resp = await fetch("/system/processes");
          const data = await resp.json();
          const processes = data.processes || [];

          // Fetch scheduler status
          const schedulerResp = await fetch("/bot/scheduler/status");
          const schedulerData = await schedulerResp.json();
          const isSchedulerRunning = schedulerData.running || false;

          let html = '<div style="display: grid; gap: 0.5rem;">';

          // Add Trading Bot Scheduler if running
          if (isSchedulerRunning) {{
            const pairs = schedulerData.pairs || [];
            const interval = schedulerData.interval_minutes || 1;
            const jobs = schedulerData.jobs || [];
            const activeJobs = jobs.length;

            html += `
              <div style="background: rgba(16, 185, 129, 0.1); padding: 0.6rem; border-radius: 8px; border-left: 3px solid #10b981;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div>
                    <strong style="color: #10b981;">🤖 Trading Bot Scheduler</strong>
                    <div style="font-size: 0.85rem; color: #64748b; margin-top: 0.2rem;">
                      Pairs: ${{pairs.join(", ")}} | Interval: ${{interval}}m | Jobs: ${{activeJobs}} active
                    </div>
                  </div>
                  <button
                    class="btn-secondary"
                    style="background: #fef2f2; color: #b91c1c; border-color: #fca5a5; padding: 0.4rem 0.8rem; font-size: 0.85rem;"
                    onclick="stopSchedulerFromProcessManager()"
                  >
                    🗑️ Stop
                  </button>
                </div>
              </div>
            `;
          }}

          // Add system processes
          processes.forEach(proc => {{
            const uptimeMin = Math.floor(proc.uptime_seconds / 60);
            const uptimeSec = proc.uptime_seconds % 60;
            const typeColor = proc.type === "Monitor CLI" ? "#f59e0b" : proc.type === "Control Plane" ? "#3b82f6" : "#10b981";

            html += `
              <div style="background: rgba(255,255,255,0.5); padding: 0.6rem; border-radius: 8px; border-left: 3px solid ${{typeColor}};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <div>
                    <strong style="color: ${{typeColor}};">${{proc.type}}</strong>
                    <div style="font-size: 0.85rem; color: #64748b; margin-top: 0.2rem;">
                      PID: ${{proc.pid}} | Uptime: ${{uptimeMin}}m ${{uptimeSec}}s | CPU: ${{proc.cpu_percent}}% | Mem: ${{proc.memory_percent.toFixed(1)}}%
                    </div>
                  </div>
                  <button
                    class="btn-secondary"
                    style="background: #fef2f2; color: #b91c1c; border-color: #fca5a5; padding: 0.4rem 0.8rem; font-size: 0.85rem;"
                    onclick="killProcess(${{proc.pid}}, '${{proc.type}}')"
                  >
                    🗑️ Kill
                  </button>
                </div>
              </div>
            `;
          }});

          if (!isSchedulerRunning && processes.length === 0) {{
            html = '<p style="color: #64748b;">✅ ไม่มี background processes ที่ต้องจัดการ</p>';
          }} else {{
            html += '</div>';
          }}

          processListEl.innerHTML = html;
        }} catch (err) {{
          processListEl.innerHTML = `<p style="color: #b91c1c;">💥 Error: ${{err.message}}</p>`;
        }}
      }}

      async function stopSchedulerFromProcessManager() {{
        if (!confirm('ยืนยันหยุด Trading Bot Scheduler?')) return;

        try {{
          const resp = await fetch("/bot/scheduler/stop", {{ method: "POST" }});
          const data = await resp.json();

          if (resp.ok) {{
            alert('✅ หยุด Trading Bot Scheduler สำเร็จ');
            await refreshProcesses();
            await refreshSchedulerStatus();
          }} else {{
            throw new Error(data.detail || "Failed to stop scheduler");
          }}
        }} catch (err) {{
          alert(`💥 Error: ${{err.message}}`);
        }}
      }}

      async function killProcess(pid, type) {{
        if (!confirm(`ยืนยันหยุด process: ${{type}} (PID: ${{pid}})?`)) return;

        try {{
          const resp = await fetch(`/system/processes/${{pid}}/kill`, {{ method: "POST" }});
          const data = await resp.json();

          if (resp.ok) {{
            alert(`✅ หยุด ${{type}} (PID: ${{pid}}) สำเร็จ`);
            await refreshProcesses();
          }} else {{
            throw new Error(data.detail || "Failed to kill process");
          }}
        }} catch (err) {{
          alert(`💥 Error: ${{err.message}}`);
        }}
      }}

      refreshProcessesBtn.addEventListener("click", refreshProcesses);

      async function refreshSchedulerStatus() {{
        try {{
          console.log(`[refreshSchedulerStatus] Called`);
          const resp = await fetch("/bot/scheduler/status");
          const data = await resp.json();
          renderSchedulerStatus(data);
        }} catch (err) {{
          schedulerCard.innerHTML = `<p style="color: #b91c1c;">💥 Error: ${{err.message}}</p>`;
        }}
      }}

      startSchedulerBtn.addEventListener("click", async () => {{
        const pair = document.getElementById("pair").value;
        const intervalRaw = document.getElementById("interval").value;
        const interval = Math.max(parseFloat(intervalRaw || "0"), 0.1);
        try {{
          startSchedulerBtn.disabled = true;
          appendLog(`🔄 Starting Auto Trading for ${{pair}} (every ${{interval}} minute(s))...`);
          const resp = await fetch("/bot/scheduler/start", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify({{ pairs: [pair], interval_minutes: interval }})
          }});
          const data = await resp.json();
          if (!resp.ok) {{
            const detail = data?.detail ?? data;
            const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
            throw new Error(msg);
          }}
          appendLog(`✅ Auto Trading started for ${{pair}} - checking every ${{interval}} minute(s)`);
          await refreshSchedulerStatus();
        }} catch (err) {{
          alert("Failed to start auto trading: " + err.message);
          appendLog("💥 Auto Trading start failed: " + err.message);
          startSchedulerBtn.disabled = false;
        }}
      }});

      stopSchedulerBtn.addEventListener("click", async () => {{
        if (!confirm("ยืนยันหยุด Auto Trading?")) return;
        try {{
          stopSchedulerBtn.disabled = true;
          appendLog("🔄 Stopping Auto Trading...");
          const resp = await fetch("/bot/scheduler/stop", {{ method: "POST" }});
          const data = await resp.json();
          if (!resp.ok) {{
            const detail = data?.detail ?? data;
            const msg = typeof detail === "string" ? detail : JSON.stringify(detail);
            throw new Error(msg);
          }}
          appendLog("⏹️ Auto Trading stopped successfully");
          await refreshSchedulerStatus();
        }} catch (err) {{
          alert("Failed to stop auto trading: " + err.message);
          appendLog("💥 Auto Trading stop failed: " + err.message);
          stopSchedulerBtn.disabled = false;
        }}
      }});

      refreshSchedulerBtn.addEventListener("click", refreshSchedulerStatus);

      // Auto-refresh scheduler status every 60 seconds (1 minute)
      setInterval(refreshSchedulerStatus, 60000);
      // Auto-refresh scheduler logs every 60 seconds (1 minute)
      setInterval(() => refreshSchedulerLogs(true), 60000);

      // Log version to console for debugging
      console.log("🔧 Bot Runner v2.0 - Refresh interval: 60s");

      // Initial load
      refreshSchedulerStatus();
      refreshSchedulerLogs(false);
      refreshProcesses();

      // Auto-refresh processes every 30 seconds
      setInterval(refreshProcesses, 30000);
    </script>
    """


__all__ = ["render_bot_runner"]
