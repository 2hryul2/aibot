"""Test: detect KakaoTalk new messages via window title change.

When KakaoTalk receives a message while not focused, the main window title
changes from "카카오톡" to "카카오톡 (N)" where N is the unread count.

This script hooks EVENT_OBJECT_NAMECHANGE scoped to KakaoTalk's PID
and watches for that pattern.

Run this, then trigger a KakaoTalk message to see if it detects correctly.
"""

import ctypes
import ctypes.wintypes
import re
import time
import win32gui
import win32process

user32 = ctypes.windll.user32

# WinEvent constants
EVENT_OBJECT_NAMECHANGE = 0x800C
WINEVENT_OUTOFCONTEXT = 0x0000

OBJID_WINDOW = 0
CHILDID_SELF = 0

KAKAO_TITLE_PATTERN = re.compile(r"카카오톡\s*\((\d+)\)")

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


def find_kakao_main_window():
    """Find KakaoTalk main window handle and PID."""
    result = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if "카카오톡" in title or "KakaoTalk" in title:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            cls = win32gui.GetClassName(hwnd)
            result.append({"hwnd": hwnd, "pid": pid, "title": title, "class": cls})
        return True

    win32gui.EnumWindows(callback, None)
    return result


def on_name_change(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    """Callback for window title change events."""
    try:
        if idObject != OBJID_WINDOW or idChild != CHILDID_SELF:
            return
        if not hwnd:
            return

        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
        ts = time.strftime('%H:%M:%S')

        # Check for unread count pattern
        match = KAKAO_TITLE_PATTERN.search(title)
        if match:
            unread = int(match.group(1))
            print(f"[{ts}] ** NEW MESSAGE ** unread={unread} title=\"{title}\" class={cls}")
        elif "카카오톡" in title or "KakaoTalk" in title:
            print(f"[{ts}] Title changed: \"{title}\" class={cls}")
        else:
            print(f"[{ts}] Other: \"{title}\" class={cls}")

    except Exception as e:
        print(f"Error: {e}")


def main():
    print("Searching for KakaoTalk window...")
    windows = find_kakao_main_window()

    if not windows:
        print("KakaoTalk not found! Make sure it's running.")
        return

    for w in windows:
        print(f"  Found: hwnd={w['hwnd']} pid={w['pid']} class={w['class']} title=\"{w['title']}\"")

    # Use the first found PID
    kakao_pid = windows[0]["pid"]
    print(f"\nHooking EVENT_OBJECT_NAMECHANGE for PID={kakao_pid}")
    print("Trigger a KakaoTalk message now. (Ctrl+C to stop)\n")

    cb = WINEVENTPROC(on_name_change)
    hook = user32.SetWinEventHook(
        EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE,
        0, cb, kakao_pid, 0,
        WINEVENT_OUTOFCONTEXT,
    )

    if not hook:
        print("ERROR: Failed to install hook")
        return

    print(f"Hook installed. Monitoring...\n")

    # Message pump
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        user32.UnhookWinEvent(hook)


if __name__ == "__main__":
    main()
