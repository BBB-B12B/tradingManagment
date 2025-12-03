"""Backtest endpoints for CDC trading logic."""

from __future__ import annotations

import datetime as dt
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Query
from httpx import HTTPStatusError

from clients.binance_th_client import BinanceTHClient
from libs.common.cdc_rules import evaluate_all_rules, DivergenceDetector, DivergenceType
from libs.common.cdc_rules.types import Candle, CDCColor
from libs.common.cdc_rules.pattern_classifier import classify_pattern
from routes.config import _db as config_store
from indicators.action_zone import compute_action_zone
from indicators.fibonacci import get_fibonacci_analysis, trace_wave_from_entry

router = APIRouter(prefix="/backtest", tags=["backtest"])

_market_client = BinanceTHClient()

LTF_TO_HTF = {
    "15m": "1h",
    "30m": "4h",
    "1h": "1d",
    "4h": "1d",
    "1d": "1w",
}

ENTRY_TF_MAP = {
    # Match chart simple mode (1W → 1D → 1H)
    "1d": "1h",
}

HISTORICAL_BUFFER_MS = 5 * 24 * 60 * 60 * 1000  # 5 days buffer, same as chart logic


def _ema(values: List[float], period: int) -> List[float]:
    alpha = 2 / (period + 1)
    ema_values: List[float] = []
    ema = values[0]
    ema_values.append(ema)
    for price in values[1:]:
        ema = alpha * price + (1 - alpha) * ema
        ema_values.append(ema)
    return ema_values


def _macd_histogram(closes: List[float]) -> List[float]:
    """Calculate MACD histogram for close prices."""
    if len(closes) < 2:
        return [0.0 for _ in closes]
    ema_fast = _ema(closes, 12)
    ema_slow = _ema(closes, 26)
    macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, 9)
    return [macd - signal for macd, signal in zip(macd_line, signal_line)]


def _compute_rsi(closes: List[float], period: int = 14) -> List[Optional[float]]:
    """RSI calculation (matching chart logic)."""
    if len(closes) < period + 1:
        return [None for _ in closes]

    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def rsi_val(g: float, l: float) -> float:
        if l == 0:
            return 100.0
        rs = g / l
        return 100 - (100 / (1 + rs))

    rsi: List[Optional[float]] = [None] * period
    rsi.append(rsi_val(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi.append(rsi_val(avg_gain, avg_loss))

    return rsi


def _detect_strong_signals(decorated_rows: List[dict], rsi_values: List[Optional[float]]) -> List[dict]:
    """
    Detect Strong_Buy / Strong_Sell using unified divergence detection.

    Uses the same logic as app.py JavaScript implementation:
    - Zone 1: RSI < 30 or > 70
    - Zone 2: RSI <= 35 or >= 65
    - Minimum distance: 10 candles
    - Dynamic Zone 1 updates
    - Reversal confirmation (Blue zone + RSI > 40 for BUY, Orange zone + RSI < 60 for SELL)
    """
    states: List[dict] = []

    # Prepare data for divergence detector
    rsi_clean = [r if r is not None else 50.0 for r in rsi_values]
    lows = [row.get("low", row.get("close", 0.0)) for row in decorated_rows]
    highs = [row.get("high", row.get("close", 0.0)) for row in decorated_rows]
    trends = [row.get("ema_fast", 0.0) > row.get("ema_slow", 0.0) for row in decorated_rows]

    # Detect all divergences
    detector = DivergenceDetector()
    divergences = detector.detect(rsi_clean, lows, highs, trends)

    # Create divergence lookup by end index
    div_by_end_idx = {}
    for div in divergences:
        div_by_end_idx[div.end_index] = div

    # Track active signals
    bullish_active = False
    bullish_div_idx: Optional[int] = None
    bearish_active = False
    bearish_div_idx: Optional[int] = None

    for i, row in enumerate(decorated_rows):
        rsi = rsi_values[i] if i < len(rsi_values) else None
        state = {
            "index": i,
            "time": row.get("timestamp"),
            "strong_buy": "none-Active",
            "strong_sell": "none-Active",
            "special_signal": None,
            "cutloss": None,
        }

        if rsi is None:
            states.append(state)
            continue

        zone = row.get("action_zone")

        # Check if new divergence detected at this candle
        if i in div_by_end_idx:
            div = div_by_end_idx[i]
            if div.type == DivergenceType.BULLISH:
                bullish_active = True
                bullish_div_idx = i
            elif div.type == DivergenceType.BEARISH:
                bearish_active = True
                bearish_div_idx = i

        # Bullish divergence: Wait for reversal confirmation
        if bullish_active:
            state["strong_buy"] = "Active"

            # Reversal confirmation: Blue zone + RSI > 40
            if zone == "blue" and rsi > 40:
                # Calculate cutloss using swing low
                cutloss = row.get("low", row["close"])
                lookback = 30
                for j in range(i - 1, max(-1, i - lookback), -1):
                    if j < 0 or j >= len(decorated_rows):
                        continue
                    low_j = decorated_rows[j].get("low", decorated_rows[j]["close"])
                    if low_j < cutloss:
                        cutloss = low_j

                # Add safety buffer
                cutloss = cutloss * 0.98

                # Check for red zone (more conservative)
                reds: List[float] = []
                for j in range(i - 1, max(-1, i - lookback), -1):
                    if j < 0 or j >= len(decorated_rows):
                        continue
                    if decorated_rows[j].get("action_zone") == "red":
                        reds.append(decorated_rows[j].get("low", decorated_rows[j]["close"]))
                    elif reds:
                        break
                if reds:
                    red_low = min(reds) * 0.98
                    cutloss = min(cutloss, red_low)

                state["special_signal"] = "BUY"
                state["cutloss"] = cutloss
                state["strong_buy"] = "none-Active"
                bullish_active = False
                bullish_div_idx = None

            # Cancel if RSI drops below 30 again (failed reversal)
            elif rsi < 30:
                bullish_active = False
                bullish_div_idx = None

        # Bearish divergence: Wait for reversal confirmation
        if bearish_active:
            state["strong_sell"] = "Active"

            # Reversal confirmation: Orange zone + RSI < 60
            if zone == "orange" and rsi < 60:
                state["special_signal"] = "SELL"
                state["strong_sell"] = "none-Active"
                bearish_active = False
                bearish_div_idx = None

            # Cancel if RSI rises above 70 again (failed reversal)
            elif rsi > 70:
                bearish_active = False
                bearish_div_idx = None

        states.append(state)

    return states



def _decorate_candles(raw_rows: List[dict]) -> tuple[List[Candle], List[dict]]:
    """Convert raw Binance rows to Candle objects plus indicator-rich rows."""
    closes = [row["close"] for row in raw_rows]
    zones = compute_action_zone(closes)

    candles: List[Candle] = []
    decorated_rows: List[dict] = []
    for row, zone in zip(raw_rows, zones):
        ts = dt.datetime.utcfromtimestamp(row["open_time"] / 1000)
        color = CDCColor.GREEN if zone["cdc_color"] == "green" else CDCColor.RED if zone["cdc_color"] == "red" else None
        candles.append(
            Candle(
                timestamp=ts,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                cdc_color=color or CDCColor.NONE,
            )
        )
        decorated_rows.append(
            {
                **row,
                "timestamp": ts,
                "ema_fast": zone["ema_fast"],
                "ema_slow": zone["ema_slow"],
                "action_zone": zone["zone"],
                "cdc_color": zone["cdc_color"],
            }
        )

    _annotate_patterns(decorated_rows, candles)
    return candles, decorated_rows


def _annotate_patterns(decorated_rows: List[dict], candles: List[Candle], window: int = 30) -> None:
    """Add W/V pattern metadata to decorated rows (same as chart tooltips)."""
    for idx, row in enumerate(decorated_rows):
        if idx < window:
            row["pattern"] = "NONE"
            row["is_v_shape"] = False
            continue

        pattern_result = classify_pattern(candles[: idx + 1], window)
        pattern_type = None
        if pattern_result.metadata and "pattern_type" in pattern_result.metadata:
            pattern_type = pattern_result.metadata["pattern_type"]

        row["pattern"] = pattern_type or "NONE"
        row["is_v_shape"] = pattern_type == "V_SHAPE"


def _align_htf_candle_index(htf_candles: List[Candle], ltf_ts: dt.datetime, current_idx: int) -> int:
    """
    Move the HTF pointer forward while the next HTF candle is not ahead of the current LTF time.
    Keeps stateful index to avoid repeated scans.
    """
    while (
        current_idx + 1 < len(htf_candles)
        and htf_candles[current_idx + 1].timestamp <= ltf_ts
    ):
        current_idx += 1
    return current_idx


def _is_bullish(row: dict) -> bool:
    return row["ema_fast"] > row["ema_slow"]


def _find_candle_at_or_before(candles: List[dict], ts_ms: int) -> Optional[dict]:
    for candle in reversed(candles):
        if candle["open_time"] <= ts_ms:
            return candle
    return None


def _find_buy_entry_on_lower_tf(start_ts_ms: int, lower_tf_candles: List[dict]) -> Optional[dict]:
    """Replicates chart Simple mode: blue→green + bull + not V-shape on lower TF."""
    for i in range(2, len(lower_tf_candles)):
        candle = lower_tf_candles[i]
        if candle["open_time"] < start_ts_ms:
            continue

        zone_i2 = lower_tf_candles[i - 2]["action_zone"]
        zone_i1 = lower_tf_candles[i - 1]["action_zone"]
        if zone_i2 == "blue" and zone_i1 == "green" and _is_bullish(candle) and not candle.get("is_v_shape", False):
            return candle
    return None


def _find_sell_exit_on_lower_tf(start_ts_ms: int, lower_tf_candles: List[dict]) -> Optional[dict]:
    """Replicates chart Simple mode exit: first bearish/red candle on lower TF."""
    for candle in lower_tf_candles:
        if candle["open_time"] < start_ts_ms:
            continue

        is_bearish = candle["ema_fast"] < candle["ema_slow"] and candle["close"] < candle["ema_fast"]
        is_red = candle["action_zone"] == "red"
        if is_bearish or is_red:
            return candle
    return None


def _trace_wave_for_entry(decorated_ltf: List[Dict], entry_open_time: int) -> Optional[dict]:
    """
    Trace Elliott Wave structure from entry point using EMA crossover zones.
    This matches the frontend's traceWaveStructureFromBuyArrow() logic.
    """
    return trace_wave_from_entry(decorated_ltf, entry_open_time)


def _run_backtest(
    candles_ltf: List[Candle],
    decorated_ltf: List[dict],
    candles_htf: List[Candle],
    decorated_htf: List[dict],
    lower_tf_candles: List[dict],
    macd_hist: List[float],
    strong_states: List[dict],
    params,
    enable_w_shape_filter: bool,
    enable_leading_signal: bool,
    initial_capital: float,
    budget_pct: float,
    per_trade_cap_pct: float,
    use_trailing_stop: bool,
    wave_structures: List[dict],
) -> Dict[str, Any]:
    trades: List[dict] = []
    in_position = False
    entry_price = 0.0
    entry_time: Optional[dt.datetime] = None
    entry_rules: Optional[Dict[str, bool]] = None
    exit_reason: Optional[str] = None
    position_capital: float = 0.0
    position_cutloss: Optional[float] = None
    position_units: float = 0.0
    lower_tf_start = lower_tf_candles[0]["open_time"] if lower_tf_candles else None
    use_historical_path = lower_tf_start is None
    htf_idx = 0
    equity = 1.0

    # Track accumulated profit for compound calculation
    # Formula: invested_amount = (initial_capital × budget_pct) + accumulated_profit
    accumulated_profit: float = 0.0

    # Trailing Stop variables
    trailing_stop_price: Optional[float] = None
    trailing_stop_activated: bool = False
    trailing_stop_activation_price: Optional[float] = None
    prev_high: float = 0.0
    next_sl: Optional[float] = None  # Lagging indicator: SL to be used in NEXT candle
    entry_trend_was_bullish: Optional[bool] = None  # Track trend at entry time

    for idx, candle in enumerate(candles_ltf):
        if idx < 2:
            continue

        htf_idx = _align_htf_candle_index(candles_htf, candle.timestamp, htf_idx)
        ltf_slice = candles_ltf[: idx + 1]
        htf_slice = candles_htf[: htf_idx + 1]
        macd_slice = macd_hist[: idx + 1]

        if not htf_slice:
            continue

        ltf_row = decorated_ltf[idx]
        prev_row = decorated_ltf[idx - 1]
        prev2_row = decorated_ltf[idx - 2]
        current_zone = ltf_row["action_zone"]
        prev_zone = prev_row["action_zone"]
        prev2_zone = prev2_row["action_zone"]
        is_bull = _is_bullish(ltf_row)
        is_v_shape = ltf_row.get("is_v_shape", False)
        state = strong_states[idx] if idx < len(strong_states) else None

        rules_result = evaluate_all_rules(
            candles_ltf=ltf_slice,
            candles_htf=htf_slice,
            macd_histogram=macd_slice,
            params=params,
            enable_w_shape_filter=enable_w_shape_filter,
            enable_leading_signal=enable_leading_signal,
        )

        # Track if divergence signal was used for entry (for priority system)
        divergence_entry_taken = False

        # PRIORITY 1: Strong_Buy special signal entry (RSI divergence + blue zone)
        # This takes precedence over pattern-based entry (blue→green)
        if (
            not in_position
            and state
            and state.get("special_signal") == "BUY"
        ):
            entry_price = ltf_row["close"]
            position_cutloss = state.get("cutloss")
            if position_cutloss is None or entry_price <= position_cutloss:
                continue

            # position sizing: (initial_capital × budget_pct) + accumulated_profit
            # This compounds 100% of profit into next trade, not entire equity
            base_investment = initial_capital * budget_pct
            position_capital = base_investment + accumulated_profit
            units = position_capital / entry_price
            if position_capital <= 0 or units <= 0:
                continue

            in_position = True
            divergence_entry_taken = True  # Mark that divergence entry was used
            entry_time = candle.timestamp
            entry_rules = dict(rules_result.summary)
            position_units = units
            # For divergence entries, use actual EMA values at entry time
            entry_ema_fast = ltf_row.get("ema_fast", 0.0)
            entry_ema_slow = ltf_row.get("ema_slow", 0.0)
            entry_trend_was_bullish = entry_ema_fast > entry_ema_slow  # Save actual trend at entry
            print(f"[BACKTEST DIVERGENCE] Entry at {candle.timestamp}: EMA Fast={entry_ema_fast:.2f}, Slow={entry_ema_slow:.2f}, Trend={'BULL' if entry_trend_was_bullish else 'BEAR'}")

            # Initialize Trailing Stop (only if enabled)
            if use_trailing_stop:
                trailing_stop_price = position_cutloss
                trailing_stop_activated = False
                next_sl = position_cutloss  # Initialize next_sl for lagging indicator pattern

                # Try to find wave structure for this entry (use open_time, not index)
                entry_open_time = int(ltf_row["open_time"])
                wave = _trace_wave_for_entry(decorated_ltf, entry_open_time)
                if wave:
                    # Calculate Fibonacci 100% Extension = Swing Low 2 + (Swing High - Swing Low 1)
                    swing_low_1 = wave.get("swing_low_1", {})
                    swing_high = wave.get("swing_high", {})
                    swing_low_2 = wave.get("swing_low_2", {})

                    wave1_range = swing_high.get("price", 0) - swing_low_1.get("price", 0)
                    projection_base = swing_low_2.get("price", 0)
                    trailing_stop_activation_price = projection_base + wave1_range  # 100% Extension

                    print(f"[BACKTEST] Entry at {candle.timestamp}: Price={entry_price:.2f}, InitialSL={position_cutloss:.2f}, Activation={trailing_stop_activation_price:.2f} (Fib 100% Extension)")
                else:
                    # Fallback: Use 7.5% profit as activation
                    trailing_stop_activation_price = entry_price * 1.075
                    print(f"[BACKTEST] Entry at {candle.timestamp}: Price={entry_price:.2f}, InitialSL={position_cutloss:.2f}, Activation={trailing_stop_activation_price:.2f} (7.5% fallback - no wave)")

                prev_high = (candle.open + candle.close) / 2  # Initialize with average price
            continue

        # Historical path mirrors chart fallback when lower-TF data is missing
        historical_signal = (
            use_historical_path
            or (
                lower_tf_start is not None
                and ltf_row["open_time"] < lower_tf_start - HISTORICAL_BUFFER_MS
            )
        )

        def _calc_cutloss(idx_ltf: int) -> float:
            """ตาม logic ในกราฟ: หาจุดต่ำสุดจาก red ย้อนหลังแบบติดกัน (ดู 30 แท่ง), fallback min close 2 แท่งก่อนหน้า"""
            lookback = 30
            cutloss_price = ltf_row["close"] * 0.95

            reds: List[float] = []
            for j in range(idx_ltf - 1, max(-1, idx_ltf - lookback) , -1):
                zone = decorated_ltf[j]["action_zone"]
                if zone == "red":
                    reds.append(decorated_ltf[j]["close"])
                elif reds:
                    break

            if reds:
                cutloss_price = min(reds)
            elif idx_ltf >= 2:
                cutloss_price = min(decorated_ltf[idx_ltf - 2]["close"], decorated_ltf[idx_ltf - 1]["close"])
            return cutloss_price

        # Entry check: blue → green + bull + not V-shape
        # PRIORITY 2: Only enter via pattern if no divergence signal exists
        if (
            not in_position
            and not divergence_entry_taken  # Skip if divergence entry already taken
            and prev2_zone == "blue"
            and prev_zone == "green"
            and is_bull
            and not is_v_shape
        ):
            if historical_signal:
                entry_price = ltf_row["close"]
                position_cutloss = _calc_cutloss(idx)
                if entry_price <= position_cutloss:
                    continue

                # position sizing: (initial_capital × budget_pct) + accumulated_profit
                base_investment = initial_capital * budget_pct
                position_capital = base_investment + accumulated_profit
                units = position_capital / entry_price
                if position_capital <= 0 or units <= 0:
                    continue

                in_position = True
                entry_time = candle.timestamp
                entry_rules = dict(rules_result.summary)
                position_units = units
                entry_trend_was_bullish = is_bull  # Save trend at entry

                # Initialize Trailing Stop (only if enabled)
                if use_trailing_stop:
                    trailing_stop_price = position_cutloss
                    trailing_stop_activated = False
                    next_sl = position_cutloss  # Initialize next_sl for lagging indicator pattern

                    # Trace wave structure from this entry point
                    entry_open_time_ms = int(ltf_row["open_time"])
                    wave = _trace_wave_for_entry(decorated_ltf, entry_open_time_ms)
                    if wave:
                        # Calculate Fibonacci 100% Extension = Swing Low 2 + (Swing High - Swing Low 1)
                        swing_low_1 = wave.get("swing_low_1", {})
                        swing_high = wave.get("swing_high", {})
                        swing_low_2 = wave.get("swing_low_2", {})

                        wave1_range = swing_high.get("price", 0) - swing_low_1.get("price", 0)
                        projection_base = swing_low_2.get("price", 0)
                        trailing_stop_activation_price = projection_base + wave1_range  # 100% Extension

                        print(f"[BACKTEST PATH2] Entry at {candle.timestamp}: Price={entry_price:.2f}, InitialSL={position_cutloss:.2f}, Activation={trailing_stop_activation_price:.2f} (Fib 100% Extension from traced wave)")
                    else:
                        # Fallback: Use 7.5% profit as activation
                        trailing_stop_activation_price = entry_price * 1.075
                        print(f"[BACKTEST PATH2] Entry at {candle.timestamp}: Price={entry_price:.2f}, InitialSL={position_cutloss:.2f}, Activation={trailing_stop_activation_price:.2f} (7.5% fallback - no wave)")

                    prev_high = (candle.open + candle.close) / 2  # Initialize with average price
                continue

            htf_row = _find_candle_at_or_before(decorated_htf, int(ltf_row["open_time"]))
            if not htf_row or not _is_bullish(htf_row):
                continue

            entry_candle = _find_buy_entry_on_lower_tf(int(ltf_row["open_time"]), lower_tf_candles)
            if entry_candle:
                entry_price = entry_candle["close"]
                entry_time = dt.datetime.utcfromtimestamp(entry_candle["open_time"] / 1000)
                entry_rules = dict(rules_result.summary)
                position_cutloss = _calc_cutloss(idx)
                if entry_price <= position_cutloss:
                    continue

                # position sizing: (initial_capital × budget_pct) + accumulated_profit
                base_investment = initial_capital * budget_pct
                position_capital = base_investment + accumulated_profit
                units = position_capital / entry_price
                if position_capital <= 0 or units <= 0:
                    continue

                in_position = True
                position_units = units
                entry_trend_was_bullish = is_bull  # Save trend at entry

                # Initialize Trailing Stop
                trailing_stop_price = position_cutloss
                trailing_stop_activated = False
                next_sl = position_cutloss  # Initialize next_sl for lagging indicator pattern

                # Trace wave structure from this entry point
                entry_open_time_ms = int(ltf_row["open_time"])
                wave = _trace_wave_for_entry(decorated_ltf, entry_open_time_ms)
                if wave:
                    # Calculate Fibonacci 100% Extension = Swing Low 2 + (Swing High - Swing Low 1)
                    swing_low_1 = wave.get("swing_low_1", {})
                    swing_high = wave.get("swing_high", {})
                    swing_low_2 = wave.get("swing_low_2", {})

                    wave1_range = swing_high.get("price", 0) - swing_low_1.get("price", 0)
                    projection_base = swing_low_2.get("price", 0)
                    trailing_stop_activation_price = projection_base + wave1_range  # 100% Extension

                    print(f"[BACKTEST PATH2-HIST] Entry at {candle.timestamp}: Price={entry_price:.2f}, InitialSL={position_cutloss:.2f}, Activation={trailing_stop_activation_price:.2f} (Fib 100% Extension from traced wave)")
                else:
                    # Fallback: Use 7.5% profit as activation
                    trailing_stop_activation_price = entry_price * 1.075
                    print(f"[BACKTEST PATH2-HIST] Entry at {candle.timestamp}: Price={entry_price:.2f}, InitialSL={position_cutloss:.2f}, Activation={trailing_stop_activation_price:.2f} (7.5% fallback - no wave)")

                prev_high = (candle.open + candle.close) / 2  # Initialize with average price

        # Update Trailing Stop while in position (only if enabled)
        if in_position and use_trailing_stop and trailing_stop_price is not None:
            current_avg = (candle.open + candle.close) / 2  # Average price (matching app.js)
            current_low = candle.low

            # Check if trend CHANGED from entry (EMA crossover)
            # This MUST be checked BEFORE activation and BEFORE stop update
            # Only exit if trend actually reversed from what it was at entry
            ema_fast = ltf_row.get("ema_fast", 0.0)
            ema_slow = ltf_row.get("ema_slow", 0.0)
            is_bullish = ema_fast > ema_slow

            # Exit only if trend changed from entry trend
            # If entered during Bear, wait for Bull then back to Bear
            # If entered during Bull, exit when it becomes Bear
            trend_reversed = False
            if entry_trend_was_bullish and not is_bullish:
                # Entered in Bull, now Bear → Exit
                trend_reversed = True
            elif not entry_trend_was_bullish and is_bullish:
                # Entered in Bear, now Bull → Update entry trend, don't exit yet
                entry_trend_was_bullish = True

            if trend_reversed:
                # Bullish trend ended, exit immediately
                exit_price = ltf_row["close"]
                exit_time = candle.timestamp
                exit_reason = "EMA_CROSSOVER_BEARISH"
                print(f"[BACKTEST] Bullish trend ENDED at {candle.timestamp}: EMA crossover to Bearish (Fast={ema_fast:.2f} < Slow={ema_slow:.2f}), Exit at Close={exit_price:.2f}")

                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                pnl_amount = position_capital * (pnl_pct / 100)
                duration_days = (exit_time - entry_time).total_seconds() / 86400 if entry_time else 0.0
                equity_value = equity * initial_capital + pnl_amount
                equity = equity_value / initial_capital

                # Update accumulated profit for compounding
                accumulated_profit += pnl_amount

                trades.append(
                    {
                        "entry_time": entry_time.isoformat() if entry_time else "",
                        "entry_price": round(entry_price, 4),
                        "exit_time": exit_time.isoformat(),
                        "exit_price": round(exit_price, 4),
                        "pnl_pct": round(pnl_pct, 3),
                        "invested_amount": round(position_capital, 2),
                        "position_units": round(position_units, 6),
                        "pnl_amount": round(pnl_amount, 2),
                        "cutloss_price": round(position_cutloss, 4) if position_cutloss is not None else None,
                        "duration_days": round(duration_days, 2),
                        "ltf_color_at_entry": ltf_slice[-1].cdc_color.value if ltf_slice else "unknown",
                        "ltf_color_at_exit": ltf_row.get("cdc_color", "none"),
                        "rules": entry_rules or {},
                        "exit_reason": exit_reason,
                    }
                )

                in_position = False
                entry_price = 0.0
                entry_time = None
                entry_rules = None
                exit_reason = None
                position_capital = 0.0
                position_cutloss = None
                position_units = 0.0
                trailing_stop_price = None
                trailing_stop_activated = False
                trailing_stop_activation_price = None
                prev_high = 0.0
                next_sl = None  # Reset lagging indicator
                entry_trend_was_bullish = None  # Reset entry trend
                continue

            # IMPORTANT: Check exit FIRST (before updating stop) to use PREVIOUS candle's SL
            # This matches app.js logic: currentSL = nextSL (from previous candle)
            # Use next_sl from previous iteration, not trailing_stop_price which may have just been updated
            current_sl = next_sl if next_sl is not None else trailing_stop_price
            if trailing_stop_activated and current_low <= current_sl:
                exit_price = current_sl  # Exit at the SL from PREVIOUS candle
                exit_time = candle.timestamp
                exit_reason = "TRAILING_STOP"
                print(f"[BACKTEST] Trailing Stop HIT at {candle.timestamp}: Low={current_low:.2f} <= Stop={current_sl:.2f}")

                pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                pnl_amount = position_capital * (pnl_pct / 100)
                duration_days = (exit_time - entry_time).total_seconds() / 86400 if entry_time else 0.0
                equity_value = equity * initial_capital + pnl_amount
                equity = equity_value / initial_capital

                # Update accumulated profit for compounding
                accumulated_profit += pnl_amount

                trades.append(
                    {
                        "entry_time": entry_time.isoformat() if entry_time else "",
                        "entry_price": round(entry_price, 4),
                        "exit_time": exit_time.isoformat(),
                        "exit_price": round(exit_price, 4),
                        "pnl_pct": round(pnl_pct, 3),
                        "invested_amount": round(position_capital, 2),
                        "position_units": round(position_units, 6),
                        "pnl_amount": round(pnl_amount, 2),
                        "cutloss_price": round(position_cutloss, 4) if position_cutloss is not None else None,
                        "duration_days": round(duration_days, 2),
                        "ltf_color_at_entry": ltf_slice[-1].cdc_color.value if ltf_slice else "unknown",
                        "ltf_color_at_exit": ltf_row.get("cdc_color", "none"),
                        "rules": entry_rules or {},
                        "exit_reason": exit_reason,
                    }
                )

                in_position = False
                entry_price = 0.0
                entry_time = None
                entry_rules = None
                exit_reason = None
                position_capital = 0.0
                position_cutloss = None
                position_units = 0.0
                trailing_stop_price = None
                trailing_stop_activated = False
                trailing_stop_activation_price = None
                prev_high = 0.0
                next_sl = None  # Reset lagging indicator
                entry_trend_was_bullish = None  # Reset entry trend
                continue

            # After checking exit, NOW check activation and update SL for NEXT candle
            # Check if we should activate trailing stop (entire candle above 105% of activation)
            if not trailing_stop_activated and trailing_stop_activation_price:
                activation_threshold = trailing_stop_activation_price * 1.05  # 105%
                if current_low >= activation_threshold:
                    trailing_stop_activated = True
                    print(f"[BACKTEST] Trailing Stop ACTIVATED at {candle.timestamp}: Low={current_low:.2f} >= Threshold={activation_threshold:.2f}")

            # Update trailing stop based on current average price
            # ALWAYS calculate (like in app.js), not just when activated
            # The activation flag only controls whether we EXIT, not whether we calculate
            # Use FIXED DISTANCE (7%) from current average price (matching app.js)

            trailing_distance = 0.07  # 7% trailing distance (matching app.js)
            potential_sl = current_avg * (1 - trailing_distance)

            # Trailing Stop can only rise, never fall
            if potential_sl > next_sl:
                old_stop = next_sl
                next_sl = potential_sl  # Update next_sl to be used in NEXT candle
                trailing_stop_price = potential_sl  # Also update trailing_stop_price for backward compatibility

                # Calculate price change percentage for logging
                price_change_pct = ((current_avg - prev_high) / prev_high * 100) if prev_high > 0 else 0.0

                if trailing_stop_activated:
                    print(f"[BACKTEST] Trailing Stop updated: {old_stop:.2f} -> {potential_sl:.2f} (Avg Price: {current_avg:.2f}, {price_change_pct:+.2f}%) [will be used in NEXT candle]")
                else:
                    print(f"[BACKTEST] Trailing Stop updated (pre-activation): {old_stop:.2f} -> {potential_sl:.2f} (Avg Price: {current_avg:.2f}) [will be used in NEXT candle]")

            # Always update prev_high to track price movement (even if SL didn't move)
            prev_high = current_avg

        # Exit check: orange → red, close on lower TF (or LTF for historical)
        if (
            in_position
            and prev2_zone == "orange"
            and prev_zone == "red"
        ):
            if historical_signal or not lower_tf_candles:
                exit_price = ltf_row["close"]
                exit_time = candle.timestamp
            else:
                start_ms = max(
                    int(ltf_row["open_time"]),
                    int(entry_time.timestamp() * 1000) if entry_time else int(ltf_row["open_time"]),
                )
                exit_candle = _find_sell_exit_on_lower_tf(start_ms, lower_tf_candles)
                if not exit_candle:
                    continue
                exit_price = exit_candle["close"]
                exit_time = dt.datetime.utcfromtimestamp(exit_candle["open_time"] / 1000)

            exit_reason = "ORANGE_RED"
            # ถ้าราคาออกต่ำกว่าจุด cutloss ให้แท็กเป็น cutloss และใช้ราคาตัดขาดทุนเป็นราคาออก
            if position_cutloss is not None and exit_price <= position_cutloss:
                exit_reason = "STOP_LOSS_SUPPORT"
                exit_price = position_cutloss

            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            pnl_amount = position_capital * (pnl_pct / 100)
            duration_days = (exit_time - entry_time).total_seconds() / 86400 if entry_time else 0.0
            equity_value = equity * initial_capital + pnl_amount
            equity = equity_value / initial_capital

            # Update accumulated profit for compounding
            accumulated_profit += pnl_amount

            trades.append(
                {
                    "entry_time": entry_time.isoformat() if entry_time else "",
                    "entry_price": round(entry_price, 4),
                    "exit_time": exit_time.isoformat(),
                    "exit_price": round(exit_price, 4),
                    "pnl_pct": round(pnl_pct, 3),
                    "invested_amount": round(position_capital, 2),
                    "position_units": round(position_units, 6),
                    "pnl_amount": round(pnl_amount, 2),
                    "cutloss_price": round(position_cutloss, 4) if position_cutloss is not None else None,
                    "duration_days": round(duration_days, 2),
                    "ltf_color_at_entry": ltf_slice[-1].cdc_color.value if ltf_slice else "unknown",
                    "ltf_color_at_exit": ltf_row.get("cdc_color", "none"),
                    "rules": entry_rules or {},
                    "exit_reason": exit_reason,
                }
            )

            in_position = False
            entry_price = 0.0
            entry_time = None
            entry_rules = None
            exit_reason = None
            position_capital = 0.0
            position_cutloss = None
            position_units = 0.0
            trailing_stop_price = None
            trailing_stop_activated = False
            trailing_stop_activation_price = None
            prev_high = 0.0
            continue

        # Strong_Sell special signal exit (RSI divergence + orange zone)
        if (
            in_position
            and state
            and state.get("special_signal") == "SELL"
        ):
            exit_price = ltf_row["close"]
            exit_reason = "STRONG_SELL"
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            pnl_amount = position_capital * (pnl_pct / 100)
            duration_days = (candle.timestamp - entry_time).total_seconds() / 86400 if entry_time else 0.0
            equity_value = equity * initial_capital + pnl_amount
            equity = equity_value / initial_capital

            # Update accumulated profit for compounding
            accumulated_profit += pnl_amount

            trades.append(
                {
                    "entry_time": entry_time.isoformat() if entry_time else "",
                    "entry_price": round(entry_price, 4),
                    "exit_time": candle.timestamp.isoformat(),
                    "exit_price": round(exit_price, 4),
                    "pnl_pct": round(pnl_pct, 3),
                    "invested_amount": round(position_capital, 2),
                    "position_units": round(position_units, 6),
                    "pnl_amount": round(pnl_amount, 2),
                    "cutloss_price": round(position_cutloss, 4) if position_cutloss is not None else None,
                    "duration_days": round(duration_days, 2),
                    "ltf_color_at_entry": ltf_slice[-1].cdc_color.value if ltf_slice else "unknown",
                    "ltf_color_at_exit": ltf_row.get("cdc_color", "none"),
                    "rules": entry_rules or {},
                    "exit_reason": exit_reason,
                }
            )

            in_position = False
            entry_price = 0.0
            entry_time = None
            entry_rules = None
            exit_reason = None
            position_capital = 0.0
            position_cutloss = None
            position_units = 0.0
            trailing_stop_price = None
            trailing_stop_activated = False
            trailing_stop_activation_price = None
            prev_high = 0.0

    if in_position and entry_time is not None:
        if lower_tf_candles:
            last_exit_row = lower_tf_candles[-1]
            exit_price = last_exit_row["close"]
            exit_time = dt.datetime.utcfromtimestamp(last_exit_row["open_time"] / 1000)
        else:
            last_exit_row = decorated_ltf[-1]
            exit_price = last_exit_row["close"]
            exit_time = dt.datetime.utcfromtimestamp(last_exit_row["open_time"] / 1000)

        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        pnl_amount = position_capital * (pnl_pct / 100)
        duration_days = (exit_time - entry_time).total_seconds() / 86400 if entry_time else 0.0
        exit_reason = "END_OF_DATA"
        if position_cutloss is not None and exit_price <= position_cutloss:
            exit_reason = "STOP_LOSS_SUPPORT"
            exit_price = position_cutloss
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            pnl_amount = position_capital * (pnl_pct / 100)
            duration_days = (exit_time - entry_time).total_seconds() / 86400 if entry_time else 0.0
        equity_value = equity * initial_capital + pnl_amount
        equity = equity_value / initial_capital

        # Update accumulated profit for compounding
        accumulated_profit += pnl_amount

        trades.append(
            {
                "entry_time": entry_time.isoformat(),
                "entry_price": round(entry_price, 4),
                "exit_time": exit_time.isoformat(),
                "exit_price": round(exit_price, 4),
                "pnl_pct": round(pnl_pct, 3),
                "invested_amount": round(position_capital, 2),
                "position_units": round(position_units, 6),
                "pnl_amount": round(pnl_amount, 2),
                "cutloss_price": round(position_cutloss, 4) if position_cutloss is not None else None,
                "duration_days": round(duration_days, 2),
                "ltf_color_at_entry": decorated_ltf[-1].get("cdc_color", "none"),
                "ltf_color_at_exit": decorated_ltf[-1].get("cdc_color", "none"),
                "rules": entry_rules or {},
                "exit_reason": exit_reason,
                "open_ended": True,
            }
        )

    total_trades = len(trades)
    wins = len([t for t in trades if t["pnl_pct"] > 0])
    avg_return = sum(t["pnl_pct"] for t in trades) / total_trades if total_trades else 0.0
    final_equity_value = equity * initial_capital
    total_income = accumulated_profit  # Use accumulated_profit instead of equity-based calculation
    total_duration_days = sum(t.get("duration_days", 0) for t in trades)
    avg_duration_days = total_duration_days / total_trades if total_trades else 0.0

    # คำนวณเงินที่ใช้จริงในการซื้อขาย (Total Capital Deployed)
    total_capital_deployed = sum(t["invested_amount"] for t in trades)
    avg_capital_deployed = total_capital_deployed / total_trades if total_trades else 0.0

    # คำนวณ ROI (Return on Investment)
    # Formula: accumulated_profit / avg_capital_deployed
    # This shows true ROI based on average investment per trade
    if avg_capital_deployed > 0:
        roi_pct = (accumulated_profit / avg_capital_deployed) * 100
    else:
        roi_pct = 0.0

    # คำนวณ CAGR (กำไรเฉลี่ยต่อปีแบบทบต้น)
    # ใช้ระยะเวลารวมจาก entry แรกถึง exit สุดท้ายถ้ามีข้อมูล
    if trades:
        first_entry = trades[0]["entry_time"]
        last_exit = trades[-1]["exit_time"]
        try:
            start_dt = dt.datetime.fromisoformat(first_entry)
            end_dt = dt.datetime.fromisoformat(last_exit)
            total_days = max((end_dt - start_dt).days, 1)
        except Exception:
            total_days = max(int(total_duration_days), 1)
    else:
        total_days = 1

    years = total_days / 365.0
    if years > 0:
        cagr_pct = (equity ** (1 / years) - 1) * 100
    else:
        cagr_pct = (equity - 1) * 100

    stats = {
        "total_trades": total_trades,
        "wins": wins,
        "win_rate_pct": round((wins / total_trades) * 100, 2) if total_trades else 0.0,
        "avg_return_pct": round(avg_return, 3),
        "cumulative_return_pct": round((equity - 1) * 100, 2),
        "initial_capital": initial_capital,
        "final_equity_value": round(final_equity_value, 2),
        "total_income": round(total_income, 2),
        "avg_capital_deployed": round(avg_capital_deployed, 2),
        "total_capital_deployed": round(total_capital_deployed, 2),
        "roi_pct": round(roi_pct, 2),
        "total_duration_days": round(total_duration_days, 2),
        "avg_duration_days": round(avg_duration_days, 2),
        "cagr_pct": round(cagr_pct, 2),
    }

    return {"trades": trades, "stats": stats}


@router.get("")
async def run_backtest(
    pair: str = Query(..., description="Trading pair, e.g., BTC/USDT"),
    timeframe: Optional[str] = Query(None, description="Override lower timeframe (defaults to config timeframe)"),
    htf_timeframe: Optional[str] = Query(None, description="Override higher timeframe (defaults to mapping)"),
    limit: int = Query(240, ge=50, le=1000),
    initial_capital: float = Query(10000.0, ge=0, description="เงินต้น (หน่วยเดียวกับ quote currency)"),
    use_trailing_stop: bool = Query(True, description="Enable Trailing Stop (True) or use Strong Sell only (False)"),
) -> Dict[str, Any]:
    """
    Run a lightweight backtest using Binance candles and the CDC rule engine.
    """
    cfg = config_store.get(pair.upper())
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Config not found for pair {pair}")

    ltf_interval = timeframe or cfg.timeframe
    htf_interval = htf_timeframe or LTF_TO_HTF.get(ltf_interval, "1d")
    entry_interval = ENTRY_TF_MAP.get(ltf_interval, ltf_interval)

    try:
        ltf_rows = await _market_client.get_candles(pair=pair, interval=ltf_interval, limit=limit)
        htf_rows = await _market_client.get_candles(pair=pair, interval=htf_interval, limit=min(limit, 120))
        if entry_interval == ltf_interval:
            entry_rows = ltf_rows
        else:
            entry_rows = await _market_client.get_candles(
                pair=pair,
                interval=entry_interval,
                limit=1000,  # mirror chart fetch for 1H
            )
    except (HTTPStatusError, ValueError) as exc:
        response = getattr(exc, "response", None)
        extra = f": {response.text}" if response is not None else f": {exc}"
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch Binance data for {pair} ({ltf_interval}/{htf_interval}){extra}",
        ) from exc

    candles_ltf, decorated_ltf = _decorate_candles(ltf_rows)
    candles_htf, decorated_htf = _decorate_candles(htf_rows)
    _, decorated_entry = _decorate_candles(entry_rows)
    macd_hist = _macd_histogram([row["close"] for row in ltf_rows])
    rsi_values = _compute_rsi([row["close"] for row in ltf_rows])
    strong_states = _detect_strong_signals(decorated_ltf, rsi_values)

    # Get Elliott Wave analysis for Fibonacci activation prices
    # Need to pass decorated_ltf (with EMA data) instead of raw ltf_rows
    fib_analysis = get_fibonacci_analysis(decorated_ltf)
    wave_structures = fib_analysis.get("waves", [])
    print(f"[BACKTEST] Fibonacci analysis found {len(wave_structures)} wave structures")

    if not candles_ltf or not candles_htf:
        raise HTTPException(status_code=400, detail="Not enough candle data to run backtest")

    result = _run_backtest(
        candles_ltf=candles_ltf,
        decorated_ltf=decorated_ltf,
        candles_htf=candles_htf,
        decorated_htf=decorated_htf,
        lower_tf_candles=decorated_entry,
        macd_hist=macd_hist,
        strong_states=strong_states,
        params=cfg.rule_params,
        enable_w_shape_filter=cfg.enable_w_shape_filter,
        enable_leading_signal=cfg.enable_leading_signal,
        initial_capital=initial_capital,
        budget_pct=cfg.budget_pct,
        per_trade_cap_pct=cfg.risk.per_trade_cap_pct,
        use_trailing_stop=use_trailing_stop,
        wave_structures=wave_structures,
    )

    return {
        "pair": pair.upper(),
        "ltf_timeframe": ltf_interval,
        "htf_timeframe": htf_interval,
        "entry_timeframe": entry_interval,
        "candles_used": len(candles_ltf),
        "rule_params": cfg.rule_params.model_dump(),
        "initial_capital": initial_capital,
        **result,
    }


__all__ = ["router"]
