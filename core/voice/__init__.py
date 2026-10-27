"""voice 包初始化：请从 voice.input.* 与 voice.output.* 导入具体模块。

历史上这里做过全局导入，导致「只想用语音输出（TTS）」的进程也被迫加载
语音输入链路。现改为不在此处做任何全局导入，按需从具体子模块导入：

    from core.voice.input.integration import get_voice_integration
    from core.voice.output.voice_integration import get_voice_integration

注意（关于 onnxruntime）：曾声明的 onnxruntime 已移除 —— 没有任何代码导入它
（VAD 用的是能量检测，见 input/voice_realtime/core/audio_manager.py），
且它与 PyQt5 存在 DLL 冲突（先导入 PyQt5 再导入 onnxruntime 会失败）。
若将来接入 silero VAD 等 ONNX 模型，请在导入 PyQt5 之前完成 onnxruntime 导入。
"""

__all__ = []
