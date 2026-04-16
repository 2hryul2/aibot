"""Stop hook display: show claude.bmp for 10 seconds, then revert to clock.

Runs as a detached background process so the hook exits immediately.
"""

import os
import sys
import time


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))

    try:
        from ditoo_connection import load_config, get_device, send_image, send_clock
        config = load_config()
        device = get_device(config)

        image_path = os.path.join(script_dir, "claude.bmp")
        send_image(device, image_path, config)
        device.disconnect()
    except Exception:
        pass

    time.sleep(5)

    try:
        from ditoo_connection import load_config, get_device, send_clock
        config = load_config()
        device = get_device(config)
        send_clock(device, style=0)
        device.disconnect()
    except Exception:
        pass


if __name__ == "__main__":
    main()
