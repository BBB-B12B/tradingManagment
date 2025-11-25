"""Export report data to CSV/PDF."""

import csv
from pathlib import Path
from typing import List


def export_csv(path: Path, orders: List[dict]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["pair", "status", "pnl"])
        writer.writeheader()
        writer.writerows(orders)
