from __future__ import annotations

import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import serial

from motor_logger.config import AppConfig, ControllerConfig, load_config
from motor_logger.controller import MotorController, PollResult
from motor_logger.csv_logger import CsvTelemetryLogger, make_controller_row
from motor_logger.display import render_dashboard
from motor_logger.serial_io import connect_controller, reconnect_controller
from motor_logger.session import create_power_cycle_session


class TelemetryApp:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._running = True
        self._controllers: list[MotorController] = []
        self._csv_loggers: dict[str, CsvTelemetryLogger] = {}
        self._session_path: Path | None = None

    def _enabled_controllers(self) -> list[ControllerConfig]:
        ctrls: list[ControllerConfig] = []
        if self._config.front.enabled:
            ctrls.append(self._config.front)
        if self._config.rear.enabled:
            ctrls.append(self._config.rear)
        if not ctrls:
            raise RuntimeError(
                "No controllers enabled — set front_enabled=true or rear_enabled=true in config"
            )
        return ctrls

    def _is_running(self) -> bool:
        return self._running

    def _handle_signal(self, signum: int, _frame: object) -> None:
        print(f"\nReceived signal {signum}, stopping...")
        self._running = False

    def _establish_connections(self) -> bool:
        print("Waiting for serial ports and establishing connections...")
        self._controllers.clear()

        for ctrl in self._enabled_controllers():
            motor = MotorController(
                ctrl,
                self._config.serial_baud,
                self._config.serial_timeout_sec,
            )
            if not connect_controller(
                motor,
                retry_sec=self._config.connect_retry_sec,
                timeout_sec=self._config.port_wait_timeout_sec,
                running=self._is_running,
            ):
                return False
            self._controllers.append(motor)

        if self._config.startup_delay_sec > 0:
            time.sleep(self._config.startup_delay_sec)

        return True

    def _handle_poll_result(self, motor: MotorController, result: PollResult, timestamp: str) -> None:
        if result.needs_reconnect:
            reconnect_controller(motor, self._config.connect_retry_sec)
            return

        if not result.ok:
            return

        logger = self._csv_loggers.get(result.label)
        if logger:
            logger.write_row(make_controller_row(result, timestamp))

    def run(self) -> int:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        session = None
        try:
            if not self._establish_connections():
                return 1

            session = create_power_cycle_session(self._config)
            self._session_path = session.cycle_path

            for ctrl in self._enabled_controllers():
                csv_path = session.csv_paths[ctrl.label]
                self._csv_loggers[ctrl.label] = CsvTelemetryLogger(csv_path)
                print(f"Logging {ctrl.label} -> {csv_path}")

            print(f"Session folder: {session.cycle_path}")
            print(
                f"Listening on {len(self._controllers)} port(s) @ {self._config.poll_hz} Hz "
                f"(CSV rows written only when valid data received) — Ctrl+C to stop\n"
            )

            next_loop = time.perf_counter()
            while self._running:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                results: list[PollResult] = []

                for motor in self._controllers:
                    try:
                        results.append(motor.poll(self._config.read_timeout_sec))
                    except serial.SerialException as exc:
                        print(f"[{motor.label}] Serial error: {exc}")
                        results.append(
                            PollResult(
                                motor.label,
                                False,
                                str(exc),
                                {},
                                needs_reconnect=True,
                            )
                        )

                for motor, result in zip(self._controllers, results):
                    self._handle_poll_result(motor, result, timestamp)

                if self._config.show_dashboard:
                    render_dashboard(
                        self._config,
                        timestamp,
                        results,
                        session.csv_paths,
                        str(session.cycle_path),
                    )

                next_loop += self._config.poll_interval_sec
                sleep_for = next_loop - time.perf_counter()
                if sleep_for > 0:
                    time.sleep(sleep_for)

            return 0

        except serial.SerialException as exc:
            print(f"Serial error: {exc}", file=sys.stderr)
            return 1
        finally:
            for motor in self._controllers:
                motor.close()
            for logger in self._csv_loggers.values():
                logger.close()
            if self._session_path:
                print(f"\nLogging stopped. Data saved under:\n  {self._session_path}")


def main(config_path: Path | None = None) -> int:
    config = load_config(config_path)
    return TelemetryApp(config).run()
