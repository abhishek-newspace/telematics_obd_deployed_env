from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import serial

from motor_logger.config import ControllerConfig
from motor_logger.protocol import build_read_command, parse_controller_frame


@dataclass
class PollResult:
    label: str
    ok: bool
    message: str
    fields: dict[str, Any]
    needs_reconnect: bool = False


class MotorController:
    def __init__(
        self,
        config: ControllerConfig,
        baud: int,
        timeout_sec: float,
    ) -> None:
        self._config = config
        self._baud = baud
        self._timeout_sec = timeout_sec
        self._serial: serial.Serial | None = None
        self._read_cmd = build_read_command()
        self._prefix = f"{config.label} "

    @property
    def label(self) -> str:
        return self._config.label

    @property
    def device(self) -> str:
        return self._config.device

    def open(self) -> None:
        self._serial = serial.Serial(
            self._config.device,
            self._baud,
            timeout=self._timeout_sec,
        )

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._serial = None

    def reset_buffer(self) -> None:
        if self._serial:
            self._serial.reset_input_buffer()

    def prepare(self, startup_delay_sec: float) -> None:
        self.reset_buffer()
        if startup_delay_sec > 0:
            time.sleep(startup_delay_sec)

    def poll(self, read_timeout_sec: float) -> PollResult:
        if not self._serial or not self._serial.is_open:
            return PollResult(self.label, False, "Serial not open", {}, needs_reconnect=True)

        try:
            self._serial.write(self._read_cmd)
        except serial.SerialException as exc:
            return PollResult(self.label, False, str(exc), {}, needs_reconnect=True)

        deadline = time.perf_counter() + read_timeout_sec
        while self._serial.in_waiting < 200 and time.perf_counter() < deadline:
            time.sleep(0.005)

        waiting = self._serial.in_waiting
        if waiting < 200:
            if waiting:
                self._serial.read(waiting)
            self._serial.reset_input_buffer()
            return PollResult(self.label, False, "No data", {})

        try:
            raw = self._serial.read(200)
        except serial.SerialException as exc:
            return PollResult(self.label, False, str(exc), {}, needs_reconnect=True)

        parsed, message = parse_controller_frame(
            raw,
            prefix=self._prefix,
            swap_motors=self._config.swap_motors,
        )

        if parsed is None:
            self._serial.reset_input_buffer()
            return PollResult(self.label, False, message, {})

        return PollResult(self.label, True, message, parsed)
