#!/usr/bin/env python3
"""Simple Trading Monitor - แสดงผล logs แบบ stream (ไม่ clear screen)

Usage:
    python monitor_simple.py              # แสดงแบบสรุป
    python monitor_simple.py --details    # แสดงแบบละเอียด
"""

import asyncio
import httpx
import sys
from datetime import datetime
from typing import Dict, Any, List

CONTROL_PLANE_URL = "http://localhost:5001"


async def fetch_summary() -> Dict[str, Any]:
    """ดึงข้อมูล Summary"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONTROL_PLANE_URL}/bot/summary", timeout=5.0)
        resp.raise_for_status()
        return resp.json()


async def fetch_logs() -> List[Dict[str, Any]]:
    """ดึง Logs"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONTROL_PLANE_URL}/bot/scheduler/logs", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("logs", [])


def format_time(ts_str: str) -> str:
    """Format timestamp"""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except:
        return ts_str


def print_summary(summary: Dict[str, Any], logs: List[Dict[str, Any]] = []):
    """แสดง Summary"""
    mode = summary.get("mode", "UNKNOWN")
    positions = summary.get("positions", [])

    # หา Binance Balance จาก logs ล่าสุด
    binance_balance = 0.0
    for log in reversed(logs):
        if log.get("action") == "position_state" and "binance_balance" in log:
            binance_balance = log.get("binance_balance", 0.0)
            break

    print("\n" + "="*70)
    print(f"📊 Trading Summary - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70)

    print(f"🎯 โหมด: {mode}")
    print(f"💰 Binance Balance: {binance_balance:.8f} BTC")

    if positions:
        pos = positions[0]
        pair = pos.get("pair", "N/A")
        qty = pos.get("qty", 0)
        entry_price = pos.get("entry_price", 0)
        sl_price = pos.get("trailing_stop_price") or pos.get("sl_price", 0)
        trailing_on = pos.get("trailing_stop_activated", False)

        print(f"📍 คู่เงิน: {pair}")
        print(f"🔒 Position: {qty:.8f} BTC")
        print(f"💵 ราคาเข้า: {entry_price:,.2f} USDT")
        print(f"🛡️  Stop Loss: {sl_price:,.2f} USDT (Trailing: {'✅' if trailing_on else '❌'})")
    else:
        print("📍 สถานะ: FLAT (ไม่มี Position)")

    print("="*70)


def print_logs(logs: List[Dict[str, Any]], show_details: bool = False):
    """แสดง Logs"""
    print("\n🧩 Rule Check Log")
    print("-"*70)

    if not logs:
        print("ยังไม่มีการรัน")
        return

    # แสดง 10 logs ล่าสุด
    recent_logs = logs[-10:]

    for log in recent_logs:
        ts = format_time(log.get("ts", ""))
        pair = log.get("pair", "N/A")
        action = log.get("action", "")
        status = log.get("status", "")

        # Skip position_state
        if action == "position_state":
            continue

        prefix = f"[{ts}] 📍 [{pair}]"

        if action == "wait":
            if status == "no_entry_signal":
                # Entry Mode
                reason = log.get("reason", "")
                rules = log.get("rules", {})

                print(f"{prefix} สถานะ: FLAT | {reason}")

                if show_details and rules:
                    print(f"  🔽 CDC Transition | ⛔ Pattern: detected")
                    for rule_name, passed in rules.items():
                        emoji = "✅" if passed else "❌"
                        print(f"    {emoji} {rule_name}")

            elif status == "monitoring_exit":
                # Exit Mode
                exit_checks = log.get("exit_checks", {})
                current_price = log.get("current_price", 0)

                print(f"{prefix} รอซื้อ | ❌🟦➡️🟩 CDC Transition | ℹ️ ⛔ Pattern: detected")

                if show_details and exit_checks:
                    print(f"  🔽 Exit Checks:")
                    for check_name, value in exit_checks.items():
                        print(f"    🔍 {check_name}: {value}")

        elif action == "buy":
            entry_price = log.get("entry_price", 0)
            qty = log.get("qty", 0)
            print(f"{prefix} 🛒 ซื้อแล้ว! | ราคา: {entry_price:,.2f} | จำนวน: {qty:.4f}")

        elif action == "sell":
            exit_price = log.get("exit_price", 0)
            pnl_pct = log.get("pnl_pct", 0)
            reason = log.get("reason", "")
            print(f"{prefix} 💸 ขายแล้ว! | ราคา: {exit_price:,.2f} | PnL: {pnl_pct:+.2f}% | เหตุผล: {reason}")

        elif action == "error":
            error = log.get("error", "")
            print(f"{prefix} 💥 error: {error}")

    print("-"*70)


async def monitor_once(show_details: bool = False):
    """รันครั้งเดียว"""
    try:
        summary = await fetch_summary()
        logs = await fetch_logs()

        print_summary(summary, logs)  # ส่ง logs ด้วยเพื่อแสดง balance
        print_logs(logs, show_details=show_details)

    except Exception as e:
        print(f"❌ Error: {e}")


async def monitor_loop(show_details: bool = False, interval: int = 5):
    """รันแบบ loop"""
    print(f"🚀 กำลังเริ่ม Trading Monitor... (รีเฟรชทุก {interval} วินาที)")
    print("กด Ctrl+C เพื่อหยุด\n")

    try:
        while True:
            await monitor_once(show_details=show_details)
            print(f"\n⏰ รอ {interval} วินาที...\n")
            await asyncio.sleep(interval)
    except KeyboardInterrupt:
        print("\n\n👋 ปิดโปรแกรม\n")


async def main():
    """Entry point"""
    show_details = "--details" in sys.argv or "-d" in sys.argv
    watch_mode = "--watch" in sys.argv or "-w" in sys.argv

    if watch_mode:
        await monitor_loop(show_details=show_details)
    else:
        await monitor_once(show_details=show_details)


if __name__ == "__main__":
    asyncio.run(main())
