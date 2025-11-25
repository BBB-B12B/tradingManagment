"""View helpers for order reports."""

from typing import List


def render_report(orders: List[dict]) -> str:
    lines = ["CDC Order Report"]
    for order in orders:
        lines.append(f"Pair: {order['pair']} Status: {order['status']} PnL: {order.get('pnl')}")
    return "\n".join(lines)
