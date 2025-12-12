"""Endpoints for triggering a simple bot run and logging simulated orders to D1 via the worker."""

from __future__ import annotations

import os
import uuid
from typing import Dict, Any, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import ccxt

from routes.config import _db as config_store
from routes import order_sync
from routes import backtest

router = APIRouter(prefix="/bot", tags=["bot"])

_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
_WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")
_BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
_BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
# สำหรับบัญชีที่มี base เริ่มต้นค้างอยู่ (เช่น 1 BTC) ให้หักออกเมื่อประเมินโหมด ENTRY/EXIT
_BASE_BALANCE_OFFSET = float(os.getenv("BASE_BALANCE_OFFSET", "1.0"))


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_WORKER_TOKEN}"} if _WORKER_TOKEN else {}


class BotRunRequest(BaseModel):
    pair: str
    limit: int = 240
    initial_capital: float = 10000.0


class LiveRunRequest(BaseModel):
    pair: str
    limit: int = 240
    initial_capital: float = 10000.0


def _parse_float(val: Any) -> float:
    try:
        return float(val)
    except Exception:
        return 0.0


def _executed_status(status: str) -> bool:
    """Return True if status indicates an executed/partial order (not just NEW/OPEN)."""
    s = (status or "").upper()
    return s in {"FILLED", "CLOSED", "PARTIALLY_FILLED", "PARTIAL_FILL"}


def _sort_key(order: Dict[str, Any]) -> str:
    """Sort orders chronologically using filled/requested/created timestamps."""
    for key in ("filled_at", "requested_at", "created_at"):
        val = order.get(key)
        if val:
            return str(val)
    return ""


def _compute_open_position(orders: list[Dict[str, Any]], pair: str) -> Dict[str, Any]:
    """
    Build net open position (qty + avg cost) from order history.
    - Ignore canceled/rejected orders
    - Process ENTRY then offset with EXIT in time order (FIFO)
    - Keep remaining qty/cost only for legs that are not fully closed
    """
    pair_upper = pair.upper()
    relevant = [o for o in orders if (o.get("pair") or "").upper() == pair_upper]
    relevant.sort(key=_sort_key)

    entry_queue: list[Dict[str, float]] = []
    ignored_status = {"CANCELED", "REJECTED"}

    def _consume_exit(qty: float) -> None:
        nonlocal entry_queue
        remaining = qty
        new_queue: list[Dict[str, float]] = []
        for leg in entry_queue:
            if remaining <= 0:
                new_queue.append(leg)
                continue
            if leg["qty"] > remaining:
                # partially reduce this entry leg
                leg["qty"] -= remaining
                new_queue.append(leg)
                remaining = 0
            else:
                # consume entire leg
                remaining -= leg["qty"]
        entry_queue = new_queue

    for o in relevant:
        status = (o.get("status") or "").upper()
        if status in ignored_status:
            continue

        qty = _parse_float(o.get("filled_qty") if _executed_status(status) else o.get("filled_qty"))
        # If filled_qty missing/zero but requested exists and status is FILLED/CLOSED, fall back
        if qty <= 0 and _executed_status(status):
            qty = _parse_float(o.get("requested_qty"))
        price = _parse_float(o.get("avg_price") or o.get("entry_price"))

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
        "orders_used": len(relevant),
    }


def _make_ccxt_client() -> ccxt.binance:
    if not _BINANCE_API_KEY or not _BINANCE_API_SECRET:
        raise HTTPException(status_code=400, detail="Missing BINANCE_API_KEY / BINANCE_API_SECRET")
    client = ccxt.binance({
        "apiKey": _BINANCE_API_KEY,
        "secret": _BINANCE_API_SECRET,
        "options": {"defaultType": "spot"},
    })
    # use testnet when keys are testnet
    client.set_sandbox_mode(True)
    return client


def _get_balance_for_pair(client: ccxt.binance, pair: str) -> Dict[str, float]:
    base, quote = pair.split("/")
    bal = client.fetch_balance()
    base_free = bal.get(base, {}).get("free", 0.0) if isinstance(bal.get(base), dict) else bal.get(base, 0.0)
    quote_free = bal.get(quote, {}).get("free", 0.0) if isinstance(bal.get(quote), dict) else bal.get(quote, 0.0)
    return {"base": float(base_free or 0.0), "quote": float(quote_free or 0.0)}


async def _post_order(client: httpx.AsyncClient, payload: Dict[str, Any]) -> None:
    resp = await client.post(f"{_WORKER_URL}/orders", json=payload, headers=_auth_headers(), timeout=10.0)
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = getattr(exc.response, "text", str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to log order: {detail}") from exc


@router.post("/run")
async def run_bot(payload: BotRunRequest) -> Dict[str, Any]:
    """
    Run a lightweight analysis (reuse backtest) and persist simulated ENTRY/EXIT orders to D1.
    """
    pair = payload.pair.upper()
    limit = payload.limit
    initial_capital = payload.initial_capital

    cfg = config_store.get(pair)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Config not found for pair {pair}")

    try:
        result = await backtest.run_backtest(
            pair=pair,
            timeframe=None,
            htf_timeframe=None,
            limit=limit,
            initial_capital=initial_capital,
            use_trailing_stop=True,
        )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Bot run failed: {exc}") from exc

    trades = result.get("trades", [])
    stats = result.get("stats", {})
    orders_created = 0
    async with httpx.AsyncClient() as client:
        for trade in trades:
            entry_qty = trade.get("position_units") or 0
            exit_qty = entry_qty
            entry_price = trade.get("entry_price")
            exit_price = trade.get("exit_price")
            rules = trade.get("rules", {}) or {}
            entry_time = trade.get("entry_time") or ""
            exit_time = trade.get("exit_time") or ""
            entry_payload = {
                "pair": pair.upper(),
                "order_type": "ENTRY",
                "side": "BUY",
                "requested_qty": entry_qty,
                "filled_qty": entry_qty,
                "avg_price": entry_price,
                "order_id": f"sim-entry-{uuid.uuid4().hex[:8]}",
                "status": "FILLED",
                "entry_reason": "CDC_RULES",
                "exit_reason": None,
                "rule_1_cdc_green": bool(rules.get("rule_1_cdc_green")),
                "rule_2_leading_red": bool(rules.get("rule_2_leading_red")),
                "rule_3_leading_signal": bool(rules.get("rule_3_leading_signal")),
                "rule_4_pattern": bool(rules.get("rule_4_pattern")),
                "entry_price": entry_price,
                "exit_price": None,
                "pnl": None,
                "pnl_pct": None,
                "w_low": trade.get("cutloss_price"),
                "sl_price": trade.get("cutloss_price"),
                "requested_at": entry_time,
                "filled_at": entry_time,
            }
            exit_payload = {
                "pair": pair.upper(),
                "order_type": "EXIT",
                "side": "SELL",
                "requested_qty": exit_qty,
                "filled_qty": exit_qty,
                "avg_price": exit_price,
                "order_id": f"sim-exit-{uuid.uuid4().hex[:8]}",
                "status": "FILLED",
                "entry_reason": None,
                "exit_reason": trade.get("exit_reason") or "TAKE_PROFIT",
                "rule_1_cdc_green": bool(rules.get("rule_1_cdc_green")),
                "rule_2_leading_red": bool(rules.get("rule_2_leading_red")),
                "rule_3_leading_signal": bool(rules.get("rule_3_leading_signal")),
                "rule_4_pattern": bool(rules.get("rule_4_pattern")),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": trade.get("pnl_amount"),
                "pnl_pct": trade.get("pnl_pct"),
                "w_low": trade.get("cutloss_price"),
                "sl_price": trade.get("cutloss_price"),
                "requested_at": exit_time,
                "filled_at": exit_time,
            }
            await _post_order(client, entry_payload)
            orders_created += 1
            await _post_order(client, exit_payload)
            orders_created += 1

    return {
        "status": "ok",
        "pair": pair.upper(),
        "trades": len(trades),
        "orders_logged": orders_created,
        "stats": stats,
    }


@router.post("/run-live")
async def run_live(payload: LiveRunRequest) -> Dict[str, Any]:
    """
    Live-like run: ตัดสิน entry/exit จาก balance จริงและใช้ logic เดิม (CDC) จาก backtest เพียงรอบเดียว
    - ถ้ามี base asset > epsilon => โหมด EXIT (หา trade ขายล่าสุด)
    - ถ้า base ~ 0 => โหมด ENTRY (หา trade ซื้อล่าสุด)
    - ไม่แก้ไข logic CDC/backtest เพียง reuse ผลลัพธ์ล่าสุด
    """
    pair = payload.pair.upper()
    limit = payload.limit
    initial_capital = payload.initial_capital

    cfg = config_store.get(pair)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Config not found for pair {pair}")

    client = _make_ccxt_client()
    bal = _get_balance_for_pair(client, pair)
    # ใช้ประวัติ order ใน D1 เพื่อคำนวณโพสิชันที่ยังไม่ปิด/ไม่ขายหมด
    orders_data = await order_sync.fetch_worker_orders()
    position = _compute_open_position(orders_data.get("orders", []), pair)
    epsilon = 1e-8
    effective_qty = position.get("qty", 0.0)
    # ถ้า worker ไม่เหลือโพสิชัน แต่ balance base ยังมี ให้ถือว่ามีของเพื่อความปลอดภัย (หัก offset)
    base_after_offset = max(bal["base"] - _BASE_BALANCE_OFFSET, 0.0)
    if effective_qty <= epsilon and base_after_offset > epsilon:
        effective_qty = base_after_offset
    has_position = effective_qty > epsilon

    try:
        result = await backtest.run_backtest(
            pair=pair,
            timeframe=None,
            htf_timeframe=None,
            limit=limit,
            initial_capital=initial_capital,
            use_trailing_stop=True,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Live run failed: {exc}") from exc

    trades = result.get("trades", [])
    stats = result.get("stats", {})

    target_side = "SELL" if has_position else "BUY"
    # เลือก trade ที่เป็นฝั่งที่ต้องการ (BUY=entry, SELL=exit)
    selected = None
    for trade in reversed(trades):
        if target_side == "BUY" and trade.get("entry_price"):
            selected = ("ENTRY", trade)
            break
        if target_side == "SELL" and trade.get("exit_price"):
            selected = ("EXIT", trade)
            break

    if not selected:
        raise HTTPException(status_code=400, detail="No signal found for current mode")

    order_kind, trade = selected
    rules = trade.get("rules", {}) or {}
    decision_reason = {
        "mode": "EXIT" if has_position else "ENTRY",
        "position_qty": position.get("qty", 0.0),
        "effective_qty": effective_qty,
        "avg_cost": position.get("avg_cost", 0.0),
        "balance": bal,
        "base_offset": _BASE_BALANCE_OFFSET,
    }
    async with httpx.AsyncClient() as http_client:
        if order_kind == "ENTRY":
            qty = trade.get("position_units") or 0
            payload_entry = {
                "pair": pair,
                "order_type": "ENTRY",
                "side": "BUY",
                "requested_qty": qty,
                "filled_qty": qty,
                "avg_price": trade.get("entry_price"),
                "order_id": f"live-entry-{uuid.uuid4().hex[:8]}",
                "status": "NEW",
                "entry_reason": "CDC_RULES",
                "exit_reason": None,
                "rule_1_cdc_green": bool(rules.get("rule_1_cdc_green")),
                "rule_2_leading_red": bool(rules.get("rule_2_leading_red")),
                "rule_3_leading_signal": bool(rules.get("rule_3_leading_signal")),
                "rule_4_pattern": bool(rules.get("rule_4_pattern")),
                "entry_price": trade.get("entry_price"),
                "exit_price": None,
                "pnl": None,
                "pnl_pct": None,
                "w_low": trade.get("cutloss_price"),
                "sl_price": trade.get("cutloss_price"),
                "requested_at": trade.get("entry_time") or "",
                "filled_at": None,
            }
            await _post_order(http_client, payload_entry)
            orders_logged = 1
        else:
            # ขายตามจำนวนที่เหลือเปิดอยู่ (ไม่เกินสัญญาณที่ได้จาก backtest)
            signal_qty = trade.get("position_units") or 0
            qty = min(effective_qty, signal_qty or effective_qty)
            if qty <= 0:
                raise HTTPException(status_code=400, detail="No open position to exit")
            exit_reason = trade.get("exit_reason") or "CDC_EXIT"
            payload_exit = {
                "pair": pair,
                "order_type": "EXIT",
                "side": "SELL",
                "requested_qty": qty,
                "filled_qty": qty,
                "avg_price": trade.get("exit_price"),
                "order_id": f"live-exit-{uuid.uuid4().hex[:8]}",
                "status": "NEW",
                "entry_reason": None,
                "exit_reason": f"{exit_reason} | pos_qty={qty:.8f} | avg_cost={position.get('avg_cost', 0.0):.2f}",
                "rule_1_cdc_green": bool(rules.get("rule_1_cdc_green")),
                "rule_2_leading_red": bool(rules.get("rule_2_leading_red")),
                "rule_3_leading_signal": bool(rules.get("rule_3_leading_signal")),
                "rule_4_pattern": bool(rules.get("rule_4_pattern")),
                "entry_price": trade.get("entry_price"),
                "exit_price": trade.get("exit_price"),
                "pnl": trade.get("pnl_amount"),
                "pnl_pct": trade.get("pnl_pct"),
                "w_low": trade.get("cutloss_price"),
                "sl_price": trade.get("cutloss_price"),
                "requested_at": trade.get("exit_time") or "",
                "filled_at": None,
            }
            await _post_order(http_client, payload_exit)
            orders_logged = 1

    return {
        "status": "ok",
        "mode": "EXIT" if has_position else "ENTRY",
        "pair": pair,
        "orders_logged": orders_logged,
        "stats": stats,
        "balance": bal,
        "position": position,
        "decision": decision_reason,
    }


# ===========================
# Real-time Trading Scheduler
# ===========================

from trading.scheduler import TradingScheduler

# Global Scheduler Instance
_trading_scheduler: Optional[TradingScheduler] = None


class SchedulerStartRequest(BaseModel):
    pairs: List[str]
    interval_minutes: int = 1


@router.post("/scheduler/start")
async def start_scheduler(payload: SchedulerStartRequest) -> Dict[str, Any]:
    """เริ่ม Real-time Trading Scheduler

    Scheduler จะตรวจสอบเงื่อนไข Entry/Exit ทุก N นาทีสำหรับคู่เงินที่กำหนด

    Args:
        pairs: รายการคู่เงิน เช่น ["BTC/USDT", "ETH/USDT"]
        interval_minutes: ตรวจสอบทุกกี่นาที (default: 1)

    Returns:
        Status และข้อมูล Scheduler
    """
    global _trading_scheduler

    if _trading_scheduler and _trading_scheduler.is_running:
        raise HTTPException(status_code=400, detail="Scheduler is already running. Stop it first.")

    _trading_scheduler = TradingScheduler()

    try:
        await _trading_scheduler.start(
            pairs=payload.pairs,
            interval_minutes=payload.interval_minutes
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {exc}") from exc

    return {
        "status": "started",
        "pairs": payload.pairs,
        "interval_minutes": payload.interval_minutes,
        "message": f"Scheduler started - checking every {payload.interval_minutes} minute(s)",
    }


@router.post("/scheduler/stop")
async def stop_scheduler() -> Dict[str, Any]:
    """หยุด Real-time Trading Scheduler

    Returns:
        Status confirmation
    """
    global _trading_scheduler

    if not _trading_scheduler or not _trading_scheduler.is_running:
        raise HTTPException(status_code=400, detail="Scheduler is not running")

    try:
        await _trading_scheduler.stop()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {exc}") from exc

    return {
        "status": "stopped",
        "message": "Scheduler stopped successfully",
    }


@router.get("/scheduler/status")
async def get_scheduler_status() -> Dict[str, Any]:
    """ดูสถานะ Scheduler

    Returns:
        Scheduler status และข้อมูลการทำงาน
    """
    global _trading_scheduler

    if not _trading_scheduler:
        return {
            "status": "not_initialized",
            "is_running": False,
        }

    scheduler_status = _trading_scheduler.get_status()

    return {
        "status": "running" if scheduler_status["is_running"] else "stopped",
        **scheduler_status,
    }
