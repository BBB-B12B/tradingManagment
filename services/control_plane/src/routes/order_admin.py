"""Admin/utility endpoints for order management (cancel, list open)."""

from __future__ import annotations

import os
from typing import Dict, Any

import ccxt
from fastapi import APIRouter, HTTPException
import httpx

router = APIRouter(prefix="/orders", tags=["orders-admin"])

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
    client.set_sandbox_mode(True)
    return client


@router.post("/cancel")
async def cancel_order(pair: str, order_id: str) -> Dict[str, Any]:
    """Cancel a Binance order and update D1 via worker."""
    client = _make_client()
    try:
        result = client.cancel_order(id=order_id, symbol=pair)
    except ccxt.BaseError as exc:
        raise HTTPException(status_code=502, detail=f"Binance cancel failed: {exc}") from exc

    # Update worker status to CANCELED
    async with httpx.AsyncClient(timeout=10.0) as http:
        await http.post(
            f"{WORKER_URL}/orders/update",
            json={"order_id": order_id, "status": "CANCELED"},
            headers=_auth_headers(),
        )

    return {"status": "ok", "order_id": order_id, "pair": pair, "binance": result}


__all__ = ["router"]
