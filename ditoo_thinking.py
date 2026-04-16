"""Show Claude thinking icon on Ditoo Pro.

Called by UserPromptSubmit hook when user sends a prompt.
Shows icon, then launches a background watchdog that reverts to clock
after 30 minutes if no Stop hook interrupts.
"""

import sys
import os
import subprocess


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass

    script_dir = os.path.dirname(os.path.abspath(__file__))

    try:
        import time
        from ditoo_connection import load_config, get_device, send_icon, send_brightness
        config = load_config()
        device = get_device(config)
        send_brightness(device, config.get("brightness", 50))
        send_icon(device, "claude_thinking")
        # 키보드 LED 켜기 + 초록색 회전 효과 (toggle on → next x3)
        device.send_keyboard(0)  # toggle on
        time.sleep(0.1)
        for _ in range(3):
            device.send_keyboard(1)
            time.sleep(0.1)
        device.disconnect()
    except Exception:
        pass

    # Launch 30-min watchdog in background
    watchdog = os.path.join(script_dir, "ditoo_watchdog.py")
    subprocess.Popen(
        [sys.executable, watchdog],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=script_dir,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
