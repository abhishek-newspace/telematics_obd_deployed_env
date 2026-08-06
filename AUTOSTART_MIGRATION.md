# Autostart Migration

This deploy folder uses only two helper scripts for autostart:

- `install-autostart.sh`
- `remove-autostart.sh`

Services remain independent:

- `telematics.service` runs as a system service
- `obd-apps.service` runs as a user service

## Files involved

- `telematics/telematics.service`
- `telematics/start.sh`
- `obd/obd-apps.service`
- `obd/start.sh`
- `install-autostart.sh`
- `remove-autostart.sh`

## Install on a new system

1. Copy this deploy folder to the new machine.
2. Make sure Docker works for the target user.
3. If `docker compose` works only for the user, make sure the plugin exists at:

```bash
~/.docker/cli-plugins/docker-compose
```

4. Run:

```bash
cd /path/to/telematics_obd_deployed_env
sudo ./install-autostart.sh
```

5. Start services:

```bash
sudo systemctl start telematics.service
systemctl --user start obd-apps.service
```

## Stop and remove autostart

```bash
cd /path/to/telematics_obd_deployed_env
sudo ./remove-autostart.sh
```

## Verify

System service:

```bash
systemctl status telematics.service
systemctl is-enabled telematics.service
```

User service:

```bash
systemctl --user status obd-apps.service
systemctl --user is-enabled obd-apps.service
```

Containers:

```bash
docker ps --filter name=telematics_server
docker ps --filter name=obd
```

## Paths to update on another system

If the username or deploy path changes, update these files:

- `telematics/telematics.service`
- `obd/obd-apps.service`
- `obd/start.sh`
- `install-autostart.sh`
- `remove-autostart.sh`

Typical replacements:

- `/home/testing/...` -> new home path
- `testing` -> new username

## Notes

- `telematics.service` is enabled under `multi-user.target`.
- `obd-apps.service` is enabled under the user `default.target`.
- OBD still depends on the display/X11/NVIDIA environment defined in `obd/start.sh`.
