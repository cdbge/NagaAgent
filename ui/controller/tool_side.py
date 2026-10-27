from PyQt5.QtCore import Qt, QParallelAnimationGroup, QPropertyAnimation, QEasingCurve
import os
from core.system.config import config
from . import chat
class SideTool():
    def __init__(self, window):
        self.window = window
        self.side=self.window.side
        self.expanded_width=self.window.expanded_width
        self.collapsed_width=self.window.collapsed_width
        self.side.mousePressEvent=self.toggle_full_img # 侧栏点击切换聊天/设置
        self.full_img=0 # 立绘展开标志，0=收缩状态，1=展开状态
        self.animating = False  # 动画标志位，动画期间为True
        self._img_inited = False  # 标志变量，图片自适应只在初始化时触发一次
        self._animating = False  # 设置动画标志位

    
    def toggle_full_img(self,e):
        window=self.window
        if getattr(self, '_animating', False):  # 动画期间禁止重复点击
            return
        self._animating = True  # 设置动画标志位
        self.full_img^=1  # 立绘展开标志切换
        target_width = self.expanded_width if self.full_img else self.collapsed_width  # 目标宽度：展开或收缩
        
        # --- 立即切换界面状态 ---
        if self.full_img:  # 展开状态 - 进入设置页面
            # 走统一入口：同时处理页面栈、导航高亮、侧栏主题样式。
            # 原实现直接 setCurrentIndex(1) 并写死 rgba(17,17,17) + 15px 圆角，
            # 在纸色主题下会变成一块深色圆角方块。
            window.enter_settings(source="live2d")
            self.side.setCursor(Qt.PointingHandCursor)
        else:  # 收缩状态 - 主界面聊天模式
            window.leave_settings()
            window.input.setFocus()  # 恢复输入焦点
            self.side.setCursor(Qt.PointingHandCursor)
        # --- 立即切换界面状态 END ---
        
        # 创建优化后的动画组
        group = QParallelAnimationGroup(window)
        
        # 侧栏宽度动画 - 合并为单个动画
        side_anim = QPropertyAnimation(self.side, b"minimumWidth", window)
        side_anim.setDuration(config.ui.animation_duration)
        side_anim.setStartValue(self.side.width())
        side_anim.setEndValue(target_width)
        side_anim.setEasingCurve(QEasingCurve.OutCubic)  # 使用更流畅的缓动
        group.addAnimation(side_anim)
        
        side_anim2 = QPropertyAnimation(self.side, b"maximumWidth", window)
        side_anim2.setDuration(config.ui.animation_duration)
        side_anim2.setStartValue(self.side.width())
        side_anim2.setEndValue(target_width)
        side_anim2.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(side_anim2)
        
        # 输入框动画 - 进入设置时隐藏，退出时显示
        if self.full_img:
            input_hide_anim = QPropertyAnimation(window.input_wrap, b"maximumHeight", window)
            input_hide_anim.setDuration(config.ui.animation_duration // 2)
            input_hide_anim.setStartValue(window.input_wrap.height())
            input_hide_anim.setEndValue(0)
            input_hide_anim.setEasingCurve(QEasingCurve.OutQuad)
            group.addAnimation(input_hide_anim)
        else:
            input_show_anim = QPropertyAnimation(window.input_wrap, b"maximumHeight", window)
            input_show_anim.setDuration(config.ui.animation_duration // 2)
            input_show_anim.setStartValue(0)
            input_show_anim.setEndValue(60)
            input_show_anim.setEasingCurve(QEasingCurve.OutQuad)
            group.addAnimation(input_show_anim)
        
        def on_side_width_changed():
            """侧栏宽度变化时实时更新"""
            # Live2D侧栏会自动处理大小调整
            pass
        
        def on_animation_finished():
            self._animating = False  # 动画结束标志
            # Live2D侧栏会自动处理最终调整
            pass
        
        # 连接信号
        side_anim.valueChanged.connect(on_side_width_changed)
        group.finished.connect(on_animation_finished)
        group.start()

    def set_fallback_image(self, image_path):
        """设置回退图片"""
        if not os.path.exists(image_path):
            chat.add_user_message("系统", f"❌ 图片文件不存在: {image_path}")
            return False
        
        self.side.set_fallback_image(image_path)
        chat.add_user_message("系统", f"✅ 回退图片已设置: {os.path.basename(image_path)}")
        return True
    
    
    
from ..utils.lazy import lazy
@lazy
def side():
    return SideTool(config.window)