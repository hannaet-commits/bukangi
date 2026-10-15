"""부캉이 창: 투명 창 + 드래그 + 우클릭 메뉴 + 타이머 루프.

창 설정 메모 (Windows 투명 창)
- FramelessWindowHint        : 테두리/제목줄 제거
- WA_TranslucentBackground   : 배경 투명 (paintEvent 에서 Source 모드로 그려 검은 사각형 방지)
- WindowStaysOnTopHint       : 항상 위
- Tool                       : 작업표시줄에 표시하지 않음
- WindowDoesNotAcceptFocus   : 다른 프로그램의 포커스를 빼앗지 않음
- setMask(알파 모양)         : 투명한 부분은 창이 아닌 것처럼 마우스 클릭이 뒤의 창으로 전달됨
"""
from __future__ import annotations

import logging
import random
import time
from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

import settings
from animation import AnimationPlayer, FrameSpec, RenderSet, SpriteLibrary
from behavior import Bounds, PetBehavior
from speech_bubble import SpeechBubble

log = logging.getLogger("bukangi.window")


class PetWindow(QWidget):
    def __init__(
        self,
        library: SpriteLibrary,
        prefs: settings.UserPrefs,
        test_mode: bool = False,
        rng: Optional[random.Random] = None,
    ) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        if prefs.always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.prefs = prefs
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle(settings.APP_TITLE)

        self.lib = library
        self.test_mode = test_mode
        self.rng = rng or random.Random()
        self.behavior = PetBehavior(
            self.rng, use_turn=library.turn_mode != "none", turn_duration=library.turn_duration)
        self.player = AnimationPlayer(library, self.rng)
        self.bubble = SpeechBubble()
        self._last_line = ""

        self._renders: RenderSet = library.build(settings.SIZE_PRESETS[prefs.size], self.devicePixelRatioF())
        self._dpr = self._renders.dpr
        self._spec: Optional[FrameSpec] = None  # 지금 그려진 그림 (같으면 다시 그리지 않는다)
        self._mask_key: Optional[tuple[int, bool]] = None
        self._last_move: tuple[int, int] = (-99999, -99999)
        self._drag_offset: Optional[QPoint] = None
        self._tick_errors = 0
        self._turn_loop = False  # 테스트: 턴이 끝날 때마다 다시 턴

        self.setFixedSize(self._renders.size)
        self.apply_speed(prefs.speed)
        self._place_randomly()

        self._last_time = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # 시작/종료
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._set_spec(self.player.current, force=True)
        self.show()
        self._last_time = time.perf_counter()
        self._timer.start(settings.TICK_MS)

    def _place_randomly(self) -> None:
        left, top, right, bottom = self._bounds()
        x = self.rng.uniform(left, right)
        y = self.rng.uniform(top + (bottom - top) * 0.2, top + (bottom - top) * 0.8)
        self.behavior.set_position(x, y)
        self.behavior.set_direction(self.rng.choice((-1, 1)))
        self._apply_position(force=True)

    # ------------------------------------------------------------------
    # 화면 경계
    # ------------------------------------------------------------------

    def _screen_area(self) -> QRect:
        center = QPoint(round(self.behavior.x + self.width() / 2), round(self.behavior.y + self.height() / 2))
        screen = QGuiApplication.screenAt(center) or self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1280, 720)

    def _bounds(self) -> Bounds:
        """창 왼쪽 위 좌표가 움직일 수 있는 범위(작업표시줄 제외, 창이 완전히 화면 안)."""
        g = self._screen_area()
        return (g.left(), g.top(), g.left() + g.width() - self.width(), g.top() + g.height() - self.height())

    # ------------------------------------------------------------------
    # 메인 루프
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        try:
            now = time.perf_counter()
            dt = min(now - self._last_time, settings.MAX_DT * 2)
            self._last_time = now

            # 모니터 이동/배율 변경(HiDPI)을 감지하면 이미지를 다시 만든다
            dpr = self.devicePixelRatioF()
            if abs(dpr - self._dpr) > 0.01 and not self.behavior.dragging:
                self._rebuild(self.prefs.size)

            b = self.behavior
            bounds = self._bounds()
            b.update(dt, bounds)  # 1) 상태/이동 (방향 전환이 끝나면 여기서 상태가 바뀐다)
            if self._turn_loop and not b.is_turning and not b.dragging:
                b.start_turn()
            spec = self.player.update(dt, b)  # 2) 바뀐 상태를 읽어서 이번에 그릴 그림 결정
            self._set_spec(spec)  # 3) 그림/마스크 갱신 (상태와 그림이 같은 틱에 함께 바뀐다)
            if not b.dragging:
                self._apply_position(bounds=bounds)
            self.bubble.follow(self._body_rect(), b.facing)
        except Exception:  # noqa: BLE001 - 루프가 죽지 않게 한다
            self._tick_errors += 1
            if self._tick_errors <= 5:
                log.exception("tick 오류")

    def _set_spec(self, spec: FrameSpec, force: bool = False) -> None:
        """그릴 그림이 바뀌었을 때만 마스크를 맞추고 다시 그린다."""
        if spec == self._spec and not force:
            return
        self._spec = spec
        self._apply_mask(spec, force)
        self.update()

    def _apply_mask(self, spec: FrameSpec, force: bool = False) -> None:
        """투명한 부분은 클릭이 뒤의 창으로 통과하도록 창 모양을 설정한다.

        프레임마다 바꾸지 않고, 방향별 "모든 프레임의 합집합" 모양을 상태가 바뀔 때만 바꾼다.
        - 평소: swim 계열 합집합
        - turn 중 / 상태 전환 섞는 중: swim + turn 합집합 (turn 의 몸통이 잘리지 않도록)
        - 방향이 다른 두 그림을 섞는 중(turn 이 끝나는 순간): 양쪽 방향 합집합
        """
        mirror = spec.a[2]
        if (spec.b is not None and spec.b[2] != mirror) or spec.squash < 1.0:
            mirror = 0  # 방향이 바뀌는 중이면 양쪽 합집합
        key = (mirror, spec.wide_mask)
        if force or key != self._mask_key:
            self._mask_key = key
            self.setMask(self._renders.mask_for(*key))

    def _body_rect(self) -> QRect:
        """화면 좌표에서 "헤엄 상어" 가 차지하는 영역 (말풍선 위치 기준. turn 용 여백은 제외)."""
        return self._renders.body_rect.translated(self.pos())

    def _apply_position(self, force: bool = False, bounds: Optional[Bounds] = None) -> None:
        b = self.behavior
        amp = b.bob_amplitude_ratio * self.width()
        left, top, right, bottom = bounds or self._bounds()
        x = round(b.x)
        # 둥실거림을 더해도 화면 경계 밖으로 나가지 않게 제한
        y = round(min(max(b.y + b.bob * amp, top), bottom))
        if force or (x, y) != self._last_move:
            self._last_move = (x, y)
            self.move(x, y)

    def _blend_buffer(self) -> QImage:
        """프레임 섞기에 쓰는 임시 이미지 (크기/배율이 바뀔 때만 새로 만든다)."""
        dpr = self._renders.dpr
        size = self._renders.size
        buf = getattr(self, "_blend_buf", None)
        if buf is None or buf.devicePixelRatio() != dpr or buf.width() != round(size.width() * dpr):
            buf = QImage(round(size.width() * dpr), round(size.height() * dpr),
                         QImage.Format.Format_ARGB32_Premultiplied)
            buf.setDevicePixelRatio(dpr)
            self._blend_buf = buf
        return buf

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt 규칙)
        spec = self._spec
        if spec is None:
            return
        fa = self._renders.get(spec.a)
        if fa is None:  # 방어: 없는 프레임이면 아무것도 그리지 않는다
            return
        fb = self._renders.get(spec.b) if spec.b is not None else None
        p = QPainter(self)
        if spec.squash < 1.0:
            # 방향 전환(flip): 창 가운데를 기준으로 가로로 눌러서 그린다. 변형하면 지워지지 않은 옛 픽셀이 남으므로 먼저 전부 지운다.
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            cx = self.width() / 2.0
            p.translate(cx, 0.0)
            p.scale(spec.squash, 1.0)
            p.translate(-cx, 0.0)
        if fb is not None and 0.0 < spec.t < 1.0:
            # 두 프레임 섞기: 투명하게 지운 뒤 (A*(1-t) + B*t) 를 Plus 모드로 더한다.
            # 미리 곱해진 알파(premultiplied)끼리의 선형 보간이라 가장자리 알파도 정확하다.
            # (Qt 의 Plus 모드는 opacity 와 함께 쓰면 선형이 아니라서, B 는 임시 버퍼에 미리 투명도를 곱해 둔다)
            tmp = self._blend_buffer()
            tmp.fill(0)
            tp = QPainter(tmp)
            tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            tp.setOpacity(spec.t)
            tp.drawPixmap(0, 0, fb.pixmap)
            tp.end()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), Qt.GlobalColor.transparent)
            p.setOpacity(1.0 - spec.t)
            p.drawPixmap(0, 0, fa.pixmap)  # Source + 투명 바탕 = A*(1-t)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            p.drawImage(0, 0, tmp)  # + B*t
        else:
            # Source 모드: 배경을 합성하지 않고 이미지 픽셀(알파 포함)을 그대로 쓴다 → 검은 사각형 방지
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawPixmap(0, 0, fa.pixmap)
        if spec.blink > 0:
            self._paint_eyelid(p, spec)
        p.end()

    def _paint_eyelid(self, p: QPainter, spec: FrameSpec) -> None:
        """눈 깜빡임: 눈 위에 피부색 눈꺼풀을 덮어 그린다. (0.5=윗눈꺼풀 반쯤, 1=완전히 감음)"""
        rs = self._renders
        c = rs.eye.get(spec.a[2], rs.eye[1])
        r = rs.eye_radius * 1.35
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rs.skin)
        if spec.blink >= 1.0:
            p.drawEllipse(c, r, r * 0.95)
        else:
            p.drawChord(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), 0, 180 * 16)  # 윗 반원
        pen = QPen(rs.lid, max(1.0, r * 0.22))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(c.x() - r * 0.9, c.y()), QPointF(c.x() + r * 0.9, c.y()))

    # ------------------------------------------------------------------
    # 크기/속도/항상 위
    # ------------------------------------------------------------------

    def apply_speed(self, key: str) -> None:
        preset = settings.SPEED_PRESETS.get(key, settings.SPEED_PRESETS[settings.DEFAULT_SPEED])
        self.prefs.speed = key if key in settings.SPEED_PRESETS else settings.DEFAULT_SPEED
        self.behavior.speed = preset.pixels_per_sec  # 화면 이동 속도
        self.player.set_tail_period(preset.tail_period)  # 꼬리 왕복 주기(이동 속도와 별개)

    def _rebuild(self, size_key: str) -> None:
        """크기 또는 dpr 이 바뀌었을 때 프레임 캐시를 다시 만든다 (창 중심 유지)."""
        if size_key not in settings.SIZE_PRESETS:
            size_key = settings.DEFAULT_SIZE
        self.prefs.size = size_key
        old_cx = self.behavior.x + self.width() / 2
        old_cy = self.behavior.y + self.height() / 2
        self._renders = self.lib.build(settings.SIZE_PRESETS[size_key], self.devicePixelRatioF())
        self._dpr = self._renders.dpr
        self.setFixedSize(self._renders.size)
        left, top, right, bottom = self._bounds()
        x = min(max(old_cx - self.width() / 2, left), right)
        y = min(max(old_cy - self.height() / 2, top), bottom)
        self.behavior.set_position(x, y)
        self._mask_key = None
        self._set_spec(self.player.current, force=True)
        self._apply_position(force=True)

    def set_size(self, key: str) -> None:
        if key != self.prefs.size:
            self._rebuild(key)
        self.prefs.save()

    def set_speed(self, key: str) -> None:
        self.apply_speed(key)
        self.prefs.save()

    def set_always_on_top(self, on: bool) -> None:
        self.prefs.always_on_top = on
        pos = self.pos()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)  # 플래그를 바꾸면 창이 숨겨진다
        self.show()
        self.move(pos)
        if self._spec is not None:
            self._apply_mask(self._spec, force=True)
        self.prefs.save()

    def toggle_pause(self) -> None:
        self.behavior.paused = not self.behavior.paused

    # ------------------------------------------------------------------
    # 말풍선
    # ------------------------------------------------------------------

    def say(self, text: Optional[str] = None) -> None:
        if text is None:
            choices = [s for s in settings.SPEECH_LINES if s != self._last_line] or list(settings.SPEECH_LINES)
            text = self.rng.choice(choices)
        self._last_line = text
        self.bubble.show_text(text, self._body_rect(), self.behavior.facing)

    # ------------------------------------------------------------------
    # 마우스: 드래그 / 더블클릭 / 우클릭
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.behavior.dragging = True
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self.behavior.dragging and self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self._drag_offset
            self.behavior.set_position(target.x(), target.y())
            self._last_move = (target.x(), target.y())
            self.move(target)
            self.bubble.follow(self._body_rect(), self.behavior.facing)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.behavior.dragging:
            self.behavior.dragging = False
            self._drag_offset = None
            self._keep_on_screen()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.say()
            event.accept()

    def _keep_on_screen(self) -> None:
        """놓은 위치가 화면 밖이면 화면 안으로 되돌린다 (완전히 사라지는 것 방지)."""
        left, top, right, bottom = self._bounds()
        b = self.behavior
        x = min(max(b.x, left), right)
        y = min(max(b.y, top), bottom)
        b.set_position(x, y)
        self._apply_position(force=True)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.build_menu().exec(event.globalPos())
        event.accept()

    # ------------------------------------------------------------------
    # 우클릭 메뉴
    # ------------------------------------------------------------------

    def build_menu(self) -> QMenu:
        menu = QMenu()

        pause_text = "다시 움직이기" if self.behavior.paused else "일시정지"
        menu.addAction(pause_text, self.toggle_pause)
        menu.addAction("말하기", self.say)
        menu.addSeparator()

        speed_menu = menu.addMenu("속도")
        group = QActionGroup(speed_menu)
        for key, label in settings.SPEED_LABELS.items():
            act = QAction(f"{label}", speed_menu, checkable=True)
            act.setChecked(self.prefs.speed == key)
            act.triggered.connect(lambda _=False, k=key: self.set_speed(k))
            group.addAction(act)
            speed_menu.addAction(act)

        size_menu = menu.addMenu("크기")
        group2 = QActionGroup(size_menu)
        for key, label in settings.SIZE_LABELS.items():
            act = QAction(f"{label}", size_menu, checkable=True)
            act.setChecked(self.prefs.size == key)
            act.triggered.connect(lambda _=False, k=key: self.set_size(k))
            group2.addAction(act)
            size_menu.addAction(act)

        top = QAction("항상 위", menu, checkable=True)
        top.setChecked(self.prefs.always_on_top)
        top.triggered.connect(lambda checked=False: self.set_always_on_top(bool(checked)))
        menu.addAction(top)

        if self.test_mode:
            menu.addSeparator()
            self._add_test_menu(menu)

        menu.addSeparator()
        menu.addAction("종료", QApplication.quit)
        return menu

    # ------------------------------------------------------------------
    # 개발용 테스트 모드
    # ------------------------------------------------------------------

    def _add_test_menu(self, menu: QMenu) -> None:
        tm = menu.addMenu("[테스트] 애니메이션")
        grp = QActionGroup(tm)
        entries = [
            ("자동 (기본 동작)", None),
            ("헤엄치는 모습 고정", "swim"),
            ("가만히 있는 모습 고정", "idle"),
            ("눈 깜빡이는 모습 고정", "blink"),
        ]
        for label, state in entries:
            act = QAction(label, tm, checkable=True)
            act.setChecked(self.behavior.forced == state)
            act.triggered.connect(lambda _=False, s=state: self.set_test_state(s))
            grp.addAction(act)
            tm.addAction(act)
        tm.addSeparator()
        tm.addAction("▶ 오른쪽→왼쪽 턴 실행", lambda: self.test_turn(True))
        tm.addAction("◀ 왼쪽→오른쪽 턴 실행", lambda: self.test_turn(False))
        loop = QAction("턴 계속 반복", tm, checkable=True)
        loop.setChecked(self._turn_loop)
        loop.triggered.connect(lambda checked=False: self.set_turn_loop(bool(checked)))
        tm.addAction(loop)
        tm.addSeparator()
        tm.addAction("← 왼쪽으로 헤엄 (턴 없이)", lambda: self.test_direction(-1))
        tm.addAction("→ 오른쪽으로 헤엄 (턴 없이)", lambda: self.test_direction(1))
        tm.addSeparator()
        tm.addAction("현재 상태 보기", self.show_debug_info)

    def set_test_state(self, state: Optional[str]) -> None:
        self.behavior.set_forced(state)
        self.player.force_blink_loop = state == "blink"
        log.info("테스트 상태: %s", state or "자동")

    def test_direction(self, direction: int) -> None:
        self.set_test_state("swim")
        self.behavior.set_direction(direction, instant=True)

    def test_turn(self, right_to_left: bool) -> None:
        """강제로 방향 전환 실행 (시작 방향이 다르면 먼저 그 방향으로 맞춘 뒤 turn)."""
        self.behavior.force_turn(right_to_left)
        log.info("테스트: %s", self.behavior.state.value)

    def set_turn_loop(self, on: bool) -> None:
        self._turn_loop = on

    def debug_text(self) -> str:
        b = self.behavior
        spec = self.player.current
        frame = f"{spec.a[0]}#{spec.a[1] + 1}" + (f"→#{spec.b[1] + 1}({spec.t:.2f})" if spec.b else "")
        return (
            f"{b.state.value} | {frame} | v={b.vx:.0f},{b.vy:.0f} | tail={self.player.phase:.2f}"
            f"{' | turn ' + format(b.turn_progress, '.0%') if b.is_turning else ''}"
            f"{' (고정:' + b.forced + ')' if b.forced else ''}"
        )

    def show_debug_info(self) -> None:
        self.say(self.debug_text())

    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        self.bubble.hide()
        self.prefs.save()
        super().closeEvent(event)
