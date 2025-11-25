"""Records rule pass/fail counts for auditing false signals."""

from __future__ import annotations

from collections import Counter


class RuleMetrics:
    def __init__(self):
        self.counts = Counter()

    def record(self, rule_name: str, passed: bool) -> None:
        key = f"{rule_name}_{'pass' if passed else 'fail'}"
        self.counts[key] += 1
