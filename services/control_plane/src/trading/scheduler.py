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
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from trading.realtime_engine import RealtimeTradingEngine


class TradingScheduler:
    """Background Scheduler สำหรับตรวจสอบ Trading Signals แบบ Real-time"""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.pairs: List[str] = []
        self.interval_minutes = 1

    async def _check_all_pairs(self):
        """ตรวจสอบทุกคู่เงิน (เรียกโดย Scheduler)"""
        print(f"\n{'='*60}")
        print(f"[{datetime.now()}] 🔍 กำลังตรวจสอบสัญญาณเทรด...")
        print(f"คู่เงิน: {', '.join(self.pairs)}")
        print(f"{'='*60}\n")

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

                print(f"\n📊 [{pair}] สถานะ: {position.get('status', 'FLAT')} | จำนวน: {position.get('qty', 0):.4f}")

                if action == "buy":
                    # Entry Signal
                    entry_price = result.get('entry_price', 0)
                    sl_price = result.get('sl_price', 0)
                    qty = result.get('quantity', 0)
                    rules = result.get('rules', {})

                    print(f"✅ [ENTRY] {pair} @ {entry_price:.2f}")
                    print(f"   📈 ราคาเข้า: {entry_price:.2f} | จำนวน: {qty:.4f}")
                    print(f"   🛑 Stop Loss: {sl_price:.2f}")
                    print(f"   📋 เงื่อนไข:")
                    print(f"      ✓ Rule 1 (CDC Green): {'✅' if rules.get('rule_1_cdc_green') else '❌'}")
                    print(f"      ✓ Rule 2 (Leading Red): {'✅' if rules.get('rule_2_leading_red') else '❌'}")
                    print(f"      ✓ Rule 3 (Leading Signal): {'✅' if rules.get('rule_3_leading_signal') else '❌'}")
                    print(f"      ✓ Rule 4 (W-Shape): {'✅' if rules.get('rule_4_pattern') else '❌'}")

                elif action == "sell":
                    # Exit Signal
                    reason = result.get("reason", "unknown")
                    exit_price = result.get("exit_price", 0)
                    pnl_pct = result.get("pnl_pct", 0)

                    reason_thai = {
                        "STOP_LOSS": "🛑 Stop Loss ถูกชน",
                        "TRAILING_STOP": "📉 Trailing Stop ถูกชน",
                        "ORANGE_RED": "🟠➡️🔴 CDC เปลี่ยนจาก Orange → Red",
                        "DIVERGENCE": "📊 RSI Divergence (STRONG_SELL)",
                        "EMA_CROSS": "📉 EMA Crossover Bearish",
                    }.get(reason, reason)

                    pnl_symbol = "📈" if pnl_pct >= 0 else "📉"
                    print(f"❌ [EXIT] {pair} @ {exit_price:.2f}")
                    print(f"   📊 เหตุผล: {reason_thai}")
                    print(f"   {pnl_symbol} P&L: {pnl_pct:+.2f}%")

                elif action == "wait":
                    # No Signal
                    status_thai = {
                        "no_entry_signal": "⏸️ ไม่มีสัญญาณเข้า (เงื่อนไขไม่ผ่าน)",
                        "holding": "⏳ กำลังถือ Position อยู่",
                        "insufficient_data": "📊 ข้อมูลไม่เพียงพอ",
                    }.get(status, status)

                    print(f"{status_thai}")

                    # แสดงรายละเอียดเงื่อนไขที่ไม่ผ่าน (ถ้ามี)
                    if status == "no_entry_signal" and "rules" in result:
                        rules = result["rules"]
                        print(f"   📋 เงื่อนไข:")
                        print(f"      Rule 1 (CDC Green): {'✅' if rules.get('rule_1_cdc_green') else '❌'}")
                        print(f"      Rule 2 (Leading Red): {'✅' if rules.get('rule_2_leading_red') else '❌'}")
                        print(f"      Rule 3 (Leading Signal): {'✅' if rules.get('rule_3_leading_signal') else '❌'}")
                        print(f"      Rule 4 (W-Shape): {'✅' if rules.get('rule_4_pattern') else '❌'}")

            except Exception as e:
                print(f"❌ [{pair}] เกิดข้อผิดพลาด: {str(e)}")
                results.append({
                    "pair": pair,
                    "status": "error",
                    "error": str(e)
                })

        print(f"\n{'='*60}")
        print(f"[{datetime.now()}] ✅ ตรวจสอบเสร็จสิ้น")
        print(f"{'='*60}\n")

        return results

    async def start(self, pairs: List[str], interval_minutes: int = 1):
        """เริ่ม Scheduler

        Args:
            pairs: รายการคู่เงินที่ต้องการเทรด เช่น ["BTC/USDT", "ETH/USDT"]
            interval_minutes: ตรวจสอบทุกกี่นาที (default: 1)
        """
        if self.is_running:
            raise RuntimeError("Scheduler is already running")

        self.pairs = pairs
        self.interval_minutes = interval_minutes

        # เพิ่ม Job เข้า Scheduler
        self.scheduler.add_job(
            self._check_all_pairs,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id=f"trading_check_{interval_minutes}m",
            replace_existing=True,
            max_instances=1,  # ป้องกันการทำงานซ้ำซ้อน
        )

        self.scheduler.start()
        self.is_running = True

        print(f"\n{'*'*60}")
        print(f"🚀 Trading Scheduler STARTED")
        print(f"   Pairs: {', '.join(pairs)}")
        print(f"   Interval: Every {interval_minutes} minute(s)")
        print(f"   Started at: {datetime.now()}")
        print(f"{'*'*60}\n")

        # รันทันทีครั้งแรก (ไม่รอ interval)
        await self._check_all_pairs()

    async def stop(self):
        """หยุด Scheduler"""
        if not self.is_running:
            return

        self.scheduler.shutdown(wait=True)
        self.is_running = False

        print(f"\n{'*'*60}")
        print(f"⛔ Trading Scheduler STOPPED")
        print(f"   Stopped at: {datetime.now()}")
        print(f"{'*'*60}\n")

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


__all__ = ["TradingScheduler"]
