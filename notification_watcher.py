"""Windows Notification Watcher for Ditoo Pro.

Monitors:
1. Claude Desktop — via Windows notification DB polling (wpndatabase.db)
2. KakaoTalk — via Win32 SetWinEventHook (EVA_Window_Dblclk CREATE event)

Usage:
  python notification_watcher.py            Run the watcher
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

user32 = ctypes.windll.user32

# ── Config ──
CLAUDE_POLL_INTERVAL = 3  # seconds
DITOO_DISPLAY_SECONDS = 5
COOLDOWN_SECONDS = 10

# Claude Desktop
CLAUDE_HANDLER_ID = 404

# KakaoTalk
KAKAO_WINDOW_CLASS = "EVA_Window_Dblclk"

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
WINEVENT_SKIPOWNPROCESS = 0x0002

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


def install_startup():
    """Register as Windows startup program via registry (HKCU)."""
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value_name = "ClaudeDitooNotifier"
    command = f'"{sys.executable}" "{os.path.abspath(__file__)}"'

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
        winreg.CloseKey(key)
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
    """Send image to Ditoo repeatedly until user opens the target app.

    Checks every `interval` seconds if the target window class is foreground.
    When user opens the app (foreground), reverts to clock.
    keyboard_effect: number of 'next' presses to reach desired LED effect (e.g. 2 for yellow snooze)
    """
    try:
        sys.path.insert(0, SCRIPT_DIR)
        from ditoo_connection import load_config, get_device, send_image, send_clock

        image_path = os.path.join(SCRIPT_DIR, image_name)

        # 첫 전송
        config = load_config()
        device = get_device(config)
        send_image(device, image_path, config)

        # 키보드 LED 켜기 + 효과 적용
        if keyboard_effect is not None:
            device.send_keyboard(0)  # toggle on
            time.sleep(0.1)
            for _ in range(keyboard_effect):
                device.send_keyboard(1)  # next effect
                time.sleep(0.1)
            logging.info(f"Keyboard LED: on + next x{keyboard_effect}")

        device.disconnect()
        logging.info(f"Ditoo: {image_name} sent (repeat until checked)")

        # 사용자가 확인할 때까지 반복
        while True:
            time.sleep(interval)

            # 포그라운드 창 확인
            fg = user32.GetForegroundWindow()
            try:
                fg_class = win32gui.GetClassName(fg)
                if fg_class == check_window_class:
                    logging.info(f"User opened {check_window_class} — stop repeat")
                    break
            except Exception:
                pass

            # 이미지 재전송 (화면 유지)
            try:
                config = load_config()
                device = get_device(config)
                send_image(device, image_path, config)
                device.disconnect()
            except Exception:
                pass

        # 시계 복귀 + 키보드 LED 원복
        config = load_config()
        device = get_device(config)
        send_clock(device, style=0)

        if keyboard_effect is not None:
            # 키보드 LED 끄기
            device.send_keyboard(0)  # toggle off
            logging.info("Keyboard LED: off (restored)")

        device.disconnect()
        logging.info("Ditoo: clock restored (user checked)")

    except Exception as e:
        logging.error(f"Ditoo repeat failed: {e}")


# ── KakaoTalk: SetWinEventHook (CREATE event) ──

_kakao_last_notify = 0


def _on_win_event(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    """Callback for KakaoTalk window CREATE event."""
    global _kakao_last_notify
    try:
        if not hwnd:
            return
        cls = win32gui.GetClassName(hwnd)
        if cls != KAKAO_WINDOW_CLASS:
            return

        now = time.time()
        if now - _kakao_last_notify < COOLDOWN_SECONDS:
            return

        _kakao_last_notify = now
        logging.info("KakaoTalk CREATE event detected")
        print(f"[{time.strftime('%H:%M:%S')}] KakaoTalk notification!")

        # Ditoo 전송은 별도 스레드 (메시지 펌프 블로킹 방지)
        # 사용자가 카카오톡을 열 때까지 반복 표시 + 노란색 스누즈 키보드 효과
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

    while True:
        now = time.time()
        try:
            if now - last_claude_time > COOLDOWN_SECONDS:
                row = get_latest_claude_notification_id()
                if row:
                    nid, arrival = row
                    if last_claude_id is not None and nid != last_claude_id:
                        logging.info(f"New Claude notification: id={nid}")
                        print(f"[{time.strftime('%H:%M:%S')}] Claude notification!")
                        send_to_ditoo("claude.bmp")
                        last_claude_time = time.time()
                    last_claude_id = nid
        except Exception as e:
            logging.error(f"Claude poll error: {e}")

        time.sleep(CLAUDE_POLL_INTERVAL)


# ── Main ──

def watch():
    """Run Claude DB polling + KakaoTalk event hook."""
    global _kakao_last_notify

    logging.info("Notification watcher started (Claude DB + KakaoTalk event hook)")
    print("Notification watcher running... (Ctrl+C to stop)")
    print(f"  Claude: DB polling every {CLAUDE_POLL_INTERVAL}s (HandlerId={CLAUDE_HANDLER_ID})")
    print(f"  KakaoTalk: SetWinEventHook CREATE ({KAKAO_WINDOW_CLASS})")

    # Claude polling in background thread
    claude_thread = threading.Thread(target=claude_poll_loop, daemon=True)
    claude_thread.start()

    # KakaoTalk: install WinEvent hook (requires message pump on this thread)
    cb = WINEVENTPROC(_on_win_event)
    hook = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE,
        0, cb, 0, 0,
        WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
    )
    if not hook:
        logging.error("Failed to install WinEvent hook")
        print("ERROR: Failed to install KakaoTalk event hook")
        return

    logging.info("KakaoTalk event hook installed")

    # Message pump (required for SetWinEventHook callbacks)
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        user32.UnhookWinEvent(hook)
        logging.info("Watcher stopped")
        print("\nStopped.")


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--install":
            install_startup()
            return
        elif sys.argv[1] == "--uninstall":
            uninstall_startup()
            return

    watch()


if __name__ == "__main__":
    main()
