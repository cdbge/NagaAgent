import sys, os; sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + '/..'))
from PyQt5.QtWidgets import QWidget, QPushButton
from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import QColor, QPainter, QFont, QPen
from core.system.config import config


def get_ui_config():
    """获取UI配置，确保使用最新的配置"""
    return {
        'BG_ALPHA': config.ui.bg_alpha,
        'WINDOW_BG_ALPHA': config.ui.window_bg_alpha,
        'USER_NAME': config.ui.user_name,
        'MAC_BTN_SIZE': config.ui.mac_btn_size,
        'MAC_BTN_MARGIN': config.ui.mac_btn_margin,
        'MAC_BTN_GAP': config.ui.mac_btn_gap,
        'ANIMATION_DURATION': config.ui.animation_duration
    }


def refresh_ui_constants():
    global BG_ALPHA, WINDOW_BG_ALPHA, USER_NAME, MAC_BTN_SIZE, MAC_BTN_MARGIN, MAC_BTN_GAP, ANIMATION_DURATION
    ui_config = get_ui_config()
    BG_ALPHA = ui_config['BG_ALPHA']
    WINDOW_BG_ALPHA = ui_config['WINDOW_BG_ALPHA']
    USER_NAME = ui_config['USER_NAME']
    MAC_BTN_SIZE = ui_config['MAC_BTN_SIZE']
    MAC_BTN_MARGIN = ui_config['MAC_BTN_MARGIN']
    MAC_BTN_GAP = ui_config['MAC_BTN_GAP']
    ANIMATION_DURATION = ui_config['ANIMATION_DURATION']


refresh_ui_constants()


class TitleBar(QWidget):
    HEIGHT = 44
    BTN_SIZE = 24
    BTN_MARGIN = 34
    BTN_GAP = 12

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = text
        # 44px：只需要容纳窗口控制按钮 + 拖拽区；
        # 标题文字在 ArchiveHeader 里，这里不再需要 100px 高度。
        self.setFixedHeight(44)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._offset = None

        # (符号, 语义角色, 回调)。角色用于取主题色：
        #   'min'  -> 悬停用强调色
        #   'close'-> 悬停用危险色
        self._button_specs = [
            ("—", "min", lambda: self.parent().showMinimized()),
            ("✕", "close", lambda: self.parent().close()),
        ]
        self._buttons = []
        for idx, (txt, role, cb) in enumerate(self._button_specs):
            btn = QPushButton(txt, self)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(cb)
            self._buttons.append((btn, role))
            if idx == 0:
                self.btn_min = btn
            else:
                self.btn_close = btn
        self.update_style()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._offset = e.globalPos() - self.parent().frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._offset and e.buttons() & Qt.LeftButton:
            self.parent().move(e.globalPos() - self._offset)

    def mouseReleaseEvent(self, e):
        self._offset = None

    def paintEvent(self, e):
        """只画两条分隔线，不画标题文字。

        标题文字已由档案式顶栏（`ui/components/archive/header.py`）承担，
        这里再画一遍会重复。保留本控件是为了窗口拖拽与右上角控制按钮。
        """
        from ui.styles.tokens import get_theme

        t = get_theme()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        pen = QPen(QColor(t.divider))
        pen.setWidth(1)
        qp.setPen(pen)
        qp.drawLine(0, 2, w, 2)
        qp.drawLine(0, h - 3, w, h - 3)

        # 用取景框「包裹」窗口按钮组：给按钮集群画一个 L 形角标，
        # 这样右上角不再是孤零零一条线压着按钮，而是把按钮框进来。
        self._paint_button_bracket(qp, t)
        qp.end()

    def _paint_button_bracket(self, qp, t):
        """用取景框把窗口按钮「框」在右上角。

        不是给按钮画个浮动方框，而是从**窗口右上角**拉出 L 形，
        横边盖住按钮组宽度、竖边盖住按钮组高度 —— 按钮就此被角标包住，
        视觉上贴着窗口边缘，不再悬在半空。
        """
        try:
            if not self._buttons:
                return
            rects = [b.geometry() for b, _role in self._buttons]
            # 四边等距外扩 6px：这样的框才是「居中包住按钮组」，
            # 之前 top 写死 7、其余靠按钮位置算，导致上下左右留白各不相同。
            pad = 6
            left = min(r.left() for r in rects) - pad
            right = max(r.right() for r in rects) + pad
            top = max(0, min(r.top() for r in rects) - pad)
            bottom = max(r.bottom() for r in rects) + pad
            arm = 12
            pen = QPen(QColor(t.border_strong))
            pen.setWidthF(1.2)
            qp.setPen(pen)
            # 上横边：从按钮组左端一路拉到窗口右缘
            qp.drawLine(left, top, right, top)
            # 右竖边：从窗口上缘一路拉到按钮组下端
            qp.drawLine(right, top, right, bottom)
            # 左下小折角，把按钮组的下边界收住
            qp.drawLine(left, bottom - arm, left, bottom)
            qp.drawLine(left, bottom, left + arm, bottom)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_buttons()

    def update_style(self):
        """按当前主题重绘窗口控制按钮（方形 + 线框 + 语义色）。"""
        refresh_ui_constants()
        try:
            from ui.styles.tokens import font_stack, get_theme

            t = get_theme()
            # 固定中号：不再让用户调「按钮尺寸/边距/间距」这种细枝末节
            size = self.BTN_SIZE
            radius = t.radius_sm
            for btn, role in self._buttons:
                accent = t.danger if role == "close" else t.accent
                btn.setFixedSize(size, size)
                btn.setStyleSheet(
                    f"""
                    QPushButton {{
                        background: transparent;
                        color: {t.text_dim};
                        border: {t.border_width}px solid {t.border};
                        border-radius: {radius}px;
                        font-family: {font_stack(t, 'mono')};
                        font-size: 10.5pt;
                        padding: 0px;
                    }}
                    QPushButton:hover {{
                        color: {t.text_inv};
                        background: {accent};
                        border: {t.border_width}px solid {accent};
                    }}
                    QPushButton:pressed {{
                        background: {t.accent_deep if role != 'close' else t.danger};
                    }}
                    """
                )
        except Exception as exc:
            from core.system.config import logger

            logger.debug(f"[标题栏] 按钮主题化失败: {exc}")
        self._layout_buttons()
        self.update()

    def _layout_buttons(self):
        if not self._buttons:
            return
        gap = self.BTN_GAP
        # 右边距至少 34px：取景框右上角标占掉最外 24px，
        # 按钮再往里收 10px 才不会和角标叠在一起。
        # 按钮靠边：贴着窗口右上角，由包裹角标框住
        # 右边距 = 13：窗口取景框内缩线在 width-7，按钮外留 6px，
        # 正好与角标框（按钮外扩 6px）对称 —— 之前用 20 导致
        # 左侧留白 6、右侧 13，看起来就是错位。
        margin = 13
        _bh = self._buttons[0][0].height()
        # 纯垂直居中（不再额外扣 8px，否则上边距 1、下边距 6 不对称）
        y_center = max(0, (self.height() - _bh) // 2)
        x = self.width() - margin - self._buttons[0][0].width()
        for btn, _role in reversed(self._buttons):
            btn.move(x, y_center)
            x -= btn.width() + gap
