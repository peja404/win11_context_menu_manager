# Windows 右键菜单管理工具

一个 Python 写的 Windows 右键菜单管理器，可以查看、启用、禁用资源管理器右键菜单项。单文件，零外部依赖。

## 功能

- **扫描** 文件、文件夹、桌面背景、驱动器的所有右键菜单项（shell 动词 + ShellExtension）
- **中文说明** 自动识别每个菜单项的功能（VSCode、Git、7-Zip、WPS、Windows 系统项等）
- **一键禁用/启用**，完全可逆，不删除注册表数据
- **跳转到注册表** 一键打开 regedit 并定位到对应键值
- **跨电脑通用** 实时扫描本机注册表，支持多语言 Windows

## 运行

```bash
python context_menu_manager.py
```

**如果需要修改菜单项**（禁用/启用），请以管理员身份运行：

1. 右键 PowerShell / 命令提示符 → 以管理员身份运行
2. `python context_menu_manager.py`

## 环境要求

- Python 3.9+
- Windows 10 / 11
- 无需安装任何第三方库（仅使用内置 `tkinter` + `winreg`）

## 原理

Windows 右键菜单由注册表驱动，分为两种类型：

### Shell 动词

```
HKCR\*\shell\VSCode
    (Default) = "Open with VS Code"     ← 菜单显示名称
    command\                             ← 点击后执行的命令
        (Default) = "C:\...\Code.exe" "%1"
```

**禁用方式**：写入 `LegacyDisable`（REG_SZ）值。这是 Windows 原生支持的隐藏机制，删除该值即可恢复。

### ShellExtension

```
HKCR\*\shellex\ContextMenuHandlers\7-Zip
    (Default) = "{23170F69-...}"        ← COM 组件 CLSID
```

**禁用方式**：将 `(Default)` 值的 CLSID 备份到 `_OriginalCLSID`，然后清空 `(Default)`。恢复时从备份写回。

## 扫描范围

| 分类 | 路径 |
|------|------|
| 所有文件 (shell) | `HKCR\*\shell` |
| 所有文件 (shellex) | `HKCR\*\shellex\ContextMenuHandlers` |
| 文件夹 (shell) | `HKCR\Directory\shell` |
| 文件夹 (shellex) | `HKCR\Directory\shellex\ContextMenuHandlers` |
| 桌面背景 | `HKCR\Directory\Background\shell` |
| 驱动器 | `HKCR\Drive\shell` |
| 用户级文件 | `HKCU\Software\Classes\*\shell` |

## 界面

```
┌─────────────────────────────────────────────────────────┐
│  工具栏：[刷新] [在注册表中打开选中项]                     │
├──────────────┬──────────────────────────────────────────┤
│  注册表键名   │  详情                                    │
│              │                                          │
│  📂 所有文件 │  名称: VSCode                            │
│   ├ shell 动词│  功能说明: 用 Visual Studio Code 打开    │
│   │ ├ VSCode │  类型: 所有文件 → shell 动词              │
│   │ └ cmd   │  注册表路径: HKCR\*\shell\VSCode           │
│   └ Shellext │  状态: ✅ 启用                           │
│  📂 文件夹   │                                          │
│  ...         │  命令: "C:\...\Code.exe" "%1"            │
│              │                                          │
│              │  [ 禁用 ]  [ 启用 ]                       │
├──────────────┴──────────────────────────────────────────┤
│  共 35 项 | 启用: 28 | 禁用: 7                          │
└─────────────────────────────────────────────────────────┘
```

## 安全性

- 只操作 `LegacyDisable` 值（shell 动词）和 `(Default)` / `_OriginalCLSID` 值（shellex），不删除任何注册表键
- 所有操作完全可逆
- 备份值带 `_OriginalCLSID` 标记，不会与其他程序冲突

## 许可

MIT License
