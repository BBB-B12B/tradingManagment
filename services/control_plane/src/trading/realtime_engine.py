"""Real-time Trading Engine - ตรวจสอบเงื่อนไข Entry/Exit แบบ Real-time

This module implements real-time trading logic with full Entry/Exit conditions:

Entry Conditions (4 Rules):
1. CDC Color = GREEN (both LTF and HTF)
2. Leading Red exists
3. Leading Signal (Momentum Flip + Higher Low)
4. Pattern = W-Shape (not V-Shape)

Exit Conditions (5 Conditions):
1. EMA Crossover Bearish (Trend Reversal)
2. Trailing Stop Hit
3. CDC Pattern Orange → Red
4. RSI Divergence (STRONG_SELL)
5. Structural Stop Loss

ใช้งาน:
    engine = RealtimeTradingEngine(pair="BTC/USDT")
    await engine.run()  # ตรวจสอบและทำ Trade ครั้งเดียว
"""

from __future__ import annotations

import datetime as dt
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from clients.binance_th_client import BinanceTHClient
from libs.common.cdc_rules import evaluate_all_rules
from libs.common.cdc_rules.types import Candle, CDCColor
from libs.common.cdc_rules.divergence import calculate_rsi, DivergenceDetector, DivergenceType
from libs.common.exit_rules import ExitReason
from libs.common.position_state import PositionState, PositionStatus
from indicators.fibonacci import trace_wave_from_entry
from routes.config import _db as config_store
from routes.order_sync import fetch_worker_orders
from indicators.action_zone import compute_action_zone

import httpx
import os
import uuid


LTF_TO_HTF = {
    "15m": "1h",
    "30m": "4h",
    "1h": "1d",
    "4h": "1d",
    "1d": "1w",
}

_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
_WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_WORKER_TOKEN}"} if _WORKER_TOKEN else {}


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


def _decorate_candles(raw_rows: List[dict]) -> List[Candle]:
    """Convert raw Binance rows to Candle objects with CDC colors"""
    closes = [row["close"] for row in raw_rows]
    hist = _macd_histogram(closes)

    candles: List[Candle] = []
    for row, hist_value in zip(raw_rows, hist):
        ts = dt.datetime.utcfromtimestamp(row["open_time"] / 1000)
        color = CDCColor.GREEN if hist_value >= 0 else CDCColor.RED
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
        candles_ltf, candles_htf, macd_hist, ltf_rows = await self._fetch_market_data()

        if not self.position.is_long():
            # โหมด ENTRY - ตรวจสอบเงื่อนไขเข้าซื้อ
            result = await self._check_entry(candles_ltf, candles_htf, macd_hist, ltf_rows)
        else:
            # โหมด EXIT - ตรวจสอบเงื่อนไขออกขาย
            result = await self._check_exit(candles_ltf, candles_htf, macd_hist, ltf_rows)

        # เพิ่ม Position info ใน result
        result["position"] = self.position.to_dict()
        return result

    async def _load_position_state(self):
        """โหลด Position State จาก D1 Worker"""
        try:
            # ดึงจาก Worker API (ถ้ามี endpoint)
            # ตอนนี้ใช้ logic เดิมจาก bot.py ในการคำนวณจาก orders
            orders_data = await fetch_worker_orders()
            orders = orders_data.get("orders", [])

            # คำนวณ Position จาก Orders (FIFO)
            position_info = self._compute_open_position(orders)

            if position_info["qty"] > 0:
                # มี Position
                self.position = PositionState(
                    pair=self.pair,
                    status=PositionStatus.LONG,
                    entry_price=position_info["avg_cost"],
                    qty=position_info["qty"],
                    # TODO: ดึง w_low, sl_price จาก D1
                )
            else:
                # ไม่มี Position
                self.position = PositionState(
                    pair=self.pair,
                    status=PositionStatus.FLAT,
                )

            print(f"[{self.pair}] Position State: {self.position.status.value} | Qty: {self.position.qty or 0}")

        except Exception as e:
            print(f"[{self.pair}] Error loading position state: {e}")
            # Fallback: สร้าง Position FLAT
            self.position = PositionState(pair=self.pair, status=PositionStatus.FLAT)

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

            qty = float(o.get("filled_qty") or o.get("requested_qty") or 0)
            price = float(o.get("avg_price") or o.get("entry_price") or 0)

            if (o.get("order_type") or "").upper() == "ENTRY":
                if qty > 0:
                    entry_queue.append({"qty": qty, "price": price})
            elif (o.get("order_type") or "").upper() == "EXIT":
                if qty > 0:
                    _consume_exit(qty)

        total_qty = sum(leg["qty"] for leg in entry_queue)
        total_cost = sum(leg["qty"] * leg["price"] for leg in entry_queue)
        avg_cost = total_cost / total_qty if total_qty > 0 else 0.0

        return {
            "qty": total_qty,
            "avg_cost": avg_cost,
            "legs": entry_queue,
        }

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

        return candles_ltf, candles_htf, macd_hist, ltf_rows

    async def _check_entry(
        self,
        candles_ltf: List[Candle],
        candles_htf: List[Candle],
        macd_hist: List[float],
        ltf_rows: List[dict]
    ) -> Dict[str, Any]:
        """ตรวจสอบเงื่อนไข ENTRY (4 กฎ)

        ⚠️ IMPORTANT: ใช้เฉพาะแท่งเทียนที่ CLOSED แล้วเท่านั้น
        - ตัดแท่งปัจจุบันออก (candles[:-1])
        - Entry ที่ราคาเปิดของแท่งถัดไป (candles[-1].open)
        """

        # ใช้เฉพาะแท่งที่ปิดแล้ว (ไม่รวมแท่งปัจจุบัน)
        if len(candles_ltf) < 2 or len(candles_htf) < 2:
            return {
                "status": "insufficient_data",
                "action": "wait",
                "reason": "Not enough closed candles",
            }

        candles_ltf_closed = candles_ltf[:-1]  # ตัดแท่งปัจจุบันออก
        candles_htf_closed = candles_htf[:-1]
        macd_hist_closed = macd_hist[:-1]

        # ประเมินกฎทั้ง 4 ข้อ (ใช้เฉพาะแท่งปิด)
        rules_result = evaluate_all_rules(
            candles_ltf=candles_ltf_closed,
            candles_htf=candles_htf_closed,
            macd_histogram=macd_hist_closed,
            params=self.config.rule_params,
            enable_w_shape_filter=self.config.enable_w_shape_filter,
            enable_leading_signal=self.config.enable_leading_signal,
        )

        if not rules_result.all_passed:
            return {
                "status": "no_entry_signal",
                "action": "wait",
                "reason": "Entry conditions not met",
                "rules": rules_result.summary,
            }

        # ✅ ทุกกฎผ่าน → เตรียมส่ง Order ซื้อ
        # Entry ที่ราคาเปิดของแท่งถัดไป (= แท่งปัจจุบัน)
        current_candle = candles_ltf[-1]
        last_closed_candle = candles_ltf_closed[-1]

        # Entry Price = ราคาเปิดของแท่งปัจจุบัน (แท่งถัดไปจากที่ปิด)
        entry_price = current_candle.open

        # คำนวณ Position Size
        capital = 10000  # TODO: ดึงจาก Config หรือ Balance
        quantity = capital / entry_price

        # คำนวณ Stop Loss (Structural SL) - ใช้แท่งปิดเท่านั้น
        structural_sl = self._calculate_structural_sl(candles_ltf_closed)

        # คำนวณ Trailing Stop Activation (Fibonacci 100% หรือ 7.5%)
        # ใช้ timestamp ของแท่งที่ปิดล่าสุด
        entry_timestamp_ms = int(last_closed_candle.timestamp.timestamp() * 1000)
        ltf_rows_closed = ltf_rows[:-1]  # ใช้เฉพาะ rows ที่ปิด
        wave = trace_wave_from_entry(ltf_rows_closed, entry_timestamp_ms)

        if wave:
            # W-Shape → ใช้ Fib 100%
            wave1_range = wave['swing_high']['price'] - wave['swing_low_1']['price']
            activation_price = wave['swing_low_2']['price'] + wave1_range
            activation_type = "Fib_100_Extension"
        else:
            # V-Shape หรือไม่พบ Wave → ใช้ 7.5%
            activation_price = entry_price * 1.075
            activation_type = "7.5%_profit"

        # ส่ง Order ไป Worker/D1
        order_result = await self._execute_entry_order(
            entry_price=entry_price,
            quantity=quantity,
            structural_sl=structural_sl,
            activation_price=activation_price,
            rules=rules_result,
        )

        return {
            "status": "entry_signal_detected",
            "action": "buy",
            "pair": self.pair,
            "entry_price": entry_price,
            "quantity": quantity,
            "sl_price": structural_sl,
            "structural_sl": structural_sl,
            "activation_price": activation_price,
            "activation_type": activation_type,
            "rules": rules_result.summary,
            "order": order_result,
        }

    async def _check_exit(
        self,
        candles_ltf: List[Candle],
        candles_htf: List[Candle],
        macd_hist: List[float],
        ltf_rows: List[dict]
    ) -> Dict[str, Any]:
        """ตรวจสอบเงื่อนไข EXIT (5 เงื่อนไข)

        ⚠️ Exit Logic แบ่งเป็น 2 ประเภท:
        1. ใช้แท่งปัจจุบัน (Real-time): Stop Loss, Trailing Stop
        2. ใช้แท่งปิด (Wait for close): Orange→Red, Divergence, EMA Cross

        Priority:
        1. Structural Stop Loss (แท่งปัจจุบัน - ตรวจ Low ทันที)
        2. Trailing Stop Hit (แท่งปัจจุบัน - ตรวจ Low ทันที)
        3. EMA Crossover Bearish (แท่งปิด)
        4. Orange → Red (แท่งปิด)
        5. RSI Divergence (แท่งปิด)
        """

        current_candle = candles_ltf[-1]  # แท่งปัจจุบัน (ยังไม่ปิด)
        current_price = current_candle.close
        current_low = current_candle.low  # สำหรับเช็ค Stop Loss

        # === ส่วนที่ 1: ตรวจสอบแบบ Real-time (ใช้แท่งปัจจุบัน) ===

        # 1️⃣ Structural Stop Loss (ตรวจ Low ทันที)
        if self.position.sl_price and current_low <= self.position.sl_price:
            # EXIT: Stop Loss Hit
            exit_result = await self._execute_exit_order(
                reason=ExitReason.STRUCTURAL_SL,
                exit_price=self.position.sl_price,
                details=f"Low {current_low:.2f} <= SL {self.position.sl_price:.2f}"
            )
            return {
                "status": "exit_signal_detected",
                "action": "sell",
                "reason": "STOP_LOSS",
                "exit_price": self.position.sl_price,
                "order": exit_result,
            }

        # 2️⃣ Trailing Stop Hit (ตรวจ Low ทันที)
        # TODO: ต้องมี State เก็บ trailing_stop_price และ trailing_stop_activated
        # ตอนนี้ข้ามไปก่อน

        # === ส่วนที่ 2: ตรวจสอบแบบ Wait for Close (ใช้แท่งปิด) ===

        if len(candles_ltf) < 2:
            return {"status": "holding", "action": "wait", "reason": "Insufficient closed candles"}

        candles_ltf_closed = candles_ltf[:-1]
        candles_htf_closed = candles_htf[:-1]
        ltf_rows_closed = ltf_rows[:-1]

        # คำนวณ RSI (ใช้แท่งปิด)
        closes_closed = [c.close for c in candles_ltf_closed]
        rsi_values = calculate_rsi(closes_closed, period=14)

        # 3️⃣ EMA Crossover Bearish (ใช้แท่งปิด)
        # TODO: ต้องเพิ่ม ema_fast, ema_slow ใน Candle dataclass
        # ตอนนี้ข้ามไปก่อน

        # 4️⃣ CDC Pattern Orange → Red (ใช้แท่งปิด)
        # ตรวจสอบ Action Zone
        try:
            closes_for_zone = [row["close"] for row in ltf_rows_closed]
            action_zones = compute_action_zone(closes_for_zone)

            if len(action_zones) >= 2:
                prev2_zone = action_zones[-3]["zone"] if len(action_zones) >= 3 else None
                prev_zone = action_zones[-2]["zone"] if len(action_zones) >= 2 else None

                if prev2_zone == "orange" and prev_zone == "red":
                    # EXIT: Orange → Red detected
                    exit_result = await self._execute_exit_order(
                        reason=ExitReason.CDC_RED_EXIT,
                        exit_price=current_price,
                        details="CDC Pattern Orange → Red"
                    )
                    return {
                        "status": "exit_signal_detected",
                        "action": "sell",
                        "reason": "ORANGE_RED",
                        "exit_price": current_price,
                        "order": exit_result,
                    }
        except Exception as e:
            print(f"[{self.pair}] Action Zone check error: {e}")

        # 5️⃣ RSI Divergence (STRONG_SELL) - ใช้แท่งปิด
        lows = [c.low for c in candles_ltf_closed]
        highs = [c.high for c in candles_ltf_closed]
        # สร้าง trend list (ถ้า cdc_color = GREEN → bullish)
        trends = [c.cdc_color == CDCColor.GREEN for c in candles_ltf_closed]

        detector = DivergenceDetector()
        divergences = detector.detect(rsi_values, lows, highs, trends)

        # หา Bearish Divergence ล่าสุด
        for div in reversed(divergences):
            if div.type == DivergenceType.BEARISH:
                # ตรวจสอบว่า Divergence เกิดหลัง Entry หรือไม่
                if self.position.entry_bar_index and div.end_index > self.position.entry_bar_index:
                    # EXIT: Bearish Divergence detected
                    exit_result = await self._execute_exit_order(
                        reason=ExitReason.DIVERGENCE_EXIT,
                        exit_price=current_price,
                        details=f"Bearish Divergence RSI:{div.rsi_start:.1f}→{div.rsi_end:.1f}"
                    )
                    return {
                        "status": "exit_signal_detected",
                        "action": "sell",
                        "reason": "STRONG_SELL",
                        "exit_price": current_price,
                        "divergence": {
                            "rsi_start": div.rsi_start,
                            "rsi_end": div.rsi_end,
                            "price_start": div.price_start,
                            "price_end": div.price_end,
                        },
                        "order": exit_result,
                    }
                break

        # ไม่มีเงื่อนไข EXIT - ยังถือต่อ
        return {
            "status": "holding",
            "action": "wait",
            "position": self.position.to_dict(),
            "current_price": current_price,
            "sl_distance": current_price - (self.position.sl_price or 0),
        }

    def _calculate_structural_sl(self, candles: List[Candle]) -> float:
        """คำนวณ Structural Stop Loss จาก Swing Low ล่าสุด"""
        # หา Swing Low ล่าสุด (ต่ำกว่าแท่งข้างหน้า/หลัง 2 แท่ง)
        if len(candles) < 5:
            return candles[-1].low * 0.95  # Fallback 5%

        # Scan ย้อนหลัง 20 แท่ง
        lookback = min(20, len(candles) - 2)
        swing_lows = []

        for i in range(len(candles) - 2, max(0, len(candles) - lookback - 1), -1):
            if i < 2 or i >= len(candles) - 2:
                continue

            current_low = candles[i].low
            is_swing_low = all(
                current_low < candles[i - j].low for j in range(1, 3)
            ) and all(
                current_low < candles[i + j].low for j in range(1, 3)
            )

            if is_swing_low:
                swing_lows.append(current_low)

        if swing_lows:
            return min(swing_lows)  # ใช้ Swing Low ต่ำสุด
        else:
            return candles[-1].low * 0.95  # Fallback 5%

    async def _execute_entry_order(
        self,
        entry_price: float,
        quantity: float,
        structural_sl: float,
        activation_price: float,
        rules
    ) -> Dict[str, Any]:
        """ส่ง Order ซื้อไป D1 Worker"""

        order_payload = {
            "pair": self.pair,
            "order_type": "ENTRY",
            "side": "BUY",
            "requested_qty": quantity,
            "filled_qty": quantity,
            "avg_price": entry_price,
            "order_id": f"realtime-entry-{uuid.uuid4().hex[:8]}",
            "status": "NEW",
            "entry_reason": "CDC_RULES",
            "rule_1_cdc_green": rules.rule_1_cdc_green.passed,
            "rule_2_leading_red": rules.rule_2_leading_red.passed,
            "rule_3_leading_signal": rules.rule_3_leading_signal.passed,
            "rule_4_pattern": rules.rule_4_pattern.passed,
            "entry_price": entry_price,
            "w_low": structural_sl,
            "sl_price": structural_sl,
            "requested_at": dt.datetime.now().isoformat(),
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

        print(f"✅ [ENTRY] {self.pair} @ {entry_price:.2f} | Qty: {quantity:.6f} | SL: {structural_sl:.2f}")

        return {"order_id": order_payload["order_id"], "status": "submitted"}

    async def _execute_exit_order(
        self,
        reason: ExitReason,
        exit_price: float,
        details: str = ""
    ) -> Dict[str, Any]:
        """ส่ง Order ขายไป D1 Worker"""

        if not self.position or not self.position.qty:
            raise ValueError("No position to exit")

        pnl_pct = ((exit_price - self.position.entry_price) / self.position.entry_price) * 100 if self.position.entry_price else 0

        order_payload = {
            "pair": self.pair,
            "order_type": "EXIT",
            "side": "SELL",
            "requested_qty": self.position.qty,
            "filled_qty": self.position.qty,
            "avg_price": exit_price,
            "order_id": f"realtime-exit-{uuid.uuid4().hex[:8]}",
            "status": "NEW",
            "exit_reason": f"{reason.value} | {details}",
            "entry_price": self.position.entry_price,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
            "sl_price": self.position.sl_price,
            "requested_at": dt.datetime.now().isoformat(),
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

        print(f"❌ [EXIT] {self.pair} @ {exit_price:.2f} | Reason: {reason.value} | PnL: {pnl_pct:.2f}%")

        return {"order_id": order_payload["order_id"], "status": "submitted", "pnl_pct": pnl_pct}


__all__ = ["RealtimeTradingEngine"]
