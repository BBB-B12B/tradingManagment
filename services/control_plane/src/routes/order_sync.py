"""Poller endpoints to sync open orders from D1 (via worker) and update status."""

from __future__ import annotations

import os
from typing import Dict, Any, List

import httpx
import ccxt
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/orders", tags=["orders"])

WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")

def _auth_headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {WORKER_TOKEN}"} if WORKER_TOKEN else {}


def _make_client() -> ccxt.binance:
    api_key = os.getenv("BINANCE_API_KEY") or ""
    api_secret = os.getenv("BINANCE_API_SECRET") or ""
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="Missing BINANCE_API_KEY / BINANCE_API_SECRET")
    client = ccxt.binance({
        "apiKey": api_key,
        "secret": api_secret,
        "options": {"defaultType": "spot"},
    })
    # for testnet adjust if needed
    client.set_sandbox_mode(True)
    return client


async def _fetch_open_orders() -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{WORKER_URL}/orders", headers=_auth_headers(), timeout=10.0)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = getattr(exc.response, "text", str(exc))
            raise HTTPException(status_code=502, detail=f"Worker /orders failed: {detail}") from exc
        data = resp.json()
        return [o for o in data.get("orders", []) if (o.get("status") or "").upper() in {"NEW", "PARTIALLY_FILLED", "OPEN"}]


async def _update_order(order_id: str, status: str, filled_qty: float | None, avg_price: float | None) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        payload = {"order_id": order_id, "status": status}
        if filled_qty is not None:
            payload["filled_qty"] = filled_qty
        if avg_price is not None:
            payload["avg_price"] = avg_price
        await client.post(f"{WORKER_URL}/orders/update", json=payload, headers=_auth_headers())


@router.post("/sync")
async def sync_orders() -> Dict[str, Any]:
    """Poll worker for NEW/PARTIAL orders and refresh status via Binance fetch_order."""
    client = _make_client()
    open_orders = await _fetch_open_orders()
    updated = 0
    errors: list[str] = []
    if not open_orders:
        return {"status": "ok", "updated": 0, "open_orders_checked": 0, "errors": errors}
    for o in open_orders:
        order_id = o.get("order_id") or o.get("id")
        symbol = o.get("pair") or o.get("symbol")
        if not order_id or not symbol:
            continue
        try:
            remote = client.fetch_order(id=order_id, symbol=symbol)
            info = remote.get("info") or {}
            status = (remote.get("status") or info.get("status") or "").upper()
            filled = remote.get("filled") or remote.get("amount") or None
            avg_price = remote.get("average") or None
            await _update_order(order_id=str(order_id), status=status, filled_qty=filled, avg_price=avg_price)
            updated += 1
        except Exception as exc:  # pragma: no cover - network
            errors.append(f"{order_id}: {exc}")
    return {"status": "ok", "updated": updated, "open_orders_checked": len(open_orders), "errors": errors}


__all__ = ["router"]
