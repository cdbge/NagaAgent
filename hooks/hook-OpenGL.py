"""PyInstaller 钩子：收集 OpenGL（PyOpenGL）的子模块与平台文件。

为什么需要这个钩子
==================

Live2D 渲染依赖 PyOpenGL。PyInstaller 的静态分析**看不到** PyOpenGL 的
平台后端：它在运行时按 `sys.platform` 动态 import
（`OpenGL.platform.win32` / `egl` / `glx` / `darwin`），
这些名字不出现在任何 `import` 语句里，因此不会被打包进去。

后果是：开发环境跑得好好的，打包后一开 Live2D 就报
`ImportError: cannot import name 'win32' from 'OpenGL.platform'`，
而常规日志里看不出缺了什么。

这个钩子做两件事：

1. `collect_submodules('OpenGL')` —— 把全部子模块收进 hiddenimports；
2. 显式补上四个平台后端 + `OpenGL_accelerate`（装了才收）。

`OpenGL_accelerate` 是可选的 C 加速层。它**不存在也不影响运行**
（PyOpenGL 会回退到纯 Python 实现），所以这里用 try/except 包住，
不能因为它没装就让整个打包失败。
"""

import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = []
datas = []
binaries = []

try:
    # 1) OpenGL 的全部子模块（含 accel 相关的内部模块）
    hiddenimports = collect_submodules("OpenGL")

    # 2) 平台后端：运行时按 sys.platform 动态选择，静态分析永远看不到
    #    注意模块名是 `baseplatform`（没有下划线）。写成 `base_platform`
    #    不会报错，但 PyInstaller 会静默跳过 —— 打包后才发现缺模块。
    hiddenimports.extend([
        "OpenGL.platform",
        "OpenGL.platform.baseplatform",
        "OpenGL.platform.ctypesloader",
        "OpenGL.platform.win32",
        "OpenGL.platform.egl",
        "OpenGL.platform.glx",
        "OpenGL.platform.darwin",
        "OpenGL.platform.osmesa",
    ])

    # 3) 可选加速层：装了才收，没装跳过（不影响功能，只是慢一点）
    try:
        import OpenGL_accelerate  # noqa: F401
        hiddenimports.append("OpenGL_accelerate")
    except ImportError:
        pass

    # 4) 平台相关的数据文件（部分后端会读取随包附带的 .txt/.json）
    try:
        datas.extend(collect_data_files("OpenGL.platform"))
    except Exception:
        pass
    try:
        datas.extend(collect_data_files("OpenGL"))
    except Exception:
        pass

except Exception as exc:  # pragma: no cover - 打包期兜底
    # 宁可少收，也不要让打包直接失败
    print(f"[hook-OpenGL] 收集失败，按最小集合继续: {exc}")
    hiddenimports = ["OpenGL", "OpenGL.GL", "OpenGL.platform"]

# Linux 下 EGL 后端需要系统库；Windows 上不需要
if sys.platform.startswith("linux"):
    hiddenimports.extend(["OpenGL.EGL", "OpenGL.raw.EGL"])
    for candidate in (
        "/usr/lib/x86_64-linux-gnu/libEGL.so",
        "/usr/lib/libEGL.so",
        "/usr/local/lib/libEGL.so",
    ):
        if os.path.exists(candidate):
            binaries.append((candidate, "."))
