"""
进度显示组件
支持思考状态、加载动画和实时进度更新
"""

import logging
import os
from PyQt5.QtWidgets import QWidget, QLabel, QProgressBar, QVBoxLayout, QHBoxLayout  # 统一入口 #
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal  # 统一入口 #
from PyQt5.QtGui import QMovie  # 统一入口 #

logger = logging.getLogger(__name__)

class ProgressWidget(QWidget):
    #: 是否显示等待浮层。
    #: 生成过程中这块浮层会挡住消息区、干扰观察入场动效，默认关闭；
    #: 状态文字仍会更新，只是不弹窗。
    ENABLED = False

    """进度显示组件"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # QWidget 子类默认不画 QSS 背景，必须显式打开（且在 super() 之后）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(80)
        self.setup_ui()
        self.setup_animations()
        
    def setup_ui(self):
        """初始化UI"""
        self.setStyleSheet("""
            QWidget {
                background: rgba(25, 25, 25, 200);
                border-radius: 15px;
                border: 1px solid rgba(100, 200, 255, 100);
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 10, 20, 10)
        layout.setSpacing(8)
        
        # 状态标签和动画图标
        top_layout = QHBoxLayout()
        
        # 加载动画图标
        self.loading_label = QLabel()
        self.loading_label.setFixedSize(24, 24)
        self.loading_label.setAlignment(Qt.AlignCenter)
        
        # 检查是否有loading.gif
        gif_path = os.path.join(os.path.dirname(__file__), 'loading.gif')
        if os.path.exists(gif_path):
            self.movie = QMovie(gif_path)
            self.movie.setScaledSize(self.loading_label.size())
            self.loading_label.setMovie(self.movie)
        else:
            # 如果没有gif，显示文字动画
            self.loading_label.setText("●")
            self.loading_label.setObjectName("LoadingDot")
        
        top_layout.addWidget(self.loading_label)
        
        # 状态文本
        self.status_label = QLabel("正在思考...")
        self.status_label.setStyleSheet("""
            QLabel {
                color: #64C8FF;
                font: 14pt 'Lucida Console';
                background: transparent;
                border: none;
            }
        """)
        top_layout.addWidget(self.status_label)
        top_layout.addStretch()
        
        layout.addLayout(top_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.apply_theme_style()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
        # 默认隐藏
        self.hide()
        
    def apply_theme_style(self):
        """按当前主题刷新进度组件。

        原来写死 `#64C8FF` 亮蓝，在少女前线/莱茵两套主题下都很跳。
        """
        try:
            from ui.styles.tokens import get_theme

            t = get_theme()
            bar_bg = t.panel_3 if t.is_light else t.panel_2
            try:
                self.status_label.setStyleSheet(
                    f"color: {t.accent}; background: transparent;"
                    f"font-family: {t.font_mono}; font-size: 10pt;"
                )
            except Exception:
                pass
            try:
                self.loading_label.setStyleSheet(
                    f"color: {t.accent}; font-size: 16pt;"
                )
            except Exception:
                pass
            try:
                self.progress_bar.setStyleSheet(
                    f"""
                    QProgressBar {{
                        border: {t.border_width}px solid {t.border};
                        border-radius: {t.radius_sm}px;
                        background: {bar_bg};
                        text-align: center;
                        color: {t.text_dim};
                        font-family: {t.font_mono};
                        font-size: 8pt;
                    }}
                    QProgressBar::chunk {{
                        background: {t.accent};
                        border-radius: {t.radius_sm}px;
                    }}
                    """
                )
            except Exception:
                pass
        except Exception as exc:
            logger.debug(f"[进度] 主题样式失败: {exc}")

    def setup_animations(self):
        """设置动画效果"""
        # 淡入淡出动画
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(300)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        # 脉冲动画定时器（用于无gif时的文字动画）
        self.pulse_timer = QTimer()
        self.pulse_timer.timeout.connect(self.pulse_loading_text)
        self.pulse_states = ["●", "●●", "●●●", "●●", "●"]
        self.pulse_index = 0
        
    def start_loading(self, status="正在思考..."):
        """开始加载动画（ENABLED=False 时只更新文字，不显示浮层）。"""
        self.status_label.setText(status)
        if not getattr(self, "ENABLED", True):
            self.hide()
            return
        self.progress_bar.setValue(0)
        
        # 确保组件状态正确
        self.show()
        
        # 断开之前可能的连接
        try:
            self.fade_anim.finished.disconnect()
        except:
            pass
        
        # 设置淡入动画
        self.setWindowOpacity(0)
        self.fade_anim.setStartValue(0)
        self.fade_anim.setEndValue(1)
        self.fade_anim.start()
        
        # 启动动画
        if hasattr(self, 'movie'):
            self.movie.start()
        else:
            self.pulse_timer.start(500)  # 500ms间隔
            
    def update_progress(self, value, status=None):
        """更新进度"""
        # 确保组件可见
        if not self.isVisible():
            self.show()
            self.setWindowOpacity(1.0)
            
        self.progress_bar.setValue(min(100, max(0, value)))
        if status:
            self.status_label.setText(status)
            
    def stop_loading(self):
        """停止加载动画"""
        # 停止动画
        if hasattr(self, 'movie'):
            self.movie.stop()
        self.pulse_timer.stop()
        
        # 断开之前的连接，避免重复连接
        try:
            self.fade_anim.finished.disconnect()
        except:
            pass
        
        # 淡出隐藏
        self.fade_anim.setStartValue(1)
        self.fade_anim.setEndValue(0)
        self.fade_anim.finished.connect(self.hide)
        self.fade_anim.start()
        
    def pulse_loading_text(self):
        """脉冲文字动画（当没有gif时使用）"""
        if not hasattr(self, 'movie'):
            self.loading_label.setText(self.pulse_states[self.pulse_index])
            self.pulse_index = (self.pulse_index + 1) % len(self.pulse_states)


class EnhancedProgressWidget(ProgressWidget):
    """增强版进度组件，支持更多状态"""
    
    # 自定义信号
    cancel_requested = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.add_cancel_button()
        
    def add_cancel_button(self):
        """添加取消按钮"""
        from PyQt5.QtWidgets import QPushButton  # 统一入口 #
        
        # 在顶部布局添加取消按钮
        top_layout = self.layout().itemAt(0).layout()
        
        self.cancel_btn = QPushButton("✕")
        self.cancel_btn.setFixedSize(20, 20)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 100, 100, 150);
                border: none;
                border-radius: 10px;
                color: white;
                font: 12pt bold;
            }
            QPushButton:hover {
                background: rgba(255, 100, 100, 200);
            }
            QPushButton:pressed {
                background: rgba(255, 50, 50, 200);
            }
        """)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.cancel_btn.hide()  # 默认隐藏
        
        top_layout.addWidget(self.cancel_btn)
        
    def set_thinking_mode(self):
        """设置思考模式（浮层已停用）。"""
        if not getattr(self, "ENABLED", True):
            self.status_label.setText("正在深度思考...")
            self.hide()
            return
        self.start_loading("正在深度思考...", show_cancel=True)
        # 思考模式使用不确定进度条
        self.progress_bar.setRange(0, 0)
        # 确保显示状态
        self.show()
        self.setWindowOpacity(1.0)
        
    def set_generating_mode(self):
        """设置生成模式（浮层已停用）。"""
        if not getattr(self, "ENABLED", True):
            self.status_label.setText("正在生成回复...")
            self.hide()
            return
        self.update_progress(0, "正在生成回复...")
        self.progress_bar.setRange(0, 100)
        
    def set_processing_mode(self, task_name="处理中"):
        """设置处理模式"""
        self.update_progress(0, f"{task_name}...")
        self.progress_bar.setRange(0, 100)
        
    def start_loading(self, status="正在思考...", show_cancel=False):
        """开始加载，可选择是否显示取消按钮"""
        super().start_loading(status)
        if show_cancel:
            self.cancel_btn.show()
        else:
            self.cancel_btn.hide() 