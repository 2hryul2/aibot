"""Show clock on Ditoo Pro.

Called after response text finishes, or for idle display.
Usage: python ditoo_clock.py
"""

import sys

def main():
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
