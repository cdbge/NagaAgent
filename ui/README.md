# ui — 桌面表现层

基于 PyQt5 的界面层，运行在**主线程**（`main.py` 中唯一需要事件循环的部分）
三个网络服务都在后台线程里，UI 通过 HTTP 与它们通信

## 目录

```
ui/
├── pyqt_chat_window.py   主窗口（组装各组件、订阅服务端事件）
├── components/           可复用组件：进度条、Live2D 侧栏、标题栏、侧边栏、
│                         意图分析页（widget_intent_analysis.py）、
│                         心智云图页（widget_mindmap.py）
│                         设置页见下方「设置页的三个文件」
├── controller/           工具控制器：chat / voice / document / game / live2d / mindmap / side / setting
├── live2d/                Live2D 渲染、动画、模型配置
├── styles/                QSS 样式与按钮工厂
├── tray/                  系统托盘（后台驻留、开机自启）
├── utils/                 消息渲染、简单 HTTP 客户端、设置项候选值、风格热重载
└── img/                   图片资源（含下拉箭头等 QSS 用图）
```

> **配置的唯一来源是根目录 `config.json`**（由 `core/system/config.py` 读取）
> UI 侧不另存环境变量副本，也不直接读写配置文件 —— 一律经配置管理器

### 设置页的三个文件

依赖单向：

```
settings_widgets.py     SettingCard / SettingGroup（卡片与可折叠分组基件）
        ↑
settings_groups.py      SettingsGroupsMixin（10 个 create_*_group 界面构建方法）
        ↑
widget_settings.py      ElegantSettingsWidget / SettingWidget（生命周期、信号、
                        加载 load_current_settings、保存 save_settings）
```

新增设置项：在 `settings_groups.py` 建控件 + 建 `SettingCard(..., "配置键")`，
再在 `load_current_settings()` 里补回填

> ⚠️ 加载侧是手写 `hasattr` 判断（约 25 处），控件改名会静默跳过，新增控件务必核对回填代码

## 页面顺序（组件与主窗口的对应关系）

`chat_stack` 的页序与侧边栏顺序**不同**，必须显式对应，改动时注意：

| chat_stack 索引 | 页面 | 侧边栏索引 |
|---|---|---|
| 0 | 聊天 | 0 对话 |
| 1 | 设置 | —（由托盘/设置入口进入） |
| 2 | **博弈图**（`IntentAnalysisWidget`） | 2 博弈图 |
| 3 | **心智云图**（`MindMapWidget`） | 1 心智云图 |

### `widget_mindmap.py`

**纯画布**：无工具条、标题、边框与滚动条；背景透明以融合主窗口的深色半透明底
操作走**右键菜单**（重新生成 / 在浏览器打开 / 打开数据目录）
进入页面时自动判断数据是否比图谱新，是则重新生成，因此没有刷新按钮

依赖 `PyQtWebEngine`（内嵌网页渲染）；缺失时退化为提示 + 浏览器打开，不会让界面崩掉

### `widget_intent_analysis.py`

展示后台意图分析的实测记录（时间、状态、发现的工具、分发回执、耗时），
每 3 秒轮询 `/intent_analysis/records`页面隐藏时停止轮询，关闭时回收线程

## 分层约定（重要，请遵守）

1. **优先新增 `components/` 下的 widget**，不要在 `pyqt_chat_window.py` 里直接堆界面代码
2. 组件**验证通过后**才接进主窗口
3. 业务调用统一走 `controller/`，不要把 HTTP 请求或配置读写写进 widget
4. 与后端交互一律通过 `utils/simple_http_client.py`；不要在 UI 里直接 import 服务层模块
5. 消息渲染统一走 `utils/message_renderer.py`（轻量 Markdown → HTML）
6. 设置项的**候选值**（字体、模型、后端、语音等有限集合）统一放
   `utils/setting_options.py`，不要在设置页里硬编码列表
7. 端口不要写死，用 `core.system.config.get_current_port("<name>")`

## 与其它层的关系

```
ui/  ──HTTP──▶  servers/apiserver   (:8000)
     ──HTTP──▶  servers/mcpserver   (:8003)
     ──导入──▶  core/system/config  （仅读取配置与端口）
```

## 已修复

- 消息不会自动滚动到底部
- 自动滚动时跨线程调用 Qt 导致崩溃
- 加载中进度条显示异常

## 待修复

- 心智云图调用
- agent manager 相关问题

## 更新日志

### 4.1

对 UI 架构做了重构，大幅解耦：把一个 2000 行的单体 window 拆分开，
组件按文件夹归类，形成接近 MVC 的结构，使外层业务调用更易理解
