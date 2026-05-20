"""
Windows Context Menu Manager — 右键菜单管理工具
===============================================

查看、启用、禁用 Windows 资源管理器右键菜单项。
一个 Python 文件，零外部依赖（仅使用内置 tkinter + winreg）。

工作原理
--------
Windows 右键菜单由注册表驱动，分为两大类：

1. **Shell 动词** (shell verbs)
   路径形如: HKCR\\*\\shell\\VSCode
   包含一个 ``command`` 子键，存储要执行的命令行。
   这是最常见的类型：VSCode、Git Bash、CMD 等。
   禁用方式：写入 ``LegacyDisable`` (REG_SZ) 值（Windows 原生机制）。

2. **Shell 扩展** (shellex / ContextMenuHandlers)
   路径形如: HKCR\\*\\shellex\\ContextMenuHandlers\\7-Zip
   注册的是 COM 组件 CLSID，由对应的 DLL 实现菜单绘制。
   这是第三方程序的主要方式：7-Zip、WPS、杀毒软件等。
   禁用方式：备份 (Default) 值 → 清空 (Default)。恢复时从备份值还原。

权限要求
--------
- 查看：无需管理员权限
- 修改 HKCR 下的项：需要管理员权限
- 修改 HKCU 下的项：无需管理员权限

跨平台
------
仅支持 Windows（依赖 winreg 和注册表结构）。
在 Windows 10 / 11 上测试通过。
支持多语言 regedit 跳转（中文 / 英文 / 日文 / 韩文 / 法文）。

运行方式
--------
    python context_menu_manager.py

或以管理员身份运行（允许修改 HKCR）：
    右键 PowerShell → 以管理员身份运行 → python context_menu_manager.py

许可
----
MIT License
"""

import tkinter as tk
from tkinter import ttk, messagebox
import winreg
import subprocess
import re


# ============================================================================
#  注册表扫描配置
#  每个元组: (界面分类名, 子类型, HKEY 常量, 子键路径)
#  程序从这些路径枚举所有右键菜单项
# ============================================================================

REGISTRY_SCANS = [
    # 文件右键菜单
    ("所有文件", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"*\shell"),
    ("所有文件", "ShellExtension", winreg.HKEY_CLASSES_ROOT, r"*\shellex\ContextMenuHandlers"),

    # 文件夹右键菜单
    ("文件夹", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"Directory\shell"),
    ("文件夹", "ShellExtension", winreg.HKEY_CLASSES_ROOT, r"Directory\shellex\ContextMenuHandlers"),

    # 桌面 / 文件夹空白处右键菜单
    ("桌面/文件夹背景", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"Directory\Background\shell"),

    # 驱动器右键菜单
    ("驱动器", "shell 动词", winreg.HKEY_CLASSES_ROOT, r"Drive\shell"),
    ("驱动器", "ShellExtension", winreg.HKEY_CLASSES_ROOT, r"Drive\shellex\ContextMenuHandlers"),

    # 用户级文件右键菜单（HKCU 优先级高于 HKCR）
    ("用户级文件", "shell 动词", winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell"),
]

# HKEY 常量 → 注册表编辑器地址栏中的缩写
HKEY_NAMES = {
    winreg.HKEY_CLASSES_ROOT: "HKCR",
    winreg.HKEY_CURRENT_USER: "HKCU",
    winreg.HKEY_LOCAL_MACHINE: "HKLM",
}

# ============================================================================
#  regedit 跳转的语言适配
#  Windows 安装语言 ID → regedit 地址栏根节点名称
#  语言 ID 来源: HKLM\SYSTEM\CurrentControlSet\Control\Nls\Language\InstallLanguage
# ============================================================================

_REGEDIT_COMPUTER_LABELS = {
    "0804": "计算机",          # 中文简体
    "0409": "Computer",        # 英文美国
    "0809": "Computer",        # 英文英国
    "040c": "Ordinateur",      # 法文
    "0407": "Computer",        # 德文（regedit 在德文系统也用 "Computer"）
    "0411": "コンピューター",  # 日文
    "0412": "컴퓨터",          # 韩文
}


def get_regedit_computer_label():
    """读取当前 Windows 的安装语言，返回 regedit 地址栏根节点名称。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Nls\Language"
        ) as key:
            lang_id, _ = winreg.QueryValueEx(key, "InstallLanguage")
        return _REGEDIT_COMPUTER_LABELS.get(lang_id, "Computer")
    except OSError:
        return "Computer"


# ============================================================================
#  功能说明映射
#  根据注册表键名 / 命令行程序名 → 生成中文功能说明
#  匹配顺序见 describe_entry() 函数
# ============================================================================

# 第 1 层：按注册表键名精确匹配
# 键名来源于注册表 EnumKey，说明为中文
FUNCTION_DESCRIPTIONS = {
    # =========================================================================
    # Windows 系统内置
    # =========================================================================
    "open": "用默认程序打开文件",
    "edit": "编辑文件",
    "print": "打印文件",
    "runas": "以管理员身份运行",
    "runasuser": "以其他用户身份运行",
    "copy": "复制",
    "cut": "剪切",
    "paste": "粘贴",
    "delete": "删除",
    "rename": "重命名",
    "properties": "查看文件属性",
    "removeproperties": "从文件中移除属性信息",
    "pintohomefile": "将文件固定到「开始」屏幕",
    "pintohome": "将文件固定到「开始」屏幕",
    "pintostartscreen": "固定到开始屏幕",
    "pintotaskbar": "固定到任务栏",
    "unpinfromtaskbar": "从任务栏取消固定",
    "find": "在此位置搜索文件",
    "cmd": "在此位置打开命令提示符 (CMD)",
    "Powershell": "在此位置打开 PowerShell",
    "powershell": "在此位置打开 PowerShell",
    "Open in Windows Terminal": "在 Windows Terminal 中打开",
    "UpdateEncryptionSettings": "更新加密设置 (Windows 系统)",
    "UpdateEncryptionSettingsWork": "更新工作文件加密设置",
    "change-passphrase": "更改 BitLocker 密码",
    "change-pin": "更改 BitLocker PIN 码",
    "encrypt-bde": "启用 BitLocker 驱动器加密",
    "encrypt-bde-elev": "以管理员权限启用 BitLocker 加密",
    "manage-bde": "管理 BitLocker 驱动器加密",
    "ModernShare": "Windows 共享（就近共享/邮件/应用）",
    "sendto": "发送到（可移动设备/压缩文件夹等）",
    "troubleshoot": "兼容性疑难解答",
    "Restore": "还原到以前的版本",
    "format": "格式化磁盘",
    "eject": "弹出设备",

    # =========================================================================
    # 开发工具 & 编辑器
    # =========================================================================
    "VSCode": "用 Visual Studio Code 打开",
    "code": "用 Visual Studio Code 打开",
    "Open with VS Code": "用 Visual Studio Code 打开",
    "git_gui": "打开 Git GUI 图形界面",
    "git_shell": "打开 Git Bash 命令行",
    "git_bash": "打开 Git Bash 命令行",
    "Git Bash Here": "在此处打开 Git Bash",
    "Open with Sublime Text": "用 Sublime Text 打开",
    "Sublime Text": "用 Sublime Text 打开",
    "Open with Notepad++": "用 Notepad++ 打开",
    "Notepad++": "用 Notepad++ 打开",
    "Open with Vim": "用 Vim 编辑",
    "gvim": "用 GVim 编辑",
    "IntelliJ IDEA": "在 IntelliJ IDEA 中打开项目",
    "PyCharm": "在 PyCharm 中打开项目",
    "WebStorm": "在 WebStorm 中打开项目",
    "PhpStorm": "在 PhpStorm 中打开项目",
    "Rider": "在 Rider 中打开项目",
    "CLion": "在 CLion 中打开项目",
    "DataGrip": "在 DataGrip 中打开",
    "GoLand": "在 GoLand 中打开项目",
    "RubyMine": "在 RubyMine 中打开项目",
    "Android Studio": "在 Android Studio 中打开项目",
    "Atom": "用 Atom 编辑器打开",
    "Brackets": "用 Brackets 编辑器打开",
    "Cursor": "用 Cursor AI 编辑器打开",

    # =========================================================================
    # 压缩工具
    # =========================================================================
    "7-Zip": "7-Zip 压缩/解压菜单",
    "WinRAR": "WinRAR 压缩/解压菜单",
    "Bandizip": "Bandizip 压缩/解压菜单",
    "PeaZip": "PeaZip 压缩/解压菜单",
    "WinZip": "WinZip 压缩/解压菜单",
    "360zip": "360 压缩右键菜单",
    "HaoZip": "好压压缩/解压菜单",
    "2345好压": "好压压缩/解压菜单",
    "Add to archive": "添加到压缩文件",

    # =========================================================================
    # 安全软件
    # =========================================================================
    "EPP": "ESET 杀毒软件扫描菜单",
    "ESET": "ESET 杀毒软件扫描菜单",
    "Kaspersky": "卡巴斯基扫描菜单",
    "Avast": "Avast 杀毒扫描菜单",
    "AVG": "AVG 杀毒扫描菜单",
    "Norton": "Norton 杀毒扫描菜单",
    "Windows Defender": "Windows Defender 扫描",
    "WindowsDefender": "Windows Defender 扫描",
    "Malwarebytes": "Malwarebytes 扫描菜单",
    "360": "360 安全扫描菜单",
    "360safe": "360 安全扫描菜单",

    # =========================================================================
    # WPS / Office
    # =========================================================================
    "EncryptionMenu": "WPS 加密文件右键菜单",
    "Open with EncryptionMenu": "WPS 加密文件打开方式",
    "QingNseContextMenu": "WPS 轻办公右键菜单",
    "Open with kwpsshellext": "WPS 金山文档 Shell 扩展",
    "Open with qingshellext": "WPS 轻办公 Shell 扩展",
    "qkdesktopshellext": "WPS 桌面管理 Shell 扩展",
    "wps": "WPS Office 右键菜单",

    # =========================================================================
    # 云存储
    # =========================================================================
    "OneDrive": "OneDrive 云盘操作",
    "Dropbox": "Dropbox 云盘操作",
    "Google Drive": "Google Drive 云盘操作",
    "BaiduNetdisk": "百度网盘操作",
    "BaiduYun": "百度网盘操作",
    "阿里云盘": "阿里云盘操作",
    "坚果云": "坚果云同步操作",

    # =========================================================================
    # 版本控制
    # =========================================================================
    "TortoiseGit": "TortoiseGit 版本控制菜单",
    "TortoiseSVN": "TortoiseSVN 版本控制菜单",
    "SVN": "SVN 版本控制菜单",

    # =========================================================================
    # 文件对比 & 工具
    # =========================================================================
    "Beyond Compare": "用 Beyond Compare 比较文件",
    "BeyondCompare": "用 Beyond Compare 比较文件",
    "WinMerge": "用 WinMerge 比较文件",
    "Everything": "用 Everything 搜索",

    # =========================================================================
    # 媒体播放
    # =========================================================================
    "VLC": "VLC 媒体播放器右键菜单",
    "Play with VLC": "用 VLC 播放",
    "Add to VLC": "添加到 VLC 播放列表",
    "PotPlayer": "PotPlayer 播放器右键菜单",
    "KMPlayer": "KMPlayer 播放器右键菜单",
    "MPC": "Media Player Classic 播放器",

    # =========================================================================
    # 图形 & 截图
    # =========================================================================
    "ShareX": "ShareX 截图/上传工具",
    "Snagit": "Snagit 截图工具",
    "Greenshot": "Greenshot 截图工具",

    # =========================================================================
    # 其他系统 & 工具
    # =========================================================================
    "Sharing": "Windows 文件共享选项",
    "Share": "Windows 共享选项",
    "WorkFolders": "Windows 工作文件夹同步",
    "Offline Files": "脱机文件同步管理",
    "Open With": "选择其他程序打开文件",
    "Open With EncryptionMenu": "加密文件打开方式",
    "Mount": "装载虚拟光驱 (ISO/IMG)",
    "imgburn": "ImgBurn 刻录/映像工具",
    "AnyDesk": "AnyDesk 远程协助",
    "TeamViewer": "TeamViewer 远程协助",
    "ToDesk": "ToDesk 远程协助",
    "Sunlogin": "向日葵远程控制",
    "ScreenCapture": "截图工具",
}

# 第 2 层：解析命令字符串中的 exe 文件名，匹配程序描述
EXE_DESCRIPTIONS = {
    # 编辑器 / IDE
    "Code.exe": "用 Visual Studio Code 打开",
    "code-insiders.exe": "用 VS Code Insiders 打开",
    "cursor.exe": "用 Cursor AI 编辑器打开",
    "notepad++.exe": "用 Notepad++ 打开",
    "notepad.exe": "用记事本打开",
    "sublime_text.exe": "用 Sublime Text 打开",
    "atom.exe": "用 Atom 编辑器打开",
    "gvim.exe": "用 GVim 编辑",
    "vim.exe": "用 Vim 编辑",
    "devenv.exe": "用 Visual Studio 打开",
    "idea64.exe": "用 IntelliJ IDEA 打开",
    "pycharm64.exe": "用 PyCharm 打开",
    "webstorm64.exe": "用 WebStorm 打开",
    "phpstorm64.exe": "用 PhpStorm 打开",
    "clion64.exe": "用 CLion 打开",
    "rider64.exe": "用 Rider 打开",
    "goland64.exe": "用 GoLand 打开",
    "datagrip64.exe": "用 DataGrip 打开",
    "rubymine64.exe": "用 RubyMine 打开",
    "android-studio.exe": "用 Android Studio 打开",
    "studio64.exe": "用 Android Studio 打开",

    # Windows 系统
    "explorer.exe": "在资源管理器中打开",
    "cmd.exe": "在此打开命令提示符",
    "powershell.exe": "在此打开 PowerShell",
    "pwsh.exe": "在此打开 PowerShell 7",
    "wt.exe": "在 Windows Terminal 中打开",
    "wsl.exe": "在 WSL (Linux 子系统) 中打开",
    "mspaint.exe": "用画图打开",
    "notepad.exe": "用记事本打开",
    "snippingtool.exe": "截图工具",
    "mstsc.exe": "远程桌面连接",

    # 浏览器
    "chrome.exe": "用 Chrome 浏览器打开",
    "firefox.exe": "用 Firefox 浏览器打开",
    "msedge.exe": "用 Edge 浏览器打开",
    "brave.exe": "用 Brave 浏览器打开",
    "opera.exe": "用 Opera 浏览器打开",
    "vivaldi.exe": "用 Vivaldi 浏览器打开",
    "iexplore.exe": "用 Internet Explorer 打开",
    "360chrome.exe": "用 360 浏览器打开",
    "360se.exe": "用 360 安全浏览器打开",
    "sogouexplorer.exe": "用搜狗浏览器打开",
    "maxthon.exe": "用傲游浏览器打开",
    "qqbrowser.exe": "用 QQ 浏览器打开",

    # Git / 版本控制
    "git-bash.exe": "在此打开 Git Bash",
    "git.exe": "Git 版本控制操作",
    "TortoiseGitProc.exe": "TortoiseGit 版本控制",
    "TortoiseProc.exe": "TortoiseSVN 版本控制",
    "TortoiseMerge.exe": "文件差异比较",

    # 压缩工具
    "7zFM.exe": "7-Zip 文件管理器",
    "7zG.exe": "7-Zip 图形界面",
    "WinRAR.exe": "WinRAR 压缩文件管理器",
    "Bandizip.exe": "Bandizip 压缩工具",
    "bz.exe": "Bandizip 命令行工具",
    "peazip.exe": "PeaZip 压缩工具",
    "winzip32.exe": "WinZip 压缩工具",
    "winzip64.exe": "WinZip 压缩工具",
    "HaoZip.exe": "好压压缩工具",

    # 云存储
    "OneDrive.exe": "OneDrive 云盘",
    "Dropbox.exe": "Dropbox 云盘",
    "googledrivesync.exe": "Google Drive 云盘",

    # 媒体播放
    "vlc.exe": "VLC 媒体播放器",
    "PotPlayerMini64.exe": "PotPlayer 播放器",
    "PotPlayerMini.exe": "PotPlayer 播放器",
    "KMPlayer.exe": "KMPlayer 播放器",
    "mplayerc.exe": "Media Player Classic 播放器",
    "mpc-hc64.exe": "MPC-HC 播放器",
    "mpc-be64.exe": "MPC-BE 播放器",
    "foobar2000.exe": "Foobar2000 音乐播放器",
    "wmplayer.exe": "Windows Media Player",
    "qqmusic.exe": "QQ 音乐",
    "cloudmusic.exe": "网易云音乐",

    # 截图 / 录屏
    "ShareX.exe": "ShareX 截图/上传",
    "Snagit32.exe": "Snagit 截图工具",
    "SnagitEditor.exe": "Snagit 截图编辑器",
    "Greenshot.exe": "Greenshot 截图工具",
    "obs64.exe": "OBS Studio 录屏/直播",
    "obs32.exe": "OBS Studio 录屏/直播",

    # 远程控制
    "AnyDesk.exe": "AnyDesk 远程协助",
    "TeamViewer.exe": "TeamViewer 远程协助",
    "ToDesk.exe": "ToDesk 远程协助",
    "SunloginClient.exe": "向日葵远程控制",

    # 文件工具
    "Everything.exe": "Everything 文件搜索",
    "Everything64.exe": "Everything 文件搜索",
    "BCompare.exe": "Beyond Compare 文件比较",
    "WinMergeU.exe": "WinMerge 文件比较",
    "TotalCommander.exe": "Total Commander 文件管理器",
    "TOTALCMD64.EXE": "Total Commander 文件管理器",
    "XYplorer.exe": "XYplorer 文件管理器",

    # Python
    "python.exe": "用 Python 运行",
    "pythonw.exe": "用 Python 运行（无控制台窗口）",
    "idle.exe": "用 IDLE 编辑",

    # 图形 / 设计
    "Photoshop.exe": "用 Adobe Photoshop 打开",
    "illustrator.exe": "用 Adobe Illustrator 打开",
    "Gimp.exe": "用 GIMP 图像编辑器打开",
    "gimp-2.10.exe": "用 GIMP 图像编辑器打开",
    "inkscape.exe": "用 Inkscape 矢量编辑打开",
    "blender.exe": "用 Blender 打开",
    "paint.net.exe": "用 Paint.NET 图像编辑打开",
    "FSViewer.exe": "用 FastStone Image Viewer 查看",

    # 游戏平台
    "steam.exe": "Steam 游戏平台",
    "EpicGamesLauncher.exe": "Epic Games 启动器",
    "GalaxyClient.exe": "GOG Galaxy 游戏平台",

    # 输入法 / 翻译
    "YoudaoDict.exe": "有道词典",
    "QTranslate.exe": "QTranslate 翻译工具",
}

# 第 3 层：按注册表键名前缀匹配
# 适用于 git_*、Tortoise* 等带家族前缀的键名
NAME_PREFIX_DESCRIPTIONS = {
    "git_": "Git 版本控制操作",
    "Git_": "Git 版本控制操作",
    "open_": "用关联程序打开",
    "Open_": "用关联程序打开",
    "ZZI": "讯飞语音助手上传",
    "TortoiseGit": "TortoiseGit 版本控制",
    "TortoiseSVN": "TortoiseSVN 版本控制",
    "VisualStudio": "Visual Studio 相关操作",
    "VSCode": "Visual Studio Code 相关操作",
    "Adobe": "Adobe 产品相关操作",
    "NVIDIA": "NVIDIA 显卡设置",
    "Intel": "Intel 显卡设置",
    "AMD": "AMD 显卡设置",
}


def describe_entry(entry):
    """
    为一条右键菜单项生成中文功能说明。

    匹配策略（按优先级从高到低）：
    1. 键名精确匹配 FUNCTION_DESCRIPTIONS（区分大小写）
    2. 键名忽略大小写匹配
    3. 显示名称匹配
    4. 键名前缀匹配 NAME_PREFIX_DESCRIPTIONS
    5. 命令字符串中的 exe 名称匹配 EXE_DESCRIPTIONS
    6. 尝试提取任意 .exe 文件名，生成"运行 xxx.exe 程序"
    7. Shellex 特殊检测（WPS / 7-Zip / CLSID 格式）
    8. 键名关键词推测（encrypt / share / scan / upload ...）
    9. 以上均未命中 → 返回 "—"
    """
    name = entry.get("name", "")
    command = entry.get("command", "")
    subtype = entry.get("subtype", "")

    # ── 第 1 层：精确匹配键名 ──
    if name in FUNCTION_DESCRIPTIONS:
        return FUNCTION_DESCRIPTIONS[name]
    # 忽略大小写再试一次（处理 "Open With" vs "open with" 等大小写不一致）
    name_lower_match = next(
        (v for k, v in FUNCTION_DESCRIPTIONS.items()
         if k.lower() == name.lower()), None
    )
    if name_lower_match:
        return name_lower_match
    if entry.get("display", "") in FUNCTION_DESCRIPTIONS:
        return FUNCTION_DESCRIPTIONS[entry["display"]]

    # ── 第 2 层：前缀匹配 ──
    for prefix, desc in NAME_PREFIX_DESCRIPTIONS.items():
        if name.startswith(prefix):
            return desc

    # ── 第 3 层：命令字符串中的 exe 名匹配 ──
    if command and command != "(空)" and command != "(无)":
        for exe_name, desc in EXE_DESCRIPTIONS.items():
            if exe_name.lower() in command.lower():
                return desc
        # 提取任意 .exe 文件名作为兜底说明
        exe_match = re.search(r'([\w-]+\.exe)["\s]', command, re.IGNORECASE)
        if exe_match:
            return f"运行 {exe_match.group(1)} 程序"

    # ── 第 4 层：Shellex 特殊检测 ──
    # Shellex 项的键名通常是程序名或 CLSID，没有 command 子键，
    # 只能靠名称和 CLSID 格式来推测
    if subtype == "ShellExtension":
        # 压缩工具
        if "7-Zip" in name or "zip" in name.lower() or "7z" in name.lower():
            return "7-Zip 压缩/解压右键菜单"
        if "rar" in name.lower() or "winrar" in name.lower():
            return "WinRAR / RAR 压缩右键菜单"
        if "bandizip" in name.lower() or "bandi" in name.lower():
            return "Bandizip 压缩右键菜单"
        if "peazip" in name.lower() or "pea" in name.lower():
            return "PeaZip 压缩右键菜单"
        # WPS
        if "qing" in name.lower() or "kwps" in name.lower() or "kingsoft" in name.lower():
            return "WPS Office 右键扩展"
        if "kdesktop" in name.lower():
            return "WPS 桌面管理扩展"
        # 云存储
        if "onedrive" in name.lower():
            return "OneDrive 云盘右键扩展"
        if "dropbox" in name.lower():
            return "Dropbox 云盘右键扩展"
        if "googledrive" in name.lower() or "gdfs" in name.lower():
            return "Google Drive 云盘右键扩展"
        # 安全软件
        if "egis" in name.lower() or "eset" in name.lower() or "epp" in name.lower():
            return "安全软件（ESET / 其他）右键扫描扩展"
        if "kaspersky" in name.lower() or "kav" in name.lower():
            return "卡巴斯基右键扫描扩展"
        if "avast" in name.lower() or "avg" in name.lower():
            return "Avast/AVG 右键扫描扩展"
        if "norton" in name.lower() or "symantec" in name.lower():
            return "Norton / Symantec 右键扫描扩展"
        if "malwarebytes" in name.lower() or "mbam" in name.lower():
            return "Malwarebytes 右键扫描扩展"
        if "defender" in name.lower():
            return "Windows Defender 右键扫描扩展"
        # 版本控制
        if "tortoise" in name.lower():
            return "Tortoise 版本控制右键扩展"
        # 文件比较
        if "beyond" in name.lower() and "compare" in name.lower():
            return "Beyond Compare 文件对比扩展"
        if "winmerge" in name.lower():
            return "WinMerge 文件对比扩展"
        # 搜索工具
        if "everything" in name.lower():
            return "Everything 文件搜索扩展"
        # 截图
        if "sharex" in name.lower():
            return "ShareX 截图/上传扩展"
        if "snagit" in name.lower():
            return "Snagit 截图扩展"
        if "greenshot" in name.lower():
            return "Greenshot 截图扩展"
        # 媒体播放
        if "vlc" in name.lower():
            return "VLC 媒体播放器扩展"
        # 显卡
        if "nvidia" in name.lower():
            return "NVIDIA 显卡设置扩展"
        if ("intel" in name.lower() and
            ("graphics" in name.lower() or "gfx" in name.lower())):
            return "Intel 显卡设置扩展"
        if "amd" in name.lower() and ("catalyst" in name.lower() or
                                       "radeon" in name.lower() or "adrenalin" in name.lower()):
            return "AMD 显卡设置扩展"
        # CLSID 格式的键名（GUID 花括号），没有可读的程序名
        if name.startswith("{") and name.endswith("}"):
            return "第三方程序注册的 Shell 扩展（GUID 格式，需查 CLSID 确定来源）"
        return "第三方程序的右键扩展功能"

    # ── 第 5 层：关键词推测（适用于未命中精确表的 shell 动词） ──
    name_lower = name.lower()
    # 加密 / 安全
    if "encrypt" in name_lower or "crypt" in name_lower:
        return "文件/驱动器加密操作"
    if "decrypt" in name_lower:
        return "文件/驱动器解密操作"
    if "scan" in name_lower or "check" in name_lower:
        return "安全扫描文件"
    # 共享
    if "share" in name_lower or "sharing" in name_lower:
        return "文件共享与权限设置"
    # 媒体
    if "play" in name_lower or "player" in name_lower:
        return "播放媒体文件"
    if "convert" in name_lower:
        return "转换媒体文件格式"
    # 云 / 备份
    if "upload" in name_lower:
        return "上传文件到云端"
    if "download" in name_lower:
        return "从云端下载文件"
    if "backup" in name_lower:
        return "备份文件"
    if "sync" in name_lower:
        return "同步文件"
    if "cloud" in name_lower:
        return "云存储操作"
    # WPS / Office
    if "wps" in name_lower or "qing" in name_lower or "kingsoft" in name_lower:
        return "WPS Office 相关功能"
    # 压缩
    if "compress" in name_lower or "extract" in name_lower or "archive" in name_lower:
        return "压缩/解压文件操作"
    # 编辑
    if "edit" in name_lower:
        return "编辑文件"
    if "view" in name_lower:
        return "查看文件"
    # 系统
    if "mount" in name_lower:
        return "装载磁盘映像"
    if "unmount" in name_lower or "eject" in name_lower:
        return "弹出/卸载设备"
    if "format" in name_lower:
        return "格式化磁盘"
    # 终端
    if "terminal" in name_lower or "console" in name_lower:
        return "在此打开终端"
    if "bash" in name_lower:
        return "在此打开 Bash Shell"
    if "shell" in name_lower and "extension" not in name_lower:
        return "在此打开命令行"
    # 浏览器
    if "browser" in name_lower:
        return "用浏览器打开"
    # 编辑 / IDE
    if "studio" in name_lower and "code" not in name_lower:
        return "用开发工具打开"
    # 远程
    if "remote" in name_lower or "desk" in name_lower:
        return "远程协助/桌面连接"

    return "—"


# ============================================================================
#  注册表读写工具函数
# ============================================================================

def get_reg_value(key_handle, name=""):
    """
    安全读取注册表值。
    读取失败（键不存在 / 权限不足）返回 None，不抛异常。
    """
    try:
        value, _ = winreg.QueryValueEx(key_handle, name)
        return value
    except OSError:
        return None


# ============================================================================
#  注册表扫描
#  从注册表路径枚举所有右键菜单项，构建统一数据结构
# ============================================================================

def scan_shell_entries(hkey, base_subkey, category):
    """
    扫描 shell 动词类右键菜单项。

    Shell 动词的结构（以 VSCode 为例）：
        HKCR\\*\\shell\\VSCode
            (Default) = "Open with VS Code"      ← 显示名称
            LegacyDisable = ""                    ← 如果存在，表示被禁用
            command\\                              ← 子键
                (Default) = "C:\\...\\Code.exe" "%1"

    返回：条目列表，每项为包含 category / subtype / name / command 等字段的 dict。
    """
    entries = []
    try:
        with winreg.OpenKey(
            hkey, base_subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as parent:
            idx = 0
            while True:
                try:
                    name = winreg.EnumKey(parent, idx)
                    idx += 1
                    subkey_path = f"{base_subkey}\\{name}"

                    with winreg.OpenKey(
                        hkey, subkey_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                    ) as key:
                        display = get_reg_value(key) or name
                        disabled = get_reg_value(key, "LegacyDisable") is not None
                        command = ""
                        try:
                            with winreg.OpenKey(
                                hkey, f"{subkey_path}\\command", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                            ) as cmd_key:
                                command = get_reg_value(cmd_key) or ""
                        except OSError:
                            pass  # 部分 shell 项没有 command 子键（如子菜单容器）

                    entry = {
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
                    }
                    entry["description"] = describe_entry(entry)
                    entries.append(entry)
                except OSError:
                    break  # 枚举完毕或权限不足
    except OSError:
        pass  # 整个路径不存在或无法访问

    return entries


def scan_shellex_entries(hkey, base_subkey, category):
    """
    扫描 ShellExtension 类右键菜单项。

    Shellex 的结构（以 7-Zip 为例）：
        HKCR\\*\\shellex\\ContextMenuHandlers\\7-Zip
            (Default) = "{23170F69-40C1-278A-1001-000100010000}"  ← CLSID
            _OriginalCLSID = "..."                                 ← 本工具的备份（如果禁用过）

    返回：条目列表，与 scan_shell_entries 格式相同。
    """
    entries = []
    try:
        with winreg.OpenKey(
            hkey, base_subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        ) as parent:
            idx = 0
            while True:
                try:
                    name = winreg.EnumKey(parent, idx)
                    idx += 1
                    subkey_path = f"{base_subkey}\\{name}"

                    with winreg.OpenKey(
                        hkey, subkey_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                    ) as key:
                        clsid = get_reg_value(key) or ""
                        backup = get_reg_value(key, "_OriginalCLSID")
                        # 判断禁用状态：(Default) 为空 且 存在我们的备份标记
                        disabled = (clsid == "" and backup is not None)

                    entry = {
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
                    }
                    entry["description"] = describe_entry(entry)
                    entries.append(entry)
                except OSError:
                    break
    except OSError:
        pass

    return entries


def scan_all():
    """
    扫描所有 REGISTRY_SCANS 中定义的注册表路径。
    返回合并后的条目列表，供 UI 使用。
    """
    all_entries = []
    for category, subtype, hkey, subkey in REGISTRY_SCANS:
        if "shellex" in subtype.lower() or "ShellExtension" in subtype:
            all_entries.extend(scan_shellex_entries(hkey, subkey, category))
        else:
            all_entries.extend(scan_shell_entries(hkey, subkey, category))
    return all_entries


# ============================================================================
#  启用 / 禁用操作
#  所有操作返回 (success: bool, error_message: str | None)
# ============================================================================

def disable_shell_entry(hkey, subkey):
    """
    禁用 shell 动词：写入 LegacyDisable 值。

    机制说明：
        Windows 资源管理器在加载右键菜单时，会检查 shell 键下是否存在
        ``LegacyDisable`` 值（REG_SZ 类型）。如果存在，该菜单项将被跳过，
        不显示在右键菜单中。这是 Windows 官方支持的隐藏机制。

        要重新启用，只需删除该值。整个过程不删除任何键或数据，完全可逆。
    """
    try:
        with winreg.OpenKey(
            hkey, subkey, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
        ) as key:
            winreg.SetValueEx(key, "LegacyDisable", 0, winreg.REG_SZ, "")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except OSError as e:
        return False, str(e)


def enable_shell_entry(hkey, subkey):
    """
    启用 shell 动词：删除 LegacyDisable 值。
    """
    try:
        with winreg.OpenKey(
            hkey, subkey, 0, winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
        ) as key:
            winreg.DeleteValue(key, "LegacyDisable")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except FileNotFoundError:
        # 值本来就不存在，已经是启用状态
        return True, None
    except OSError as e:
        return False, str(e)


def disable_shellex_entry(hkey, subkey):
    """
    禁用 Shellex 菜单项：备份 (Default) 值，然后清空。

    机制说明：
        Shellex 菜单项通过 COM CLSID 注册。(Default) 值存储的是 CLSID 字符串。
        Windows 资源管理器读取该 CLSID 后加载对应的 COM DLL 来渲染菜单。

        本工具的禁用方式：
        1. 将原始 (Default) 值备份到 _OriginalCLSID 值
        2. 将 (Default) 设为空字符串（""）
        3. 资源管理器读取到空 CLSID → 无法加载 COM → 菜单项不显示

        恢复时从 _OriginalCLSID 读取原始值并写回 (Default)，然后删除备份。
    """
    try:
        with winreg.OpenKey(
            hkey, subkey, 0,
            winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
        ) as key:
            original = get_reg_value(key) or ""
            winreg.SetValueEx(key, "_OriginalCLSID", 0, winreg.REG_SZ, original)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")
        return True, None
    except PermissionError:
        return False, "权限不足，请以管理员身份运行。"
    except OSError as e:
        return False, str(e)


def enable_shellex_entry(hkey, subkey):
    """
    启用 Shellex 菜单项：从 _OriginalCLSID 恢复 (Default) 值。
    """
    try:
        with winreg.OpenKey(
            hkey, subkey, 0,
            winreg.KEY_READ | winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY
        ) as key:
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


# ============================================================================
#  主应用 GUI
#  布局：顶部工具栏 | 左侧分类树 (PanedWindow) 右侧详情面板 | 底部状态栏
# ============================================================================

class ContextMenuManager:
    """
    Windows 右键菜单管理器 GUI。

    界面结构：
    ┌──────────────────────────────────────────────────────┐
    │  工具栏：[刷新] [在注册表中打开选中项]                 │
    ├───────────────┬──────────────────────────────────────┤
    │  分类树        │  详情面板                            │
    │               │                                      │
    │  所有文件      │  名称: VSCode                        │
    │  ├ shell 动词 │  功能: 用 Visual Studio Code 打开    │
    │  │ ├ VSCode  │  类型: 所有文件 → shell 动词          │
    │  │ └ ...     │  路径: HKCR\\*\\shell\\VSCode           │
    │  └ Shellext  │  状态: 启用                           │
    │  文件夹        │                                      │
    │  ...          │  命令: "C:\\...\\Code.exe" "%1"       │
    │               │                                      │
    │               │  [ 禁用 ]  [ 启用 ]                   │
    ├───────────────┴──────────────────────────────────────┤
    │  状态栏: 共 35 项 | 启用: 28 | 禁用: 7               │
    └──────────────────────────────────────────────────────┘

    数据流：
    1. 启动 → scan_all() 扫描注册表 → 构建 entries 列表
    2. 按 category → subtype 两级分组 → 填充 Treeview
    3. 用户选中树节点 → 更新右侧详情面板
    4. 用户点击禁用/启用 → 调用对应操作函数 → 刷新
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("右键菜单管理工具")
        self.root.geometry("1080x640")
        self.root.minsize(900, 480)

        # entries: 所有扫描到的菜单项列表
        self.entries = []
        # item_data: Treeview item ID → entry dict 的映射（选中时快速查找）
        self.item_data = {}
        # tree_nodes: (category,) 或 (category, subtype) → Treeview item ID

        self._setup_style()
        self._build_ui()
        self._refresh()  # 启动时自动扫描注册表

    def _setup_style(self):
        """选择最匹配当前 Windows 版本的 ttk 主题。"""
        style = ttk.Style()
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "xpnative" in available:
            style.theme_use("xpnative")

    # ──────────────────────────────────────────────────────────
    #  UI 构建
    # ──────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── 顶部工具栏 ──
        toolbar = ttk.Frame(self.root, padding=(8, 6))
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="刷新", command=self._refresh).pack(
            side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar, text="在注册表中打开选中项",
                   command=self._open_in_regedit).pack(side=tk.LEFT)

        # ── 主区域：可拖拽分隔的左右面板 ──
        pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        # ── 左侧：Treeview 分类树 ──
        left_frame = ttk.Frame(pane)
        # 5 列：#0 (树) + name + status + description + command
        tree_cols = ("name", "status", "description", "command")
        self.tree = ttk.Treeview(
            left_frame, columns=tree_cols, show="tree headings", selectmode="browse"
        )
        self.tree.heading("#0", text="注册表键名")
        self.tree.heading("name", text="显示名称")
        self.tree.heading("status", text="状态")
        self.tree.heading("description", text="功能说明")
        self.tree.heading("command", text="命令")

        # stretch=False：列宽固定，内容超出时依靠横向滚动条
        self.tree.column("#0", width=250, minwidth=120, stretch=False)
        self.tree.column("name", width=130, minwidth=70, stretch=False)
        self.tree.column("status", width=60, minwidth=50, anchor=tk.CENTER, stretch=False)
        self.tree.column("description", width=200, minwidth=100, stretch=False)
        self.tree.column("command", width=300, minwidth=100, stretch=False)

        # 滚动条
        vsb = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        # 选中事件 → 更新右侧详情
        self.tree.bind("<<TreeviewSelect>>", self._on_selection_changed)
        pane.add(left_frame, weight=3)

        # ── 右侧：详情面板 ──
        right_frame = ttk.LabelFrame(self.root, text=" 详情 ", padding=(10, 8))
        pane.add(right_frame, weight=1)

        self.detail_widgets = {}
        detail_labels = [
            ("名称", "name"),
            ("功能说明", "description"),
            ("类型", "subtype"),
            ("注册表路径", "full_path"),
            ("状态", "status_text"),
        ]
        for row, (label, key) in enumerate(detail_labels):
            ttk.Label(right_frame, text=f"{label}:", font=("", 9, "bold")).grid(
                row=row, column=0, sticky=tk.W, pady=(8 if row > 0 else 0, 2))
            val = ttk.Label(right_frame, text="", wraplength=280)
            val.grid(row=row, column=0, sticky=tk.W, pady=(0, 0))
            self.detail_widgets[key] = val

        # 命令文本（可能很长，用只读 Text 组件以便复制）
        ttk.Label(right_frame, text="命令:", font=("", 9, "bold")).grid(
            row=6, column=0, sticky=tk.W, pady=(8, 2))
        self.cmd_text = tk.Text(
            right_frame, height=4, width=34, wrap=tk.WORD,
            font=("Consolas", 9), state=tk.DISABLED
        )
        self.cmd_text.grid(row=7, column=0, sticky="ew")

        # 操作按钮
        btn_frame = ttk.Frame(right_frame)
        btn_frame.grid(row=8, column=0, sticky=tk.W, pady=(16, 0))
        self.disable_btn = ttk.Button(
            btn_frame, text="禁用", command=self._disable_selected)
        self.disable_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.enable_btn = ttk.Button(
            btn_frame, text="启用", command=self._enable_selected)
        self.enable_btn.pack(side=tk.LEFT)
        # 初始无选中，按钮禁用
        self.disable_btn.configure(state=tk.DISABLED)
        self.enable_btn.configure(state=tk.DISABLED)

        right_frame.columnconfigure(0, weight=1)

        # ── 底部状态栏 ──
        self.status_bar = ttk.Label(
            self.root, text="", relief=tk.SUNKEN, anchor=tk.W, padding=(8, 2))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    # ──────────────────────────────────────────────────────────
    #  数据刷新
    # ──────────────────────────────────────────────────────────

    def _refresh(self):
        """
        重新扫描注册表并刷新 Treeview。

        分组策略：
        - 一级节点：category（如"所有文件"）
        - 二级节点：subtype（如"shell 动词"）
        - 三级叶节点：具体的右键菜单项
        """
        self.entries = scan_all()
        self.item_data.clear()

        # 清空现有树
        for item in self.tree.get_children():
            self.tree.delete(item)

        # 按 (category, subtype) 分组
        grouped = {}
        for entry in self.entries:
            key = (entry["category"], entry["subtype"])
            grouped.setdefault(key, []).append(entry)

        for (cat, sub), items in sorted(grouped.items()):
            # 一级：分类
            cat_iid = self.tree.insert(
                "", tk.END, text=cat, open=True, values=("", "", "", ""))
            # 二级：子类型
            sub_iid = self.tree.insert(
                cat_iid, tk.END, text=sub, open=True, values=("", "", "", ""))
            # 三级：具体项
            for entry in items:
                status_icon = "✅" if entry["enabled"] else "❌"
                cmd_preview = entry.get("command", "")
                if len(cmd_preview) > 50:
                    cmd_preview = cmd_preview[:47] + "..."

                iid = self.tree.insert(
                    sub_iid, tk.END,
                    text=entry["name"],       # 树列（#0）：注册表键名
                    values=(
                        entry["display"],     # 显示名称
                        status_icon,          # 状态图标
                        entry.get("description", "—"),  # 功能说明
                        cmd_preview,          # 命令预览
                    )
                )
                self.item_data[iid] = entry

        self._update_status_bar()
        self._clear_detail()

    def _update_status_bar(self):
        """更新底部状态栏统计。"""
        total = len(self.entries)
        enabled_count = sum(1 for e in self.entries if e["enabled"])
        disabled_count = total - enabled_count
        self.status_bar.configure(
            text=f"  共 {total} 项  |  启用: {enabled_count}  |  禁用: {disabled_count}  "
        )

    # ──────────────────────────────────────────────────────────
    #  详情面板
    # ──────────────────────────────────────────────────────────

    def _clear_detail(self):
        """清空详情面板所有字段，按钮置灰。"""
        for w in self.detail_widgets.values():
            w.configure(text="")
        self.cmd_text.configure(state=tk.NORMAL)
        self.cmd_text.delete("1.0", tk.END)
        self.cmd_text.configure(state=tk.DISABLED)
        self.disable_btn.configure(state=tk.DISABLED)
        self.enable_btn.configure(state=tk.DISABLED)

    def _on_selection_changed(self, event):
        """
        Treeview 选中项变化时，更新右侧详情面板。

        选中的是分类/子类型节点时（item_data 中无记录），清空详情。
        选中具体菜单项时，显示其所有字段并根据启用/禁用状态切换按钮。
        """
        selection = self.tree.selection()
        if not selection:
            self._clear_detail()
            return

        iid = selection[0]
        entry = self.item_data.get(iid)
        if entry is None:
            # 选中的是分类/子类型节点，不是具体菜单项
            self._clear_detail()
            self.disable_btn.configure(state=tk.DISABLED)
            self.enable_btn.configure(state=tk.DISABLED)
            return

        self.detail_widgets["name"].configure(text=entry["display"])
        self.detail_widgets["description"].configure(
            text=entry.get("description", "—"))
        self.detail_widgets["subtype"].configure(
            text=f"{entry['category']} → {entry['subtype']}")
        self.detail_widgets["full_path"].configure(text=entry["full_path"])
        self.detail_widgets["status_text"].configure(
            text="✅ 启用" if entry["enabled"] else "❌ 禁用")

        self.cmd_text.configure(state=tk.NORMAL)
        self.cmd_text.delete("1.0", tk.END)
        self.cmd_text.insert("1.0", entry.get("command", "(无)"))
        self.cmd_text.configure(state=tk.DISABLED)

        # 按钮状态：已启用 → 显示"禁用"按钮；已禁用 → 显示"启用"按钮
        if entry["enabled"]:
            self.disable_btn.configure(state=tk.NORMAL)
            self.enable_btn.configure(state=tk.DISABLED)
        else:
            self.disable_btn.configure(state=tk.DISABLED)
            self.enable_btn.configure(state=tk.NORMAL)

    # ──────────────────────────────────────────────────────────
    #  操作
    # ──────────────────────────────────────────────────────────

    def _get_selected_entry(self):
        """返回当前选中的菜单项 entry dict，无选中返回 None。"""
        sel = self.tree.selection()
        if not sel:
            return None
        return self.item_data.get(sel[0])

    def _disable_selected(self):
        """禁用当前选中的菜单项。"""
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
        """启用当前选中的菜单项。"""
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
        """
        在注册表编辑器中打开当前选中项的注册表位置。

        实现方式：
        1. 将目标路径写入 HKCU\\...\\Applets\\Regedit\\LastKey
        2. 启动 regedit.exe
        3. regedit 启动时读取 LastKey 并自动定位到该路径

        路径适配了 Windows 多语言（计算机 / Computer / コンピューター 等）。
        """
        entry = self._get_selected_entry()
        if not entry:
            messagebox.showinfo("提示", "请先选中一个菜单项。")
            return

        hkey_name = HKEY_NAMES.get(entry["hkey"], "?")
        reg_path = f"{get_regedit_computer_label()}\\{hkey_name}\\{entry['subkey']}"

        # 写入 LastKey，regedit 启动时会自动定位
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Applets\Regedit",
                0, winreg.KEY_WRITE
            ) as key:
                winreg.SetValueEx(key, "LastKey", 0, winreg.REG_SZ, reg_path)
        except PermissionError:
            pass  # 写 LastKey 失败不影响 regedit 启动，只是不会自动定位

        try:
            subprocess.Popen(["regedit.exe"])
        except OSError as e:
            messagebox.showerror("错误", f"无法启动注册表编辑器: {e}")

    def run(self):
        """启动主事件循环。"""
        self.root.mainloop()


def main():
    """程序入口：创建 GUI 实例并运行。"""
    app = ContextMenuManager()
    app.run()


if __name__ == "__main__":
    main()
