# CM5 / reComputer R21xx — required udev & .link files

## udev (single file) → `/etc/udev/rules.d/`

| File | Purpose |
|------|---------|
| **`99-telematics-cm5.rules`** | All telematics udev: CAN rename helpers, USB-CAN / motor / VE symlinks, ModemManager ignore |

## systemd `.link` → `/etc/systemd/network/` (not udev)

| File | Purpose |
|------|---------|
| `10-telematics-eth-cm5.link` | USB SMSC → **`telematics_eth`** |
| `10-eth1-cm5-onboard.link` | CM5 GEM → **`eth1`** |
| `10-telematics-can-control-cm5.link` | MCP2518FD CS0 → **`can_control`** |
| `10-telematics-can-auxiliary-cm5.link` | MCP2518FD CS1 → **`can_auxiliary`** |

## helpers

| File | Purpose |
|------|---------|
| `cm5-can-up.sh` | Bring up SocketCAN |
| `telematics-can-rename.sh` | Rename helper |
| `telematics-can-names-cm5.service` | systemd unit |
| `sync-cm5-udev.sh` | Install to `/etc` and remove old split rules |

```bash
sudo bash ~/Desktop/telematics_obd_deployed_env/udev/sync-cm5-udev.sh
```
