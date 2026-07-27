#!/usr/bin/env python3
"""
Convert telematics L-band raw .bin logs to CSV (same style as
telemetry_log_*_0.csv from main compute).

Usage:
  python3 lband_bin_to_csv.py data/lband_logs/power_cycle_.../lband_raw_part001.bin
  python3 lband_bin_to_csv.py input.bin -o output.csv
  python3 lband_bin_to_csv.py input.bin --extra   # also write src_ip/ports columns

Binary record layout (written by LbandFileLogger):
  [#; comment header lines...]
  then repeating:
    magic      4 bytes  ASCII 'LBND'
    epoch_us   8 bytes  big-endian uint64  (host capture time, microseconds)
    src_ip     4 bytes  big-endian IPv4
    src_port   2 bytes  big-endian uint16
    local_port 2 bytes  big-endian uint16  (UDP port we bound: 7000 or 7500)
    len        4 bytes  big-endian uint32  (payload byte count)
    payload    N bytes  raw UDP datagram (= MAVLink2 frame(s))

MAVLink2 header (first 10 bytes of payload), ICD §5.1:
  [0]    STX        0xFD
  [1]    LEN        payload length
  [2]    incompat   bit0=1 → signed (13-byte signature after CRC)
  [3]    compat
  [4]    seq
  [5]    system_id
  [6]    component_id
  [7:10] msgid      24-bit little-endian
  ...    message payload, CRC, optional signature
"""

from __future__ import annotations

import argparse
import csv
import socket
import struct
import sys
from pathlib import Path

RECORD_MAGIC = b"LBND"
RECORD_META_FMT = ">QIHHI"  # epoch_us, src_ip, src_port, local_port, len
RECORD_META_SIZE = struct.calcsize(RECORD_META_FMT)  # 20

# ICD §5.1.4 ports
PORT_COMP = 7000  # Compute / radio-compute side
PORT_GCS = 7500   # GCS side


def skip_ascii_header(fh) -> None:
    """Skip leading #; metadata comment lines written by the logger."""
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            return
        if line.startswith(b"#;"):
            continue
        fh.seek(pos)
        return


def iter_records(path: Path):
    """Yield dicts for each LBND record in the .bin file."""
    with path.open("rb") as fh:
        skip_ascii_header(fh)
        while True:
            magic = fh.read(4)
            if not magic:
                break
            if len(magic) < 4:
                break
            if magic != RECORD_MAGIC:
                # Resync: slide one byte (corrupt/truncated edge case)
                fh.seek(fh.tell() - 3)
                continue

            meta = fh.read(RECORD_META_SIZE)
            if len(meta) < RECORD_META_SIZE:
                break

            epoch_us, src_ip_u32, src_port, local_port, payload_len = struct.unpack(
                RECORD_META_FMT, meta
            )
            payload = fh.read(payload_len)
            if len(payload) < payload_len:
                break

            yield {
                "epoch_us": epoch_us,
                "src_ip": socket.inet_ntoa(struct.pack(">I", src_ip_u32)),
                "src_port": src_port,
                "local_port": local_port,
                "payload": payload,
            }


def parse_mavlink2_header(payload: bytes):
    """
    Extract msgid / system_id / component_id from a MAVLink2 frame.
    Returns (msg_id, system_id, component_id) or (None, None, None).
    """
    if len(payload) < 10 or payload[0] != 0xFD:
        return None, None, None
    system_id = payload[5]
    component_id = payload[6]
    msg_id = payload[7] | (payload[8] << 8) | (payload[9] << 16)
    return msg_id, system_id, component_id


def direction_from_ports(src_port: int, local_port: int) -> str:
    """
    Map UDP ports to a direction label similar to the sample CSV.

    ICD:
      Compute → GCS : src :7000 → dest :7500
      GCS → Compute : src :7500 → dest :7000
    """
    if local_port == PORT_GCS or src_port == PORT_COMP:
        return "COMP_TO_GCS_TX"
    if local_port == PORT_COMP or src_port == PORT_GCS:
        return "GCS_TO_COMP_RX"
    return f"UDP_{src_port}_TO_{local_port}"


def convert(bin_path: Path, csv_path: Path, extra: bool = False) -> int:
    fieldnames = [
        "timestamp",
        "length",
        "direction",
        "msg_id",
        "system_id",
        "component_id",
        "raw_data",
    ]
    if extra:
        fieldnames.extend(["src_ip", "src_port", "local_port"])

    count = 0
    with csv_path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()

        for rec in iter_records(bin_path):
            payload = rec["payload"]
            msg_id, system_id, component_id = parse_mavlink2_header(payload)
            row = {
                "timestamp": rec["epoch_us"],
                "length": len(payload),
                "direction": direction_from_ports(rec["src_port"], rec["local_port"]),
                "msg_id": "" if msg_id is None else msg_id,
                "system_id": "" if system_id is None else system_id,
                "component_id": "" if component_id is None else component_id,
                "raw_data": payload.hex().upper(),
            }
            if extra:
                row["src_ip"] = rec["src_ip"]
                row["src_port"] = rec["src_port"]
                row["local_port"] = rec["local_port"]
            writer.writerow(row)
            count += 1

    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert L-band LBND .bin logs to telemetry-style CSV"
    )
    parser.add_argument("bin_file", type=Path, help="Path to lband_raw_partNNN.bin")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output CSV path (default: <bin_file>.csv)",
    )
    parser.add_argument(
        "--extra",
        action="store_true",
        help="Add src_ip, src_port, local_port columns",
    )
    args = parser.parse_args()

    if not args.bin_file.is_file():
        print(f"error: file not found: {args.bin_file}", file=sys.stderr)
        return 1

    out = args.output or args.bin_file.with_suffix(".csv")
    n = convert(args.bin_file, out, extra=args.extra)
    print(f"Wrote {n} rows → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
