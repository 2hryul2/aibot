"""Send an image to the Ditoo Pro display.

Usage: python ditoo_image.py "path/to/image.png"
"""

import sys
import os
import logging
import filelock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(SCRIPT_DIR, ".ditoo.lock")


def main():
    if len(sys.argv) < 2:
        print("Usage: python ditoo_image.py <image_path>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.isfile(image_path):
        print(f"File not found: {image_path}")
        sys.exit(1)

    logging.basicConfig(level=logging.WARNING)

    try:
        lock = filelock.FileLock(LOCK_FILE, timeout=5)
        with lock:
            from ditoo_connection import load_config, get_device, send_image, send_brightness

            config = load_config()
            device = get_device(config)
            send_brightness(device, config.get("brightness", 50))
            send_image(device, image_path)
            device.disconnect()
            print(f"Image sent: {image_path}")
    except filelock.Timeout:
        print("Device is busy (another instance is sending)")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
