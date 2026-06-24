from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import serial
from motor_logger.controller import MotorController


def wait_for_device(device: str, poll_sec: float, timeout_sec: float) -> bool:
    """Block until device node exists (timeout_sec=0 waits forever)."""
    deadline = None if timeout_sec <= 0 else time.monotonic() + timeout_sec
    while deadline is None or time.monotonic() < deadline:
        if Path(device).exists():
            return True
        time.sleep(poll_sec)
    return False


def connect_controller(
    motor: MotorController,
    *,
    retry_sec: float,
    timeout_sec: float,
    running: Callable[[], bool],
) -> bool:
    """Wait for device node, then retry open until success or timeout."""
    device = motor.device
    if not wait_for_device(device, retry_sec, timeout_sec):
        print(f"[{motor.label}] Timed out waiting for {device} to appear")
        return False

    deadline = None if timeout_sec <= 0 else time.monotonic() + timeout_sec
    while running():
        try:
            motor.open()
            motor.reset_buffer()
            print(f"[{motor.label}] Connected on {device}")
            return True
        except serial.SerialException as exc:
            print(f"[{motor.label}] Connect failed ({device}): {exc} — retry in {retry_sec}s")
            motor.close()
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(retry_sec)
    return False


def reconnect_controller(motor: MotorController, retry_sec: float) -> bool:
    motor.close()
    time.sleep(retry_sec)
    try:
        motor.open()
        motor.reset_buffer()
        print(f"[{motor.label}] Reconnected on {motor.device}")
        return True
    except serial.SerialException as exc:
        print(f"[{motor.label}] Reconnect failed: {exc}")
        motor.close()
        return False
