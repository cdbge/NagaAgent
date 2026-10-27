# -*- coding: utf-8 -*-
"""以「脱离父进程树」的方式启动 NagaAgent。

背景：在 harness 里用普通后台任务/Start-Process 拉起来的进程，
仍然挂在同一个 Windows Job 对象里；父 shell 被回收时，
子进程会被一起杀掉 —— 表现为「应用莫名其妙消失，日志没有 traceback」。

CREATE_BREAKAWAY_FROM_JOB + DETACHED_PROCESS 让它彻底独立，
父进程死掉也不影响。
"""

import os
import subprocess
import sys

ROOT = r"D:\Desktop\NagaAgent"
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

out = open(os.path.join(ROOT, "data", "app_stdout.log"), "wb")
err = open(os.path.join(ROOT, "data", "app_stderr.log"), "wb")

env = dict(os.environ)
env["PYTHONUTF8"] = "1"
env["PYTHONIOENCODING"] = "utf-8"

flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
try:
    flags |= CREATE_BREAKAWAY_FROM_JOB
except Exception:
    pass

p = subprocess.Popen(
    [PY, "-X", "faulthandler", "-u", "main.py"],
    cwd=ROOT,
    stdout=out,
    stderr=err,
    stdin=subprocess.DEVNULL,
    env=env,
    creationflags=flags,
    close_fds=True,
)
print("PID", p.pid)
