"""NagaAgent 核心能力层。

被服务层与 UI 层共用的基础设施与业务能力：

- ``system``        : 配置、日志、意图分析、启动自检
- ``summer_memory`` : GRAG 五元组知识图谱记忆
- ``voice``         : 语音输入与 TTS 输出
- ``mqtt_tool``     : 物联网设备控制
"""
