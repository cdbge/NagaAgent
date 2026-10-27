# 系统托盘模块使用说明

## 概述
系统托盘模块提供控制台托盘功能：把终端窗口隐藏到系统托盘，并附带开机自启动开关

> 托盘功能与自启动管理都集中在 `console_tray.py`

## 文件结构
```
ui/tray/
├── __init__.py              # 模块初始化文件
├── console_tray.py          # 控制台托盘（含自启动管理）
└── README.md                # 使用说明文档
```

## 功能特性

### 1. 控制台托盘功能
- 控制台窗口隐藏/显示
- 系统托盘图标管理
- 右键菜单操作
- 双击显示控制台

### 2. 自启动功能
- 注册表方式自启动（Windows）
- 启动项方式自启动（macOS / Linux）
- 自启动状态查询与切换

### 3. 窗口管理
- 自动隐藏控制台到托盘
- 从托盘恢复控制台
- 从任务栏隐藏/恢复

## 使用方法

### 集成控制台托盘
```python
from ui.tray.console_tray import integrate_console_tray

# 集成控制台托盘功能
console_tray = integrate_console_tray()
```

### 直接创建
```python
from ui.tray.console_tray import create_console_tray

tray = create_console_tray(auto_hide=True)
```

### 手动控制
```python
# 隐藏 / 显示控制台
tray.hide_console_window()
tray.show_console_window()

# 开机自启动开关
tray._toggle_auto_start()
```

## 启动方式

```bash
# 带控制台启动（会显示托盘图标）
python main.py

# 无控制台启动（推荐）
pythonw main.py
```

## 依赖库
```bash
pip install pystray pillow PyQt5
```

## 配置说明

### 托盘图标
- 默认使用 `ui/img/window_icon.png`
- 备用图标 `ui/img/standby.png`

### 托盘菜单
- 显示控制台
- 隐藏控制台
- 开机自启动开关
- 退出应用

### 退出行为
点击「退出应用」会**先让各窗口走 `closeEvent` 做资源清理**（取消在跑的请求、
停止进度动画、释放 Live2D 的渲染定时器与 GL 资源、关闭心智云图的 WebEngine 视图），
再退出 Qt 事件循环

> 不使用 `os._exit()`：那样会跳过 atexit 与 Qt 析构，上述资源不会被释放

## 控制台托盘功能

### 特性
- 自动检测控制台窗口句柄（Windows / macOS / Linux 分别实现）
- 支持隐藏/显示控制台窗口
- 托盘图标右键菜单
- 双击显示控制台

### 使用方法
1. 运行 `python main.py`
2. 系统启动后会在托盘显示图标
3. 右键托盘图标选择「隐藏控制台」
4. 双击托盘图标或选择「显示控制台」恢复

### 快捷键
- 双击托盘图标：显示控制台
- 右键托盘图标：显示菜单
