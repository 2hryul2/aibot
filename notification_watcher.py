"""Windows Notification Watcher for Ditoo Pro.

Monitors:
1. Claude Desktop — via Windows notification DB polling (wpndatabase.db)
2. KakaoTalk — via PID-scoped SetWinEventHook (KakaoTalkShadowWndClass CREATE)

Runs as a system tray icon with right-click menu (Start/Stop/Quit).

Usage:
  python notification_watcher.py            Run with tray icon
  python notification_watcher.py --install   Register as startup program
  python notification_watcher.py --uninstall Remove from startup
"""

import ctypes
import ctypes.wintypes
import os
import sys
import time
import sqlite3
import shutil
import tempfile
import logging
import threading

import win32gui
import win32process
import pystray
from PIL import Image

user32 = ctypes.windll.user32

# ── Config ──
CLAUDE_POLL_INTERVAL = 3  # seconds
DITOO_DISPLAY_SECONDS = 5
COOLDOWN_SECONDS = 10

# Claude Desktop
CLAUDE_HANDLER_ID = 404

# KakaoTalk
KAKAO_WINDOW_CLASS = "EVA_Window_Dblclk"
KAKAO_SHADOW_CLASS = "KakaoTalkShadowWndClass"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Microsoft", "Windows", "Notifications", "wpndatabase.db",
)

# ── Logging ──
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "claude-ditoo", "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    filename=os.path.join(LOG_DIR, "notification_watcher.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ── WinEvent constants ──
EVENT_OBJECT_CREATE = 0x8000
WINEVENT_OUTOFCONTEXT = 0x0000

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.HWND,
    ctypes.wintypes.LONG,
    ctypes.wintypes.LONG,
    ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD,
)

# ── Watcher state ──
_watcher_running = False
_watcher_thread = None
_stop_event = threading.Event()


def _get_pythonw():
    """Get pythonw.exe path (no console window) from current Python."""
    exe_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(exe_dir, "pythonw.exe")
    if os.path.isfile(pythonw):
        return pythonw
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if os.path.isfile(pythonw):
        return pythonw
    return None


def install_startup():
    """Register as Windows startup program via registry (HKCU)."""
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "ClaudeDitooNotifier"

    pythonw = _get_pythonw()
    if pythonw:
        command = f'"{pythonw}" "{os.path.abspath(__file__)}"'
    else:
        command = f'"{sys.executable}" "{os.path.abspath(__file__)}"'

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(key)
        logging.info(f"Startup registered: {command}")
        print(f"Startup registered: {value_name}")
        print(f"  Command: {command}")
    except Exception as e:
        print(f"Failed: {e}")


def uninstall_startup():
    """Remove from Windows startup."""
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "ClaudeDitooNotifier"

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.DeleteValue(key, value_name)
        winreg.CloseKey(key)
        print(f"Startup removed: {value_name}")
    except FileNotFoundError:
        print("Not registered.")
    except Exception as e:
        print(f"Failed: {e}")


# ── Claude Desktop: notification DB polling ──

def get_latest_claude_notification_id():
    """Read the latest Claude notification ID from wpndatabase.db."""
    tmp = os.path.join(tempfile.gettempdir(), "wpn_ditoo_copy.db")
    try:
        shutil.copy2(DB_PATH, tmp)
        conn = sqlite3.connect(tmp)
        row = conn.execute(
            "SELECT Id, ArrivalTime FROM Notification "
            "WHERE HandlerId = ? AND Type = 'toast' "
            "ORDER BY ArrivalTime DESC LIMIT 1",
            (CLAUDE_HANDLER_ID,),
        ).fetchone()
        conn.close()
        return row
    except Exception as e:
        logging.error(f"DB read error: {e}")
        return None
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


# ── Ditoo display ──

def send_to_ditoo(image_name, display_seconds=DITOO_DISPLAY_SECONDS):
    """Send image to Ditoo, wait, revert to clock."""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from ditoo_connection import load_config, get_device, send_image, send_clock

        config = load_config()
        device = get_device(config)
        image_path = os.path.join(SCRIPT_DIR, image_name)
        send_image(device, image_path, config)
        device.disconnect()
        logging.info(f"Ditoo: {image_name} sent ({display_seconds}s)")

        time.sleep(display_seconds)

        config = load_config()
        device = get_device(config)
        send_clock(device, style=0)
        device.disconnect()
        logging.info("Ditoo: clock restored")

    except Exception as e:
        logging.error(f"Ditoo send failed: {e}")


def send_to_ditoo_until_checked(image_name, check_window_class, interval=10, keyboard_effect=None):
    """Send image to Ditoo repeatedly until user opens the target app."""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from ditoo_connection import load_config, get_device, send_image, send_clock

        image_path = os.path.join(SCRIPT_DIR, image_name)

        config = load_config()
        device = get_device(config)
        send_image(device, image_path, config)

        if keyboard_effect is not None:
            device.send_keyboard(0)  # toggle on
            time.sleep(0.1)
            for _ in range(keyboard_effect):
                device.send_keyboard(1)
                time.sleep(0.1)
            logging.info(f"Keyboard LED: on + next x{keyboard_effect}")

        device.disconnect()
        logging.info(f"Ditoo: {image_name} sent (repeat until checked)")

        while not _stop_event.is_set():
            _stop_event.wait(interval)
            if _stop_event.is_set():
                break

            fg = user32.GetForegroundWindow()
            try:
                fg_class = win32gui.GetClassName(fg)
                if fg_class == check_window_class:
                    logging.info(f"User opened {check_window_class} — stop repeat")
                    break
            except Exception:
                pass

            try:
                config = load_config()
                device = get_device(config)
                send_image(device, image_path, config)
                device.disconnect()
            except Exception:
                pass

        config = load_config()
        device = get_device(config)
        send_clock(device, style=0)

        if keyboard_effect is not None:
            device.send_keyboard(0)  # toggle off
            logging.info("Keyboard LED: off (restored)")

        device.disconnect()
        logging.info("Ditoo: clock restored (user checked)")

    except Exception as e:
        logging.error(f"Ditoo repeat failed: {e}")


# ── KakaoTalk: PID-scoped ShadowWnd detection ──

_kakao_last_notify = 0


def find_kakao_pid():
    """Find KakaoTalk main window and return its PID."""
    result = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if "카카오톡" in title or "KakaoTalk" in title:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                result.append(pid)
        return True

    win32gui.EnumWindows(cb, None)
    return result[0] if result else None


def _on_win_event(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    """Callback for KakaoTalk ShadowWnd CREATE event (new message notification)."""
    global _kakao_last_notify
    try:
        if not hwnd:
            return
        cls = win32gui.GetClassName(hwnd)
        if cls != KAKAO_SHADOW_CLASS:
            return

        now = time.time()
        if now - _kakao_last_notify < COOLDOWN_SECONDS:
            return

        _kakao_last_notify = now
        logging.info("KakaoTalk ShadowWnd CREATE detected (new message)")

        threading.Thread(
            target=send_to_ditoo_until_checked,
            args=("kakao.bmp", KAKAO_WINDOW_CLASS),
            kwargs={"interval": 10, "keyboard_effect": 2},
            daemon=True,
        ).start()

    except Exception:
        pass


# ── Claude polling thread ──

def claude_poll_loop():
    """Poll Claude notification DB in a separate thread."""
    last_claude_id = None
    row = get_latest_claude_notification_id()
    if row:
        last_claude_id = row[0]
        logging.info(f"Initial Claude notification ID: {last_claude_id}")

    last_claude_time = 0

    while not _stop_event.is_set():
        now = time.time()
        try:
            if now - last_claude_time > COOLDOWN_SECONDS:
                row = get_latest_claude_notification_id()
                if row:
                    nid, arrival = row
                    if last_claude_id is not None and nid != last_claude_id:
                        logging.info(f"New Claude notification: id={nid}")
                        send_to_ditoo("claude.bmp")
                        last_claude_time = time.time()
                    last_claude_id = nid
        except Exception as e:
            logging.error(f"Claude poll error: {e}")

        _stop_event.wait(CLAUDE_POLL_INTERVAL)


# ── Watcher core ──

def _watcher_main():
    """Run Claude DB polling + KakaoTalk event hook in a thread."""
    global _watcher_running

    logging.info("Notification watcher started")
    _watcher_running = True

    kakao_pid = find_kakao_pid()
    if kakao_pid:
        logging.info(f"KakaoTalk PID={kakao_pid}")
    else:
        logging.warning("KakaoTalk not found at startup")

    claude_thread = threading.Thread(target=claude_poll_loop, daemon=True)
    claude_thread.start()

    cb = WINEVENTPROC(_on_win_event)
    hook = None
    if kakao_pid:
        hook = user32.SetWinEventHook(
            EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE,
            0, cb, kakao_pid, 0,
            WINEVENT_OUTOFCONTEXT,
        )
        if hook:
            logging.info(f"KakaoTalk event hook installed (PID={kakao_pid})")
        else:
            logging.error("Failed to install KakaoTalk event hook")

    msg = ctypes.wintypes.MSG()
    while not _stop_event.is_set():
        # PeekMessage with PM_REMOVE to avoid blocking forever
        if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0x0001):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.1)

    if hook:
        user32.UnhookWinEvent(hook)
    _watcher_running = False
    logging.info("Watcher stopped")


# ── Tray icon ──

def _create_tray_icon():
    """Create tray icon image (16x16 orange circle)."""
    icon_path = os.path.join(SCRIPT_DIR, "claude_icon.png")
    if os.path.isfile(icon_path):
        return Image.open(icon_path).resize((64, 64), Image.Resampling.NEAREST)
    # Fallback: generate simple icon
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=(0xCC, 0x66, 0x33, 0xFF))
    return img


def _on_start(icon, item):
    """Start watching."""
    global _watcher_thread
    if _watcher_running:
        return
    _stop_event.clear()
    _watcher_thread = threading.Thread(target=_watcher_main, daemon=True)
    _watcher_thread.start()
    icon.notify("Ditoo Watcher started", "Ditoo Notifier")
    logging.info("Watcher started via tray")


def _on_stop(icon, item):
    """Stop watching."""
    if not _watcher_running:
        return
    _stop_event.set()
    icon.notify("Ditoo Watcher stopped", "Ditoo Notifier")
    logging.info("Watcher stopped via tray")


def _on_quit(icon, item):
    """Quit the app."""
    _stop_event.set()
    icon.stop()
    logging.info("Tray app quit")


def _get_status(item):
    """Dynamic menu label showing current status."""
    return "Running" if _watcher_running else "Stopped"


def run_tray():
    """Run the notification watcher as a system tray icon."""
    icon = pystray.Icon(
        "ditoo_notifier",
        _create_tray_icon(),
        "Ditoo Notifier",
        menu=pystray.Menu(
            pystray.MenuItem(_get_status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start", _on_start),
            pystray.MenuItem("Stop", _on_stop),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _on_quit),
        ),
    )

    # Auto-start watcher
    _stop_event.clear()
    global _watcher_thread
    _watcher_thread = threading.Thread(target=_watcher_main, daemon=True)
    _watcher_thread.start()

    logging.info("Tray icon started")
    icon.run()


# ── Main ──

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--install":
            install_startup()
            return
        elif sys.argv[1] == "--uninstall":
            uninstall_startup()
            return

    run_tray()


if __name__ == "__main__":
    main()
