"""Endpoints for triggering a simple bot run and logging simulated orders to D1 via the worker."""

from __future__ import annotations

import os
import uuid
from typing import Dict, Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import ccxt

from routes.config import _db as config_store
from routes import backtest

router = APIRouter(prefix="/bot", tags=["bot"])

_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
_WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")
_BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
_BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")


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
    epsilon = 1e-8
    has_position = bal["base"] > epsilon

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
            qty = trade.get("position_units") or 0
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
                "exit_reason": trade.get("exit_reason") or "TAKE_PROFIT",
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
    }
