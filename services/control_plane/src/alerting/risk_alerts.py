"""Alerts for breaker/SL triggers."""

from typing import Dict


def build_risk_alerts(risk_status: Dict) -> Dict:
    alerts = []
    if risk_status.get("breaker"):
        alerts.append("Breaker active")
    if risk_status.get("structural_sl"):
        alerts.append("Structural SL hit")
    return {"alerts": alerts}
