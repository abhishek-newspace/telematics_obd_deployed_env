from __future__ import annotations

import struct
from typing import Any

FAULT_MAP: dict[int, str] = {
    0x01: "M2 Phase Sensor",
    0x02: "M1 Phase Sensor",
    0x04: "M2 Current Sensor",
    0x08: "M1 Current Sensor",
    0x10: "Overcurrent",
    0x20: "Overvoltage",
    0x40: "Undervoltage",
    0x80: "Ctrl Over Temp",
    0x100: "M2 Overcurrent",
    0x200: "M1 Overcurrent",
    0x400: "M2 Overspeed",
    0x800: "M1 Overspeed",
    0x1000: "M2 Overload",
    0x2000: "M1 Overload",
    0x4000: "M2 Phase Loss",
    0x8000: "M1 Phase Loss",
    0x10000: "M2 Brake",
    0x20000: "M1 Brake",
    0x40000: "M2 Encoder",
    0x80000: "M1 Encoder",
    0x100000: "M2 Over Temp",
    0x200000: "M1 Over Temp",
    0x400000: "M2 Hall Fault",
    0x800000: "M1 Hall Fault",
    0x1000000: "M2 Stalled",
    0x2000000: "M1 Stalled",
    0x4000000: "UART Failure",
    0x8000000: "RS485 Failure",
    0x10000000: "CAN Failure",
    0x20000000: "Joystick Failure",
    0x40000000: "Throttle Failure",
}

CONTROL_TYPE_MAP = {0: "Analog", 1: "RS485", 2: "CAN", 3: "Remote", 4: "Rocker"}
MOTOR_MODE_MAP = {0: "Torque", 1: "Speed", 2: "Position"}
DIRECTION_MAP = {0: "Forward", 1: "Reverse"}
SENSOR_TYPE_MAP = {0: "HallLess", 1: "Hall", 2: "Encoder"}
CAN_BAUD_MAP = {0: "100K", 3: "250K", 4: "500K"}
CAN_FRAME_MAP = {0: "Standard", 1: "Extended"}

# Full CSV column order — mirrors MX_ES_DriverCan TV4 GUI fields from the 0x91 frame.
TELEMETRY_METRICS: list[str] = [
  # Live / display
    "Fault Status",
    "Fault Code",
    "Bus Voltage (V)",
    "Bus Current (A)",
    "Throttle Voltage (V)",
    "Ctrl Temp (C)",
    "M1 Speed (RPM)",
    "M1 Speed (krpm)",
    "M1 Current (A)",
    "M1 Motor Temp (C)",
    "M2 Speed (RPM)",
    "M2 Speed (krpm)",
    "M2 Current (A)",
    "M2 Motor Temp (C)",
    "Brake State Mark",
    "Brake Enable",
  # Communication
    "Control Type",
    "RS485 Address",
    "RS485 Baud",
    "CAN TX ID",
    "CAN RX ID",
    "CAN Baud",
    "CAN Frame Type",
    "Send Interval (ms)",
  # Motor config
    "M1 Mode",
    "M1 Direction",
    "M2 Mode",
    "M2 Direction",
    "M1 Sensor Type",
    "M2 Sensor Type",
    "Pole Pairs",
    "BMQ Pairs",
    "Encoder AB Swap",
    "Auto Hold",
    "Rated Speed (RPM)",
    "Acceleration Pct",
    "Deceleration Pct",
  # Speed loop / current loop
    "Kp Speed",
    "Ki Speed",
    "Kp Idq",
    "Ki Idq",
  # Limits & protection
    "OverCurrent I (A)",
    "OverCurrent Time (ms)",
    "Tim Max I",
    "Max Bus Current (A)",
    "Max Phase Current (A)",
    "Max Voltage (V)",
    "Min Voltage (V)",
    "Limit Max SCW",
    "Limit Max SCCW",
  # Brake / voltage profile
    "Pick-up Voltage (V)",
    "Keep Voltage (V)",
    "Brake Delay (s)",
    "Drive Downtime (s)",
    "Brake Resistor Voltage (V)",
    "SF Tim Max I",
  # Motor parameters
    "Rs Current (A)",
    "Ls Current (A)",
    "R/L Hz",
    "Flux VpHz",
    "Rs Ohm",
    "Lsq H",
    "Lsd H",
]

# Subset shown on the live terminal dashboard.
DASHBOARD_METRICS: list[str] = [
    "Fault Status",
    "Bus Voltage (V)",
    "Bus Current (A)",
    "Throttle Voltage (V)",
    "Ctrl Temp (C)",
    "M1 Speed (RPM)",
    "M1 Motor Temp (C)",
    "M2 Speed (RPM)",
    "M2 Motor Temp (C)",
    "Brake Enable",
    "Limit Max SCW",
    "Limit Max SCCW",
]


def decode_faults(fault_code: int) -> str:
    if fault_code == 0:
        return "Normal"
    active = [desc for bitmask, desc in FAULT_MAP.items() if fault_code & bitmask]
    return " | ".join(active)


def calculate_crc16(data: bytes | bytearray | list[int]) -> tuple[int, int]:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFF, (crc >> 8) & 0xFF


def build_read_command() -> bytearray:
    frame = bytearray([0xF1, 0x91, 0x08, 0x00, 0x00, 0x00])
    lo, hi = calculate_crc16(frame)
    frame.extend([lo, hi])
    return frame


def _read_f32_be(data: bytes, offset: int) -> float:
    return struct.unpack(">f", data[offset : offset + 4])[0]


def _read_u16_be(data: bytes, offset: int) -> int:
    return struct.unpack(">H", data[offset : offset + 2])[0]


def _map(value: int, table: dict[int, str]) -> str:
    return table.get(value, f"Unknown({value})")


def _swap_motor_triplets(
    m1_speed_krpm: float,
    m1_current: float,
    m1_temp: float,
    m2_speed_krpm: float,
    m2_current: float,
    m2_temp: float,
    *,
    swap: bool,
) -> tuple[float, float, float, float, float, float]:
    if swap:
        return m2_speed_krpm, m2_current, m2_temp, m1_speed_krpm, m1_current, m1_temp
    return m1_speed_krpm, m1_current, m1_temp, m2_speed_krpm, m2_current, m2_temp


def _swap_motor_config(
    m1_mode: int,
    m1_dir: int,
    m2_mode: int,
    m2_dir: int,
    m1_sensor: int,
    m2_sensor: int,
    *,
    swap: bool,
) -> tuple[int, int, int, int, int, int]:
    if swap:
        return m2_mode, m2_dir, m1_mode, m1_dir, m2_sensor, m1_sensor
    return m1_mode, m1_dir, m2_mode, m2_dir, m1_sensor, m2_sensor


def parse_controller_frame(
    data: bytes,
    *,
    prefix: str = "",
    swap_motors: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    if len(data) != 200 or data[0] != 0xF1 or data[1] != 0x91:
        return None, "Invalid frame or incomplete data."

    lo, hi = calculate_crc16(data[:-2])
    if lo != data[198] or hi != data[199]:
        return None, "CRC mismatch."

    fault_code = struct.unpack(">Q", data[62:70])[0]

    raw_m1_speed_krpm = _read_f32_be(data, 86)
    raw_m1_current = _read_f32_be(data, 90)
    raw_m1_temp = _read_f32_be(data, 94)
    raw_m2_speed_krpm = _read_f32_be(data, 98)
    raw_m2_current = _read_f32_be(data, 102)
    raw_m2_temp = _read_f32_be(data, 106)

    m1_krpm, m1_current, m1_temp, m2_krpm, m2_current, m2_temp = _swap_motor_triplets(
        raw_m1_speed_krpm,
        raw_m1_current,
        raw_m1_temp,
        raw_m2_speed_krpm,
        raw_m2_current,
        raw_m2_temp,
        swap=swap_motors,
    )

    m1_mode, m1_dir, m2_mode, m2_dir, m1_sensor, m2_sensor = _swap_motor_config(
        data[24],
        data[25],
        data[26],
        data[27],
        (data[40] >> 4) & 0x0F,
        data[40] & 0x0F,
        swap=swap_motors,
    )

    values: dict[str, Any] = {
        "Fault Status": decode_faults(fault_code),
        "Fault Code": f"0x{fault_code:016X}",
        "Bus Voltage (V)": round(_read_f32_be(data, 70) * 1000.0, 2),
        "Bus Current (A)": round(_read_f32_be(data, 74), 2),
        "Throttle Voltage (V)": round(_read_f32_be(data, 78), 2),
        "Ctrl Temp (C)": round(_read_f32_be(data, 82), 1),
        "M1 Speed (RPM)": round(m1_krpm * 1000.0, 1),
        "M1 Speed (krpm)": round(m1_krpm, 4),
        "M1 Current (A)": round(m1_current, 1),
        "M1 Motor Temp (C)": round(m1_temp, 1),
        "M2 Speed (RPM)": round(m2_krpm * 1000.0, 1),
        "M2 Speed (krpm)": round(m2_krpm, 4),
        "M2 Current (A)": round(m2_current, 1),
        "M2 Motor Temp (C)": round(m2_temp, 1),
        "Brake State Mark": "Enable" if (data[44] & 0x01) else "Disabled",
        "Brake Enable": "On" if (data[45] & 0x01) else "Off",
        "Control Type": _map(data[8], CONTROL_TYPE_MAP),
        "RS485 Address": data[9],
        "RS485 Baud": int.from_bytes(data[10:14], "big"),
        "CAN TX ID": f"0x{int.from_bytes(data[14:18], 'big'):X}",
        "CAN RX ID": f"0x{int.from_bytes(data[18:22], 'big'):X}",
        "CAN Baud": _map(data[22], CAN_BAUD_MAP),
        "CAN Frame Type": _map(data[23], CAN_FRAME_MAP),
        "Send Interval (ms)": _read_u16_be(data, 60),
        "M1 Mode": _map(m1_mode, MOTOR_MODE_MAP),
        "M1 Direction": _map(m1_dir, DIRECTION_MAP),
        "M2 Mode": _map(m2_mode, MOTOR_MODE_MAP),
        "M2 Direction": _map(m2_dir, DIRECTION_MAP),
        "M1 Sensor Type": _map(m1_sensor, SENSOR_TYPE_MAP),
        "M2 Sensor Type": _map(m2_sensor, SENSOR_TYPE_MAP),
        "Pole Pairs": _read_u16_be(data, 28),
        "BMQ Pairs": data[41],
        "Encoder AB Swap": "Yes" if data[39] else "No",
        "Auto Hold": "On" if data[38] else "Off",
        "Rated Speed (RPM)": _read_u16_be(data, 42),
        "Acceleration Pct": _read_u16_be(data, 30),
        "Deceleration Pct": _read_u16_be(data, 32),
        "Kp Speed": _read_u16_be(data, 34),
        "Ki Speed": _read_u16_be(data, 36),
        "Kp Idq": round(_read_f32_be(data, 126), 4),
        "Ki Idq": round(_read_f32_be(data, 130), 4),
        "OverCurrent I (A)": _read_u16_be(data, 54),
        "OverCurrent Time (ms)": _read_u16_be(data, 56),
        "Tim Max I": _read_u16_be(data, 58),
        "Max Bus Current (A)": round(_read_f32_be(data, 110), 1),
        "Max Phase Current (A)": round(_read_f32_be(data, 114), 1),
        "Max Voltage (V)": round(_read_f32_be(data, 118), 1),
        "Min Voltage (V)": round(_read_f32_be(data, 122), 1),
        "Limit Max SCW": round(_read_f32_be(data, 178), 2),
        "Limit Max SCCW": round(_read_f32_be(data, 182), 2),
        "Pick-up Voltage (V)": round(_read_f32_be(data, 134), 2),
        "Keep Voltage (V)": round(_read_f32_be(data, 138), 2),
        "Brake Delay (s)": round(_read_f32_be(data, 142), 2),
        "Drive Downtime (s)": round(_read_f32_be(data, 146), 2),
        "Brake Resistor Voltage (V)": round(_read_f32_be(data, 186), 1),
        "SF Tim Max I": round(_read_f32_be(data, 190), 1),
        "Rs Current (A)": round(_read_f32_be(data, 150), 4),
        "Ls Current (A)": round(_read_f32_be(data, 154), 4),
        "R/L Hz": round(_read_f32_be(data, 158), 2),
        "Flux VpHz": round(_read_f32_be(data, 162), 4),
        "Rs Ohm": round(_read_f32_be(data, 166), 4),
        "Lsq H": round(_read_f32_be(data, 170), 6),
        "Lsd H": round(_read_f32_be(data, 174), 6),
    }

    return {f"{prefix}{key}": val for key, val in values.items()}, "Success"
