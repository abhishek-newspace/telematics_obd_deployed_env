from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from motor_logger.config import AppConfig, ControllerConfig


@dataclass
class PowerCycleSession:
    cycle_path: Path
    csv_paths: dict[str, Path] = field(default_factory=dict)
    manifest_path: Path | None = None
    created_at: str = ""


def _folder_timestamp() -> str:
    now = datetime.now()
    ms = now.microsecond // 1000
    return now.strftime("%Y%m%d_%H%M%S") + f"_{ms:03d}"


def _display_timestamp() -> str:
    now = datetime.now()
    ms = now.microsecond // 1000
    return now.strftime("%d-%m-%Y %H:%M:%S") + f".{ms:03d}.0"


def _enabled_controllers(config: AppConfig) -> list[ControllerConfig]:
    ctrls: list[ControllerConfig] = []
    if config.front.enabled:
        ctrls.append(config.front)
    if config.rear.enabled:
        ctrls.append(config.rear)
    return ctrls


def _controller_line(ctrl: ControllerConfig) -> str:
    if not ctrl.enabled:
        return f"{ctrl.label}=disabled"
    return (
        f"{ctrl.label}={ctrl.device} file={ctrl.csv_filename} "
        f"swap_motors={str(ctrl.swap_motors).lower()}"
    )


def create_power_cycle_session(config: AppConfig) -> PowerCycleSession:
    folder_name = config.power_cycle_prefix + _folder_timestamp()
    cycle_path = config.log_base_dir / folder_name
    cycle_path.mkdir(parents=True, exist_ok=True)

    created_at = _display_timestamp()
    csv_paths = {
        ctrl.label: cycle_path / ctrl.csv_filename
        for ctrl in _enabled_controllers(config)
    }

    session = PowerCycleSession(
        cycle_path=cycle_path,
        csv_paths=csv_paths,
        manifest_path=cycle_path / "session_manifest.txt",
        created_at=created_at,
    )
    write_session_manifest(config, session)
    return session


def write_session_manifest(config: AppConfig, session: PowerCycleSession) -> None:
    log_files = ",".join(path.name for path in session.csv_paths.values())
    lines = [
        f"ugv_id={config.ugv_id}",
        f"created_at={session.created_at}",
        "log_timestamp_mode=jetson_system_clock",
        "protocol=MX_ES_DriverCan_UART_F1",
        f"serial_baud={config.serial_baud}",
        f"poll_hz={config.poll_hz}",
        _controller_line(config.front),
        _controller_line(config.rear),
        f"log_files={log_files}",
        f"retrieval=copy folder {config.log_base_dir.name}/{session.cycle_path.name} for offline analysis",
    ]
    assert session.manifest_path is not None
    session.manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
