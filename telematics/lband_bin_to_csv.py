#!/usr/bin/env python3
"""
Convert telematics L-band raw .bin logs to readable CSV using ICD §5.1.

Keeps the original telemetry-style columns and adds ICD decode columns:
  icd_message, mavlink_message, seq, mavlink_ver, decoded

The `decoded` column shows each field as:
  name=engineering (raw=N)   or   name=status_text (raw=N)

Usage:
  python3 lband_bin_to_csv.py data/lband_logs/power_cycle_.../lband_raw_part001.bin
  python3 lband_bin_to_csv.py input.bin -o out.csv --extra
  python3 lband_bin_to_csv.py input.bin --summary

Binary record (LbandFileLogger):
  [#; header...] then LBND | epoch_us BE64 | src_ip BE32 | src_port BE16 |
  local_port BE16 | len BE32 | payload (MAVLink v1/v2 frame(s))
"""

from __future__ import annotations

import argparse
import csv
import math
import socket
import struct
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

RECORD_MAGIC = b"LBND"
RECORD_META_FMT = ">QIHHI"  # epoch_us, src_ip, src_port, local_port, len
RECORD_META_SIZE = struct.calcsize(RECORD_META_FMT)

PORT_COMP = 7000  # GCS → COMP destination (ICD §5.1.4)
PORT_GCS = 7500   # COMP → GCS destination

# ---------------------------------------------------------------------------
# Enum / status maps (ICD §5.1 + MAVLink common)
# ---------------------------------------------------------------------------

MAV_TYPE = {
    0: "GENERIC",
    1: "FIXED_WING",
    2: "QUADROTOR",
    6: "GCS",
    10: "GROUND_ROVER",
    18: "ONBOARD_CONTROLLER",  # ICD: COMP
}

MAV_AUTOPILOT = {
    8: "INVALID",
}

MAV_STATE = {
    0: "UNINIT",
    1: "BOOT",
    2: "CALIBRATING",
    3: "STANDBY",
    4: "ACTIVE",
    5: "CRITICAL",
    6: "EMERGENCY",
    7: "POWEROFF",
    8: "FLIGHT_TERMINATION",
}

GPS_FIX = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D_FIX",
    3: "3D_FIX",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
    7: "STATIC",
    8: "PPP",
}

COMP_ID = {
    68: "TELEMETRY_RADIO",
    190: "MISSION_PLANNER_GCS",
    191: "COMPUTE",
}

SYS_ID = {
    1: "UGV",
    255: "GCS",
}

MAV_CMD = {
    20: "NAV_RETURN_TO_LAUNCH",
    176: "DO_SET_MODE",
    179: "DO_SET_HOME",
    181: "DO_SET_RELAY",
    183: "DO_SET_SERVO",
    400: "COMPONENT_ARM_DISARM",
}

MODE_SEL = {1: "MODE_A", 2: "MODE_B", 3: "MODE_C", 4: "MODE_D", 5: "MODE_E"}
DRIVE_LIMIT = {1: "LOW", 2: "MEDIUM", 3: "HIGH"}
ARM_PARAM = {0: "DISARM", 1: "ARM"}

# msgid -> (icd_name, mavlink_name)  ICD §5.1.6 / §5.1.7 / §4.2.5.9
MSG_META = {
    0: ("HEARTBEAT", "HEARTBEAT"),  # refined by sys/comp below
    2: ("COMP_SYSTEM_TIME", "SYSTEM_TIME"),
    24: ("COMP_GPS_RAW_INT", "GPS_RAW_INT"),
    30: ("COMP_IMU_ATTITUDE", "ATTITUDE"),
    33: ("GLOBAL_POSITION_INT", "GLOBAL_POSITION_INT"),
    69: ("GCS_MANUAL_CONTROL", "MANUAL_CONTROL"),
    76: ("COMMAND_LONG", "COMMAND_LONG"),  # refined by command id
    109: ("COMP_RADIO_STATUS", "RADIO_STATUS"),
    111: ("TIMESYNC", "TIMESYNC"),  # refined by direction / tc1
    50001: ("COMP_UGV_STATUS", "UGV_SYSTEM_INFO"),
}


def _enum(mapping: Dict[int, str], raw: int) -> str:
    return f"{mapping.get(raw, '?')} (raw={raw})"


def _eng(name: str, eng: Any, raw: Any) -> str:
    return f"{name}={eng} (raw={raw})"


def _u16(b: bytes, o: int) -> int:
    return b[o] | (b[o + 1] << 8)


def _i16(b: bytes, o: int) -> int:
    v = _u16(b, o)
    return v - 65536 if v >= 32768 else v


def _u32(b: bytes, o: int) -> int:
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)


def _i32(b: bytes, o: int) -> int:
    v = _u32(b, o)
    return v - (1 << 32) if v >= (1 << 31) else v


def _u64(b: bytes, o: int) -> int:
    v = 0
    for i in range(8):
        v |= b[o + i] << (8 * i)
    return v


def _i64(b: bytes, o: int) -> int:
    v = _u64(b, o)
    return v - (1 << 64) if v >= (1 << 63) else v


def _f32(b: bytes, o: int) -> float:
    return struct.unpack_from("<f", b, o)[0]


def _rad_deg(rad: float) -> str:
    return f"{math.degrees(rad):.3f}deg"


# ---------------------------------------------------------------------------
# Record / frame iterators
# ---------------------------------------------------------------------------

def skip_ascii_header(fh) -> None:
    while True:
        pos = fh.tell()
        line = fh.readline()
        if not line:
            return
        if line.startswith(b"#;"):
            continue
        fh.seek(pos)
        return


def iter_records(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("rb") as fh:
        skip_ascii_header(fh)
        while True:
            magic = fh.read(4)
            if not magic or len(magic) < 4:
                break
            if magic != RECORD_MAGIC:
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


def iter_mavlink_frames(datagram: bytes) -> Iterable[Dict[str, Any]]:
    """Yield MAVLink v1/v2 frames found in a UDP datagram."""
    i = 0
    n = len(datagram)
    while i < n:
        if datagram[i] == 0xFD and i + 10 <= n:
            plen = datagram[i + 1]
            incompat = datagram[i + 2]
            seq = datagram[i + 4]
            sys_id = datagram[i + 5]
            comp_id = datagram[i + 6]
            msg_id = datagram[i + 7] | (datagram[i + 8] << 8) | (datagram[i + 9] << 16)
            hdr = 10
            signed = 13 if (incompat & 0x01) else 0
            total = hdr + plen + 2 + signed
            if i + hdr + plen > n:
                i += 1
                continue
            yield {
                "mavlink_ver": 2,
                "seq": seq,
                "system_id": sys_id,
                "component_id": comp_id,
                "msg_id": msg_id,
                "payload": datagram[i + hdr : i + hdr + plen],
                "frame": datagram[i : i + min(total, n - i)],
            }
            i += total if total > 0 else 1
            continue

        if datagram[i] == 0xFE and i + 6 <= n:
            plen = datagram[i + 1]
            seq = datagram[i + 2]
            sys_id = datagram[i + 3]
            comp_id = datagram[i + 4]
            msg_id = datagram[i + 5]
            hdr = 6
            total = hdr + plen + 2
            if i + hdr + plen > n:
                i += 1
                continue
            yield {
                "mavlink_ver": 1,
                "seq": seq,
                "system_id": sys_id,
                "component_id": comp_id,
                "msg_id": msg_id,
                "payload": datagram[i + hdr : i + hdr + plen],
                "frame": datagram[i : i + min(total, n - i)],
            }
            i += total if total > 0 else 1
            continue

        i += 1


def direction_from_ports(src_port: int, local_port: int) -> str:
    if local_port == PORT_GCS or src_port == PORT_COMP:
        return "COMP_TO_GCS_TX"
    if local_port == PORT_COMP or src_port == PORT_GCS:
        return "GCS_TO_COMP_RX"
    return f"UDP_{src_port}_TO_{local_port}"


# ---------------------------------------------------------------------------
# ICD payload decoders → list of "name=eng (raw=...)" parts
# ---------------------------------------------------------------------------

def icd_names(msg_id: int, sys_id: int, comp_id: int, payload: bytes) -> Tuple[str, str]:
    if msg_id == 0:
        if sys_id == 255 or comp_id == 190:
            return "GCS_HEARTBEAT", "HEARTBEAT"
        return "COMP_HEARTBEAT", "HEARTBEAT"
    if msg_id == 111:
        tc1 = _i64(payload, 0) if len(payload) >= 8 else 0
        if sys_id == 255 or (tc1 == 0 and sys_id != 1):
            return "GCS_TIMESYNC_REQ", "TIMESYNC"
        return "COMP_TIMESYNC_RESP", "TIMESYNC"
    if msg_id == 76 and len(payload) >= 4:
        cmd = _u16(payload, 2)
        if cmd == 176:
            return "GCS_MODE_COMMAND", "COMMAND_LONG"
        if cmd == 400:
            return "GCS_ARM_DISARM_COMMAND", "COMMAND_LONG"
        if cmd == 20:
            return "GCS_RTH_COMMAND", "COMMAND_LONG"
        if cmd == 179:
            return "GCS_SET_HOME_LOCATION_COMMAND", "COMMAND_LONG"
        if cmd == 181:
            return "GCS_RELAY_FAMILY_COMMAND", "COMMAND_LONG"
        return "GCS_COMMAND_LONG", "COMMAND_LONG"
    meta = MSG_META.get(msg_id)
    if meta:
        return meta
    return f"UNKNOWN_{msg_id}", f"MSG_{msg_id}"


def decode_heartbeat(p: bytes) -> List[str]:
    # Standard MAVLink wire order (verified on live GCS/COMP L-band traffic)
    if len(p) < 9:
        return [f"truncated_payload(len={len(p)})"]
    custom = _u32(p, 0)
    typ, ap, base, status, mv = p[4], p[5], p[6], p[7], p[8]
    return [
        _eng("type", MAV_TYPE.get(typ, "?"), typ),
        _eng("autopilot", MAV_AUTOPILOT.get(ap, "?"), ap),
        _eng("base_mode", base, base),
        _eng("custom_mode", custom, custom),
        _eng("system_status", MAV_STATE.get(status, "?"), status),
        _eng("mavlink_version", mv, mv),
    ]


def decode_system_time(p: bytes) -> List[str]:
    if len(p) < 12:
        return [f"truncated_payload(len={len(p)})"]
    unix_us = _u64(p, 0)
    boot_ms = _u32(p, 8)
    return [
        _eng("time_unix_usec", unix_us, unix_us),
        _eng("time_boot_ms", f"{boot_ms}ms", boot_ms),
    ]


def decode_gps_raw(p: bytes) -> List[str]:
    if len(p) < 30:
        return [f"truncated_payload(len={len(p)})"]
    time_usec = _u64(p, 0)
    lat = _i32(p, 8)
    lon = _i32(p, 12)
    alt = _i32(p, 16)
    eph = _u16(p, 20)
    epv = _u16(p, 22)
    vel = _u16(p, 24)
    cog = _u16(p, 26)
    fix = p[28]
    sats = p[29]
    parts = [
        _eng("time_usec", time_usec, time_usec),
        _eng("lat_deg", f"{lat / 1e7:.7f}", lat),
        _eng("lon_deg", f"{lon / 1e7:.7f}", lon),
        _eng("alt_m", f"{alt / 1000.0:.3f}", alt),
        _eng("eph", "unknown" if eph == 65535 else f"{eph / 100.0:.2f}m", eph),
        _eng("epv", "unknown" if epv == 65535 else f"{epv / 100.0:.2f}m", epv),
        _eng("vel_m_s", "unknown" if vel == 65535 else f"{vel / 100.0:.2f}", vel),
        _eng("cog_deg", "unknown" if cog == 65535 else f"{cog / 100.0:.2f}", cog),
        _eng("fix_type", GPS_FIX.get(fix, "?"), fix),
        _eng("satellites_visible", "unknown" if sats == 255 else sats, sats),
    ]
    return parts


def decode_attitude(p: bytes) -> List[str]:
    if len(p) < 28:
        return [f"truncated_payload(len={len(p)})"]
    boot = _u32(p, 0)
    roll, pitch, yaw = _f32(p, 4), _f32(p, 8), _f32(p, 12)
    rs, ps, ys = _f32(p, 16), _f32(p, 20), _f32(p, 24)
    return [
        _eng("time_boot_ms", f"{boot}ms", boot),
        _eng("roll", _rad_deg(roll), f"{roll:.6f}rad"),
        _eng("pitch", _rad_deg(pitch), f"{pitch:.6f}rad"),
        _eng("yaw", _rad_deg(yaw), f"{yaw:.6f}rad"),
        _eng("rollspeed", f"{rs:.4f}rad/s", f"{rs:.6f}"),
        _eng("pitchspeed", f"{ps:.4f}rad/s", f"{ps:.6f}"),
        _eng("yawspeed", f"{ys:.4f}rad/s", f"{ys:.6f}"),
    ]


def decode_timesync(p: bytes) -> List[str]:
    if len(p) < 16:
        return [f"truncated_payload(len={len(p)})"]
    tc1 = _i64(p, 0)
    ts1 = _i64(p, 8)
    parts = [
        _eng("tc1", "request" if tc1 == 0 else tc1, tc1),
        _eng("ts1", ts1, ts1),
    ]
    if len(p) >= 18:
        parts.append(_eng("target_system", SYS_ID.get(p[16], "?"), p[16]))
        parts.append(_eng("target_component", COMP_ID.get(p[17], "?"), p[17]))
    return parts


def decode_manual_control(p: bytes) -> List[str]:
    if len(p) < 11:
        return [f"truncated_payload(len={len(p)})"]
    target = p[0]
    x, y, z, r = _i16(p, 1), _i16(p, 3), _i16(p, 5), _i16(p, 7)
    buttons = _u16(p, 9)

    def axis(v: int) -> str:
        if v == 0:
            return "0 (not_moving)"
        if v == 32767:
            return "32767 (disabled)"
        # ICD: map int16 to approx -1..+1 joystick
        return f"{v / 32767.0:.4f}"

    return [
        _eng("target", SYS_ID.get(target, "?"), target),
        _eng("x_fwd_back", axis(x), x),
        _eng("y_port_stbd", axis(y), y),
        _eng("z", axis(z), z),
        _eng("r", axis(r), r),
        _eng("buttons", buttons, buttons),
    ]


def decode_command_long(p: bytes) -> List[str]:
    if len(p) < 33:
        return [f"truncated_payload(len={len(p)})"]
    tgt_s, tgt_c = p[0], p[1]
    cmd = _u16(p, 2)
    conf = p[4]
    # MAVLink COMMAND_LONG: params are float32 after confirmation
    params = [_f32(p, 5 + 4 * i) for i in range(7)]
    parts = [
        _eng("target_system", SYS_ID.get(tgt_s, "?"), tgt_s),
        _eng("target_component", COMP_ID.get(tgt_c, "?"), tgt_c),
        _eng("command", MAV_CMD.get(cmd, "?"), cmd),
        _eng("confirmation", conf, conf),
    ]
    if cmd == 176:  # DO_SET_MODE / GCS_MODE_COMMAND
        # ICD documents param1/2/3 as mode flags; on wire they are floats
        p1, p2, p3 = int(params[0]), int(params[1]), int(params[2])
        parts += [
            _eng("param1_custom_mode_flag", p1, params[0]),
            _eng("param2_mode", MODE_SEL.get(p2, "?"), params[1]),
            _eng("param3_drive_limit", DRIVE_LIMIT.get(p3, "?"), params[2]),
        ]
    elif cmd == 400:  # ARM/DISARM
        arm = int(params[0])
        parts.append(_eng("param1_arm", ARM_PARAM.get(arm, "?"), params[0]))
    else:
        for i, v in enumerate(params, start=1):
            parts.append(f"param{i}={v}")
    return parts


def decode_radio_status(p: bytes) -> List[str]:
    if len(p) < 9:
        return [f"truncated_payload(len={len(p)})"]
    rxerrors = _u16(p, 0)
    fixed = _u16(p, 2)
    rssi, remrssi, txbuf, noise, remnoise = p[4], p[5], p[6], p[7], p[8]

    def rf(v: int) -> str:
        return "invalid" if v >= 255 else str(v)

    snr = "" if rssi >= 255 or noise >= 255 else str(rssi - noise)
    return [
        _eng("rxerrors", rxerrors, rxerrors),
        _eng("fixed", fixed, fixed),
        _eng("rssi", rf(rssi), rssi),
        _eng("remrssi", rf(remrssi), remrssi),
        _eng("txbuf_pct", "invalid" if txbuf > 100 else txbuf, txbuf),
        _eng("noise", rf(noise), noise),
        _eng("remnoise", rf(remnoise), remnoise),
        _eng("snr_est", snr if snr else "n/a", snr if snr else ""),
    ]


def decode_ugv_status(p: bytes) -> List[str]:
    """Partial ICD §5.1.7.2.1 COMP_UGV_STATUS (first status bytes)."""
    if not p:
        return ["empty"]
    parts = [f"payload_len={len(p)}"]
    # ICD lists bitfields starting around byte 10; live stubs often put state early.
    # Decode conservatively: byte0 vehicle-ish + any readable SOC-like bytes.
    if len(p) >= 1:
        st = p[0] & 0x03
        vcu = {0: "reserved/unknown", 1: "Idle", 2: "Key_On", 3: "Drive"}.get(st, "?")
        parts.append(_eng("vcu_status_lo2", vcu, p[0]))
    if len(p) >= 5:
        parts.append(_eng("boot_ms_hint", _u32(p, 1), _u32(p, 1)))
    if len(p) >= 13:
        parts.append(_eng("byte11_lv_soc_hint", p[11], p[11]))
        parts.append(_eng("byte12_hv_soc_hint", p[12], p[12]))
    parts.append("note=full_162B_layout_partial")
    return parts


def decode_global_position_int(p: bytes) -> List[str]:
    if len(p) < 28:
        return [f"truncated_payload(len={len(p)})"]
    boot = _u32(p, 0)
    lat, lon = _i32(p, 4), _i32(p, 8)
    alt, rel = _i32(p, 12), _i32(p, 16)
    vx, vy, vz = _i16(p, 20), _i16(p, 22), _i16(p, 24)
    hdg = _u16(p, 26)
    return [
        _eng("time_boot_ms", f"{boot}ms", boot),
        _eng("lat_deg", f"{lat / 1e7:.7f}", lat),
        _eng("lon_deg", f"{lon / 1e7:.7f}", lon),
        _eng("alt_m", f"{alt / 1000.0:.3f}", alt),
        _eng("relative_alt_m", f"{rel / 1000.0:.3f}", rel),
        _eng("vx_m_s", f"{vx / 100.0:.2f}", vx),
        _eng("vy_m_s", f"{vy / 100.0:.2f}", vy),
        _eng("vz_m_s", f"{vz / 100.0:.2f}", vz),
        _eng("hdg_deg", "unknown" if hdg == 65535 else f"{hdg / 100.0:.2f}", hdg),
    ]


DECODERS = {
    0: (decode_heartbeat, 9),
    2: (decode_system_time, 12),
    24: (decode_gps_raw, 30),
    30: (decode_attitude, 28),
    33: (decode_global_position_int, 28),
    69: (decode_manual_control, 11),
    76: (decode_command_long, 33),
    109: (decode_radio_status, 9),
    111: (decode_timesync, 16),
    50001: (decode_ugv_status, 1),
}


def _pad_payload(payload: bytes, min_len: int) -> bytes:
    """MAVLink2 may truncate trailing zero bytes; pad before field decode."""
    if len(payload) >= min_len:
        return payload
    return payload + bytes(min_len - len(payload))


def decode_frame(frame: Dict[str, Any]) -> Tuple[str, str, str]:
    mid = frame["msg_id"]
    p = frame["payload"]
    icd, mav = icd_names(mid, frame["system_id"], frame["component_id"], p)
    entry = DECODERS.get(mid)
    if entry:
        decoder, min_len = entry
        parts = decoder(_pad_payload(p, min_len))
        if len(frame["payload"]) < min_len:
            parts.append(f"mavlink2_truncated_pad={min_len - len(frame['payload'])}B")
    else:
        parts = [f"payload_hex={p.hex().upper()[:64]}{'...' if len(p) > 32 else ''}"]
    head = [
        _eng("sys", SYS_ID.get(frame["system_id"], "?"), frame["system_id"]),
        _eng("comp", COMP_ID.get(frame["component_id"], "?"), frame["component_id"]),
    ]
    return icd, mav, "; ".join(head + parts)


# ---------------------------------------------------------------------------
# Convert
# ---------------------------------------------------------------------------

BASE_FIELDS = [
    "timestamp",
    "length",
    "direction",
    "msg_id",
    "system_id",
    "component_id",
    "raw_data",
]

DECODE_FIELDS = [
    "icd_message",
    "mavlink_message",
    "seq",
    "mavlink_ver",
    "decoded",
]

EXTRA_FIELDS = ["src_ip", "src_port", "local_port"]


def convert(bin_path: Path, csv_path: Path, extra: bool = False) -> Tuple[int, Counter]:
    fieldnames = BASE_FIELDS + DECODE_FIELDS + (EXTRA_FIELDS if extra else [])
    counts: Counter = Counter()
    rows = 0

    with csv_path.open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for rec in iter_records(bin_path):
            payload = rec["payload"]
            frames = list(iter_mavlink_frames(payload))
            if not frames:
                # Still emit a row so nothing is silently dropped
                row = {
                    "timestamp": rec["epoch_us"],
                    "length": len(payload),
                    "direction": direction_from_ports(rec["src_port"], rec["local_port"]),
                    "msg_id": "",
                    "system_id": "",
                    "component_id": "",
                    "raw_data": payload.hex().upper(),
                    "icd_message": "NON_MAVLINK_OR_CORRUPT",
                    "mavlink_message": "",
                    "seq": "",
                    "mavlink_ver": "",
                    "decoded": "no_mavlink_frame_found",
                }
                if extra:
                    row.update(
                        {
                            "src_ip": rec["src_ip"],
                            "src_port": rec["src_port"],
                            "local_port": rec["local_port"],
                        }
                    )
                writer.writerow(row)
                rows += 1
                counts["NON_MAVLINK"] += 1
                continue

            for fr in frames:
                icd, mav, decoded = decode_frame(fr)
                counts[icd] += 1
                row = {
                    "timestamp": rec["epoch_us"],
                    "length": len(fr["frame"]),
                    "direction": direction_from_ports(rec["src_port"], rec["local_port"]),
                    "msg_id": fr["msg_id"],
                    "system_id": fr["system_id"],
                    "component_id": fr["component_id"],
                    "raw_data": fr["frame"].hex().upper(),
                    "icd_message": icd,
                    "mavlink_message": mav,
                    "seq": fr["seq"],
                    "mavlink_ver": fr["mavlink_ver"],
                    "decoded": decoded,
                }
                if extra:
                    row.update(
                        {
                            "src_ip": rec["src_ip"],
                            "src_port": rec["src_port"],
                            "local_port": rec["local_port"],
                        }
                    )
                writer.writerow(row)
                rows += 1

    return rows, counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert L-band LBND .bin logs to ICD-decoded CSV"
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
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print ICD message counts after convert",
    )
    args = parser.parse_args()

    if not args.bin_file.is_file():
        print(f"error: file not found: {args.bin_file}", file=sys.stderr)
        return 1

    out = args.output or args.bin_file.with_suffix(".csv")
    n, counts = convert(args.bin_file, out, extra=args.extra)
    print(f"Wrote {n} rows → {out}")
    print("ICD message counts:")
    for name, c in counts.most_common():
        print(f"  {c:7d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
