"""에셋이 없을 때 쓰는 임시(placeholder) 흑상어.

QPainter로 간단히 그린다. 실제 PNG가 준비되면 이 파일은 쓰이지 않는다.
모든 프레임은 같은 캔버스 크기에 같은 위치(코 위치 고정)로 그려서 크기/위치가 튀지 않는다.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF, QTransform

CANVAS_W, CANVAS_H = 1200, 520

BODY_COLOR = QColor("#3b4249")
BELLY_COLOR = QColor("#b3bbc2")
FIN_COLOR = QColor("#2e343a")
OUTLINE = QColor("#1b1f23")


def _tail_polygon(angle: float) -> QPolygonF:
    """꼬리 지느러미. 꼬리 시작점(300,267)을 축으로 angle도 만큼 회전."""
    pts = QPolygonF(
        [
            QPointF(310, 250),
            QPointF(150, 95),  # 위쪽 날개 끝
            QPointF(205, 250),
            QPointF(120, 420),  # 아래쪽 날개 끝
            QPointF(310, 285),
        ]
    )
    tr = QTransform()
    tr.translate(300, 267)
    tr.rotate(angle)
    tr.translate(-300, -267)
    return tr.map(pts)


def draw_shark(tail_angle: float = 0.0, eye: str = "open") -> QImage:
    """상어 한 프레임을 그려서 반환한다. eye: 'open' | 'half' | 'closed'."""
    img = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(OUTLINE, 5)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)

    # 꼬리 (몸통 뒤에 그린다)
    p.setBrush(QBrush(FIN_COLOR))
    p.drawPolygon(_tail_polygon(tail_angle))

    # 등/배 지느러미
    p.drawPolygon(QPolygonF([QPointF(690, 190), QPointF(770, 55), QPointF(845, 180)]))
    p.drawPolygon(QPolygonF([QPointF(800, 330), QPointF(740, 450), QPointF(910, 335)]))

    # 몸통
    body = QPainterPath()
    body.moveTo(1150, 270)
    body.cubicTo(1060, 175, 800, 150, 560, 200)
    body.lineTo(300, 250)
    body.lineTo(300, 285)
    body.cubicTo(560, 320, 900, 365, 1150, 290)
    body.closeSubpath()
    p.setBrush(QBrush(BODY_COLOR))
    p.drawPath(body)

    # 밝은 배
    belly = QPainterPath()
    belly.moveTo(1150, 285)
    belly.cubicTo(900, 340, 700, 300, 520, 285)
    belly.cubicTo(700, 345, 950, 372, 1150, 292)
    belly.closeSubpath()
    p.save()
    p.setClipPath(body)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(BELLY_COLOR))
    p.drawPath(belly)
    p.restore()

    # 아가미 선
    p.setPen(QPen(OUTLINE, 4))
    for i in range(4):
        x = 880 + i * 22
        p.drawLine(x, 225, x - 8, 285)

    # 눈
    ex, ey = 1040, 240
    if eye == "open":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b0d0f"))
        p.drawEllipse(QPointF(ex, ey), 11, 11)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(ex + 3, ey - 4), 3.5, 3.5)
    elif eye == "half":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0b0d0f"))
        p.drawChord(int(ex - 11), int(ey - 11), 22, 22, 180 * 16, 180 * 16)
        p.setPen(QPen(OUTLINE, 4))
        p.drawLine(int(ex - 12), int(ey), int(ex + 12), int(ey))
    else:
        p.setPen(QPen(OUTLINE, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(int(ex - 12), int(ey), int(ex + 12), int(ey))

    p.end()
    return img


def _turn_frame(k: int, n: int) -> QImage:
    """방향 전환 프레임: 상어를 가운데 축으로 좌우 폭을 줄였다가(cos) 뒤집어서 도는 모습을 흉내 낸다."""
    base = draw_shark(0.0)
    theta = math.pi * k / (n - 1)  # 0 → 180도
    sx = math.cos(theta)
    if abs(sx) < 0.08:  # 완전히 얇아져 사라지지 않게 최소 폭 유지
        sx = 0.08 if sx >= 0 else -0.08
    out = QImage(CANVAS_W, CANVAS_H, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    tr = QTransform()
    tr.translate(CANVAS_W / 2, CANVAS_H / 2)
    tr.scale(sx, 1.0)
    tr.translate(-CANVAS_W / 2, -CANVAS_H / 2)
    p.setTransform(tr)
    p.drawImage(0, 0, base)
    p.end()
    return out


def make_placeholder_frames(turn_frames: int = 8) -> dict[str, list[QImage]]:
    """swim 4장, turn 8장을 만들어 돌려준다."""
    return {
        # 꼬리 각도: -12, 0, +12, 0 → 0,1,2,3 순으로 재생하면 좌우로 부드럽게 흔들림
        "swim": [draw_shark(a) for a in (-12.0, 0.0, 12.0, 0.0)],
        "turn": [_turn_frame(k, turn_frames) for k in range(turn_frames)],
    }
