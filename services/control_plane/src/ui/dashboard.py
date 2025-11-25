"""Console dashboard to display rule status and position state."""

from typing import Dict, Optional


def render_dashboard(
    rule_snapshot: Dict,
    position_state: Dict,
    rules_status: Optional[Dict] = None,
) -> str:
    lines = ["CDC Zone Dashboard"]
    lines.append("=" * 70)

    # CDC Rules Status (per pair)
    if rules_status:
        lines.append("\n📊 CDC Rules Evaluation:")
        lines.append("-" * 70)

        for pair, status in rules_status.items():
            all_passed = status["all_passed"]
            status_icon = "✅" if all_passed else "❌"

            lines.append(f"\n  {status_icon} {pair} - {'ALL PASS' if all_passed else 'BLOCKED'}")

            for rule_name, passed in status["rules"].items():
                icon = "  ✓" if passed else "  ✗"
                lines.append(f"    {icon} {rule_name}")

        lines.append("")
    else:
        lines.append("\n📊 CDC Rules Evaluation: No data yet")
        lines.append("  Use POST /rules/evaluate to evaluate rules")

    lines.append("-" * 70)

    # Telemetry metrics
    if rule_snapshot:
        lines.append("\n📈 Rule Metrics (Telemetry):")
        for rule, count in rule_snapshot.items():
            lines.append(f"  • {rule}: {count}")
    else:
        lines.append("\n📈 Rule Metrics: {}")

    # Position state
    lines.append("\n💰 Position State:")
    lines.append(f"  • Overall: {position_state.get('status', 'unknown')}")
    lines.append(f"  • Updated: {position_state.get('updated', 'N/A')}")

    # Show individual positions if available
    positions = position_state.get('positions', {})
    if positions:
        for pair, status in positions.items():
            lines.append(f"  • {pair}: {status}")

    lines.append("\n" + "=" * 70)

    return "\n".join(lines)
