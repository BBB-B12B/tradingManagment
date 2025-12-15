from __future__ import annotations

import json
import os
import time
from typing import Dict, Any

# allow absolute imports for libs/
import sys
from pathlib import Path
import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = Path(__file__).resolve().parent

for path in (REPO_ROOT, SRC_DIR):
    if str(path) not in sys.path:
        sys.path.append(str(path))

# Load environment as early as possible so downstream routers see the values
ENV_NAME = os.getenv("APP_ENV") or os.getenv("ENV") or "dev"
ENV_FILE = REPO_ROOT / ".env" / f".env.{ENV_NAME}"


def _load_env_file(path: Path) -> bool:
    """Lightweight .env loader (avoids new deps). Returns True if loaded."""
    if not path.exists():
        return False
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key and key not in os.environ:
            os.environ[key.strip()] = value.strip()
    return True


ENV_LOADED = _load_env_file(ENV_FILE)

# Reload worker settings after env is loaded
WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")

# Third-party imports (after env load for ccxt options)
import ccxt
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="CDC Zone Control Plane")

from routes import config, kill_switch, rules, positions, market, live_rules, backtest, fibonacci, bot, order_sync, order_admin, system
from routes.config import _db as config_store, _load_configs_from_d1
from telemetry.config_metrics import ConfigMetrics
from telemetry.rule_metrics import RuleMetrics
from ui.dashboard import render_dashboard
from ui.config_portal import render_config_portal
from ui.layout import render_page
from ui.backtest_view import render_backtest_view
from ui.account_link import render_account_link
from ui.bot_runner import render_bot_runner
from reports.success_dashboard import build_success_dashboard
from ui.report_views import render_report


def _make_testnet_client(api_key: str, api_secret: str) -> ccxt.binance:
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="BINANCE_API_KEY/SECRET is required")
    client = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "options": {"defaultType": "spot"},
    })
    # Sandbox mode points to testnet.binance.vision for spot
    client.set_sandbox_mode(True)
    return client


def _worker_headers() -> Dict[str, str]:
    if WORKER_TOKEN:
        return {"Authorization": f"Bearer {WORKER_TOKEN}"}
    return {}


def _post_order_to_worker(payload: Dict[str, Any]) -> None:
    """Best-effort log order to worker/D1."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(f"{WORKER_URL}/orders", json=payload, headers=_worker_headers())
            resp.raise_for_status()
    except Exception as exc:  # pragma: no cover - logging only
        print(f"[WARN] Failed to log order to worker: {exc}")


@app.on_event("startup")
async def startup_event():
    """Load configs from D1 on startup and restore scheduler if needed"""
    print("Loading configs from D1...")
    await _load_configs_from_d1()
    print(f"Loaded {len(config_store)} configs from D1")

    # Auto-restore scheduler if it was running before reload
    scheduler_state_file = SRC_DIR / ".scheduler_state.json"
    if scheduler_state_file.exists():
        try:
            state = json.loads(scheduler_state_file.read_text())
            print(f"🔄 Restoring scheduler: {state.get('pairs')} @ {state.get('interval_minutes')}min")

            # Import and restore scheduler via the bot module
            from routes import bot
            from trading.scheduler import TradingScheduler

            # Create new scheduler instance and set it in bot module
            bot._trading_scheduler = TradingScheduler()

            # Restore with saved config
            await bot._trading_scheduler.start(
                pairs=state.get("pairs", []),
                interval_minutes=state.get("interval_minutes", 1.0)
            )
            print("✅ Scheduler restored successfully")
        except Exception as e:
            print(f"⚠️ Failed to restore scheduler: {e}")
            # Clean up state file if restore fails
            scheduler_state_file.unlink(missing_ok=True)


app.include_router(config.router)
app.include_router(kill_switch.router)
app.include_router(rules.router)
app.include_router(positions.router)
app.include_router(market.router)
app.include_router(live_rules.router)
app.include_router(backtest.router)
app.include_router(fibonacci.router)
app.include_router(bot.router)
app.include_router(order_sync.router)
app.include_router(order_admin.router)
app.include_router(system.router)
app.add_api_route("/worker/orders", order_sync.fetch_worker_orders, methods=["GET"])

config_metrics = ConfigMetrics()
rule_metrics = RuleMetrics()


class RuleMetricRequest(BaseModel):
    rule_name: str
    passed: bool


class ConfigMetricRequest(BaseModel):
    duration_seconds: float
    success: bool = True


class TestOrderRequest(BaseModel):
    symbol: str = "BTC/USDT"
    side: str = "buy"
    amount: float = 0.0001
    type: str = "market"
    price: float | None = None


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


@app.post("/test/binance-order", tags=["test"])
def test_binance_order(payload: TestOrderRequest) -> Dict[str, Any]:
    """Send a tiny market order to Binance Testnet using env keys."""
    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="Missing BINANCE_API_KEY / BINANCE_API_SECRET (testnet HMAC key required)")

    client = _make_testnet_client(api_key, api_secret)

    symbol = payload.symbol.upper()
    side = payload.side.lower()
    amount = float(payload.amount)
    order_type = payload.type.lower() if payload.type else "market"
    price = float(payload.price) if payload.price is not None else None

    if side not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="side must be 'buy' or 'sell'")
    if amount <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")
    if order_type not in {"market", "limit"}:
        raise HTTPException(status_code=400, detail="type must be 'market' or 'limit'")
    if order_type == "limit" and (price is None or price <= 0):
        raise HTTPException(status_code=400, detail="price must be provided for limit orders")

    try:
        markets = client.load_markets()
        if symbol not in markets:
            raise HTTPException(status_code=400, detail=f"Symbol {symbol} not supported on Binance")
        m = markets[symbol]
        lot_filter = {}
        for f in m.get("info", {}).get("filters", []):
            if f.get("filterType") == "LOT_SIZE":
                lot_filter = f
                break
        min_amount = float(lot_filter.get("minQty") or m["limits"]["amount"].get("min") or 0)
        step_size = float(lot_filter.get("stepSize") or m["limits"]["amount"].get("step") or 0)
        if amount < min_amount:
            raise HTTPException(status_code=400, detail=f"Amount {amount} below min lot {min_amount}")
        if step_size:
            q = amount / step_size
            if abs(q - round(q)) > 1e-8:
                raise HTTPException(status_code=400, detail=f"Amount {amount} not aligned to step size {step_size}")
        if price is None:
            price = client.fetch_ticker(symbol)["last"] or client.price_to_precision(symbol, 1)
        notional = price * amount
        min_notional = m["limits"]["cost"]["min"] or 0
        if min_notional and notional < min_notional:
            raise HTTPException(status_code=400, detail=f"Notional {notional:.6f} below min {min_notional}")
        # Ensure precision
        amount = float(client.amount_to_precision(symbol, amount))

        if order_type == "limit":
            order = client.create_order(symbol=symbol, type="limit", side=side, amount=amount, price=price)
        else:
            order = client.create_order(symbol=symbol, type="market", side=side, amount=amount)
        info = order.get("info") or {}
        filled_qty = float(info.get("executedQty") or amount)
        avg_price = None
        try:
            quote = float(info.get("cummulativeQuoteQty") or 0)
            if filled_qty:
                avg_price = quote / filled_qty
        except Exception:
            avg_price = None

        worker_payload = {
            "pair": symbol.upper(),
            "order_type": "ENTRY" if side.lower() == "buy" else "EXIT",
            "side": side.upper(),
            "requested_qty": amount,
            "filled_qty": filled_qty,
            "avg_price": avg_price or price,
            "order_id": info.get("orderId") or order.get("id"),
            "status": info.get("status") or "UNKNOWN",
            "entry_reason": "TEST_ENDPOINT",
            "exit_reason": None,
            "rule_1_cdc_green": False,
            "rule_2_leading_red": False,
            "rule_3_leading_signal": False,
            "rule_4_pattern": False,
            "entry_price": avg_price or price,
            "exit_price": None,
            "pnl": None,
            "pnl_pct": None,
            "w_low": None,
            "sl_price": None,
            "requested_at": info.get("transactTime"),
            "filled_at": info.get("transactTime"),
        }
        _post_order_to_worker(worker_payload)

        return {
            "status": "ok",
            "order_id": info.get("orderId") or order.get("id"),
            "symbol": symbol,
            "side": side,
            "amount": order.get("amount") or amount,
            "info": info,
        }
    except ccxt.BaseError as exc:
        raise HTTPException(status_code=502, detail=f"Binance testnet error: {exc}") from exc


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
      .chart-header h2 { font-size: 1.25rem; font-weight: 600; color: #0f172a; }
      .chart-header select { padding: 0.5rem 1rem; border-radius: 8px; border: 1px solid #cbd5e1; font-size: 0.95rem; background: #f8fafc; }
      .chart-header select:hover { background: #f1f5f9; border-color: #94a3b8; }
      #tv-chart { border-radius: 8px; }
    """
    return HTMLResponse(render_page(body_html, title="CDC Zone Dashboard", extra_style=extra_style))




def build_chart_section() -> str:
    pairs = sorted(config_store.keys())
    if not pairs:
        return "<p style='margin-top:1.5rem;'>ยังไม่มี Config กรุณาตั้งค่าอย่างน้อย 1 คู่เพื่อดูกราฟราคา</p>"

    options = "".join(f'<option value="{pair}">{pair}</option>' for pair in pairs)
    chart_html = """
    <div class="chart-card">
      <div class="chart-header">
        <h2 style="margin:0;">📈 กราฟราคาล่าสุด (Candlestick)</h2>
        <div style="display: flex; gap: 1rem; align-items: center;">
          <div>
            <label for="timeframe-select" style="margin-right:0.5rem;">Chart View</label>
            <select id="timeframe-select">
              <option value="1w">1W (Weekly)</option>
              <option value="1d" selected>1D (Daily)</option>
              <option value="1h">1H (Hourly)</option>
            </select>
          </div>
          <div>
            <label for="signal-mode" style="margin-right:0.5rem;">Signal Mode</label>
            <select id="signal-mode">
              <option value="simple">Simple (Zone Only)</option>
              <option value="advanced">Advanced (Full Rules)</option>
            </select>
          </div>
          <div>
            <label for="chart-pair" style="margin-right:0.5rem;">เลือกคู่</label>
            <select id="chart-pair">__PAIR_OPTIONS__</select>
          </div>
        </div>
      </div>
      <div id="tv-chart" style="width: 100%; height: 640px; position: relative; margin-bottom: 20px;">
        <!-- Custom Tooltip -->
        <div id="chart-tooltip" style="
          position: absolute;
          display: none;
          padding: 8px 12px;
          background: rgba(255, 255, 255, 0.95);
          border: 1px solid #cbd5e1;
          border-radius: 8px;
          box-shadow: 0 4px 12px rgba(0,0,0,0.1);
          font-size: 12px;
          line-height: 1.5;
          pointer-events: none;
          z-index: 1000;
          max-width: 300px;
        "></div>
      </div>

    </div>

    <!-- Lightweight Charts (TradingView) - Using specific version 4.1.3 -->
    <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>

    <script>
      const chartContainer = document.getElementById("tv-chart");
      const tooltipEl = document.getElementById("chart-tooltip");
      const pairSelect = document.getElementById("chart-pair");
      const signalModeSelect = document.getElementById("signal-mode");
      const timeframeSelect = document.getElementById("timeframe-select");

      let tvChart = null;
      let candleSeries = null;
      let emaFastSeries = null;
      let emaSlowSeries = null;
      let zoneSeries = [];
      let rsiSeries = null;
      let rsiOverboughtSeries = null;
      let rsiOversoldSeries = null;
      let rsiMinMaxSeries = null; // Hidden series to set RSI scale range

      // Store candle and marker data for tooltips
      let candleData = [];
      let markerDataMap = new Map(); // timestamp -> marker info
      let rsiData = []; // Store RSI values for divergence detection
      let divergenceLines = []; // Store divergence line series
      let detectedDivergences = []; // Store detected divergences for display
      let candleStates = []; // Store Strong_Buy/Strong_Sell states for each candle
      let buyArrowMarkers = []; // Store BUY arrow positions for click detection
      let trailingStopDataMap = new Map(); // timestamp -> trailing stop info (SL price, activation status)

      // Store multi-timeframe data globally for tooltip access
      let data1w = null;
      let data1d = null;
      let data1h = null;

      // Remove candles that have null/NaN prices or EMA to avoid chart errors
      function sanitizeCandles(rawCandles, label) {
        const cleaned = [];
        let dropped = 0;

        (rawCandles || []).forEach((c, idx) => {
          const openTime = typeof c.open_time === "number" ? c.open_time : Number(c.open_time);
          const numericFields = [c.open, c.high, c.low, c.close, c.ema_fast, c.ema_slow, openTime];
          const hasAllNumbers = numericFields.every(v => Number.isFinite(v));

          if (!hasAllNumbers) {
            dropped += 1;
            console.warn(`⚠️ Dropping invalid candle in ${label} at index ${idx}:`, c);
            return;
          }

          cleaned.push({ ...c, open_time: openTime });
        });

        if (dropped > 0) {
          console.warn(`⚠️ Sanitized ${label}: dropped ${dropped} invalid candles, kept ${cleaned.length}`);
        }
        return cleaned;
      }

      // Fixed 3-Timeframe System: 1W → 1D → 1H
      // Always fetch these 3 timeframes for multi-timeframe validation

      const zoneColors = {
        green: { body: 'rgba(16, 185, 129, 0.5)', wick: '#10b981', border: '#10b981' },
        red: { body: 'rgba(239, 68, 68, 0.5)', wick: '#ef4444', border: '#ef4444' },
        blue: { body: 'rgba(59, 130, 246, 0.35)', wick: '#3b82f6', border: '#3b82f6' },
        lblue: { body: 'rgba(56, 189, 248, 0.35)', wick: '#06b6d4', border: '#06b6d4' },
        orange: { body: 'rgba(249, 115, 22, 0.35)', wick: '#f97316', border: '#f97316' },
        yellow: { body: 'rgba(234, 179, 8, 0.35)', wick: '#eab308', border: '#eab308' },
      };

      const zoneFill = {
        green: { top: 'rgba(34, 197, 94, 0.12)', bottom: 'rgba(34, 197, 94, 0)' },
        red: { top: 'rgba(239, 68, 68, 0.12)', bottom: 'rgba(239, 68, 68, 0)' },
        blue: { top: 'rgba(59, 130, 246, 0.08)', bottom: 'rgba(59, 130, 246, 0)' },
        lblue: { top: 'rgba(56, 189, 248, 0.16)', bottom: 'rgba(56, 189, 248, 0)' },
        orange: { top: 'rgba(249, 115, 22, 0.18)', bottom: 'rgba(249, 115, 22, 0)' },
        yellow: { top: 'rgba(234, 179, 8, 0.18)', bottom: 'rgba(234, 179, 8, 0)' },
      };

      const isGreenZone = (z) => z === 'green';
      const isRedZone = (z) => z === 'red';

      // Calculate EMA helper function
      function calculateEMA(values, period) {
        if (!values || values.length === 0) return [];
        const alpha = 2 / (period + 1);
        const result = [];
        let ema = values[0];
        result.push(ema);
        for (let i = 1; i < values.length; i++) {
          ema = alpha * values[i] + (1 - alpha) * ema;
          result.push(ema);
        }
        return result;
      }

      // Calculate RSI
      function calculateRSI(closes, period = 14) {
        if (!closes || closes.length < period + 1) return [];

        const changes = [];
        for (let i = 1; i < closes.length; i++) {
          changes.push(closes[i] - closes[i - 1]);
        }

        const gains = changes.map(c => c > 0 ? c : 0);
        const losses = changes.map(c => c < 0 ? Math.abs(c) : 0);

        // Calculate first average gain/loss
        let avgGain = 0;
        let avgLoss = 0;
        for (let i = 0; i < period; i++) {
          avgGain += gains[i];
          avgLoss += losses[i];
        }
        avgGain /= period;
        avgLoss /= period;

        const rsi = [];
        // First RSI value
        const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
        rsi.push(100 - (100 / (1 + rs)));

        // Calculate subsequent RSI values using smoothed average
        for (let i = period; i < changes.length; i++) {
          avgGain = ((avgGain * (period - 1)) + gains[i]) / period;
          avgLoss = ((avgLoss * (period - 1)) + losses[i]) / period;

          const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
          const rsiValue = 100 - (100 / (1 + rs));
          rsi.push(rsiValue);
        }

        return rsi;
      }

      // Detect RSI Divergence แบบ State Machine (ปรับปรุงแล้ว)
      // คำว่า "ไม่ติดกัน" หมายถึง ต้องออกจากโซนสุดขั้วก่อน (RSI กลับเข้าโซนปกติ) แล้วจึงกลับเข้าโซนสุดขั้วอีกครั้ง
      // ปรับให้ flexible: Zone 2 ไม่จำเป็นต้องเข้าโซนสุดขั้วเต็ม แค่ใกล้เคียงก็พอ (68.5/31.5)
      function detectDivergence(priceData, rsiData, zoneData) {
        const divergences = [];
        const candleStates = [];

        if (!priceData || !rsiData || !zoneData || priceData.length < 30) {
          console.log("⚠️ Not enough data for divergence detection");
          return { divergences, candleStates };
        }

        console.log("🔍 Starting Zone-based divergence detection with", priceData.length, "candles");
        console.log("📊 RSI Data points:", rsiData.length);
        console.log("📊 Zone Data points:", zoneData.length);

        // Thresholds
        const OVERSOLD_THRESHOLD = 30;           // Zone 1 ต้องต่ำกว่า 30
        const NEAR_OVERSOLD_THRESHOLD = 35;      // Zone 2 ต่ำกว่าหรือเท่ากับ 35 (ปรับจาก 31.5)
        const OVERBOUGHT_THRESHOLD = 70;         // Zone 1 ต้องสูงกว่า 70
        const NEAR_OVERBOUGHT_THRESHOLD = 65;    // Zone 2 สูงกว่าหรือเท่ากับ 65 (ปรับจาก 68.5)
        const MIN_CANDLES_BETWEEN_ZONES = 10;    // ระยะห่างขั้นต่ำระหว่าง Zone 1 และ Zone 2

        // Bullish Divergence State (Oversold < 30 สำหรับ Zone 1, <= 35 สำหรับ Zone 2)
        let bullishCurrentZone = []; // แท่งปัจจุบันที่อยู่ใน oversold
        let bullishNearZone = [];    // แท่งที่อยู่ใกล้ oversold (Zone 2 <= 35)
        let bullishPreviousZone = null; // จุดต่ำสุดของโซน oversold ก่อนหน้า
        let bullishPreviousTrendType = null; // 'bear' หรือ 'bull' - ชัดเจนกว่า boolean
        let bullishActive = false;
        let bullishDivPoint = null;
        let bullishWaitingForNearZone = false; // รอ Zone 2 ที่ใกล้เคียง

        // Bearish Divergence State (Overbought > 70 สำหรับ Zone 1, >= 65 สำหรับ Zone 2)
        let bearishCurrentZone = []; // แท่งปัจจุบันที่อยู่ใน overbought
        let bearishNearZone = [];    // แท่งที่อยู่ใกล้ overbought (Zone 2 >= 65)
        let bearishPreviousZone = null; // จุดสูงสุดของโซน overbought ก่อนหน้า
        let bearishPreviousTrendType = null; // 'bear' หรือ 'bull' - ชัดเจนกว่า boolean
        let bearishActive = false;
        let bearishDivPoint = null;
        let bearishWaitingForNearZone = false; // รอ Zone 2 ที่ใกล้เคียง

        for (let i = 0; i < priceData.length; i++) {
          if (!priceData[i] || !rsiData[i] || !zoneData[i]) continue;

          const candle = priceData[i];
          const rsi = rsiData[i].value;
          const zone = zoneData[i];
          const timestamp = typeof candle.open_time === "number"
            ? Math.floor(candle.open_time / 1000)
            : candle.open_time;

          const isBullish = zone.ema_fast > zone.ema_slow;
          const isBearish = zone.ema_fast < zone.ema_slow;

          const state = {
            index: i,
            time: timestamp,
            strong_sell: 'none-Active',
            strong_buy: 'none-Active',
            special_signal: null,
            cutloss: null
          };

          // === BULLISH DIVERGENCE (Oversold < 30 สำหรับ Zone 1, <= 35 สำหรับ Zone 2) ===
          if (!bullishActive) {
            // Zone 1: ต้องต่ำกว่า 30 (extreme oversold)
            if (rsi < OVERSOLD_THRESHOLD) {
              bullishCurrentZone.push({
                index: i,
                time: timestamp,
                rsi: rsi,
                price: candle.low  // ✅ ใช้ราคาต่ำสุด (low) สำหรับ Bullish Divergence
              });
            }
            // ออกจาก Zone 1 แล้ว (RSI >= 30)
            else if (bullishCurrentZone.length > 0 && rsi >= OVERSOLD_THRESHOLD) {
              // จบ Zone 1 - หาจุดต่ำสุด
              const lowestPoint = bullishCurrentZone.reduce((min, p) => p.rsi < min.rsi ? p : min);
              console.log(`📉 Oversold Zone 1 ended. Lowest RSI: ${lowestPoint.rsi.toFixed(2)} at index ${lowestPoint.index}, Trend: ${isBearish ? 'Bear' : 'Bull'}`);

              // เก็บเป็น Previous Zone (ถ้ายังไม่มี หรือ Zone ใหม่ต่ำกว่า Zone เก่า)
              if (!bullishPreviousZone || lowestPoint.rsi < bullishPreviousZone.rsi) {
                bullishPreviousZone = lowestPoint;
                bullishPreviousTrendType = isBearish ? 'bear' : 'bull'; // ✅ ชัดเจนกว่า
                console.log(`   → Set as new Zone 1 baseline for Bullish Divergence (Trend: ${isBearish ? 'Bear' : 'Bull'})`);
              }
              bullishCurrentZone = [];
              bullishWaitingForNearZone = true;
              bullishNearZone = [];
            }

            // ✅ ถ้ากำลังรอ Zone 2 แต่เจอ Extreme Oversold ใหม่ (RSI < 30) → อัพเดท Zone 1
            if (bullishWaitingForNearZone && rsi < OVERSOLD_THRESHOLD && isBearish) {
              // เก็บจุดใหม่ที่แรงกว่า (RSI ต่ำกว่า)
              if (!bullishPreviousZone || rsi < bullishPreviousZone.rsi) {
                console.log(`🔄 Found stronger Zone 1: RSI ${rsi.toFixed(2)} < previous ${bullishPreviousZone ? bullishPreviousZone.rsi.toFixed(2) : 'N/A'} → Update Zone 1`);
                bullishPreviousZone = {
                  index: i,
                  time: timestamp,
                  rsi: rsi,
                  price: candle.low
                };
                bullishPreviousTrendType = 'bear';
                bullishNearZone = []; // Reset Zone 2 เพราะมี Zone 1 ใหม่
              }
            }

            // ตรวจสอบว่า Trend เปลี่ยนหรือไม่ (EMA crossover) → Reset
            if (bullishWaitingForNearZone && bullishPreviousTrendType !== null) {
              // ถ้า Zone 1 เป็น Bear แต่ตอนนี้กลายเป็น Bull → Reset
              if (bullishPreviousTrendType === 'bear' && !isBearish) {
                console.log(`⚠️ Trend changed from Bear to Bull → Reset Bullish Divergence tracking`);
                bullishPreviousZone = null;
                bullishPreviousTrendType = null;
                bullishNearZone = [];
                bullishWaitingForNearZone = false;
              }
            }

            // รอ Zone 2: RSI ย่อกลับมาใกล้ oversold (<= 35) หลังจากมี Zone 1 แล้ว
            if (bullishWaitingForNearZone && rsi <= NEAR_OVERSOLD_THRESHOLD && isBearish) {
              bullishNearZone.push({
                index: i,
                time: timestamp,
                rsi: rsi,
                price: candle.low  // ✅ ใช้ราคาต่ำสุด (low)
              });
            }
            // ออกจาก Near Zone 2 แล้ว (RSI > 35) → ตรวจจับ Divergence
            else if (bullishWaitingForNearZone && bullishNearZone.length > 0 && rsi > NEAR_OVERSOLD_THRESHOLD) {
              const lowestNearPoint = bullishNearZone.reduce((min, p) => p.rsi < min.rsi ? p : min);
              console.log(`📉 Near-Oversold Zone 2 candidate. Lowest RSI: ${lowestNearPoint.rsi.toFixed(2)} at index ${lowestNearPoint.index}`);

              // ✅ เช็คระยะห่างระหว่าง Zone 1 และ Zone 2
              const tooClose = bullishPreviousZone && lowestNearPoint.index - bullishPreviousZone.index < MIN_CANDLES_BETWEEN_ZONES;
              if (tooClose) {
                console.log(`   ⚠️ Zones too close (${lowestNearPoint.index - bullishPreviousZone.index} candles) → Skip this Zone 2`);
                bullishNearZone = [];
              }

              // เปรียบเทียบ Zone 1 vs Zone 2 (ถ้าไม่ใกล้เกินไป)
              if (!tooClose && bullishPreviousZone && bullishPreviousTrendType === 'bear') {
                // ถ้า Zone 2 มี RSI ต่ำกว่าหรือเท่ากับ Zone 1 → อัพเดท Zone 1 ใหม่
                if (lowestNearPoint.rsi <= bullishPreviousZone.rsi) {
                  console.log(`   → Zone 2 RSI (${lowestNearPoint.rsi.toFixed(2)}) <= Zone 1 RSI (${bullishPreviousZone.rsi.toFixed(2)}) → Update Zone 1`);
                  // ✅ แก้ไข: อัพเดทได้ถ้าต่ำกว่า ไม่ต้องเช็ค OVERSOLD_THRESHOLD
                  bullishPreviousZone = lowestNearPoint;
                  bullishPreviousTrendType = 'bear'; // ยังคงเป็น Bear
                }
                // Zone 2 มี RSI สูงกว่า Zone 1 → เช็ค Divergence
                else if (lowestNearPoint.rsi > bullishPreviousZone.rsi) {
                  const prevLow = bullishPreviousZone.price;
                  const currLow = bullishNearZone.reduce((min, p) => p.price < min.price ? p : min).price;

                  if (currLow < prevLow) {
                    const priceDiff = ((prevLow - currLow) / prevLow * 100).toFixed(2);
                    const rsiDiff = (lowestNearPoint.rsi - bullishPreviousZone.rsi).toFixed(2);

                    console.log(`🟢 BULLISH DIVERGENCE DETECTED!`);
                    console.log(`   Zone 1: Index ${bullishPreviousZone.index}, RSI ${bullishPreviousZone.rsi.toFixed(2)}, Price ${prevLow.toFixed(2)}`);
                    console.log(`   Zone 2: Index ${lowestNearPoint.index}, RSI ${lowestNearPoint.rsi.toFixed(2)}, Price ${currLow.toFixed(2)}`);
                    console.log(`   Distance: ${lowestNearPoint.index - bullishPreviousZone.index} candles`);
                    console.log(`   Price Lower by ${priceDiff}%, RSI Higher by ${rsiDiff}`);
                    console.log(`   Trend: Bear ✓ (maintained throughout)`);

                    divergences.push({
                      type: 'bullish',
                      startIndex: bullishPreviousZone.index,
                      endIndex: lowestNearPoint.index,
                      startTime: bullishPreviousZone.time,
                      endTime: lowestNearPoint.time,
                      priceStart: prevLow,
                      priceEnd: currLow,
                      rsiStart: bullishPreviousZone.rsi,
                      rsiEnd: lowestNearPoint.rsi,
                    });

                    bullishActive = true;
                    bullishDivPoint = lowestNearPoint;

                    // Reset
                    bullishPreviousZone = null;
                    bullishPreviousTrendType = null;
                    bullishWaitingForNearZone = false;
                  } else {
                    console.log(`   → Price not diverging (${currLow.toFixed(2)} >= ${prevLow.toFixed(2)}) → Keep Zone 1, wait for next Zone 2`);
                  }
                }
              }

              bullishNearZone = [];
            }

            // Reset ถ้า RSI ขึ้นสูงเกิน 50 (ออกจากช่วง oversold โดยสิ้นเชิง)
            if (bullishWaitingForNearZone && rsi > 50) {
              console.log(`⚠️ RSI rose above 50 → Reset Bullish Divergence tracking`);
              bullishPreviousZone = null;
              bullishPreviousTrendType = null;
              bullishNearZone = [];
              bullishWaitingForNearZone = false;
            }
          }

          // ถ้า Strong_Buy Active อยู่
          if (bullishActive) {
            state.strong_buy = 'Active';

            // ✅ เงื่อนไขการยืนยันการกลับตัว (Reversal Confirmation)
            // 1. ต้องเข้า Blue Zone (uptrend confirmed)
            // 2. RSI ต้องกลับมาเหนือ 40 (แรงซื้อกลับมา)
            if (zone.zone === 'blue' && rsi > 40) {
              // ✅ คำนวณ Cutloss แบบปรับปรุง - ใช้ swing low ย้อนหลัง 30 แท่ง
              let cutloss = candle.low; // เริ่มจากราคาต่ำสุดปัจจุบัน
              const lookback = 30;

              // หา swing low (จุดต่ำสุด) ย้อนหลัง
              for (let j = i - 1; j >= Math.max(0, i - lookback); j--) {
                if (!priceData[j]) continue;
                if (priceData[j].low < cutloss) {
                  cutloss = priceData[j].low;
                }
              }

              // เพิ่ม safety buffer 2%
              cutloss = cutloss * 0.98;

              // ตรวจสอบว่ามี red zone ย้อนหลังไหม (เพิ่มความปลอดภัย)
              const reds = [];
              for (let j = i - 1; j >= Math.max(0, i - lookback); j--) {
                if (!zoneData[j]) continue;
                if (zoneData[j].zone === 'red') {
                  reds.push(priceData[j].low);
                } else if (reds.length > 0) {
                  break;
                }
              }

              // ถ้าเจอ red zone ให้ใช้จุดต่ำสุดของ red zone (ปลอดภัยกว่า)
              if (reds.length > 0) {
                const redLow = Math.min(...reds) * 0.98;
                cutloss = Math.min(cutloss, redLow);
              }

              state.special_signal = 'BUY';
              state.cutloss = cutloss;
              state.strong_buy = 'none-Active';
              bullishActive = false;
              bullishPreviousZone = null;
              console.log(`🔔 ✅ BUY SIGNAL CONFIRMED at index ${i}`);
              console.log(`   Cutloss: ${cutloss.toFixed(2)} (Swing low with 2% buffer)`);
              console.log(`   RSI: ${rsi.toFixed(2)} (above 40 ✓)`);
              console.log(`   Zone: Blue (uptrend ✓)`);
            }
            // ถ้ายังไม่เข้าเงื่อนไข ให้รอต่อ แต่ถ้า RSI ลงต่ำกว่า 30 อีกครั้ง → ยกเลิกสัญญาณ
            else if (rsi < 30) {
              console.log(`⚠️ RSI dropped below 30 again → Cancel BUY signal (failed reversal)`);
              bullishActive = false;
              bullishPreviousZone = null;
            }
          }

          // === BEARISH DIVERGENCE (Overbought > 70 สำหรับ Zone 1, >= 65 สำหรับ Zone 2) ===
          if (!bearishActive) {
            // Zone 1: ต้องสูงกว่า 70 (extreme overbought)
            if (rsi > OVERBOUGHT_THRESHOLD) {
              bearishCurrentZone.push({
                index: i,
                time: timestamp,
                rsi: rsi,
                price: candle.high  // ✅ ใช้ราคาสูงสุด (high) สำหรับ Bearish Divergence
              });
            }
            // ออกจาก Zone 1 แล้ว (RSI <= 70)
            else if (bearishCurrentZone.length > 0 && rsi <= OVERBOUGHT_THRESHOLD) {
              // จบ Zone 1 - หาจุดสูงสุด
              const highestPoint = bearishCurrentZone.reduce((max, p) => p.rsi > max.rsi ? p : max);
              console.log(`📈 Overbought Zone 1 ended. Highest RSI: ${highestPoint.rsi.toFixed(2)} at index ${highestPoint.index}, Trend: ${isBullish ? 'Bull' : 'Bear'}`);

              // เก็บเป็น Previous Zone (ถ้ายังไม่มี หรือ Zone ใหม่สูงกว่า Zone เก่า)
              if (!bearishPreviousZone || highestPoint.rsi > bearishPreviousZone.rsi) {
                bearishPreviousZone = highestPoint;
                bearishPreviousTrendType = isBullish ? 'bull' : 'bear'; // ✅ ชัดเจนกว่า
                console.log(`   → Set as new Zone 1 baseline for Bearish Divergence (Trend: ${isBullish ? 'Bull' : 'Bear'})`);
              }
              bearishCurrentZone = [];
              bearishWaitingForNearZone = true;
              bearishNearZone = [];
            }

            // ✅ ถ้ากำลังรอ Zone 2 แต่เจอ Extreme Overbought ใหม่ (RSI > 70) → อัพเดท Zone 1
            if (bearishWaitingForNearZone && rsi > OVERBOUGHT_THRESHOLD && isBullish) {
              // เก็บจุดใหม่ที่แรงกว่า
              if (!bearishPreviousZone || rsi > bearishPreviousZone.rsi) {
                console.log(`🔄 Found stronger Zone 1: RSI ${rsi.toFixed(2)} > previous ${bearishPreviousZone ? bearishPreviousZone.rsi.toFixed(2) : 'N/A'} → Update Zone 1`);
                bearishPreviousZone = {
                  index: i,
                  time: timestamp,
                  rsi: rsi,
                  price: candle.high
                };
                bearishPreviousTrendType = 'bull';
                bearishNearZone = []; // Reset Zone 2 เพราะมี Zone 1 ใหม่
              }
            }

            // ตรวจสอบว่า Trend เปลี่ยนหรือไม่ (EMA crossover) → Reset
            if (bearishWaitingForNearZone && bearishPreviousTrendType !== null) {
              // ถ้า Zone 1 เป็น Bull แต่ตอนนี้กลายเป็น Bear → Reset
              if (bearishPreviousTrendType === 'bull' && !isBullish) {
                console.log(`⚠️ Trend changed from Bull to Bear → Reset Bearish Divergence tracking`);
                bearishPreviousZone = null;
                bearishPreviousTrendType = null;
                bearishNearZone = [];
                bearishWaitingForNearZone = false;
              }
            }

            // รอ Zone 2: RSI เด้งกลับมาใกล้ overbought (>= 65) หลังจากมี Zone 1 แล้ว
            if (bearishWaitingForNearZone && rsi >= NEAR_OVERBOUGHT_THRESHOLD && isBullish) {
              bearishNearZone.push({
                index: i,
                time: timestamp,
                rsi: rsi,
                price: candle.high  // ✅ ใช้ราคาสูงสุด (high)
              });
            }
            // ออกจาก Near Zone 2 แล้ว (RSI < 65) → ตรวจจับ Divergence
            else if (bearishWaitingForNearZone && bearishNearZone.length > 0 && rsi < NEAR_OVERBOUGHT_THRESHOLD) {
              const highestNearPoint = bearishNearZone.reduce((max, p) => p.rsi > max.rsi ? p : max);
              console.log(`📈 Near-Overbought Zone 2 candidate. Highest RSI: ${highestNearPoint.rsi.toFixed(2)} at index ${highestNearPoint.index}`);

              // ✅ เช็คระยะห่างระหว่าง Zone 1 และ Zone 2
              const tooCloseBearish = bearishPreviousZone && highestNearPoint.index - bearishPreviousZone.index < MIN_CANDLES_BETWEEN_ZONES;
              if (tooCloseBearish) {
                console.log(`   ⚠️ Zones too close (${highestNearPoint.index - bearishPreviousZone.index} candles) → Skip this Zone 2`);
                bearishNearZone = [];
              }

              // เปรียบเทียบ Zone 1 vs Zone 2 (ถ้าไม่ใกล้เกินไป)
              if (!tooCloseBearish && bearishPreviousZone && bearishPreviousTrendType === 'bull') {
                // ถ้า Zone 2 มี RSI สูงกว่าหรือเท่ากับ Zone 1 → อัพเดท Zone 1 ใหม่
                if (highestNearPoint.rsi >= bearishPreviousZone.rsi) {
                  console.log(`   → Zone 2 RSI (${highestNearPoint.rsi.toFixed(2)}) >= Zone 1 RSI (${bearishPreviousZone.rsi.toFixed(2)}) → Update Zone 1`);
                  // ✅ แก้ไข: อัพเดทได้ถ้าสูงกว่า ไม่ต้องเช็ค OVERBOUGHT_THRESHOLD
                  bearishPreviousZone = highestNearPoint;
                  bearishPreviousTrendType = 'bull'; // ยังคงเป็น Bull
                }
                // Zone 2 มี RSI ต่ำกว่า Zone 1 → เช็ค Divergence
                else if (highestNearPoint.rsi < bearishPreviousZone.rsi) {
                  const prevHigh = bearishPreviousZone.price;
                  const currHigh = bearishNearZone.reduce((max, p) => p.price > max.price ? p : max).price;

                  if (currHigh > prevHigh) {
                    const priceDiff = ((currHigh - prevHigh) / prevHigh * 100).toFixed(2);
                    const rsiDiff = (bearishPreviousZone.rsi - highestNearPoint.rsi).toFixed(2);

                    console.log(`🔴 BEARISH DIVERGENCE DETECTED!`);
                    console.log(`   Zone 1: Index ${bearishPreviousZone.index}, RSI ${bearishPreviousZone.rsi.toFixed(2)}, Price ${prevHigh.toFixed(2)}`);
                    console.log(`   Zone 2: Index ${highestNearPoint.index}, RSI ${highestNearPoint.rsi.toFixed(2)}, Price ${currHigh.toFixed(2)}`);
                    console.log(`   Distance: ${highestNearPoint.index - bearishPreviousZone.index} candles`);
                    console.log(`   Price Higher by ${priceDiff}%, RSI Lower by ${rsiDiff}`);
                    console.log(`   Trend: Bull ✓ (maintained throughout)`);

                    divergences.push({
                      type: 'bearish',
                      startIndex: bearishPreviousZone.index,
                      endIndex: highestNearPoint.index,
                      startTime: bearishPreviousZone.time,
                      endTime: highestNearPoint.time,
                      priceStart: prevHigh,
                      priceEnd: currHigh,
                      rsiStart: bearishPreviousZone.rsi,
                      rsiEnd: highestNearPoint.rsi,
                    });

                    bearishActive = true;
                    bearishDivPoint = highestNearPoint;

                    // Reset
                    bearishPreviousZone = null;
                    bearishPreviousTrendType = null;
                    bearishWaitingForNearZone = false;
                  } else {
                    console.log(`   → Price not diverging (${currHigh.toFixed(2)} <= ${prevHigh.toFixed(2)}) → Keep Zone 1, wait for next Zone 2`);
                  }
                }
              }

              bearishNearZone = [];
            }

            // Reset ถ้า RSI ลงต่ำกว่า 50 (ออกจากช่วง overbought โดยสิ้นเชิง)
            if (bearishWaitingForNearZone && rsi < 50) {
              console.log(`⚠️ RSI dropped below 50 → Reset Bearish Divergence tracking`);
              bearishPreviousZone = null;
              bearishPreviousTrendType = null;
              bearishNearZone = [];
              bearishWaitingForNearZone = false;
            }
          }

          // ถ้า Strong_Sell Active อยู่
          if (bearishActive) {
            state.strong_sell = 'Active';

            // ✅ เงื่อนไขการยืนยันการกลับตัว (Reversal Confirmation)
            // 1. ต้องเข้า Orange Zone (downtrend confirmed)
            // 2. RSI ต้องกลับมาต่ำกว่า 60 (แรงขายกลับมา)
            if (zone.zone === 'orange' && rsi < 60) {
              state.special_signal = 'SELL';
              state.strong_sell = 'none-Active';
              bearishActive = false;
              bearishPreviousZone = null;
              console.log(`🔔 ✅ SELL SIGNAL CONFIRMED at index ${i}`);
              console.log(`   RSI: ${rsi.toFixed(2)} (below 60 ✓)`);
              console.log(`   Zone: Orange (downtrend ✓)`);
            }
            // ถ้ายังไม่เข้าเงื่อนไข ให้รอต่อ แต่ถ้า RSI ขึ้นเหนือ 70 อีกครั้ง → ยกเลิกสัญญาณ
            else if (rsi > 70) {
              console.log(`⚠️ RSI rose above 70 again → Cancel SELL signal (failed reversal)`);
              bearishActive = false;
              bearishPreviousZone = null;
            }
          }

          candleStates.push(state);
        }

        console.log(`✅ Divergence detection complete: ${divergences.length} divergences found`);
        return { divergences, candleStates };
      }

      // Draw divergence lines on RSI chart
      function drawDivergenceLines(divergences) {
        if (!tvChart || !rsiSeries) {
          console.warn("⚠️ Cannot draw divergence lines: chart or RSI series not ready");
          return;
        }

        // Clear existing lines
        divergenceLines.forEach(lineSeries => {
          tvChart.removeSeries(lineSeries);
        });
        divergenceLines = [];

        // Draw new lines and markers on RSI panel
        const rsiMarkers = [];

        divergences.forEach(div => {
          const lineColor = div.type === 'bullish' ? '#22c55e' : '#ef4444';
          const lineSeries = tvChart.addLineSeries({
            color: lineColor,
            lineWidth: 2,
            lineStyle: 0, // Solid line
            priceScaleId: 'rsi',
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });

          // Draw line from start to end
          const lineData = [
            { time: div.startTime, value: div.rsiStart },
            { time: div.endTime, value: div.rsiEnd },
          ];

          lineSeries.setData(lineData);
          divergenceLines.push(lineSeries);

          // Add markers to make divergence endpoints obvious
          rsiMarkers.push({
            time: div.startTime,
            position: 'aboveBar',
            color: lineColor,
            shape: div.type === 'bullish' ? 'arrowUp' : 'arrowDown',
            text: div.type === 'bullish' ? 'Bull Div' : 'Bear Div',
          });
          rsiMarkers.push({
            time: div.endTime,
            position: 'belowBar',
            color: lineColor,
            shape: div.type === 'bullish' ? 'arrowUp' : 'arrowDown',
            text: div.type === 'bullish' ? 'Bull Div' : 'Bear Div',
          });
        });

        // Attach markers to RSI series (clears old ones automatically)
        rsiSeries.setMarkers(rsiMarkers);

        console.log(`📈 Drew ${divergences.length} divergence lines (markers: ${rsiMarkers.length})`);
      }

      function initChart() {
        if (tvChart) return;

        if (typeof LightweightCharts === 'undefined') {
          console.error("❌ LightweightCharts library not loaded!");
          alert("ไม่สามารถโหลดไลบรารี่กราฟได้ กรุณาตรวจสอบการเชื่อมต่ออินเทอร์เน็ต");
          return;
        }

        console.log("📊 Initializing charts...");

        // ========================================
        // Main chart with price and RSI
        // ========================================
        const chart = LightweightCharts.createChart(chartContainer, {
          width: chartContainer.clientWidth,
          height: 640,
          layout: {
            background: { color: "#ffffff" },
            textColor: "#0f172a",
          },
          grid: {
            vertLines: { color: "#e5e7eb" },
            horzLines: { color: "#e5e7eb" },
          },
          rightPriceScale: {
            borderColor: "#cbd5e1",
            scaleMargins: {
              top: 0.05,
              bottom: 0.30, // Reserve 30% at bottom for RSI
            },
          },
          leftPriceScale: {
            visible: false, // Hide default left scale
            borderColor: "#cbd5e1",
          },
          timeScale: {
            borderColor: "#cbd5e1",
            timeVisible: true,
            secondsVisible: false,
          },
        });

        // EMA Slow (26) - Orange line
        emaSlowSeries = chart.addLineSeries({
          color: '#f97316',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: 'EMA 26',
          priceScaleId: 'right',
        });

        // EMA Fast (12) - Blue line
        emaFastSeries = chart.addLineSeries({
          color: '#3b82f6',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: 'EMA 12',
          priceScaleId: 'right',
        });

        // Main candlestick series
        candleSeries = chart.addCandlestickSeries({
          upColor: "#10b981",
          downColor: "#ef4444",
          wickUpColor: "#10b981",
          wickDownColor: "#ef4444",
          borderVisible: false,
          priceScaleId: 'right',
        });

        // ========================================
        // RSI Series (bottom section: 70%-95% from top)
        // ========================================

        // RSI Line with dedicated scale
        rsiSeries = chart.addLineSeries({
          color: '#8b5cf6', // Purple color for RSI
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          title: 'RSI(14)',
          priceScaleId: 'rsi',
          priceFormat: {
            type: 'price',
            precision: 2,
            minMove: 0.01,
          },
        });

        // Configure RSI scale (fixed 0-100 range)
        chart.priceScale('rsi').applyOptions({
          scaleMargins: {
            top: 0.70, // Start at 70% from top
            bottom: 0.05, // End at 95% from top (30% height for RSI)
          },
          borderColor: '#cbd5e1',
          visible: true,
          autoScale: true,
          mode: 0, // Normal mode
          invertScale: false,
        });

        // RSI Overbought line (70)
        rsiOverboughtSeries = chart.addLineSeries({
          color: '#ef4444', // Red
          lineWidth: 1,
          lineStyle: 2, // Dashed
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: 'rsi',
        });

        // RSI Oversold line (30)
        rsiOversoldSeries = chart.addLineSeries({
          color: '#22c55e', // Green
          lineWidth: 1,
          lineStyle: 2, // Dashed
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: 'rsi',
        });

        // Hidden series to force RSI scale to 0-100 range
        rsiMinMaxSeries = chart.addLineSeries({
          color: 'transparent',
          lineWidth: 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
          priceScaleId: 'rsi',
          visible: false,
        });

        tvChart = chart;

        // Setup crosshair tooltip
        chart.subscribeCrosshairMove((param) => {
          if (!param.time || !param.point) {
            tooltipEl.style.display = 'none';
            return;
          }

          const timestamp = typeof param.time === 'number' ? param.time * 1000 : param.time;
          const candle = candleData.find(c => c.open_time === timestamp);
          const marker = markerDataMap.get(timestamp);

          if (!candle && !marker) {
            tooltipEl.style.display = 'none';
            return;
          }

          let html = '';

          // Show marker info if exists
          if (marker) {
            // Determine signal color based on fake signal status and type
            let signalColor = marker.type === 'BUY' ? '#22c55e' : '#ef4444';
            if (marker.isFakeSignal) {
              signalColor = '#f59e0b'; // Amber for fake signals
            }

            // Signal type badge
            const isHistorical = marker.isHistorical === true;
            const signalBadgeColor = isHistorical ? '#6b7280' : '#FFD700'; // Gray for historical, Gold for validated
            const signalBadgeBg = isHistorical ? '#f3f4f6' : '#fffbeb';
            const signalBadgeText = isHistorical ? '📜 Historical Reference' : '⭐ Validated Current Signal';

            html += `<div style="font-weight: 600; color: ${signalColor}; margin-bottom: 4px;">`;
            html += `${marker.type === 'BUY' ? '🔼' : '🔽'} ${marker.type} Signal`;

            // Show signal type badge
            html += ` <span style="background: ${signalBadgeBg}; color: ${signalBadgeColor}; padding: 2px 6px; border-radius: 3px; font-size: 10px; font-weight: 600;">${signalBadgeText}</span>`;

            // Show fake signal warning
            if (marker.isFakeSignal) {
              html += ` <span style="color: #f59e0b;">⚠ สัญญาณหลอก</span>`;
            }
            html += `</div>`;

            // Show signal details based on type
            if (marker.type === 'BUY') {
              if (marker.buyPrice) html += `<div>Entry: <b>${marker.buyPrice.toFixed(2)}</b></div>`;
              if (marker.targetPrice) html += `<div>Target (ref): <b>${marker.targetPrice.toFixed(2)}</b> (+${marker.targetPercent.toFixed(1)}%)</div>`;
              if (marker.cutlossPrice) html += `<div>Cutloss: <b>${marker.cutlossPrice.toFixed(2)}</b> (${marker.cutlossPercent.toFixed(1)}%)</div>`;
              if (marker.risk_reward) html += `<div>R:R = <b>1:${marker.risk_reward.toFixed(2)}</b></div>`;

              // Exit strategy note
              html += `<div style="margin-top: 6px; padding: 6px; background: #fff7ed; border-left: 3px solid #f59e0b; font-size: 11px;">`;
              html += `💡 <b>Exit Strategy:</b> ออกตาม SELL signal หรือ ถูก Cutloss`;
              html += `</div>`;

              // Validation status - different for historical vs current
              if (isHistorical) {
                // Historical: Show only 1D checks
                html += `<div style="margin-top: 8px; padding: 6px; background: #f9fafb; border-left: 3px solid #6b7280; font-size: 11px;">`;
                html += `<div style="font-weight: 600; margin-bottom: 4px;">✓ 1D Pattern Check</div>`;
                html += `<div>Bull 1D: <span style="color: ${marker.validation_1d_bull ? '#22c55e' : '#ef4444'};">${marker.validation_1d_bull ? '✓ pass' : '✗ fail'}</span></div>`;
                html += `<div>Signal 1D: <span style="color: #22c55e;">✓ pass</span> (blue→green)</div>`;
                html += `<div style="color: #9ca3af; margin-top: 4px; font-style: italic;">เป็นสัญญาณอดีต ใช้เฉพาะ 1D pattern</div>`;
                html += `</div>`;
              } else {
                // Current: Show full Auto 3-TF validation
                html += `<div style="margin-top: 8px; padding: 6px; background: #fffbeb; border-left: 3px solid #FFD700; font-size: 11px;">`;
                html += `<div style="font-weight: 600; margin-bottom: 4px;">⭐ Auto 3-TF Validation</div>`;
                html += `<div>Bull 1W: <span style="color: #22c55e;">✓ pass</span></div>`;
                html += `<div>Bull 1D: <span style="color: ${marker.validation_1d_bull ? '#22c55e' : '#ef4444'};">${marker.validation_1d_bull ? '✓ pass' : '✗ fail'}</span></div>`;
                html += `<div>Signal 1D: <span style="color: #22c55e;">✓ pass</span> (blue→green)</div>`;
                html += `<div>Signal 1H: <span style="color: #22c55e;">✓ pass</span> (entry found)</div>`;
                html += `<div style="color: #92400e; margin-top: 4px; font-weight: 600;">🎯 ผ่านการตรวจสอบครบทุก TF - แนะนำสูง!</div>`;
                html += `</div>`;
              }
            } else if (marker.type === 'SELL') {
              // SELL = EXIT signal (Long Only strategy) - Multi-type support
              const exitLabels = {
                'TRAILING_STOP': { icon: '📈', label: 'Trailing Stop Exit', color: '#10b981', bg: '#f0fdf4' },
                'DIVERGENCE': { icon: '⚠️', label: 'Divergence Exit', color: '#f59e0b', bg: '#fffbeb' },
                'EMA_CROSS': { icon: '🔴', label: 'EMA Cross Exit', color: '#ef4444', bg: '#fef2f2' },
                'STOP_LOSS': { icon: '🛑', label: 'Stop Loss', color: '#dc2626', bg: '#fef2f2' },
              };

              const exitInfo = marker.exit_reason && exitLabels[marker.exit_reason]
                ? exitLabels[marker.exit_reason]
                : exitLabels['EMA_CROSS'];

              if (marker.sellPrice) html += `<div>Exit Price: <b>${marker.sellPrice.toFixed(2)}</b></div>`;
              html += `<div style="margin-top: 6px; padding: 6px; background: ${exitInfo.bg}; border-left: 3px solid ${exitInfo.color}; font-size: 11px;">`;
              html += `${exitInfo.icon} <b>${exitInfo.label}</b> - ขายออกจากการถือ Long`;
              html += `</div>`;

              // Validation status - different for historical vs current
              if (isHistorical) {
                // Historical: Show only 1D checks
                html += `<div style="margin-top: 8px; padding: 6px; background: #f9fafb; border-left: 3px solid #6b7280; font-size: 11px;">`;
                html += `<div style="font-weight: 600; margin-bottom: 4px;">✓ 1D Pattern Check</div>`;
                html += `<div>Signal 1D: <span style="color: #22c55e;">✓ pass</span> (orange→red)</div>`;
                html += `<div style="color: #9ca3af; margin-top: 4px; font-style: italic;">เป็นสัญญาณอดีต ใช้เฉพาะ 1D pattern</div>`;
                html += `</div>`;
              } else {
                // Current: Show full validation with 1H exit
                html += `<div style="margin-top: 8px; padding: 6px; background: #fffbeb; border-left: 3px solid #FFD700; font-size: 11px;">`;
                html += `<div style="font-weight: 600; margin-bottom: 4px;">⭐ Auto 3-TF Validation</div>`;
                html += `<div>Signal 1D: <span style="color: #22c55e;">✓ pass</span> (orange→red)</div>`;
                html += `<div>Signal 1H: <span style="color: #22c55e;">✓ pass</span> (exit found)</div>`;
                html += `<div style="color: #92400e; margin-top: 4px; font-weight: 600;">🎯 ผ่านการตรวจสอบครบ - แนะนำสูง!</div>`;
                html += `</div>`;
              }
            }

            // Show note (for 1D signals)
            if (marker.note) {
              html += `<div style="margin-top: 6px; padding: 6px; background: #fef3c7; border-left: 3px solid #f59e0b; font-size: 11px;">💡 ${marker.note}</div>`;
            }

            // Show HTF validation reason if fake signal
            if (marker.isFakeSignal && marker.htfReason) {
              html += `<div style="font-size: 11px; color: #9ca3af; margin-top: 4px;">${marker.htfReason === '1w_not_bull' ? '1W ไม่ Bull' : 'LTF เข้า แต่ HTF ไม่เข้า'}</div>`;
            }

            html += '<hr style="margin: 6px 0; border: none; border-top: 1px solid #e5e7eb;" />';
          }

          // Show candle info
          if (candle) {
            const isBull = candle.ema_fast > candle.ema_slow;
            const trendColor = isBull ? '#22c55e' : '#ef4444';
            const trendLabel = isBull ? 'Bull' : 'Bear';

            html += `<div style="margin-bottom: 4px;"><b>Candle Data</b></div>`;
            html += `<div>O: ${candle.open.toFixed(2)} | H: ${candle.high.toFixed(2)}</div>`;
            html += `<div>L: ${candle.low.toFixed(2)} | C: ${candle.close.toFixed(2)}</div>`;
            html += `<div style="color: ${trendColor};">Trend: <b>${trendLabel}</b></div>`;
            html += `<div>EMA Fast: ${candle.ema_fast.toFixed(2)}</div>`;
            html += `<div>EMA Slow: ${candle.ema_slow.toFixed(2)}</div>`;
            html += `<div>Zone: <b>${candle.action_zone}</b></div>`;

            // Find RSI value for this timestamp
            const rsiValue = rsiData.find(r => r.time === timestamp / 1000);
            if (rsiValue) {
              const rsiColor = rsiValue.value > 70 ? '#ef4444' : rsiValue.value < 30 ? '#22c55e' : '#8b5cf6';
              html += `<div style="color: ${rsiColor};">RSI(14): <b>${rsiValue.value.toFixed(2)}</b></div>`;
            }

            // Find candle state (Strong_Buy/Strong_Sell status)
            const state = candleStates.find(s => s && s.time === timestamp / 1000);

            // Debug log (แสดงครั้งแรกที่เจอ state)
            if (state && (state.strong_buy === 'Active' || state.strong_sell === 'Active' || state.special_signal)) {
              console.log(`🎯 Found state at timestamp ${timestamp}:`, state);
            }

            // Show Strong_Buy/Strong_Sell Status
            if (state) {
              if (state.strong_buy === 'Active') {
                html += `<div style="margin-top: 6px; padding: 6px; background: #f0fdf4; border-left: 3px solid #22c55e; font-size: 11px;">`;
                html += `<div style="color: #22c55e; font-weight: 600;">🟢 Strong_Buy: Active</div>`;
                html += `<div style="font-size: 10px; color: #64748b; margin-top: 2px;">รอสัญญาณซื้อที่แท่งสีน้ำเงิน</div>`;
                html += `</div>`;
              }

              if (state.strong_sell === 'Active') {
                html += `<div style="margin-top: 6px; padding: 6px; background: #fef2f2; border-left: 3px solid #ef4444; font-size: 11px;">`;
                html += `<div style="color: #ef4444; font-weight: 600;">🔴 Strong_Sell: Active</div>`;
                html += `<div style="font-size: 10px; color: #64748b; margin-top: 2px;">รอสัญญาณขายที่แท่งสีส้ม</div>`;
                html += `</div>`;
              }

              // Show Special Buy/Sell Signals
              if (state.special_signal === 'BUY') {
                html += `<div style="margin-top: 8px; padding: 8px; background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%); border: 2px solid #22c55e; border-radius: 6px; font-size: 12px;">`;
                html += `<div style="color: #16a34a; font-weight: 700; font-size: 14px;">🚀 สัญญาณซื้อพิเศษ (Special BUY)</div>`;
                if (state.cutloss) {
                  html += `<div style="margin-top: 4px; color: #dc2626; font-weight: 600;">⚠️ Cutloss: ${state.cutloss.toFixed(2)}</div>`;
                }
                html += `<div style="font-size: 10px; color: #64748b; margin-top: 4px;">Bullish Divergence + Blue Zone</div>`;
                html += `</div>`;
              }

              if (state.special_signal === 'SELL') {
                html += `<div style="margin-top: 8px; padding: 8px; background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%); border: 2px solid #ef4444; border-radius: 6px; font-size: 12px;">`;
                html += `<div style="color: #dc2626; font-weight: 700; font-size: 14px;">⚠️ สัญญาณขายพิเศษ (Special SELL)</div>`;
                html += `<div style="font-size: 10px; color: #64748b; margin-top: 4px;">Bearish Divergence + Orange Zone</div>`;
                html += `</div>`;
              }
            }

            // Check for divergence confirmation at this candle
            const divergenceHere = detectedDivergences.find(d => d.endTime === timestamp / 1000);
            if (divergenceHere) {
              const divColor = divergenceHere.type === 'bullish' ? '#22c55e' : '#ef4444';
              const divIcon = divergenceHere.type === 'bullish' ? '📈' : '📉';
              const divLabel = divergenceHere.type === 'bullish' ? 'Bullish Divergence' : 'Bearish Divergence';
              html += `<div style="margin-top: 6px; padding: 6px; background: ${divergenceHere.type === 'bullish' ? '#f0fdf4' : '#fef2f2'}; border-left: 3px solid ${divColor}; font-size: 11px;">`;
              html += `<div style="color: ${divColor}; font-weight: 600;">${divIcon} ${divLabel} Detected</div>`;
              html += `<div style="font-size: 10px; color: #64748b; margin-top: 2px;">RSI: ${divergenceHere.rsiStart.toFixed(2)} → ${divergenceHere.rsiEnd.toFixed(2)}</div>`;
              html += `</div>`;
            }

            if (candle.pattern && candle.pattern !== 'NONE') {
              html += `<div>Pattern: <b>${candle.pattern}</b></div>`;
            }

            // Show Trailing Stop info if available
            const tsInfo = trailingStopDataMap.get(timestamp);
            if (tsInfo) {
              const riskDistance = ((candle.close - tsInfo.slPrice) / candle.close * 100).toFixed(2);
              const slColor = tsInfo.isActivated ? '#ef4444' : '#fb923c';
              const slStatus = tsInfo.isActivated ? 'Active' : 'Calculating';
              const slIcon = tsInfo.isActivated ? '🔴' : '🟠';
              const slBg = tsInfo.isActivated ? '#fef2f2' : '#fff7ed';

              html += `<div style="margin-top: 6px; padding: 6px; background: ${slBg}; border-left: 3px solid ${slColor}; font-size: 11px;">`;
              html += `<div style="color: ${slColor}; font-weight: 600;">${slIcon} Trailing Stop (${slStatus})</div>`;
              html += `<div>SL Price: <b>${tsInfo.slPrice.toFixed(2)}</b></div>`;
              html += `<div>Risk Distance: <b>${riskDistance}%</b> from close</div>`;

              if (tsInfo.unchanged) {
                html += `<div style="color: #64748b; font-size: 10px; margin-top: 2px;">📌 Using SL from previous candle</div>`;
              } else {
                html += `<div style="color: #16a34a; font-size: 10px; margin-top: 2px;">📈 SL moved up this candle</div>`;
              }

              if (!tsInfo.isActivated) {
                html += `<div style="color: #9ca3af; font-size: 10px; margin-top: 2px;">⏳ Waiting for activation threshold</div>`;
              }

              html += `</div>`;
            }

            // Add validation checks - Check at 1D level (where patterns are detected)
            if (signalModeSelect.value === 'simple' && data1d && data1d.candles && data1d.candles.length >= 3) {
              // Find the corresponding 1D candle
              const idx1d = data1d.candles.findIndex(c => c.open_time <= candle.open_time && c.open_time + 86400000 > candle.open_time);

              if (idx1d >= 2) {
                const c1d = data1d.candles[idx1d];
                const zone_i2 = data1d.candles[idx1d - 2].action_zone;
                const zone_i1 = data1d.candles[idx1d - 1].action_zone;
                const isBull1d = c1d.ema_fast > c1d.ema_slow;
                const isVShape1d = c1d.is_v_shape === true;

                html += `<hr style="margin: 6px 0; border: none; border-top: 1px solid #e5e7eb;" />`;
                html += `<div style="margin-bottom: 4px;"><b>Signal Validation (Auto 3-TF)</b></div>`;

                // Check BUY signal conditions
                const hasBuyPattern = (zone_i2 === 'blue' && zone_i1 === 'green');
                html += `<div><b>BUY Signal Check:</b></div>`;
                html += `<div>1D Pattern (blue→green): ${hasBuyPattern ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #9ca3af;">✗</span>'}</div>`;

                if (hasBuyPattern) {
                  html += `<div>1D Bull Trend: ${isBull1d ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #ef4444;">✗</span>'}</div>`;
                  html += `<div>1D Not V-shape: ${!isVShape1d ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #ef4444;">✗</span>'}</div>`;

                  if (isBull1d && !isVShape1d) {
                    // Actually check 1W and 1H
                    const v1w = validate1W_Bull(c1d.open_time, data1w.candles);
                    html += `<div>1W Bull: ${v1w.valid ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #ef4444;">✗</span>'}</div>`;

                    if (v1w.valid) {
                      const entry1h = find1H_BuyEntry(c1d.open_time, data1h.candles);
                      html += `<div>1H Entry Found: ${entry1h.found ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #ef4444;">✗</span>'}</div>`;

                      if (entry1h.found) {
                        html += `<div style="color: #22c55e; margin-top: 4px;"><b>✅ สัญญาณ BUY ครบทุกเงื่อนไข!</b></div>`;
                      } else {
                        html += `<div style="color: #ef4444; margin-top: 4px;">❌ ไม่มี 1H entry point</div>`;
                      }
                    } else {
                      html += `<div style="color: #ef4444; margin-top: 4px;">❌ 1W ไม่ Bull (ไม่แสดงสัญญาณ)</div>`;
                    }
                  }
                }

                // Check SELL signal conditions
                const hasSellPattern = (zone_i2 === 'orange' && zone_i1 === 'red');
                html += `<div style="margin-top: 6px;"><b>SELL Signal Check:</b></div>`;
                html += `<div>1D Pattern (orange→red): ${hasSellPattern ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #9ca3af;">✗</span>'}</div>`;

                if (hasSellPattern) {
                  const exit1h = find1H_SellExit(c1d.open_time, data1h.candles);
                  html += `<div>1H Exit Found: ${exit1h.found ? '<span style="color: #22c55e;">✓</span>' : '<span style="color: #ef4444;">✗</span>'}</div>`;

                  if (exit1h.found) {
                    html += `<div style="color: #22c55e; margin-top: 4px;"><b>✅ สัญญาณ SELL ครบทุกเงื่อนไข!</b></div>`;
                  } else {
                    html += `<div style="color: #ef4444; margin-top: 4px;">❌ ไม่มี 1H exit point</div>`;
                  }
                }

                if (!hasBuyPattern && !hasSellPattern) {
                  html += `<div style="color: #9ca3af; margin-top: 4px;">ไม่มี Pattern ที่จุดนี้</div>`;
                }
              }
            }
          }

          tooltipEl.innerHTML = html;
          tooltipEl.style.display = 'block';

          // Position tooltip
          const x = param.point.x;
          const y = param.point.y;
          const tooltipWidth = 250;
          const tooltipHeight = tooltipEl.offsetHeight;

          let left = x + 15;
          let top = y - tooltipHeight / 2;

          // Keep tooltip within chart bounds
          if (left + tooltipWidth > chartContainer.clientWidth) {
            left = x - tooltipWidth - 15;
          }
          if (top < 0) top = 10;
          if (top + tooltipHeight > chartContainer.clientHeight) {
            top = chartContainer.clientHeight - tooltipHeight - 10;
          }

          tooltipEl.style.left = left + 'px';
          tooltipEl.style.top = top + 'px';
        });

        console.log("✅ Chart initialized successfully");

        window.addEventListener("resize", () => {
          tvChart.applyOptions({ width: chartContainer.clientWidth });
        });
      }

      function clearZoneSeries() {
        zoneSeries.forEach(series => tvChart.removeSeries(series));
        zoneSeries = [];
      }

      // ==========================================
      // Fibonacci Retracement/Extension Functions
      // ==========================================

      let fibonacciSeries = []; // Store Fibonacci level series for cleanup
      let waveObjects = []; // Store wave triangle/rectangle objects
      let activeWaveId = null; // Currently selected wave

      function clearFibonacciSeries() {
        fibonacciSeries.forEach(series => tvChart.removeSeries(series));
        fibonacciSeries = [];
      }

      async function drawFibonacciLevels(pair, timeframe) {
        try {
          // Clear previous Fibonacci lines and wave objects
          clearFibonacciSeries();
          clearWaveObjects();

          // Fetch Wave patterns from API
          const fibUrl = `/fibonacci?pair=${encodeURIComponent(pair)}&timeframe=${timeframe}&limit=1000`;
          console.log('🌊 Fetching Wave patterns from:', fibUrl);

          const response = await fetch(fibUrl);
          if (!response.ok) {
            console.warn('⚠️ Failed to fetch Wave data:', response.statusText);
            return;
          }

          const fibData = await response.json();
          console.log('🌊 Wave data:', fibData);

          if (!fibData.has_waves || !fibData.waves || fibData.waves.length === 0) {
            console.log('ℹ️ No wave patterns detected');
            return;
          }

          console.log(`🌊 Found ${fibData.wave_count} wave patterns`);

          // Draw Elliott Wave 1-2 patterns
          // Blue = Wave 1 Low, Red = Wave 1 High, Green = Wave 2 Low
          console.log(`📊 Total waves from API: ${fibData.waves.length}`);
          fibData.waves.forEach((wave, idx) => {
            console.log(`🔍 Processing wave ${wave.wave_id}:`, {
              has_low1: !!wave.swing_low_1,
              has_high: !!wave.swing_high,
              has_low2: !!wave.swing_low_2,
              fib_levels: wave.fib_levels?.length || 0
            });

            if (!wave.swing_low_1 || !wave.swing_high || !wave.swing_low_2) {
              console.warn(`⚠️ Incomplete wave pattern ${wave.wave_id}`);
              return;
            }

            // Wave 1 Low (blue)
            const t1 = wave.swing_low_1.open_time ? Math.floor(wave.swing_low_1.open_time / 1000) : null;
            const p1 = wave.swing_low_1.price;

            // Wave 1 High (red)
            const t2 = wave.swing_high.open_time ? Math.floor(wave.swing_high.open_time / 1000) : null;
            const p2 = wave.swing_high.price;

            // Wave 2 Low (green)
            const t3 = wave.swing_low_2.open_time ? Math.floor(wave.swing_low_2.open_time / 1000) : null;
            const p3 = wave.swing_low_2.price;

            // Skip if any timestamp is invalid
            if (!t1 || !t2 || !t3) {
              console.warn(`⚠️ Invalid timestamps for wave ${wave.wave_id}:`, { t1, t2, t3 });
              return;
            }

            console.log(`🌊 Wave ${wave.wave_id}:`, {
              wave1_low: { index: wave.swing_low_1.index, price: p1 },
              wave1_high: { index: wave.swing_high.index, price: p2 },
              wave2_low: { index: wave.swing_low_2.index, price: p3 },
            });

            // Determine if this is a bear wave (Projection) or bull wave (Retracement)
            const isBearWave = wave.wave_id.startsWith('bear');

            // NOTE: No longer drawing dots here - we draw ALL dots from valid_bear_lows, invalid_bear_lows, and all_bull_highs
            // This prevents duplicate dots and ensures every zone has exactly one dot

            // Store wave object for click handling
            // Bear wave: clickable at swing_low_1 (t1, p1) - blue dot (points to future)
            //            AND at swing_low_2 (t3, p3) - green dot (entry point)
            // Bull wave: clickable at swing_high (t2, p2) - red dot
            waveObjects.push({
              waveId: wave.wave_id,
              isBearWave: isBearWave,
              fibLevels: wave.fib_levels || [],
              trailingStop: wave.trailing_stop || null,  // Trailing Stop data from backend
              showingProjection: false,
              showingRetracement: false,
              showingTrailingStop: false,  // New state for Trailing Stop visibility
              showingWaveStructure: false,  // New state for showing Wave reference structure
              points: { t1, p1, t2, p2, t3, p3 },
              swing_low_1: wave.swing_low_1,  // Store full swing point data
              swing_high: wave.swing_high,
              swing_low_2: wave.swing_low_2,
              clickableTime: isBearWave ? t1 : t2,  // Blue dot at t1 for bear, red dot at t2 for bull
              clickablePrice: isBearWave ? p1 : p2,
              entryTime: t3,  // Green dot (entry point) for bear waves
              entryPrice: p3,
            });

            console.log(`✅ Drew Elliott Wave ${wave.wave_id}`);
          });

          const bearCount = waveObjects.filter(w => w.isBearWave).length;
          const bullCount = waveObjects.filter(w => !w.isBearWave).length;
          console.log(`✅ Drew ${waveObjects.length} Elliott Wave patterns: ${bearCount} bear (Projection), ${bullCount} bull (Retracement)`);

          // Draw invalid bear lows (green dots, non-clickable)
          if (fibData.invalid_bear_lows && fibData.invalid_bear_lows.length > 0) {
            console.log(`🟢 Found ${fibData.invalid_bear_lows.length} invalid bear lows (green dots)`);

            fibData.invalid_bear_lows.forEach((invalidLow, idx) => {
              const timestamp = invalidLow.open_time ? Math.floor(invalidLow.open_time / 1000) : null;
              const price = invalidLow.price;

              if (!timestamp || !price) {
                console.warn(`⚠️ Invalid timestamp or price for invalid bear low at index ${invalidLow.index}`);
                return;
              }

              console.log(`🟢 Invalid bear low ${idx + 1}: Index ${invalidLow.index}, Price ${price}`);

              // Create green dot (non-clickable, slightly transparent)
              const invalidLowDot = tvChart.addLineSeries({
                color: '#10b981',  // Green (same as Wave 2 Low)
                lineWidth: 0,
                pointMarkersVisible: true,
                pointMarkersRadius: 4,
                title: '',
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
              });
              invalidLowDot.setData([{ time: timestamp, value: price }]);
              fibonacciSeries.push(invalidLowDot);
            });

            console.log(`✅ Drew ${fibData.invalid_bear_lows.length} invalid bear low markers (green, non-clickable)`);
          }

          // Draw ALL bull highs (red dots, always displayed)
          if (fibData.all_bull_highs && fibData.all_bull_highs.length > 0) {
            console.log(`🔴 Found ${fibData.all_bull_highs.length} bull highs (red dots)`);

            fibData.all_bull_highs.forEach((bullHigh, idx) => {
              const timestamp = bullHigh.open_time ? Math.floor(bullHigh.open_time / 1000) : null;
              const price = bullHigh.price;

              if (!timestamp || !price) {
                console.warn(`⚠️ Invalid timestamp or price for bull high at index ${bullHigh.index}`);
                return;
              }

              console.log(`🔴 Bull high ${idx + 1}: Index ${bullHigh.index}, Price ${price}`);

              // Create red dot (clickable for Retracement)
              const bullHighDot = tvChart.addLineSeries({
                color: '#ef4444',  // Red
                lineWidth: 0,
                pointMarkersVisible: true,
                pointMarkersRadius: 4,
                title: '',
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
              });
              bullHighDot.setData([{ time: timestamp, value: price }]);
              fibonacciSeries.push(bullHighDot);
            });

            console.log(`✅ Drew ${fibData.all_bull_highs.length} bull high markers (red)`);
          }

          // Draw valid bear lows (blue dots, clickable for Projection)
          if (fibData.valid_bear_lows && fibData.valid_bear_lows.length > 0) {
            console.log(`🔵 Found ${fibData.valid_bear_lows.length} valid bear lows (blue dots)`);

            fibData.valid_bear_lows.forEach((validLow, idx) => {
              const timestamp = validLow.open_time ? Math.floor(validLow.open_time / 1000) : null;
              const price = validLow.price;

              if (!timestamp || !price) {
                console.warn(`⚠️ Invalid timestamp or price for valid bear low at index ${validLow.index}`);
                return;
              }

              console.log(`🔵 Valid bear low ${idx + 1}: Index ${validLow.index}, Price ${price}`);

              // Create blue dot (clickable for Projection)
              const validLowDot = tvChart.addLineSeries({
                color: '#2563eb',  // Blue
                lineWidth: 0,
                pointMarkersVisible: true,
                pointMarkersRadius: 4,
                title: '',
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
              });
              validLowDot.setData([{ time: timestamp, value: price }]);
              fibonacciSeries.push(validLowDot);
            });

            console.log(`✅ Drew ${fibData.valid_bear_lows.length} valid bear low markers (blue)`);
          }

          // No wave markers for now (using LineSeries instead)
          window.waveMarkers = [];

          // Add click handler for wave objects
          if (waveObjects.length > 0) {
            chartContainer.addEventListener('click', handleWaveClick);
            console.log('✅ Added click handler for wave objects');
          }

        } catch (error) {
          console.error('❌ Error drawing Wave patterns:', error);
        }
      }

      function clearWaveObjects() {
        waveObjects.forEach(obj => {
          if (obj.fibSeries) {
            obj.fibSeries.forEach(series => tvChart.removeSeries(series));
          }
        });
        waveObjects = [];
        activeWaveId = null;
        window.waveMarkers = [];
        chartContainer.removeEventListener('click', handleWaveClick);
      }

      function handleWaveClick(event) {
        // Click handler:
        // - Click on Wave 1 Low (blue dot) → Toggle Fibonacci Projection
        // - Click on Wave 1 High (red dot) → Toggle Fibonacci Retracement
        // - Click on BUY arrow (Strong Buy signal) → Toggle Trailing Stop
        const rect = chartContainer.getBoundingClientRect();
        const x = event.clientX - rect.left;

        console.log('Click detected at pixel x:', x);

        const CLICK_THRESHOLD = 40; // pixels
        const timeScale = tvChart.timeScale();

        // Check wave points and BUY arrows
        let closestMatch = null;
        let minDistance = Infinity;

        // 1. Check wave swing points (Blue/Red dots only - Green dots not clickable)
        waveObjects.forEach((wave, idx) => {
          // Check blue/red clickable point (swing_low_1 for bear, swing_high for bull)
          const clickCoord = timeScale.timeToCoordinate(wave.clickableTime);
          if (clickCoord !== null) {
            const dx = Math.abs(x - clickCoord);
            if (dx < minDistance && dx < CLICK_THRESHOLD) {
              minDistance = dx;
              closestMatch = { waveIndex: idx, pointType: wave.isBearWave ? 'low' : 'high' };
            }
          }

          // Green dots (entry point at swing_low_2) are NOT clickable
          // Only BUY arrows should trigger wave structure display
        });

        // 2. Check BUY arrow markers (Strong Buy signals)
        buyArrowMarkers.forEach((arrow, arrowIdx) => {
          const arrowCoord = timeScale.timeToCoordinate(arrow.time);
          if (arrowCoord !== null) {
            const dx = Math.abs(x - arrowCoord);
            if (dx < minDistance && dx < CLICK_THRESHOLD) {
              minDistance = dx;
              closestMatch = { arrowIndex: arrowIdx, pointType: 'buy_arrow' };
            }
          }
        });

        if (closestMatch) {
          if (closestMatch.pointType === 'buy_arrow') {
            // Clicked on BUY arrow → Trace Wave Structure backwards and show it
            const arrow = buyArrowMarkers[closestMatch.arrowIndex];
            console.log(`✅ Clicked on BUY arrow at time ${arrow.time}, distance: ${minDistance.toFixed(2)}px`);
            console.log(`   Arrow data:`, arrow);

            // Check if clicking the same arrow again (toggle off)
            if (window.activeTracedArrowTime === arrow.time) {
              console.log(`ℹ️ Clicking same arrow again - hiding traced wave`);

              // Hide traced wave
              if (window.tracedWaveSeries) {
                window.tracedWaveSeries.forEach(series => tvChart.removeSeries(series));
                window.tracedWaveSeries = [];
              }
              window.activeTracedArrowTime = null;
              return;
            }

            // Trace Wave structure from BUY arrow
            const waveStructure = traceWaveStructureFromBuyArrow(arrow);

            if (waveStructure) {
              // Successfully traced Wave structure
              console.log(`✅ Traced Wave structure:`, waveStructure);

              // Hide all existing visualizations first
              waveObjects.forEach((w, idx) => {
                hideWaveFibonacci(idx);
              });

              // Clear any previous traced wave (when clicking different arrow)
              if (window.tracedWaveSeries) {
                window.tracedWaveSeries.forEach(series => tvChart.removeSeries(series));
                window.tracedWaveSeries = [];
              }

              window.tracedWaveSeries = [];
              window.activeTracedArrowTime = arrow.time; // Remember which arrow is active

              // Draw the traced Wave structure
              // 1. Highlight the three reference points (Blue → Orange → Green)
              const points = [
                { ...waveStructure.swingLow1, color: '#2563eb', label: 'Swing Low 1' },  // Blue
                { ...waveStructure.swingHigh, color: '#f97316', label: 'Swing High' },   // Orange
                { ...waveStructure.swingLow2, color: '#10b981', label: 'Entry (Swing Low 2)' }  // Green
              ];

              points.forEach((point, idx) => {
                const highlightSeries = tvChart.addLineSeries({
                  color: point.color,
                  lineWidth: 0,
                  pointMarkersVisible: true,
                  pointMarkersRadius: 8,
                  title: point.label,
                  priceLineVisible: false,
                  lastValueVisible: false,
                  crosshairMarkerVisible: true,
                });
                highlightSeries.setData([{ time: point.time, value: point.price }]);
                window.tracedWaveSeries.push(highlightSeries);
              });

              // 2. Draw connecting lines
              const connectingLine = tvChart.addLineSeries({
                color: '#fbbf24',
                lineWidth: 3,
                lineStyle: 1,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
                title: 'Wave Structure',
              });
              connectingLine.setData([
                { time: waveStructure.swingLow1.time, value: waveStructure.swingLow1.price },
                { time: waveStructure.swingHigh.time, value: waveStructure.swingHigh.price },
                { time: waveStructure.swingLow2.time, value: waveStructure.swingLow2.price },
              ]);
              window.tracedWaveSeries.push(connectingLine);

              // 3. Show Fibonacci levels (100% = Activation, 161.8% = Target)
              const wave1Range = waveStructure.swingHigh.price - waveStructure.swingLow1.price;
              const projectionBase = waveStructure.swingLow2.price;

              const keyLevels = [
                { ratio: 1.000, label: '100% (Activation)', price: projectionBase + wave1Range, color: '#15803d' },
                { ratio: 1.618, label: '161.8% (Target)', price: projectionBase + (wave1Range * 1.618), color: '#fbbf24' }
              ];

              keyLevels.forEach(level => {
                const fibLine = tvChart.addLineSeries({
                  color: level.color,
                  lineWidth: 4,
                  lineStyle: level.ratio === 1.618 ? 0 : 2,
                  priceLineVisible: false,
                  lastValueVisible: true,
                  crosshairMarkerVisible: false,
                  title: level.label,
                });

                const now = Math.floor(Date.now() / 1000);
                fibLine.setData([
                  { time: now - (10 * 365 * 24 * 60 * 60), value: level.price },
                  { time: now + (2 * 365 * 24 * 60 * 60), value: level.price }
                ]);
                window.tracedWaveSeries.push(fibLine);
              });

              // 4. Draw Trailing Stop
              const entryTime = waveStructure.buyPoint.time;
              const entryPrice = waveStructure.buyPoint.price;
              const initialSL = waveStructure.swingLow2.price;
              const activationPrice = projectionBase + wave1Range; // 100% Extension

              const ts = calculateTrailingStopFromEntry(entryTime, entryPrice, initialSL, activationPrice);

              if (ts) {
                console.log(`📈 Calculated Trailing Stop:`, ts);
                drawTracedTrailingStop(ts, entryTime);
              }

              console.log(`✅ Displayed traced Wave structure from BUY arrow`);
            } else {
              // No valid Elliott Wave structure found
              console.warn('⚠️ Could not trace valid Wave structure from BUY arrow');
              console.log('📊 Using fallback: 7.5% profit activation for Trailing Stop');

              // Check if clicking the same arrow again (toggle off)
              if (window.activeTracedArrowTime === arrow.time) {
                console.log(`ℹ️ Clicking same arrow again - hiding Trailing Stop`);

                // Hide traced wave / Trailing Stop
                if (window.tracedWaveSeries) {
                  window.tracedWaveSeries.forEach(series => tvChart.removeSeries(series));
                  window.tracedWaveSeries = [];
                }
                window.activeTracedArrowTime = null;
                return;
              }

              // Clear any previous traced wave
              if (window.tracedWaveSeries) {
                window.tracedWaveSeries.forEach(series => tvChart.removeSeries(series));
                window.tracedWaveSeries = [];
              }

              window.tracedWaveSeries = [];
              window.activeTracedArrowTime = arrow.time; // Remember which arrow is active

              // Calculate Trailing Stop with 7.5% profit activation
              const entryTime = Math.floor(arrow.timestamp / 1000);
              const entryPrice = arrow.price;
              const initialSL = arrow.cutloss || entryPrice * 0.95; // Use cutloss or 5% below entry
              const activationPrice = entryPrice * 1.075; // 7.5% profit

              console.log(`📍 Entry: ${entryPrice}, Initial SL: ${initialSL}, Activation: ${activationPrice} (7.5% profit)`);

              // Show activation line
              const activationLine = tvChart.addLineSeries({
                color: '#fb923c',  // Orange
                lineWidth: 3,
                lineStyle: 2,  // Dashed
                priceLineVisible: false,
                lastValueVisible: true,
                crosshairMarkerVisible: false,
                title: 'Activation (7.5% Profit)',
              });

              const now = Math.floor(Date.now() / 1000);
              activationLine.setData([
                { time: now - (10 * 365 * 24 * 60 * 60), value: activationPrice },
                { time: now + (2 * 365 * 24 * 60 * 60), value: activationPrice }
              ]);
              window.tracedWaveSeries.push(activationLine);

              // Calculate and draw Trailing Stop
              const ts = calculateTrailingStopFromEntry(entryTime, entryPrice, initialSL, activationPrice);

              if (ts) {
                console.log(`📈 Calculated Trailing Stop (no Wave):`, ts);
                drawTracedTrailingStop(ts, entryTime);
              }

              console.log(`✅ Displayed Trailing Stop for non-Wave signal`);
            }

          } else {
            // Clicked on wave point (Blue/Red dot - NOT Green)
            const wave = waveObjects[closestMatch.waveIndex];
            console.log(`✅ Clicked on ${wave.waveId} ${closestMatch.pointType}, distance: ${minDistance.toFixed(2)}px`);

            // Close all other waves first
            waveObjects.forEach((w, idx) => {
              if (idx !== closestMatch.waveIndex) {
                hideWaveFibonacci(idx);
              }
            });

            // Toggle based on which point was clicked
            if (closestMatch.pointType === 'low') {
              // Click on Blue dot (swing_low_1) → Toggle Fibonacci Projection
              toggleWaveProjection(closestMatch.waveIndex);
            } else if (closestMatch.pointType === 'high') {
              // Click on Red dot (swing_high) → Toggle Fibonacci Retracement
              toggleWaveRetracement(closestMatch.waveIndex);
            }
            // Green dots (entry) are NOT clickable - removed 'entry' handler
          }
        } else {
          console.log('No wave point or BUY arrow close enough to click (threshold: ' + CLICK_THRESHOLD + 'px)');
        }
      }

      function hideWaveFibonacci(waveIndex) {
        const wave = waveObjects[waveIndex];
        if (!wave) return;

        // Hide all Fibonacci levels
        if (wave.projectionSeries) {
          wave.projectionSeries.forEach(series => tvChart.removeSeries(series));
          wave.projectionSeries = [];
        }
        if (wave.retracementSeries) {
          wave.retracementSeries.forEach(series => tvChart.removeSeries(series));
          wave.retracementSeries = [];
        }

        // Reference lines
        if (wave.referenceSeries) {
          wave.referenceSeries.forEach(series => tvChart.removeSeries(series));
          wave.referenceSeries = [];
        }

        // Hide Wave Structure
        if (wave.waveStructureSeries) {
          wave.waveStructureSeries.forEach(series => tvChart.removeSeries(series));
          wave.waveStructureSeries = [];
        }

        // Hide Trailing Stop
        if (wave.trailingStopSeries) {
          wave.trailingStopSeries.forEach(series => tvChart.removeSeries(series));
          wave.trailingStopSeries = [];
        }

        // Hide highlights (deprecated)
        if (wave.lowHighlightSeries) {
          wave.lowHighlightSeries.applyOptions({ pointMarkersVisible: false });
        }
        if (wave.highHighlightSeries) {
          wave.highHighlightSeries.applyOptions({ pointMarkersVisible: false });
        }

        wave.showingProjection = false;
        wave.showingRetracement = false;
        wave.showingTrailingStop = false;
        wave.showingWaveStructure = false;
      }

      function toggleTrailingStop(waveIndex, arrowData = null) {
        const wave = waveObjects[waveIndex];
        if (!wave || !wave.isBearWave) return;

        // Toggle Trailing Stop visibility
        if (wave.showingTrailingStop) {
          // Hide Trailing Stop
          if (wave.trailingStopSeries) {
            wave.trailingStopSeries.forEach(series => tvChart.removeSeries(series));
            wave.trailingStopSeries = [];
          }
          wave.showingTrailingStop = false;
          console.log(`ℹ️ Hid Trailing Stop for ${wave.waveId}`);
        } else {
          // Show Trailing Stop (pass arrowData if provided)
          drawTrailingStop(waveIndex, arrowData);
        }
      }

      function toggleWaveProjection(waveIndex) {
        const wave = waveObjects[waveIndex];
        if (!wave) return;

        // Simple Toggle for Fibonacci Projection
        if (wave.showingProjection) {
          // Hide Fibonacci Projection
          hideWaveFibonacci(waveIndex);
        } else {
          // Show projection (reduced levels: 38.2%, 61.8%, 100%, 161.8%, 261.8%)
          // IMPORTANT: Projection base is p3 (green dot - swing_low_2)
          // Formula: p3 + (Wave1Range × ratio), where Wave1Range = p2 - p1
          const wave1Range = wave.points.p2 - wave.points.p1;
          const projectionBase = wave.points.p3;  // Start from green dot (swing_low_2)

          const projectionLevels = [
            { ratio: 0.382, label: '38.2%', price: projectionBase + (wave1Range * 0.382) },
            { ratio: 0.618, label: '61.8%', price: projectionBase + (wave1Range * 0.618) },
            { ratio: 1.000, label: '100%', price: projectionBase + wave1Range },
            { ratio: 1.618, label: '161.8%', price: projectionBase + (wave1Range * 1.618) },
            { ratio: 2.618, label: '261.8%', price: projectionBase + (wave1Range * 2.618) },
          ];

          const projectionColors = {
            '38.2%': '#22c55e',  // Green
            '61.8%': '#16a34a',  // Darker green
            '100%': '#15803d',   // Even darker green
            '161.8%': '#fbbf24', // Yellow/gold (primary target)
            '261.8%': '#f59e0b'  // Orange
          };

          wave.projectionSeries = [];
          projectionLevels.forEach(level => {
            const color = projectionColors[level.label] || '#10b981';
            const fibLineWidth = (level.label === '161.8%') ? 4 : 3;  // Thicker lines

            const priceLine = tvChart.addLineSeries({
              color: color,
              lineWidth: fibLineWidth,
              lineStyle: level.label === '161.8%' ? 0 : 2,
              priceLineVisible: false,
              lastValueVisible: true,
              crosshairMarkerVisible: false,
              title: `${wave.waveId} Proj ${level.label}`,
            });

            // Make line span entire chart (10 years back, 2 years forward)
            const now = Math.floor(Date.now() / 1000);
            const lineData = [
              { time: now - (10 * 365 * 24 * 60 * 60), value: level.price },  // 10 years back
              { time: now + (2 * 365 * 24 * 60 * 60), value: level.price }     // 2 years forward
            ];

            priceLine.setData(lineData);
            wave.projectionSeries.push(priceLine);
          });

          // Draw connecting lines to show reference points (FORWARD direction)
          // For Projection: t1 (Blue Low) → t2 (Orange High) → t3 (Green Low)
          // Pattern must be: Index t1 < t2 < t3 (chronologically forward)
          const referenceLineSeries = tvChart.addLineSeries({
            color: '#fbbf24',  // Yellow/Orange
            lineWidth: 2,
            lineStyle: 1,  // Dotted line
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            title: '',
          });

          // Sort by time: t1 < t2 < t3
          const refLineData = [
            { time: wave.points.t1, value: wave.points.p1 },  // Low1 (blue - earliest)
            { time: wave.points.t2, value: wave.points.p2 },  // High (orange - middle)
            { time: wave.points.t3, value: wave.points.p3 },  // Low2 (green - latest)
          ];
          console.log(`📏 Reference line for ${wave.waveId}:`, {
            t1: new Date(wave.points.t1 * 1000).toISOString().split('T')[0],
            p1: wave.points.p1,
            t2: new Date(wave.points.t2 * 1000).toISOString().split('T')[0],
            p2: wave.points.p2,
            t3: new Date(wave.points.t3 * 1000).toISOString().split('T')[0],
            p3: wave.points.p3,
          });
          referenceLineSeries.setData(refLineData);
          wave.projectionSeries.push(referenceLineSeries);

          // Show yellow highlight on low dot
          if (wave.lowHighlightSeries) {
            wave.lowHighlightSeries.applyOptions({ pointMarkersVisible: true });
          }

          wave.showingProjection = true;
          console.log(`✅ Showed Projection for ${wave.waveId}`);
        }
      }

      // Calculate Trailing Stop from BUY arrow entry point
      function calculateTrailingStopFromEntry(entryTime, entryPrice, initialSL, activationPrice = null) {
        // Use data1d.candles (which has all 1D candles from backend)
        const candles1d = data1d?.candles || [];

        console.log(`🔍 Looking for entry candle at time: ${entryTime}, entry price: ${entryPrice}, initial SL: ${initialSL}`);
        console.log(`   data1d has ${candles1d.length} candles`);

        if (candles1d.length === 0) {
          console.warn('⚠️ No 1D candle data available');
          return null;
        }

        // Find entry candle index in 1D candles
        // entryTime is in seconds, candle.open_time is in milliseconds
        const entryMs = entryTime * 1000;
        let entryIndex = -1;

        // Try exact match first
        for (let i = 0; i < candles1d.length; i++) {
          if (candles1d[i].open_time === entryMs) {
            entryIndex = i;
            console.log(`✅ Found entry candle at index ${i} (exact match)`);
            break;
          }
        }

        // If exact match fails, find nearest candle (within 1 day tolerance)
        if (entryIndex === -1) {
          console.warn('⚠️ No exact match found, searching for nearest candle...');
          let minDiff = Infinity;
          for (let i = 0; i < candles1d.length; i++) {
            const diff = Math.abs(candles1d[i].open_time - entryMs);
            if (diff < minDiff && diff < 86400000) { // Within 1 day (24h in ms)
              minDiff = diff;
              entryIndex = i;
            }
          }

          if (entryIndex !== -1) {
            console.log(`✅ Found nearest entry candle at index ${entryIndex} (${minDiff}ms difference)`);
            console.log(`   Looking for: ${new Date(entryMs).toISOString()}`);
            console.log(`   Found: ${new Date(candles1d[entryIndex].open_time).toISOString()}`);
          } else {
            console.warn('⚠️ Entry candle not found');
            console.warn('   Searching for time:', entryTime, '(', new Date(entryMs).toISOString(), ')');
            console.warn('   Sample 1D candle times:', candles1d.slice(Math.max(0, candles1d.length - 3)).map(c => ({
              open_time: c.open_time,
              date: new Date(c.open_time).toISOString()
            })));
            return null;
          }
        }

        if (entryIndex >= candles1d.length - 1) {
          console.warn('⚠️ No candles after entry');
          return null;
        }

        const trailingStops = [];
        let currentSL = initialSL;
        let exitPoint = null;

        console.log(`📊 Starting Trailing Stop calculation:`);
        console.log(`   Entry Price: ${entryPrice}, Initial SL: ${initialSL}`);
        if (activationPrice) {
          console.log(`   Activation Price: ${activationPrice}`);
        }

        // Track previous candle's AVERAGE PRICE (Open + Close) / 2 for calculating NEXT candle's SL
        // Start from entry candle's average as the baseline
        const entryCandle = candles1d[entryIndex];
        let prevAvg = entryCandle ? (entryCandle.open + entryCandle.close) / 2 : entryPrice;
        let nextSL = initialSL;  // SL to be used in NEXT candle
        let isActivated = activationPrice ? false : true; // If no activation price, always active
        let activationPoint = null;

        // Scan each candle AFTER entry
        for (let i = entryIndex + 1; i < candles1d.length; i++) {
          const candle = candles1d[i];
          const avgPrice = (candle.open + candle.close) / 2;  // Average of open and close
          const low = candle.low;

          // IMPORTANT: Use SL calculated from PREVIOUS candle
          // This candle uses nextSL (which was calculated in previous iteration)
          currentSL = nextSL;

          // Check if price hit stop loss ONLY if activated
          if (isActivated && low <= currentSL) {
            exitPoint = {
              time: Math.floor(candle.open_time / 1000),
              price: currentSL,
            };
            console.log(`🛑 EXIT at candle ${i}: Low ${low} <= SL ${currentSL} (activated)`);
            break;
          }

          // Check if bullish trend ended (EMA crossover from Bull to Bear)
          // Stop calculating when EMA Fast crosses below EMA Slow
          const isBullish = candle.ema_fast > candle.ema_slow;
          if (!isBullish) {
            // Bullish trend ended, stop calculating
            console.log(`🛑 Bullish trend ENDED at candle ${i}: EMA crossover to Bearish`);
            exitPoint = {
              time: Math.floor(candle.open_time / 1000),
              price: candle.close,  // Exit at close price when trend reverses
            };
            break;
          }

          // Check if we should activate trailing stop
          // Activation occurs when candle's LOW is above 105% of activation price (Fibo level)
          // This ensures price has clearly broken above the activation level with buffer
          const activationThreshold = activationPrice * 1.05; // 105% of Fibo activation price
          if (!isActivated && activationPrice && candle.low >= activationThreshold) {
            isActivated = true;
            activationPoint = {
              time: Math.floor(candle.open_time / 1000),
              price: activationPrice,
            };
            console.log(`🎯 Trailing Stop ACTIVATED at candle ${i}: Low above 105% of Fibo (Low: ${candle.low} >= ${activationThreshold.toFixed(2)} [105% of ${activationPrice}])`);
          }

          // After checking exit, NOW calculate SL for NEXT candle
          // ALWAYS calculate based on current price - NOT just when making new highs
          // This allows SL to adjust during pullbacks and consolidation while trending up
          // Trailing Stop uses FIXED DISTANCE from current average price

          // Calculate SL as fixed percentage below current average price
          // Distance: 7% below current price (adjustable)
          const trailingDistance = 0.07; // 7% trailing distance
          const potentialSL = avgPrice * (1 - trailingDistance);

          // Trailing Stop can only rise, never fall
          // This ensures we lock in profits as price moves up
          if (potentialSL > nextSL) {
            nextSL = potentialSL;

            // Calculate how much price moved since last update
            const priceChange = avgPrice - prevAvg;
            const priceChangePercent = prevAvg > 0 ? (priceChange / prevAvg * 100) : 0;

            trailingStops.push({
              time: Math.floor(candle.open_time / 1000),
              price: nextSL,
              isActivated: isActivated,  // Store activation state
            });

            console.log(`📊 Candle ${i}: Price ${avgPrice.toFixed(2)} (${priceChangePercent >= 0 ? '+' : ''}${priceChangePercent.toFixed(2)}%), SL → ${nextSL.toFixed(2)} (${(trailingDistance * 100).toFixed(1)}% below)`);
          } else {
            // SL didn't move, but still record it for tooltip (using previous SL)
            trailingStops.push({
              time: Math.floor(candle.open_time / 1000),
              price: nextSL,
              isActivated: isActivated,
              unchanged: true,  // Mark that SL didn't change
            });
          }

          // Always update prevAvg to track price movement
          prevAvg = avgPrice;
        }

        console.log(`📈 Trailing Stop calculated: ${trailingStops.length} updates, Final SL: ${currentSL}`);

        return {
          initialSL,
          trailingStops,
          exitPoint,
          finalSL: currentSL,
          isActive: exitPoint === null,
          activationPoint,
          activationPrice,
        };
      }

      function drawTracedTrailingStop(ts, entryTime) {
        // Draw Trailing Stop for traced wave structure
        if (!ts) return;

        console.log(`📈 Drawing Trailing Stop for traced wave:`, ts);

        // Build SL data points: Create a point for EVERY candle from entry to exit
        const slDataPoints = [];
        const allCandles = data1d.candles;

        // Find entry candle index
        const entryIndex = allCandles.findIndex(c => Math.floor(c.open_time / 1000) === entryTime);
        if (entryIndex === -1) {
          console.error('❌ Entry candle not found for Trailing Stop visualization');
          return;
        }

        // Determine exit index (or use last candle if still active)
        let exitIndex = allCandles.length - 1;
        if (ts.exitPoint) {
          const foundExit = allCandles.findIndex(c => Math.floor(c.open_time / 1000) === ts.exitPoint.time);
          if (foundExit !== -1) exitIndex = foundExit;
        }

        // Create a map of SL updates by timestamp
        const slUpdates = new Map();
        const initialSL = ts.initialSL || ts.initial_sl;

        if (ts.trailingStops && ts.trailingStops.length > 0) {
          ts.trailingStops.forEach(update => {
            slUpdates.set(update.time, { price: update.price, isActivated: update.isActivated, unchanged: update.unchanged });

            // Store in global map for tooltip access
            trailingStopDataMap.set(update.time * 1000, {
              slPrice: update.price,
              isActivated: update.isActivated,
              unchanged: update.unchanged || false,
              entryTime: entryTime,
              initialSL: initialSL,
            });
          });
        }

        // Separate data points for pre-activation and active states
        const preActivationPoints = [];
        const activePoints = [];

        // Now iterate through EVERY candle from entry to exit
        let currentSL = initialSL;
        let isActivated = false;
        const activationTime = ts.activationPoint ? ts.activationPoint.time : null;

        for (let i = entryIndex; i <= exitIndex; i++) {
          const candle = allCandles[i];
          const candleTime = Math.floor(candle.open_time / 1000);

          // Check if we reached activation point
          if (activationTime && candleTime >= activationTime) {
            isActivated = true;
          }

          // Check if SL updated at this candle
          let slChanged = false;
          if (slUpdates.has(candleTime)) {
            const update = slUpdates.get(candleTime);
            const previousSL = currentSL;
            currentSL = update.price;
            isActivated = update.isActivated;
            slChanged = (currentSL !== previousSL);
          }

          // Store in global map for ALL candles (not just when SL changes)
          // This ensures tooltip shows SL for every candle in the position
          if (!trailingStopDataMap.has(candle.open_time)) {
            trailingStopDataMap.set(candle.open_time, {
              slPrice: currentSL,
              isActivated: isActivated,
              unchanged: !slChanged,
              entryTime: entryTime,
              initialSL: initialSL,
            });
          }

          // Add to appropriate array based on activation state
          if (isActivated) {
            activePoints.push({ time: candleTime, value: currentSL });
          } else {
            preActivationPoints.push({ time: candleTime, value: currentSL });
          }
        }

        console.log(`📊 Drawing Trailing Stop: ${preActivationPoints.length} pre-activation points, ${activePoints.length} active points`);

        // Draw Pre-Activation Trailing Stop (dashed orange line)
        if (preActivationPoints.length > 0) {
          const preActivationLine = tvChart.addLineSeries({
            color: '#fb923c',  // Orange
            lineWidth: 2,
            lineStyle: 2,  // Dashed
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: true,
            title: 'Trailing Stop (Calculating)',
          });
          preActivationLine.setData(preActivationPoints);
          window.tracedWaveSeries.push(preActivationLine);
        }

        // Draw Active Trailing Stop (solid red line)
        if (activePoints.length > 0) {
          const activeLine = tvChart.addLineSeries({
            color: '#ef4444',  // Red
            lineWidth: 2,
            lineStyle: 0,  // Solid
            priceLineVisible: false,
            lastValueVisible: true,
            crosshairMarkerVisible: true,
            title: 'Trailing Stop (Active)',
          });
          activeLine.setData(activePoints);
          window.tracedWaveSeries.push(activeLine);
        }

        // Draw entry marker
        const entryMarker = tvChart.addLineSeries({
          color: '#10b981',  // Green
          lineWidth: 0,
          pointMarkersVisible: true,
          pointMarkersRadius: 6,
          title: 'Entry',
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        entryMarker.setData([{ time: entryTime, value: initialSL }]);
        window.tracedWaveSeries.push(entryMarker);

        // Draw exit marker if exists
        if (ts.exitPoint) {
          const exitMarker = tvChart.addLineSeries({
            color: '#ef4444',  // Red
            lineWidth: 0,
            pointMarkersVisible: true,
            pointMarkersRadius: 6,
            title: 'Exit',
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          });
          exitMarker.setData([{ time: ts.exitPoint.time, value: ts.exitPoint.price }]);
          window.tracedWaveSeries.push(exitMarker);
        }

        // Draw activation marker if exists
        if (ts.activationPoint) {
          const activationMarker = tvChart.addLineSeries({
            color: '#fbbf24',  // Gold
            lineWidth: 0,
            pointMarkersVisible: true,
            pointMarkersRadius: 6,
            title: 'Activation',
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: true,
          });
          activationMarker.setData([{ time: ts.activationPoint.time, value: ts.activationPoint.price }]);
          window.tracedWaveSeries.push(activationMarker);
        }

        console.log(`✅ Drew Trailing Stop for traced wave`);
      }

      function drawTrailingStop(waveIndex, arrowData = null) {
        const wave = waveObjects[waveIndex];
        if (!wave || !wave.isBearWave) {
          console.warn(`⚠️ Not a Bear wave: ${wave?.waveId}`);
          return;
        }

        let ts;
        let entryTime;

        if (arrowData) {
          // Calculate Trailing Stop from BUY arrow entry point
          console.log(`📈 Calculating Trailing Stop from BUY arrow:`, arrowData);
          entryTime = arrowData.time;
          // arrowData.price is the entry price (buy price)
          // arrowData.cutloss is the initial stop loss
          ts = calculateTrailingStopFromEntry(arrowData.time, arrowData.price, arrowData.cutloss);
          if (!ts) {
            console.warn(`⚠️ Could not calculate Trailing Stop from arrow`);
            return;
          }
        } else {
          // Use pre-calculated Trailing Stop from backend (wave pattern)
          if (!wave.trailingStop) {
            console.warn(`⚠️ No trailing stop data for wave ${wave.waveId}`);
            return;
          }
          ts = wave.trailingStop;
          entryTime = wave.points.t3;
        }

        console.log(`📈 Drawing Trailing Stop for ${wave.waveId}:`, ts);

        // Hide Fibonacci first
        if (wave.projectionSeries) {
          wave.projectionSeries.forEach(series => tvChart.removeSeries(series));
          wave.projectionSeries = [];
        }

        // Create trailing stop line series (step line showing SL updates)
        wave.trailingStopSeries = [];

        // Build SL data points: Create a point for EVERY candle from entry to exit
        // This creates the proper "staircase" pattern instead of diagonal lines
        const slDataPoints = [];

        // Get all candles from data1d
        const allCandles = data1d.candles;

        // Find entry candle index
        const entryIndex = allCandles.findIndex(c => Math.floor(c.open_time / 1000) === entryTime);
        if (entryIndex === -1) {
          console.error('❌ Entry candle not found for Trailing Stop visualization');
          return;
        }

        // Determine exit index (or use last candle if still active)
        let exitIndex = allCandles.length - 1;
        if (ts.exitPoint) {
          const foundExit = allCandles.findIndex(c => Math.floor(c.open_time / 1000) === ts.exitPoint.time);
          if (foundExit !== -1) exitIndex = foundExit;
        } else if (ts.exit_point) {
          const exitTime = ts.exit_point.open_time ? Math.floor(ts.exit_point.open_time / 1000) : null;
          if (exitTime) {
            const foundExit = allCandles.findIndex(c => Math.floor(c.open_time / 1000) === exitTime);
            if (foundExit !== -1) exitIndex = foundExit;
          }
        }

        // Create a map of SL updates by timestamp for quick lookup
        const slUpdates = new Map();
        const initialSL = ts.initialSL || ts.initial_sl;

        if (ts.trailingStops && ts.trailingStops.length > 0) {
          // Frontend calculated (from arrow)
          ts.trailingStops.forEach(update => {
            slUpdates.set(update.time, update.price);
          });
        } else if (ts.trailing_stops && ts.trailing_stops.length > 0) {
          // Backend calculated (from wave)
          ts.trailing_stops.forEach(update => {
            const timestamp = update.open_time ? Math.floor(update.open_time / 1000) : null;
            if (timestamp) {
              slUpdates.set(timestamp, update.price);
            }
          });
        }

        // Now iterate through EVERY candle from entry to exit
        let currentSL = initialSL;
        for (let i = entryIndex; i <= exitIndex; i++) {
          const candle = allCandles[i];
          const candleTime = Math.floor(candle.open_time / 1000);

          // Check if SL updated at this candle
          if (slUpdates.has(candleTime)) {
            currentSL = slUpdates.get(candleTime);
          }

          // Add data point with current SL level (creates horizontal steps)
          slDataPoints.push({ time: candleTime, value: currentSL });
        }

        // Draw Trailing Stop line (green step line)
        const trailingStopLine = tvChart.addLineSeries({
          color: '#22c55e',  // Green
          lineWidth: 3,
          lineStyle: 0,  // Solid line
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: true,
          title: `${wave.waveId} Trailing SL`,
        });
        trailingStopLine.setData(slDataPoints);
        wave.trailingStopSeries.push(trailingStopLine);

        // Draw entry marker (Green dot)
        const entryMarker = tvChart.addLineSeries({
          color: '#10b981',  // Bright green
          lineWidth: 0,
          pointMarkersVisible: true,
          pointMarkersRadius: 6,
          title: 'Entry',
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        entryMarker.setData([{ time: entryTime, value: ts.initialSL || ts.initial_sl }]);
        wave.trailingStopSeries.push(entryMarker);

        // Draw exit marker if position closed
        const hasExit = ts.exitPoint || ts.exit_point;
        if (hasExit) {
          let exitTime, exitPrice;

          if (ts.exitPoint) {
            // Frontend calculated
            exitTime = ts.exitPoint.time;
            exitPrice = ts.exitPoint.price;
          } else if (ts.exit_point) {
            // Backend calculated
            exitTime = ts.exit_point.open_time ? Math.floor(ts.exit_point.open_time / 1000) : null;
            exitPrice = ts.exit_point.price;
          }

          if (exitTime) {
            const exitMarker = tvChart.addLineSeries({
              color: '#ef4444',  // Red
              lineWidth: 0,
              pointMarkersVisible: true,
              pointMarkersRadius: 6,
              title: 'Exit',
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
            });
            exitMarker.setData([{ time: exitTime, value: exitPrice }]);
            wave.trailingStopSeries.push(exitMarker);
          }
        }

        wave.showingProjection = false;
        wave.showingTrailingStop = true;
        console.log(`✅ Showed Trailing Stop for ${wave.waveId}`);
      }

      function toggleWaveRetracement(waveIndex) {
        const wave = waveObjects[waveIndex];
        if (!wave) return;

        // Toggle retracement
        if (wave.showingRetracement) {
          // Hide retracement
          if (wave.retracementSeries) {
            wave.retracementSeries.forEach(series => tvChart.removeSeries(series));
            wave.retracementSeries = [];
          }
          // Hide highlight
          if (wave.highHighlightSeries) {
            wave.highHighlightSeries.applyOptions({ pointMarkersVisible: false });
          }
          wave.showingRetracement = false;
          console.log(`ℹ️ Hid Retracement for ${wave.waveId}`);
        } else {
          // Show retracement (0%, 61.8%, 78.6%, 88.7%, 94.2%, 100%)
          console.log(`🔮 Showing Retracement for ${wave.waveId}, fibLevels:`, wave.fibLevels);

          // Use darker, more vibrant purple/magenta colors
          const retracementColors = {
            '0%': '#e879f9',    // Light magenta
            '61.8%': '#d946ef', // Magenta
            '78.6%': '#c026d3', // Fuchsia (important level)
            '88.7%': '#a21caf', // Purple (important level)
            '94.2%': '#86198f', // Dark purple
            '100%': '#701a75'   // Darkest purple
          };

          wave.retracementSeries = [];
          wave.fibLevels.forEach(level => {
            const color = retracementColors[level.label] || '#a855f7';
            const fibLineWidth = (level.label === '78.6%' || level.label === '88.7%') ? 4 : 3;  // Thicker lines

            const priceLine = tvChart.addLineSeries({
              color: color,
              lineWidth: fibLineWidth,
              lineStyle: 2,
              priceLineVisible: false,
              lastValueVisible: true,
              crosshairMarkerVisible: false,
              title: `${wave.waveId} Ret ${level.label}`,
            });

            // Make line span entire chart (10 years back, 2 years forward)
            const now = Math.floor(Date.now() / 1000);
            const lineData = [
              { time: now - (10 * 365 * 24 * 60 * 60), value: level.price },  // 10 years back
              { time: now + (2 * 365 * 24 * 60 * 60), value: level.price }     // 2 years forward
            ];

            priceLine.setData(lineData);
            wave.retracementSeries.push(priceLine);
          });

          // Draw connecting lines to show reference points (Low → High)
          const referenceLineSeries = tvChart.addLineSeries({
            color: '#fbbf24',  // Yellow
            lineWidth: 2,
            lineStyle: 1,  // Dotted line
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            title: '',
          });

          const refLineData = [
            { time: wave.points.t1, value: wave.points.p1 },  // Wave 1 Low
            { time: wave.points.t2, value: wave.points.p2 },  // Wave 1 High
          ];
          referenceLineSeries.setData(refLineData);
          wave.retracementSeries.push(referenceLineSeries);

          // Show yellow highlight on high dot
          if (wave.highHighlightSeries) {
            wave.highHighlightSeries.applyOptions({ pointMarkersVisible: true });
          }

          wave.showingRetracement = true;
          console.log(`✅ Showed Retracement for ${wave.waveId}`);
        }
      }

      function traceWaveStructureFromBuyArrow(arrowData) {
        // Trace back Elliott Wave structure from BUY arrow position
        // Pattern: Bearish(Blue) → Bullish(Orange) → Bearish(Green) → Bullish(BUY)
        //
        // Logic:
        // 1. BUY is in Bullish zone → Skip entire Bullish zone
        // 2. Find Bearish zone before → Swing Low 2 (Green) = lowest in entire zone
        // 3. Find Bullish zone before → Swing High (Orange) = highest in entire zone
        // 4. Find Bearish zone before → Swing Low 1 (Blue) = lowest in entire zone (must < Swing Low 2)

        const candles1d = data1d.candles;
        const buyTimestamp = arrowData.timestamp; // milliseconds

        console.log(`🔍 Tracing Wave structure from BUY arrow at ${new Date(buyTimestamp).toISOString()}`);

        // Find BUY candle index in 1D
        let buyIndex = -1;
        for (let i = candles1d.length - 1; i >= 0; i--) {
          if (candles1d[i].open_time <= buyTimestamp) {
            buyIndex = i;
            break;
          }
        }

        if (buyIndex < 10) {
          console.warn('⚠️ Not enough candles before BUY point');
          return null;
        }

        const buyZone = candles1d[buyIndex].action_zone;
        console.log(`📍 BUY at index ${buyIndex}, zone: ${buyZone}`);

        // Helper function to find entire EMA crossover zone boundaries
        // Bull zone = EMA Fast > EMA Slow
        // Bear zone = EMA Fast < EMA Slow
        function findEMAZoneBoundaries(startIndex, isBullish) {
          let zoneStart = -1;
          let zoneEnd = -1;

          // Find first candle of this EMA trend
          for (let i = startIndex; i >= 0; i--) {
            const candle = candles1d[i];
            const isBullCandle = candle.ema_fast > candle.ema_slow;

            if (isBullCandle === isBullish) {
              zoneEnd = i;
              break;
            }
          }

          if (zoneEnd === -1) return null;

          // Find where zone ends (scan backwards until EMA crossover)
          for (let i = zoneEnd; i >= 0; i--) {
            const candle = candles1d[i];
            const isBullCandle = candle.ema_fast > candle.ema_slow;

            if (isBullCandle === isBullish) {
              zoneStart = i;
            } else {
              break; // EMA crossed over, exit zone
            }
          }

          return { start: zoneStart, end: zoneEnd };
        }

        // Step 1: Skip current Bullish zone (where BUY is - EMA Fast > Slow)
        const bullishZoneBuy = findEMAZoneBoundaries(buyIndex, true);
        if (!bullishZoneBuy) {
          console.warn('⚠️ Could not find Bullish zone for BUY');
          return null;
        }
        console.log(`⏭️ Skipped Bullish EMA zone at BUY: [${bullishZoneBuy.start}, ${bullishZoneBuy.end}]`);

        // Step 2: Find Bearish zone before → Swing Low 2 (Green)
        const bearishZone2 = findEMAZoneBoundaries(bullishZoneBuy.start - 1, false);
        if (!bearishZone2) {
          console.warn('⚠️ Could not find Bearish zone for Swing Low 2');
          return null;
        }

        // Find LOWEST point in this Bearish zone
        let swingLow2 = null;
        for (let i = bearishZone2.end; i >= bearishZone2.start; i--) {
          if (!swingLow2 || candles1d[i].low < swingLow2.price) {
            swingLow2 = {
              index: i,
              price: candles1d[i].low,
              time: Math.floor(candles1d[i].open_time / 1000),
              zone: candles1d[i].action_zone
            };
          }
        }
        console.log(`🟢 Swing Low 2 found at index ${swingLow2.index}, price ${swingLow2.price}, EMA Bear zone range [${bearishZone2.start}, ${bearishZone2.end}]`);

        // Step 3: Find Bullish zone before → Swing High (Orange)
        const bullishZone = findEMAZoneBoundaries(bearishZone2.start - 1, true);
        if (!bullishZone) {
          console.warn('⚠️ Could not find Bullish zone for Swing High');
          return null;
        }

        // Find HIGHEST point in this Bullish zone
        let swingHigh = null;
        for (let i = bullishZone.end; i >= bullishZone.start; i--) {
          if (!swingHigh || candles1d[i].high > swingHigh.price) {
            swingHigh = {
              index: i,
              price: candles1d[i].high,
              time: Math.floor(candles1d[i].open_time / 1000),
              zone: candles1d[i].action_zone
            };
          }
        }
        console.log(`🟠 Swing High found at index ${swingHigh.index}, price ${swingHigh.price}, EMA Bull zone range [${bullishZone.start}, ${bullishZone.end}]`);

        // Step 4: Find Bearish zone before → Swing Low 1 (Blue)
        const bearishZone1 = findEMAZoneBoundaries(bullishZone.start - 1, false);
        if (!bearishZone1) {
          console.warn('⚠️ Could not find Bearish zone for Swing Low 1');
          return null;
        }

        // Find LOWEST point in this Bearish zone
        let swingLow1 = null;
        for (let i = bearishZone1.end; i >= bearishZone1.start; i--) {
          if (!swingLow1 || candles1d[i].low < swingLow1.price) {
            swingLow1 = {
              index: i,
              price: candles1d[i].low,
              time: Math.floor(candles1d[i].open_time / 1000),
              zone: candles1d[i].action_zone
            };
          }
        }

        console.log(`🔵 Swing Low 1 found at index ${swingLow1.index}, price ${swingLow1.price}, EMA Bear zone range [${bearishZone1.start}, ${bearishZone1.end}]`);

        // Validate: Swing Low 1 must be lower than Swing Low 2
        if (swingLow1.price >= swingLow2.price) {
          console.warn(`⚠️ Invalid Wave: Swing Low 1 (${swingLow1.price}) not lower than Swing Low 2 (${swingLow2.price})`);
          return null;
        }

        console.log(`✅ Valid Wave Pattern: Low1(${swingLow1.price}) < Low2(${swingLow2.price}) < High(${swingHigh.price})`);

        return {
          swingLow1,
          swingHigh,
          swingLow2,
          buyPoint: {
            time: Math.floor(buyTimestamp / 1000),
            price: arrowData.price
          }
        };
      }

      function toggleWaveStructure(waveIndex) {
        // Show Elliott Wave structure + Trailing Stop when clicking Green dot (entry point)
        const wave = waveObjects[waveIndex];
        if (!wave || !wave.isBearWave) return;

        console.log(`🌊 Clicked on entry point (Green dot) for ${wave.waveId}`);

        // Toggle visibility
        if (wave.showingWaveStructure) {
          // Hide Wave Structure
          if (wave.waveStructureSeries) {
            wave.waveStructureSeries.forEach(series => tvChart.removeSeries(series));
            wave.waveStructureSeries = [];
          }
          // Hide Trailing Stop
          if (wave.trailingStopSeries) {
            wave.trailingStopSeries.forEach(series => tvChart.removeSeries(series));
            wave.trailingStopSeries = [];
          }
          wave.showingWaveStructure = false;
          wave.showingTrailingStop = false;
          console.log(`ℹ️ Hid Wave Structure for ${wave.waveId}`);
        } else {
          // Show Wave Structure + Trailing Stop
          wave.waveStructureSeries = [];

          // 1. Highlight the three reference points (Blue → Orange → Green)
          const points = [
            { time: wave.points.t1, price: wave.points.p1, color: '#2563eb', label: 'Swing Low 1' },  // Blue
            { time: wave.points.t2, price: wave.points.p2, color: '#f97316', label: 'Swing High' },   // Orange
            { time: wave.points.t3, price: wave.points.p3, color: '#10b981', label: 'Entry (Swing Low 2)' }  // Green
          ];

          // Draw highlighted markers for each point
          points.forEach((point, idx) => {
            const highlightSeries = tvChart.addLineSeries({
              color: point.color,
              lineWidth: 0,
              pointMarkersVisible: true,
              pointMarkersRadius: 8,  // Larger radius for highlight
              title: point.label,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: true,
            });
            highlightSeries.setData([{ time: point.time, value: point.price }]);
            wave.waveStructureSeries.push(highlightSeries);
          });

          // 2. Draw connecting lines between the three points
          const connectingLine = tvChart.addLineSeries({
            color: '#fbbf24',  // Yellow/Gold
            lineWidth: 3,
            lineStyle: 1,  // Dotted line
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
            title: 'Wave Structure',
          });
          connectingLine.setData([
            { time: wave.points.t1, value: wave.points.p1 },  // Blue dot
            { time: wave.points.t2, value: wave.points.p2 },  // Orange dot
            { time: wave.points.t3, value: wave.points.p3 },  // Green dot
          ]);
          wave.waveStructureSeries.push(connectingLine);

          // 3. Show key Fibonacci levels (100% Extension = Activation Price, 161.8% = Target)
          const wave1Range = wave.points.p2 - wave.points.p1;
          const projectionBase = wave.points.p3;

          const keyLevels = [
            { ratio: 1.000, label: '100% (Activation)', price: projectionBase + wave1Range, color: '#15803d' },      // Dark green
            { ratio: 1.618, label: '161.8% (Target)', price: projectionBase + (wave1Range * 1.618), color: '#fbbf24' }  // Gold
          ];

          keyLevels.forEach(level => {
            const fibLine = tvChart.addLineSeries({
              color: level.color,
              lineWidth: 4,
              lineStyle: level.ratio === 1.618 ? 0 : 2,  // Solid for target, dashed for activation
              priceLineVisible: false,
              lastValueVisible: true,
              crosshairMarkerVisible: false,
              title: level.label,
            });

            const now = Math.floor(Date.now() / 1000);
            fibLine.setData([
              { time: now - (10 * 365 * 24 * 60 * 60), value: level.price },
              { time: now + (2 * 365 * 24 * 60 * 60), value: level.price }
            ]);
            wave.waveStructureSeries.push(fibLine);
          });

          // 4. Show Trailing Stop
          drawTrailingStop(waveIndex, null);

          wave.showingWaveStructure = true;
          console.log(`✅ Showed Wave Structure + Trailing Stop for ${wave.waveId}`);
        }
      }

      // ==========================================
      // Multi-Timeframe Validation Functions
      // ==========================================

      // Helper: Find candle by timestamp (or closest before)
      function findCandleByTime(candles, timestamp) {
        if (!candles || candles.length === 0) return null;
        for (let i = candles.length - 1; i >= 0; i--) {
          if (candles[i].open_time <= timestamp) {
            return candles[i];
          }
        }
        return null;
      }

      // 1. Validate 1W: Must be in Bull trend
      function validate1W_Bull(timestamp, candles1w) {
        const candle = findCandleByTime(candles1w, timestamp);
        if (!candle) {
          return { valid: false, reason: 'no_1w_candle' };
        }
        const isBull = candle.ema_fast > candle.ema_slow;
        return {
          valid: isBull,
          reason: isBull ? '1w_bull_ok' : '1w_not_bull'
        };
      }

      // 2. Validate 1D: Must be Bull + have blue→green pattern
      function validate1D_BuyPattern(timestamp, candles1d) {
        if (!candles1d || candles1d.length < 3) {
          return { valid: false, reason: 'no_1d_data' };
        }

        // Find index of candle at or before timestamp
        let idx = -1;
        for (let i = candles1d.length - 1; i >= 0; i--) {
          if (candles1d[i].open_time <= timestamp) {
            idx = i;
            break;
          }
        }

        if (idx < 2) {
          return { valid: false, reason: '1d_insufficient_data' };
        }

        const c = candles1d[idx];
        const zone_i2 = candles1d[idx - 2].action_zone;
        const zone_i1 = candles1d[idx - 1].action_zone;
        const isBull = c.ema_fast > c.ema_slow;
        const hasPattern = (zone_i2 === 'blue' && zone_i1 === 'green');

        return {
          valid: isBull && hasPattern,
          reason: isBull && hasPattern ? '1d_pattern_ok' : '1d_no_pattern',
          candleIndex: idx
        };
      }

      // 3. Find 1H Buy Entry after 1D signal
      function find1H_BuyEntry(dailyTimestamp, candles1h) {
        if (!candles1h || candles1h.length < 3) {
          return { found: false, reason: 'no_1h_data' };
        }

        // หาแท่ง 1H หลังจาก daily signal
        const candidates = candles1h.filter(c => c.open_time >= dailyTimestamp);

        for (let i = 2; i < candidates.length; i++) {
          const c = candidates[i];
          const zone_i2 = candidates[i - 2].action_zone;
          const zone_i1 = candidates[i - 1].action_zone;
          const isBull = c.ema_fast > c.ema_slow;
          const isVShape = c.is_v_shape === true;

          // ต้องเป็น blue→green + Bull + NOT V-shape
          if (zone_i2 === 'blue' && zone_i1 === 'green' && isBull && !isVShape) {
            return {
              found: true,
              entryTime: c.open_time,
              entryPrice: c.close,
              candleIndex: i
            };
          }
        }

        return { found: false, reason: 'no_1h_entry' };
      }

      // 4. Validate 1D: Must have orange→red pattern
      function validate1D_SellPattern(timestamp, candles1d) {
        if (!candles1d || candles1d.length < 3) {
          return { valid: false, reason: 'no_1d_data' };
        }

        let idx = -1;
        for (let i = candles1d.length - 1; i >= 0; i--) {
          if (candles1d[i].open_time <= timestamp) {
            idx = i;
            break;
          }
        }

        if (idx < 2) {
          return { valid: false, reason: '1d_insufficient_data' };
        }

        const zone_i2 = candles1d[idx - 2].action_zone;
        const zone_i1 = candles1d[idx - 1].action_zone;
        const hasPattern = (zone_i2 === 'orange' && zone_i1 === 'red');

        return {
          valid: hasPattern,
          reason: hasPattern ? '1d_sell_pattern_ok' : '1d_no_sell_pattern',
          candleIndex: idx
        };
      }

      // 5. Find 1H Sell Exit after 1D signal
      function find1H_SellExit(dailyTimestamp, candles1h) {
        if (!candles1h || candles1h.length === 0) {
          return { found: false, reason: 'no_1h_data' };
        }

        // หาแท่ง 1H หลังจาก daily signal ที่เป็น bearish/red
        const candidates = candles1h.filter(c => c.open_time >= dailyTimestamp);

        for (let i = 0; i < candidates.length; i++) {
          const c = candidates[i];
          const isBearish = c.ema_fast < c.ema_slow && c.close < c.ema_fast;
          const isRedZone = c.action_zone === 'red';

          if (isBearish || isRedZone) {
            return {
              found: true,
              exitTime: c.open_time,
              exitPrice: c.close
            };
          }
        }

        return { found: false, reason: 'no_1h_exit' };
      }

      // 6. Calculate Cutloss from 1D red candles
      function calc1D_Cutloss(candleIndex, candles1d, entryPrice) {
        const lookback = 30;
        let cutlossPrice = entryPrice * 0.95; // fallback

        let redCandles = [];
        for (let j = candleIndex - 1; j >= Math.max(0, candleIndex - lookback); j--) {
          const zone = candles1d[j].action_zone;
          if (zone === 'red') {
            redCandles.push(candles1d[j].close);
          } else if (redCandles.length > 0) {
            break;
          }
        }

        if (redCandles.length > 0) {
          cutlossPrice = Math.min(...redCandles);
        } else if (candleIndex >= 2) {
          cutlossPrice = Math.min(candles1d[candleIndex - 2].close, candles1d[candleIndex - 1].close);
        }

        return cutlossPrice;
      }

      // 7. Calculate Stop Loss from 1D green candles
      function calc1D_StopLoss(candleIndex, candles1d, entryPrice) {
        const lookback = 30;
        let stoplossPrice = entryPrice * 1.05; // fallback

        let greenCandles = [];
        for (let j = candleIndex - 1; j >= Math.max(0, candleIndex - lookback); j--) {
          const zone = candles1d[j].action_zone;
          if (zone === 'green') {
            greenCandles.push(candles1d[j].close);
          } else if (greenCandles.length > 0) {
            break;
          }
        }

        if (greenCandles.length > 0) {
          stoplossPrice = Math.max(...greenCandles);
        } else if (candleIndex >= 2) {
          stoplossPrice = Math.max(candles1d[candleIndex - 2].close, candles1d[candleIndex - 1].close);
        }

        return stoplossPrice;
      }

      async function loadCandles(pair) {
        // Clear BUY arrow markers and traced wave state on reload
        buyArrowMarkers = [];
        window.activeTracedArrowTime = null;
        if (window.tracedWaveSeries) {
          window.tracedWaveSeries.forEach(series => tvChart.removeSeries(series));
          window.tracedWaveSeries = [];
        }
        try {
          console.log("🔄 Loading candles for pair:", pair);
          initChart();

          // Get selected display timeframe (1d or 1h)
          const displayTF = timeframeSelect.value;
          console.log(`📊 Display timeframe: ${displayTF}`);

          // Fixed 3-Timeframe System: Always fetch 1W, 1D, 1H (Maximum data for analysis)
          const tf1w_url = `/market/candles?pair=${encodeURIComponent(pair)}&interval=1w&limit=200&include_indicators=true`;  // ~4 years
          const tf1d_url = `/market/candles?pair=${encodeURIComponent(pair)}&interval=1d&limit=1000&include_indicators=true`; // ~3 years
          const tf1h_url = `/market/candles?pair=${encodeURIComponent(pair)}&interval=1h&limit=1000&include_indicators=true`; // ~42 days

          console.log("📡 Fetching 1W from:", tf1w_url);
          console.log("📡 Fetching 1D from:", tf1d_url);
          console.log("📡 Fetching 1H from:", tf1h_url);

          const [resp1w, resp1d, resp1h] = await Promise.all([
            fetch(tf1w_url),
            fetch(tf1d_url),
            fetch(tf1h_url)
          ]);

          if (!resp1w.ok || !resp1d.ok || !resp1h.ok) {
            console.error("❌ Failed to fetch one or more timeframes");
            throw new Error("ไม่สามารถดึงข้อมูลราคาได้ กรุณาลองใหม่");
          }

          // Assign to global variables for tooltip access
          data1w = await resp1w.json();
          data1d = await resp1d.json();
          data1h = await resp1h.json();

          // Drop any candles with null/NaN to prevent "Value is null" crashes
          data1w.candles = sanitizeCandles(data1w.candles, "1W");
          data1d.candles = sanitizeCandles(data1d.candles, "1D");
          data1h.candles = sanitizeCandles(data1h.candles, "1H");

          console.log("📦 1W candles:", data1w.candles?.length || 0);
          console.log("📦 1D candles:", data1d.candles?.length || 0);
          console.log("📦 1H candles:", data1h.candles?.length || 0);

          // Select which data to display on chart based on displayTF
          let data;
          if (displayTF === '1w') {
            data = data1w;
          } else if (displayTF === '1d') {
            data = data1d;
          } else {
            data = data1h;
          }

          const candles = (data.candles || []).map(c => {
            const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
            return {
              time: t,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
            };
          });

          console.log("🕒 First candle timestamp:", candles[0]?.time);
          console.log("🕒 Last candle timestamp:", candles[candles.length - 1]?.time);

          if (!candles.length) {
            console.warn("⚠️ ไม่มีข้อมูลแท่งเทียนสำหรับคู่ที่เลือก");
            candleSeries.setData([]);
            return;
          }

          // Color candles based on CDC zone (2 colors: green/red)
          const coloredCandles = (data.candles || []).map(c => {
            const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
            const zone = c.action_zone || c.cdc_color || 'red';
            const palette = zoneColors[zone] || zoneColors.red;
            return {
              time: t,
              open: c.open,
              high: c.high,
              low: c.low,
              close: c.close,
              color: palette.body,
              wickColor: palette.wick,
              borderColor: palette.border,
            };
          });

          candleSeries.setData(coloredCandles);

          // Create EMA line data
          const emaFastData = (data.candles || []).map(c => {
            const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
            return { time: t, value: c.ema_fast };
          });

          const emaSlowData = (data.candles || []).map(c => {
            const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
            return { time: t, value: c.ema_slow };
          });

          // Set EMA lines
          emaFastSeries.setData(emaFastData);
          emaSlowSeries.setData(emaSlowData);

          // Calculate and set RSI
          const closes = (data.candles || []).map(c => c.close);
          const rsiValues = calculateRSI(closes, 14);

          // Prepare RSI data (offset by RSI period since RSI starts after period candles)
          const rsiDataPoints = [];
          const rsiPeriod = 14;
          for (let i = 0; i < rsiValues.length; i++) {
            const candleIdx = i + rsiPeriod;
            if (candleIdx < data.candles.length) {
              const c = data.candles[candleIdx];
              const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
              rsiDataPoints.push({
                time: t,
                value: rsiValues[i],
                candleIndex: candleIdx, // Store index for later reference
              });
            }
          }
          rsiSeries.setData(rsiDataPoints);

          // Store RSI data globally for divergence detection
          rsiData = rsiDataPoints;
          console.log("📊 RSI loaded with", rsiDataPoints.length, "values");

          // Set RSI reference lines (Overbought 70, Oversold 30)
          if (rsiDataPoints.length > 0) {
            const overboughtData = rsiDataPoints.map(d => ({ time: d.time, value: 70 }));
            const oversoldData = rsiDataPoints.map(d => ({ time: d.time, value: 30 }));

            rsiOverboughtSeries.setData(overboughtData);
            rsiOversoldSeries.setData(oversoldData);

            // Force RSI scale to show 0-100 range with invisible data points
            const minMaxData = [
              { time: rsiDataPoints[0].time, value: 0 },
              { time: rsiDataPoints[0].time, value: 100 },
              { time: rsiDataPoints[rsiDataPoints.length - 1].time, value: 0 },
              { time: rsiDataPoints[rsiDataPoints.length - 1].time, value: 100 },
            ];
            rsiMinMaxSeries.setData(minMaxData);

            // Detect and draw divergences with zone data
            // ต้อง slice candles และ zoneData ให้เริ่มจาก index 14 เพราะ RSI เริ่มที่ candle ที่ 15
            const rsiStartIndex = 14; // RSI period
            const candlesForRSI = data.candles.slice(rsiStartIndex);
            const zoneDataForRSI = candlesForRSI.map(c => ({
              ema_fast: c.ema_fast,
              ema_slow: c.ema_slow,
              zone: c.action_zone || c.cdc_color || 'red'
            }));

            console.log(`📊 Candles for RSI: ${candlesForRSI.length}, RSI values: ${rsiDataPoints.length}`);

            // Extra safety: guard against unexpected undefined from detectDivergence
            const divergenceResult = detectDivergence(candlesForRSI, rsiDataPoints, zoneDataForRSI) || {
              divergences: [],
              candleStates: [],
            };
            detectedDivergences = divergenceResult.divergences || [];
            candleStates = divergenceResult.candleStates || [];
            drawDivergenceLines(detectedDivergences);
            console.log(`🔍 Detected ${detectedDivergences.length} divergences:`, detectedDivergences);
            console.log(`📊 candleStates length: ${candleStates.length}`);

            // ═══════════════════════════════════════════════════════════════════
            // ENHANCED EXIT SIGNAL DETECTION
            // Add exit_reason field to candleStates for multi-type exit signals
            // ═══════════════════════════════════════════════════════════════════
            console.log("🔍 Enhancing candleStates with multi-type exit signals...");
            console.log(`📊 detectedDivergences: ${detectedDivergences.length}, candleStates: ${candleStates.length}`);

            let lastBuyIndex = -1;
            let buyPrice = 0;
            let cutloss = 0;

            candleStates.forEach((state, idx) => {
              // Track BUY entries
              if (state.special_signal === 'BUY') {
                lastBuyIndex = idx;
                buyPrice = candlesForRSI[idx]?.close || 0;
                cutloss = state.cutloss || buyPrice * 0.95;
                state.exit_reason = null; // BUY has no exit_reason
                return;
              }

              // We're in a position if we found a BUY before
              if (lastBuyIndex >= 0 && idx > lastBuyIndex) {
                const candle = candlesForRSI[idx];
                if (!candle) return;

                // Priority order: Trailing Stop > Divergence > EMA Cross > Stop Loss

                // 1. Check Trailing Stop (if trailingStopDataMap has data for this candle)
                const tsInfo = trailingStopDataMap.get(candle.open_time);
                if (tsInfo && tsInfo.isActivated && candle.low <= tsInfo.slPrice) {
                  if (!state.special_signal) { // Don't override existing signals
                    state.special_signal = 'SELL';
                    state.exit_reason = 'TRAILING_STOP';
                    state.exit_price = tsInfo.slPrice;
                    console.log(`📈 Trailing Stop Exit at index ${idx}, price ${tsInfo.slPrice}`);
                    lastBuyIndex = -1; // Reset position
                    return;
                  }
                }

                // 2. Check Bearish Divergence
                const bearishDivAtThisCandle = detectedDivergences.find(
                  div => div.type === 'bearish' && div.endIndex === idx
                );
                if (bearishDivAtThisCandle && !state.special_signal) {
                  state.special_signal = 'SELL';
                  state.exit_reason = 'DIVERGENCE';
                  state.exit_price = candle.close;
                  console.log(`⚠️ Divergence Exit at index ${idx}, price ${candle.close}`);
                  lastBuyIndex = -1; // Reset position
                  return;
                }

                // 3. EMA Cross Exit (already set by detectDivergence as 'SELL')
                if (state.special_signal === 'SELL' && !state.exit_reason) {
                  state.exit_reason = 'EMA_CROSS';
                  state.exit_price = candle.close;
                  console.log(`🔴 EMA Cross Exit at index ${idx}, price ${candle.close}`);
                  lastBuyIndex = -1; // Reset position
                  return;
                }

                // 4. Check Stop Loss
                if (candle.low <= cutloss && !state.special_signal) {
                  state.special_signal = 'SELL';
                  state.exit_reason = 'STOP_LOSS';
                  state.exit_price = cutloss;
                  console.log(`🛑 Stop Loss Exit at index ${idx}, price ${cutloss}`);
                  lastBuyIndex = -1; // Reset position
                  return;
                }
              }
            });

            console.log(`✅ Enhanced ${candleStates.length} candleStates with exit signals`);
          }

          // Store candle data for tooltips
          candleData = data.candles || [];

          // Clear previous maps
          markerDataMap.clear();
          trailingStopDataMap.clear();

          // Clear previous zone series
          clearZoneSeries();

          // Create zones by grouping consecutive Bull/Bear trend (2 colors only)
          const zones = [];
          let currentZone = null;

          (data.candles || []).forEach((c, i) => {
            // Determine Bull/Bear trend from EMA
            const isBull = c.ema_fast > c.ema_slow;
            const color = isBull ? 'green' : 'red';

            if (!currentZone || currentZone.color !== color) {
              // Start new zone
              currentZone = {
                color,
                fastData: [],
                slowData: []
              };
              zones.push(currentZone);
            }

            const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
            currentZone.fastData.push({ time: t, value: c.ema_fast });
            currentZone.slowData.push({ time: t, value: c.ema_slow });
          });

          console.log(`✅ Found ${zones.length} trend zones (Bull/Bear)`);

          // Create subtle background highlights using BaselineSeries
          // This prevents black blocks when zoomed
          zones.forEach(zone => {
            const isBull = zone.color === 'green';

            // Use BaselineSeries with very low opacity for subtle background
            const baseline = tvChart.addBaselineSeries({
              baseValue: { type: 'price', price: 0 },  // Fill from bottom of chart
              topLineColor: 'transparent',
              topFillColor1: isBull ? 'rgba(34, 197, 94, 0.08)' : 'rgba(239, 68, 68, 0.08)',
              topFillColor2: isBull ? 'rgba(34, 197, 94, 0.02)' : 'rgba(239, 68, 68, 0.02)',
              bottomLineColor: 'transparent',
              bottomFillColor1: 'transparent',
              bottomFillColor2: 'transparent',
              lineVisible: false,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
            });

            // Use the higher EMA line as the "top" for baseline
            const topData = isBull ? zone.fastData : zone.slowData;
            const baselineFormattedData = topData.map(d => ({
              time: d.time,
              value: d.value,
            }));

            baseline.setData(baselineFormattedData);
            zoneSeries.push(baseline);
          });

          console.log(`✅ Created ${zones.length} Bull/Bear zone highlights`);

          // Add buy/sell markers based on signal mode
          const signalMode = signalModeSelect.value;
          const markers = [];

          if (signalMode === 'simple') {
            // Simple Mode: 3-Timeframe Validation (1W → 1D → 1H)
            // Logic is FIXED - always uses 1W → 1D → 1H
            // Signals are shown at same TIME on whichever TF chart is displayed

            console.log(`📊 Processing 1D candles for signal detection...`);
            console.log(`📦 Available data: 1W=${data1w.candles?.length || 0}, 1D=${data1d.candles?.length || 0}, 1H=${data1h.candles?.length || 0}`);

            // Get the time range of 1H data
            const oldestH1Time = data1h.candles && data1h.candles.length > 0 ? data1h.candles[0].open_time : 0;
            const newestH1Time = data1h.candles && data1h.candles.length > 0 ? data1h.candles[data1h.candles.length - 1].open_time : 0;
            console.log(`⏰ 1H data range: ${new Date(oldestH1Time).toISOString()} to ${new Date(newestH1Time).toISOString()}`);

            // Only process 1D candles within reasonable range of 1H data (with buffer for looking ahead)
            const bufferDays = 5 * 24 * 60 * 60 * 1000; // 5 days buffer
            const minValidTime = oldestH1Time - bufferDays;
            console.log(`🔎 Will process 1D candles from ${new Date(minValidTime).toISOString()} onwards`);

            // Step 1: Find all valid signals using dual-path logic
            // Path A: Historical signals (before 1H data range) - use only 1D pattern, show normal colors
            // Path B: Current signals (within 1H data range) - use full Auto 3-TF validation, show GOLD colors
            (data1d.candles || []).forEach((c1d, idx1d) => {
              if (idx1d < 2) return;

              const zone_i2 = data1d.candles[idx1d - 2].action_zone;
              const zone_i1 = data1d.candles[idx1d - 1].action_zone;
              const isVShape = c1d.is_v_shape === true;
              const isBull = c1d.ema_fast > c1d.ema_slow;

              // Determine if this is historical (before 1H data range) or current (within 1H data range)
              const isHistorical = c1d.open_time < minValidTime;

              if (isHistorical) {
                // ═══════════════════════════════════════════════════════════════════
                // PATH A: HISTORICAL SIGNALS (before 1H data range)
                // Use only 1D pattern detection, show normal green/red arrows
                // ═══════════════════════════════════════════════════════════════════

                // BUY: Check only 1D pattern (blue→green) + Bull trend + no V-shape
                if (zone_i2 === 'blue' && zone_i1 === 'green' && !isVShape && isBull) {
                  console.log(`📜 Historical BUY Pattern at ${new Date(c1d.open_time).toISOString()} (1D only)`);

                  const buyPrice = c1d.close;
                  const cutlossPrice = calc1D_Cutloss(idx1d, data1d.candles, buyPrice);
                  const targetPercent = 2.0;
                  const targetPrice = buyPrice * (1 + targetPercent / 100);
                  const risk = buyPrice - cutlossPrice;
                  const reward = targetPrice - buyPrice;
                  const riskReward = risk > 0 ? reward / risk : 0;
                  const cutlossPercent = ((cutlossPrice - buyPrice) / buyPrice) * 100;

                  // Store marker data (historical reference)
                  markerDataMap.set(c1d.open_time, {
                    type: 'BUY',
                    buyPrice,
                    targetPrice,
                    targetPercent,
                    cutlossPrice,
                    cutlossPercent,
                    risk_reward: riskReward,
                    isFakeSignal: false,
                    isHistorical: true, // Flag as historical
                    validation_1d_bull: isBull,
                    validation_1d_pattern: true, // blue→green
                  });

                  // Validate Elliott Wave pattern
                  const tempArrow = { timestamp: c1d.open_time, price: buyPrice };
                  const waveStructure = traceWaveStructureFromBuyArrow(tempArrow);
                  const hasValidWave = waveStructure !== null;

                  // Show marker: Green = valid Wave, Orange = no valid Wave
                  const t = Math.floor(c1d.open_time / 1000);
                  const arrowColor = hasValidWave ? '#22c55e' : '#fb923c'; // Green or Orange
                  markers.push({
                    time: t,
                    position: 'belowBar',
                    color: arrowColor,
                    shape: 'arrowUp',
                    text: '',
                  });

                  // Store BUY arrow for click detection
                  buyArrowMarkers.push({
                    time: t,
                    timestamp: c1d.open_time,
                    price: buyPrice,
                    cutloss: cutlossPrice,
                    hasValidWave: hasValidWave, // Store validation result
                  });
                }

                // SELL: Check only 1D pattern (orange→red)
                if (zone_i2 === 'orange' && zone_i1 === 'red') {
                  console.log(`📜 Historical SELL Pattern at ${new Date(c1d.open_time).toISOString()} (1D only)`);

                  const sellPrice = c1d.close;

                  // Store marker data (historical reference)
                  markerDataMap.set(c1d.open_time, {
                    type: 'SELL',
                    sellPrice,
                    isFakeSignal: false,
                    isHistorical: true, // Flag as historical
                    validation_1d_pattern: true, // orange→red
                  });

                  // Show marker with normal red color
                  const t = Math.floor(c1d.open_time / 1000);
                  markers.push({
                    time: t,
                    position: 'aboveBar',
                    color: '#ef4444', // Normal red
                    shape: 'arrowDown',
                    text: '',
                  });
                }

              } else {
                // ═══════════════════════════════════════════════════════════════════
                // PATH B: CURRENT SIGNALS (within 1H data range)
                // Use full Auto 3-TF validation (1W→1D→1H), show GOLD arrows
                // ═══════════════════════════════════════════════════════════════════

                // BUY: Check 1W Bull + 1D pattern + find 1H entry
                if (zone_i2 === 'blue' && zone_i1 === 'green' && !isVShape && isBull) {
                  console.log(`🔍 BUY Pattern found at 1D index ${idx1d}, time: ${new Date(c1d.open_time).toISOString()}`);

                  const v1w = validate1W_Bull(c1d.open_time, data1w.candles);
                  console.log(`   1W Bull validation:`, v1w);
                  if (!v1w.valid) return; // Skip if 1W not Bull

                  const entry1h = find1H_BuyEntry(c1d.open_time, data1h.candles);
                  console.log(`   1H Entry search:`, entry1h);

                  if (entry1h.found) {
                    console.log(`✅ VALIDATED BUY Signal (GOLD) at ${new Date(entry1h.entryTime).toISOString()}, price: ${entry1h.entryPrice}`);

                    const buyPrice = entry1h.entryPrice;
                    const cutlossPrice = calc1D_Cutloss(idx1d, data1d.candles, buyPrice);
                    const targetPercent = 2.0;
                    const targetPrice = buyPrice * (1 + targetPercent / 100);
                    const risk = buyPrice - cutlossPrice;
                    const reward = targetPrice - buyPrice;
                    const riskReward = risk > 0 ? reward / risk : 0;
                    const cutlossPercent = ((cutlossPrice - buyPrice) / buyPrice) * 100;

                    // Store marker data with full validation status
                    markerDataMap.set(entry1h.entryTime, {
                      type: 'BUY',
                      buyPrice,
                      targetPrice,
                      targetPercent,
                      cutlossPrice,
                      cutlossPercent,
                      risk_reward: riskReward,
                      isFakeSignal: false,
                      isHistorical: false, // Flag as current validated signal
                      // Validation status
                      validation_1w_bull: true,
                      validation_1d_bull: isBull,
                      validation_1d_pattern: true, // blue→green
                      validation_1h_entry: true,
                    });

                    // Validate Elliott Wave pattern
                    const tempArrow = { timestamp: entry1h.entryTime, price: buyPrice };
                    const waveStructure = traceWaveStructureFromBuyArrow(tempArrow);
                    const hasValidWave = waveStructure !== null;

                    // Show marker with GOLD color (highly recommended)
                    const t = typeof entry1h.entryTime === "number" ? Math.floor(entry1h.entryTime / 1000) : entry1h.entryTime;
                    markers.push({
                      time: t,
                      position: 'belowBar',
                      color: '#FFD700', // GOLD - highly recommended (always gold for current signals)
                      shape: 'arrowUp',
                      text: '',
                    });

                    // Store BUY arrow for click detection
                    buyArrowMarkers.push({
                      time: t,
                      timestamp: entry1h.entryTime,
                      price: buyPrice,
                      cutloss: cutlossPrice,
                      hasValidWave: hasValidWave, // Store validation result
                    });
                  }
                }

                // SELL: Check 1D pattern + find 1H exit (Long Only - this is EXIT signal)
                if (zone_i2 === 'orange' && zone_i1 === 'red') {
                  console.log(`🔍 SELL Pattern found at 1D index ${idx1d}, time: ${new Date(c1d.open_time).toISOString()}`);

                  const exit1h = find1H_SellExit(c1d.open_time, data1h.candles);
                  console.log(`   1H Exit search:`, exit1h);

                  if (exit1h.found) {
                    console.log(`✅ VALIDATED SELL Signal (GOLD) at ${new Date(exit1h.exitTime).toISOString()}, price: ${exit1h.exitPrice}`);

                    const sellPrice = exit1h.exitPrice;

                    // Store marker data with full validation status
                    markerDataMap.set(exit1h.exitTime, {
                      type: 'SELL',
                      sellPrice,
                      isFakeSignal: false,
                      isHistorical: false, // Flag as current validated signal
                      // Validation status
                      validation_1d_pattern: true, // orange→red
                      validation_1h_exit: true,
                    });

                    // Show marker with GOLD color (highly recommended)
                    const t = typeof exit1h.exitTime === "number" ? Math.floor(exit1h.exitTime / 1000) : exit1h.exitTime;
                    markers.push({
                      time: t,
                      position: 'aboveBar',
                      color: '#FFD700', // GOLD - highly recommended
                      shape: 'arrowDown',
                      text: '',
                    });
                  }
                }
              }
            });

            console.log(`📊 Signal Detection Summary: Found ${markers.length} total signals`);
            // Convert marker time (seconds) to milliseconds for markerDataMap lookup
            const buyCount = markers.filter(m => markerDataMap.get(m.time * 1000)?.type === 'BUY').length;
            const sellCount = markers.filter(m => markerDataMap.get(m.time * 1000)?.type === 'SELL').length;
            console.log(`   BUY signals: ${buyCount}, SELL signals: ${sellCount}`);
            console.log(`🎯 BUY Arrow Markers stored: ${buyArrowMarkers.length}`, buyArrowMarkers);

            // ═══════════════════════════════════════════════════════════════════
            // ADD MULTI-TYPE EXIT SIGNALS FROM CANDLESTATES (SIMPLE MODE)
            // Add markers for Trailing Stop, Divergence, EMA Cross, and Stop Loss
            // ═══════════════════════════════════════════════════════════════════
            console.log("📍 [Simple Mode] Adding multi-type exit signal markers from candleStates...");

            const exitStylesSimple = {
              'TRAILING_STOP': { color: '#10b981', text: '📈', label: 'Trailing Stop' },
              'DIVERGENCE': { color: '#f59e0b', text: '⚠️', label: 'Divergence Exit' },
              'EMA_CROSS': { color: '#ef4444', text: '🔴', label: 'EMA Cross' },
              'STOP_LOSS': { color: '#dc2626', text: '🛑', label: 'Stop Loss' },
            };

            let addedExitMarkersSimple = 0;

            if (candleStates && candleStates.length > 0) {
              candleStates.forEach((state, stateIdx) => {
                if (!state || !state.special_signal || state.special_signal !== 'SELL') return;
                if (!state.exit_reason) return;

                // Calculate actual candle index (add RSI offset = 14)
                const candleIdx = stateIdx + 14;
                if (candleIdx >= data.candles.length) return;

                const candle = data.candles[candleIdx];
                const t = typeof candle.open_time === "number" ? Math.floor(candle.open_time / 1000) : candle.open_time;

                // Check if marker already exists for this time
                const existingMarker = markers.find(m => m.time === t && m.shape === 'arrowDown');

                const exitStyle = exitStylesSimple[state.exit_reason] || exitStylesSimple['EMA_CROSS'];

                if (!existingMarker) {
                  // Add new marker
                  const marker = {
                    time: t,
                    position: 'aboveBar',
                    color: exitStyle.color,
                    shape: 'arrowDown',
                    text: exitStyle.text,
                  };

                  markers.push(marker);
                  addedExitMarkersSimple++;

                  console.log(`📍 [Simple Mode] Added ${state.exit_reason} exit marker at candleIdx=${candleIdx}, time=${t}`);
                } else {
                  // Update existing marker with exit reason styling
                  existingMarker.color = exitStyle.color;
                  existingMarker.text = exitStyle.text;
                  console.log(`📍 [Simple Mode] Updated existing marker to ${state.exit_reason} at candleIdx=${candleIdx}`);
                }

                // Update or add markerDataMap entry
                const existingData = markerDataMap.get(candle.open_time);
                if (existingData) {
                  // Merge with existing data
                  existingData.exit_reason = state.exit_reason;
                  existingData.exitStyle = exitStyle;
                  existingData.sellPrice = state.exit_price || existingData.sellPrice || candle.close;
                } else {
                  // Create new entry
                  markerDataMap.set(candle.open_time, {
                    type: 'SELL',
                    exit_reason: state.exit_reason,
                    sellPrice: state.exit_price || candle.close,
                    exitStyle: exitStyle,
                  });
                }
              });

              console.log(`✅ [Simple Mode] Added/Updated ${addedExitMarkersSimple} exit markers from candleStates`);
              console.log(`📊 Total markers after adding exit signals: ${markers.length}`);
            } else {
              console.log("⚠️ [Simple Mode] No candleStates available for multi-type exit signals");
            }

          } else {
            // Advanced Mode: 2-candle pattern + Bull trend + all 4 rules must pass
            try {
              const rulesResp = await fetch(`/rules/live/evaluate/historical?pair=${encodeURIComponent(pair)}&limit=${limit}`);
              if (rulesResp.ok) {
                const rulesData = await rulesResp.json();
                console.log("📋 Historical rule evaluation result:", rulesData);

                // Create a map of timestamp -> all_passed
                const rulesMap = new Map();
                (rulesData.historical_results || []).forEach(r => {
                  rulesMap.set(r.timestamp, r.all_passed);
                });

                (data.candles || []).forEach((c, i) => {
                  if (i < 2) return; // Need at least 2 previous candles

                  const t = typeof c.open_time === "number" ? Math.floor(c.open_time / 1000) : c.open_time;
                  const zone_i2 = data.candles[i - 2].action_zone;
                  const zone_i1 = data.candles[i - 1].action_zone;

                  // Check Bull/Bear trend at current candle [i]
                  const emaFast = c.ema_fast;
                  const emaSlow = c.ema_slow;
                  const isBull = emaFast > emaSlow;

                  // Check if rules passed at this candle
                  const rulesPassed = rulesMap.get(c.open_time) || false;

                  // BUY signal: [i-2] blue + [i-1] green + Bull trend + all 4 rules passed
                  if (zone_i2 === 'blue' && zone_i1 === 'green' && isBull && rulesPassed) {
                    // Validate with HTF
                    const htfValidation = validateHTF(c.open_time, 'BUY', htfData.candles);
                    const isFakeSignal = !htfValidation.valid;

                    // Calculate buy price
                    const buyPrice = c.close;

                    // Calculate cutloss: Find consecutive red candles closest to entry point (look back 30 candles)
                    const cutlossWindow = 30;
                    let cutlossPrice = buyPrice * 0.95; // Default fallback (5% below entry)

                    // Find the most recent consecutive red zone candles
                    let redCandles = [];
                    for (let j = i - 1; j >= Math.max(0, i - cutlossWindow); j--) {
                      const zone = data.candles[j].action_zone;
                      if (zone === 'red') {
                        redCandles.push(data.candles[j].close); // Use close price, not low
                      } else if (redCandles.length > 0) {
                        // Found non-red after finding reds, stop here
                        break;
                      }
                    }

                    if (redCandles.length > 0) {
                      cutlossPrice = Math.min(...redCandles);
                    } else {
                      // Fallback: use min close of last 2 candles
                      cutlossPrice = Math.min(data.candles[i - 2].close, data.candles[i - 1].close);
                    }

                    // Calculate Take Profit target (2% profit)
                    const targetPercent = 2.0;
                    const targetPrice = buyPrice * (1 + targetPercent / 100);

                    // Calculate Risk:Reward
                    const risk = buyPrice - cutlossPrice;
                    const reward = targetPrice - buyPrice;
                    const riskReward = risk > 0 ? reward / risk : 0;

                    const cutlossPercent = ((cutlossPrice - buyPrice) / buyPrice) * 100;

                    // Store marker data for tooltip
                    markerDataMap.set(c.open_time, {
                      type: 'BUY',
                      buyPrice,
                      targetPrice,
                      targetPercent,
                      cutlossPrice,
                      cutlossPercent,
                      risk_reward: riskReward,
                      advanced: true, // Mark as advanced mode signal
                      isFakeSignal,
                      htfReason: htfValidation.reason,
                    });

                    // Choose marker appearance based on HTF validation
                    if (isFakeSignal) {
                      // Fake signal: Amber marker with warning
                      markers.push({
                        time: t,
                        position: 'belowBar',
                        color: '#f59e0b',
                        shape: 'arrowUp',
                        text: '⚠',
                      });
                    } else {
                      // Valid signal: Green marker with checkmark
                      markers.push({
                        time: t,
                        position: 'belowBar',
                        color: '#22c55e',
                        shape: 'arrowUp',
                        text: '✓', // Checkmark for advanced mode
                      });

                      // Store BUY arrow for click detection
                      buyArrowMarkers.push({
                        time: t,
                        timestamp: c.open_time,
                        price: buyPrice,
                        cutloss: cutlossPrice,
                      });
                    }
                  }

                  // SELL signal: [i-2] orange + [i-1] red
                  if (zone_i2 === 'orange' && zone_i1 === 'red') {
                    // Validate with HTF
                    const htfValidation = validateHTF(c.open_time, 'SELL', htfData.candles);
                    let isFakeSignal = !htfValidation.valid;

                    // ถ้าเป็นสัญญาณ 1D ให้หา confirmation บน 1H
                    let refineResult = { confirmed: true, entryPrice: c.close };
                    if (interval === '1d') {
                      refineResult = refineSellOn1h(c.open_time, (refineSellData.candles || []));
                      isFakeSignal = !refineResult.confirmed;
                    }

                    // Calculate sell price (entry for short position)
                    const sellPrice = refineResult.entryPrice || c.close;

                    // Calculate stop loss: Find consecutive green candles closest to entry point (look back 30 candles)
                    const stoplossWindow = 30;
                    let stoplossPrice = sellPrice * 1.05; // Default fallback (5% above entry)

                    // Find the most recent consecutive green zone candles
                    let greenCandles = [];
                    for (let j = i - 1; j >= Math.max(0, i - stoplossWindow); j--) {
                      const zone = data.candles[j].action_zone;
                      if (zone === 'green') {
                        greenCandles.push(data.candles[j].close); // Use close price
                      } else if (greenCandles.length > 0) {
                        // Found non-green after finding greens, stop here
                        break;
                      }
                    }

                    if (greenCandles.length > 0) {
                      stoplossPrice = Math.max(...greenCandles);
                    } else {
                      // Fallback: use max close of last 2 candles
                      stoplossPrice = Math.max(data.candles[i - 2].close, data.candles[i - 1].close);
                    }

                    // Calculate Take Profit target (2% profit on short)
                    const targetPercent = 2.0;
                    const targetPrice = sellPrice * (1 - targetPercent / 100);

                    // Calculate Risk:Reward
                    const risk = stoplossPrice - sellPrice;
                    const reward = sellPrice - targetPrice;
                    const riskReward = risk > 0 ? reward / risk : 0;

                    const stoplossPercent = ((stoplossPrice - sellPrice) / sellPrice) * 100;

                    // Store marker data for tooltip
                    markerDataMap.set(c.open_time, {
                      type: 'SELL',
                      sellPrice,
                      targetPrice,
                      targetPercent,
                      stoplossPrice,
                      stoplossPercent,
                      risk_reward: riskReward,
                      advanced: true,
                      isFakeSignal,
                      htfReason: htfValidation.reason,
                      exit_reason: 'EMA_CROSS', // Default to EMA Cross for orange→red pattern
                    });

                    // Choose marker appearance based on HTF validation
                    if (isFakeSignal) {
                      // Fake signal: Amber marker with warning
                      markers.push({
                        time: t,
                        position: 'aboveBar',
                        color: '#f59e0b',
                        shape: 'arrowDown',
                        text: '⚠',
                      });
                    } else {
                      // Valid signal: Red marker (EMA Cross)
                      markers.push({
                        time: t,
                        position: 'aboveBar',
                        color: '#ef4444',
                        shape: 'arrowDown',
                        text: '🔴', // EMA Cross icon
                      });
                    }
                  }
                });

                // ═══════════════════════════════════════════════════════════════════
                // ADD ADDITIONAL EXIT SIGNALS FROM CANDLESTATES
                // Add markers for Trailing Stop, Divergence, and Stop Loss exits
                // that weren't captured by the orange→red pattern above
                // ═══════════════════════════════════════════════════════════════════
                console.log("📍 Adding multi-type exit signal markers from candleStates...");

                const exitStyles = {
                  'TRAILING_STOP': { color: '#10b981', text: '📈', label: 'Trailing Stop' },
                  'DIVERGENCE': { color: '#f59e0b', text: '⚠️', label: 'Divergence Exit' },
                  'EMA_CROSS': { color: '#ef4444', text: '🔴', label: 'EMA Cross' },
                  'STOP_LOSS': { color: '#dc2626', text: '🛑', label: 'Stop Loss' },
                };

                let addedExitMarkers = 0;

                if (candleStates && candleStates.length > 0) {
                  candleStates.forEach((state, stateIdx) => {
                    if (!state || !state.special_signal || state.special_signal !== 'SELL') return;
                    if (!state.exit_reason) return;

                    // Calculate actual candle index (add RSI offset = 14)
                    const candleIdx = stateIdx + 14;
                    if (candleIdx >= candlesForRSI.length) return;

                    const candle = candlesForRSI[candleIdx];
                    const t = typeof candle.open_time === "number" ? Math.floor(candle.open_time / 1000) : candle.open_time;

                    // Check if marker already exists for this time
                    const existingMarker = markers.find(m => m.time === t && m.shape === 'arrowDown');

                    // Skip EMA_CROSS if already added by orange→red pattern detection
                    if (state.exit_reason === 'EMA_CROSS' && existingMarker) {
                      return; // Already added by pattern detection above
                    }

                    const exitStyle = exitStyles[state.exit_reason] || exitStyles['EMA_CROSS'];

                    if (!existingMarker) {
                      // Add new marker
                      const marker = {
                        time: t,
                        position: 'aboveBar',
                        color: exitStyle.color,
                        shape: 'arrowDown',
                        text: exitStyle.text,
                      };

                      markers.push(marker);
                      addedExitMarkers++;

                      console.log(`📍 Added ${state.exit_reason} exit marker at candleIdx=${candleIdx}, time=${t}`);
                    }

                    // Update or add markerDataMap entry
                    const existingData = markerDataMap.get(candle.open_time);
                    if (existingData) {
                      // Merge with existing data (from orange→red pattern)
                      existingData.exit_reason = state.exit_reason;
                      existingData.exitStyle = exitStyle;
                      existingData.sellPrice = state.exit_price || existingData.sellPrice || candle.close;
                    } else {
                      // Create new entry
                      markerDataMap.set(candle.open_time, {
                        type: 'SELL',
                        exit_reason: state.exit_reason,
                        sellPrice: state.exit_price || candle.close,
                        exitStyle: exitStyle,
                        advanced: true,
                      });
                    }
                  });

                  console.log(`✅ Added ${addedExitMarkers} additional exit markers from candleStates`);
                } else {
                  console.log("⚠️ No candleStates available for multi-type exit signals");
                }

              } else {
                console.warn("⚠️ Could not fetch historical rule evaluation, falling back to simple mode");
                // Fallback to simple mode
                signalModeSelect.value = 'simple';
                return loadCandles(pair);
              }
            } catch (err) {
              console.error("❌ Error fetching historical rules:", err);
              // Fallback to simple mode
              signalModeSelect.value = 'simple';
              return loadCandles(pair);
            }
          }


          // Draw Fibonacci wave objects FIRST to populate window.waveMarkers
          console.log("🌊 About to draw Fibonacci wave objects...");
          await drawFibonacciLevels(pair, displayTF);
          console.log("🌊 Finished drawing Fibonacci wave objects");

          // Merge buy/sell markers with wave markers
          const allMarkers = [...markers];
          if (window.waveMarkers && window.waveMarkers.length > 0) {
            allMarkers.push(...window.waveMarkers);
            console.log(`📍 Merging ${markers.length} buy/sell markers + ${window.waveMarkers.length} wave markers`);
          }

          candleSeries.setMarkers(allMarkers);
          console.log("📍 Added", allMarkers.length, "total markers");

          tvChart.timeScale().fitContent();
          console.log("✅ Chart loaded successfully with", candles.length, "candles");
          console.log("🔵 ========== loadCandles() FINISHED ==========");
        } catch (err) {
          console.error("💥 Error loading candles:", err);
          alert("เกิดข้อผิดพลาดในการโหลดกราฟ: " + err.message);
        }
      }

      pairSelect.addEventListener("change", (e) => {
        loadCandles(e.target.value);
      });

      timeframeSelect.addEventListener("change", (e) => {
        console.log("🔄 Timeframe changed to:", e.target.value);
        loadCandles(pairSelect.value);
      });

      signalModeSelect.addEventListener("change", (e) => {
        console.log("🔄 Signal mode changed to:", e.target.value);
        loadCandles(pairSelect.value);
      });

      loadCandles(pairSelect.value);
    </script>
    """
    return chart_html.replace("__PAIR_OPTIONS__", options)






@app.get("/reports/success", tags=["reports"])
def success_report() -> Dict:
    return build_success_dashboard(config_metrics, rule_metrics)


@app.get("/reports/orders", response_class=HTMLResponse, tags=["reports"])
def order_report_view() -> HTMLResponse:
    orders = [{"pair": "BTC/THB", "status": "closed", "pnl": 0.5}]
    inner = render_report(orders).replace("\n", "<br/>")
    return HTMLResponse(render_page(inner, title="CDC Zone Orders Report"))


@app.get("/ui/account-link", response_class=HTMLResponse, tags=["ui"])
def account_link_ui() -> HTMLResponse:
    """UI page for linking BinanceTH account keys."""
    global ENV_LOADED
    if not ENV_LOADED:
        ENV_LOADED = _load_env_file(ENV_FILE)
    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    status = {
        "has_key": bool(api_key),
        "has_secret": bool(api_secret),
        "api_key_tail": api_key[-4:] if api_key else "",
        "api_secret_tail": api_secret[-4:] if api_secret else "",
        "env_name": ENV_NAME,
        "env_file": str(ENV_FILE),
        "env_loaded": ENV_LOADED,
    }
    body_html = render_account_link(status)
    return HTMLResponse(render_page(body_html, title="ผูกบัญชี Binance"))


@app.get("/ui/config", response_class=HTMLResponse, tags=["ui"])
def config_portal() -> HTMLResponse:
    """Simple HTML UI for managing configurations."""
    from routes.config import _db

    configs = list(_db.values())
    html = render_config_portal(configs)
    return HTMLResponse(html)


@app.get("/ui/backtest", response_class=HTMLResponse, tags=["ui"])
def backtest_ui() -> HTMLResponse:
    pairs = sorted(config_store.keys())
    body_html = render_backtest_view(pairs)
    return HTMLResponse(render_page(body_html, title="CDC Zone Backtest"))


@app.get("/ui/bot", response_class=HTMLResponse, tags=["ui"])
def bot_runner_ui() -> HTMLResponse:
    pairs = sorted(config_store.keys())
    body_html = render_bot_runner(pairs)
    return HTMLResponse(render_page(body_html, title="Run Bot"))
