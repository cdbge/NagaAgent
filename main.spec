# -*- mode: python ; coding: utf-8 -*-

# pyproject.toml requires python >=3.11,<3.12

# 导入必要的模块
from PyInstaller.utils.hooks import copy_metadata
import os

# 收集包的 metadata
metadata_packages = ['fastmcp']
datas = []
for package in metadata_packages:
    try:
        datas += copy_metadata(package)
    except Exception as e:
        print(f"Warning: Could not copy metadata for {package}: {e}")

# 收集所有需要的资源文件
# (source_path, destination_in_bundle)
datas += [
    ('config.json.example', '.'),
    # 不要打包 config.json：它包含用户私有的 api_key / neo4j_password 等凭据。
    # 首次启动时由 build.py / setup 从 config.json.example 复制生成。
    ('LICENSE', '.'),
    ('pyproject.toml', '.'),
    ('README.md', '.'),
    ('requirements.txt', '.'),
]

# 收集需要包含的目录
# Tree 对象需要在 Analysis 中单独处理
trees = [
    Tree('servers', prefix='servers'),
    Tree('core', prefix='core'),
    Tree('data/logs', prefix='data/logs'),
    Tree('ui', prefix='ui'),
]

# 添加py2neo包的VERSION文件到数据文件
import py2neo
py2neo_path = py2neo.__file__
py2neo_dir = os.path.dirname(py2neo_path)
version_file = os.path.join(py2neo_dir, 'VERSION')
if os.path.exists(version_file):
    datas.append((version_file, 'py2neo'))

# 添加图标文件到数据文件
icon_files = [
    'ui/img/icons/naga_chat.png',
    'ui/img/icons/love_adventure.png',
    'ui/img/icons/personality_game.png',
    'ui/img/icons/mind_map.png'
]
for icon_file in icon_files:
    if os.path.exists(icon_file):
        datas.append((icon_file, 'ui/img/icons'))

# 添加样式文件到数据文件
datas.append(('ui/styles/progress.txt', 'ui/styles'))

# agent-manifest.json 已由上面的 Tree('servers') 整树打包，无需再单独收集。

a = Analysis(
    ['main.py'],
    pathex=[os.getcwd()],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'agents',
        'html2text',
        'docx',
        'jmcomic',
        'crawl4ai',
        'langchain_community',
        'playwright',
        'langchain_community.utilities',
        'fastmcp',
        'live2d',
    ],
    # hooks/ 下放 hook-<模块>.py，PyInstaller 会自动应用（见 hook-OpenGL.py）。
    # OpenGL 的平台后端是运行时按 sys.platform 动态 import 的，静态分析看不到，
    # 必须靠钩子补进 hiddenimports —— 否则打包后 Live2D 一定起不来。
    hookspath=[os.path.join(os.getcwd(), 'hooks')],
    hooksconfig={},
    # 运行时钩子不会自动生效，必须显式列出：压制 PyOpenGL 噪音日志、
    # 设置 PYOPENGL_PLATFORM、Linux 下补 LD_LIBRARY_PATH。
    runtime_hooks=['hooks/rthook-opengl.py'],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

# 添加 Tree 对象到分析结果
for tree in trees:
    a.datas += tree

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NagaAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False, # 不使用UPX，保证速度和兼容性
    console=True, # 保留控制台，便于查看服务日志与启动错误
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None # 您可以指定一个图标路径, e.g., icon='ui/img/icon.ico'
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='main',
)