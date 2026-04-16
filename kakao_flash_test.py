"""Test: detect KakaoTalk taskbar flash using SetWinEventHook.

When a window flashes in the taskbar, Windows fires EVENT_OBJECT_STATECHANGE.
This script hooks that event and filters for KakaoTalk windows.

Run this, then trigger a KakaoTalk message to see what events fire.
"""

import ctypes
import ctypes.wintypes
import time
import win32gui
import threading

user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32

# Event constants
EVENT_OBJECT_STATECHANGE = 0x800A
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_OBJECT_NAMECHANGE = 0x800C
EVENT_OBJECT_CREATE = 0x8000
EVENT_OBJECT_SHOW = 0x8002
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

KAKAO_CLASS = "EVA_Window_Dblclk"

# Callback type
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    ctypes.wintypes.HANDLE,   # hWinEventHook
    ctypes.wintypes.DWORD,    # event
    ctypes.wintypes.HWND,     # hwnd
    ctypes.wintypes.LONG,     # idObject
    ctypes.wintypes.LONG,     # idChild
    ctypes.wintypes.DWORD,    # dwEventThread
    ctypes.wintypes.DWORD,    # dwmsEventTime
)

EVENT_NAMES = {
    EVENT_OBJECT_STATECHANGE: "STATE_CHANGE",
    EVENT_SYSTEM_FOREGROUND: "FOREGROUND",
    EVENT_OBJECT_NAMECHANGE: "NAME_CHANGE",
    EVENT_OBJECT_CREATE: "CREATE",
    EVENT_OBJECT_SHOW: "SHOW",
}


def callback(hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
    try:
        if not hwnd:
            return
        cls = win32gui.GetClassName(hwnd)
        if KAKAO_CLASS not in cls:
            return

        title = win32gui.GetWindowText(hwnd)
        visible = win32gui.IsWindowVisible(hwnd)
        event_name = EVENT_NAMES.get(event, hex(event))
        ts = time.strftime('%H:%M:%S')
        print(f"[{ts}] {event_name} hwnd={hwnd} visible={visible} title={title}")
    except Exception:
        pass


def main():
    print("Monitoring KakaoTalk window events...")
    print("Trigger a KakaoTalk message now. (Ctrl+C to stop)")
    print()

    cb = WINEVENTPROC(callback)

    # Hook multiple event ranges
    hooks = []
    for event_min, event_max in [
        (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
        (EVENT_OBJECT_STATECHANGE, EVENT_OBJECT_STATECHANGE),
        (EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE),
        (EVENT_OBJECT_CREATE, EVENT_OBJECT_CREATE),
        (EVENT_OBJECT_SHOW, EVENT_OBJECT_SHOW),
    ]:
        hook = user32.SetWinEventHook(
            event_min, event_max,
            0, cb, 0, 0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        )
        if hook:
            hooks.append(hook)

    print(f"Hooks installed: {len(hooks)}")

    # Message pump (required for SetWinEventHook)
    msg = ctypes.wintypes.MSG()
    try:
        while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        for h in hooks:
            user32.UnhookWinEvent(h)


if __name__ == "__main__":
    main()
