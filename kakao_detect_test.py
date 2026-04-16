"""KakaoTalk notification detection test.

Monitors KakaoTalk window for:
1. Title change (unread count)
2. Taskbar flash (FLASHW_TRAY)

Run this, then trigger a KakaoTalk message to see what changes.
"""

import ctypes
import ctypes.wintypes
import time
import win32gui

user32 = ctypes.windll.user32

# KakaoTalk main window class
KAKAO_CLASS = "EVA_Window_Dblclk"


def find_kakao_window():
    """Find KakaoTalk main window handle."""
    result = []

    def callback(hwnd, _):
        cls = win32gui.GetClassName(hwnd)
        if cls == KAKAO_CLASS:
            result.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def get_flash_info(hwnd):
    """Check if window is requesting attention (flashing)."""
    # GW_OWNER check - flashing windows lose foreground
    style = win32gui.GetWindowLong(hwnd, -20)  # GWL_EXSTYLE
    return style


def main():
    hwnd = find_kakao_window()
    if not hwnd:
        print("KakaoTalk not found!")
        return

    title = win32gui.GetWindowText(hwnd)
    style = get_flash_info(hwnd)
    print(f"KakaoTalk found: hwnd={hwnd}")
    print(f"  Initial title: {title}")
    print(f"  Initial exstyle: {hex(style)}")
    print()
    print("Monitoring... trigger a KakaoTalk message now.")
    print("(Ctrl+C to stop)")
    print()

    prev_title = title
    prev_style = style

    while True:
        try:
            curr_title = win32gui.GetWindowText(hwnd)
            curr_style = get_flash_info(hwnd)

            if curr_title != prev_title:
                print(f"[{time.strftime('%H:%M:%S')}] TITLE CHANGED: '{prev_title}' -> '{curr_title}'")
                prev_title = curr_title

            if curr_style != prev_style:
                print(f"[{time.strftime('%H:%M:%S')}] EXSTYLE CHANGED: {hex(prev_style)} -> {hex(curr_style)}")
                prev_style = curr_style

            # Check if window is flashing via foreground state
            fg = user32.GetForegroundWindow()
            if fg != hwnd:
                # Window is not foreground - check if it's requesting attention
                info = ctypes.wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(info))

            time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopped.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    main()
