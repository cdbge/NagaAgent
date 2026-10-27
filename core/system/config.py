# config.py - 简化配置系统
"""
NagaAgent 配置系统 - 基于Pydantic实现类型安全和验证
支持配置热更新和变更通知
"""
import os
from pathlib import Path
from typing import Optional, List, Dict, Callable
from datetime import datetime

from PyQt5.QtWidgets import QWidget
from pydantic import BaseModel, Field, field_validator

from .deepseek import DEEPSEEK_BASE_URL, DEEPSEEK_DEFAULT_MODEL
from .json_config import load_config_json

# ========== 服务器端口配置 - 统一管理 ==========
# 端口唯一权威来源是 config.json（api_server / agentserver / mcpserver / tts 各节）。
# 原先这里另有一个硬编码的 ServerPortsConfig 快照，既读不到 config.json 也不随热重载
# 更新，形成"第二真相"，已删除。

# 端口默认值：仅作为 config.json 缺失或尚未加载时的兜底。
# 权威来源始终是 config.json（经由下方 _live_port 读取）。
_PORT_DEFAULTS = {
    # 注意：8000/8001/8003 在 Windows 上可能被 Hyper-V 动态预留
    # （excludedportrange 7971-8370），bind 会抛 WSAEACCES。
    # 故默认改用 18000 段。
    "api_server": 18000,
    "agent_server": 18001,
    "mcp_server": 18003,
    "tts_server": 15048,
    "asr_server": 15060,
}

def _live_port(server_name: str) -> int:
    """从已加载的 config.json 配置中读取端口。

    注意这里刻意使用模块级 ``config``（import 时才绑定），而不是 ``server_ports``：
    后者是 import 阶段构造的硬编码快照，既无法反映 config.json，也不会随热重载更新。
    """
    try:
        if server_name == "api_server":
            return config.api_server.port
        if server_name == "agent_server":
            return config.agentserver.port
        if server_name == "mcp_server":
            return config.mcpserver.port
        if server_name == "tts_server":
            return config.tts.port
        if server_name == "asr_server":
            return config.asr.port
    except Exception:
        # 首次加载过程中 config 可能尚未就绪，退回默认值
        pass
    return _PORT_DEFAULTS.get(server_name, 0)

def get_server_port(server_name: str) -> int:
    """获取指定服务器的端口号（来源：config.json）"""
    return _live_port(server_name)

def get_current_port(server_name: str) -> int:
    """get_server_port 的显式别名。

    语义是"解析当前应使用的端口"，与"读取某段配置"区分开，供启动脚本使用；
    所有端口都来自 config.json，缺失时由 _live_port 退回默认值。
    """
    return _live_port(server_name)

def get_all_server_ports() -> Dict[str, int]:
    """获取所有服务器端口配置（来源：config.json）"""
    return {name: _live_port(name) for name in _PORT_DEFAULTS}

# 配置变更监听器
_config_listeners: List[Callable] = []

# 为了向后兼容，提供AI_NAME常量
def get_ai_name() -> str:
    """获取AI名称"""
    return config.system.ai_name

def add_config_listener(callback: Callable):
    """添加配置变更监听器"""
    _config_listeners.append(callback)

def remove_config_listener(callback: Callable):
    """移除配置变更监听器"""
    if callback in _config_listeners:
        _config_listeners.remove(callback)

def notify_config_changed():
    """通知所有监听器配置已变更"""
    for listener in _config_listeners:
        try:
            listener()
        except Exception as e:
            print(f"配置监听器执行失败: {e}")

def setup_environment():
    """设置环境变量解决兼容性问题"""
    env_vars = {
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1", 
        "OPENBLAS_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.0",
        "PYTORCH_ENABLE_MPS_FALLBACK": "1"
    }
    for key, value in env_vars.items():
        os.environ.setdefault(key, value)

class SystemConfig(BaseModel):
    """系统基础配置"""
    version: str = Field(default="4.0.0", description="系统版本号")
    ai_name: str = Field(default="娜迦日达", description="AI助手名称")
    base_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent, description="项目根目录")
    log_dir: Path = Field(default_factory=lambda: Path(__file__).parent.parent.parent / "data" / "logs", description="日志目录")
    voice_enabled: bool = Field(default=True, description="是否启用语音功能")
    stream_mode: bool = Field(default=True, description="是否启用流式响应")
    debug: bool = Field(default=False, description="是否启用调试模式")
    log_level: str = Field(default="INFO", description="日志级别")

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v):
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f'日志级别必须是以下之一: {valid_levels}')
        return v.upper()

class APIConfig(BaseModel):
    """API服务配置"""
    api_key: str = Field(default="sk-placeholder-key-not-set", description="API密钥")
    base_url: str = Field(default=DEEPSEEK_BASE_URL, description="API基础URL")
    model: str = Field(default=DEEPSEEK_DEFAULT_MODEL, description="使用的模型名称")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    # 官方 deepseek-flash / deepseek-v4-pro 的最大输出为 384K；旧上限 32768 已过时
    max_tokens: int = Field(default=8192, ge=1, le=384000, description="最大输出token数")
    max_history_rounds: int = Field(default=100, ge=1, le=200, description="最大历史轮数")
    persistent_context: bool = Field(default=True, description="是否启用持久化上下文")
    context_load_days: int = Field(default=3, ge=1, le=30, description="加载历史上下文的天数")
    applied_proxy: bool = Field(default=True, description="是否应用代理")
    # 思考模式：官方两个模型默认开启 thinking；关闭可显著降低延迟与输出 token
    thinking_enabled: bool = Field(default=True, description="是否启用思考(thinking)模式")
    # 仅思考模式生效：低/中/高，用于权衡推理深度与成本
    reasoning_effort: str = Field(default="medium", description="推理强度: low/medium/high")
    # 原生 function calling：模型在生成过程中直接发起工具调用，省掉「先做一次
    # 意图分析判断要调哪个工具」的额外模型往返。关掉会退回旧的单轮流式链路。
    function_calling_enabled: bool = Field(
        default=True, description="是否启用原生 function calling（模型自主调用工具）")
    # 工具路由：工具很多时先用一次轻量分类缩小工具表，避免每轮都为用不到的
    # 工具付 token。**默认关闭** —— 它本身要花一次模型调用，工具少时不划算。
    # 另有硬性门槛：工具数少于 40 个时无论开关如何都不启用（见 intent_router.py）。
    intent_router_enabled: bool = Field(
        default=False, description="是否启用工具路由（仅工具数超过 40 时生效）")
    # 自身控制：把「改配置/切模型/开关语音/Live2D/设表情」做成模型可调用的工具。
    # 关掉后这些工具不会出现在模型的工具表里。
    control_enabled: bool = Field(
        default=True, description="是否允许模型通过工具控制应用自身")

class HandoffConfig(BaseModel):
    """工具调用循环配置（config.json: handoff）"""
    max_loop_stream: int = Field(
        default=5, ge=1, le=20,
        description="流式对话中工具调用循环的最大轮数")
    max_loop_non_stream: int = Field(
        default=3, ge=1, le=20,
        description="非流式对话中工具调用循环的最大轮数")

class ServicePortConfig(BaseModel):
    """仅含端口/启用的服务配置（Agent 服务器、MCP 服务器）

    config.json 里已经存在 agentserver / mcpserver 两节，但 NagaConfig 之前并未声明
    对应字段，配合 model_config 的 extra="ignore"，用户配置的端口会被静默丢弃。
    """
    enabled: bool = Field(default=True, description="是否启用该服务")
    host: str = Field(default="127.0.0.1", description="监听主机")
    port: int = Field(default=0, ge=0, le=65535, description="监听端口")
    auto_start: bool = Field(default=True, description="启动时自动启动该服务")

class APIServerConfig(BaseModel):
    """API服务器配置"""
    enabled: bool = Field(default=True, description="是否启用API服务器")
    host: str = Field(default="127.0.0.1", description="API服务器主机")
    port: int = Field(default=18000, ge=1, le=65535, description="API服务器端口")
    auto_start: bool = Field(default=True, description="启动时自动启动API服务器")

class GRAGConfig(BaseModel):
    """GRAG知识图谱记忆系统配置"""
    enabled: bool = Field(default=False, description="是否启用GRAG记忆系统")
    auto_extract: bool = Field(default=False, description="是否自动提取对话中的五元组")
    context_length: int = Field(default=5, ge=1, le=20, description="记忆上下文长度")
    similarity_threshold: float = Field(default=0.6, ge=0.0, le=1.0, description="记忆检索相似度阈值")
    neo4j_uri: str = Field(default="neo4j://127.0.0.1:7687", description="Neo4j连接URI")
    neo4j_user: str = Field(default="neo4j", description="Neo4j用户名")
    neo4j_password: str = Field(default="your_password", description="Neo4j密码")
    neo4j_database: str = Field(default="neo4j", description="Neo4j数据库名")

    # ---- 以下四项被 task_manager 读取，但此前未在配置模型中声明 ----
    # 后果：task_manager.__init__ 的 try 块抛 AttributeError，被 except 静默兜底成
    # 硬编码值（其中 task_timeout=30）。而五元组抽取要走一次完整 LLM 调用，
    # 30 秒根本不够 -> 任务被判“执行超时” -> 结果被丢弃，记忆永远写不进去。
    task_timeout: int = Field(
        default=180, ge=10, le=1800,
        description="单个五元组抽取任务的总超时（秒），需容纳一次 LLM 调用，勿设过小")
    max_workers: int = Field(default=3, ge=1, le=16, description="抽取任务并发 worker 数")
    max_queue_size: int = Field(default=100, ge=1, le=1000, description="抽取任务队列容量")
    auto_cleanup_hours: int = Field(default=24, ge=1, le=720, description="已完成任务的自动清理周期（小时）")

    # ---- 图存储后端（可插拔） ----
    # kuzu   : 默认。嵌入式图数据库，pip 安装即用，无需服务/端口/Docker
    # neo4j  : 可选。需要独立 Neo4j 服务；有相应需求的用户切换到它
    # sqlite : 兜底。标准库自带，零依赖
    graph_backend: str = Field(
        default="kuzu",
        description="图存储后端: kuzu(默认) / neo4j / sqlite")
    kuzu_db_path: str = Field(
        default="data/graph.kuzu",
        description="Kuzu 数据库目录（相对仓库根目录）")


class BrowserConfig(BaseModel):
    """浏览器配置"""
    playwright_headless: bool = Field(default=False, description="Playwright浏览器是否无头模式")
    edge_lnk_path: str = Field(
        default=r'C:\Users\DREEM\Desktop\Microsoft Edge.lnk',
        description="Edge浏览器快捷方式路径"
    )
    edge_common_paths: List[str] = Field(
        default=[
            r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
            r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
            os.path.expanduser(r'~\AppData\Local\Microsoft\Edge\Application\msedge.exe')
        ],
        description="Edge浏览器常见安装路径"
    )

class TTSConfig(BaseModel):
    """TTS服务配置"""
    api_key: str = Field(default="", description="TTS服务API密钥")
    port: int = Field(default=15048, ge=1, le=65535, description="TTS服务端口")
    default_voice: str = Field(default="zh-CN-XiaoxiaoNeural", description="默认语音")
    default_format: str = Field(default="mp3", description="默认音频格式")
    default_speed: float = Field(default=1.0, ge=0.1, le=3.0, description="默认语速")
    default_language: str = Field(default="zh-CN", description="默认语言")
    remove_filter: bool = Field(default=False, description="是否移除过滤")
    require_api_key: bool = Field(default=False, description="是否需要API密钥")

class ASRConfig(BaseModel):
    """ASR输入服务配置"""
    port: int = Field(default=15060, ge=1, le=65535, description="ASR服务端口")





# ========== 新增：电脑控制配置 ==========
class ComputerControlConfig(BaseModel):
    """电脑控制配置"""
    enabled: bool = Field(default=True, description="是否启用电脑控制功能")
    model: str = Field(default="glm-4.5v", description="视觉/坐标识别模型")
    model_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", description="模型API地址")
    api_key: str = Field(default="", description="模型API密钥")
    grounding_model: str = Field(default="glm-4.5v", description="元素定位/grounding模型")
    grounding_url: str = Field(default="https://open.bigmodel.cn/api/paas/v4", description="grounding模型API地址")
    grounding_api_key: str = Field(default="", description="grounding模型API密钥")
    screen_width: int = Field(default=1920, description="逻辑屏幕宽度（用于缩放体系）")
    screen_height: int = Field(default=1080, description="逻辑屏幕高度（用于缩放体系）")
    max_dim_size: int = Field(default=1920, description="逻辑空间最大边尺寸")

# 天气服务使用免费API，无需配置

class MQTTConfig(BaseModel):
    """MQTT配置"""
    enabled: bool = Field(default=False, description="是否启用MQTT功能")
    broker: str = Field(default="localhost", description="MQTT代理服务器地址")
    port: int = Field(default=1883, ge=1, le=65535, description="MQTT代理服务器端口")
    topic: str = Field(default="/test/topic", description="MQTT主题")
    client_id: str = Field(default="naga_mqtt_client", description="MQTT客户端ID")
    username: str = Field(default="", description="MQTT用户名")
    password: str = Field(default="", description="MQTT密码")
    qos: int = Field(default=1, ge=0, le=2, description="服务质量等级")

class UIConfig(BaseModel):
    """用户界面配置"""
    user_name: str = Field(default="用户", description="默认用户名")
    bg_alpha: float = Field(default=0.5, ge=0.0, le=1.0, description="聊天背景透明度")
    window_bg_alpha: int = Field(default=110, ge=0, le=255, description="主窗口背景透明度")
    mac_btn_size: int = Field(default=36, ge=10, le=100, description="Mac按钮大小")
    mac_btn_margin: int = Field(default=16, ge=0, le=50, description="Mac按钮边距")
    mac_btn_gap: int = Field(default=12, ge=0, le=30, description="Mac按钮间距")
    animation_duration: int = Field(default=600, ge=100, le=2000, description="动画时长（毫秒）")
    # 聊天区字体。此前这两项在 pyqt_chat_window / tool_setting 里被硬编码为
    # 'Lucida Console', 16（共 3 处），无法调整；现统一由此配置驱动。
    font_family: str = Field(default="Lucida Console", description="聊天区字体（需系统已安装）")
    font_size: int = Field(default=14, ge=10, le=32, description="聊天区字号（pt）")
    # 界面主题：gfl（少女前线·战术，默认）/ rhine（莱茵生命·档案，浅色）/ default（深空）
    # 令牌定义见 ui/styles/tokens.py，切换后由 apply_ui_style() 即时换肤
    theme: str = Field(default="gfl", description="界面主题: gfl / rhine / default")

class Live2DConfig(BaseModel):
    """Live2D配置"""
    enabled: bool = Field(default=True, description="是否启用Live2D功能")
    # 默认值必须指向**真实存在**的模型。此前写的是 kasane_teto（仓库里没有这个模型），
    # 于是没有 config.json 的干净安装会静默回退到图片模式，且日志只说"模型不存在"。
    model_path: str = Field(
        default="ui/live2d/live2d_models/重音テト/重音テト.model3.json",
        description="Live2D模型文件路径（相对仓库根或绝对路径）")
    # 额外的模型扫描目录。设置页的「浏览…」选中模型后会自动把其父目录记进来，
    # 这样下次打开设置时该目录下的**所有**模型都会出现在下拉里。
    extra_model_dirs: List[str] = Field(
        default_factory=list,
        description="额外的Live2D模型扫描目录（绝对路径或相对仓库根）")
    fallback_image: str = Field(default="ui/img/standby.png", description="回退图片路径")
    auto_switch: bool = Field(default=True, description="是否自动切换模式")
    animation_enabled: bool = Field(default=True, description="是否启用动画")
    touch_interaction: bool = Field(default=True, description="是否启用触摸交互")
    scale_factor: float = Field(default=1.0, ge=0.5, le=3.0, description="Live2D缩放比例")

    # 情绪绑定：根据 AI 回复内容自动触发表情（见 ui/live2d/emotion_binding.py）
    auto_emotion: bool = Field(default=True, description="是否根据AI回复情绪自动切换表情")
    emotion_min_intensity: float = Field(default=0.35, ge=0.0, le=1.0, description="触发情绪表情的最低强度")
    
    # 嘴部同步配置
    lip_sync_enabled: bool = Field(default=True, description="是否启用嘴部同步动画")
    lip_sync_smooth_factor: float = Field(default=0.3, ge=0.1, le=1.0, description="嘴部动画平滑系数（越小越平滑）")
    lip_sync_volume_scale: float = Field(default=1.5, ge=0.5, le=5.0, description="音量放大系数（调整嘴部张开幅度）")
    lip_sync_volume_threshold: float = Field(default=0.01, ge=0.0, le=0.1, description="音量检测阈值（低于此值视为静音）")

class VoiceRealtimeConfig(BaseModel):
    """实时语音配置"""
    enabled: bool = Field(default=False, description="是否启用实时语音功能")
    provider: str = Field(default="qwen", description="语音服务提供商 (qwen/openai/local)")
    api_key: str = Field(default="", description="语音服务API密钥")
    model: str = Field(default="qwen3-omni-flash-realtime", description="语音模型名称")
    voice: str = Field(default="Cherry", description="语音角色")
    input_sample_rate: int = Field(default=16000, description="输入采样率")
    output_sample_rate: int = Field(default=24000, description="输出采样率")
    chunk_size_ms: int = Field(default=200, description="音频块大小（毫秒）")
    vad_threshold: float = Field(default=0.02, ge=0.0, le=1.0, description="静音检测阈值")
    echo_suppression: bool = Field(default=True, description="回声抑制")
    min_user_interval: float = Field(default=2.0, ge=0.5, le=10.0, description="用户输入最小间隔（秒）")
    cooldown_duration: float = Field(default=1.0, ge=0.5, le=5.0, description="冷却期时长（秒）")
    max_user_speech: float = Field(default=30.0, ge=5.0, le=120.0, description="最大说话时长（秒）")
    debug: bool = Field(default=False, description="是否启用调试模式")
    use_api_server: bool = Field(default=False, description="是否通过API Server处理（支持MCP调用）")
    voice_mode: str = Field(default="auto", description="语音模式：auto/local/end2end/hybrid（auto会根据provider自动选择）")
    asr_host: str = Field(default="localhost", description="本地ASR服务地址")
    asr_port: int = Field(default=5000, description="本地ASR服务端口")
    record_duration: int = Field(default=10, ge=5, le=60, description="本地模式最大录音时长（秒）")
    tts_voice: str = Field(default="zh-CN-XiaoyiNeural", description="TTS语音选择（本地/混合模式）")
    tts_host: str = Field(default="localhost", description="TTS服务地址")
    tts_port: int = Field(default=5061, ge=1, le=65535, description="TTS服务端口")
    auto_play: bool = Field(default=True, description="AI回复后自动播放语音")
    interrupt_playback: bool = Field(default=True, description="用户说话时自动打断AI语音播放")

class OnlineSearchConfig(BaseModel):
    """在线搜索配置"""
    searxng_url: str = Field(default="http://localhost:8080", description="SearXNG实例URL")
    engines: List[str] = Field(default=["google"], description="默认搜索引擎列表")
    num_results: int = Field(default=5, ge=1, le=20, description="搜索结果数量")

class SystemCheckConfig(BaseModel):
    """系统检测状态配置"""
    passed: bool = Field(default=False, description="系统检测是否通过")
    timestamp: str = Field(default="", description="检测时间戳")
    python_version: str = Field(default="", description="Python版本")
    project_path: str = Field(default="", description="项目路径")

# 提示词管理功能已集成到config.py中

class PromptManager:
    """提示词管理器 - 统一管理所有提示词模板"""
    
    def __init__(self, prompts_dir: str = None):
        """初始化提示词管理器"""
        if prompts_dir is None:
            # 默认使用system目录下的prompts文件夹
            prompts_dir = Path(__file__).parent / "prompts"
        
        self.prompts_dir = Path(prompts_dir)
        self.prompts_dir.mkdir(exist_ok=True)
        
        # 内存缓存
        self._cache = {}
        self._last_modified = {}
        
        # 初始化默认提示词
        self._init_default_prompts()
    
    def _init_default_prompts(self):
        """初始化默认提示词 - 现在从文件加载，不再硬编码"""
        # 检查是否存在默认提示词文件，如果不存在则创建
        default_prompts = ["conversation_analyzer_prompt","conversation_style_prompt"]
        
        for prompt_name in default_prompts:
            prompt_file = self.prompts_dir / f"{prompt_name}.txt"
            if not prompt_file.exists():
                print(f"警告：提示词文件 {prompt_name}.txt 不存在，请手动创建")
    
    def get_prompt(self, name: str, **kwargs) -> str:
        """获取提示词模板"""
        try:
            # 从缓存或文件加载
            content = self._load_prompt(name)
            if content is None:
                print(f"警告：提示词 '{name}' 不存在，使用默认值")
                return f"[提示词 {name} 未找到]"
            
            # 格式化模板
            if kwargs:
                try:
                    return content.format(**kwargs)
                except KeyError as e:
                    print(f"错误：提示词 '{name}' 格式化失败，缺少参数: {e}")
                    return content
            else:
                return content
                
        except Exception as e:
            print(f"错误：获取提示词 '{name}' 失败: {e}")
            return f"[提示词 {name} 加载失败: {e}]"
    
    def save_prompt(self, name: str, content: str):
        """保存提示词到文件"""
        try:
            prompt_file = self.prompts_dir / f"{name}.txt"
            with open(prompt_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 更新缓存
            self._cache[name] = content
            self._last_modified[name] = datetime.now()
            
            print(f"提示词 '{name}' 已保存")
            
        except Exception as e:
            print(f"错误：保存提示词 '{name}' 失败: {e}")
    
    def _load_prompt(self, name: str) -> Optional[str]:
        """从文件加载提示词"""
        try:
            prompt_file = self.prompts_dir / f"{name}.txt"
            
            if not prompt_file.exists():
                return None
            
            # 检查文件是否被修改
            current_mtime = prompt_file.stat().st_mtime
            if name in self._last_modified and self._last_modified[name].timestamp() >= current_mtime:
                return self._cache.get(name)
            
            # 读取文件
            with open(prompt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 更新缓存
            self._cache[name] = content
            self._last_modified[name] = datetime.now()
            
            return content
            
        except Exception as e:
            print(f"错误：加载提示词 '{name}' 失败: {e}")
            return None

# 全局提示词管理器实例
_prompt_manager = None
_skills_prompt_cache = None

#: 聊天区字体的兜底值（config.ui 缺失或非法时使用）
_CHAT_FONT_FALLBACK = ("Lucida Console", 16)


def get_chat_font() -> tuple:
    """返回聊天区字体 ``(family, size_pt)`` —— 唯一来源。

    此前 'Lucida Console', 16 被硬编码在三处（主窗口两处、设置控制器一处），
    改字号要改三个地方且无法由用户调整。凡需要聊天字体的地方都应调用本函数。
    """
    try:
        family = (config.ui.font_family or _CHAT_FONT_FALLBACK[0]).strip()
        size = int(config.ui.font_size)
        if not family or size <= 0:
            raise ValueError
        return family, size
    except Exception:
        return _CHAT_FONT_FALLBACK


def get_chat_font_qss() -> str:
    """返回可直接内嵌到 QSS 里的字体片段，如 ``16pt 'Lucida Console'``。"""
    family, size = get_chat_font()
    return f"{size}pt '{family}'"

def get_prompt_manager() -> PromptManager:
    """获取全局提示词管理器实例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager

def get_skills_prompt() -> str:
    """获取「可用技能」清单提示词（供注入系统提示词）。

    技能由 <repo>/skills/<name>/SKILL.md 声明，见 core/system/skill_manager.py。
    只加载元数据（Level 1），技能正文按需读取，因此这里很轻。
    """
    global _skills_prompt_cache
    if _skills_prompt_cache is None:
        try:
            from .skill_manager import get_skills_prompt as _gp
            _skills_prompt_cache = _gp() or ""
        except Exception as exc:
            print(f"警告：加载技能清单失败（不影响对话）: {exc}")
            _skills_prompt_cache = ""
    return _skills_prompt_cache

def get_prompt(name: str, **kwargs) -> str:
    """便捷函数：获取提示词。

    当 kwargs 里带 ``include_skills=True`` 时，会在结果末尾附加「可用技能」清单，
    让模型知道自己具备哪些专业技能（技能正文仍按需加载）。
    """
    include_skills = kwargs.pop("include_skills", False)
    text = get_prompt_manager().get_prompt(name, **kwargs)
    if include_skills:
        skills = get_skills_prompt()
        if skills:
            text = f"{text}\n\n{skills}"
    return text

def save_prompt(name: str, content: str):
    """便捷函数：保存提示词"""
    get_prompt_manager().save_prompt(name, content)


class NagaConfig(BaseModel):
    """NagaAgent主配置类"""
    system: SystemConfig = Field(default_factory=SystemConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    api_server: APIServerConfig = Field(default_factory=APIServerConfig)
    agentserver: ServicePortConfig = Field(
        default_factory=lambda: ServicePortConfig(port=18001), description="Agent服务器（config.json: agentserver）")
    mcpserver: ServicePortConfig = Field(
        default_factory=lambda: ServicePortConfig(port=18003), description="MCP工具服务器（config.json: mcpserver）")
    grag: GRAGConfig = Field(default_factory=GRAGConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)  # ASR输入服务配置 #
    # prompts: 提示词配置已迁移到 system/prompt_repository.py
    # weather: 天气服务使用免费API，无需配置
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    live2d: Live2DConfig = Field(default_factory=Live2DConfig)
    voice_realtime: VoiceRealtimeConfig = Field(default_factory=VoiceRealtimeConfig)  # 实时语音配置
    online_search: OnlineSearchConfig = Field(default_factory=OnlineSearchConfig)
    system_check: SystemCheckConfig = Field(default_factory=SystemCheckConfig)
    computer_control: ComputerControlConfig = Field(default_factory=ComputerControlConfig)
    handoff: HandoffConfig = Field(default_factory=HandoffConfig)
    window: QWidget = Field(default=None)

    model_config = {
        "extra": "ignore",  # 保留原配置：忽略未定义的字段
        "arbitrary_types_allowed": True,  # 允许非标准类型（如 QWidget）
        "json_schema_extra": {
            "exclude": ["window"]  # 序列化到 config.json 时排除 window 字段（避免报错）
        }
    }
    def __init__(self, **kwargs):
        setup_environment()
        super().__init__(**kwargs)
        self.system.log_dir.mkdir(parents=True, exist_ok=True)  # 确保递归创建日志目录


# 全局配置实例

def load_config():
    """加载配置"""
    config_path = str(Path(__file__).parent.parent.parent / "config.json")

    if os.path.exists(config_path):
        try:
            # 编码检测、注释剥离与解析回退都由 json_config 统一处理
            return NagaConfig(**load_config_json(config_path))
        except Exception as e:
            print(f"警告：加载 {config_path} 失败: {e}")
            print("使用默认配置")
            return NagaConfig()
    else:
        print(f"警告：配置文件 {config_path} 不存在，使用默认配置")

    return NagaConfig()

config = load_config()

def reload_config() -> NagaConfig:
    """重新加载配置"""
    global config
    config = load_config()
    notify_config_changed()
    return config

def hot_reload_config() -> NagaConfig:
    """热更新配置 - 重新加载配置并通知所有模块。

    **原地更新而非重新绑定**：全项目有大量模块写的是
    ``from core.system.config import config``，它们在导入时就把**对象引用**存下来了。
    如果这里 `config = load_config()` 重绑，那些模块手里仍是旧对象，永远看不到
    新值 —— 表现为「改了配置但某个模块不生效」，极难排查。

    因此这里把新配置的字段逐个 setattr 到**同一个对象**上，所有持有者自然同步。
    """
    global config
    old_version = getattr(getattr(config, "system", None), "version", "?")

    try:
        fresh = load_config()
    except Exception as exc:
        print(f"配置热更新失败，保留当前配置: {exc}")
        return config

    for field_name in type(fresh).model_fields:
        try:
            setattr(config, field_name, getattr(fresh, field_name))
        except Exception as exc:
            print(f"配置热更新跳过字段 {field_name}: {exc}")

    notify_config_changed()
    print(f"配置已热更新: {old_version} -> "
          f"{getattr(getattr(config, 'system', None), 'version', '?')}")
    return config

def get_config() -> NagaConfig:
    """获取当前配置"""
    return config

# 初始化时打印配置信息
if config.system.debug:
    print(f"NagaAgent {config.system.version} 配置已加载")
    print(f"API服务器: {'启用' if config.api_server.enabled else '禁用'} ({config.api_server.host}:{config.api_server.port})")
    print(f"GRAG记忆系统: {'启用' if config.grag.enabled else '禁用'}")

# 启动时设置用户显示名：优先config.json，其次系统用户名 #
try:
    # 检查 config.json 中的 user_name 是否为空白或未填写
    if not config.ui.user_name or not config.ui.user_name.strip():
        # 如果是，则尝试获取系统登录用户名并覆盖
        config.ui.user_name = os.getlogin()
except Exception:
    # 获取系统用户名失败时，将保留默认值 "用户" 或 config.json 中的空值
    pass

# 向后兼容的AI_NAME常量
AI_NAME = config.system.ai_name

import logging
logger = logging.getLogger(__name__)
