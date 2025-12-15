"""HTML renderer for Backtest UI."""

from __future__ import annotations

from typing import List


def render_backtest_view(pairs: List[str]) -> str:
    if not pairs:
        return """
        <div class="card">
          <h2>🧪 Backtest</h2>
          <p>ยังไม่มี Config ให้ backtest กรุณาเพิ่มคู่เทรดในหน้า Config ก่อน</p>
        </div>
        """

    options = "".join(f'<option value="{pair}">{pair}</option>' for pair in pairs)

    style = """
      body { margin: 0; padding: 0; }
      .backtest-container { display: flex; flex-direction: column; gap: 0.75rem; max-width: 100%; padding: 0.25rem 0.5rem; box-sizing: border-box; }
      .card { background: #fff; border-radius: 12px; box-shadow: 0 8px 20px rgba(15,23,42,0.06); padding: 0.9rem 1rem; }
      .card h2 { margin-top: 0; margin-bottom: 0.5rem; display: flex; align-items: center; gap: 0.4rem; font-size: 1.3rem; }
      .controls { display: flex; flex-wrap: wrap; gap: 0.6rem 0.8rem; align-items: flex-end; }
      .form-field { display: flex; flex-direction: column; gap: 0.3rem; min-width: 180px; }
      .form-field label { font-weight: 600; color: #0f172a; font-size: 0.9rem; }
      .form-field input, .form-field select { padding: 0.5rem 0.65rem; border: 1px solid #d5dbe3; border-radius: 8px; background: #f8fafc; font-size: 0.9rem; }
      .actions { display: flex; gap: 0.6rem; align-items: center; }
      .btn-primary { background: linear-gradient(135deg, #2563eb, #1d4ed8); color: #fff; border: none; border-radius: 8px; padding: 0.65rem 1.1rem; cursor: pointer; font-weight: 700; white-space: nowrap; font-size: 0.95rem; }
      .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
      .status { font-weight: 600; color: #0f172a; font-size: 0.9rem; }
      .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 0.65rem; margin-top: 0.5rem; }
      .stat { background: #f8fafc; border: 1px solid #e5e7eb; padding: 0.7rem 0.8rem; border-radius: 10px; }
      .table-wrapper { width: 100%; overflow-x: auto; margin-top: 0.75rem; }
      table { width: 100%; border-collapse: collapse; min-width: 1500px; }
      th, td { border-bottom: 1px solid #e5e7eb; padding: 0.5rem 0.4rem; text-align: left; font-size: 0.85rem; vertical-align: top; white-space: nowrap; }
      th { background: linear-gradient(135deg, #eff6ff, #f8fafc); color: #0f172a; font-weight: 600; position: sticky; top: 0; z-index: 10; }
      .pill { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.45rem; border-radius: 999px; font-size: 0.82rem; }
      .pill.win { background: #ecfdf3; color: #166534; }
      .pill.loss { background: #fef2f2; color: #b91c1c; }
      .note { color: #475569; font-size: 0.85rem; }
      .card-wide { width: 100%; max-width: 100%; }
      .controls-header { margin-bottom: 0.25rem; font-size: 0.9rem; }
      @media (max-width: 900px) {
        .form-field { min-width: 150px; flex: 1 1 45%; }
        table { font-size: 0.75rem; min-width: 1200px; }
        th, td { padding: 0.35rem 0.25rem; }
      }
    """

    return f"""
    <style>{style}</style>
    <div class="backtest-container">
      <div class="card card-wide">
        <h2>🧪 Backtest</h2>
        <p class="controls-header">ลองรัน backtest แบบเร็วด้วยกฎ CDC ทั้ง 4 ข้อบน Binance data</p>
        <form id="backtest-form" class="controls">
          <div class="form-field">
            <label for="pair">Pair</label>
            <select id="pair" name="pair">{options}</select>
          </div>
          <div class="form-field">
            <label for="timeframe">Timeframe (LTF)</label>
            <input id="timeframe" name="timeframe" type="text" placeholder="เช่น 1h, 4h" value="1d" />
          </div>
          <div class="form-field">
            <label for="limit">จำนวนแท่ง (ย้อนหลัง)</label>
            <input id="limit" name="limit" type="number" value="1000" min="50" max="1000" />
          </div>
          <div class="form-field">
            <label for="capital">เงินต้น (หน่วย quote)</label>
            <input id="capital" name="capital" type="number" value="10000" min="0" step="1" />
          </div>
          <div class="actions">
            <button class="btn-primary" type="submit" id="run-btn">Run Backtest</button>
            <span id="status" class="status"></span>
          </div>
        </form>
      </div>
      <div class="card card-wide" id="results">
        <h2>📈 ผลลัพธ์</h2>
        <p>กรอกค่าแล้วกด Run เพื่อดูผลลัพธ์</p>
      </div>
    </div>
    <script>
      const form = document.getElementById("backtest-form");
      const statusEl = document.getElementById("status");
      const resultsEl = document.getElementById("results");
      const runBtn = document.getElementById("run-btn");

      const ruleOrder = [
        ["rule_1_cdc_green", "CDC สีเขียว (LTF/HTF)"],
        ["rule_2_leading_red", "Leading Red"],
        ["rule_3_leading_signal", "Leading Signal"],
        ["rule_4_pattern", "Pattern (W/ไม่เป็น V)"],
      ];

      function entryReasonText(reason) {{
        switch (reason) {{
          case "PATTERN_BLUE_TO_GREEN": return "🔵➡️🟢 BLUE→GREEN";
          case "DIVERGENCE_BULLISH": return "📊 Bullish Divergence";
          default: return reason || "BLUE→GREEN";
        }}
      }}

      function exitReasonText(reason) {{
        switch (reason) {{
          case "ACTION_ZONE_RED_LTF": return "เปลี่ยนเป็น Red (Action Zone) ที่ LTF";
          case "ACTION_ZONE_RED_BOTH": return "Action Zone Red พร้อมกัน LTF/HTF";
          case "CDC_RED_LTF": return "CDC LTF เปลี่ยนเป็นแดง";
          case "CDC_RED_HTF": return "CDC HTF เปลี่ยนเป็นแดง";
          case "CDC_RED_BOTH": return "CDC LTF/HTF เป็นแดงพร้อมกัน";
          case "YELLOW_YELLOW_RED": return "เหลือง เหลือง แล้วเจอ Red → ขาย";
          case "STOP_LOSS_SUPPORT": return "หลุดจุดต่ำสุดก่อนเข้า (Cut loss)";
          case "STRONG_SELL": return "สัญญาณ Strong Sell (RSI Divergence)";
          case "END_OF_DATA": return "สิ้นสุดข้อมูลย้อนหลัง";
          default: return reason || "-";
        }}
      }}

      function renderRulesCell(trade) {{
        const rules = trade.rules || {{}};
        if (!Object.keys(rules).length) return "-";
        const items = ruleOrder.map(([key, label]) => {{
          const passed = rules[key];
          const icon = passed ? "✓" : "✗";
          return `<div>${{icon}} ${{label}}</div>`;
        }}).join("");
        return `<div style="display:grid; gap:2px;">${{items}}</div>`;
      }}

      function renderResults(data) {{
        const trades = data.trades || [];
        const stats = data.stats || {{}};
        const income = stats.total_income ?? 0;
        const finalValue = stats.final_equity_value ?? 0;
        const initialCapital = stats.initial_capital ?? data.initial_capital ?? 0;
        const totalDays = stats.total_duration_days ?? 0;
        const cagr = stats.cagr_pct ?? 0;
        const avgCapitalDeployed = stats.avg_capital_deployed ?? 0;
        const totalCapitalDeployed = stats.total_capital_deployed ?? 0;
        const roi = stats.roi_pct ?? 0;

        const rows = trades.length
          ? trades.map(t => `
            <tr>
              <td>${{t.entry_time}}</td>
              <td>${{t.exit_time || '-'}} </td>
              <td>${{t.entry_price.toFixed(2)}}</td>
              <td>${{t.exit_price.toFixed(2)}}</td>
              <td>${{t.cutloss_price != null ? t.cutloss_price.toFixed(2) : '-'}}</td>
              <td>${{(t.invested_amount ?? 0).toFixed(2)}}</td>
              <td>${{(() => {{
                const sat = (t.position_units ?? 0) * 1e8;
                if (sat === 0) return "0";
                const absSat = Math.abs(sat);
                const exp = Math.floor(Math.log10(absSat));
                const base = sat / Math.pow(10, exp);
                return `${{base.toFixed(2)}} × 10^${{exp}}`;
              }})()}}</td>
              <td>${{(t.pnl_amount ?? 0).toFixed(2)}}</td>
              <td>${{t.duration_days != null ? t.duration_days.toFixed(2) : '-'}}</td>
              <td><span class="pill ${{t.pnl_pct > 0 ? 'win' : 'loss'}}">${{t.pnl_pct.toFixed(2)}}%</span></td>
              <td class="note">${{entryReasonText(t.entry_reason)}}</td>
              <td class="note">${{exitReasonText(t.exit_reason)}}</td>
              <td>${{renderRulesCell(t)}}</td>
            </tr>
          `).join("")
          : '<tr><td colspan="13" style="text-align:center; padding:0.9rem;">ยังไม่มีเทรด</td></tr>';

        resultsEl.innerHTML = `
          <h2>📈 ผลลัพธ์</h2>
          <div class="stat-grid">
            <div class="stat"><div>จำนวนเทรด</div><strong>${{stats.total_trades || 0}}</strong></div>
            <div class="stat"><div>Win Rate</div><strong>${{(stats.win_rate_pct || 0).toFixed(2)}}%</strong></div>
            <div class="stat"><div>Avg Return/Trade</div><strong>${{(stats.avg_return_pct || 0).toFixed(2)}}%</strong><div class="note">เฉลี่ย % ต่อเทรด</div></div>
            <div class="stat"><div>ROI (ทุนที่ใช้จริง)</div><strong>${{roi.toFixed(2)}}%</strong><div class="note">กำไร ÷ เงินลงทุนรวม</div></div>
            <div class="stat"><div>เงินเข้าเฉลี่ย/เทรด</div><strong>${{avgCapitalDeployed.toFixed(2)}}</strong><div class="note">รวมใช้ ${{totalCapitalDeployed.toFixed(2)}}</div></div>
            <div class="stat"><div>Total Income</div><strong>${{income.toFixed(2)}}</strong><div class="note">ทุนเริ่ม ${{initialCapital.toFixed(2)}} → พอร์ต ${{finalValue.toFixed(2)}}</div></div>
            <div class="stat"><div>Cumulative Return</div><strong>${{(stats.cumulative_return_pct || 0).toFixed(2)}}%</strong><div class="note">กำไรทบต้น (% ของพอร์ต)</div></div>
            <div class="stat"><div>ระยะเวลารวม</div><strong>${{totalDays.toFixed(2)}} วัน</strong><div class="note">CAGR ${{cagr.toFixed(2)}}%/ปี</div></div>
          </div>
          <div class="table-wrapper">
            <table>
              <thead>
                <tr><th>เข้า</th><th>ออก</th><th>ราคาเข้า</th><th>ราคาออก</th><th>Cutloss</th><th>เงินเข้า</th><th>จำนวนหน่วย (Sat)</th><th>กำไร/ขาดทุน</th><th>ระยะเวลา (วัน)</th><th>PnL %</th><th>เหตุเข้า</th><th>เหตุออก</th><th>เกณฑ์ 4 ข้อ</th></tr>
              </thead>
              <tbody>${{rows}}</tbody>
            </table>
          </div>
        `;
      }}

      form.addEventListener("submit", async (e) => {{
        e.preventDefault();
        const pair = document.getElementById("pair").value;
        const timeframe = document.getElementById("timeframe").value;
        const limit = document.getElementById("limit").value;
        const capital = document.getElementById("capital").value;

        statusEl.textContent = "⏳ กำลังรัน backtest...";
        runBtn.disabled = true;

        try {{
          const url = `/backtest?pair=${{encodeURIComponent(pair)}}&timeframe=${{encodeURIComponent(timeframe)}}&limit=${{limit}}&initial_capital=${{capital}}`;
          const resp = await fetch(url);
          const data = await resp.json();
          if (!resp.ok) {{
            throw new Error(data.detail || "Backtest ล้มเหลว");
          }}
          statusEl.textContent = `✅ ${{data.stats.total_trades}} เทรด | Win rate ${{data.stats.win_rate_pct.toFixed(2)}}%`;
          renderResults(data);
        }} catch (err) {{
          console.error(err);
          statusEl.textContent = "❌ " + err.message;
        }} finally {{
          runBtn.disabled = false;
        }}
      }});
    </script>
    """


__all__ = ["render_backtest_view"]
