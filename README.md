# Motor Controller UART Telemetry Logger

Python service for **NVIDIA Jetson** that polls Mei Xin motor drive controllers over **USB-serial (RS-485/RS-232)** and logs telemetry to CSV files. Each run creates a new **power-cycle session folder**, matching the pattern used by the Iris telematics stack.

Compatible with the **MX_ES_DriverCan TV4** vendor protocol (`0xF1` frames, function `0x91` read @ **38400 baud**).

---

## What it does

```
Jetson  ──USB-serial──►  Motor controller (Front / Rear)
         │
         └── Poll every 200 ms (5 Hz default):
               TX  8 bytes  →  F1 91 08 ...  (read parameters)
               RX  200 bytes ←  live data + config snapshot
         │
         └── Write CSV row **only when a valid 200-byte frame is received**
         │
         └── On wake/start: wait for /dev/ttyUSB*, connect with retry, then listen
               data/power_cycle_<timestamp>/
```

The motor controller does **not** stream data on its own. The logger must **send a read command every cycle** to receive a fresh 200-byte frame.

---

## Project layout

```
motor-controller-log/
├── config/
│   └── motor_logger.conf       # Ports, baud, poll rate, file names
├── data/                       # Runtime logs (gitignored except .gitkeep)
│   └── power_cycle_YYYYMMDD_HHMMSS_mmm/
│       ├── session_manifest.txt
│       ├── motor_front_telemetry.csv
│       └── motor_rear_telemetry.csv   # when rear_enabled=true
├── motor_logger/
│   ├── app.py                  # Main loop, signals
│   ├── config.py               # Config loader + env overrides
│   ├── protocol.py             # CRC, frame parse, field map
│   ├── controller.py           # Serial poll per drive
│   ├── csv_logger.py           # Per-controller CSV writer
│   ├── session.py              # Power-cycle folder + manifest
│   ├── serial_io.py            # Port wait, connect/reconnect retry
│   └── display.py              # Live terminal dashboard
├── Dockerfile
├── run_logger.py               # Entry point
├── requirements.txt
└── README.md
```

---

## Requirements

### Hardware

- Jetson with USB port
- USB-to-serial adapter (Prolific PL2303, CH340, FTDI, or CP210x)
- RS-485 or RS-232 link to the motor controller (match your drive wiring)
- Motor controller **powered on**

### Software (Jetson / Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-serial
```

**USB driver note:** If `lsusb` shows the adapter but `/dev/ttyUSB*` is missing, you may need the kernel module (e.g. `pl2303` or `ch341`). See `~/Desktop/l4t-kernel-build/` scripts on this Jetson.

### Permissions

```bash
sudo usermod -aG dialout $USER
# log out and back in
```

---

## Installation

```bash
cd ~/Desktop/motor-controller-log
pip3 install -r requirements.txt
```

---

## Configuration

Edit `config/motor_logger.conf`:

| Setting | Description | Default |
|---------|-------------|---------|
| `front_enabled` | Log front controller | `true` |
| `front_serial` | Serial device | `/dev/ttyUSB0` |
| `front_swap_motors` | Swap M1/M2 byte mapping (PCB quirk) | `true` |
| `front_csv_filename` | Output CSV name | `motor_front_telemetry.csv` |
| `rear_enabled` | Log rear controller | `false` |
| `rear_serial` | Second port | `/dev/ttyUSB1` |
| `serial_baud` | UART baud rate | `38400` |
| `poll_hz` | Poll rate | `5` |
| `port_wait_timeout_sec` | Wait for USB device node (`0` = forever) | `0` |
| `connect_retry_sec` | Retry interval for open/reconnect | `5` |
| `log_base_dir` | Log root | `data` |

### Environment overrides

Any config key can be overridden without editing the file:

```bash
MOTOR_LOG_FRONT_SERIAL=/dev/ttyUSB2 python3 run_logger.py
MOTOR_LOG_REAR_ENABLED=true MOTOR_LOG_REAR_SERIAL=/dev/ttyUSB3 python3 run_logger.py
```

---

## Usage

### Start logging

```bash
cd ~/Desktop/motor-controller-log
python3 run_logger.py
```

Or:

```bash
python3 -m motor_logger
```

Stop with **Ctrl+C**. CSV files are flushed after every row.

**Logging rule:** rows are written **only on successful parses**. Timeouts, CRC errors, and missing data are **not** written to CSV (the process keeps polling).

On startup the logger **waits for serial devices** (`port_wait_timeout_sec=0` waits forever), opens ports with retry, then listens continuously.

### Docker (recommended for wake-and-log)

Compose file on Desktop:

```bash
cd ~/Desktop
docker compose -f motor-controller-docker-compose.yml build
docker compose -f motor-controller-docker-compose.yml up -d
```

Logs:

```bash
docker logs -f motor_logger
```

Stop:

```bash
docker compose -f motor-controller-docker-compose.yml down
```

Edit `motor-controller-log/config/motor_logger.conf` for your `ttyUSB` port numbers. Data is stored in `motor-controller-log/data/`.

**USB hot-plug:** compose mounts `/dev:/dev` and adds `device_cgroup_rules` for USB-serial (`ttyUSB*`, major 188). Without the cgroup rule, the port is visible inside the container but opening it fails with `Operation not permitted`. Do **not** use `devices: /dev/ttyUSB0` alone — Docker refuses to start if that node is missing at boot.

The container uses `restart: unless-stopped` so it starts on boot, waits for USB ports, connects, and logs when motor data arrives.

### Output per session

Each time you start the logger (typically one **power cycle** / boot session):

```
data/power_cycle_20260624_174200_997/
├── session_manifest.txt
├── motor_front_telemetry.csv
└── motor_rear_telemetry.csv      # if rear enabled
```

`session_manifest.txt` records UGV id, timestamps, serial ports, and file names for offline retrieval.

### Find the correct serial port

```bash
lsusb
ls -la /dev/ttyUSB*
```

Unplug the motor adapter, note which `ttyUSB` disappears, plug back in — that is your port. Avoid sharing a port with telematics CAN adapters.

---

## Logged data

Each CSV row is one poll (~5 Hz by default) with **59 telemetry/config fields** from the 200-byte `0x91` response, including:

- **Live:** fault status, bus voltage/current, throttle, controller temp, M1/M2 speed, current, motor temp, brake status
- **Limits:** max SCW/SCCW, max bus/phase current, max/min voltage, overcurrent thresholds
- **Comms:** RS485/CAN settings, send interval
- **Motor config:** mode, direction, sensor type, pole pairs, accel/decel, PID gains, Rs/Ls/flux parameters

The live terminal dashboard shows a **subset** of key fields; the CSV contains the full set.

Fields such as **Ref_A** and **SpeedRef_krpm** (motor start / load-test commands) are **not** in the normal `0x91` poll and are not logged continuously.

---

## How the protocol works

### Read command (PC → drive)

8 bytes, CRC-16/Modbus:

```
F1 91 08 00 00 00 [CRC_LO] [CRC_HI]
```

Built by `motor_logger.protocol.build_read_command()`.

### Response (drive → PC)

200 bytes: header `F1 91`, payload bytes 2–197, CRC at 198–199.

The parser (`parse_controller_frame`) validates length, header, and CRC, then decodes big-endian floats and integers per the MX_ES_DriverCan byte map.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `No such file: /dev/ttyUSB0` | Adapter not plugged or driver missing | Check `lsusb`, load `pl2303`/`ch341`, replug USB; Docker uses `/dev` mount so container still starts and waits |
| `Permission denied` | Not in `dialout` | `sudo usermod -aG dialout $USER`, re-login |
| `Timeout/Incomplete` / no CSV rows | Motor not replying yet | Logger keeps listening; check power/wiring; rows appear only when data is valid |
| `CRC mismatch` | Garbled frame | Not logged to CSV; polling continues |
| Port busy | Another process using serial | `sudo lsof /dev/ttyUSB0`, stop other loggers |
| Rear errors with one adapter | `rear_enabled=true` but no second port | Set `rear_enabled=false` |

### Quick hardware test

```bash
python3 - <<'EOF'
import serial, time
from motor_logger.protocol import build_read_command

with serial.Serial("/dev/ttyUSB0", 38400, timeout=1.0) as ser:
    time.sleep(2)
    ser.reset_input_buffer()
    ser.write(build_read_command())
    time.sleep(0.3)
    print("bytes:", ser.in_waiting)
EOF
```

Expect `bytes: 200` when hardware and wiring are correct.

---

## Running at boot

Use Docker with `restart: unless-stopped` (see `~/Desktop/motor-controller-docker-compose.yml`), or create a systemd user service for `run_logger.py`. The app waits for USB devices before opening ports (`port_wait_timeout_sec=0`).

---

## Related projects on this Jetson

| Project | Role |
|---------|------|
| `motor-controller/MX_ES_DriverCan_TV4_01_WD/` | Windows vendor GUI (config / firmware) |
| `l4t-kernel-build/` | USB-serial kernel modules (`pl2303`, `ch341`) |
| `telematics_v4.0/` | CAN bus logging (separate USB ports) |

Do not assign the same `/dev/ttyUSBx` to telematics and motor logging at the same time.
