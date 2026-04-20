"""Test: detect KakaoTalk messages via KakaoTalkShadowWnd appearance.

KakaoTalkShadowWnd (class: KakaoTalkShadowWndClass) appears when
a notification popup shows. Monitor its creation/visibility.
"""

import win32gui
import win32process
import time


def scan_kakao_windows():
    """Find all KakaoTalk-related windows."""
    result = []

    def cb(hwnd, _):
        cls = win32gui.GetClassName(hwnd)
        if "KakaoTalk" in cls or "EVA_" in cls:
            title = win32gui.GetWindowText(hwnd)
            visible = win32gui.IsWindowVisible(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                rect = win32gui.GetWindowRect(hwnd)
                size = (rect[2] - rect[0], rect[3] - rect[1])
            except Exception:
                rect = None
                size = None
            result.append({
                "hwnd": hwnd,
                "class": cls,
                "title": title,
                "visible": visible,
                "pid": pid,
                "rect": rect,
                "size": size,
            })
        return True

    win32gui.EnumWindows(cb, None)
    return result


def main():
    print("Monitoring KakaoTalk windows... (Ctrl+C to stop)")
    print("Send a message to see what windows appear.\n")

    shadow_was_visible = False
    prev_shadow_count = 0

    while True:
        windows = scan_kakao_windows()
        shadow_windows = [w for w in windows if "Shadow" in w["class"] and w["visible"]]
        shadow_count = len(shadow_windows)

        # Shadow window appeared
        if shadow_count > 0 and not shadow_was_visible:
            ts = time.strftime('%H:%M:%S')
            print(f"[{ts}] ** SHADOW APPEARED ** count={shadow_count}")
            for w in shadow_windows:
                print(f"  hwnd={w['hwnd']} size={w['size']} rect={w['rect']} title=\"{w['title']}\"")
            shadow_was_visible = True

        # Shadow window count changed
        elif shadow_count != prev_shadow_count and shadow_count > 0:
            ts = time.strftime('%H:%M:%S')
            print(f"[{ts}] Shadow count changed: {prev_shadow_count} -> {shadow_count}")

        # Shadow window disappeared
        elif shadow_count == 0 and shadow_was_visible:
            ts = time.strftime('%H:%M:%S')
            print(f"[{ts}] Shadow disappeared")
            shadow_was_visible = False

        prev_shadow_count = shadow_count
        time.sleep(0.3)


if __name__ == "__main__":
    main()
