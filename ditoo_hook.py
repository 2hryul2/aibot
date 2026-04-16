"""Claude Code Stop hook: display Claude's response on Ditoo device.

This script is called by Claude Code when it finishes responding.
It reads the hook JSON from stdin, extracts the response text,
and sends it to the Ditoo as scrolling text.

The actual Bluetooth communication runs in a detached subprocess
so this hook exits immediately without blocking Claude.
"""

import json
import subprocess
import sys
import os


def main():
    try:
        hook_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    text = hook_data.get("last_assistant_message", "")
    if not text or not text.strip():
        sys.exit(0)

    # Launch display script: claude.bmp → 10s → clock (background)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    display_script = os.path.join(script_dir, "ditoo_stop_display.py")
    subprocess.Popen(
        [sys.executable, display_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=script_dir,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
