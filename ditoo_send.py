"""Background sender: connects to Ditoo and displays text.

Called by ditoo_hook.py as a detached subprocess.
Usage: python ditoo_send.py "text to display"
"""

import sys
import os
import logging
import filelock

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK_FILE = os.path.join(SCRIPT_DIR, ".ditoo.lock")
WATCHDOG_FILE = os.path.join(SCRIPT_DIR, ".watchdog")


def extract_display_text(text, max_length=80):
    """Extract a short displayable string from Claude's response."""
    text = text.strip()

    # If it starts with a code block, show a status indicator
    if text.startswith("```"):
        return "Code ready"

    # Remove markdown formatting
    for prefix in ["# ", "## ", "### ", "- ", "* "]:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break

    # Take first line only
    first_line = text.split("\n")[0].strip()
    if not first_line:
        return "Done"

    # Truncate to max length
    if len(first_line) > max_length:
        first_line = first_line[:max_length - 3] + "..."

    return first_line


def main():
    if len(sys.argv) < 2:
        sys.exit(1)

    raw_text = sys.argv[1]
    display_text = extract_display_text(raw_text)

    if not display_text:
        sys.exit(0)

    logging.basicConfig(level=logging.WARNING)

    # Cancel watchdog — response arrived
    try:
        os.remove(WATCHDOG_FILE)
    except FileNotFoundError:
        pass

    try:
        lock = filelock.FileLock(LOCK_FILE, timeout=5)
        with lock:
            import time
            from ditoo_connection import load_config, get_device, send_text, send_brightness, send_clock

            from ditoo_connection import send_icon
            config = load_config()
            device = get_device(config)
            send_brightness(device, config.get("brightness", 50))
            send_icon(device, "claude_done")
            # 키보드 LED 끄기
            device.send_keyboard(0)  # toggle off
            time.sleep(5)
            send_clock(device, style=0)
            device.disconnect()
    except filelock.Timeout:
        pass  # Another instance is already sending; skip
    except Exception:
        pass  # Bluetooth errors should not propagate


if __name__ == "__main__":
    main()
