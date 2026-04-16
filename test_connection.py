"""Test script to verify Bluetooth connection to Ditoo device.

Run: python test_connection.py
Expected: "Hello Claude" scrolls on the Ditoo display.
"""

import sys
import time
from ditoo_connection import load_config, get_device, send_text, send_brightness

def main():
    config = load_config()
    print(f"Connecting to Ditoo at {config['mac']} (port {config.get('port', 1)})...")

    try:
        device = get_device(config)
        print("Connected!")

        send_brightness(device, config.get("brightness", 50))
        print("Brightness set.")

        send_text(device, "Hello Claude", config)
        print("Text sent! Check your Ditoo display.")

        time.sleep(5)
        device.disconnect()
        print("Disconnected. Test complete.")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
