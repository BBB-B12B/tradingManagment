"""Ensures all CDC rules pass before invoking order planner."""

from __future__ import annotations

from typing import Dict


class OrderGate:
    def __init__(self, required_rules: list[str]):
        self.required_rules = required_rules

    def allow(self, snapshot: Dict[str, bool]) -> bool:
        return all(snapshot.get(rule, False) for rule in self.required_rules)
