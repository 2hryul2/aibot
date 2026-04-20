"""Config GUI for Ditoo Notifier.

Shows running programs from the taskbar and lets the user
select which ones to monitor. Saves to config.json.
"""

import ctypes
import ctypes.wintypes
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

import win32gui
import win32process

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")


def get_process_name(pid):
    """Get executable name from PID."""
    PROCESS_QUERY_INFO = 0x0400
    PROCESS_VM_READ = 0x0010
    handle = ctypes.windll.kernel32.OpenProcess(
        PROCESS_QUERY_INFO | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.psapi.GetModuleFileNameExW(handle, None, buf, 260)
        return os.path.basename(buf.value) if buf.value else None
    except Exception:
        return None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def get_running_programs():
    """Get visible taskbar programs with window info."""
    programs = {}

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or len(title.strip()) == 0:
            return True
        cls = win32gui.GetClassName(hwnd)
        if cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd", "Progman",
                   "WorkerW", "Windows.UI.Core.CoreWindow",
                   "ApplicationFrameWindow", "ForegroundStaging",
                   "Shell_InputSwitchTopLevelWindow",
                   "Windows.UI.Composition.DesktopWindowContentBridge"):
            return True

        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        exe_name = get_process_name(pid)
        if not exe_name:
            return True
        # Skip system processes
        if exe_name.lower() in ("textinputhost.exe",
                                 "searchhost.exe", "shellexperiencehost.exe"):
            return True

        # Use title as key to show each window separately
        key = f"{exe_name.lower()}|{title}"
        if key not in programs:
            programs[key] = {
                "exe": exe_name,
                "title": title,
                "class": cls,
                "pid": pid,
            }
        return True

    win32gui.EnumWindows(cb, None)
    return sorted(programs.values(), key=lambda p: p["title"])


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")


class ConfigWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Ditoo Notifier - Config")
        self.root.geometry("550x500")
        self.root.resizable(True, True)

        self.config = load_config()
        self.watchers = list(self.config.get("watchers", []))

        self.programs = get_running_programs()
        self.existing_vars = []   # (BooleanVar, watcher_dict)
        self.new_vars = []        # (BooleanVar, program_dict)

        self._build_ui()
        self.root.mainloop()

    def _get_registered_titles(self):
        """Get set of window_title values from current watchers."""
        return {w.get("window_title", "") for w in self.watchers}

    def _build_ui(self):
        # Clear
        for widget in self.root.winfo_children():
            widget.destroy()
        self.existing_vars = []
        self.new_vars = []

        # ── Title ──
        tk.Label(self.root, text="Ditoo Notification Watchers",
                 font=("Segoe UI", 13, "bold"), anchor=tk.W,
                 padx=10, pady=8).pack(fill=tk.X)

        # ── Existing watchers ──
        ef = tk.LabelFrame(self.root, text="Registered Watchers", padx=8, pady=4)
        ef.pack(fill=tk.X, padx=10, pady=(0, 4))

        if not self.watchers:
            tk.Label(ef, text="(none)", fg="gray").pack(anchor=tk.W)

        for w in self.watchers:
            row = tk.Frame(ef)
            row.pack(fill=tk.X, pady=1)

            var = tk.BooleanVar(value=w.get("enabled", True))
            self.existing_vars.append((var, w))

            tk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
            method = w.get("detect_method", "?")
            tk.Label(row, text=w["name"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
            tk.Label(row, text=f"  [{method}]", fg="gray", font=("Segoe UI", 8)).pack(side=tk.LEFT)
            tk.Button(row, text="X", fg="red", font=("Segoe UI", 7), width=2,
                      command=lambda n=w["name"]: self._remove_watcher(n)).pack(side=tk.RIGHT)

        # ── Separator ──
        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=10, pady=4)

        # ── Running programs ──
        pf = tk.LabelFrame(self.root, text="Running Programs (check to add)", padx=8, pady=4)
        pf.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))

        # Treeview with checkboxes
        columns = ("title", "exe")
        self.tree = ttk.Treeview(pf, columns=columns, show="tree headings",
                                  height=12, selectmode="extended")
        self.tree.heading("#0", text="")
        self.tree.heading("title", text="Program")
        self.tree.heading("exe", text="Process")
        self.tree.column("#0", width=30, stretch=False)
        self.tree.column("title", width=320)
        self.tree.column("exe", width=150)

        scrollbar = ttk.Scrollbar(pf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        registered_titles = self._get_registered_titles()
        self._tree_items = {}

        for prog in self.programs:
            # Skip already registered
            already = any(t and t in prog["title"] for t in registered_titles)
            if already:
                continue

            iid = self.tree.insert("", tk.END, text="",
                                    values=(prog["title"], prog["exe"]))
            self._tree_items[iid] = prog

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Buttons ──
        bf = tk.Frame(self.root, padx=10, pady=8)
        bf.pack(fill=tk.X)

        tk.Button(bf, text="Save & Reload", font=("Segoe UI", 10, "bold"),
                  bg="#4CAF50", fg="white", width=15,
                  command=self._save).pack(side=tk.RIGHT, padx=4)
        tk.Button(bf, text="Cancel", font=("Segoe UI", 10),
                  width=10, command=self.root.destroy).pack(side=tk.RIGHT, padx=4)

    def _remove_watcher(self, name):
        if messagebox.askyesno("Remove", f"Remove '{name}' from watchers?"):
            self.watchers = [w for w in self.watchers if w["name"] != name]
            self._build_ui()

    def _save(self):
        # Update enabled state of existing watchers
        for var, w in self.existing_vars:
            w["enabled"] = var.get()

        # Add selected programs as new watchers
        selected = self.tree.selection()
        for iid in selected:
            prog = self._tree_items.get(iid)
            if not prog:
                continue

            name = prog["title"].split(" - ")[0].split(" \u2014 ")[0].strip()
            if not name:
                name = prog["exe"].replace(".exe", "")

            new_watcher = {
                "name": name,
                "enabled": True,
                "detect_method": "window_create",
                "window_title": name,
                "window_class": prog["class"],
                "exe_name": prog["exe"],
                "image": "default_notify.bmp",
                "keyboard_effect": None,
                "cooldown": 10,
                "display_seconds": 5,
            }
            self.watchers.append(new_watcher)

        self.config["watchers"] = self.watchers
        save_config(self.config)

        messagebox.showinfo("Saved", "Config saved.\nClick 'Reload' in tray menu to apply.")
        self.root.destroy()


def main():
    ConfigWindow()


if __name__ == "__main__":
    main()
