"""Test: detect KakaoTalk messages via KakaoTalkShadowWndClass CREATE event.

Hooks EVENT_OBJECT_CREATE scoped to KakaoTalk's PID,
filters by class name KakaoTalkShadowWndClass.
"""

import ctypes
import ctypes.wintypes
import time
import win32gui
import win32process

user32 = ctypes.windll.user32

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

SHADOW_CLASS = "KakaoTalkShadowWndClass"


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


def on_create(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    try:
        if not hwnd:
            return
        cls = win32gui.GetClassName(hwnd)
        if cls != SHADOW_CLASS:
            return

        ts = time.strftime('%H:%M:%S')
        print(f"[{ts}] ** NEW MESSAGE ** KakaoTalkShadowWnd created (hwnd={hwnd})")

    except Exception:
        pass


def main():
    pid = find_kakao_pid()
    if not pid:
        print("KakaoTalk not found!")
        return

    print(f"KakaoTalk PID: {pid}")
    print(f"Hooking EVENT_OBJECT_CREATE for {SHADOW_CLASS}...")
    print("Send a message now. (Ctrl+C to stop)\n")

    cb = WINEVENTPROC(on_create)
    hook = user32.SetWinEventHook(
        EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE,
        0, cb, pid, 0,
        WINEVENT_OUTOFCONTEXT,
    )

    if not hook:
        print("ERROR: Failed to install hook")
        return

    print("Hook installed. Monitoring...\n")

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
