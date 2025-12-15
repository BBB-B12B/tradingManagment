#!/usr/bin/env python3
"""Check Binance Testnet Balance

แสดง Balance ทั้งหมดจาก Binance Testnet

Usage:
    python check_balance.py
"""

import asyncio
import ccxt.async_support as ccxt
import os
from typing import Dict, Any
from pathlib import Path


# โหลด .env file ถ้ามี
def load_env():
    """โหลด environment variables จาก .env.dev"""
    # ลองหาจาก project root
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env" / ".env.dev"

    if env_path.exists():
        print(f"📁 Loading env from: {env_path}")
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())
    else:
        print(f"⚠️  .env.dev not found at: {env_path}")


load_env()


async def get_binance_balance() -> Dict[str, Any]:
    """ดึง Balance จาก Binance Testnet"""

    # ตั้งค่า API Keys
    api_key = os.getenv("BINANCE_API_KEY", "")
    api_secret = os.getenv("BINANCE_API_SECRET", "")

    if not api_key or not api_secret:
        raise RuntimeError("Missing BINANCE_API_KEY or BINANCE_API_SECRET environment variables")

    # สร้าง Binance client
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'recvWindow': 10000,  # Allow 10s timestamp difference
        }
    })

    # Enable Testnet mode
    exchange.set_sandbox_mode(True)

    try:
        # Load server time to sync timestamps
        await exchange.load_time_difference()

        # ดึง Balance
        balance = await exchange.fetch_balance(params={'recvWindow': 10000})
        return balance
    finally:
        await exchange.close()


def print_balance(balance: Dict[str, Any]):
    """แสดง Balance แบบสวยงาม"""
    print("\n" + "="*70)
    print("💰 Binance Testnet Balance")
    print("="*70)

    # แสดงเฉพาะ assets ที่มี balance > 0
    free_balances = balance.get('free', {})
    used_balances = balance.get('used', {})
    total_balances = balance.get('total', {})

    has_balance = False

    for asset, total in sorted(total_balances.items()):
        if total > 0:
            has_balance = True
            free = free_balances.get(asset, 0)
            used = used_balances.get(asset, 0)

            print(f"\n💎 {asset}:")
            print(f"   Free:  {free:,.8f}")
            print(f"   Used:  {used:,.8f}")
            print(f"   Total: {total:,.8f}")

    if not has_balance:
        print("\n⚠️  ไม่มี Balance ใน Testnet")
        print("💡 Tip: ไปขอ Testnet tokens ที่ https://testnet.binance.vision/")

    print("\n" + "="*70)


async def main():
    """Entry point"""
    print("🔍 กำลังดึง Balance จาก Binance Testnet...")

    try:
        balance = await get_binance_balance()
        print_balance(balance)

    except RuntimeError as e:
        print("\n❌ ไม่พบ API Keys!")
        print("\nวิธีตั้งค่า:")
        print("1. ไปที่ https://testnet.binance.vision/ และสร้าง API Key")
        print("2. เพิ่มใน .env file:")
        print("   BINANCE_API_KEY=your_api_key_here")
        print("   BINANCE_API_SECRET=your_api_secret_here")
        print(f"\nError: {e}")

    except ccxt.AuthenticationError as e:
        print("\n❌ Authentication Error!")
        print("API Key หรือ Secret ไม่ถูกต้อง")
        print(f"\nError: {e}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
