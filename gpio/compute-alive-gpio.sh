#!/bin/bash
# Drive reComputer R21xx industrial DO as a "compute alive" signal.
# HIGH (transistor ON) while the OS is up; LOW after clean shutdown so an
# external controller can cut power safely.
#
# Uses ONLY the industrial DO bank on I2C expander 1-0021 (DO_1..DO_4).
# That bank is electrically separate from:
#   - CAN  (MCP2518FD SPI → can_control / can_auxiliary)
#   - UART (WCH ttyACM* RS232/RS485, USB ttyUSB motors/actuator)
#   - onboard LEDs / buzzer / LoRa reset lines on the same expander
#
# Default line: DO_1 (terminal silkscreen DO1 / G_DO)
# Override: COMPUTE_ALIVE_DO=DO_1|DO_2|DO_3|DO_4
#
# Usage: compute-alive-gpio.sh on|off|status

set -euo pipefail

DO_NAME="${COMPUTE_ALIVE_DO:-DO_1}"
CHIP_LABEL="${COMPUTE_ALIVE_CHIP_LABEL:-1-0021}"
CHIP_DEV="${COMPUTE_ALIVE_CHIP_DEV:-/dev/gpiochip15}"

# Line offsets on I2C expander 1-0021 (confirmed on this CM5 image)
declare -A DO_OFFSET=(
  [DO_1]=15
  [DO_2]=14
  [DO_3]=13
  [DO_4]=12
)

die() { echo "compute-alive-gpio: $*" >&2; exit 1; }

resolve_gpio_num() {
  local offset="${DO_OFFSET[$DO_NAME]:-}"
  [[ -n "$offset" ]] || die "unknown DO '$DO_NAME' (use DO_1..DO_4)"

  local chipdir base
  for chipdir in /sys/class/gpio/gpiochip*; do
    [[ -f "$chipdir/label" ]] || continue
    if [[ "$(cat "$chipdir/label")" == "$CHIP_LABEL" ]]; then
      base="$(cat "$chipdir/base")"
      echo $((base + offset))
      return 0
    fi
  done
  die "GPIO chip label '$CHIP_LABEL' not found"
}

# Abort if another kernel consumer already owns this DO line (never touch CAN/UART).
assert_do_safe() {
  local offset="${DO_OFFSET[$DO_NAME]}"
  python3 - "$CHIP_DEV" "$offset" "$DO_NAME" <<'PY'
import sys
import gpiod

chip_path, offset_s, do_name = sys.argv[1], sys.argv[2], sys.argv[3]
offset = int(offset_s)
chip = gpiod.Chip(chip_path)
info = chip.get_line_info(offset)
name = info.name or ""
if name != do_name:
    raise SystemExit(
        f"compute-alive-gpio: refused — offset {offset} is '{name}', expected '{do_name}' "
        f"(wrong chip/line; will not touch CAN/UART pins)"
    )
if info.used and info.consumer not in (None, "", "sysfs", "compute-alive"):
    raise SystemExit(
        f"compute-alive-gpio: refused — {do_name} already used by consumer "
        f"'{info.consumer}' (leaving pin alone)"
    )
print(f"compute-alive-gpio: safety ok — {do_name} free on {chip_path} offset {offset}")
PY
}

export_out() {
  local num="$1"
  if [[ ! -d "/sys/class/gpio/gpio${num}" ]]; then
    echo "$num" > /sys/class/gpio/export
  fi
  # Wait briefly for udev/sysfs nodes
  local i
  for i in 1 2 3 4 5 6 7 8 9 10; do
    [[ -e "/sys/class/gpio/gpio${num}/direction" ]] && break
    sleep 0.05
  done
  echo out > "/sys/class/gpio/gpio${num}/direction"
}

set_value() {
  local num="$1" val="$2"
  echo "$val" > "/sys/class/gpio/gpio${num}/value"
}

cmd="${1:-}"
num="$(resolve_gpio_num)"

case "$cmd" in
  on)
    assert_do_safe
    export_out "$num"
    set_value "$num" 1
    echo "compute-alive-gpio: ${DO_NAME} (gpio${num}) -> 1 (ON / system up)"
    ;;
  off)
    assert_do_safe
    if [[ ! -d "/sys/class/gpio/gpio${num}" ]]; then
      export_out "$num"
    else
      echo out > "/sys/class/gpio/gpio${num}/direction"
    fi
    set_value "$num" 0
    echo "compute-alive-gpio: ${DO_NAME} (gpio${num}) -> 0 (OFF / safe to cut power)"
    ;;
  status)
    assert_do_safe || true
    if [[ -e "/sys/class/gpio/gpio${num}/value" ]]; then
      echo "${DO_NAME} gpio${num}=$(cat "/sys/class/gpio/gpio${num}/value")"
    else
      echo "${DO_NAME} gpio${num}=unexported"
    fi
    ;;
  *)
    die "usage: $0 on|off|status"
    ;;
esac
