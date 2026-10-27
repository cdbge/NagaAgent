# Live2D集成模块

这是NAGA Agent项目中独立的Live2D集成模块，不依赖外部的Live2D-Virtual-Girlfriend项目

## 模块结构

```
ui/live2d/
├── __init__.py          # 模块初始化文件（只导出下面三件）
├── renderer.py          # Live2D渲染器
├── animator.py          # 动画系统
├── widget.py            # Live2D Widget组件
├── emotion_binding.py   # 情绪识别 -> 表情/动作映射
├── live2d_models/       # Live2D模型文件夹
│   └── 重音テト/         # 当前模型
│       └── 重音テト.model3.json
└── README.md            # 说明文档
```

配套的应用内组件在 `ui/components/widget_live2d_side.py`（`Live2DSideWidget`），
负责把 Live2D 画布贴到主窗口侧栏，并提供编辑模式、动作面板等 UI 功能

> **配置来源**：Live2D 参数统一读 `core/system/config.py` 的 `config.live2d`

## 主要组件

### 1. Live2DRenderer (renderer.py)
- 负责Live2D模型的加载、渲染和基础操作
- 提供模型参数设置、动作触发等功能
- 独立于UI组件，可复用

### 2. Live2DAnimator (animator.py)
- 动画系统管理器
- 包含多种动画器：
  - `BlinkAnimator`: 眨眼动画
  - `EyeBallAnimator`: 眼球跟踪动画
  - `BodyAngleAnimator`: 身体摆动动画
  - `BreathAnimator`: 呼吸动画
  - `EmotionAnimator`: 情绪动画
- `LipSyncAnimator`: 口型同步（读取 `config.live2d.lip_sync_*` 开关与参数）

### 3. Live2DWidget (widget.py)
- 基于 `QOpenGLWidget` 的Live2D显示组件
- 集成渲染器和动画系统
- 提供鼠标交互功能

### 4. 情绪绑定 (emotion_binding.py)
- `detect_emotion()`: 从 AI 回复文本识别情绪
- `pick_expression()` / `bind_emotion_to_live2d()`: 映射到模型的表情与动作
- 由 `ui/controller/tool_chat.py` 在回复结束时调用，
  可用 `live2d.auto_emotion` / `live2d.emotion_min_intensity` 调整

## 使用方法

### 基本使用
```python
from ui.live2d import Live2DWidget

# 创建Live2D Widget
live2d_widget = Live2DWidget(parent)

# 加载模型
success = live2d_widget.load_model(
    "ui/live2d/live2d_models/重音テト/重音テト.model3.json")

# 设置情绪
live2d_widget.set_emotion("happy", intensity=0.8)

# 设置口型（0.0 ~ 1.0）
live2d_widget.set_mouth_form(0.5)   # 或 set_audio_volume(volume)
```

### 在 Live2DSideWidget 中使用
```python
from ui.components.widget_live2d_side import Live2DSideWidget

# 创建侧栏 Widget
side_widget = Live2DSideWidget()

# 设置 Live2D 模型（路径相对仓库根目录）
side_widget.set_live2d_model(
    "ui/live2d/live2d_models/重音テト/重音テト.model3.json")

# 设置回退图片（模型不可用时显示）
side_widget.set_fallback_image("ui/img/standby.png")

# 切换 Live2D / 图片模式
side_widget.toggle_display_mode()

# 退出前释放资源（60FPS 渲染定时器 + GL 资源）
side_widget.cleanup()
```

> `cleanup()` 由 `ChatWindow.closeEvent()` 统一调用，
> 用于释放 60FPS 渲染定时器与 GL 资源

## 特性

- ✅ 独立的模块设计，不依赖外部项目
- ✅ 完整的动画系统支持
- ✅ 鼠标交互功能
- ✅ 自动回退到图片模式
- ✅ 资源管理和清理
- ✅ 错误处理和日志记录
- ✅ 随 AI 回复情绪自动切换表情/动作

## 依赖要求

- `live2d-py`: Live2D Python绑定
  （**锁定 0.5.4**：1.0.0 只提供 `v2` 模块，没有代码所需的 `v3`）
- `PyQt5`: GUI框架
- `opensimplex`: 噪声生成（可选，用于更自然的动画）

### 噪声模块安装

为了获得最佳的动画效果，建议安装噪声模块：

```bash
# 安装opensimplex（纯Python实现，无需编译）
pip install opensimplex
```

**注意**：如果没有安装opensimplex模块，系统会自动降级到简化模式，使用正弦波生成动画

## 配置

Live2D 功能在 `config.json` 的 `live2d` 段配置（也可在设置页「UI 风格配置」里改，
模型已做成下拉选择）：

```json
{
  "live2d": {
    "enabled": true,
    "model_path": "ui/live2d/live2d_models/重音テト/重音テト.model3.json",
    "fallback_image": "ui/img/standby.png",
    "auto_switch": true,
    "animation_enabled": true,
    "touch_interaction": true,
    "scale_factor": 1.0,
    "auto_emotion": true,
    "emotion_min_intensity": 0.35,
    "lip_sync_enabled": true,
    "lip_sync_smooth_factor": 0.3,
    "lip_sync_volume_scale": 1.5,
    "lip_sync_volume_threshold": 0.01
  }
}
```

## 注意事项

1. 确保已安装 `live2d-py` 包（版本锁定 0.5.4）
2. 模型文件路径必须正确 —— 设置页的下拉会扫描 `live2d_models/` 自动列出
3. 如果 Live2D 不可用，会自动回退到图片模式（`fallback_image`）
4. 动画系统需要噪声模块支持，但可以降级运行
5. `PyQt5.QtWebEngineWidgets` 与 Live2D 的 OpenGL 上下文共存时，
   必须在创建 `QApplication` **之前**设置 `Qt.AA_ShareOpenGLContexts`
   （`main.py` 已处理）
