"""Poll KakaoTalk window title every 0.5s to observe changes."""

import win32gui
import time


def find_kakao_titles():
    result = []

    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            if "카카오톡" in title or "KakaoTalk" in title:
                result.append((hwnd, title, cls))
        return True

    win32gui.EnumWindows(cb, None)
    return result


def main():
    print("Polling KakaoTalk window title... (Ctrl+C to stop)")
    print("Send a message while KakaoTalk is NOT focused.\n")

    prev_title = ""
    while True:
        windows = find_kakao_titles()
        for hwnd, title, cls in windows:
            if title != prev_title:
                print(f"[{time.strftime('%H:%M:%S')}] title=\"{title}\" class={cls} hwnd={hwnd}")
                prev_title = title
        time.sleep(0.5)


if __name__ == "__main__":
    main()
