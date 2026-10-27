"""NagaAgent 服务层。

包含三个网络服务，均由 ``main.py`` 以独立线程启动：

- ``apiserver``  : API 服务器（:8000），对话与 LLM 接口
- ``agentserver``: Agent 服务器（:8001），电脑控制与任务调度
- ``mcpserver``  : MCP 服务器（:8003），工具注册与调度
"""
