#!/usr/bin/env python3
"""
Live motor telemetry viewer (DEV/TEST ONLY — remove for production).

Tails motor_front / motor_rear CSV as telematics writes them.
Does not open the UART — no conflict with the container.

Usage (two terminals):
  python3 motor_live_view.py --side front
  python3 motor_live_view.py --side rear

Edit CONSOLE_COLUMNS below: uncomment lines you want on the console.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, TextIO, Tuple

_HERE = Path(__file__).resolve().parent
# Script lives in telematics/tools/ → data is ../data
_TELEM = _HERE.parent if (_HERE / ".." / "data").resolve().is_dir() else _HERE

# =============================================================================
# Console columns — keep ALL names here; comment (#) ones you don't want.
# Uncomment a line to show it. Order = console left→right.
# Names must match the motor CSV header exactly.
# =============================================================================
CONSOLE_COLUMNS = [
    "Timestamp (IST)",
    "Start Code",
    "Function Code",
    "Frame Length (bytes)",
    # "Reserved_1 Byte 3",
    # "Reserved_1 Byte 4",
    # "Reserved_1 Byte 5",
    # "Reserved_1 Byte 6",
    # "Reserved_1 Byte 7",
    "Control Type",
    "RS485 Address",
    "RS485 Baud",
    "CAN TX ID",
    "CAN RX ID",
    "CAN Baud",
    "CAN Frame Type",
    "M1 Mode",
    "M1 Direction",
    "M2 Mode",
    "M2 Direction",
    "Pole Pairs",
    "Acceleration Pct",
    "Deceleration Pct",
    "Kp Speed",
    "Ki Speed",
    "Auto Hold",
    "Encoder AB Swap",
    "M1 Sensor Type",
    "M2 Sensor Type",
    "BMQ Pairs",
    "Rated Speed (RPM)",
    "Brake State Mark",
    "Brake Enable",
    "OverCurrent I (A)",
    "OverCurrent Time (ms)",
    "Tim Max I",
    "Send Interval (ms)",
    "Fault Code",
    "Fault Status",
    "Bus Voltage (V)",
    "Bus Current (A)",
    "Throttle Voltage (V)",
    "Ctrl Temp (C)",
    "M1 Speed (krpm)",
    "M1 Speed (RPM)",
    "M1 Current (A)",
    "M1 Motor Temp (C)",
    "M2 Speed (krpm)",
    "M2 Speed (RPM)",
    "M2 Current (A)",
    "M2 Motor Temp (C)",
    "Max Bus Current (A)",
    "Max Phase Current (A)",
    "Max Voltage (V)",
    "Ls Current (A)",
    "R/L Hz",
    "Flux VpHz",
    "Rs Ohm",
    "Lsq H",
    "Lsd H",
    "Limit Max SCW",
    "Limit Max SCCW",
    "Brake Resistor Voltage (V)",
    "SF Tim Max I",
    "Reserved_3 Byte 194",
    "Reserved_3 Byte 195",
    "Reserved_3 Byte 196",
    "Reserved_3 Byte 197",
    "CRC Byte 198 (High)",
    "CRC Byte 199 (Low)",
    "CRC Valid",
]

# Short labels for console (optional). Missing → use full header name.
SHORT_LABELS = {
    "Timestamp (IST)": "time",
    "M1 Mode": "M1mode",
    "M2 Mode": "M2mode",
    "Brake Enable": "brk",
    "Fault Code": "flt",
    "Fault Status": "fst",
    "Bus Voltage (V)": "Vbus",
    "Bus Current (A)": "Ibus",
    "Ctrl Temp (C)": "Tctl",
    "M1 Speed (RPM)": "M1rpm",
    "M1 Current (A)": "M1A",
    "M1 Motor Temp (C)": "M1C",
    "M2 Speed (RPM)": "M2rpm",
    "M2 Current (A)": "M2A",
    "M2 Motor Temp (C)": "M2C",
    "CRC Valid": "crc",
}

# ANSI colors (disabled with --no-color or non-TTY)
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

MOTOR_MODE = {
    "0": "Torque",
    "1": "Speed",
    "2": "Position",
}

USE_COLOR = True


def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"{code}{text}{RESET}"


def map_motor_mode(raw: str) -> str:
    key = raw.strip()
    name = MOTOR_MODE.get(key)
    if name is None:
        return raw
    return f"{name}({key})"


def pretty_value(col: str, raw: str) -> Tuple[str, str]:
    """Return (display_text, ansi_color_for_value)."""
    val = raw
    color = BRIGHT_WHITE

    if col == "Timestamp (IST)" and " " in val:
        val = val.split(" ", 1)[1]
        color = DIM
    elif col in ("M1 Mode", "M2 Mode"):
        val = map_motor_mode(raw)
        if raw.strip() == "1":
            color = BRIGHT_CYAN  # Speed
        elif raw.strip() == "0":
            color = MAGENTA  # Torque
        else:
            color = YELLOW
    elif col == "Brake Enable":
        if raw.strip() in ("1", "true", "True"):
            val = "ON"
            color = BRIGHT_YELLOW
        else:
            val = "OFF"
            color = GREEN
    elif col == "Fault Status":
        if raw.strip().lower() in ("normal", "ok", "0", ""):
            color = BRIGHT_GREEN
        else:
            color = BRIGHT_RED
    elif col == "Fault Code":
        cleaned = raw.strip().lower().replace("0x", "")
        if cleaned and set(cleaned) <= {"0"}:
            color = DIM
        else:
            color = BRIGHT_RED
    elif col == "CRC Valid":
        if raw.strip() in ("1", "true", "True"):
            val = "OK"
            color = BRIGHT_GREEN
        else:
            val = "BAD"
            color = BRIGHT_RED
    elif col in ("M1 Speed (RPM)", "M2 Speed (RPM)"):
        color = BRIGHT_CYAN
    elif col in ("M1 Current (A)", "M2 Current (A)", "Bus Current (A)"):
        color = YELLOW
    elif col in ("Bus Voltage (V)",):
        color = GREEN
    elif col in ("Ctrl Temp (C)", "M1 Motor Temp (C)", "M2 Motor Temp (C)"):
        try:
            t = float(raw)
            color = BRIGHT_RED if t >= 70 else (YELLOW if t >= 50 else GREEN)
        except ValueError:
            color = WHITE

    return val, color


def find_latest_csv(logs_root: Path, side: str) -> Optional[Path]:
    pattern = f"power_cycle_*/motor_{side}_telemetry_part*.csv"
    candidates = sorted(
        logs_root.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def skip_comment_header(fh: TextIO) -> List[str]:
    """Skip #; preamble; return CSV header fields."""
    header: Optional[List[str]] = None
    last_pos = fh.tell()
    while True:
        last_pos = fh.tell()
        line = fh.readline()
        if not line:
            break
        if line.startswith("#") or not line.strip():
            continue
        header = next(csv.reader([line]))
        break
    if header is None:
        fh.seek(last_pos)
        raise RuntimeError("CSV header not found yet")
    return header


def resolve_columns(all_headers: List[str], wanted: List[str]) -> List[str]:
    known = set(all_headers)
    out: List[str] = []
    missing: List[str] = []
    for name in wanted:
        if name in known:
            out.append(name)
        else:
            missing.append(name)
    if missing:
        print(
            f"[motor-live] WARN unknown columns (ignored): {missing}",
            file=sys.stderr,
        )
    if not out:
        raise SystemExit("error: no valid CONSOLE_COLUMNS selected")
    return out


def side_tag(side: str) -> str:
    if side == "front":
        return c(BOLD + BLUE, "[FRONT]")
    return c(BOLD + MAGENTA, "[REAR]")


def fmt_row(side: str, cols: List[str], row: Dict[str, str]) -> str:
    parts = [side_tag(side)]
    for col in cols:
        label = SHORT_LABELS.get(col, col)
        raw = row.get(col, "")
        val, vcolor = pretty_value(col, raw)
        parts.append(f"{c(DIM, label)}={c(vcolor, val)}")
    return "  ".join(parts)


def open_csv(path: Path, from_end: bool) -> Tuple[TextIO, List[str]]:
    fh = path.open("r", newline="", encoding="utf-8", errors="replace")
    headers = skip_comment_header(fh)
    if from_end:
        fh.seek(0, os.SEEK_END)
    return fh, headers


def follow(
    side: str,
    path: Path,
    from_end: bool,
    columns: List[str],
    poll_sec: float,
    switch_latest: bool,
    logs_root: Path,
    every: int,
) -> int:
    print(
        c(DIM, f"[motor-live] {side} → {path}")
        + c(DIM, " (from end)" if from_end else " (from start)"),
        file=sys.stderr,
        flush=True,
    )
    print(
        c(DIM, f"[motor-live] columns: {', '.join(columns)}"),
        file=sys.stderr,
        flush=True,
    )
    print(
        c(
            DIM,
            "[motor-live] DEV ONLY — Ctrl+C to stop. Edit CONSOLE_COLUMNS in this script.",
        ),
        file=sys.stderr,
        flush=True,
    )

    fh, headers = open_csv(path, from_end=from_end)
    cols = resolve_columns(headers, columns)
    current = path
    last_inode = current.stat().st_ino
    last_check = time.monotonic()
    printed = 0
    skip_n = max(1, every)
    buf = ""

    try:
        while True:
            chunk = fh.read()
            if chunk:
                buf += chunk
                while True:
                    if "\n" not in buf:
                        break
                    line, buf = buf.split("\n", 1)
                    line = line.strip("\r")
                    if not line or line.startswith("#"):
                        continue
                    try:
                        cells = next(csv.reader([line]))
                    except csv.Error:
                        continue
                    if len(cells) < 2:
                        continue
                    if cells[0] == "Timestamp (IST)":
                        continue
                    row = {
                        headers[i]: cells[i] if i < len(cells) else ""
                        for i in range(len(headers))
                    }
                    printed += 1
                    if printed % skip_n != 0:
                        continue
                    print(fmt_row(side, cols, row), flush=True)
                continue

            time.sleep(poll_sec)
            now = time.monotonic()
            if switch_latest and (now - last_check) >= 1.0:
                last_check = now
                latest = find_latest_csv(logs_root, side)
                if latest is None:
                    continue
                try:
                    st = latest.stat()
                except FileNotFoundError:
                    continue
                if latest.resolve() != current.resolve() or st.st_ino != last_inode:
                    fh.close()
                    current = latest
                    last_inode = st.st_ino
                    print(
                        c(YELLOW, f"[motor-live] switched → {current}"),
                        file=sys.stderr,
                        flush=True,
                    )
                    fh, headers = open_csv(current, from_end=True)
                    cols = resolve_columns(headers, columns)
                    buf = ""
    except KeyboardInterrupt:
        print(
            c(DIM, f"\n[motor-live] {side} stopped — rows_seen≈{printed}"),
            file=sys.stderr,
            flush=True,
        )
    finally:
        fh.close()
    return 0


def main() -> int:
    global USE_COLOR
    default_logs = _TELEM / "data" / "motor_logs"
    parser = argparse.ArgumentParser(
        description="Live motor CSV viewer (DEV/TEST only)"
    )
    parser.add_argument(
        "--side",
        choices=("front", "rear"),
        required=True,
        help="Which controller CSV to follow (use two terminals)",
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        type=Path,
        default=None,
        help="Optional explicit motor_*_telemetry_partNNN.csv",
    )
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=default_logs,
        help=f"Session root (default: {default_logs})",
    )
    parser.add_argument(
        "--from-end",
        action="store_true",
        help="Only new rows after attach (default when auto-picking latest)",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Print existing rows then keep following",
    )
    parser.add_argument(
        "--every",
        type=int,
        default=1,
        help="Print every Nth row (e.g. 5 to thin out at high poll_hz)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=0.05,
        help="EOF poll interval seconds",
    )
    parser.add_argument(
        "--no-switch",
        action="store_true",
        help="Do not auto-follow a newer power_cycle / part file",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors",
    )
    parser.add_argument(
        "--list-columns",
        action="store_true",
        help="Print CSV header from latest file and exit",
    )
    args = parser.parse_args()

    USE_COLOR = (not args.no_color) and sys.stdout.isatty()

    path = args.csv_file
    if path is None:
        path = find_latest_csv(args.logs_root, args.side)
        if path is None:
            print(
                f"error: no motor_{args.side}_telemetry_part*.csv under {args.logs_root}",
                file=sys.stderr,
            )
            return 1
        from_end = not args.from_start
    else:
        from_end = args.from_end and not args.from_start

    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    if args.list_columns:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            headers = skip_comment_header(fh)
        for i, h in enumerate(headers):
            mark = " " if h in CONSOLE_COLUMNS else "#"
            print(f"{mark} {i:3d}  {h}")
        return 0

    return follow(
        side=args.side,
        path=path,
        from_end=from_end,
        columns=list(CONSOLE_COLUMNS),
        poll_sec=max(0.01, args.poll),
        switch_latest=not args.no_switch,
        logs_root=args.logs_root,
        every=max(1, args.every),
    )


if __name__ == "__main__":
    raise SystemExit(main())
