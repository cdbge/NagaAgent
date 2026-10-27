#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 pyproject.toml 的 dependencies 重新生成 requirements.txt，保持两者一致。

仅取 [project].dependencies（运行时依赖），不含可选依赖组。
分组标题按包名归类生成，便于人读。
"""
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(r"D:\Desktop\NagaAgent")
PYPROJECT = REPO / "pyproject.toml"
REQ = REPO / "requirements.txt"

data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
deps = data["project"]["dependencies"]

# 分组规则（前缀匹配，按顺序优先）
GROUPS = [
    ("Web / API 服务", ["fastapi", "uvicorn", "flask", "python-multipart", "websockets"]),
    ("LLM / Agent / MCP", ["openai", "mcp", "fastmcp", "langchain"]),
    ("桌面界面", ["pyqt5"]),
    ("配置 / 序列化", ["pydantic", "json5", "charset-normalizer", "pyyaml"]),
    ("HTTP / 网络", ["requests", "aiohttp", "httpx", "html2text", "python-dotenv"]),
    ("浏览器自动化", ["playwright", "crawl4ai"]),
    ("知识图谱 / 记忆", ["kuzu", "py2neo", "neo4j", "pyvis"]),
    ("Live2D", ["live2d-py"]),
    ("语音 / 音频 / TTS", ["edge-tts", "sounddevice", "pydub", "librosa", "numpy", "scipy",
                            "soundfile", "pygame", "gevent", "emoji", "pyaudio"]),
    ("系统控制 / Windows 集成", ["pyautogui", "psutil", "pyopengl", "pystray", "paho-mqtt",
                                  "comtypes", "pycaw", "screen-brightness-control", "winshell"]),
    ("图像 / OCR", ["pillow", "opencv-python", "pytesseract"]),
    ("文档", ["python-docx", "msoffcrypto-tool", "docx2pdf"]),
    ("其他业务", ["bilibili-api", "markdown", "jmcomic"]),
]


def base_name(spec: str) -> str:
    return re.split(r"[<>=!\[;]", spec, 1)[0].strip().lower()


buckets: dict[str, list[str]] = {g[0]: [] for g in GROUPS}
other: list[str] = []

for dep in deps:
    bn = base_name(dep)
    placed = False
    for title, prefixes in GROUPS:
        if any(bn == p for p in prefixes):
            buckets[title].append(dep)
            placed = True
            break
    if not placed:
        other.append(dep)

lines = [
    "# 本文件由 pyproject.toml 的 [project].dependencies 生成，请勿手工编辑。",
    "# 重新生成：python scripts/gen_requirements.py",
    "# 安装时 uv sync 会读取 pyproject.toml 与 uv.lock；本文件供 pip 用户使用。",
    "",
]

total = 0
for title, _ in GROUPS:
    items = buckets[title]
    if not items:
        continue
    lines.append(f"# ---------- {title} ----------")
    lines.extend(sorted(items))
    lines.append("")
    total += len(items)

if other:
    lines.append("# ---------- 其他 ----------")
    lines.extend(sorted(other))
    lines.append("")
    total += len(other)

out = "\n".join(lines).rstrip() + "\n"

print(f"  pyproject 依赖数: {len(deps)}")
print(f"  写入 requirements 数: {total}")
if total != len(deps):
    print(f"  [WARN] 数量不一致，请检查分组规则")
    sys.exit(2)

if "--apply" in sys.argv:
    REQ.write_text(out, encoding="utf-8")
    print(f"  已写入 {REQ}")
else:
    print("  (dry-run; pass --apply)")
    print("  --- 预览 ---")
    for l in out.splitlines()[:24]:
        print("   ", l)
