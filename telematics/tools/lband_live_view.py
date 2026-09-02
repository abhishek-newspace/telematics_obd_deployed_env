#!/usr/bin/env python3
"""
Live ICD decode of L-band LBND .bin while telematics is logging.

DEV/TEST ONLY — remove for production. Does not bind UDP :7000/:7500
(so it never fights the logger). It tails the same .bin the container writes.

Examples:
  # Follow newest session under data/lband_logs
  python3 lband_live_view.py

  # Specific file + live CSV on Desktop
  python3 lband_live_view.py data/lband_logs/.../lband_raw_part001.bin \\
      --csv ~/Desktop/lband_live.csv --from-end

  # Only GPS + radio status, quieter console
  python3 lband_live_view.py --filter GPS_RAW_INT,RADIO_STATUS,UGV_STATUS
"""

from __future__ import annotations

import argparse
import csv
import os
import socket
import struct
import sys
import time
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, TextIO, Tuple

# Reuse offline converter (same directory).
_HERE = Path(__file__).resolve().parent
_TELEM = _HERE.parent if (_HERE.parent / "data").is_dir() else _HERE
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import lband_bin_to_csv as lb  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

USE_COLOR = True


def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    return f"{code}{text}{RESET}"


def find_latest_bin(logs_root: Path) -> Optional[Path]:
    if not logs_root.is_dir():
        return None
    candidates = sorted(
        logs_root.glob("power_cycle_*/lband_raw_part*.bin"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def ist_from_epoch_us(epoch_us: int) -> str:
    return datetime.fromtimestamp(epoch_us / 1e6, tz=IST).strftime("%H:%M:%S.%f")[:-3]


def parse_filter(raw: str) -> Optional[Set[str]]:
    if not raw.strip():
        return None
    return {x.strip().upper() for x in raw.split(",") if x.strip()}


def match_filter(icd: str, mav: str, filt: Optional[Set[str]]) -> bool:
    if filt is None:
        return True
    u_icd = icd.upper()
    u_mav = mav.upper()
    for token in filt:
        if token in u_icd or token in u_mav:
            return True
    return False


def color_for_icd(icd: str) -> str:
    u = icd.upper()
    if "NON_MAVLINK" in u or "CORRUPT" in u:
        return BRIGHT_RED
    if "HEARTBEAT" in u:
        return BRIGHT_GREEN
    if "GPS" in u:
        return BRIGHT_CYAN
    if "ATTITUDE" in u or "IMU" in u:
        return BRIGHT_BLUE
    if "RADIO" in u:
        return BRIGHT_MAGENTA
    if "UGV" in u or "STATUS" in u:
        return YELLOW
    if "TIME" in u or "TIMESYNC" in u:
        return CYAN
    if "COMMAND" in u or "MANUAL" in u or "ARM" in u or "MODE" in u:
        return BRIGHT_YELLOW
    if "GCS" in u:
        return MAGENTA
    return BRIGHT_WHITE


def color_for_direction(direction: str) -> str:
    if "COMP_TO_GCS" in direction:
        return BLUE
    if "GCS_TO_COMP" in direction:
        return MAGENTA
    return DIM


def colorize_decoded(decoded: str) -> str:
    """Lightly highlight name=value tokens in the decoded string."""
    if not USE_COLOR or not decoded:
        return decoded
    parts: List[str] = []
    for token in decoded.split("; "):
        if "=" in token:
            name, rest = token.split("=", 1)
            parts.append(f"{c(DIM, name)}={c(BRIGHT_WHITE, rest)}")
        else:
            parts.append(c(DIM, token))
    return "; ".join(parts)


def format_line(
    rec: Dict,
    fr: Dict,
    icd: str,
    mav: str,
    decoded: str,
    quiet: bool,
) -> str:
    ts = c(DIM, ist_from_epoch_us(int(rec["epoch_us"])))
    direction = lb.direction_from_ports(rec["src_port"], rec["local_port"])
    icd_s = c(BOLD + color_for_icd(icd), f"{icd:<28}")
    decoded_s = colorize_decoded(decoded)
    if quiet:
        return f"{ts}  {icd_s}  {decoded_s}"
    dir_s = c(color_for_direction(direction), f"{direction:<16}")
    src = (
        f"{c(DIM, 'src=')}{c(CYAN, rec['src_ip'])}"
        f"{c(DIM, ':')}{c(CYAN, str(rec['src_port']))}"
        f"{c(DIM, '→:')}"
        f"{c(CYAN, str(rec['local_port']))}"
    )
    seq = f"{c(DIM, 'seq=')}{c(YELLOW, str(fr['seq']))}"
    return f"{ts}  {dir_s}  {icd_s}  {src}  {seq}  {decoded_s}"


def try_read_one_record(fh: TextIO) -> Tuple[Optional[Dict], bool]:
    """
    Read one complete LBND record.
    Returns (record, incomplete_at_eof).
    incomplete_at_eof=True means seek back and wait for more bytes.
    """
    start = fh.tell()
    magic = fh.read(4)
    if not magic:
        return None, False
    if len(magic) < 4:
        fh.seek(start)
        return None, True
    if magic != lb.RECORD_MAGIC:
        # Resync: advance 1 byte from start
        fh.seek(start + 1)
        return None, False

    meta = fh.read(lb.RECORD_META_SIZE)
    if len(meta) < lb.RECORD_META_SIZE:
        fh.seek(start)
        return None, True

    epoch_us, src_ip_u32, src_port, local_port, payload_len = struct.unpack(
        lb.RECORD_META_FMT, meta
    )
    if payload_len > 65535:
        # Corrupt length — skip magic and continue
        fh.seek(start + 1)
        return None, False

    payload = fh.read(payload_len)
    if len(payload) < payload_len:
        fh.seek(start)
        return None, True

    return {
        "epoch_us": epoch_us,
        "src_ip": socket.inet_ntoa(struct.pack(">I", src_ip_u32)),
        "src_port": src_port,
        "local_port": local_port,
        "payload": payload,
    }, False


def open_bin(path: Path, from_end: bool):
    fh = path.open("rb")
    lb.skip_ascii_header(fh)
    if from_end:
        fh.seek(0, os.SEEK_END)
    return fh


def emit_record(
    rec: Dict,
    filt: Optional[Set[str]],
    quiet: bool,
    csv_writer: Optional[csv.DictWriter],
    counts: Counter,
) -> int:
    n = 0
    frames = list(lb.iter_mavlink_frames(rec["payload"]))
    if not frames:
        icd, mav, decoded = "NON_MAVLINK_OR_CORRUPT", "", "no_mavlink_frame_found"
        if match_filter(icd, mav, filt):
            ts = c(DIM, ist_from_epoch_us(int(rec["epoch_us"])))
            direction = lb.direction_from_ports(rec["src_port"], rec["local_port"])
            print(
                f"{ts}  {c(color_for_direction(direction), f'{direction:<16}')}  "
                f"{c(BOLD + BRIGHT_RED, icd)}  {c(DIM, decoded)}",
                flush=True,
            )
            n += 1
        counts[icd] += 1
        return n

    for fr in frames:
        icd, mav, decoded = lb.decode_frame(fr)
        counts[icd] += 1
        if not match_filter(icd, mav, filt):
            continue
        print(format_line(rec, fr, icd, mav, decoded, quiet), flush=True)
        if csv_writer is not None:
            csv_writer.writerow(
                {
                    "timestamp": rec["epoch_us"],
                    "ist_time": ist_from_epoch_us(int(rec["epoch_us"])),
                    "direction": lb.direction_from_ports(
                        rec["src_port"], rec["local_port"]
                    ),
                    "icd_message": icd,
                    "mavlink_message": mav,
                    "msg_id": fr["msg_id"],
                    "seq": fr["seq"],
                    "src_ip": rec["src_ip"],
                    "src_port": rec["src_port"],
                    "local_port": rec["local_port"],
                    "decoded": decoded,
                }
            )
        n += 1
    return n


def follow(
    path: Path,
    from_end: bool,
    filt: Optional[Set[str]],
    quiet: bool,
    csv_path: Optional[Path],
    poll_sec: float,
    switch_latest: bool,
    logs_root: Path,
) -> int:
    counts: Counter = Counter()
    printed = 0
    csv_fh = None
    csv_writer = None

    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not csv_path.exists() or csv_path.stat().st_size == 0
        csv_fh = csv_path.open("a", newline="")
        fieldnames = [
            "timestamp",
            "ist_time",
            "direction",
            "icd_message",
            "mavlink_message",
            "msg_id",
            "seq",
            "src_ip",
            "src_port",
            "local_port",
            "decoded",
        ]
        csv_writer = csv.DictWriter(csv_fh, fieldnames=fieldnames)
        if new_file:
            csv_writer.writeheader()
            csv_fh.flush()

    current = path
    print(
        c(
            DIM,
            f"[lband-live] following {current}"
            f"{' (from end)' if from_end else ' (from start)'}"
            f"{'' if csv_path is None else f'  csv→{csv_path}'}",
        ),
        file=sys.stderr,
        flush=True,
    )
    print(
        c(
            DIM,
            "[lband-live] DEV ONLY — Ctrl+C to stop. Does not affect production logger.",
        ),
        file=sys.stderr,
        flush=True,
    )

    fh = open_bin(current, from_end=from_end)
    last_inode = current.stat().st_ino
    last_check = time.monotonic()

    try:
        while True:
            rec, incomplete = try_read_one_record(fh)
            if rec is not None:
                printed += emit_record(rec, filt, quiet, csv_writer, counts)
                if csv_fh is not None:
                    csv_fh.flush()
                continue
            if incomplete:
                time.sleep(poll_sec)
                continue

            # EOF — wait for more data; optionally jump to a newer part/session.
            time.sleep(poll_sec)
            now = time.monotonic()
            if switch_latest and (now - last_check) >= 1.0:
                last_check = now
                latest = find_latest_bin(logs_root)
                if latest is not None:
                    try:
                        st = latest.stat()
                    except FileNotFoundError:
                        continue
                    if latest.resolve() != current.resolve() or st.st_ino != last_inode:
                        fh.close()
                        current = latest
                        last_inode = st.st_ino
                        print(
                            c(YELLOW, f"[lband-live] switched → {current}"),
                            file=sys.stderr,
                            flush=True,
                        )
                        fh = open_bin(current, from_end=True)
    except KeyboardInterrupt:
        print(
            c(DIM, f"\n[lband-live] stopped — printed={printed}"),
            file=sys.stderr,
            flush=True,
        )
        if counts:
            print(c(DIM, "[lband-live] message counts:"), file=sys.stderr)
            for name, cnt in counts.most_common(20):
                print(
                    f"  {c(YELLOW, f'{cnt:7d}')}  {c(color_for_icd(name), name)}",
                    file=sys.stderr,
                )
    finally:
        fh.close()
        if csv_fh is not None:
            csv_fh.close()
    return 0


def main() -> int:
    global USE_COLOR
    default_logs = _TELEM / "data" / "lband_logs"
    parser = argparse.ArgumentParser(
        description="Live ICD decode of L-band .bin (DEV/TEST only)"
    )
    parser.add_argument(
        "bin_file",
        nargs="?",
        type=Path,
        default=None,
        help="lband_raw_partNNN.bin (default: newest under data/lband_logs)",
    )
    parser.add_argument(
        "--logs-root",
        type=Path,
        default=default_logs,
        help=f"Session root to auto-pick latest bin (default: {default_logs})",
    )
    parser.add_argument(
        "--from-end",
        action="store_true",
        help="Only decode new records after attach (default if no explicit file)",
    )
    parser.add_argument(
        "--from-start",
        action="store_true",
        help="Decode existing file contents then keep following",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Comma substrings of ICD/MAV names, e.g. GPS,RADIO_STATUS,HEARTBEAT",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Append readable rows to this CSV (use a user-writable path)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Shorter console lines (time + ICD + decoded)",
    )
    parser.add_argument(
        "--poll",
        type=float,
        default=0.05,
        help="EOF poll interval seconds (default 0.05)",
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
    args = parser.parse_args()

    USE_COLOR = (not args.no_color) and sys.stdout.isatty()

    path = args.bin_file
    if path is None:
        path = find_latest_bin(args.logs_root)
        if path is None:
            print(
                f"error: no lband_raw_part*.bin under {args.logs_root}",
                file=sys.stderr,
            )
            return 1
        from_end = not args.from_start
    else:
        from_end = args.from_end and not args.from_start

    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    return follow(
        path=path,
        from_end=from_end,
        filt=parse_filter(args.filter),
        quiet=args.quiet,
        csv_path=args.csv,
        poll_sec=max(0.01, args.poll),
        switch_latest=not args.no_switch,
        logs_root=args.logs_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
