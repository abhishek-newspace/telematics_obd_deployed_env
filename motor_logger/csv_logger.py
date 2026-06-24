from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from motor_logger.controller import PollResult
from motor_logger.protocol import TELEMETRY_METRICS

METRICS = TELEMETRY_METRICS

CONTROLLER_FIELDNAMES = ["Timestamp", *METRICS]


class CsvTelemetryLogger:
    def __init__(self, csv_path: Path, fieldnames: list[str] | None = None) -> None:
        self._path = csv_path
        self._fieldnames = fieldnames or CONTROLLER_FIELDNAMES
        self._file = csv_path.open("w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._file, fieldnames=self._fieldnames)
        self._writer.writeheader()
        self._file.flush()

    @property
    def path(self) -> Path:
        return self._path

    def write_row(self, row: dict[str, Any]) -> None:
        self._writer.writerow(row)
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def make_controller_row(result: PollResult, timestamp: str | None = None) -> dict[str, Any]:
    if not result.ok:
        raise ValueError("make_controller_row requires a successful poll result")

    ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    row: dict[str, Any] = {"Timestamp": ts}
    prefix = f"{result.label} "
    for metric in METRICS:
        row[metric] = result.fields.get(f"{prefix}{metric}", "")
    return row
