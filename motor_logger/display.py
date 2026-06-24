from __future__ import annotations

import os
from pathlib import Path

from motor_logger.config import AppConfig
from motor_logger.controller import PollResult
from motor_logger.protocol import DASHBOARD_METRICS

METRICS = DASHBOARD_METRICS


def clear_terminal() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render_dashboard(
    config: AppConfig,
    timestamp: str,
    results: list[PollResult],
    csv_paths: dict[str, Path],
    cycle_path: str,
) -> None:
    clear_terminal()
    print("=== MOTOR CONTROLLER TELEMETRY LOGGER ===")
    print(f"Power cycle : {cycle_path}")
    for label, path in csv_paths.items():
        print(f"CSV {label:<6}: {path}")
    print(f"Poll rate   : {config.poll_hz} Hz @ {config.serial_baud} baud")
    print(f"Timestamp   : {timestamp}\n")

    headers = [r.label for r in results]
    col_w = 25
    print(f"{'METRIC':<25} | " + " | ".join(f"{h:<{col_w}}" for h in headers))
    print("-" * (28 + (col_w + 3) * len(headers)))

    for metric in METRICS:
        cells = []
        for result in results:
            key = f"{result.label} {metric}"
            if result.ok:
                cells.append(str(result.fields.get(key, "")))
            elif result.needs_reconnect:
                cells.append("Reconnecting...")
            else:
                cells.append("—")
        print(f"{metric:<25} | " + " | ".join(f"{c:<{col_w}}" for c in cells))

    print("-" * (28 + (col_w + 3) * len(headers)))
    if not any(r.ok for r in results):
        print("Waiting for valid motor data (no CSV row written this cycle)...")
