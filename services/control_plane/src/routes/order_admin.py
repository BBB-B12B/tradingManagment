"""Admin/utility endpoints for order management (cancel, list open)."""

from __future__ import annotations

import os
from typing import Dict, Any

import ccxt
from fastapi import APIRouter, HTTPException
import httpx

from trading.order_sync import sync_orders_from_binance, sync_pending_orders

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


@router.post("/migrate-new-to-canceled")
async def migrate_new_status_to_canceled() -> Dict[str, Any]:
    """อัปเดต Orders ทั้งหมดที่มี status NEW เป็น CANCELED

    ใช้สำหรับ migration จาก status เก่า (NEW) ไปใหม่ (PENDING/CANCELED)
    """
    # ดึง Orders ทั้งหมดจาก Worker
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.get(f"{WORKER_URL}/orders", headers=_auth_headers())
        resp.raise_for_status()
        data = resp.json()
        orders = data.get("orders", [])

    # กรอง Orders ที่มี status = NEW
    new_orders = [
        o for o in orders
        if (o.get("status") or "").upper() == "NEW"
    ]

    if not new_orders:
        return {
            "status": "ok",
            "message": "ไม่มี NEW Orders ที่ต้อง migrate",
            "migrated_count": 0,
        }

    # อัปเดตทุก Order เป็น CANCELED
    migrated = []
    errors = []

    async with httpx.AsyncClient(timeout=10.0) as http:
        for order in new_orders:
            order_id = order.get("order_id")

            try:
                # Update status เป็น CANCELED
                await http.post(
                    f"{WORKER_URL}/orders/update",
                    json={"order_id": order_id, "status": "CANCELED"},
                    headers=_auth_headers(),
                )
                migrated.append(order_id)
            except Exception as e:
                errors.append({"order_id": order_id, "error": str(e)})

    return {
        "status": "ok",
        "message": f"Migrate {len(migrated)} Orders จาก NEW → CANCELED",
        "migrated_count": len(migrated),
        "migrated_orders": migrated,
        "errors": errors,
    }


@router.post("/cancel-all-pending")
async def cancel_all_pending_orders(pair: str = None) -> Dict[str, Any]:
    """ยกเลิก Order ทั้งหมดที่ PENDING (ยังไม่ FILLED)

    Args:
        pair: ถ้าระบุจะยกเลิกเฉพาะคู่นั้น ถ้าไม่ระบุจะยกเลิกทุกคู่

    Returns:
        จำนวน Order ที่ยกเลิก
    """
    # ดึง Orders ทั้งหมดจาก Worker
    async with httpx.AsyncClient(timeout=10.0) as http:
        resp = await http.get(f"{WORKER_URL}/orders", headers=_auth_headers())
        resp.raise_for_status()
        data = resp.json()
        orders = data.get("orders", [])

    # กรอง Orders ที่ PENDING
    pending_orders = [
        o for o in orders
        if (o.get("status") or "").upper() == "PENDING"
        and (not pair or (o.get("pair") or "").upper() == pair.upper())
    ]

    if not pending_orders:
        return {
            "status": "ok",
            "message": "ไม่มี PENDING Orders",
            "canceled_count": 0,
        }

    # ยกเลิกทุก Order
    canceled = []
    errors = []

    async with httpx.AsyncClient(timeout=10.0) as http:
        for order in pending_orders:
            order_id = order.get("order_id")
            order_pair = order.get("pair")

            try:
                # Update status เป็น CANCELED ใน Worker
                await http.post(
                    f"{WORKER_URL}/orders/update",
                    json={"order_id": order_id, "status": "CANCELED"},
                    headers=_auth_headers(),
                )
                canceled.append(order_id)
            except Exception as e:
                errors.append({"order_id": order_id, "error": str(e)})

    return {
        "status": "ok",
        "message": f"ยกเลิก {len(canceled)} Orders",
        "canceled_count": len(canceled),
        "canceled_orders": canceled,
        "errors": errors,
    }


@router.post("/test-binance-order")
async def test_binance_order(
    pair: str,
    side: str = "buy",
    amount: float = 0.001,
    order_type: str = "market"
) -> Dict[str, Any]:
    """ทดสอบการส่ง Order จริงไปที่ Binance Testnet

    Args:
        pair: คู่เงิน เช่น BTC/USDT
        side: buy หรือ sell
        amount: จำนวนที่ต้องการซื้อ/ขาย (base currency)
        order_type: market หรือ limit (ถ้า limit จะใช้ราคาตลาดปัจจุบัน)

    Returns:
        ข้อมูล Order จาก Binance และสถานะการบันทึกใน D1

    ⚠️ Endpoint นี้จะส่ง Order จริงไปที่ Binance Testnet!
    """
    client = _make_client()

    try:
        # 1. เช็ค Balance ก่อนส่ง Order
        symbol = pair.replace("/", "")  # BTC/USDT → BTCUSDT
        base, quote = pair.split("/")

        balance = client.fetch_balance()
        base_free = balance.get(base, {}).get("free", 0.0)
        quote_free = balance.get(quote, {}).get("free", 0.0)

        # 2. Adjust amount to exchange precision
        amount = float(client.amount_to_precision(symbol, amount))

        # 3. เช็ค Balance เพียงพอหรือไม่
        if side.lower() == "buy":
            # ต้องการ USDT
            current_price = client.fetch_ticker(symbol)["last"]
            required = current_price * amount
            if quote_free < required:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient {quote}: need {required:.2f}, have {quote_free:.2f}"
                )
        else:
            # ต้องการ Base Asset (BTC)
            if base_free < amount:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient {base}: need {amount:.8f}, have {base_free:.8f}"
                )

        # 4. Place Order ที่ Binance Testnet
        binance_order = client.create_order(
            symbol=symbol,
            type=order_type,
            side=side.lower(),
            amount=amount,
        )

        # 5. ดึงข้อมูล Order
        info = binance_order.get("info", {})
        order_id = str(info.get("orderId") or binance_order.get("id"))
        status = info.get("status", "UNKNOWN")
        filled_qty = float(info.get("executedQty") or 0)

        # คำนวณ avg_price
        avg_price = None
        try:
            cumm_quote = float(info.get("cummulativeQuoteQty") or 0)
            if filled_qty > 0 and cumm_quote > 0:
                avg_price = cumm_quote / filled_qty
        except Exception:
            pass

        # 6. บันทึกลง D1 Worker
        worker_status = "FILLED" if status == "FILLED" else "PENDING"

        order_payload = {
            "pair": pair,
            "order_type": "ENTRY" if side.lower() == "buy" else "EXIT",
            "side": side.upper(),
            "requested_qty": amount,
            "filled_qty": filled_qty,
            "avg_price": avg_price or binance_order.get("price", 0),
            "order_id": order_id,
            "status": worker_status,
            "entry_reason": "TEST_ENDPOINT",
            "exit_reason": None if side.lower() == "buy" else "TEST_ENDPOINT",
            "rule_1_cdc_green": False,
            "rule_2_leading_red": False,
            "rule_3_leading_signal": False,
            "rule_4_pattern": False,
            "requested_at": info.get("transactTime"),
            "filled_at": info.get("transactTime") if worker_status == "FILLED" else None,
        }

        async with httpx.AsyncClient(timeout=10.0) as http:
            await http.post(
                f"{WORKER_URL}/orders",
                json=order_payload,
                headers=_auth_headers(),
            )

        # 7. ตรวจสอบ Balance หลังส่ง Order
        balance_after = client.fetch_balance()
        base_after = balance_after.get(base, {}).get("free", 0.0)
        quote_after = balance_after.get(quote, {}).get("free", 0.0)

        return {
            "status": "ok",
            "message": f"✅ Order {side.upper()} placed successfully on Binance Testnet",
            "binance_order_id": order_id,
            "binance_status": status,
            "symbol": symbol,
            "side": side.upper(),
            "amount": amount,
            "filled_qty": filled_qty,
            "avg_price": avg_price,
            "balance_before": {base: base_free, quote: quote_free},
            "balance_after": {base: base_after, quote: quote_after},
            "binance_response": info,
        }

    except ccxt.InsufficientFunds as exc:
        raise HTTPException(status_code=400, detail=f"Insufficient funds: {exc}") from exc
    except ccxt.BaseError as exc:
        raise HTTPException(status_code=502, detail=f"Binance error: {exc}") from exc


@router.post("/sync-from-binance")
async def sync_orders_from_binance_endpoint(
    pair: str = "BTC/USDT",
    lookback_hours: int = 24
) -> Dict[str, Any]:
    """Sync Orders จาก Binance → D1

    ดึง Orders จาก Binance (ย้อนหลัง 24 ชม.)
    เช็คว่า Order ไหนยังไม่มีใน D1 → บันทึกเพิ่ม
    Update Status ของ PENDING Orders

    Args:
        pair: คู่เงิน เช่น BTC/USDT
        lookback_hours: ดึง Orders ย้อนหลังกี่ชั่วโมง (default: 24)

    Returns:
        จำนวน Orders ที่เพิ่มและ Update
    """
    try:
        result = await sync_orders_from_binance(pair=pair, lookback_hours=lookback_hours)
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}") from exc


@router.post("/sync-pending")
async def sync_pending_orders_endpoint() -> Dict[str, Any]:
    """Sync เฉพาะ PENDING Orders จาก D1 → Binance

    ดึง Orders ที่มี Status = PENDING จาก D1
    Query Status จาก Binance
    Update Status เมื่อเปลี่ยน (FILLED/CANCELED)

    Returns:
        จำนวน Orders ที่ Update Status
    """
    try:
        result = await sync_pending_orders()
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}") from exc


__all__ = ["router"]
