from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class ControllerConfig:
    enabled: bool
    device: str
    swap_motors: bool
    label: str
    csv_filename: str


@dataclass
class AppConfig:
    ugv_id: str
    log_base_dir: Path
    power_cycle_prefix: str
    serial_baud: int
    poll_hz: float
    startup_delay_sec: float
    read_timeout_sec: float
    serial_timeout_sec: float
    port_wait_timeout_sec: float
    connect_retry_sec: float
    front: ControllerConfig
    rear: ControllerConfig
    show_dashboard: bool

    @property
    def poll_interval_sec(self) -> float:
        return 1.0 / self.poll_hz


def _apply_env(key: str, value: str) -> str:
    env_key = "MOTOR_LOG_" + key.upper()
    return os.environ.get(env_key, value)


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or (_project_root() / "config" / "motor_logger.conf")
    values: dict[str, str] = {}

    if cfg_path.is_file():
        with cfg_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                values[key.strip()] = _apply_env(key.strip(), val.strip())
    else:
        values = {}

    def get(key: str, default: str) -> str:
        return _apply_env(key, values.get(key, default))

    root = _project_root()
    log_base = Path(get("log_base_dir", "data"))
    if not log_base.is_absolute():
        log_base = root / log_base

    return AppConfig(
        ugv_id=get("ugv_id", "UGV_IRIS_DEFAULT_01"),
        log_base_dir=log_base,
        power_cycle_prefix=get("log_power_cycle_prefix", "power_cycle_"),
        serial_baud=int(get("serial_baud", "38400")),
        poll_hz=float(get("poll_hz", "5")),
        startup_delay_sec=float(get("startup_delay_sec", "2")),
        read_timeout_sec=float(get("read_timeout_sec", "0.15")),
        serial_timeout_sec=float(get("serial_timeout_sec", "1.0")),
        port_wait_timeout_sec=float(get("port_wait_timeout_sec", "0")),
        connect_retry_sec=float(get("connect_retry_sec", "5")),
        front=ControllerConfig(
            enabled=_parse_bool(get("front_enabled", "true")),
            device=get("front_serial", "/dev/ttyUSB0"),
            swap_motors=_parse_bool(get("front_swap_motors", "true")),
            label=get("front_label", "Front"),
            csv_filename=get("front_csv_filename", "motor_front_telemetry.csv"),
        ),
        rear=ControllerConfig(
            enabled=_parse_bool(get("rear_enabled", "false")),
            device=get("rear_serial", "/dev/ttyUSB1"),
            swap_motors=_parse_bool(get("rear_swap_motors", "false")),
            label=get("rear_label", "Rear"),
            csv_filename=get("rear_csv_filename", "motor_rear_telemetry.csv"),
        ),
        show_dashboard=_parse_bool(get("show_dashboard", "true")),
    )
