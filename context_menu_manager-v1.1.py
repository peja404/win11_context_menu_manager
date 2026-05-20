"""
右键菜单管理工具 — 查看和管理 Windows 右键上下文菜单项。
零外部依赖，仅使用 Python 内置库 tkinter + winreg。
"""

import tkinter as tk
from tkinter import ttk, messagebox
import winreg
import subprocess
import sys


# ─── 注册表扫描配置 ───────────────────────────────────────────────

REGISTRY_SCANS = [
    # (显示分类, 子类型, 预定义 HKEY, 子键路径模板)
    ("所有文件", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"*\shell"),
    ("所有文件", "ShellExtension", winreg.HKEY_CLASSES_ROOT, r"*\shellex\ContextMenuHandlers"),
    ("文件夹", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"Directory\shell"),
    ("文件夹", "ShellExtension", winreg.HKEY_CLASSES_ROOT, r"Directory\shellex\ContextMenuHandlers"),
    ("桌面/文件夹背景", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"Directory\Background\shell"),
    ("驱动器", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"Drive\shell"),
    ("驱动器", "ShellExtension", winreg.HKEY_CLASSES_ROOT, r"Drive\shellex\ContextMenuHandlers"),
    ("用户级文件", "shell 动词", winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell"),
]

HKEY_NAMES = {
    winreg.HKEY_CLASSES_ROOT: "HKCR",
    winreg.HKEY_CURRENT_USER: "HKCU",
    winreg.HKEY_LOCAL_MACHINE: "HKLM",
}


def get_reg_value(key_handle, name=""):
    """安全读取注册表值，失败返回 None"""
    try:
        value, _ = winreg.QueryValueEx(key_handle, name)
        return value
    except OSError:
        return None


def scan_shell_entries(hkey, base_subkey, category):
    """扫描 shell 动词条目（有 command 子键的）"""
    entries = []
    try:
        with winreg.OpenKey(hkey, base_subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as parent:
            idx = 0
            while True:
                try:
                    name = winreg.EnumKey(parent, idx)
                    idx += 1
                    subkey_path = f"{base_subkey}\\{name}"
                    with winreg.OpenKey(hkey, subkey_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                        display = get_reg_value(key) or name
                        disabled = get_reg_value(key, "LegacyDisable") is not None
                        # 读取 command
                        command = ""
                        try:
                            with winreg.OpenKey(hkey, f"{subkey_path}\\command", 0,
                                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as cmd_key:
                                command = get_reg_value(cmd_key) or ""
                        except OSError:
                            pass

                    entries.append({
                        "category": category,
                        "subtype": "shell 动词",
                        "name": name,
                        "display": str(display),
                        "full_path": f"{HKEY_NAMES.get(hkey, '?')}\\{subkey_path}",
                        "hkey": hkey,
                        "subkey": subkey_path,
                        "command": str(command),
                        "enabled": not disabled,
                        "type": "shell",
                    })
                except OSError:
                    break
    except OSError:
        pass
    return entries


def scan_shellex_entries(hkey, base_subkey, category):
    """扫描 ShellExtension 条目（CLSID-based 处理器）"""
    entries = []
    try:
        with winreg.OpenKey(hkey, base_subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as parent:
            idx = 0
            while True:
                try:
                    name = winreg.EnumKey(parent, idx)
                    idx += 1
                    subkey_path = f"{base_subkey}\\{name}"
                    with winreg.OpenKey(hkey, subkey_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                        clsid = get_reg_value(key) or ""
                        backup = get_reg_value(key, "_OriginalCLSID")
                        # 如果 (Default) 为空且存在备份，说明被我们禁用了
                        disabled = (clsid == "" and backup is not None)

                    entries.append({
                        "category": category,
                        "subtype": "ShellExtension",
                        "name": name,
                        "display": name,
                        "full_path": f"{HKEY_NAMES.get(hkey, '?')}\\{subkey_path}",
                        "hkey": hkey,
                        "subkey": subkey_path,
                        "command": str(clsid) if clsid else "(空)",
                        "enabled": not disabled,
                        "type": "shellex",
                    })
                except OSError:
                    break
    except OSError:
        pass
    return entries


def scan_all():
    """扫描所有注册表项，返回统一格式列表"""
    all_entries = []
    for category, subtype, hkey, subkey in REGISTRY_SCANS:
        if "shellex" in subtype.lower() or "ShellExtension" in subtype:
            all_entries.extend(scan_shellex_entries(hkey, subkey, category))
        else:
            all_entries.extend(scan_shell_entries(hkey, subkey, category))
    return all_entries


# ─── 启用/禁用操作 ─────────────────────────────────────────────────

def disable_shell_entry(hkey, subkey):
    """禁用 shell 动词：写入 LegacyDisable 值"""
    try:
        with winreg.OpenKey(hkey, subkey, 0,
                            winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            winreg.SetValueEx(key, "LegacyDisable", 0, winreg.REG_SZ, "")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except OSError as e:
        return False, str(e)


def enable_shell_entry(hkey, subkey):
    """启用 shell 动词：删除 LegacyDisable 值"""
    try:
        with winreg.OpenKey(hkey, subkey, 0,
                            winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            winreg.DeleteValue(key, "LegacyDisable")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except FileNotFoundError:
        return True, None  # 值不存在，已经是启用状态
    except OSError as e:
        return False, str(e)


def disable_shellex_entry(hkey, subkey):
    """禁用 shellex：备份 Default 值，然后清空"""
    try:
        with winreg.OpenKey(hkey, subkey, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            original = get_reg_value(key) or ""
            winreg.SetValueEx(key, "_OriginalCLSID", 0, winreg.REG_SZ, original)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except OSError as e:
        return False, str(e)


def enable_shellex_entry(hkey, subkey):
    """启用 shellex：从备份恢复 Default 值"""
    try:
        with winreg.OpenKey(hkey, subkey, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
            backup = get_reg_value(key, "_OriginalCLSID")
            if backup is None:
                return False, "找不到原始 CLSID 备份，无法恢复。"
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, backup or "")
            winreg.DeleteValue(key, "_OriginalCLSID")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except FileNotFoundError:
        return False, "备份值不存在，无法恢复。"
    except OSError as e:
        return False, str(e)


# ─── 主应用 ───────────────────────────────────────────────────────

class ContextMenuManager:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("右键菜单管理工具")
        self.root.geometry("960x620")
        self.root.minsize(800, 480)

        self.entries = []
        self.item_data = {}   # tree iid → entry dict
        self.tree_nodes = {}  # category/subtype name → tree iid (for grouping)

        self._setup_style()
        self._build_ui()
        self._refresh()

    def _setup_style(self):
        style = ttk.Style()
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "xpnative" in available:
            style.theme_use("xpnative")

    # ── UI 构建 ──────────────────────────────────────────────────

    def _build_ui(self):
        # 顶部工具栏
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="在注册表中打开选中项", command=self._open_in_regedit).pack(side=tk.LEFT)

        # 主区域：Pane 分割
        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        # 左侧：分类树
        left_frame = ttk.Frame(pane)
        tree_cols = ("name", "status", "command")
        self.tree = ttk.Treeview(left_frame, columns=tree_cols, show="tree headings",
                                 selectmode="browse")
        self.tree.heading("#0", text="菜单项 / 分类")
        self.tree.heading("name", text="显示名称")
        self.tree.heading("status", text="状态")
        self.tree.heading("command", text="命令 / CLSID")
        self.tree.column("#0", width=220, minwidth=140)
        self.tree.column("name", width=120, minwidth=80)
        self.tree.column("status", width=60, minwidth=50, anchor=tk.CENTER)
        self.tree.column("command", width=260, minwidth=120)

        vsb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)

        pane.add(left_frame, weight=3)

        # 右侧：详情面板
        right_frame = ttk.LabelFrame(self.root, text=" 详情 ", padding=(10, 8))
        # 用 pack 在 right side，和 pane 一起放在 self.root
        # 改为直接用 pack after pane
        pane.add(right_frame, weight=1)

        # 详情内容
        self.detail_widgets = {}
        labels = [
            ("名称", "name"),
            ("类型", "subtype"),
            ("注册表路径", "full_path"),
            ("命令 / CLSID", "command"),
            ("状态", "status_text"),
        ]
        for row, (label, key) in enumerate(labels):
            ttk.Label(right_frame, text=f"{label}:", font=("", 9, "bold")).grid(
                row=row, column=0, sticky=tk.W, pady=(8 if row > 0 else 0, 2))
            val = ttk.Label(right_frame, text="", wraplength=280)
            val.grid(row=row, column=0, sticky=tk.W, pady=(0, 0))
            self.detail_widgets[key] = val

        # 命令值可能很长，单独用一个可复制的 Entry
        ttk.Label(right_frame, text="命令:", font=("", 9, "bold")).grid(
            row=5, column=0, sticky=tk.W, pady=(8, 2))
        self.cmd_text = tk.Text(right_frame, height=3, width=34, wrap=tk.WORD,
                                font=("Consolas", 9), state=tk.DISABLED)
        self.cmd_text.grid(row=6, column=0, sticky="ew")

        # 操作按钮
        btn_frame = ttk.Frame(right_frame)
        btn_frame.grid(row=7, column=0, sticky=tk.W, pady=(16, 0))
        self.disable_btn = ttk.Button(btn_frame, text="禁用", command=self._disable_selected)
        self.disable_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.enable_btn = ttk.Button(btn_frame, text="启用", command=self._enable_selected)
        self.enable_btn.pack(side=tk.LEFT)
        self.disable_btn.configure(state=tk.DISABLED)
        self.enable_btn.configure(state=tk.DISABLED)

        right_frame.columnconfigure(0, weight=1)

        # 状态栏
        self.status_bar = ttk.Label(self.root, text="", relief=tk.SUNKEN, anchor=tk.W,
                                    padding=(8, 2))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ── 数据刷新 ─────────────────────────────────────────────────

    def _refresh(self):
        self.entries = scan_all()
        self.item_data.clear()
        self.tree_nodes.clear()

        # 清空树
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 按 category → subtype 两级分组
        grouped = {}
        for entry in self.entries:
            key = (entry["category"], entry["subtype"])
            grouped.setdefault(key, []).append(entry)

        for (cat, sub), items in sorted(grouped.items()):
            # 一级：category
            cat_iid = self.tree.insert("", tk.END, text=cat, open=True,
                                       values=("", "", ""))
            self.tree_nodes[(cat,)] = cat_iid

            # 二级：subtype
            sub_iid = self.tree.insert(cat_iid, tk.END, text=sub, open=True,
                                       values=("", "", ""))
            self.tree_nodes[(cat, sub)] = sub_iid

            # 三级：具体项
            for entry in items:
                status_icon = "✅" if entry["enabled"] else "❌"
                cmd_preview = entry.get("command", "")
                if len(cmd_preview) > 60:
                    cmd_preview = cmd_preview[:57] + "..."
                iid = self.tree.insert(sub_iid, tk.END,
                                       values=(entry["display"], status_icon, cmd_preview))
                self.item_data[iid] = entry

        self._update_status_bar()
        self._clear_detail()

    def _update_status_bar(self):
        total = len(self.entries)
        enabled_count = sum(1 for e in self.entries if e["enabled"])
        disabled_count = total - enabled_count
        self.status_bar.configure(
            text=f"  共 {total} 项  |  启用: {enabled_count}  |  禁用: {disabled_count}  "
        )

    # ── 详情面板 ─────────────────────────────────────────────────

    def _clear_detail(self):
        for w in self.detail_widgets.values():
            w.configure(text="")
        self.cmd_text.configure(state=tk.NORMAL)
        self.cmd_text.delete("1.0", tk.END)
        self.cmd_text.configure(state=tk.DISABLED)
        self.disable_btn.configure(state=tk.DISABLED)
        self.enable_btn.configure(state=tk.DISABLED)

    def _on_selection_changed(self, event):
        selection = self.tree.selection()
        if not selection:
            self._clear_detail()
            return

        iid = selection[0]
        entry = self.item_data.get(iid)
        if entry is None:
            self._clear_detail()
            # 更新按钮状态：如果选中的是分类节点，按钮禁用
            self.disable_btn.configure(state=tk.DISABLED)
            self.enable_btn.configure(state=tk.DISABLED)
            return

        self.detail_widgets["name"].configure(text=entry["display"])
        self.detail_widgets["subtype"].configure(text=f"{entry['category']} → {entry['subtype']}")
        self.detail_widgets["full_path"].configure(text=entry["full_path"])
        self.detail_widgets["status_text"].configure(
            text="✅ 启用" if entry["enabled"] else "❌ 禁用")

        self.cmd_text.configure(state=tk.NORMAL)
        self.cmd_text.delete("1.0", tk.END)
        self.cmd_text.insert("1.0", entry.get("command", "(无)"))
        self.cmd_text.configure(state=tk.DISABLED)

        # 按钮状态
        if entry["enabled"]:
            self.disable_btn.configure(state=tk.NORMAL)
            self.enable_btn.configure(state=tk.DISABLED)
        else:
            self.disable_btn.configure(state=tk.DISABLED)
            self.enable_btn.configure(state=tk.NORMAL)

    # ── 操作 ─────────────────────────────────────────────────────

    def _get_selected_entry(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self.item_data.get(sel[0])

    def _disable_selected(self):
        entry = self._get_selected_entry()
        if not entry:
            return
        if entry["type"] == "shell":
            ok, err = disable_shell_entry(entry["hkey"], entry["subkey"])
        else:
            ok, err = disable_shellex_entry(entry["hkey"], entry["subkey"])

        if ok:
            self._refresh()
            self.status_bar.configure(text="  已禁用该项")
        else:
            messagebox.showerror("操作失败", err or "未知错误")

    def _enable_selected(self):
        entry = self._get_selected_entry()
        if not entry:
            return
        if entry["type"] == "shell":
            ok, err = enable_shell_entry(entry["hkey"], entry["subkey"])
        else:
            ok, err = enable_shellex_entry(entry["hkey"], entry["subkey"])

        if ok:
            self._refresh()
            self.status_bar.configure(text="  已启用该项")
        else:
            messagebox.showerror("操作失败", err or "未知错误")

    def _open_in_regedit(self):
        entry = self._get_selected_entry()
        if not entry:
            messagebox.showinfo("提示", "请先选中一个菜单项。")
            return

        hkey_name = HKEY_NAMES.get(entry["hkey"], "?")
        # regedit 的 LastKey 格式：计算机\HKEY_CLASSES_ROOT\...
        reg_path = f"计算机\\{hkey_name}\\{entry['subkey']}"

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit",
                                0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "LastKey", 0, winreg.REG_SZ, reg_path)
        except PermissionError:
            pass  # 静默失败，regedit 仍能打开只是可能不定位

        try:
            subprocess.Popen(["regedit.exe"])
        except OSError as e:
            messagebox.showerror("错误", f"无法启动注册表编辑器: {e}")

    def run(self):
        self.root.mainloop()


def main():
    app = ContextMenuManager()
    app.run()


if __name__ == "__main__":
    main()
