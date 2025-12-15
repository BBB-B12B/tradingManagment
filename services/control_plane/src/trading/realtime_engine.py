"""Real-time Trading Engine - ตรวจสอบเงื่อนไข Entry/Exit แบบ Real-time

This module implements real-time trading logic with Entry/Exit conditions:

Entry Requirements (ต้องผ่านทั้งหมด):
1. ✅ LTF: BLUE→GREEN transition (prev2=blue, prev=green)
2. ✅ LTF: Bull trend (EMA Fast > EMA Slow)
3. ✅ HTF: Bull trend (EMA Fast > EMA Slow)
4. ✅ Not V-shape pattern
5. ✅ Entry price > Cutloss price

❌ Divergence ไม่ใช้สำหรับ Entry (ใช้เฉพาะ Exit)

Exit Conditions (Priority Order):
1. EMA Crossover Bearish (Trend Reversal)
2. Trailing Stop Hit
3. CDC Pattern Orange → Red
4. RSI Divergence (STRONG_SELL) - Bearish Divergence สำหรับ Exit เท่านั้น

ใช้งาน:
    engine = RealtimeTradingEngine(pair="BTC/USDT")
    await engine.run()  # ตรวจสอบและทำ Trade ครั้งเดียว
"""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from clients.binance_th_client import BinanceTHClient
from libs.common.cdc_rules import evaluate_all_rules
from libs.common.cdc_rules.types import Candle, CDCColor
from libs.common.cdc_rules.divergence import calculate_rsi, DivergenceDetector, DivergenceType
from enum import Enum
from libs.common.exit_rules import ExitReason
from libs.common.position_state import PositionState, PositionStatus
from indicators.fibonacci import trace_wave_from_entry
from routes.config import _db as config_store
from routes.order_sync import fetch_worker_orders
from indicators.action_zone import compute_action_zone

import httpx
import os
import uuid
import ccxt


LTF_TO_HTF = {
    "15m": "1h",
    "30m": "4h",
    "1h": "1d",
    "4h": "1d",
    "1d": "1w",
}

_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
_WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")
_BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
_BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_WORKER_TOKEN}"} if _WORKER_TOKEN else {}


def _make_binance_client() -> ccxt.binance:
    """สร้าง Binance client สำหรับ Testnet"""
    if not _BINANCE_API_KEY or not _BINANCE_API_SECRET:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET in environment")

    client = ccxt.binance({
        "apiKey": _BINANCE_API_KEY,
        "secret": _BINANCE_API_SECRET,
        "options": {"defaultType": "spot"},
    })
    client.set_sandbox_mode(True)  # Use Testnet
    return client


def _ema(values: List[float], period: int) -> List[float]:
    """Calculate EMA"""
    if not values:
        return []
    alpha = 2 / (period + 1)
    ema_values: List[float] = []
    ema = values[0]
    ema_values.append(ema)
    for price in values[1:]:
        ema = alpha * price + (1 - alpha) * ema
        ema_values.append(ema)
    return ema_values


def _macd_histogram(closes: List[float]) -> List[float]:
    """Calculate MACD histogram"""
    if len(closes) < 26:
        return [0.0 for _ in closes]
    ema_fast = _ema(closes, 12)
    ema_slow = _ema(closes, 26)
    macd_line = [fast - slow for fast, slow in zip(ema_fast, ema_slow)]
    signal_line = _ema(macd_line, 9)
    return [macd - signal for macd, signal in zip(macd_line, signal_line)]


def _serialize_metadata(obj: Any) -> Any:
    """Recursively convert Enum objects to their values for JSON serialization"""
    if isinstance(obj, Enum):
        return obj.value
    elif isinstance(obj, dict):
        return {k: _serialize_metadata(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [_serialize_metadata(item) for item in obj]
    else:
        return obj


def _decorate_candles(raw_rows: List[dict]) -> List[Candle]:
    """Convert raw Binance rows to Candle objects with CDC colors"""
    closes = [row["close"] for row in raw_rows]

    # Calculate CDC Action Zone colors using EMA-based logic
    action_zones = compute_action_zone(closes, fast_period=12, slow_period=26)

    candles: List[Candle] = []
    for row, zone_data in zip(raw_rows, action_zones):
        ts = dt.datetime.utcfromtimestamp(row["open_time"] / 1000)

        # Map zone string to CDCColor enum
        zone = zone_data["zone"]
        color_map = {
            "green": CDCColor.GREEN,
            "red": CDCColor.RED,
            "blue": CDCColor.BLUE,
            "lblue": CDCColor.LBLUE,
            "orange": CDCColor.ORANGE,
            "yellow": CDCColor.YELLOW,
            "none": CDCColor.NONE,
        }
        color = color_map.get(zone, CDCColor.NONE)

        candles.append(
            Candle(
                timestamp=ts,
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                cdc_color=color,
            )
        )
    return candles


class RealtimeTradingEngine:
    """Real-time Trading Engine - ตัวจริงที่ทำงานตลอดเวลา"""

    def __init__(self, pair: str):
        self.pair = pair.upper()
        self.config = config_store.get(self.pair)
        if not self.config:
            raise ValueError(f"Config not found for pair {self.pair}")

        self.market_client = BinanceTHClient()
        self.position: Optional[PositionState] = None
        self.ltf_interval = self.config.timeframe
        self.htf_interval = LTF_TO_HTF.get(self.ltf_interval, "1d")

    async def run(self) -> Dict[str, Any]:
        """Main Loop - ตรวจสอบและทำ Trade ครั้งเดียว

        Returns:
            Dict with status, action, and details
        """
        print(f"[{dt.datetime.now()}] [{self.pair}] Checking trading signals...")

        # 1. โหลด Position State จาก Worker/D1
        await self._load_position_state()

        # 2. ดึงข้อมูล Candles และคำนวณ Indicators
        candles_ltf, candles_htf, macd_hist, ltf_rows, strong_states = await self._fetch_market_data()

        if not self.position.is_long():
            # โหมด ENTRY - ตรวจสอบเงื่อนไขเข้าซื้อ

            # ⚠️ เช็คว่ามี Pending ENTRY Order อยู่หรือไม่
            if self._has_pending_entry_order():
                result = {
                    "action": "wait",
                    "status": "pending_order_exists",
                    "reason": "มี Order ENTRY ที่ PENDING อยู่แล้ว รอให้ match ก่อน",
                }
            else:
                result = await self._check_entry(candles_ltf, candles_htf, macd_hist, ltf_rows, strong_states)
        else:
            # โหมด EXIT - ตรวจสอบเงื่อนไขออกขาย
            result = await self._check_exit(candles_ltf, candles_htf, macd_hist, ltf_rows, strong_states)

        # เพิ่ม Position info ใน result
        result["position"] = self.position.to_dict()
        return result

    async def _load_position_state(self):
        """โหลด Position State จาก D1 Worker และเช็ค Pending Orders"""
        try:
            # ดึง Orders จาก Worker API
            orders_data = await fetch_worker_orders()
            orders = orders_data.get("orders", [])

            # เก็บ orders ไว้ใช้เช็ค pending ภายหลัง
            self.all_orders = orders

            # ดึง Position State จาก D1
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{_WORKER_URL}/positions/{self.pair}",
                    headers=_auth_headers(),
                    timeout=10.0
                )
                resp.raise_for_status()
                position_data = resp.json().get("position", {})

            # คำนวณ Position จาก Orders (FIFO) เพื่อหา qty และ avg_cost
            position_info = self._compute_open_position(orders)

            # Dust threshold - ถือว่า qty < 0.000001 เป็น 0
            MIN_POSITION_QTY = 0.000001

            if position_info["qty"] >= MIN_POSITION_QTY:
                # มี Position - โหลดข้อมูลจาก D1 + เติม qty/avg_cost จาก FIFO
                self.position = PositionState(
                    pair=self.pair,
                    status=PositionStatus.LONG,
                    entry_price=position_info["avg_cost"],
                    qty=position_info["qty"],
                    w_low=position_data.get("w_low"),
                    sl_price=position_data.get("sl_price"),
                    activation_price=position_data.get("activation_price"),
                    entry_trend_bullish=bool(position_data.get("entry_trend_bullish")) if position_data.get("entry_trend_bullish") is not None else None,
                    trailing_stop_activated=bool(position_data.get("trailing_stop_activated", False)),
                    trailing_stop_price=position_data.get("trailing_stop_price"),
                    prev_high=position_data.get("prev_high"),
                )
            else:
                # ไม่มี Position (รวม dust position)
                self.position = PositionState(
                    pair=self.pair,
                    status=PositionStatus.FLAT,
                )

        except Exception as e:
            print(f"[{self.pair}] Error loading position state: {e}")
            # Fallback: สร้าง Position FLAT
            self.position = PositionState(pair=self.pair, status=PositionStatus.FLAT)
            self.all_orders = []

    def _has_pending_entry_order(self) -> bool:
        """เช็คว่ามี Pending ENTRY Order อยู่หรือไม่"""
        pair_upper = self.pair.upper()
        relevant = [o for o in self.all_orders if (o.get("pair") or "").upper() == pair_upper]

        for o in relevant:
            if (o.get("order_type") or "").upper() == "ENTRY":
                status = (o.get("status") or "").upper()
                # เช็คว่าเป็น Pending หรือไม่ (ไม่รวม NEW เพราะเราไม่ใช้แล้ว)
                if status == "PENDING":
                    return True
        return False

    def _compute_open_position(self, orders: List[Dict[str, Any]]) -> Dict[str, Any]:
        """คำนวณ Position จาก Order History (FIFO)"""
        pair_upper = self.pair.upper()
        relevant = [o for o in orders if (o.get("pair") or "").upper() == pair_upper]
        relevant.sort(key=lambda o: o.get("filled_at") or o.get("requested_at") or o.get("created_at") or "")

        entry_queue: List[Dict[str, float]] = []
        ignored_status = {"CANCELED", "REJECTED"}

        def _consume_exit(qty: float) -> None:
            nonlocal entry_queue
            remaining = qty
            new_queue: List[Dict[str, float]] = []
            for leg in entry_queue:
                if remaining <= 0:
                    new_queue.append(leg)
                    continue
                if leg["qty"] > remaining:
                    leg["qty"] -= remaining
                    new_queue.append(leg)
                    remaining = 0
                else:
                    remaining -= leg["qty"]
            entry_queue = new_queue

        for o in relevant:
            status = (o.get("status") or "").upper()
            if status in ignored_status:
                continue

            # ⚠️ IMPORTANT: นับเฉพาะ Order ที่ FILLED แล้วเท่านั้น
            # - ไม่นับ PENDING orders (ยังไม่ match)
            # - ใช้ filled_qty เท่านั้น ห้ามใช้ requested_qty
            # - Status ที่ยอมรับ: FILLED, CLOSED, PARTIALLY_FILLED
            is_filled = status in {"FILLED", "CLOSED", "PARTIALLY_FILLED"}

            if not is_filled:
                # Skip orders ที่ยังไม่ filled (NEW, PENDING, etc.)
                continue

            qty = float(o.get("filled_qty") or 0)
            if qty <= 0:
                continue

            price = float(o.get("avg_price") or o.get("entry_price") or 0)

            if (o.get("order_type") or "").upper() == "ENTRY":
                entry_queue.append({"qty": qty, "price": price})
            elif (o.get("order_type") or "").upper() == "EXIT":
                _consume_exit(qty)

        total_qty = sum(leg["qty"] for leg in entry_queue)
        total_cost = sum(leg["qty"] * leg["price"] for leg in entry_queue)
        avg_cost = total_cost / total_qty if total_qty > 0 else 0.0

        return {
            "qty": total_qty,
            "avg_cost": avg_cost,
            "legs": entry_queue,
        }

    async def _update_trailing_stop_state(
        self,
        trailing_stop_activated: bool,
        trailing_stop_price: float,
        prev_high: float
    ):
        """อัปเดต Trailing Stop State กลับไปที่ D1"""
        try:
            update_payload = {
                "pair": self.pair,
                "trailing_stop_activated": trailing_stop_activated,
                "trailing_stop_price": trailing_stop_price,
                "prev_high": prev_high,
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{_WORKER_URL}/positions",
                    json=update_payload,
                    headers=_auth_headers(),
                    timeout=10.0
                )
                resp.raise_for_status()
                print(f"[TRAILING STOP] State saved to D1: activated={trailing_stop_activated}, SL={trailing_stop_price:.2f}")

        except Exception as e:
            print(f"[TRAILING STOP] Error saving state to D1: {e}")
            # Don't raise - we can continue even if save fails

    async def _fetch_market_data(self):
        """ดึงข้อมูล Candles และคำนวณ Indicators"""
        ltf_rows = await self.market_client.get_candles(
            pair=self.pair,
            interval=self.ltf_interval,
            limit=240
        )
        htf_rows = await self.market_client.get_candles(
            pair=self.pair,
            interval=self.htf_interval,
            limit=120
        )

        candles_ltf = _decorate_candles(ltf_rows)
        candles_htf = _decorate_candles(htf_rows)
        macd_hist = _macd_histogram([row["close"] for row in ltf_rows])

        # คำนวณ RSI และ Divergence (สำหรับ Exit เท่านั้น)
        rsi_values = calculate_rsi([row["close"] for row in ltf_rows], period=14)
        rsi_clean = [x for x in rsi_values if x is not None]
        lows = [c.low for c in candles_ltf[-len(rsi_clean):]]
        highs = [c.high for c in candles_ltf[-len(rsi_clean):]]
        trends = [1 if c.close > c.open else -1 for c in candles_ltf[-len(rsi_clean):]]

        detector = DivergenceDetector()
        divergences = detector.detect(rsi_clean, lows, highs, trends)

        # สร้าง divergence lookup by end index
        div_by_end_idx = {div.end_index: div for div in divergences}

        # คำนวณ Strong States (ใช้สำหรับ Bearish Divergence Exit เท่านั้น)
        strong_states = self._calculate_strong_states(
            candles_ltf, rsi_values, div_by_end_idx
        )

        return candles_ltf, candles_htf, macd_hist, ltf_rows, strong_states

    def _calculate_strong_states(
        self,
        candles: List[Candle],
        rsi_values: List[Optional[float]],
        div_by_end_idx: dict
    ) -> List[dict]:
        """คำนวณ Strong States สำหรับ Bearish Divergence Exit เท่านั้น

        ❌ ไม่ใช้ Bullish Divergence สำหรับ Entry อีกต่อไป
        ✅ ใช้เฉพาะ Bearish Divergence (SELL signal) สำหรับ Exit
        """
        states = []
        bullish_active = False
        bullish_div_idx: Optional[int] = None
        bearish_active = False
        bearish_div_idx: Optional[int] = None

        for i, candle in enumerate(candles):
            rsi = rsi_values[i] if i < len(rsi_values) else None
            state = {
                "index": i,
                "time": candle.timestamp,
                "strong_buy": "none-Active",
                "strong_sell": "none-Active",
                "special_signal": None,
                "cutloss": None,
            }

            if rsi is None:
                states.append(state)
                continue

            zone = candle.cdc_color

            # Bullish Divergence Logic (backtest.py line 140-188)
            if i in div_by_end_idx:
                div = div_by_end_idx[i]
                if div.type == DivergenceType.BULLISH:
                    bullish_active = True
                    bullish_div_idx = i
                    state["strong_buy"] = "Active"
                elif div.type == DivergenceType.BEARISH:
                    bearish_active = True
                    bearish_div_idx = i
                    state["strong_sell"] = "Active"

            # Bullish signal: Blue zone after divergence
            if bullish_active and zone == CDCColor.BLUE:
                # Find cutloss from consecutive red candles
                cutloss = candle.close * 0.95  # fallback
                if bullish_div_idx is not None:
                    red_low = None
                    for j in range(bullish_div_idx, i):
                        if candles[j].cdc_color == CDCColor.RED:
                            if red_low is None or candles[j].low < red_low:
                                red_low = candles[j].low
                        else:
                            red_low = None
                    if red_low is not None:
                        cutloss = min(cutloss, red_low)

                state["special_signal"] = "BUY"
                state["cutloss"] = cutloss
                state["strong_buy"] = "none-Active"
                bullish_active = False
                bullish_div_idx = None

            # Bearish signal: Orange zone after divergence
            if bearish_active and zone == CDCColor.ORANGE:
                state["special_signal"] = "SELL"
                state["strong_sell"] = "none-Active"
                bearish_active = False
                bearish_div_idx = None

            # Keep Active state if still active
            if bullish_active and state["strong_buy"] == "none-Active":
                state["strong_buy"] = "Active"
            if bearish_active and state["strong_sell"] == "none-Active":
                state["strong_sell"] = "Active"

            states.append(state)

        return states

    def _build_rules_detail(
        self,
        rules_result,
        candles_ltf: List[Candle],
        candles_htf: List[Candle]
    ) -> Dict[str, Any]:
        """สร้าง rules_detail สำหรับ UI"""
        # ดึงข้อมูล CDC colors
        ltf_prev2_color = candles_ltf[-3].cdc_color.value if len(candles_ltf) >= 3 else "unknown"
        ltf_prev1_color = candles_ltf[-2].cdc_color.value if len(candles_ltf) >= 2 else "unknown"
        ltf_curr_color = candles_ltf[-1].cdc_color.value if len(candles_ltf) >= 1 else "unknown"

        htf_prev2_color = candles_htf[-3].cdc_color.value if len(candles_htf) >= 3 else "unknown"
        htf_prev1_color = candles_htf[-2].cdc_color.value if len(candles_htf) >= 2 else "unknown"
        htf_curr_color = candles_htf[-1].cdc_color.value if len(candles_htf) >= 1 else "unknown"

        # ดึงข้อมูล Pattern จาก rules_result
        pattern_result = rules_result.rule_4_pattern if hasattr(rules_result, 'rule_4_pattern') else None
        pattern_meta = pattern_result.metadata if pattern_result else {}
        pattern_type = pattern_meta.get("pattern")

        # PatternType enum values: W_SHAPE="W", V_SHAPE="V", NONE="NONE"
        is_w_shape = pattern_type == "W" if pattern_type else False
        is_v_shape = pattern_type == "V" if pattern_type else False

        # ดึงข้อมูล W-shape details
        pattern_details = pattern_meta.get("details", {})
        w_left = pattern_details.get("low1")
        w_mid = pattern_details.get("mid_high")
        w_right = pattern_details.get("low2")

        # ดึง metadata จาก rule_1_cdc_green
        rule_1_meta = rules_result.rule_1_cdc_green.metadata if hasattr(rules_result.rule_1_cdc_green, 'metadata') else {}
        htf_transition = rule_1_meta.get("htf_transition")
        ltf_transition = rule_1_meta.get("ltf_transition")

        # สร้าง metadata สำหรับ LTF colors (ใช้ในการแสดงผล)
        ltf_colors_metadata = {
            "prev2": ltf_prev2_color,
            "prev1": ltf_prev1_color,
            "current": ltf_curr_color
        }

        # สร้าง metadata สำหรับ Pattern (รวม W-shape details)
        pattern_metadata = {
            "is_w_shape": is_w_shape,
            "is_v_shape": is_v_shape,
            "pattern_type": pattern_type or "NONE",
        }

        # เพิ่ม W-shape details ถ้ามี
        if w_left is not None and w_mid is not None and w_right is not None:
            pattern_metadata["w_left"] = w_left
            pattern_metadata["w_mid"] = w_mid
            pattern_metadata["w_right"] = w_right

        return {
            "rule_1_cdc_green": {
                "passed": rules_result.rule_1_cdc_green.passed,
                "reason": rules_result.rule_1_cdc_green.reason,
                "metadata": ltf_colors_metadata  # ส่งแบบ flat เพื่อให้ UI อ่านได้
            },
            "rule_4_pattern": {
                "passed": True,  # Always true (info only)
                "reason": f"W-shape: {is_w_shape}, V-shape: {is_v_shape}",
                "metadata": pattern_metadata
            }
        }

    async def _check_entry(
        self,
        candles_ltf: List[Candle],
        candles_htf: List[Candle],
        macd_hist: List[float],
        ltf_rows: List[dict],
        strong_states: List[dict]
    ) -> Dict[str, Any]:
        """ตรวจสอบเงื่อนไข ENTRY (ตรงกับ backtest.py และ rule_engine.py)

        Entry Requirements (ต้องผ่านทั้งหมด):
        1. ✅ LTF: BLUE→GREEN transition (prev2=blue, prev=green)
        2. ✅ LTF: Bull trend (EMA Fast > EMA Slow)
        3. ✅ HTF: Bull trend (EMA Fast > EMA Slow)
        4. ✅ Not V-shape pattern
        5. ✅ Entry price > Cutloss price

        ❌ Divergence ไม่ใช้สำหรับ Entry อีกต่อไป (ใช้เฉพาะ Exit)
        """

        # ตรวจสอบว่ามีข้อมูลเพียงพอ
        if len(candles_ltf) < 3 or len(candles_htf) < 2:
            return {
                "status": "no_entry_signal",
                "action": "wait",
                "reason": "Insufficient candles (need at least 3 LTF and 2 HTF)",
            }

        current_candle = candles_ltf[-1]

        # ประเมิน Rules โดยใช้ evaluate_all_rules (ตรงกับ backtest)
        rules_result = evaluate_all_rules(
            candles_ltf=candles_ltf,
            candles_htf=candles_htf,
            macd_histogram=macd_hist,
            params=self.config.rule_params,
            enable_w_shape_filter=self.config.enable_w_shape_filter,
            enable_leading_signal=self.config.enable_leading_signal,
        )

        # สร้าง rules_detail สำหรับ UI
        rules_detail_dict = self._build_rules_detail(rules_result, candles_ltf, candles_htf)

        # ตรวจสอบว่า Rules ผ่านหรือไม่ (เหมือน backtest.py line 121)
        if not rules_result.all_passed:
            return {
                "status": "no_entry_signal",
                "action": "wait",
                "reason": f"Entry rules not passed: {rules_result.rule_1_cdc_green.reason}",
                "rules": rules_result.summary,
                "rules_detail": rules_detail_dict,
            }

        # ✅ Entry Conditions Matched!
        entry_price = current_candle.close

        # คำนวณ Position Size จาก Balance จริง
        try:
            binance_client = _make_binance_client()
            balance = binance_client.fetch_balance()

            # ดึง USDT balance
            usdt_free = balance.get("USDT", {}).get("free", 0.0)

            if usdt_free <= 0:
                return {
                    "status": "no_entry_signal",
                    "action": "wait",
                    "reason": f"Insufficient USDT balance: {usdt_free:.2f}",
                    "rules": rules_result.summary,
                    "rules_detail": rules_detail_dict,
                }

            # ใช้เงินทั้งหมด (หรือ % ที่กำหนดใน config)
            # สามารถปรับเป็น: capital = usdt_free * self.config.position_size_pct
            capital = usdt_free
            quantity = capital / entry_price

        except Exception as exc:
            # Fallback: ถ้าดึง balance ไม่ได้ ให้ใช้ค่า default
            print(f"[WARNING] Cannot fetch balance: {exc}. Using default capital.")
            capital = 10000
            quantity = capital / entry_price

        # คำนวณ Stop Loss
        candles_ltf_closed = candles_ltf[:-1]
        structural_sl = self._calculate_structural_sl(candles_ltf_closed)

        # Validate: Entry price > Cutloss (เหมือน backtest)
        if entry_price <= structural_sl:
            return {
                "status": "no_entry_signal",
                "action": "wait",
                "reason": f"Entry price ({entry_price:.2f}) <= Cutloss ({structural_sl:.2f})",
                "rules": rules_result.summary,
                "rules_detail": rules_detail_dict,
            }

        # ส่ง Order ไป Binance
        order_result = await self._execute_entry_order(
            entry_price=entry_price,
            quantity=quantity,
            structural_sl=structural_sl,
            activation_price=entry_price * 1.075,
            rules=rules_result,
        )

        return {
            "status": "entry_signal_detected",
            "action": "buy",
            "pair": self.pair,
            "entry_price": entry_price,
            "quantity": quantity,
            "sl_price": structural_sl,
            "entry_type": "PATTERN",
            "pattern": "BLUE→GREEN + Bull Trend (LTF+HTF)",
            "rules": rules_result.summary,
            "rules_detail": rules_detail_dict,
            "order": order_result,
        }

    async def _check_exit(
        self,
        candles_ltf: List[Candle],
        candles_htf: List[Candle],
        macd_hist: List[float],
        ltf_rows: List[dict],
        strong_states: List[dict] = None
    ) -> Dict[str, Any]:
        """ตรวจสอบเงื่อนไข EXIT (เหมือน backtest.py ทุกประการ)

        Exit Conditions (Priority Order):
        0. Structural Stop Loss (Cutloss) Hit
        1. EMA Crossover (Bearish Trend Reversal)
        2. Trailing Stop Hit
        3. Orange → Red Pattern
        4. Strong Sell Signal (Bearish Divergence)
        """

        # ตรวจสอบข้อมูลเพียงพอ
        if len(candles_ltf) < 3 or len(ltf_rows) < 3:
            return {
                "status": "holding",
                "action": "wait",
                "position": self.position.to_dict(),
                "reason": "Insufficient data for exit check",
            }

        current_candle = candles_ltf[-1]
        current_row = ltf_rows[-1]
        current_price = current_candle.close
        current_low = current_candle.low
        current_avg = (current_candle.open + current_candle.close) / 2

        prev2_candle = candles_ltf[-3]
        prev_candle = candles_ltf[-2]
        current_state = strong_states[-1] if strong_states else None

        # Get position metadata (stored when entry)
        entry_price = self.position.entry_price  # Changed from avg_cost
        entry_trend_was_bullish = getattr(self.position, 'entry_trend_bullish', None)
        structural_sl = self.position.sl_price  # Initial/Structural Stop Loss

        # ===================================================
        # PRIORITY 0: Structural Stop Loss (Cutloss) Hit
        # ===================================================
        # This is the MOST important check - must happen BEFORE all other exit conditions
        # Matches backtest.py line 577-624
        if structural_sl is not None and current_low <= structural_sl:
            # 🚪 EXIT! Hit Structural Stop Loss
            exit_result = await self._execute_exit_order(
                reason=ExitReason.STRUCTURAL_SL,
                exit_price=structural_sl,  # Exit at SL price, not Low
                details=f"Structural Stop Loss Hit: Low={current_low:.2f} <= SL={structural_sl:.2f}"
            )
            print(f"[STRUCTURAL SL] Hit at {current_candle.timestamp}: Low={current_low:.2f} <= Cutloss={structural_sl:.2f}")

            return {
                "status": "exit_signal_detected",
                "action": "sell",
                "reason": "STRUCTURAL_SL",
                "exit_price": structural_sl,
                "pnl_pct": exit_result.get("pnl_pct", 0),
                "sl_price": structural_sl,
                "current_low": current_low,
                "order": exit_result,
            }

        # PRIORITY 1: EMA Crossover (Bearish Trend Reversal)
        # backtest.py line 599-670
        ema_fast = current_row.get("ema_fast", 0)
        ema_slow = current_row.get("ema_slow", 0)
        is_bullish = ema_fast > ema_slow

        if entry_trend_was_bullish and not is_bullish:
            # Entered in Bull, now Bear → EXIT!
            exit_result = await self._execute_exit_order(
                reason=ExitReason.EMA_CROSSOVER_BEARISH,
                exit_price=current_price,
                details=f"Bullish trend ended: EMA Fast ({ema_fast:.2f}) < EMA Slow ({ema_slow:.2f})"
            )
            return {
                "status": "exit_signal_detected",
                "action": "sell",
                "reason": "EMA_CROSSOVER_BEARISH",
                "exit_price": current_price,
                "pnl_pct": exit_result.get("pnl_pct", 0),
                "ema_fast": ema_fast,
                "ema_slow": ema_slow,
                "order": exit_result,
            }

        # PRIORITY 2: Trailing Stop Hit
        # backtest.py line 672-724
        activation_price = getattr(self.position, 'activation_price', None)
        trailing_stop_activated = getattr(self.position, 'trailing_stop_activated', False)
        trailing_stop_price = getattr(self.position, 'trailing_stop_price', None)
        prev_high = getattr(self.position, 'prev_high', None)

        if activation_price and trailing_stop_price is not None:
            # Step 1: Check Activation (Low >= 105% of activation_price)
            activation_threshold = activation_price * 1.05

            if not trailing_stop_activated and current_low >= activation_threshold:
                # ✅ Activated!
                trailing_stop_activated = True
                print(f"[TRAILING STOP] Activated at {current_candle.timestamp}: Low={current_low:.2f} >= Threshold={activation_threshold:.2f}")

            # Step 2: Check if SL Hit (only after activation)
            if trailing_stop_activated and current_low <= trailing_stop_price:
                # 🚪 EXIT! Hit Trailing Stop
                exit_result = await self._execute_exit_order(
                    reason=ExitReason.TRAILING_STOP,
                    exit_price=trailing_stop_price,  # Exit at SL price, not Low
                    details=f"Trailing Stop Hit: Low={current_low:.2f} <= SL={trailing_stop_price:.2f}"
                )
                return {
                    "status": "exit_signal_detected",
                    "action": "sell",
                    "reason": "TRAILING_STOP",
                    "exit_price": trailing_stop_price,
                    "pnl_pct": exit_result.get("pnl_pct", 0),
                    "sl_price": trailing_stop_price,
                    "current_low": current_low,
                    "order": exit_result,
                }

            # Step 3: Update Trailing Stop (can only rise)
            # SL = Current Avg Price × 93% (7% trailing distance)
            trailing_distance = 0.07
            potential_sl = current_avg * (1 - trailing_distance)

            if potential_sl > trailing_stop_price:
                old_sl = trailing_stop_price
                trailing_stop_price = potential_sl
                prev_high = current_avg

                price_change_pct = ((current_avg - (prev_high or entry_price)) / (prev_high or entry_price) * 100) if (prev_high or entry_price) > 0 else 0

                print(f"[TRAILING STOP] Updated: {old_sl:.2f} -> {trailing_stop_price:.2f} (Avg Price: {current_avg:.2f}, {price_change_pct:+.2f}%)")

                # Step 4: บันทึกกลับไป D1
                await self._update_trailing_stop_state(
                    trailing_stop_activated=trailing_stop_activated,
                    trailing_stop_price=trailing_stop_price,
                    prev_high=prev_high
                )

        # PRIORITY 3: Orange → Red Pattern
        # backtest.py line 759-825
        prev2_zone = prev2_candle.cdc_color
        prev_zone = prev_candle.cdc_color

        if prev2_zone == CDCColor.ORANGE and prev_zone == CDCColor.RED:
            exit_result = await self._execute_exit_order(
                reason=ExitReason.ORANGE_RED,
                exit_price=current_price,
                details=f"Orange → Red pattern detected"
            )
            return {
                "status": "exit_signal_detected",
                "action": "sell",
                "reason": "ORANGE_RED",
                "exit_price": current_price,
                "pnl_pct": exit_result.get("pnl_pct", 0),
                "pattern": f"ORANGE→RED (prev2={prev2_zone.value}, prev={prev_zone.value})",
                "order": exit_result,
            }

        # PRIORITY 4: Strong Sell Signal (Bearish Divergence)
        # backtest.py line 827-872
        if current_state and current_state.get("special_signal") == "SELL":
            exit_result = await self._execute_exit_order(
                reason=ExitReason.STRONG_SELL,
                exit_price=current_price,
                details=f"Bearish Divergence signal"
            )
            return {
                "status": "exit_signal_detected",
                "action": "sell",
                "reason": "STRONG_SELL",
                "exit_price": current_price,
                "pnl_pct": exit_result.get("pnl_pct", 0),
                "special_signal": "SELL",
                "order": exit_result,
            }

        # ไม่มีเงื่อนไข EXIT - ยังถือต่อ
        trailing_stop_info = "Not configured"
        if activation_price:
            activation_threshold = activation_price * 1.05
            trailing_stop_info = f"Activated={trailing_stop_activated}, SL={trailing_stop_price:.2f}, Threshold={activation_threshold:.2f}"

        # Distance to Structural SL
        structural_sl_info = "N/A"
        if structural_sl:
            distance_pct = ((current_price - structural_sl) / structural_sl) * 100
            structural_sl_info = f"SL={structural_sl:.2f}, Distance={distance_pct:+.2f}%, Safe={'✅' if current_low > structural_sl else '❌'}"

        exit_checks = {
            "structural_sl": structural_sl_info,
            "ema_crossover": f"Bull={is_bullish} (Fast={ema_fast:.2f}, Slow={ema_slow:.2f})",
            "trailing_stop": trailing_stop_info,
            "orange_red": f"prev2={prev2_zone.value}, prev={prev_zone.value}",
            "strong_sell": current_state.get("special_signal") if current_state else None,
        }

        return {
            "status": "holding",
            "action": "wait",
            "position": self.position.to_dict(),
            "current_price": current_price,
            "exit_checks": exit_checks,
        }

    def _calculate_structural_sl(self, candles: List[Candle]) -> float:
        """คำนวณ Structural Stop Loss จาก Swing Low ที่ใกล้ที่สุดกับจุด Entry

        Swing Low = แท่งที่ Low ต่ำกว่าแท่งข้างหน้าและข้างหลังอย่างน้อย 2 แท่ง
        ใช้ Swing Low แรกที่เจอ (ใกล้ที่สุด) ไม่ใช่ต่ำสุด
        """
        if len(candles) < 5:
            return candles[-1].low * 0.95  # Fallback 5%

        lookback = 30  # เพิ่มเป็น 30 แท่งเหมือน backtest
        swing_window = 2  # ต้องต่ำกว่าแท่งข้างๆ อย่างน้อย 2 แท่ง

        # หา Swing Low ย้อนหลังจากแท่งล่าสุด
        for i in range(len(candles) - 1, max(swing_window, len(candles) - lookback - 1), -1):
            if i < swing_window or i >= len(candles) - swing_window:
                continue

            current_low = candles[i].low

            # เช็คว่าเป็น Swing Low หรือไม่
            is_swing_low = True

            # เช็คแท่งข้างหลัง (ก่อนหน้า)
            for k in range(1, swing_window + 1):
                if i - k >= 0 and candles[i - k].low <= current_low:
                    is_swing_low = False
                    break

            # เช็คแท่งข้างหน้า (หลัง)
            if is_swing_low:
                for k in range(1, swing_window + 1):
                    if i + k < len(candles) and candles[i + k].low <= current_low:
                        is_swing_low = False
                        break

            # ถ้าเป็น Swing Low → ใช้เป็น Cutloss (Swing Low ที่ใกล้ที่สุด)
            if is_swing_low:
                return current_low

        # Fallback: ถ้าไม่เจอ Swing Low ให้ใช้ Low ต่ำสุดใน 30 แท่ง
        lows = [c.low for c in candles[max(0, len(candles) - lookback):]]
        if lows:
            return min(lows)

        # Fallback สุดท้าย
        return candles[-1].low * 0.95

    async def _execute_entry_order(
        self,
        entry_price: float,
        quantity: float,
        structural_sl: float,
        activation_price: float,
        rules
    ) -> Dict[str, Any]:
        """ส่ง Order ซื้อไป Binance Testnet และบันทึกใน D1 Worker

        Flow:
        1. เช็ค Balance
        2. Place Market Order ที่ Binance Testnet
        3. รอรับ Order ID และ Filled Info จาก Binance
        4. บันทึก Order ลง D1 Worker ด้วยสถานะ FILLED/PENDING
        """

        try:
            # 1. สร้าง Binance Client
            binance_client = _make_binance_client()

            # 2. เช็ค Balance (USDT สำหรับ BUY)
            symbol = self.pair.replace("/", "")  # BTC/USDT → BTCUSDT
            base, quote = self.pair.split("/")

            balance = binance_client.fetch_balance()
            quote_free = balance.get(quote, {}).get("free", 0.0)

            required_usdt = entry_price * quantity

            if quote_free < required_usdt:
                raise RuntimeError(
                    f"Insufficient balance: need {required_usdt:.2f} {quote}, "
                    f"have {quote_free:.2f} {quote}"
                )

            # 3. Adjust quantity to exchange precision
            quantity = float(binance_client.amount_to_precision(symbol, quantity))

            # 4. Place MARKET BUY Order ที่ Binance Testnet
            binance_order = binance_client.create_order(
                symbol=symbol,
                type="market",
                side="buy",
                amount=quantity,
            )

            # 5. ดึงข้อมูล Order จาก Binance Response
            info = binance_order.get("info", {})
            binance_order_id = str(info.get("orderId") or binance_order.get("id"))
            binance_status = info.get("status", "UNKNOWN")  # NEW, FILLED, PARTIALLY_FILLED, etc.

            filled_qty = float(info.get("executedQty") or quantity)

            # คำนวณ avg_price จาก cummulativeQuoteQty / executedQty
            avg_price = entry_price
            try:
                cumm_quote = float(info.get("cummulativeQuoteQty") or 0)
                if filled_qty > 0 and cumm_quote > 0:
                    avg_price = cumm_quote / filled_qty
            except Exception:
                pass

            # 5.1 ✅ Verify Order Status (รอ 2 วินาทีแล้วเช็คอีกครั้ง)
            await asyncio.sleep(2)

            try:
                verified_order = binance_client.fetch_order(binance_order_id, symbol)
                verified_status = verified_order.get("status", "UNKNOWN")
                verified_filled_qty = float(verified_order.get("filled", filled_qty))

                print(f"[ORDER VERIFY] Order {binance_order_id}: {verified_status}, Filled: {verified_filled_qty}")

                # อัพเดทข้อมูลจาก verified order
                binance_status = verified_status
                filled_qty = verified_filled_qty

                # คำนวณ avg_price ใหม่จาก verified order
                if "cost" in verified_order and verified_filled_qty > 0:
                    avg_price = float(verified_order["cost"]) / verified_filled_qty

            except Exception as verify_exc:
                print(f"[ORDER VERIFY] Warning: Cannot verify order {binance_order_id}: {verify_exc}")
                # ใช้ข้อมูลจาก response เดิม

            # 6. บันทึก Order ลง D1 Worker
            # ใช้สถานะจาก Binance: FILLED/PARTIALLY_FILLED/PENDING
            worker_status = "FILLED" if binance_status == "FILLED" else "PENDING"

            order_payload = {
                "pair": self.pair,
                "order_type": "ENTRY",
                "side": "BUY",
                "requested_qty": quantity,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "order_id": binance_order_id,
                "status": worker_status,
                "entry_reason": "CDC_RULES",
                "rule_1_cdc_green": rules.rule_1_cdc_green.passed if rules else False,
                "rule_2_leading_red": rules.rule_2_leading_red.passed if rules else False,
                "rule_3_leading_signal": rules.rule_3_leading_signal.passed if rules else False,
                "rule_4_pattern": rules.rule_4_pattern.passed if rules else False,
                "entry_price": avg_price,
                "w_low": structural_sl,
                "sl_price": structural_sl,
                "activation_price": activation_price,  # เพิ่ม Activation Price
                "requested_at": dt.datetime.now().isoformat(),
                "filled_at": dt.datetime.now().isoformat() if worker_status == "FILLED" else None,
            }

            # ส่งไป Worker
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{_WORKER_URL}/orders",
                    json=order_payload,
                    headers=_auth_headers(),
                    timeout=10.0
                )
                resp.raise_for_status()

            # 7. Update Position State ใน D1 (เพิ่ม entry_trend_bullish และ activation_price)
            # ดึง EMA เพื่อบันทึก Trend ตอน Entry
            ltf_rows_temp = await self.market_client.get_candles(
                pair=self.pair,
                interval=self.ltf_interval,
                limit=1
            )
            current_row = ltf_rows_temp[-1] if ltf_rows_temp else {}
            ema_fast = current_row.get("ema_fast", 0)
            ema_slow = current_row.get("ema_slow", 0)
            entry_trend_bullish = ema_fast > ema_slow

            position_payload = {
                "pair": self.pair,
                "status": "LONG",
                "entry_price": avg_price,
                "entry_time": dt.datetime.now().isoformat(),
                "w_low": structural_sl,
                "sl_price": structural_sl,
                "qty": filled_qty,
                "activation_price": activation_price,
                "entry_trend_bullish": entry_trend_bullish,
                "trailing_stop_activated": False,
                "trailing_stop_price": structural_sl,  # เริ่มต้นด้วย structural SL
                "prev_high": entry_price,  # เริ่มต้นด้วย entry price
            }

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{_WORKER_URL}/positions",
                    json=position_payload,
                    headers=_auth_headers(),
                    timeout=10.0
                )
                resp.raise_for_status()

            return {
                "order_id": binance_order_id,
                "status": worker_status,
                "binance_status": binance_status,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "binance_order": binance_order,
                "position_updated": True,
            }

        except ccxt.InsufficientFunds as exc:
            raise RuntimeError(f"Binance: Insufficient funds - {exc}") from exc
        except ccxt.BaseError as exc:
            raise RuntimeError(f"Binance error: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Order placement failed: {exc}") from exc

    async def _execute_exit_order(
        self,
        reason: ExitReason,
        exit_price: float,
        details: str = ""
    ) -> Dict[str, Any]:
        """ส่ง Order ขายไป Binance Testnet และบันทึกใน D1 Worker

        Flow:
        1. เช็ค Position ที่เหลือ
        2. Place Market SELL Order ที่ Binance Testnet
        3. รอรับ Order ID และ Filled Info จาก Binance
        4. บันทึก Order ลง D1 Worker ด้วยสถานะ FILLED/PENDING
        """

        if not self.position or not self.position.qty:
            raise ValueError("No position to exit")

        try:
            # 1. สร้าง Binance Client
            binance_client = _make_binance_client()

            # 2. เช็ค Balance (Base Asset สำหรับ SELL)
            symbol = self.pair.replace("/", "")  # BTC/USDT → BTCUSDT
            base, quote = self.pair.split("/")

            balance = binance_client.fetch_balance()
            base_free = balance.get(base, {}).get("free", 0.0)

            quantity = self.position.qty

            if base_free < quantity:
                raise RuntimeError(
                    f"Insufficient balance: need {quantity:.8f} {base}, "
                    f"have {base_free:.8f} {base}"
                )

            # 3. Adjust quantity to exchange precision
            quantity = float(binance_client.amount_to_precision(symbol, quantity))

            # 4. Place MARKET SELL Order ที่ Binance Testnet
            binance_order = binance_client.create_order(
                symbol=symbol,
                type="market",
                side="sell",
                amount=quantity,
            )

            # 5. ดึงข้อมูล Order จาก Binance Response
            info = binance_order.get("info", {})
            binance_order_id = str(info.get("orderId") or binance_order.get("id"))
            binance_status = info.get("status", "UNKNOWN")

            filled_qty = float(info.get("executedQty") or quantity)

            # คำนวณ avg_price จาก cummulativeQuoteQty / executedQty
            avg_price = exit_price
            try:
                cumm_quote = float(info.get("cummulativeQuoteQty") or 0)
                if filled_qty > 0 and cumm_quote > 0:
                    avg_price = cumm_quote / filled_qty
            except Exception:
                pass

            # 5.1 ✅ Verify Order Status (รอ 2 วินาทีแล้วเช็คอีกครั้ง)
            await asyncio.sleep(2)

            try:
                verified_order = binance_client.fetch_order(binance_order_id, symbol)
                verified_status = verified_order.get("status", "UNKNOWN")
                verified_filled_qty = float(verified_order.get("filled", filled_qty))

                print(f"[EXIT ORDER VERIFY] Order {binance_order_id}: {verified_status}, Filled: {verified_filled_qty}")

                # อัพเดทข้อมูลจาก verified order
                binance_status = verified_status
                filled_qty = verified_filled_qty

                # คำนวณ avg_price ใหม่จาก verified order
                if "cost" in verified_order and verified_filled_qty > 0:
                    avg_price = float(verified_order["cost"]) / verified_filled_qty

            except Exception as verify_exc:
                print(f"[EXIT ORDER VERIFY] Warning: Cannot verify order {binance_order_id}: {verify_exc}")
                # ใช้ข้อมูลจาก response เดิม

            # 6. คำนวณ PnL
            pnl_pct = ((avg_price - self.position.entry_price) / self.position.entry_price) * 100 if self.position.entry_price else 0
            pnl_amount = (avg_price - self.position.entry_price) * filled_qty if self.position.entry_price else 0

            # 7. บันทึก Order ลง D1 Worker
            worker_status = "FILLED" if binance_status == "FILLED" else "PENDING"

            order_payload = {
                "pair": self.pair,
                "order_type": "EXIT",
                "side": "SELL",
                "requested_qty": quantity,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "order_id": binance_order_id,  # ใช้ Order ID จาก Binance
                "status": worker_status,
                "exit_reason": f"{reason.value} | {details}",
                "entry_price": self.position.entry_price,
                "exit_price": avg_price,
                "pnl": pnl_amount,
                "pnl_pct": pnl_pct,
                "sl_price": self.position.sl_price,
                "requested_at": dt.datetime.now().isoformat(),
                "filled_at": dt.datetime.now().isoformat() if worker_status == "FILLED" else None,
            }

            # ส่งไป Worker
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{_WORKER_URL}/orders",
                    json=order_payload,
                    headers=_auth_headers(),
                    timeout=10.0
                )
                resp.raise_for_status()

            return {
                "order_id": binance_order_id,
                "status": worker_status,
                "binance_status": binance_status,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "pnl_pct": pnl_pct,
                "pnl_amount": pnl_amount,
                "binance_order": binance_order,
            }

        except ccxt.InsufficientFunds as exc:
            raise RuntimeError(f"Binance: Insufficient funds - {exc}") from exc
        except ccxt.BaseError as exc:
            raise RuntimeError(f"Binance error: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Order placement failed: {exc}") from exc


__all__ = ["RealtimeTradingEngine"]
