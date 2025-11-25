"""Analyze rule compliance for each order."""

from typing import List


def audit_rules(orders: List[dict]) -> List[dict]:
    results = []
    for order in orders:
        snapshot = order.get("rule_snapshot", {})
        failed = [rule for rule, passed in snapshot.items() if not passed]
        results.append({"pair": order["pair"], "failed_rules": failed})
    return results
