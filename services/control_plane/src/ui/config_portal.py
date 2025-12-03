"""Simple HTML portal for managing trading configurations."""

from __future__ import annotations

import json
from typing import List

from libs.common.config.schema import TradingConfiguration


PAIR_SUGGESTIONS = [
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "ADA/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "AVAX/USDT",
    "MATIC/USDT",
    "DOT/USDT",
]

TIMEFRAME_OPTIONS = ["15m", "1h", "4h", "1d", "1w"]
RISK_PERCENT_OPTIONS = ["0.005", "0.008", "0.01", "0.03", "0.05"]
BUFFER_OPTIONS = ["0.002", "0.003", "0.005"]
BUDGET_OPTIONS = ["0.2", "0.5", "0.8", "1.0"]
RULE_INT_OPTIONS = ["1", "2", "3", "5", "10", "20", "30"]


def render_config_portal(configs: List[TradingConfiguration]) -> str:
    config_map = {
        cfg.pair: cfg.model_dump()
        for cfg in sorted(configs, key=lambda c: c.pair)
    }
    configs_json = json.dumps(config_map)

    pairs_html = "".join(
        f'<option value="{cfg.pair}">{cfg.pair}</option>'
        for cfg in sorted(configs, key=lambda c: c.pair)
    )

    pair_suggestions_html = "".join(f'<option value="{pair}"></option>' for pair in PAIR_SUGGESTIONS)
    timeframe_options_html = "".join(f'<option value="{tf}"></option>' for tf in TIMEFRAME_OPTIONS)
    budget_options_html = "".join(f'<option value="{val}"></option>' for val in BUDGET_OPTIONS)
    risk_options_html = "".join(f'<option value="{val}"></option>' for val in RISK_PERCENT_OPTIONS)
    buffer_options_html = "".join(f'<option value="{val}"></option>' for val in BUFFER_OPTIONS)
    rule_int_options_html = "".join(f'<option value="{val}"></option>' for val in RULE_INT_OPTIONS)

    return f"""
<html>
  <head>
    <title>CDC Zone Config Portal</title>
    <style>
      body {{ font-family: "Inter", "IBM Plex Sans Thai", "Sarabun", sans-serif; margin: 0; padding: 0; background: #f7fafc; color: #1f2933; }}
      h1 {{ margin-bottom: 0.5rem; }}
      .navbar {{
        background: #0f172a;
        color: #fff;
        padding: 0.8rem 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 12px rgba(15,23,42,0.25);
      }}
      .navbar h1 {{
        margin: 0;
        font-size: 1.3rem;
      }}
      .nav-links {{
        display: flex;
        gap: 1rem;
      }}
      .nav-links a {{
        color: #e2e8f0;
        text-decoration: none;
        padding: 0.4rem 0.8rem;
        border-radius: 8px;
        font-weight: 500;
      }}
      .nav-links a:hover {{
        background: rgba(255,255,255,0.15);
      }}
      .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
      .layout {{ display: flex; gap: 1.5rem; flex-wrap: wrap; }}
      .panel {{ flex: 1 1 420px; border: 1px solid #dce0e8; border-radius: 16px; padding: 1.75rem; box-shadow: 0 10px 30px rgba(15,23,42,0.08); background: #fff; }}
      .panel h2 {{ margin-top: 0; font-size: 1.2rem; font-weight: 600; color: #0f172a; display: flex; align-items: center; gap: 0.4rem; }}
      .field {{ display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.9rem; }}
      .field label {{ font-weight: 600; }}
      input[type="text"], input[type="number"], select {{ width: 100%; padding: 0.6rem; border: 1px solid #d5dbe3; border-radius: 10px; background: #fbfdff; transition: border 0.2s ease, box-shadow 0.2s ease; }}
      input[type="text"]:focus, input[type="number"]:focus, select:focus {{ outline: none; border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }}
      input[type="checkbox"] {{ margin-right: 0.3rem; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; border-radius: 12px; overflow: hidden; }}
      th, td {{ padding: 0.7rem 0.8rem; border-bottom: 1px solid #e4e7eb; text-align: left; font-size: 0.95rem; }}
      th {{ background: linear-gradient(135deg, #eff6ff, #f8fafc); font-size: 0.9rem; color: #0f172a; }}
      tbody tr:nth-child(every) {{ background: #fff; }}
      button {{ margin-top: 1.2rem; padding: 0.75rem 1.2rem; background: #2563eb; color: #fff; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; }}
      button:disabled {{ opacity: 0.7; cursor: not-allowed; }}
      .inline-checkbox {{ display: flex; align-items: center; gap: 0.5rem; margin-top: 0.8rem; }}
      .two-col {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 1rem; }}
      .section-title {{ margin-top: 1.5rem; margin-bottom: 0.3rem; font-size: 1rem; color: #111; }}
      #status {{ margin-top: 1rem; font-weight: 600; }}
      .helper {{ font-size: 0.85rem; color: #6b7280; margin-top: 0.2rem; }}
      .tooltip {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        margin-left: 0.3rem;
        width: 18px;
        height: 18px;
        border-radius: 999px;
        background: #2563eb;
        color: #fff;
        font-size: 0.75rem;
        cursor: help;
        position: relative;
      }}
      .tooltip span {{
        visibility: hidden;
        position: absolute;
        background: #1e293b;
        color: #fff;
        padding: 0.5rem 0.75rem;
        border-radius: 8px;
        width: 220px;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        opacity: 0;
        transition: opacity 0.2s ease;
        font-size: 0.8rem;
        line-height: 1.2;
        z-index: 10;
      }}
      .tooltip:hover span {{
        visibility: visible;
        opacity: 1;
      }}
    </style>
  </head>
  <body>
  <body>
    <div class="navbar">
      <h1>CDC Zone Control Plane</h1>
      <div class="nav-links">
        <a href="/dashboard">📊 Dashboard</a>
        <a href="/ui/config">⚙️ Config</a>
        <a href="/ui/backtest">🧪 Backtest</a>
        <a href="/reports/success">✅ Success Report</a>
        <a href="/docs">📘 API Docs</a>
      </div>
    </div>
    <div class="container">
      <h1>CDC Zone – Config Portal</h1>
      <p>จัดการค่าคอนฟิกของคู่เทรดผ่าน UI แทนการใช้ curl หรือ Swagger</p>
      <div class="config-layout">
        <div class="panel">
          <h2>💾 บันทึก/แก้ไข Config</h2>
        <form id="config-form">
          <div class="field">
            <label for="pair">Trading Pair <span style="color: red;">*</span></label>
            <input type="text" id="pair" name="pair" list="pair-options" placeholder="พิมพ์ เช่น BTC/USDT, ETH/USDT" required />
            <div class="helper">รูปแบบ: BASE/QUOTE เช่น BTC/USDT (ต้องมี /)</div>
          </div>

          <div class="field">
            <label for="pair-select" style="font-weight:400; color: #6b7280;">⚡ Shortcut: โหลดจาก config ที่บันทึกไว้ (ไม่บังคับ)</label>
            <select id="pair-select">
              <option value="">-- เลือกเพื่อโหลด config เก่า (optional) --</option>
              {pairs_html}
            </select>
            <div class="helper">เลือกคู่ที่มีอยู่แล้วเพื่อโหลดค่า config มาแก้ไข</div>
          </div>
          <datalist id="pair-options">
            {pair_suggestions_html}
          </datalist>

          <div class="field">
            <label for="timeframe">Base Timeframe <span class="tooltip">?<span>ระบบใช้ Auto 3-Timeframe Analysis (1W → 1D → 1H) โดยอัตโนมัติ ค่านี้เป็น Base TF สำหรับ reference</span></span></label>
            <input type="text" id="timeframe" name="timeframe" value="1d" readonly style="background: #f3f4f6; cursor: not-allowed;" />
            <div class="helper">🔄 Auto 3-TF: 1W (Bull trend) → 1D (Pattern) → 1H (Entry/Exit)</div>
          </div>

          <div class="field">
            <label for="budget_pct">💰 Budget % ต่อการเทรด (เงินที่ลงทุนจริง) <span class="tooltip">?<span>% ของ port ที่จะลงทุนในแต่ละ trade<br>ตัวอย่าง: Port 10,000 บาท + Budget 2% = ลง 200 บาท/trade</span></span></label>
            <input type="number" step="0.1" id="budget_pct" name="budget_pct" list="budget-options" value="0.5" min="0.1" max="20" required />
            <div class="helper">⚡ ต้องการลง 20% ของ port → ใส่ 20 (จำกัดไม่เกิน 20% เพื่อความปลอดภัย)</div>
          </div>
          <datalist id="budget-options">
            {budget_options_html}
          </datalist>

          <div class="inline-checkbox" style="margin-top:1rem;">
            <label><input type="checkbox" id="enable_w_shape_filter" checked />Enable W-shape Filter</label>
            <label><input type="checkbox" id="enable_leading_signal" checked />Enable Leading Signal</label>
          </div>

          <div class="section-title">Risk Settings</div>

          <!-- Educational box explaining the difference -->
          <div style="background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; padding: 12px; margin-bottom: 16px; font-size: 13px; line-height: 1.6;">
            <div style="font-weight: 600; margin-bottom: 8px; color: #856404;">📚 ความแตกต่างระหว่าง Budget % และ Per Trade Cap %</div>
            <div style="margin-bottom: 8px;">
              <strong style="color: #0066cc;">Budget % (ด้านบน)</strong> = เงินที่คุณต้องการลงทุนจริงต่อ trade<br>
              <span style="color: #666;">ตัวอย่าง: Port 10,000 บาท + Budget 20% = ต้องการลง 2,000 บาท/trade</span>
            </div>
            <div style="margin-bottom: 8px;">
              <strong style="color: #dc3545;">Per Trade Cap % (ด้านล่าง)</strong> = % ของ port ทั้งหมดที่ยอมเสี่ยงขาดทุน (ใช้คำนวณ position size)<br>
              <span style="color: #666;">ตัวอย่าง: Port 10,000 + Per Trade Cap 2% = ยอมเสีย 200 บาท สูงสุด</span>
            </div>
            <div style="background: white; padding: 8px; border-radius: 3px; border-left: 3px solid #28a745; margin-top: 8px;">
              <strong>ตัวอย่างการคำนวณ:</strong><br>
              • Port = 10,000 บาท<br>
              • Per Trade Cap % = 2% → ยอมเสีย 200 บาท สูงสุด<br>
              • Entry = 100 บาท, Cutloss = 95 บาท (ห่าง 5 บาท)<br>
              • Position Size = 200 ÷ 5 = <strong>40 หน่วย</strong><br>
              • <strong>เงินที่ลงจริง = 40 × 100 = 4,000 บาท</strong> (ไม่ใช่ Budget %)<br>
              • ถ้าโดน cutloss: ขาดทุน 40 × 5 = 200 บาท (2% ของ port)
            </div>
            <div style="margin-top: 8px; color: #856404;">
              ⚠️ <strong>สำคัญ:</strong> Budget % กำหนดเงินลงทุน, Per Trade Cap % กำหนดความเสี่ยง
            </div>
          </div>

          <div class="two-col">
            <div class="field">
              <label for="per_trade_cap_pct">🛡️ Per Trade Cap % (ความเสี่ยงสูงสุด) <span class="tooltip">?<span>% ของพอร์ตทั้งหมดที่ยอมขาดทุนต่อ trade<br>ใช้คำนวณ Position Size ตามระยะห่าง Entry-Cutloss</span></span></label>
              <input type="number" step="0.01" id="per_trade_cap_pct" list="risk-options" value="2" />
              <div class="helper">⚡ แนะนำ: 1-5% | ตัวอย่าง: Port 10,000 + ใส่ 2 = ยอมเสีย 200 บาท สูงสุด</div>
            </div>
          </div>
          <datalist id="risk-options">
            {risk_options_html}
          </datalist>

          <button type="button" id="toggle-advanced" style="margin-top:1.5rem;">⚙️ Advance Settings</button>
          <div id="advanced-settings" style="display:none; margin-top:1rem;">
            <div class="section-title">Rule Parameters</div>
            <div class="two-col">
              <div class="field">
                <label for="lead_red_min_bars">Leading Red Min Bars <span class="tooltip">?<span>จำนวนแท่งขั้นต่ำที่ต้องย้อนกลับไปหาแท่งแดง</span></span></label>
                <input type="number" id="lead_red_min_bars" list="rule-int-options" value="1" />
              </div>
              <div class="field">
                <label for="lead_red_max_bars">Leading Red Max Bars <span class="tooltip">?<span>จำนวนแท่งสูงสุดที่ยอมให้แดงนำหน้า (เช่น 20 แท่ง)</span></span></label>
                <input type="number" id="lead_red_max_bars" list="rule-int-options" value="20" />
              </div>
              <div class="field">
                <label for="leading_momentum_lookback">Momentum Lookback <span class="tooltip">?<span>ดู MACD histogram ย้อนกี่แท่งเพื่อหาการตัดขึ้น</span></span></label>
                <input type="number" id="leading_momentum_lookback" list="rule-int-options" value="3" />
              </div>
              <div class="field">
                <label for="higher_low_min_diff_pct">Higher Low Min Diff % <span class="tooltip">?<span>Diff ขั้นต่ำระหว่าง L1 กับ L2 (เช่น 0.2% = 0.002)</span></span></label>
                <input type="number" step="0.0001" id="higher_low_min_diff_pct" list="buffer-options" value="0.002" />
              </div>
              <div class="field">
                <label for="higher_low_max_bars_between">Higher Low Max Bars <span class="tooltip">?<span>จำนวนแท่งสูงสุดที่ยอมให้ระหว่าง swing low สองจุด</span></span></label>
                <input type="number" id="higher_low_max_bars_between" list="rule-int-options" value="20" />
              </div>
              <div class="field">
                <label for="w_window_bars">W Window Bars <span class="tooltip">?<span>จำนวนแท่งที่ใช้ค้นหา W-shape (เช่น 30 ≈ 1 เดือน TF Day)</span></span></label>
                <input type="number" id="w_window_bars" list="rule-int-options" value="30" />
              </div>
            </div>
          </div>
          <datalist id="rule-int-options">
            {rule_int_options_html}
          </datalist>

          <button type="submit">บันทึก Config</button>
          <div id="status"></div>
        </form>
      </div>

      <div class="panel">
        <h2>📋 Config ที่มีอยู่</h2>
        <table>
          <thead>
            <tr>
              <th>Pair</th>
              <th>Base TF</th>
              <th>Budget %</th>
              <th>W-Filter</th>
              <th>Leading Signal</th>
              <th></th>
            </tr>
          </thead>
          <tbody id="config-table-body">
            {"".join(_render_config_row(cfg) for cfg in sorted(configs, key=lambda c: c.pair))}
          </tbody>
        </table>
      </div>
    </div>

    <script>
      let configs = {configs_json};
      const statusEl = document.getElementById("status");
      const pairSelect = document.getElementById("pair-select");
      const configTableBody = document.getElementById("config-table-body");
      const pairOptionsList = document.getElementById("pair-options");
      const basePairOptions = `{pair_suggestions_html}`;

      function setStatus(msg, success=true) {{
        statusEl.textContent = msg;
        statusEl.style.color = success ? "#059669" : "#b91c1c";
      }}

      function toPercentInput(value) {{
        if (value === null || value === undefined) return "";
        const percent = value * 100;
        return Number.isFinite(percent) ? percent.toFixed(3).replace(/\\.0+$/, "").replace(/\\.([1-9]*)0+$/, '.$1') : "";
      }}

      function fillForm(pair) {{
        if (!pair || !configs[pair]) return;
        const cfg = configs[pair];
        document.getElementById("pair").value = cfg.pair;
        document.getElementById("timeframe").value = cfg.timeframe;
        document.getElementById("budget_pct").value = toPercentInput(cfg.budget_pct);
        document.getElementById("enable_w_shape_filter").checked = cfg.enable_w_shape_filter;
        document.getElementById("enable_leading_signal").checked = cfg.enable_leading_signal;

        document.getElementById("per_trade_cap_pct").value = toPercentInput(cfg.risk.per_trade_cap_pct);

        document.getElementById("lead_red_min_bars").value = cfg.rule_params.lead_red_min_bars;
        document.getElementById("lead_red_max_bars").value = cfg.rule_params.lead_red_max_bars;
        document.getElementById("leading_momentum_lookback").value = cfg.rule_params.leading_momentum_lookback;
        document.getElementById("higher_low_min_diff_pct").value = cfg.rule_params.higher_low_min_diff_pct;
        document.getElementById("higher_low_max_bars_between").value = cfg.rule_params.higher_low_max_bars_between;
        document.getElementById("w_window_bars").value = cfg.rule_params.w_window_bars;
      }}

      function renderConfigsView() {{
        const list = Object.values(configs).sort((a, b) => a.pair.localeCompare(b.pair));
        if (pairSelect) {{
          pairSelect.innerHTML = '<option value="">เลือก pair ที่มี</option>' + list.map(cfg => `<option value="${{cfg.pair}}">${{cfg.pair}}</option>`).join("");
        }}
        if (pairOptionsList) {{
          pairOptionsList.innerHTML = basePairOptions + list.map(cfg => `<option value="${{cfg.pair}}"></option>`).join("");
        }}
        if (configTableBody) {{
          if (!list.length) {{
            configTableBody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:1rem;">ยังไม่มี config</td></tr>';
          }} else {{
            configTableBody.innerHTML = list.map(cfg => `
              <tr data-pair="${{cfg.pair}}">
                <td>${{cfg.pair}}</td>
                <td>${{cfg.timeframe}}</td>
                <td>${{(cfg.budget_pct * 100).toFixed(2)}}%</td>
                <td>${{cfg.enable_w_shape_filter ? "✅" : "❌"}}</td>
                <td>${{cfg.enable_leading_signal ? "✅" : "❌"}}</td>
                <td><button type="button" class="delete-btn" data-pair="${{cfg.pair}}" title="ลบ config นี้">🗑️</button></td>
              </tr>
            `).join("");
          }}
        }}
      }}

      renderConfigsView();

      if (pairSelect) {{
        pairSelect.addEventListener("change", (event) => {{
          fillForm(event.target.value);
        }});
      }}

      const advButton = document.getElementById("toggle-advanced");
      const advSection = document.getElementById("advanced-settings");
      if (advButton && advSection) {{
        advButton.addEventListener("click", () => {{
          const visible = advSection.style.display === "block";
          advSection.style.display = visible ? "none" : "block";
          advButton.textContent = visible ? "⚙️ Advance Settings" : "🔽 Hide Advance Settings";
        }});
      }}

      document.getElementById("config-form").addEventListener("submit", async (event) => {{
        event.preventDefault();
        setStatus("กำลังบันทึก...", true);

        const payload = {{
          config: {{
            pair: document.getElementById("pair").value.toUpperCase(),
            timeframe: document.getElementById("timeframe").value,
            budget_pct: (() => {{
              const raw = parseFloat(document.getElementById("budget_pct").value);
              return isNaN(raw) ? 0 : raw / 100;
            }})(),
            enable_w_shape_filter: document.getElementById("enable_w_shape_filter").checked,
            enable_leading_signal: document.getElementById("enable_leading_signal").checked,
            risk: {{
              per_trade_cap_pct: (() => {{
                const raw = parseFloat(document.getElementById("per_trade_cap_pct").value);
                return isNaN(raw) ? 0 : raw / 100;
              }})()
            }},
            rule_params: {{
              lead_red_min_bars: parseInt(document.getElementById("lead_red_min_bars").value),
              lead_red_max_bars: parseInt(document.getElementById("lead_red_max_bars").value),
              leading_momentum_lookback: parseInt(document.getElementById("leading_momentum_lookback").value),
              higher_low_min_diff_pct: parseFloat(document.getElementById("higher_low_min_diff_pct").value),
              higher_low_max_bars_between: parseInt(document.getElementById("higher_low_max_bars_between").value),
              w_window_bars: parseInt(document.getElementById("w_window_bars").value)
            }}
          }}
        }};

        try {{
          const resp = await fetch("/config", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});

          if (!resp.ok) {{
            let message = "บันทึกไม่สำเร็จ";
            try {{
              const error = await resp.json();
              message = typeof error === "string" ? error : (error.detail || JSON.stringify(error));
            }} catch (_err) {{}}
            throw new Error(message);
          }}

          const savedPair = payload.config.pair;
          configs[savedPair] = payload.config;
          renderConfigsView();
          fillForm(savedPair);
          setStatus("บันทึกสำเร็จ!", true);
        }} catch (err) {{
          setStatus(err.message, false);
        }}
      }});

      if (configTableBody) {{
        configTableBody.addEventListener("click", async (event) => {{
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          if (!target.classList.contains("delete-btn")) return;
          const pair = target.getAttribute("data-pair");
          if (!pair) return;
          if (!confirm(`ต้องการลบ config สำหรับ ${{pair}} หรือไม่?`)) return;
          try {{
            const resp = await fetch(`/config?pair=${{encodeURIComponent(pair)}}`, {{ method: "DELETE" }});
            if (!resp.ok) {{
              const err = await resp.json();
              throw new Error(err.detail || "ลบไม่สำเร็จ");
            }}
            delete configs[pair];
            renderConfigsView();
            setStatus(`ลบ ${{pair}} แล้ว`, true);
          }} catch (err) {{
            setStatus(err.message, false);
          }}
        }});
      }}
    </script>
  </body>
</html>
"""


def _render_config_row(cfg: TradingConfiguration) -> str:
    return f"""
      <tr data-pair="{cfg.pair}">
        <td>{cfg.pair}</td>
        <td>{cfg.timeframe}</td>
        <td>{cfg.budget_pct * 100:.2f}%</td>
        <td>{"✅" if cfg.enable_w_shape_filter else "❌"}</td>
        <td>{"✅" if cfg.enable_leading_signal else "❌"}</td>
        <td><button type="button" class="delete-btn" data-pair="{cfg.pair}" title="ลบ config นี้">🗑️</button></td>
      </tr>
    """


__all__ = ["render_config_portal"]
