"""Test: detect KakaoTalk via taskbar button and system tray icon.

Polls taskbar buttons and system tray icons to find KakaoTalk
and observe name/tooltip changes when messages arrive.
"""

import uiautomation as auto
import time


def scan_taskbar_buttons():
    """Find KakaoTalk in taskbar buttons."""
    results = []
    try:
        taskbar = auto.PaneControl(ClassName="Shell_TrayWnd", searchDepth=1)
        # Try MSTaskListWClass (Win10) or MSTaskSwWClass (Win11)
        for cls in ["MSTaskListWClass", "MSTaskSwWClass", "Windows.UI.Composition.DesktopWindowContentBridge"]:
            try:
                task_list = taskbar.PaneControl(ClassName=cls, searchDepth=5)
                for btn in task_list.GetChildren():
                    if btn.ControlType == auto.ControlType.ButtonControl:
                        name = btn.Name
                        if "카카오" in name or "KakaoTalk" in name or "kakao" in name.lower():
                            results.append({"source": f"taskbar({cls})", "name": name})
            except Exception:
                pass
    except Exception as e:
        print(f"Taskbar scan error: {e}")
    return results


def scan_tray_icons():
    """Find KakaoTalk in system tray (notification area)."""
    results = []
    tray_names = [
        "User Promoted Notification Area",
        "System Promoted Notification Area",
    ]
    try:
        taskbar = auto.PaneControl(ClassName="Shell_TrayWnd", searchDepth=1)
        for tray_name in tray_names:
            try:
                tray = taskbar.ToolBarControl(Name=tray_name, searchDepth=10)
                for btn in tray.GetChildren():
                    if btn.ControlType == auto.ControlType.ButtonControl:
                        name = btn.Name
                        if "카카오" in name or "KakaoTalk" in name or "kakao" in name.lower():
                            results.append({"source": f"tray({tray_name})", "name": name})
            except Exception:
                pass
    except Exception as e:
        print(f"Tray scan error: {e}")
    return results


def scan_overflow_tray():
    """Find KakaoTalk in overflow notification area."""
    results = []
    try:
        overflow = auto.PaneControl(ClassName="NotifyIconOverflowWindow", searchDepth=1)
        toolbar = overflow.ToolBarControl(Name="Overflow Notification Area", searchDepth=5)
        for btn in toolbar.GetChildren():
            if btn.ControlType == auto.ControlType.ButtonControl:
                name = btn.Name
                if "카카오" in name or "KakaoTalk" in name or "kakao" in name.lower():
                    results.append({"source": "tray(overflow)", "name": name})
    except Exception:
        pass
    return results


def main():
    print("Scanning taskbar & tray for KakaoTalk... (Ctrl+C to stop)")
    print("Send a message to see what changes.\n")

    # Initial scan - show all found
    print("=== Initial Scan ===")
    for item in scan_taskbar_buttons():
        print(f"  [{item['source']}] \"{item['name']}\"")
    for item in scan_tray_icons():
        print(f"  [{item['source']}] \"{item['name']}\"")
    for item in scan_overflow_tray():
        print(f"  [{item['source']}] \"{item['name']}\"")
    print()

    # Monitor changes
    prev_names = {}
    while True:
        all_items = scan_taskbar_buttons() + scan_tray_icons() + scan_overflow_tray()
        for item in all_items:
            key = item["source"]
            name = item["name"]
            if key not in prev_names:
                print(f"[{time.strftime('%H:%M:%S')}] NEW: [{key}] \"{name}\"")
                prev_names[key] = name
            elif prev_names[key] != name:
                print(f"[{time.strftime('%H:%M:%S')}] CHANGED: [{key}] \"{prev_names[key]}\" -> \"{name}\"")
                prev_names[key] = name

        time.sleep(1)


if __name__ == "__main__":
    main()
