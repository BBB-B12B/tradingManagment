#!/usr/bin/env python3
"""Real-time Trading Monitor CLI

แสดงผล logs จาก Trading Scheduler แบบ Real-time พร้อม Toggle

Usage:
    python monitor.py
"""

import asyncio
import httpx
import os
from datetime import datetime
from typing import Dict, Any, List

# ANSI Colors
RESET = "\033[0m"
BOLD = "\033[1m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_DARK = "\033[40m"

# Emojis
EMOJI_CHART = "📊"
EMOJI_RULES = "🧩"
EMOJI_MONEY = "💰"
EMOJI_POSITION = "📍"
EMOJI_UP = "🟢"
EMOJI_DOWN = "🔴"
EMOJI_WAIT = "⏸️"
EMOJI_BUY = "🛒"
EMOJI_SELL = "💸"
EMOJI_ERROR = "💥"
EMOJI_INFO = "ℹ️"
EMOJI_TOGGLE = "🔽"

CONTROL_PLANE_URL = os.getenv("CONTROL_PLANE_URL", "http://localhost:5001")


async def fetch_summary() -> Dict[str, Any]:
    """ดึงข้อมูล Summary (Balance, Position, Mode)"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONTROL_PLANE_URL}/bot/summary", timeout=5.0)
        resp.raise_for_status()
        return resp.json()


async def fetch_logs() -> List[Dict[str, Any]]:
    """ดึง Logs จาก Scheduler"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONTROL_PLANE_URL}/bot/scheduler/logs", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        return data.get("logs", [])


def format_timestamp(ts_str: str) -> str:
    """แปลง ISO timestamp เป็น Thai time"""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        # Convert to Bangkok time (UTC+7)
        bangkok_dt = dt.replace(tzinfo=None)  # Simplified
        return bangkok_dt.strftime("%H:%M:%S")
    except:
        return ts_str


def print_header(summary: Dict[str, Any]):
    """แสดง Header พร้อม Balance และ Position"""
    mode = summary.get("mode", "UNKNOWN")
    active_positions = summary.get("active_positions", 0)
    positions = summary.get("positions", [])

    # Title
    print(f"\n{BG_DARK}{BOLD}{WHITE}  {EMOJI_CHART} Trading Monitor - Real-time  {RESET}")
    print(f"{BG_DARK}{WHITE}{'─' * 60}{RESET}\n")

    # Mode
    mode_color = GREEN if mode == "EXIT" else CYAN
    mode_emoji = EMOJI_POSITION if mode == "EXIT" else EMOJI_WAIT
    print(f"{BOLD}{mode_emoji} โหมด: {mode_color}{mode}{RESET}")

    # Positions
    if active_positions > 0 and positions:
        pos = positions[0]  # แสดง position แรก
        pair = pos.get("pair", "N/A")
        qty = pos.get("qty", 0)
        entry_price = pos.get("entry_price", 0)
        current_sl = pos.get("trailing_stop_price") or pos.get("sl_price", 0)
        trailing_activated = pos.get("trailing_stop_activated", False)

        print(f"{BOLD}{EMOJI_MONEY} คู่เงิน: {YELLOW}{pair}{RESET}")
        print(f"{BOLD}💎 จำนวน: {GREEN}{qty:.4f}{RESET} BTC")
        print(f"{BOLD}💵 ราคาเข้า: {WHITE}{entry_price:,.2f}{RESET} USDT")
        print(f"{BOLD}🛡️  Stop Loss: {RED}{current_sl:,.2f}{RESET} USDT {CYAN}(Trailing: {'✅' if trailing_activated else '❌'}){RESET}")
    else:
        print(f"{BOLD}{EMOJI_INFO} สถานะ: {YELLOW}FLAT{RESET} (ไม่มี Position)")

    print(f"\n{WHITE}{'─' * 60}{RESET}")


def print_rule_check_log(logs: List[Dict[str, Any]], show_details: bool = False):
    """แสดง Rule Check Log"""
    print(f"\n{BOLD}{EMOJI_RULES} Rule Check Log{RESET}")
    print(f"{BG_DARK}{WHITE}{'─' * 60}{RESET}\n")

    if not logs:
        print(f"{YELLOW}ยังไม่มีการรัน{RESET}")
        return

    # แสดง 5 logs ล่าสุด
    recent_logs = logs[-5:]

    for log in recent_logs:
        ts = format_timestamp(log.get("ts", ""))
        pair = log.get("pair", "N/A")
        action = log.get("action", "unknown")
        status = log.get("status", "unknown")

        # Skip position_state logs
        if action == "position_state":
            continue

        # Time prefix
        time_str = f"[{CYAN}{ts}{RESET}]"

        if action == "wait":
            if status == "no_entry_signal":
                # Entry Mode
                reason = log.get("reason", "")
                rules = log.get("rules", {})

                print(f"{time_str} {EMOJI_WAIT} {pair} รอซื้อ | {reason}")

                if show_details and rules:
                    print(f"  {EMOJI_TOGGLE} Rules:")
                    for rule_name, passed in rules.items():
                        emoji = "✅" if passed else "❌"
                        print(f"    {emoji} {rule_name}: {passed}")
                    print()

            elif status == "monitoring_exit":
                # Exit Mode
                exit_checks = log.get("exit_checks", {})
                current_price = log.get("current_price", 0)

                print(f"{time_str} {EMOJI_POSITION} {pair} ถือ Position | ราคาปัจจุบัน: {current_price:,.2f}")

                if show_details and exit_checks:
                    print(f"  {EMOJI_TOGGLE} Exit Checks:")
                    for check_name, value in exit_checks.items():
                        print(f"    🔍 {check_name}: {value}")
                    print()

        elif action == "buy":
            entry_price = log.get("entry_price", 0)
            qty = log.get("qty", 0)
            print(f"{time_str} {EMOJI_BUY} {pair} ซื้อแล้ว! | ราคา: {entry_price:,.2f} | จำนวน: {qty:.4f}")

        elif action == "sell":
            exit_price = log.get("exit_price", 0)
            pnl_pct = log.get("pnl_pct", 0)
            reason = log.get("reason", "")
            pnl_color = GREEN if pnl_pct >= 0 else RED
            print(f"{time_str} {EMOJI_SELL} {pair} ขายแล้ว! | ราคา: {exit_price:,.2f} | PnL: {pnl_color}{pnl_pct:+.2f}%{RESET} | เหตุผล: {reason}")

        elif action == "error":
            error = log.get("error", "Unknown error")
            print(f"{time_str} {EMOJI_ERROR} {pair} error: {RED}{error}{RESET}")


async def monitor_loop(show_details: bool = False):
    """Main monitoring loop"""
    while True:
        try:
            # Clear screen
            os.system('clear' if os.name != 'nt' else 'cls')

            # Fetch data
            summary = await fetch_summary()
            logs = await fetch_logs()

            # Display
            print_header(summary)
            print_rule_check_log(logs, show_details=show_details)

            # Footer
            print(f"\n{WHITE}{'─' * 60}{RESET}")
            print(f"{BOLD}กด Ctrl+C เพื่อออก | รีเฟรชทุก 3 วินาที{RESET}")
            if not show_details:
                print(f"{YELLOW}💡 Tip: เพิ่ม --details เพื่อดูข้อมูลละเอียด{RESET}")

            # Wait
            await asyncio.sleep(3)

        except KeyboardInterrupt:
            print(f"\n\n{GREEN}👋 ปิดโปรแกรม{RESET}\n")
            break
        except Exception as e:
            print(f"\n{RED}{EMOJI_ERROR} Error: {e}{RESET}")
            await asyncio.sleep(5)


async def main():
    """Entry point"""
    import sys
    show_details = "--details" in sys.argv or "-d" in sys.argv

    print(f"{BOLD}{CYAN}🚀 กำลังเริ่มต้น Trading Monitor...{RESET}\n")
    await asyncio.sleep(1)

    await monitor_loop(show_details=show_details)


if __name__ == "__main__":
    asyncio.run(main())
