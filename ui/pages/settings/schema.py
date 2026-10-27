#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全部设置的声明表。

**加一个设置 = 在这里加一行。** 不用碰 UI 代码。

约定
====

* 每个 Section 对应左侧一个编号类别；
* Field 的 key 必须是 `组.字段` 形式，直接对应 config 对象路径；
* 控件的存在由 `kind` 决定，可选逻辑用 `visible_when` 表达。
"""

from __future__ import annotations

from .spec import SECRET, SELECT, SLIDER, TEXT, TOGGLE, Field, Section


# ------------------------------------------------------------------ 动态选项
def _model_options():
    """可用模型列表。"""
    try:
        from core.system.config import DEEPSEEK_MODEL_FLASH, DEEPSEEK_MODEL_PRO

        return [
            ("DeepSeek Flash（快）", DEEPSEEK_MODEL_FLASH),
            ("DeepSeek Pro（强）", DEEPSEEK_MODEL_PRO),
        ]
    except Exception:
        return [("deepseek-flash", "deepseek-flash")]


def _theme_options():
    from ui.styles.tokens import theme_options

    return theme_options()


#: 中文字体关键字：优先排在前面，避免用户选到纯拉丁字体导致逐字回退
CJK_HINTS = ("YaHei", "SimHei", "SimSun", "Microsoft Ya", "Noto Sans CJK",
             "Source Han", "PingFang", "Hei", "Song", "Kai", "Ming")


def _font_options():
    """聊天可选字体：中文字体优先，其余按字母序补在后面。"""
    try:
        from PyQt5.QtGui import QFontDatabase

        fams = sorted(QFontDatabase().families())
        cjk = [f for f in fams if any(h.lower() in f.lower() for h in CJK_HINTS)]
        latin = [f for f in fams if f not in cjk]
        return [(f, f) for f in (cjk + latin)]
    except Exception:
        return [("Microsoft YaHei UI", "Microsoft YaHei UI")]


def _log_options():
    return [("DEBUG", "DEBUG"), ("INFO", "INFO"),
            ("WARNING", "WARNING"), ("ERROR", "ERROR")]


def _backend_options():
    return [("Kuzu（嵌入式，推荐）", "kuzu"),
            ("Neo4j（需自建服务）", "neo4j"),
            ("SQLite（标准库）", "sqlite")]


def _voice_mode_options():
    return [
        ("自动（auto）", "auto"),
        ("本地（local）", "local"),
        ("端到端（end2end）", "end2end"),
        ("混合（hybrid）", "hybrid"),
    ]


def _asr_provider_options():
    return [("本地 FunASR", "local"), ("通义千问", "qwen"), ("OpenAI", "openai")]


def _tts_voice_options():
    try:
        from core.system.config import config

        cur = getattr(config.voice_realtime, "tts_voice", "") or ""
        base = ["zh-CN-XiaoyiNeural", "zh-CN-YunxiNeural",
                "zh-CN-XiaoxiaoNeural", "zh-CN-YunjianNeural"]
        if cur and cur not in base:
            base.insert(0, cur)
        return [(v, v) for v in base]
    except Exception:
        return [("zh-CN-XiaoyiNeural", "zh-CN-XiaoyiNeural")]


# ------------------------------------------------------------------ 声明
SECTIONS = [
    Section(0, "API 配置", "对话模型与密钥", [
        SECRET("api.api_key", "API Key", "用于连接 DeepSeek 的密钥"),
        TEXT("api.base_url", "API Base URL", "API 基础地址"),
        SELECT("api.model", "AI 模型", _model_options, "选择用于对话的模型"),
        SLIDER("api.max_tokens", "最大 Token", 2048, 65536,
               "单次对话的最大长度限制", suffix=" tk"),
        SLIDER("api.max_history_rounds", "历史轮数", 5, 100,
               "上下文里保留最近多少轮对话", suffix=" 轮"),
        SLIDER("api.context_load_days", "加载天数", 1, 30,
               "从最近几天的日志里加载历史", suffix=" 天"),
    ]),

    Section(1, "系统配置", "名称、日志与语音播报", [
        TEXT("system.ai_name", "AI 名称", "修改后写入 config.json 的 system.ai_name"),
        SELECT("system.log_level", "日志级别", _log_options, "控制台与日志文件的详细程度"),
        TOGGLE("system.debug", "调试模式", "输出更详细的运行日志"),
        TOGGLE("system.voice_enabled", "启用语音播报", "AI 回复是否自动转成语音"),
    ]),

    Section(2, "界面风格", "主题、字体与外观", [
        SELECT("ui.theme", "界面主题", _theme_options, "保存后立即生效"),
        TEXT("ui.user_name", "用户昵称", "聊天窗口显示的昵称"),
        SLIDER("ui.window_bg_alpha", "界面不透明度", 0, 255,
               "窗口、消息气泡、Live2D 面板的整体不透明度"),
        SELECT("ui.animation_duration", "界面动画时长", [
            ("150ms（极快）", 150), ("250ms（快）", 250), ("400ms（标准）", 400),
            ("600ms（舒缓）", 600), ("900ms（很慢）", 900),
        ], "侧边栏、气泡入场等动画时长"),
        SELECT("ui.font_size", "聊天字体大小", [
            (f"{v} pt", v) for v in (12, 13, 14, 15, 16, 18, 20, 22, 24)
        ], "输入框与消息正文的字号"),
        SELECT("ui.font_family", "聊天字体", _font_options,
               "下拉列出系统已安装字体；中文建议选中文字体", editable=True),
    ]),

    Section(3, "记忆系统", "知识图谱与检索", [
        TOGGLE("grag.enabled", "启用记忆", "从对话中抽取长期事实写入知识图谱"),
        SELECT("grag.graph_backend", "存储后端", _backend_options, "知识图谱的存储方式"),
        TEXT("grag.kuzu_db_path", "Kuzu 目录", "相对仓库根目录"),
        SLIDER("grag.similarity_threshold", "相似度阈值", 0, 100,
               "检索记忆时的匹配门槛（越大越严格）",
               scale=0.01, decimals=2),
        TEXT("computer_control.model", "电脑控制模型", "用于电脑控制任务的主要模型"),
        TEXT("computer_control.model_url", "电脑控制 API 地址", "电脑控制模型的 API 地址"),
        SECRET("computer_control.api_key", "电脑控制 API 密钥", "电脑控制模型的 API 密钥"),
        TEXT("computer_control.grounding_model", "定位模型", "用于元素定位与坐标识别的模型"),
        TEXT("computer_control.grounding_url", "定位模型 API 地址", "定位模型的 API 地址"),
        SECRET("computer_control.grounding_api_key", "定位模型 API 密钥", "定位模型的 API 密钥"),
    ]),

    Section(4, "语音输入", "语音识别（ASR）", [
        TOGGLE("voice_realtime.enabled", "启用语音输入", "支持实时语音转文本"),
        SELECT("voice_realtime.voice_mode", "语音模式", _voice_mode_options,
               "决定走本地、端到端还是混合链路"),
        SELECT("voice_realtime.provider", "ASR 服务提供商", _asr_provider_options,
               "本地 = FunASR，云端需 API Key"),
        SECRET("voice_realtime.api_key", "API 密钥", "语音服务密钥（云端模式）"),
        TEXT("voice_realtime.model", "ASR 模型名称", "随服务商变化"),
        SLIDER("voice_realtime.vad_threshold", "静音检测阈值", 0, 100,
               "VAD 灵敏度（越小越容易触发）", scale=0.01, decimals=2),
    ]),

    Section(5, "语音输出", "语音合成（TTS）", [
        SELECT("voice_realtime.tts_voice", "TTS 语音", _tts_voice_options,
               "合成语音使用的音色", editable=True),
    ]),

    Section(6, "MQTT 配置", "物联网设备控制", [
        TEXT("mqtt.broker", "MQTT Broker", "MQTT 服务器地址"),
        SLIDER("mqtt.port", "MQTT 端口", 1, 65535, "MQTT 服务器端口"),
        TEXT("mqtt.username", "MQTT 用户名", "MQTT 服务器用户名"),
        SECRET("mqtt.password", "MQTT 密码", "MQTT 服务器密码"),
    ]),
]
