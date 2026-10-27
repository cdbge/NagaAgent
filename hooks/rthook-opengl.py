"""PyInstaller 运行时钩子：在冻结环境里正确初始化 OpenGL。

为什么需要它
============

`hook-OpenGL.py` 解决的是「模块没被打包进去」；这个钩子解决的是
「打包进去了但初始化失败」：

1. **日志噪音** —— PyOpenGL 启动时会打一堆 WARNING（找不到加速层、
   平台探测失败等），在打包版里用户会误以为程序出错。这里把噪音压到
   ERROR，只保留 `OpenGL.acceleratesupport` 的 WARNING（它能告诉维护者
   加速模块到底有没有生效）。

2. **平台探测** —— 冻结后 `sys._MEIPASS` 的目录结构与源码树不同，
   某些后端会去找相对路径而失败。这里显式设置 `PYOPENGL_PLATFORM`
   （若用户已设置则尊重用户值）。

3. **Linux 库路径** —— Linux 打包版需要把 `_internal` 加进
   `LD_LIBRARY_PATH` 才能找到随包的 EGL 库。Windows 上这段不执行。

运行时钩子必须写进 spec 的 `runtime_hooks=[...]`。PyInstaller 只自动识别
`hookspath` 下的 `hook-<module>.py`，`rthook-*.py` 不会自动生效。
"""

import logging
import os
import sys

# --- 1) 压制噪音日志 -------------------------------------------------------
logging.getLogger("OpenGL").setLevel(logging.ERROR)
logging.getLogger("OpenGL.plugins").setLevel(logging.ERROR)
# 保留 WARNING：它能说明加速模块是否被正确打包
logging.getLogger("OpenGL.acceleratesupport").setLevel(logging.WARNING)


def _setup_opengl_environment() -> None:
    """设置打包环境下的 OpenGL 环境变量与库搜索路径。"""

    # --- 2) Linux：把 _internal 加入库搜索路径 -----------------------------
    if sys.platform.startswith("linux"):
        lib_paths = [
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib",
            "/usr/local/lib",
        ]
        if getattr(sys, "frozen", False):
            internal = os.path.join(getattr(sys, "_MEIPASS", ""), "_internal")
            if os.path.isdir(internal):
                lib_paths.append(internal)

        current = os.environ.get("LD_LIBRARY_PATH", "")
        new_paths = [p for p in lib_paths if os.path.isdir(p) and p not in current]
        if new_paths:
            os.environ["LD_LIBRARY_PATH"] = (
                ":".join(new_paths + [current]) if current else ":".join(new_paths)
            )

    # --- 3) 平台后端：尊重用户已有设置，没有则留空让 PyOpenGL 自己探测 ----
    #    注意不能硬编码成 'win32'：同一个包在 Wine / WSL 下可能需要别的后端。
    os.environ.setdefault("PYOPENGL_PLATFORM", os.environ.get("PYOPENGL_PLATFORM", ""))

    # --- 4) 若 EGL 后端已被加载但不可用，回退到基础平台 --------------------
    #    模块名是 `baseplatform`（没有下划线）
    if "OpenGL.platform.egl" in sys.modules:
        try:
            import OpenGL.platform
            from OpenGL.platform import baseplatform

            OpenGL.platform.use(baseplatform.BasePlatform)
        except Exception:
            # 回退失败不致命：真正的可用性由渲染层自己判断
            pass


# 导入时立即执行 —— 必须早于 live2d / PyOpenGL 的任何实际使用
_setup_opengl_environment()
