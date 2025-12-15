"""Trading Scheduler - ตรวจสอบเงื่อนไขทุก 1 นาทีแบบ Real-time

This module implements a background scheduler that checks trading signals
every N minutes for configured trading pairs.

ใช้งาน:
    scheduler = TradingScheduler()
    await scheduler.start(pairs=["BTC/USDT"], interval_minutes=1)
    # ... รอ ...
    await scheduler.stop()
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional
from collections import deque
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from trading.realtime_engine import RealtimeTradingEngine
import ccxt.async_support as ccxt
import os
from pathlib import Path


# โหลด .env file ถ้ามี
def _load_env_once():
    """โหลด environment variables จาก .env.dev"""
    project_root = Path(__file__).parent.parent.parent.parent
    env_path = project_root / ".env" / ".env.dev"

    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


_load_env_once()


class TradingScheduler:
    """Background Scheduler สำหรับตรวจสอบ Trading Signals แบบ Real-time"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.pairs: List[str] = []
        self.interval_minutes: float = 1.0
        self.logs = deque(maxlen=200)  # buffer สำหรับ UI log
        self.binance_client: Optional[ccxt.binance] = None

    def _record_log(self, entry: dict):
        """เก็บ log ลง buffer (ts=UTC)"""
        self.logs.append({**entry, "ts": datetime.utcnow().isoformat()})

    async def _get_binance_balance(self, asset: str = "BTC") -> float:
        """ดึง Balance จาก Binance Testnet"""
        try:
            if not self.binance_client:
                api_key = os.getenv("BINANCE_API_KEY", "")
                api_secret = os.getenv("BINANCE_API_SECRET", "")

                if not api_key or not api_secret:
                    return 0.0

                self.binance_client = ccxt.binance({
                    'apiKey': api_key,
                    'secret': api_secret,
                    'enableRateLimit': True,
                    'options': {
                        'defaultType': 'spot',
                        'recvWindow': 10000,  # Allow 10s timestamp difference
                    },
                })
                self.binance_client.set_sandbox_mode(True)
                # Sync with server time
                await self.binance_client.load_time_difference()

            balance = await self.binance_client.fetch_balance(params={'recvWindow': 10000})
            return float(balance.get('free', {}).get(asset, 0))
        except Exception as e:
            print(f"[Scheduler] Error fetching balance: {e}")
            return 0.0

    async def _check_all_pairs(self):
        """ตรวจสอบทุกคู่เงิน (เรียกโดย Scheduler)"""
        results = []

        for pair in self.pairs:
            try:
                engine = RealtimeTradingEngine(pair=pair)
                result = await engine.run()
                results.append({
                    "pair": pair,
                    "status": "success",
                    "result": result
                })

                # แสดงผลลัพธ์แบบละเอียด
                action = result.get("action", "unknown")
                status = result.get("status", "unknown")
                position = result.get("position", {})
                qty_display = float(position.get("qty") or 0)

                # ดึง Binance Balance (สำหรับ BTC/USDT)
                btc_balance = 0.0
                if "BTC" in pair.upper():
                    btc_balance = await self._get_binance_balance("BTC")

                # บันทึก Position State Log ก่อนทุกครั้ง (พร้อม Binance Balance)
                self._record_log({
                    "pair": pair,
                    "action": "position_state",
                    "status": position.get("status", "FLAT"),
                    "position": position,
                    "binance_balance": btc_balance,  # เพิ่ม balance จริง
                })

                if action == "buy":
                    # Entry Signal
                    entry_price = result.get('entry_price', 0)
                    sl_price = result.get('sl_price', 0)
                    qty = result.get('quantity', 0)
                    rules = result.get('rules', {})
                    order_info = result.get('order', {})

                    self._record_log({
                        "pair": pair,
                        "action": "buy",
                        "status": status,
                        "entry_price": entry_price,
                        "sl_price": sl_price,
                        "qty": qty,
                        "rules": rules,
                        "rules_detail": result.get("rules_detail"),
                        "position": position,
                        "binance_order_id": order_info.get("order_id"),
                        "binance_status": order_info.get("binance_status"),
                        "filled_qty": order_info.get("filled_qty"),
                        "avg_price": order_info.get("avg_price"),
                    })

                elif action == "sell":
                    # Exit Signal
                    reason = result.get("reason", "unknown")
                    exit_price = result.get("exit_price", 0)
                    pnl_pct = result.get("pnl_pct", 0)
                    order_info = result.get('order', {})

                    self._record_log({
                        "pair": pair,
                        "action": "sell",
                        "status": status,
                        "reason": reason,
                        "exit_price": exit_price,
                        "pnl_pct": pnl_pct,
                        "position": position,
                        "binance_order_id": order_info.get("order_id"),
                        "binance_status": order_info.get("binance_status"),
                        "filled_qty": order_info.get("filled_qty"),
                        "avg_price": order_info.get("avg_price"),
                    })

                elif action == "wait":
                    # No Signal - บันทึก log สำหรับ UI
                    if status == "no_entry_signal" and "rules" in result:
                        # Entry Mode: แสดง Rules
                        rules = result["rules"]
                        self._record_log({
                            "pair": pair,
                            "action": "wait",
                            "status": status,
                            "reason": result.get("reason", status),
                            "rules": rules,
                            "rules_detail": result.get("rules_detail"),
                            "position": position,
                        })
                    elif status == "holding" and "exit_checks" in result:
                        # Exit Mode: แสดง Exit Checks
                        self._record_log({
                            "pair": pair,
                            "action": "wait",
                            "status": "monitoring_exit",
                            "reason": "Holding position - monitoring exit conditions",
                            "exit_checks": result.get("exit_checks"),
                            "position": position,
                            "current_price": result.get("current_price"),
                            "sl_distance": result.get("sl_distance"),
                        })

            except Exception as e:
                self._record_log({
                    "pair": pair,
                    "action": "error",
                    "status": "error",
                    "error": str(e),
                })
                results.append({
                    "pair": pair,
                    "status": "error",
                    "error": str(e)
                })

        return results

    async def start(self, pairs: List[str], interval_minutes: float = 1.0):
        """เริ่ม Scheduler

        Args:
            pairs: รายการคู่เงินที่ต้องการเทรด เช่น ["BTC/USDT", "ETH/USDT"]
            interval_minutes: ตรวจสอบทุกกี่นาที (default: 1)
        """
        if self.is_running:
            print("⚠️  Scheduler already running in this instance - stopping first...")
            await self.stop()

        self.pairs = pairs
        self.interval_minutes = float(interval_minutes)

        # ลบ jobs เก่าทั้งหมดก่อนเพิ่มใหม่ (ป้องกันการทำงานซ้ำจาก reload)
        for job in self.scheduler.get_jobs():
            self.scheduler.remove_job(job.id)
            print(f"🗑️  Removed old job: {job.id}")

        # เพิ่ม Job เข้า Scheduler
        job_id = f"trading_check_{interval_minutes}m"
        self.scheduler.add_job(
            self._check_all_pairs,
            trigger=IntervalTrigger(seconds=self.interval_minutes * 60),
            id=job_id,
            replace_existing=True,
            max_instances=1,  # ป้องกันการทำงานซ้ำซ้อน
        )
        print(f"✅ Added new job: {job_id}")

        if not self.scheduler.running:
            self.scheduler.start()
        self.is_running = True

        # บันทึก Scheduler Start Log
        self._record_log({
            "pair": ", ".join(pairs),
            "action": "scheduler_start",
            "status": "started",
            "interval_minutes": interval_minutes,
        })

        # รันทันทีครั้งแรก (ไม่รอ interval)
        await self._check_all_pairs()

    async def stop(self):
        """หยุด Scheduler"""
        if not self.is_running:
            return

        self.scheduler.shutdown(wait=True)
        self.is_running = False

    def get_status(self) -> dict:
        """ดูสถานะ Scheduler

        Returns:
            Dict with scheduler status
        """
        jobs = self.scheduler.get_jobs() if self.is_running else []

        return {
            "is_running": self.is_running,
            "pairs": self.pairs,
            "interval_minutes": self.interval_minutes,
            "jobs": [
                {
                    "id": job.id,
                    "next_run": str(job.next_run_time) if job.next_run_time else None,
                }
                for job in jobs
            ],
        }

    def get_logs(self) -> List[dict]:
        """คืนค่า log buffer สำหรับ UI"""
        return list(self.logs)


__all__ = ["TradingScheduler"]
