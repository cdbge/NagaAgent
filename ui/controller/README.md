# ui/controller — 工具控制器

> 以下是原作者（ray）留下的手写须知，原样保留：
>
> ```
> #修改须知（手写版） by ray
> 这里的大多数tool都依赖chat，注意不要循环依赖了
> 每个类都有一个实例化对象，我用@lazy进行了加载
> 我们用__init__.py直接把把对应的对象导出包
> ```

## 现有控制器

每个 `tool_*.py` 里有一个类 + 一个 `@lazy` 单例，通过 `__init__.py` 导出，
外部一律 `from ui.controller import xxx` 取用

| 文件 | 单例 | 职责 |
|---|---|---|
| `tool_chat.py` | `chat` | 消息收发与渲染、流式/打字机、历史持久化、工具调用卡片 |
| `tool_document.py` | `document` | 文档上传与处理 |
| `tool_game.py` | `game` | 「博弈图」页对应的**意图分析开关**（调 `/intent_analysis/toggle`） |
| `tool_live2d.py` | `live2d` | Live2D 显示模式切换、情绪/动作触发 |
| `tool_mindmap.py` | `mindmap` | 心智云图 —— 生成图谱并在浏览器打开 |
| `tool_setting.py` | `setting` | 把配置变更即时应用到界面（透明度、字体等） |
| `tool_side.py` | `side` | 侧栏宽度与动画 |
| `tool_voice.py` | `voice` | 语音输入/输出的 UI 侧控制 |

「博弈图」页的界面在 `ui/components/widget_intent_analysis.py`；
`tool_game.py` 只提供该页对应的开关，两者职责不同

## 约定

1. 控制器可以依赖 `chat`，但 `chat` 不反向依赖具体控制器
   需要回调时用信号（如 `ChatTool.tool_ai_response_received`）
2. `@lazy` 单例在**首次属性访问所在线程**中构造，因此不要从非 GUI 线程
   首次触碰 `chat` —— `ChatTool` 是 `QObject`，其实例化的 `QTimer` 与信号槽
   都要求 GUI 线程
3. 控制器只做业务编排，不直接堆界面代码；布局属于 `components/` 下的 widget
