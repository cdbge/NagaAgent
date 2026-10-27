#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进程内事件总线 —— 让服务层不必 import 表现层就能通知界面。

为什么需要它
------------
服务端（FastAPI 线程）需要把「工具执行完毕」这类事件送到界面上。
如果服务端直接 ``from ui.controller.tool_chat import chat``，就会：

* 让服务端进程**必须能 import 整个 UI 包**，无法无界面部署；
* 让 ``chat`` 这个懒加载单例**在服务端线程里被构造**，其 ``QTimer``
  与信号槽都会落在非 GUI 线程上。

改成「发布/订阅」后，服务端只认识**主题名**，不知道谁在听：:

    # 服务端（servers/apiserver/api_server.py）
    event_bus.publish("tool.ai_response", text=ai_response)

    # 界面（ui/pyqt_chat_window.py，启动时注册一次）
    event_bus.subscribe("tool.ai_response", on_tool_ai_response)

设计参考
--------
与 PyPubSub 的 ``pub.subscribe`` / ``pub.sendMessage`` 同构，但只保留
本项目需要的部分，不引入外部依赖。要点：

* **弱引用**：订阅者是绑定的方法时按弱引用保存，界面组件被销毁后
  自动失效，无需手工退订（否则会一直持有已销毁的 widget）。
* **主题层级**：主题名用 ``.`` 分隔，发布 ``a.b`` 会同时通知订阅了
  ``a`` 的监听者。
* **线程安全**：发布可能来自任意服务线程，订阅表加锁；**回调本身
  在发布线程中执行**，跨线程的界面更新由订阅方自行转交（Qt 信号天然
  支持跨线程排队投递）。
"""

import logging
import threading
import weakref
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

__all__ = ["EventBus", "event_bus"]


class _Listener:
    """一条订阅记录。对绑定方法使用弱引用，避免阻止组件回收。"""

    __slots__ = ("_fn", "_weak_self", "_weak_fn", "topic")

    def __init__(self, topic: str, fn: Callable[..., Any]):
        self.topic = topic
        self._fn = fn
        # 绑定方法：拆成 (弱引用实例, 函数)，实例被回收后自动失效
        obj = getattr(fn, "__self__", None)
        if obj is not None and not isinstance(obj, type):
            try:
                self._weak_self = weakref.ref(obj)
                self._weak_fn = fn.__func__
                self._fn = None
                return
            except TypeError:
                pass  # 不可弱引用的对象（如内建类型实例）回退到强引用
        self._weak_self = None
        self._weak_fn = None

    def get(self) -> Optional[Callable[..., Any]]:
        """取回可调用对象；对应实例已被回收时返回 ``None``。"""
        if self._weak_self is None:
            return self._fn
        obj = self._weak_self()
        if obj is None:
            return None
        return self._weak_fn.__get__(obj, type(obj))

    def is_alive(self) -> bool:
        return self.get() is not None


class EventBus:
    """极简发布/订阅总线。

    主题名形如 ``"tool.ai_response"``；发布 ``"tool.ai_response"`` 时，
    订阅了它、以及订阅了其父主题 ``"tool"`` 的监听者都会被调用。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listeners: Dict[str, List[_Listener]] = {}

    # ---------------------------------------------------------------- 订阅
    def subscribe(self, topic: str, handler: Callable[..., Any]) -> Callable[[], None]:
        """订阅主题，返回一个「取消订阅」的可调用对象。

        订阅者若是绑定方法，按弱引用保存：实例被回收后回调自动失效。
        """
        if not topic or not callable(handler):
            raise ValueError("subscribe() 需要非空主题名与可调用对象")
        with self._lock:
            self._listeners.setdefault(topic, []).append(_Listener(topic, handler))

        def _unsubscribe() -> None:
            self.unsubscribe(topic, handler)

        return _unsubscribe

    def unsubscribe(self, topic: str, handler: Callable[..., Any]) -> bool:
        """取消订阅；成功移除返回 ``True``。"""
        with self._lock:
            listeners = self._listeners.get(topic)
            if not listeners:
                return False
            for i, lis in enumerate(listeners):
                if lis.get() is handler or lis._fn is handler:
                    del listeners[i]
                    if not listeners:
                        del self._listeners[topic]
                    return True
        return False

    def clear(self, topic: Optional[str] = None) -> None:
        """清空订阅（``topic`` 为 None 时清空全部）。主要供测试使用。"""
        with self._lock:
            if topic is None:
                self._listeners.clear()
            else:
                self._listeners.pop(topic, None)

    # ---------------------------------------------------------------- 发布
    def publish(self, topic: str, **data: Any) -> int:
        """向主题发布消息，返回被调用的监听者数量。

        主题的父级也会收到消息（``a.b.c`` 会通知 ``a.b``、``a`` 的订阅者）。
        单个监听者抛异常不会影响其它监听者。
        """
        targets: List[_Listener] = []
        traversed: List[str] = []          # 本次经过的主题，清理只碰这些
        dead_seen = False
        with self._lock:
            # 从最具体的主题往上找，同一监听者只调用一次
            parts = topic.split(".")
            seen: set = set()
            for i in range(len(parts), 0, -1):
                t = ".".join(parts[:i])
                traversed.append(t)
                for lis in self._listeners.get(t, ()):
                    if not lis.is_alive():
                        dead_seen = True
                        continue
                    key = id(lis)
                    if key not in seen:
                        seen.add(key)
                        targets.append(lis)

            # 仅当**确实遇到**失效弱引用时才清理，且只清理本次经过的主题。
            # 原实现在每次 publish 都遍历全总线的所有主题，成本随总线规模
            # 增长（实测 10001 个监听者时单次 848 μs），而不是随本次发布
            # 相关的监听者数量增长。
            if dead_seen:
                for t in traversed:
                    listeners = self._listeners.get(t)
                    if not listeners:
                        continue
                    alive = [x for x in listeners if x.is_alive()]
                    if alive:
                        self._listeners[t] = alive
                    else:
                        del self._listeners[t]

        called = 0
        for lis in targets:
            fn = lis.get()
            if fn is None:
                continue
            try:
                fn(**data)
                called += 1
            except Exception as e:  # 单个监听者出错不影响其它监听者
                logger.error("事件监听者执行失败 topic=%s: %s", lis.topic, e)
        return called

    # ---------------------------------------------------------------- 内省
    def topics(self) -> List[Tuple[str, int]]:
        """返回 ``[(主题, 活跃监听者数)]``，便于排查「事件没人接」。"""
        with self._lock:
            return [(t, sum(1 for x in ls if x.is_alive()))
                    for t, ls in sorted(self._listeners.items())]


#: 全进程共用的总线实例
event_bus = EventBus()
