"""말풍선 창.

펫 창과는 별도의 작은 투명 창으로 만든다.
(펫 창을 크게 만들어 그 안에 풍선을 그리면 투명한 큰 영역이 클릭을 막기 때문)
마우스 입력은 통과시켜서(WindowTransparentForInput) 말풍선이 뜬 동안에도 뒤의 창을 쓸 수 있다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

import settings

PAD_X = 14
PAD_Y = 9
TAIL_H = 9  # 꼬리(삼각형) 높이
TAIL_HALF_W = 7
RADIUS = 11
MAX_TEXT_W = 260


class SpeechBubble(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._font = QFont(settings.SPEECH_FONT_FAMILY, settings.SPEECH_FONT_POINT_SIZE)
        self._text = ""
        self._text_rect = QRect()
        self._tail_x = 20.0
        self._tail_up = False  # True 이면 꼬리가 위(풍선이 펫 아래에 있을 때)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    # -- 공개 API -----------------------------------------------------------

    def show_text(self, text: str, anchor: QRect, facing: int, duration_ms: int | None = None) -> None:
        """anchor(펫 창의 화면 사각형) 근처에 text 를 잠깐 보여준다."""
        self._text = text
        fm = QFontMetrics(self._font)
        self._text_rect = fm.boundingRect(QRect(0, 0, MAX_TEXT_W, 1000), int(Qt.TextFlag.TextWordWrap), text)
        w = self._text_rect.width() + PAD_X * 2
        h = self._text_rect.height() + PAD_Y * 2 + TAIL_H
        self.setFixedSize(w, h)
        self.follow(anchor, facing)
        self.show()
        self.raise_()
        self.update()
        self._timer.start(duration_ms or settings.SPEECH_DURATION_MS)

    def follow(self, anchor: QRect, facing: int) -> None:
        """펫이 움직일 때 말풍선도 따라가게 위치를 갱신한다."""
        if not self.isVisible() and not self._timer.isActive():
            return
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

        # 머리 쪽(상어가 보는 방향 쪽) 위에 말풍선을 띄운다
        head_x = anchor.left() + anchor.width() * (0.8 if facing >= 0 else 0.2)
        x = int(head_x - self.width() / 2)
        x = max(area.left() + 2, min(x, area.right() - self.width() - 2))
        y = anchor.top() - self.height() - 2
        self._tail_up = False
        if y < area.top():  # 화면 위쪽이 모자라면 펫 아래에 띄운다
            y = anchor.bottom() + 2
            self._tail_up = True
        self._tail_x = max(RADIUS + TAIL_HALF_W, min(head_x - x, self.width() - RADIUS - TAIL_HALF_W))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
        self.update()

    # -- 그리기 ---------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 규칙)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        body_top = TAIL_H if self._tail_up else 0
        body = QRectF(1, body_top + 1, w - 2, h - TAIL_H - 2)

        path = QPainterPath()
        path.addRoundedRect(body, RADIUS, RADIUS)
        tail = QPainterPath()
        tx = self._tail_x
        if self._tail_up:
            tail.moveTo(QPointF(tx - TAIL_HALF_W, body.top()))
            tail.lineTo(QPointF(tx, 1))
            tail.lineTo(QPointF(tx + TAIL_HALF_W, body.top()))
        else:
            tail.moveTo(QPointF(tx - TAIL_HALF_W, body.bottom()))
            tail.lineTo(QPointF(tx, h - 1))
            tail.lineTo(QPointF(tx + TAIL_HALF_W, body.bottom()))
        tail.closeSubpath()
        path = path.united(tail)

        p.setPen(QPen(QColor(34, 44, 56), 1.5))
        p.setBrush(QColor(248, 251, 255, 245))
        p.drawPath(path)

        p.setPen(QColor(24, 32, 42))
        p.setFont(self._font)
        text_area = QRectF(body.left() + PAD_X - 1, body.top() + PAD_Y - 1,
                           self._text_rect.width() + 2, self._text_rect.height() + 2)
        p.drawText(text_area, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), self._text)
        p.end()
