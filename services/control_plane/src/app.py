from __future__ import annotations

import time
from typing import Dict

# allow absolute imports for libs/
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = Path(__file__).resolve().parent

for path in (REPO_ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from routes import config, kill_switch, rules, positions, market, live_rules
from routes.config import _db as config_store
from telemetry.config_metrics import ConfigMetrics
from telemetry.rule_metrics import RuleMetrics
from ui.dashboard import render_dashboard
from ui.config_portal import render_config_portal
from ui.layout import render_page
from reports.success_dashboard import build_success_dashboard
from ui.report_views import render_report

app = FastAPI(title="CDC Zone Control Plane")
app.include_router(config.router)
app.include_router(kill_switch.router)
app.include_router(rules.router)
app.include_router(positions.router)
app.include_router(market.router)
app.include_router(live_rules.router)

config_metrics = ConfigMetrics()
rule_metrics = RuleMetrics()


class RuleMetricRequest(BaseModel):
    rule_name: str
    passed: bool


class ConfigMetricRequest(BaseModel):
    duration_seconds: float
    success: bool = True


@app.get("/", tags=["health"])
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/telemetry/rules", tags=["telemetry"])
def record_rule_metric(payload: RuleMetricRequest) -> Dict[str, str]:
    rule_metrics.record(payload.rule_name, payload.passed)
    return {"status": "recorded"}


@app.post("/telemetry/config", tags=["telemetry"])
def record_config_metric(payload: ConfigMetricRequest) -> Dict[str, str]:
    config_metrics.record(payload.duration_seconds, payload.success)
    return {"status": "recorded"}


@app.get("/dashboard", response_class=HTMLResponse, tags=["ui"])
def dashboard() -> HTMLResponse:
    # Get rule evaluation status from rules router
    from routes.rules import _latest_results
    from routes.positions import _position_repo

    rule_snapshot = {rule: count for rule, count in rule_metrics.counts.items()}

    # Get actual position states
    positions_list = _position_repo.list_all()
    position_state = {
        "status": "multiple" if len(positions_list) > 1 else (positions_list[0].status.value if positions_list else "no positions"),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "positions": {pos.pair: pos.status.value for pos in positions_list}
    }

    # Convert latest results to dashboard format
    rules_status = {}
    for pair, result in _latest_results.items():
        rules_status[pair] = {
            "all_passed": result.all_passed,
            "rules": {
                "CDC Green": result.rule_1_cdc_green.passed,
                "Leading Red": result.rule_2_leading_red.passed,
                "Leading Signal": result.rule_3_leading_signal.passed,
                "Pattern (W/V)": result.rule_4_pattern.passed,
            }
        }

    text = render_dashboard(
        rule_snapshot=rule_snapshot,
        position_state=position_state,
        rules_status=rules_status,
    )
    chart_section = build_chart_section()
    body_html = f"""
    <div class="dashboard-text">
      <pre style='font-family: "IBM Plex Mono", Menlo, monospace; font-size: 0.95rem;'>{text}</pre>
    </div>
    {chart_section}
    """
    extra_style = """
      .dashboard-text pre { background: #fff; border-radius: 12px; padding: 1rem; box-shadow: 0 4px 16px rgba(15,23,42,0.08); }
      .chart-card { margin-top: 1.5rem; background: #fff; border-radius: 16px; padding: 1.5rem; box-shadow: 0 12px 30px rgba(15,23,42,0.08); }
      .chart-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
      .chart-header select { padding: 0.4rem 0.8rem; border-radius: 8px; border: 1px solid #d5dbe3; }
      canvas { max-height: 360px; }
    """
    return HTMLResponse(render_page(body_html, title="CDC Zone Dashboard", extra_style=extra_style))


def build_chart_section() -> str:
    pairs = sorted(config_store.keys())
    if not pairs:
        return "<p style='margin-top:1.5rem;'>ยังไม่มี Config กรุณาตั้งค่าอย่างน้อย 1 คู่เพื่อดูกราฟราคา</p>"

    options = "".join(f'<option value="{pair}">{pair}</option>' for pair in pairs)
    return f"""
    <div class="chart-card">
      <div class="chart-header">
        <h2 style="margin:0;">📈 กราฟราคาล่าสุด</h2>
        <div>
          <label for="chart-pair" style="margin-right:0.5rem;">เลือกคู่</label>
          <select id="chart-pair">{options}</select>
        </div>
      </div>
      <canvas id="market-chart"></canvas>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.6"></script>
    <script>
      const chartPairSelect = document.getElementById("chart-pair");
      let marketChart = null;
      async function loadMarketChart(pair) {{
        try {{
          const resp = await fetch(`/market/candles?pair=${{encodeURIComponent(pair)}}&interval=1h&limit=60`);
          if (!resp.ok) {{
            throw new Error("ไม่สามารถดึงข้อมูลราคาได้");
          }}
          const data = await resp.json();
          const candles = data.candles || [];
          const labels = candles.map(c => new Date(c.open_time).toLocaleTimeString());
          const closes = candles.map(c => c.close);
          const colors = candles.map(c => c.close >= c.open ? "#16a34a" : "#dc2626");
          const ctx = document.getElementById("market-chart").getContext("2d");
          if (marketChart) {{
            marketChart.destroy();
          }}
          marketChart = new Chart(ctx, {{
            type: "bar",
            data: {{
              labels,
              datasets: [{{
                label: "ราคา Close",
                data: closes,
                backgroundColor: colors,
                borderRadius: 4,
              }}],
            }},
            options: {{
              responsive: true,
              plugins: {{
                legend: {{ display: false }},
              }},
              scales: {{
                x: {{
                  ticks: {{ maxTicksLimit: 12 }},
                }},
                y: {{
                  title: {{ display: true, text: "ราคา" }},
                  beginAtZero: false,
                }},
              }},
            }},
          }});
        }} catch (err) {{
          console.error(err);
        }}
      }}

      chartPairSelect.addEventListener("change", (e) => loadMarketChart(e.target.value));
      loadMarketChart(chartPairSelect.value);
    </script>
    """


@app.get("/reports/success", tags=["reports"])
def success_report() -> Dict:
    return build_success_dashboard(config_metrics, rule_metrics)


@app.get("/reports/orders", response_class=HTMLResponse, tags=["reports"])
def order_report_view() -> HTMLResponse:
    orders = [{"pair": "BTC/THB", "status": "closed", "pnl": 0.5}]
    inner = render_report(orders).replace("\n", "<br/>")
    return HTMLResponse(render_page(inner, title="CDC Zone Orders Report"))


@app.get("/ui/config", response_class=HTMLResponse, tags=["ui"])
def config_portal() -> HTMLResponse:
    """Simple HTML UI for managing configurations."""
    from routes.config import _db

    configs = list(_db.values())
    html = render_config_portal(configs)
    return HTMLResponse(html)
