"""헤엄/방향 전환 애니메이션 미리보기 도구 (개발용). PNG 원본은 절대 수정하지 않는다.

    .venv\\Scripts\\python.exe tools\\preview_swim.py                 # 창으로 보기 (재생 방식/주기 바꿔가며 확인)
    .venv\\Scripts\\python.exe tools\\preview_swim.py --report        # 프레임 간 차이 표 + 어색한 구간 점검 (콘솔)
    .venv\\Scripts\\python.exe tools\\preview_swim.py --gif           # GIF 저장 (.tmp/preview/ 에 별도 파일)
    옵션: --mode file|pingpong|smooth   --cycle 3.0 (한 주기 초)   --turn (방향 전환도 같이 저장)

창에서 쓰는 이미지는 실제 앱과 같은 SpriteLibrary(위치 보정 + 공통 크롭)를 거친 것이라
"앱에서 보이는 그대로" 확인할 수 있다.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSize, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter  # noqa: E402

import settings  # noqa: E402
from animation import GROUP_SWIM, GROUP_TURN, FrameSpec, RenderSet, SpriteLibrary, SwimTimeline, make_timeline  # noqa: E402

OUT_DIR = ROOT / ".tmp" / "preview"
MODES = ("file", "pingpong", "smooth")
BG = QColor(214, 222, 232)


# ---------------------------------------------------------------------------
# 렌더링 (앱의 paintEvent 와 같은 방식으로 두 프레임을 섞는다)
# ---------------------------------------------------------------------------


def render_spec(rs: RenderSet, spec: FrameSpec, bg: QColor | None = BG) -> QImage:
    w, h = rs.size.width(), rs.size.height()
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(bg if bg else Qt.GlobalColor.transparent)
    fa = rs.get(spec.a)
    fb = rs.get(spec.b) if spec.b else None
    p = QPainter(img)
    if fb is not None and 0.0 < spec.t < 1.0:
        layer = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(0)
        lp = QPainter(layer)
        lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        lp.setOpacity(1.0 - spec.t)
        lp.drawPixmap(0, 0, fa.pixmap)
        lp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        tmp = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
        tmp.fill(0)
        tp = QPainter(tmp)
        tp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        tp.setOpacity(spec.t)
        tp.drawPixmap(0, 0, fb.pixmap)
        tp.end()
        lp.setOpacity(1.0)
        lp.drawImage(0, 0, tmp)
        lp.end()
        p.drawImage(0, 0, layer)
    else:
        p.drawPixmap(0, 0, fa.pixmap)
    p.end()
    return img


_LIB: SpriteLibrary | None = None  # 꼬리 파도 모드면 mode 와 상관없이 라이브러리의 타임라인을 쓴다


def make_timeline_for(mode: str, n: int) -> SwimTimeline:
    if _LIB is not None and _LIB.procedural:
        return _LIB.timeline
    return make_timeline(n, mode)


# ---------------------------------------------------------------------------
# 점검 표
# ---------------------------------------------------------------------------


def _alpha_mask(img: QImage, scale: int = 4):
    """알파 > 128 이면 1 인 작은 비트맵 (numpy). 프레임 간 모양 차이 비교용."""
    import numpy as np

    small = img.scaled(img.width() // scale, img.height() // scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.FastTransformation).convertToFormat(QImage.Format.Format_ARGB32)
    ptr = small.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(small.height(), small.bytesPerLine() // 4, 4)
    return arr[:, : small.width(), 3] > 128


def shape_diff(a: QImage, b: QImage) -> float:
    import numpy as np

    ma, mb = _alpha_mask(a), _alpha_mask(b)
    union = np.logical_or(ma, mb).sum()
    return float(np.logical_xor(ma, mb).sum() / union) if union else 0.0


def print_report(lib: SpriteLibrary, mode: str, cycle: float) -> None:
    imgs = lib.images[GROUP_SWIM]
    n = len(imgs)
    tl = make_timeline_for(mode, n)
    print(f"[재생 방식: {mode}]  한 주기 {cycle:.1f}초")
    print("  보이는 순서(파일 번호):", " → ".join(str(i) for i in tl.describe()))
    print(f"  경로 구간 수 {len(tl._segs)}, 구간당 평균 {cycle / len(tl._segs) * 1000:.0f} ms")
    print("\n  인접 프레임 모양 차이 (0=같음, 클수록 크게 변함)")
    order = tl.path
    rows = []
    for a, b in zip(order, order[1:] if tl.pingpong else order[1:] + order[:1]):
        rows.append((a + 1, b + 1, shape_diff(imgs[a], imgs[b])))
    med = statistics.median(r[2] for r in rows) or 1e-6
    for a, b, d in rows:
        flag = "  ← 다른 구간보다 크게 변함 (어색할 수 있음)" if d > med * 2.5 and d > 0.02 else ""
        print(f"    frame_{a:02d} → frame_{b:02d}   차이 {d * 100:5.1f}%{flag}")
    print("\n  전체 프레임 쌍 중 가장 다른 쌍 TOP 5 (원본 순서 기준 문제 확인용)")
    pairs = sorted(((shape_diff(imgs[i], imgs[j]), i + 1, j + 1) for i in range(n) for j in range(i + 1, n)),
                   reverse=True)[:5]
    for d, i, j in pairs:
        print(f"    frame_{i:02d} ↔ frame_{j:02d}   {d * 100:5.1f}%")
    print("\n  원본 파일 순서(1→10) 인접 차이")
    for i in range(n - 1):
        d = shape_diff(imgs[i], imgs[i + 1])
        print(f"    frame_{i + 1:02d} → frame_{i + 2:02d}   {d * 100:5.1f}%")
    print("\n  구간별 시간(ms):")
    print("   ", " ".join(f"{s[2] / tl._total * cycle * 1000:.0f}" for s in tl._segs))


# ---------------------------------------------------------------------------
# GIF 저장
# ---------------------------------------------------------------------------


def _to_pil(img: QImage):
    from PIL import Image

    im = img.convertToFormat(QImage.Format.Format_RGBA8888)
    return Image.frombuffer("RGBA", (im.width(), im.height()), bytes(im.constBits()), "raw", "RGBA", im.bytesPerLine(), 1)


def export_gif(lib: SpriteLibrary, mode: str, cycle: float, fps: int = 25, width: int = 480, turn: bool = False) -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rs = lib.build(width, 1.0)
    tl = make_timeline_for(mode, len(lib.images[GROUP_SWIM]))
    n = max(2, round(cycle * fps))
    frames = []
    for k in range(n):
        a, b, t = tl.sample(k / n)
        spec = FrameSpec((GROUP_SWIM, a, 1), (GROUP_SWIM, b, 1) if b != a else None, t)
        frames.append(_to_pil(render_spec(rs, spec)).convert("P", palette=1))
    out = []
    path = OUT_DIR / f"swim_{mode}_{cycle:.1f}s.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=int(1000 / fps), loop=0, disposal=2)
    out.append(path)
    if turn and lib.has_turn:
        nt = len(lib.images[GROUP_TURN])
        steps = round(settings.TURN_DURATION * fps)
        tframes = []
        for k in range(steps):
            prog = k / steps
            active = 1.0 - settings.TURN_HOLD_LAST
            u = min(nt - 1.0, prog / active * (nt - 1))
            i = min(int(u), nt - 1)
            segs = settings.TURN_CROSSFADE_SEGMENTS
            if i < nt - 1 and i < len(segs) and segs[i] and u - i > 0:
                spec = FrameSpec((GROUP_TURN, i, 1), (GROUP_TURN, i + 1, 1), round((u - i) * 12) / 12)
            else:
                spec = FrameSpec((GROUP_TURN, i, 1))
            tframes.append(_to_pil(render_spec(rs, spec)).convert("P", palette=1))
        tpath = OUT_DIR / "turn_right_to_left.gif"
        tframes[0].save(tpath, save_all=True, append_images=tframes[1:], duration=int(1000 / fps), loop=0, disposal=2)
        out.append(tpath)
    return out


# ---------------------------------------------------------------------------
# 창 미리보기
# ---------------------------------------------------------------------------


def run_gui(lib: SpriteLibrary, mode: str, cycle: float) -> int:
    from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel,
                                   QPushButton, QVBoxLayout, QWidget)
    import time

    class Preview(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("부캉이 유영 미리보기 (원본 PNG는 수정하지 않음)")
            self.rs = lib.build(640, 1.0)
            self.mode = mode
            self.tl = make_timeline_for(mode, len(lib.images[GROUP_SWIM]))
            self.cycle = cycle
            self.speed_scale = 1.0
            self.manual: int | None = None
            self.paused = False
            self.t0 = time.perf_counter()
            self.view = QLabel()
            self.view.setFixedSize(self.rs.size)
            self.info = QLabel()
            self.info.setStyleSheet("font-family: Consolas, monospace;")
            self.combo = QComboBox()
            self.combo.addItems([f"{m}  ({d})" for m, d in zip(MODES, ("원본 1→10 반복", "1→10→9→…→2", "추천 경로+부드럽게"))])
            self.combo.setCurrentIndex(MODES.index(mode))
            self.combo.currentIndexChanged.connect(self._mode_changed)
            self.spin = QDoubleSpinBox()
            self.spin.setRange(1.0, 10.0)
            self.spin.setSingleStep(0.5)
            self.spin.setSuffix(" 초/주기")
            self.spin.setValue(cycle)
            self.spin.valueChanged.connect(self._cycle_changed)
            self.pause = QPushButton("일시정지")
            self.pause.setCheckable(True)
            self.pause.toggled.connect(self._pause)
            self.step = QCheckBox("프레임 하나씩 (←/→ 키)")
            self.step.toggled.connect(self._step_toggled)
            top = QHBoxLayout()
            for w in (self.combo, self.spin, self.pause, self.step):
                top.addWidget(w)
            lay = QVBoxLayout(self)
            lay.addLayout(top)
            lay.addWidget(self.view)
            lay.addWidget(self.info)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._tick)
            self.timer.start(16)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        def _mode_changed(self, i: int) -> None:
            self.mode = MODES[i]
            self.tl = make_timeline_for(self.mode, len(lib.images[GROUP_SWIM]))

        def _cycle_changed(self, v: float) -> None:
            phase = self._phase()
            self.cycle = v
            self.t0 = time.perf_counter() - phase * v

        def _pause(self, on: bool) -> None:
            self.paused = on
            self._paused_phase = self._phase()

        def _step_toggled(self, on: bool) -> None:
            self.manual = 0 if on else None
            if on:
                self.pause.setChecked(True)

        def _phase(self) -> float:
            return ((time.perf_counter() - self.t0) / self.cycle) % 1.0

        def keyPressEvent(self, e) -> None:  # noqa: N802
            if self.manual is None:
                return super().keyPressEvent(e)
            n = len(lib.images[GROUP_SWIM])
            if e.key() == Qt.Key.Key_Right:
                self.manual = (self.manual + 1) % n
            elif e.key() == Qt.Key.Key_Left:
                self.manual = (self.manual - 1) % n

        def _tick(self) -> None:
            if self.manual is not None:
                spec = FrameSpec((GROUP_SWIM, self.manual, 1))
                txt = f"수동: frame_{self.manual + 1:02d}"
            else:
                ph = self._paused_phase if self.paused else self._phase()
                a, b, t = self.tl.sample(ph)
                spec = FrameSpec((GROUP_SWIM, a, 1), (GROUP_SWIM, b, 1) if b != a else None, t)
                txt = (f"위상 {ph:.2f}  frame_{a + 1:02d}" + (f" → frame_{b + 1:02d} ({t * 100:.0f}%)" if b != a else "")
                       + f"   주기 {self.cycle:.1f}s")
            self.view.setPixmap(QPixmapFromImage(render_spec(self.rs, spec)))
            seq = " → ".join(str(i) for i in self.tl.describe())
            self.info.setText(txt + "\n순서: " + seq)

    from PySide6.QtGui import QPixmap

    def QPixmapFromImage(img: QImage) -> QPixmap:  # noqa: N802
        return QPixmap.fromImage(img)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = Preview()
    w.show()
    return app.exec()


def main() -> int:
    ap = argparse.ArgumentParser(description="부캉이 유영 애니메이션 미리보기/점검/GIF 저장")
    ap.add_argument("--mode", choices=MODES, default=settings.SWIM_ORDER_MODE if settings.SWIM_ORDER_MODE in MODES else "smooth")
    ap.add_argument("--cycle", type=float, default=settings.SPEED_PRESETS[settings.DEFAULT_SPEED].tail_period)
    ap.add_argument("--report", action="store_true", help="프레임 간 차이 표 출력")
    ap.add_argument("--gif", action="store_true", help=".tmp/preview/ 에 GIF 저장 (모든 재생 방식)")
    ap.add_argument("--turn", action="store_true", help="--gif 와 함께: turn GIF 도 저장")
    a = ap.parse_args()

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])  # noqa: F841
    global _LIB
    lib = SpriteLibrary()
    _LIB = lib
    if lib.procedural:
        print("[꼬리 파도 모드] 기준 PNG 한 장을 코드로 휘게 해서 재생합니다 (settings.SWIM_PROCEDURAL). "
              "예전 10장 재생 방식을 보려면 SWIM_PROCEDURAL = False 로 바꾸세요.")
    if lib.is_placeholder:
        print("PNG 에셋을 읽지 못했습니다:\n" + "\n".join(lib.notes))
        return 1
    if a.report:
        for m in MODES:
            print_report(lib, m, a.cycle)
            print("-" * 60)
        return 0
    if a.gif:
        for m in MODES:
            for p in export_gif(lib, m, a.cycle, turn=a.turn and m == "smooth"):
                print("저장:", p)
        return 0
    return run_gui(lib, a.mode, a.cycle)


if __name__ == "__main__":
    sys.exit(main())
