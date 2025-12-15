"""Order Sync Service - Sync Orders ระหว่าง Binance และ D1

ฟังก์ชันหลัก:
1. ดึง Orders จาก Binance ที่ยังไม่มีใน D1 → บันทึกเพิ่ม
2. Update Status ของ PENDING Orders จาก Binance
3. ไม่ Update Orders ที่มี Status สุดท้ายแล้ว (FILLED/CLOSED/CANCELED)
"""

from __future__ import annotations

import os
from typing import Dict, Any, List
from datetime import datetime, timedelta

import ccxt
import httpx


# Environment Variables
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
WORKER_URL = os.getenv("CLOUDFLARE_WORKER_URL", "http://localhost:8787")
WORKER_TOKEN = os.getenv("CLOUDFLARE_WORKER_API_TOKEN", "")


def _auth_headers() -> Dict[str, str]:
    """Headers สำหรับเรียก Worker API"""
    return {"Authorization": f"Bearer {WORKER_TOKEN}"} if WORKER_TOKEN else {}


def _make_binance_client() -> ccxt.binance:
    """สร้าง Binance Client สำหรับ Testnet"""
    if not BINANCE_API_KEY or not BINANCE_API_SECRET:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET")

    client = ccxt.binance({
        "apiKey": BINANCE_API_KEY,
        "secret": BINANCE_API_SECRET,
        "options": {"defaultType": "spot"},
    })
    client.set_sandbox_mode(True)  # Use Testnet
    return client


async def sync_orders_from_binance(
    pair: str = "BTC/USDT",
    lookback_hours: int = 24
) -> Dict[str, Any]:
    """Sync Orders จาก Binance → D1

    Args:
        pair: คู่เงิน เช่น BTC/USDT
        lookback_hours: ดึง Orders ย้อนหลังกี่ชั่วโมง (default: 24)

    Returns:
        Dict with:
        - new_orders_count: จำนวน Orders ใหม่ที่เพิ่มเข้า D1
        - updated_orders_count: จำนวน Orders ที่ Update Status
        - new_orders: รายการ Order IDs ที่เพิ่มใหม่
        - updated_orders: รายการ Order IDs ที่ Update

    Flow:
    1. ดึง Orders จาก Binance (ย้อนหลัง 24 ชม.)
    2. ดึง Orders จาก D1
    3. เช็คว่า Order ไหนยังไม่มีใน D1 → บันทึกเพิ่ม
    4. เช็คว่า Order ไหนมี Status = PENDING → Update Status
    """

    binance_client = _make_binance_client()
    symbol = pair.replace("/", "")  # BTC/USDT → BTCUSDT

    # 1. ดึง Orders จาก Binance (24 ชั่วโมงล่าสุด)
    since_timestamp = int((datetime.utcnow() - timedelta(hours=lookback_hours)).timestamp() * 1000)

    try:
        binance_orders = binance_client.fetch_orders(
            symbol=symbol,
            since=since_timestamp,
            limit=500
        )
    except ccxt.BaseError as exc:
        raise RuntimeError(f"Failed to fetch orders from Binance: {exc}") from exc

    # 2. ดึง Orders จาก D1
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(
            f"{WORKER_URL}/orders",
            headers=_auth_headers(),
            params={"pair": pair}
        )
        resp.raise_for_status()
        d1_data = resp.json()
        d1_orders = d1_data.get("orders", [])

    # สร้าง Map ของ Order IDs ที่มีใน D1
    d1_order_ids = {str(o.get("order_id")) for o in d1_orders}
    d1_orders_by_id = {str(o.get("order_id")): o for o in d1_orders}

    new_orders = []
    updated_orders = []

    # 3. Loop ผ่าน Orders จาก Binance
    async with httpx.AsyncClient(timeout=30.0) as http:
        for binance_order in binance_orders:
            info = binance_order.get("info", {})
            order_id = str(info.get("orderId") or binance_order.get("id"))
            binance_status = info.get("status", "UNKNOWN")
            side = info.get("side", "").upper()  # BUY or SELL
            filled_qty = float(info.get("executedQty") or 0)
            requested_qty = float(info.get("origQty") or filled_qty)

            # คำนวณ avg_price
            avg_price = None
            try:
                cumm_quote = float(info.get("cummulativeQuoteQty") or 0)
                if filled_qty > 0 and cumm_quote > 0:
                    avg_price = cumm_quote / filled_qty
            except Exception:
                pass

            # Map Binance Status → D1 Status
            if binance_status == "FILLED":
                d1_status = "FILLED"
            elif binance_status in ["NEW", "PARTIALLY_FILLED"]:
                d1_status = "PENDING"
            elif binance_status in ["CANCELED", "EXPIRED", "REJECTED"]:
                d1_status = "CANCELED"
            else:
                d1_status = "PENDING"

            # Case 1: Order ยังไม่มีใน D1 → บันทึกเพิ่ม
            if order_id not in d1_order_ids:
                # เฉพาะ fields ที่ไม่เป็น None/undefined
                order_payload = {
                    "pair": pair,
                    "order_type": "ENTRY" if side == "BUY" else "EXIT",
                    "side": side,
                    "requested_qty": requested_qty,
                    "filled_qty": filled_qty,
                    "avg_price": avg_price or 0,
                    "order_id": order_id,
                    "status": d1_status,
                    "entry_reason": "BINANCE_SYNC",
                    "exit_reason": "BINANCE_SYNC" if side == "SELL" else None,
                    "rule_1_cdc_green": False,
                    "rule_2_leading_red": False,
                    "rule_3_leading_signal": False,
                    "rule_4_pattern": False,
                    "requested_at": info.get("time") or int(datetime.utcnow().timestamp() * 1000),
                    "filled_at": info.get("updateTime") if d1_status == "FILLED" else None,
                }

                await http.post(
                    f"{WORKER_URL}/orders",
                    json=order_payload,
                    headers=_auth_headers(),
                )
                new_orders.append(order_id)

            # Case 2: Order มีใน D1 และมี Status = PENDING → Update Status
            elif order_id in d1_orders_by_id:
                d1_order = d1_orders_by_id[order_id]
                current_d1_status = (d1_order.get("status") or "").upper()

                # ถ้า D1 Status = PENDING และ Binance Status เปลี่ยน → Update
                if current_d1_status == "PENDING" and d1_status != "PENDING":
                    update_payload = {
                        "order_id": order_id,
                        "status": d1_status,
                        "filled_qty": filled_qty,
                    }

                    # เพิ่ม optional fields เฉพาะถ้ามีค่า
                    if avg_price is not None:
                        update_payload["avg_price"] = avg_price

                    if d1_status == "FILLED" and info.get("updateTime"):
                        update_payload["filled_at"] = info.get("updateTime")

                    await http.post(
                        f"{WORKER_URL}/orders/update",
                        json=update_payload,
                        headers=_auth_headers(),
                    )
                    updated_orders.append(order_id)

    return {
        "status": "ok",
        "pair": pair,
        "lookback_hours": lookback_hours,
        "binance_orders_count": len(binance_orders),
        "d1_orders_count": len(d1_orders),
        "new_orders_count": len(new_orders),
        "updated_orders_count": len(updated_orders),
        "new_orders": new_orders,
        "updated_orders": updated_orders,
    }


async def sync_pending_orders() -> Dict[str, Any]:
    """Sync เฉพาะ PENDING Orders จาก D1 → Binance

    ดึง Orders ที่มี Status = PENDING จาก D1
    Query Status จาก Binance
    Update Status เมื่อเปลี่ยน

    Returns:
        Dict with updated_orders_count และ updated_orders
    """

    binance_client = _make_binance_client()

    # 1. ดึง Orders ที่มี Status = PENDING จาก D1
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(
            f"{WORKER_URL}/orders",
            headers=_auth_headers(),
        )
        resp.raise_for_status()
        d1_data = resp.json()
        d1_orders = d1_data.get("orders", [])

    pending_orders = [
        o for o in d1_orders
        if (o.get("status") or "").upper() == "PENDING"
    ]

    if not pending_orders:
        return {
            "status": "ok",
            "message": "ไม่มี PENDING Orders ที่ต้อง Sync",
            "updated_orders_count": 0,
            "updated_orders": [],
        }

    updated_orders = []

    # 2. Loop ผ่าน PENDING Orders และ Query จาก Binance
    async with httpx.AsyncClient(timeout=30.0) as http:
        for d1_order in pending_orders:
            order_id = str(d1_order.get("order_id"))
            pair = d1_order.get("pair")
            symbol = pair.replace("/", "")  # BTC/USDT → BTCUSDT

            try:
                # Query Order จาก Binance
                binance_order = binance_client.fetch_order(id=order_id, symbol=symbol)
                info = binance_order.get("info", {})
                binance_status = info.get("status", "UNKNOWN")
                filled_qty = float(info.get("executedQty") or 0)

                # คำนวณ avg_price
                avg_price = None
                try:
                    cumm_quote = float(info.get("cummulativeQuoteQty") or 0)
                    if filled_qty > 0 and cumm_quote > 0:
                        avg_price = cumm_quote / filled_qty
                except Exception:
                    pass

                # Map Binance Status → D1 Status
                if binance_status == "FILLED":
                    d1_status = "FILLED"
                elif binance_status in ["CANCELED", "EXPIRED", "REJECTED"]:
                    d1_status = "CANCELED"
                elif binance_status == "PARTIALLY_FILLED":
                    d1_status = "PENDING"  # ยังไม่เต็ม
                else:
                    continue  # ยังคง PENDING อยู่ ไม่ต้อง Update

                # Update D1 ถ้า Status เปลี่ยน
                if d1_status != "PENDING":
                    update_payload = {
                        "order_id": order_id,
                        "status": d1_status,
                        "filled_qty": filled_qty,
                    }

                    # เพิ่ม optional fields เฉพาะถ้ามีค่า
                    if avg_price is not None:
                        update_payload["avg_price"] = avg_price

                    if d1_status == "FILLED" and info.get("updateTime"):
                        update_payload["filled_at"] = info.get("updateTime")

                    await http.post(
                        f"{WORKER_URL}/orders/update",
                        json=update_payload,
                        headers=_auth_headers(),
                    )
                    updated_orders.append(order_id)

            except ccxt.OrderNotFound:
                # Order ไม่มีที่ Binance → Mark เป็น CANCELED
                await http.post(
                    f"{WORKER_URL}/orders/update",
                    json={"order_id": order_id, "status": "CANCELED"},
                    headers=_auth_headers(),
                )
                updated_orders.append(order_id)
            except Exception as exc:
                # Skip errors แต่ log ไว้
                print(f"Error syncing order {order_id}: {exc}")
                continue

    return {
        "status": "ok",
        "message": f"Sync {len(updated_orders)} PENDING Orders",
        "pending_orders_count": len(pending_orders),
        "updated_orders_count": len(updated_orders),
        "updated_orders": updated_orders,
    }


__all__ = ["sync_orders_from_binance", "sync_pending_orders"]
