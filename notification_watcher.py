"""Windows Notification Watcher for Ditoo Pro.

Config-driven notification monitoring with system tray icon.

Supports two detection methods (set in config.json "watchers"):
  - "shadow_wnd": PID-scoped SetWinEventHook for a specific window class
  - "toast_db":   Windows notification DB polling (wpndatabase.db)

Usage:
  python notification_watcher.py            Run with tray icon
  python notification_watcher.py --install   Register as startup program
  python notification_watcher.py --uninstall Remove from startup
"""

import ctypes
import ctypes.wintypes
import json
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
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


# ── Config ──

def load_watcher_config():
    """Load config.json and return full config dict."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_watcher_config(config):
    """Save config dict back to config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


def get_watchers(config=None):
    """Get the watchers list from config."""
    if config is None:
        config = load_watcher_config()
    return config.get("watchers", [])


# ── Startup registration ──

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


# ── Toast DB detection ──

def get_latest_toast_notification(handler_id):
    """Read the latest toast notification ID from wpndatabase.db.

    WAL 모드 DB이므로 .db/.db-wal/.db-shm 3파일을 모두 복사해야 정상 읽기 가능.
    복사 실패 시 read-only 직접 접근으로 fallback.
    """
    tmp_dir = os.path.join(tempfile.gettempdir(), "wpn_ditoo_copy")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_db = os.path.join(tmp_dir, "wpndatabase.db")

    try:
        # WAL 모드: .db + .db-wal + .db-shm 모두 복사
        for ext in ("", "-wal", "-shm"):
            src = DB_PATH + ext
            dst = tmp_db + ext
            try:
                shutil.copy2(src, dst)
            except FileNotFoundError:
                pass

        conn = sqlite3.connect(tmp_db)
        row = conn.execute(
            "SELECT Id, ArrivalTime FROM Notification "
            "WHERE HandlerId = ? AND Type = 'toast' "
            "ORDER BY ArrivalTime DESC LIMIT 1",
            (handler_id,),
        ).fetchone()
        conn.close()
        return row
    except Exception:
        # Fallback: read-only 직접 접근
        try:
            uri = f"file:{DB_PATH}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.execute("PRAGMA query_only = ON")
            row = conn.execute(
                "SELECT Id, ArrivalTime FROM Notification "
                "WHERE HandlerId = ? AND Type = 'toast' "
                "ORDER BY ArrivalTime DESC LIMIT 1",
                (handler_id,),
            ).fetchone()
            conn.close()
            return row
        except Exception as e:
            logging.error(f"DB read error: {e}")
            return None
    finally:
        for ext in ("", "-wal", "-shm"):
            try:
                os.remove(tmp_db + ext)
            except Exception:
                pass


# ── Window PID finder ──

def find_window_pid(window_title):
    """Find a window by title substring and return its PID."""
    result = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if window_title in title:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                result.append(pid)
        return True

    win32gui.EnumWindows(cb, None)
    return result[0] if result else None


# ── Ditoo display ──

def send_to_ditoo(image_name, display_seconds=5, keyboard_effect=None):
    """Send image to Ditoo, wait, revert to clock."""
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from ditoo_connection import load_config, get_device, send_image, send_clock

        config = load_config()
        device = get_device(config)
        image_path = os.path.join(SCRIPT_DIR, image_name)
        send_image(device, image_path, config)

        if keyboard_effect is not None:
            device.send_keyboard(0)  # toggle on
            time.sleep(0.1)
            for _ in range(keyboard_effect):
                device.send_keyboard(1)
                time.sleep(0.1)

        device.disconnect()
        logging.info(f"Ditoo: {image_name} sent ({display_seconds}s)")

        time.sleep(display_seconds)

        config = load_config()
        device = get_device(config)
        send_clock(device, style=0)

        if keyboard_effect is not None:
            device.send_keyboard(0)  # toggle off

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


# ── Shadow WND watcher (generic) ──

def create_shadow_wnd_callback(watchers_by_shadow):
    """Create a WinEvent callback that dispatches to the correct watcher config."""
    last_notify = {}

    def callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        try:
            if not hwnd:
                return
            cls = win32gui.GetClassName(hwnd)
            if cls not in watchers_by_shadow:
                return

            watcher = watchers_by_shadow[cls]
            name = watcher["name"]
            cooldown = watcher.get("cooldown", 10)

            now = time.time()
            if now - last_notify.get(name, 0) < cooldown:
                return

            last_notify[name] = now
            logging.info(f"{name}: {cls} CREATE detected (new notification)")

            image = watcher.get("image")
            window_class = watcher.get("window_class")
            keyboard_effect = watcher.get("keyboard_effect")
            interval = watcher.get("repeat_interval", 10)

            if window_class:
                threading.Thread(
                    target=send_to_ditoo_until_checked,
                    args=(image, window_class),
                    kwargs={"interval": interval, "keyboard_effect": keyboard_effect},
                    daemon=True,
                ).start()
            else:
                display_seconds = watcher.get("display_seconds", 5)
                threading.Thread(
                    target=send_to_ditoo,
                    args=(image,),
                    kwargs={"display_seconds": display_seconds, "keyboard_effect": keyboard_effect},
                    daemon=True,
                ).start()

        except Exception:
            pass

    return callback


# ── Toast DB watcher (generic) ──

def toast_poll_loop(watcher):
    """Poll toast notification DB for a specific handler."""
    handler_id = watcher["handler_id"]
    name = watcher["name"]
    cooldown = watcher.get("cooldown", 10)
    image = watcher.get("image")
    display_seconds = watcher.get("display_seconds", 5)
    keyboard_effect = watcher.get("keyboard_effect")
    poll_interval = watcher.get("poll_interval", 3)

    last_id = None
    row = get_latest_toast_notification(handler_id)
    if row:
        last_id = row[0]
        logging.info(f"{name}: initial notification ID={last_id}")

    last_time = 0

    while not _stop_event.is_set():
        now = time.time()
        try:
            if now - last_time > cooldown:
                row = get_latest_toast_notification(handler_id)
                if row:
                    nid, arrival = row
                    if last_id is not None and nid != last_id:
                        logging.info(f"{name}: new notification id={nid}")
                        send_to_ditoo(image, display_seconds=display_seconds, keyboard_effect=keyboard_effect)
                        last_time = time.time()
                    last_id = nid
        except Exception as e:
            logging.error(f"{name} poll error: {e}")

        _stop_event.wait(poll_interval)


# ── Generic window_create watcher ──

def create_window_create_callback(watchers_by_pid):
    """Create a WinEvent callback for generic window creation detection.

    Detects new visible windows created by a monitored process while
    its main window is NOT in the foreground (= user is not looking at it).
    """
    last_notify = {}

    def callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        try:
            if not hwnd:
                return
            if not win32gui.IsWindowVisible(hwnd):
                return

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid not in watchers_by_pid:
                return

            watcher = watchers_by_pid[pid]
            name = watcher["name"]
            main_class = watcher.get("window_class", "")
            cooldown = watcher.get("cooldown", 10)

            # Skip if the created window IS the main window
            cls = win32gui.GetClassName(hwnd)
            if cls == main_class:
                return

            # Skip if the main window is foreground (user is looking at it)
            fg = user32.GetForegroundWindow()
            try:
                fg_class = win32gui.GetClassName(fg)
                if fg_class == main_class:
                    return
            except Exception:
                pass

            now = time.time()
            if now - last_notify.get(name, 0) < cooldown:
                return

            last_notify[name] = now
            logging.info(f"{name}: new window created (class={cls}, generic detection)")

            image = watcher.get("image", "default_notify.bmp")
            keyboard_effect = watcher.get("keyboard_effect")
            display_seconds = watcher.get("display_seconds", 5)

            if main_class:
                interval = watcher.get("repeat_interval", 10)
                threading.Thread(
                    target=send_to_ditoo_until_checked,
                    args=(image, main_class),
                    kwargs={"interval": interval, "keyboard_effect": keyboard_effect},
                    daemon=True,
                ).start()
            else:
                threading.Thread(
                    target=send_to_ditoo,
                    args=(image,),
                    kwargs={"display_seconds": display_seconds, "keyboard_effect": keyboard_effect},
                    daemon=True,
                ).start()

        except Exception:
            pass

    return callback


# ── Watcher core ──

def _watcher_main():
    """Run all watchers from config."""
    global _watcher_running

    logging.info("Notification watcher started")
    _watcher_running = True

    config = load_watcher_config()
    watchers = config.get("watchers", [])

    # Separate watchers by type
    shadow_watchers = {}       # shadow_class -> watcher config
    shadow_pids = {}           # pid -> [shadow_classes]
    window_create_pids = {}    # pid -> watcher config
    toast_watchers = []
    hooks = []
    # Keep callback references alive to prevent GC
    _callbacks = []

    for w in watchers:
        if not w.get("enabled", True):
            logging.info(f"{w['name']}: disabled, skipping")
            continue

        method = w.get("detect_method")

        if method == "shadow_wnd":
            shadow_class = w.get("shadow_class")
            window_title = w.get("window_title", "")
            if not shadow_class:
                logging.warning(f"{w['name']}: no shadow_class, skipping")
                continue

            pid = find_window_pid(window_title)
            if pid:
                shadow_watchers[shadow_class] = w
                if pid not in shadow_pids:
                    shadow_pids[pid] = []
                shadow_pids[pid].append(shadow_class)
                logging.info(f"{w['name']}: PID={pid}, monitoring {shadow_class}")
            else:
                logging.warning(f"{w['name']}: window '{window_title}' not found")

        elif method == "window_create":
            window_title = w.get("window_title", "")
            pid = find_window_pid(window_title)
            if pid:
                window_create_pids[pid] = w
                logging.info(f"{w['name']}: PID={pid}, generic window_create monitoring")
            else:
                logging.warning(f"{w['name']}: window '{window_title}' not found")

        elif method == "toast_db":
            toast_watchers.append(w)
            logging.info(f"{w['name']}: toast DB polling (handler_id={w.get('handler_id')})")

    # Install shadow_wnd hooks (one per PID)
    if shadow_watchers:
        cb_func = create_shadow_wnd_callback(shadow_watchers)
        cb = WINEVENTPROC(cb_func)
        _callbacks.append(cb)
        for pid in shadow_pids:
            hook = user32.SetWinEventHook(
                EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE,
                0, cb, pid, 0,
                WINEVENT_OUTOFCONTEXT,
            )
            if hook:
                hooks.append(hook)
                logging.info(f"Shadow hook installed: PID={pid}")
            else:
                logging.error(f"Failed to install shadow hook for PID={pid}")

    # Install window_create hooks (one per PID)
    if window_create_pids:
        wc_func = create_window_create_callback(window_create_pids)
        wc_cb = WINEVENTPROC(wc_func)
        _callbacks.append(wc_cb)
        for pid in window_create_pids:
            hook = user32.SetWinEventHook(
                EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE,
                0, wc_cb, pid, 0,
                WINEVENT_OUTOFCONTEXT,
            )
            if hook:
                hooks.append(hook)
                logging.info(f"Window create hook installed: PID={pid}")
            else:
                logging.error(f"Failed to install window_create hook for PID={pid}")

    # Start toast DB pollers
    for w in toast_watchers:
        t = threading.Thread(target=toast_poll_loop, args=(w,), daemon=True)
        t.start()

    # Message pump
    msg = ctypes.wintypes.MSG()
    while not _stop_event.is_set():
        if user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0x0001):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        else:
            time.sleep(0.1)

    for hook in hooks:
        user32.UnhookWinEvent(hook)
    _watcher_running = False
    logging.info("Watcher stopped")


# ── Tray icon ──

def _create_tray_icon():
    """Create tray icon image."""
    icon_path = os.path.join(SCRIPT_DIR, "claude_icon.png")
    if os.path.isfile(icon_path):
        return Image.open(icon_path).resize((64, 64), Image.Resampling.NEAREST)
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


def _on_config(icon, item):
    """Open Config GUI."""
    import subprocess
    subprocess.Popen(
        [sys.executable, os.path.join(SCRIPT_DIR, "config_gui.py")],
        cwd=SCRIPT_DIR,
    )
    logging.info("Config GUI opened")


def _on_reload(icon, item):
    """Stop and restart watcher with updated config."""
    global _watcher_thread
    if _watcher_running:
        _stop_event.set()
        time.sleep(1)
    _stop_event.clear()
    _watcher_thread = threading.Thread(target=_watcher_main, daemon=True)
    _watcher_thread.start()
    icon.notify("Config reloaded", "Ditoo Notifier")
    logging.info("Watcher reloaded via tray")


def _on_quit(icon, item):
    """Quit the app."""
    _stop_event.set()
    icon.stop()
    logging.info("Tray app quit")


def _get_status(item):
    """Dynamic menu label showing current status."""
    return "Running" if _watcher_running else "Stopped"


def _build_watcher_submenu():
    """Build dynamic submenu showing watcher status."""
    items = []
    try:
        watchers = get_watchers()
        for w in watchers:
            name = w.get("name", "Unknown")
            enabled = w.get("enabled", True)
            method = w.get("detect_method", "?")
            label = f"{'[ON]' if enabled else '[OFF]'} {name} ({method})"
            items.append(pystray.MenuItem(label, None, enabled=False))
    except Exception:
        items.append(pystray.MenuItem("Error loading config", None, enabled=False))
    return items


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
            pystray.MenuItem("Watchers", pystray.Menu(lambda: _build_watcher_submenu())),
            pystray.MenuItem("Config", _on_config),
            pystray.MenuItem("Reload", _on_reload),
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
