"""Endpoints for triggering a simple bot run and logging simulated orders to D1 via the worker."""

from __future__ import annotations

import os
import uuid
from typing import Dict, Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from routes.config import _db as config_store
from routes import backtest

router = APIRouter(prefix="/bot", tags=["bot"])

_WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
_WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")


def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_WORKER_TOKEN}"} if _WORKER_TOKEN else {}


class BotRunRequest(BaseModel):
    pair: str
    limit: int = 240
    initial_capital: float = 10000.0


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
