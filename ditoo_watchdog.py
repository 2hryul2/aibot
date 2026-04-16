"""Watchdog: wait 30 minutes, then show clock if no response came.

Each time ditoo_thinking.py runs, it writes a new timestamp to .watchdog file
and launches this script. Each time ditoo_send.py runs (Stop hook), it deletes
the .watchdog file. This script checks after 30 min if its timestamp is still
current — if so, no response came, revert to clock.
"""

import os
import sys
import time
import uuid

WATCHDOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".watchdog")
TIMEOUT = 30 * 60  # 30 minutes


def main():
    # Write unique ID so we can check if we're still the latest watchdog
    my_id = str(uuid.uuid4())
    with open(WATCHDOG_FILE, "w") as f:
        f.write(my_id)

    time.sleep(TIMEOUT)

    # Check if our ID is still current (no new prompt or response happened)
    try:
        with open(WATCHDOG_FILE, "r") as f:
            current_id = f.read().strip()
    except FileNotFoundError:
        return  # File deleted by ditoo_send.py, response was received

    if current_id != my_id:
        return  # A newer watchdog replaced us

    # No response in 30 min — revert to clock
    try:
        from ditoo_connection import load_config, get_device, send_clock
        config = load_config()
        device = get_device(config)
        send_clock(device, style=0)
        device.disconnect()
    except Exception:
        pass

    try:
        os.remove(WATCHDOG_FILE)
    except Exception:
        pass


if __name__ == "__main__":
    main()
