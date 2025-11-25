"""Aggregates telemetry metrics into success criteria dashboard."""

from __future__ import annotations

from typing import Dict

from services.control_plane.src.telemetry.config_metrics import ConfigMetrics
from services.control_plane.src.telemetry.rule_metrics import RuleMetrics


def build_success_dashboard(config_metrics: ConfigMetrics, rule_metrics: RuleMetrics) -> Dict:
    avg_duration = 0
    if config_metrics.events:
        avg_duration = sum(e["duration"] for e in config_metrics.events) / len(config_metrics.events)
    return {
        "config_events": len(config_metrics.events),
        "avg_config_duration": avg_duration,
        "rule_counts": rule_metrics.counts,
    }
