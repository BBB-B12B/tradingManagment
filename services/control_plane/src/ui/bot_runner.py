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
      .status { font-weight: 600; }
      .log { background: #0f172a; color: #e2e8f0; padding: 0.75rem; border-radius: 10px; font-family: "IBM Plex Mono", Menlo, monospace; font-size: 0.9rem; max-height: 320px; overflow: auto; white-space: pre-wrap; }
    """

    return f"""
    <style>{style}</style>
    <div class="bot-container">
      <div class="card">
        <h2>🚀 Run Bot</h2>
        <p>สั่งรันบอท (ใช้ backtest logic) แล้วบันทึกคำสั่ง ENTRY/EXIT ลง D1 ผ่าน worker</p>
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
          <span id="status" class="status"></span>
        </form>
      </div>
      <div class="card">
        <h2>📜 Log</h2>
        <div id="log" class="log">ยังไม่มีการรัน</div>
      </div>
    </div>
    <script>
      const form = document.getElementById("bot-form");
      const statusEl = document.getElementById("status");
      const logEl = document.getElementById("log");
      const runBtn = document.getElementById("run-btn");

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
          const resp = await fetch("/bot/run", {{
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
          statusEl.textContent = `✅ สำเร็จ: trades=${{data.trades}}, orders=${{data.orders_logged}}`;
          statusEl.style.color = "#166534";
          appendLog(`สำเร็จ: trades=${{data.trades}} orders=${{data.orders_logged}} ROI=${{data.stats?.roi_pct ?? 0}}%`);
        }} catch (err) {{
          statusEl.textContent = "💥 " + err.message;
          statusEl.style.color = "#b91c1c";
          appendLog("ล้มเหลว: " + err.message);
        }} finally {{
          runBtn.disabled = false;
        }}
      }});
    </script>
    """


__all__ = ["render_bot_runner"]
