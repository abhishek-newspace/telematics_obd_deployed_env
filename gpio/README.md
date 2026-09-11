# Compute-alive DO (safe external power cut)

Drives one reComputer R21xx industrial **DO** pin:

| OS state | DO level | Meaning for external cut-off |
|----------|----------|------------------------------|
| Running  | **1** (transistor ON) | Compute is up — keep power |
| Clean shutdown / `systemctl stop` | **0** (transistor OFF) | Safe to cut power |

Default pin: **DO1** (line name `DO_1` on I2C expander `1-0021`, sysfs gpio642 on this image).

**Isolation (verified on this unit):**
- **Not CAN** — `can_control` / `can_auxiliary` are MCP2518FD on SPI; actuator CAN is USB `ttyUSB`.
- **Not UART** — RS232/RS485 are WCH `ttyACM*`; motors/charger are USB serial.
- **DO_1..DO_4 are currently free** (no kernel consumer). Script refuses to run if the chosen DO is already claimed or the line name does not match.
- Does **not** touch expander lines used elsewhere (`CH342_RST`, LEDs, `EEP_WP`, LoRa resets, `RS485_POWER_EN`, buzzer).

Wire the external controller across **DO1** and **G_DO** (transistor output, &lt;60 V DC, ≤500 mA). Treat transistor **OFF** as “safe to cut”; add a short delay (1–2 s) after LOW before removing supply.

## Install

```bash
cd ~/Desktop/telematics_obd_deployed_env/gpio
sudo install -m 755 compute-alive-gpio.sh /usr/local/sbin/compute-alive-gpio.sh
sudo install -m 644 compute-alive-gpio.service /etc/systemd/system/compute-alive-gpio.service
sudo systemctl daemon-reload
sudo systemctl enable --now compute-alive-gpio.service
sudo /usr/local/sbin/compute-alive-gpio.sh status
```

## Change DO pin

```bash
sudo systemctl edit compute-alive-gpio.service
```

Add:

```ini
[Service]
Environment=COMPUTE_ALIVE_DO=DO_2
```

Then `sudo systemctl restart compute-alive-gpio.service`.

## Manual test

```bash
sudo compute-alive-gpio.sh on     # should energize DO load / show ON
sudo compute-alive-gpio.sh off    # should release — external cut logic may fire
sudo compute-alive-gpio.sh on
```

## Notes

- This is **not** the UPS detect input (GPIO16). That path *requests* shutdown when DC fails; this DO *announces* that shutdown finished.
- After the SoC fully loses power, the expander usually leaves the transistor **OFF** (same as low) — a reasonable failsafe if the CPU crashes, but prefer waiting for the deliberate ExecStop LOW when possible.
- Existing telematics `VCU_PWR_OFF_REQ2` → `shutdown -h now` will automatically run ExecStop and drop this pin.
