"""Alert helpers for rule failures or HTF context changes."""

from typing import Dict


def detect_alerts(rule_snapshot: Dict, htf_color: str) -> Dict:
    alerts = []
    if htf_color == "RED":
        alerts.append("Week turned red")
    for rule, passed in rule_snapshot.items():
        if not passed:
            alerts.append(f"Rule {rule} failed")
    return {"alerts": alerts}
