"""스프라이트 로딩 / 크기별 렌더 캐시 / 프레임 재생.

핵심 아이디어
1. PNG 는 1254x1254 캔버스에 상어가 있고 여백이 매우 크다.
   → (코드에서) 프레임별 위치 보정값(오프셋)을 적용한 뒤, 모든 프레임을 "캐릭터 영역의 합집합"으로
   똑같이 잘라낸다. 같은 사각형으로 자르므로 프레임이 바뀌어도 크기/머리 위치가 튀지 않는다.
   (원본 PNG 파일은 읽기만 하고 절대 수정하지 않는다.)
2. 화면에 그리기 전에 필요한 크기로 미리 스케일해서 QPixmap 으로 캐시한다. (매 프레임 스케일 금지)
3. 왼쪽 방향은 오른쪽 이미지를 좌우 반전해서 미리 만들어 둔다.
4. 헤엄 꼬리 움직임은 "시간(위상) → 프레임 두 장 + 섞는 비율" 로 계산한다 (SwimTimeline).
   실제 경과 시간 기준이라 PC 성능과 무관하고, 화면 이동 속도와도 독립적이다.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap, QRegion, QTransform

import settings
from asset_check import AssetReport, alpha_bbox, check_assets
from placeholder import make_placeholder_frames

log = logging.getLogger("bukangi.animation")

GROUP_SWIM = "swim"
GROUP_TURN = "turn"
GROUP_IDLE = "idle"  # 예전 PNG (USE_LEGACY_IDLE_ASSETS)
GROUP_BLINK = "blink"  # 예전 PNG (USE_LEGACY_IDLE_ASSETS)

# (그룹, 프레임 번호(0부터), 좌우 반전 +1=그대로/-1=반전)
Key = tuple[str, int, int]

BLEND_STEPS = 12  # 프레임 섞는 비율을 이 단계로 양자화 (그림이 바뀔 때만 다시 그리기 위함)


@dataclass(frozen=True)
class FrameSpec:
    """"지금 화면에 무엇을 그릴지". 같으면 다시 그릴 필요가 없다 (frozen → == 비교 가능)."""

    a: Key
    b: Optional[Key] = None  # 섞을 두 번째 프레임 (없으면 a 한 장만)
    t: float = 0.0  # b 의 비율 (0~1)
    blink: float = 0.0  # 눈 감김 정도: 0=뜸, 0.5=반쯤, 1=완전히 감음
    wide_mask: bool = False  # True 면 클릭 영역을 turn 까지 포함한 넓은 모양으로
    squash: float = 1.0  # 가로 배율 (1=그대로, 작을수록 납작). flip 방식 방향 전환에서만 1 미만


# ---------------------------------------------------------------------------
# 헤엄 타임라인: 시간(위상) -> 프레임
# ---------------------------------------------------------------------------


class SwimTimeline:
    """꼬리 한 번 왕복을 "위상(0~1)" 으로 표현하고, 위상에서 (프레임 A, 프레임 B, 섞는 비율)을 구한다.

    - path     : 재생 순서 (프레임 인덱스, 0부터)
    - pingpong : True 면 끝에서 되돌아온다(양 끝 프레임을 두 번 연속 재생하지 않음), False 면 처음으로 돌아가 반복
    - crossfade: True 면 인접한 두 프레임을 비율로 섞어 부드럽게, False 면 가장 가까운 프레임 한 장
    - ease     : 양 끝에서 천천히 멈췄다 돌아오는 정도 (pingpong 에서만)
    - weights  : 구간별 시간 가중치 (길이 = 구간 수)
    """

    def __init__(
        self,
        path: Sequence[int],
        pingpong: bool = True,
        crossfade: bool = True,
        ease: float = 0.0,
        weights: Optional[Sequence[float]] = None,
    ) -> None:
        self.path = list(path)
        if not self.path:
            raise ValueError("path 가 비어 있습니다")
        self.pingpong = pingpong and len(self.path) > 1
        self.crossfade = crossfade
        self.ease = max(0.0, min(1.0, ease)) if self.pingpong else 0.0
        k = len(self.path)
        n_base = (k - 1) if self.pingpong else k
        w = list(weights) if weights and len(weights) == n_base else [1.0] * n_base
        w = [max(0.05, float(x)) for x in w]
        if self.pingpong:
            # 앞으로 K-1 구간, 뒤로 K-1 구간 (같은 가중치 재사용)
            self._segs = [(i, 1, w[i]) for i in range(k - 1)] + [(i, -1, w[i]) for i in reversed(range(k - 1))]
        else:
            self._segs = [(i, 1, w[i]) for i in range(k)]
        self._total = sum(s[2] for s in self._segs)

    # -- 핵심 ---------------------------------------------------------------

    def position(self, phase: float) -> tuple[float, bool]:
        """위상 → (경로 위의 연속 위치 u, 앞으로 가는 중인지). u=1.5 는 path[1] 과 path[2] 의 중간."""
        x = (phase % 1.0) * self._total
        acc = 0.0
        u, forward = 0.0, True
        last = len(self._segs) - 1
        for n, (start, direction, wgt) in enumerate(self._segs):
            if x < acc + wgt or n == last:
                f = min(1.0, max(0.0, (x - acc) / wgt))
                u = start + f if direction > 0 else start + 1 - f
                forward = direction > 0
                break
            acc += wgt
        if self.ease > 0 and len(self.path) > 1:
            span = len(self.path) - 1
            z = u / span
            z = (1 - self.ease) * z + self.ease * (1 - math.cos(math.pi * z)) / 2
            u = z * span
        return u, forward

    def sample(self, phase: float) -> tuple[int, int, float]:
        """위상 → (프레임 A 인덱스, 프레임 B 인덱스, B 를 섞는 비율 0~1)."""
        u, _ = self.position(phase)
        k = len(self.path)
        if k == 1:
            return self.path[0], self.path[0], 0.0
        if not self.crossfade:
            idx = self.path[min(k - 1, int(u + 0.5)) % k]
            return idx, idx, 0.0
        i = int(u)
        if self.pingpong:
            i = min(i, k - 2)
            j = i + 1
        else:
            i %= k
            j = (i + 1) % k
        t = u - int(u)
        if self.pingpong and int(u) > k - 2:
            t = 1.0
        t = round(t * BLEND_STEPS) / BLEND_STEPS
        if t >= 1.0:
            return self.path[j], self.path[j], 0.0
        return self.path[i], self.path[j], t

    def phase_for(self, frame_index: int, forward: bool = True) -> float:
        """frame_index 프레임이 보이는 위상(가장 가까운 값). 상태가 바뀐 뒤 꼬리 자세를 이어 붙일 때 쓴다."""
        if frame_index not in self.path:
            return 0.0
        target = self.path.index(frame_index)
        best, best_err = 0.0, 1e9
        for n in range(1024):
            ph = n / 1024
            u, fwd = self.position(ph)
            if self.pingpong and fwd != forward:
                continue
            err = abs(u - target)
            if err < best_err:
                best, best_err = ph, err
        return best

    def describe(self, file_numbers: bool = True) -> list[int]:
        """한 주기 동안 보이는 프레임 순서(1부터 파일 번호). 문서/로그/테스트용."""
        out: list[int] = []
        n = 4 * len(self._segs)
        for s in range(n):
            a, b, t = self.sample((s + 0.5) / n)
            i = a if t < 0.5 else b  # 섞는 중이면 더 진하게 보이는 쪽
            if not out or out[-1] != i:
                out.append(i)
        if len(out) > 1 and out[0] == out[-1]:
            out.pop()
        return [i + 1 for i in out] if file_numbers else out


def make_timeline(frame_count: int, mode: Optional[str] = None) -> SwimTimeline:
    """settings 의 재생 방식으로 타임라인을 만든다. frame_count 보다 큰 번호는 무시."""
    mode = mode or settings.SWIM_ORDER_MODE
    if mode == "file":
        return SwimTimeline(range(frame_count), pingpong=False, crossfade=False)
    if mode == "pingpong":
        return SwimTimeline(range(frame_count), pingpong=True, crossfade=False)
    path = [n - 1 for n in settings.SWIM_SMOOTH_PATH if 1 <= n <= frame_count] or list(range(frame_count))
    weights = settings.SWIM_SEGMENT_WEIGHTS
    return SwimTimeline(
        path, pingpong=True, crossfade=settings.SWIM_CROSSFADE, ease=settings.SWIM_EASE_STRENGTH, weights=weights
    )


# ---------------------------------------------------------------------------
# 렌더 결과
# ---------------------------------------------------------------------------


@dataclass
class RenderedFrame:
    pixmap: QPixmap  # devicePixelRatio 가 설정된 화면 출력용 이미지


class RenderSet:
    """한 가지 (크기, dpr) 조합에 대해 미리 만들어 둔 모든 프레임."""

    def __init__(self, size: QSize, dpr: float) -> None:
        self.size = size  # 논리 크기 = 창 크기
        self.dpr = dpr
        self._frames: dict[Key, RenderedFrame] = {}
        # 클릭 모양(창 마스크): 모든 프레임의 합집합을 방향별로 한 번만 설정한다.
        # (프레임마다 setMask 를 바꾸면 CPU를 많이 쓰고 깜빡일 수 있어서 이렇게 한다)
        self.masks: dict[int, QRegion] = {1: QRegion(), -1: QRegion()}  # swim 계열
        self.wide_masks: dict[int, QRegion] = {1: QRegion(), -1: QRegion()}  # swim + turn
        # 눈 위치(논리 px, 방향별), 눈 반지름, 눈꺼풀 색
        self.eye: dict[int, QPointF] = {1: QPointF(), -1: QPointF()}
        self.eye_radius = 3.0
        self.skin = QColor(40, 44, 48)
        self.lid = QColor(18, 20, 22)
        # 헤엄 상어가 차지하는 영역(논리 px) - 말풍선 위치 계산용
        self.body_rect = QRect()

    def add(self, key: Key, frame: RenderedFrame) -> None:
        self._frames[key] = frame

    def get(self, key: Key) -> Optional[RenderedFrame]:
        return self._frames.get(key)

    def mask_for(self, mirror: int, wide: bool) -> QRegion:
        table = self.wide_masks if wide else self.masks
        return table.get(mirror, table[1])


# ---------------------------------------------------------------------------
# 스프라이트 라이브러리 (원본 로딩 + 정렬)
# ---------------------------------------------------------------------------


def _shift_image(img: QImage, dx: int, dy: int) -> QImage:
    """이미지 내용을 (dx,dy) 만큼 옮긴 새 이미지(같은 크기). 원본 객체는 건드리지 않는다."""
    if dx == 0 and dy == 0:
        return img
    out = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage(dx, dy, img)
    p.end()
    return out


def _pad_left(img: QImage, m: int) -> QImage:
    """이미지 왼쪽에 투명한 여백 m 픽셀을 붙인 새 이미지 (원본 객체는 건드리지 않는다)."""
    if m <= 0:
        return img
    out = QImage(img.width() + m, img.height(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawImage(m, 0, img)
    p.end()
    return out


_AREA_TABLE = bytes(1 if v > settings.ALPHA_THRESHOLD else 0 for v in range(256))


def alpha_area(image: QImage) -> int:
    """알파가 있는 픽셀 수 = 그림 속 상어가 차지하는 면적 (바이트 변환으로 빠르게 센다)."""
    a8 = image.convertToFormat(QImage.Format.Format_Alpha8)
    w, h, bpl = a8.width(), a8.height(), a8.bytesPerLine()
    data = bytes(a8.constBits())
    if bpl == w:
        return data.translate(_AREA_TABLE).count(1)
    return sum(data[y * bpl : y * bpl + w].translate(_AREA_TABLE).count(1) for y in range(h))


def alpha_centroid(image: QImage) -> tuple[float, float]:
    """알파가 있는 픽셀들의 무게중심 (x, y). 몸통 전체의 "중심"이라 프레임이 바뀌어도 몸이 제자리에 있는지 비교하기 좋다."""
    a8 = image.convertToFormat(QImage.Format.Format_Alpha8)
    w, h, bpl = a8.width(), a8.height(), a8.bytesPerLine()
    data = bytes(a8.constBits())
    rows = [data[y * bpl : y * bpl + w].translate(_AREA_TABLE).count(1) for y in range(h)]
    cols = [data[x : x + bpl * (h - 1) + 1 : bpl].translate(_AREA_TABLE).count(1) for x in range(w)]
    total = sum(rows)
    if total <= 0:
        return w / 2.0, h / 2.0
    return sum(x * c for x, c in enumerate(cols)) / total, sum(y * c for y, c in enumerate(rows)) / total


def auto_turn_offsets(turn: list[QImage], ref: QImage) -> list[tuple[int, int]]:
    """turn 프레임들의 위치 보정값을 자동으로 구한다 → 방향 전환 중에도 몸 중심이 흔들리지 않는다.

    - 세로: 모든 프레임의 몸 중심 높이를 헤엄 그림과 같은 높이로 고정한다.
    - 가로: 첫 프레임은 헤엄 그림과 같은 위치, 마지막 프레임은 "좌우 반전한 헤엄 그림"과 같은 위치에 두고,
      그 사이는 부드럽게(smoothstep) 미끄러지게 한다. 그래서 turn 이 시작/끝나는 순간 몸이 튀지 않는다.
    """
    cx, cy = alpha_centroid(ref)
    x_start, x_end = cx, (ref.width() - 1) - cx
    n = len(turn)
    out: list[tuple[int, int]] = []
    for i, img in enumerate(turn):
        t = i / (n - 1) if n > 1 else 0.0
        s = t * t * (3 - 2 * t) if settings.TURN_ALIGN_EASE else t
        tx = x_start + (x_end - x_start) * s
        ix, iy = alpha_centroid(img)
        out.append((round(tx - ix), round(cy - iy)))
    return out


def scale_about(image: QImage, scale: float, ax: float, ay: float) -> QImage:
    """(ax, ay) 점을 고정한 채 이미지를 scale 배로 키우거나 줄인 새 이미지 (같은 캔버스 크기). 원본은 그대로."""
    if abs(scale - 1.0) < 1e-3:
        return image
    out = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.translate(ax, ay)
    p.scale(scale, scale)
    p.translate(-ax, -ay)
    p.drawImage(0, 0, image)
    p.end()
    return out


def normalize_turn_sizes(turn: list[QImage], ref_area: int) -> list[float]:
    """turn 프레임마다 상어가 차지하는 면적이 헤엄 그림과 같아지도록 크기를 맞춘다 (turn 리스트를 직접 고친다).

    turn 그림은 몸을 틀 때 카메라 쪽으로 다가오는 모습이라 turn_04 는 헤엄 때보다 면적이 1.6배나 커서
    "갑자기 몸집이 커졌다 작아지는" 것처럼 보인다. 면적의 제곱근 비율로 줄이고 늘려서 그 차이를 없앤다.
    고정점은 머리 쪽 끝(앞 프레임은 오른쪽 끝, 뒤 프레임은 왼쪽 끝)이라 머리 위치가 덜 움직인다. 반환: 적용한 배율들.
    """
    scales: list[float] = []
    lo, hi = settings.TURN_SIZE_SCALE_RANGE
    for i, img in enumerate(turn):
        area = alpha_area(img)
        bb = alpha_bbox(img)
        if area <= 0 or bb.isEmpty() or ref_area <= 0:
            scales.append(1.0)
            continue
        s = (ref_area / area) ** (0.5 * settings.TURN_SIZE_STRENGTH)
        s = min(hi, max(lo, s))
        head_right = i < settings.TURN_HEAD_RIGHT_FRAMES
        ax = bb.right() if head_right else bb.left()
        turn[i] = scale_about(img, s, ax, bb.center().y())
        scales.append(s)
    return scales


def make_tail_wave_frames(base: QImage, count: int) -> list[QImage]:
    """기준 이미지 한 장에서 "꼬리가 파도치는" 이미지 count 장을 만든다 (한 주기, 처음/끝이 이어짐).

    방식: 몸 뒤쪽(꼬리 쪽 TAIL_WAVE_REGION)을 가는 세로 띠로 잘라 각 띠를 옮긴다.
    옮기는 양 = 진폭 × (꼬리 쪽으로 갈수록 커짐) × sin(시간 위상 - 꼬리로 갈수록 늦어지는 지연).
    기본은 좌우(몸 앞뒤 방향, TAIL_SWAY_OUT/IN)로만 흔들고, 위아래(TAIL_WAVE_AMPLITUDE)는 0 이다.
    - 앞쪽 몸/머리/지느러미는 한 픽셀도 안 움직이므로 프레임이 바뀌어도 크기·명암·머리 위치가 변하지 않는다.
    - 상어는 오른쪽을 보므로 꼬리는 왼쪽 끝이다.
    """
    bb = alpha_bbox(base)
    if bb.isEmpty() or count < 2:
        return [base]
    length = bb.width()
    x_tail = bb.left()
    x_pivot = x_tail + settings.TAIL_WAVE_REGION * length
    amp = settings.TAIL_WAVE_AMPLITUDE * length  # 위아래 (기본 0: 위아래로는 움직이지 않는다)
    sway_out = settings.TAIL_SWAY_OUT * length  # 원본 그림보다 꼬리가 바깥(몸에서 멀어지는 쪽)으로 더 펴지는 폭
    sway_in = settings.TAIL_SWAY_IN * length  # 몸 쪽(안쪽)으로 오므라드는 폭
    strip = max(1, int(settings.TAIL_WAVE_STRIP))
    xs = int(x_pivot)
    w, h = base.width(), base.height()
    depth = settings.TAIL_DEPTH_SCALE
    # 깊이(화면 쪽/먼 쪽) 표현은 꼬리 중심선(꼬리가 시작되는 곳의 몸 높이)을 기준으로 위아래 크기를 키우고 줄인다
    col_bb = alpha_bbox(base.copy(min(xs, w - 1), 0, 1, h))
    y_c = col_bb.center().y() if not col_bb.isEmpty() else h / 2.0
    frames: list[QImage] = []
    for k in range(count):
        phi = 2.0 * math.pi * k / count
        out = QImage(base.size(), QImage.Format.Format_ARGB32_Premultiplied)
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.drawImage(QRect(xs, 0, w - xs, h), base, QRect(xs, 0, w - xs, h))  # 고정 부분
        p.setClipRect(0, 0, xs, h)  # 크기를 바꿔 그린 띠의 가장자리가 고정 부분을 넘어 번지지 않게
        # 꼬리가 바깥으로 펴지면 원본 꼬리 끝보다 더 먼 곳까지 그려야 한다 (_load 에서 그만큼 여백을 미리 만들어 둔다)
        for x in range(max(0, int(x_tail - sway_out) - 2 * strip), xs, strip):
            width = min(strip, xs - x)
            u = (x_pivot - (x + width / 2.0)) / max(1.0, x_pivot - x_tail)  # 0=고정 경계, 1=꼬리 끝
            u = min(1.0, max(0.0, u))
            wave = math.sin(phi - settings.TAIL_WAVE_LAG * u)
            weight = u ** settings.TAIL_WAVE_POWER
            dy = amp * weight * wave
            # 좌우 흔들림: 옆에서 본 꼬리가 좌우로 휘면 몸 앞뒤 방향으로 줄었다 펴진다.
            # shift > 0 이면 안쪽(오므림), < 0 이면 바깥(원본보다 길게 펴짐). 원본 그림이 가장 편 모습이 아니라
            # 그 중간쯤이 되도록 -sway_out ~ +sway_in 사이를 오간다.
            # 도착 위치(x)마다 원본의 어느 부분을 가져올지 정하는 방식이라 띠 사이에 틈이 생기지 않는다.
            shift = weight * ((sway_in - sway_out) / 2.0 + (sway_in + sway_out) / 2.0 * wave)
            # 깊이: 꼬리가 화면 쪽으로 오면(wave>0, 짧아 보이는 순간) 커 보이고, 멀어지면 작아 보인다
            s = 1.0 + depth * weight * wave
            p.drawImage(QRectF(x, y_c - y_c * s + dy, width, h * s), base, QRectF(x - shift, 0, width, h))
        p.end()
        frames.append(out)
    return frames


class SpriteLibrary:
    """에셋을 읽어 위치 보정 후 공통 영역으로 잘라 보관한다. 문제가 있어도 예외 없이 대체 동작한다."""

    def __init__(self, assets_dir: Optional[Path] = None, force_placeholder: bool = False) -> None:
        self.assets_dir = Path(assets_dir) if assets_dir else settings.ASSETS_DIR
        self.report: AssetReport = check_assets(self.assets_dir)
        self.is_placeholder = False
        self.notes: list[str] = []  # 사용자에게 알려줄 안내/경고
        self.images: dict[str, list[QImage]] = {GROUP_SWIM: [], GROUP_TURN: [], GROUP_IDLE: [], GROUP_BLINK: []}
        self.eye_src = QPointF(*settings.EYE_POS_SRC)
        self.eye_radius_src = float(settings.EYE_RADIUS_SRC)
        self.crop = QRect()  # 원본 좌표에서 잘라낸 영역
        self.swim_bbox = QRect()  # 잘라낸 이미지 좌표에서 헤엄 상어가 차지하는 영역
        self.skin = QColor(40, 44, 48)
        self.turn_scales: list[float] = []  # turn 프레임별 크기 보정 배율 (확인/테스트용)
        self.procedural = False  # True 면 swim 프레임이 "기준 PNG 한 장을 코드로 휜" 이미지다
        self._load(force_placeholder)
        n_swim = len(self.images[GROUP_SWIM])
        if self.is_placeholder:  # 임시 상어(4장)는 단순 왕복
            self.timeline = SwimTimeline(range(n_swim), pingpong=True, crossfade=True, ease=0.3)
        elif self.procedural:  # 꼬리 파도: 한 주기가 이어지는 반복(왕복 아님), 인접 프레임은 거의 같아서 섞어도 번지지 않는다
            self.timeline = SwimTimeline(range(n_swim), pingpong=False, crossfade=True)
        else:
            self.timeline = make_timeline(n_swim)
        # turn 이 끝난 뒤 꼬리 자세를 이어 붙일 프레임 (0부터)
        self.exit_frame = 0 if self.procedural else settings.TURN_EXIT_SWIM_FRAME - 1
        # 방향 전환 방식: "art"(turn PNG 재생) | "flip"(헤엄 그림을 납작하게 눌러 뒤집기) | "none"(바로 반전)
        if settings.TURN_STYLE == "flip":
            self.turn_mode = "flip"
        else:
            self.turn_mode = "art" if self.has_turn else "none"
        self.turn_duration = settings.TURN_DURATION if self.turn_mode == "art" else settings.TURN_FLIP_DURATION
        if self.procedural and self.turn_mode == "art" and settings.TURN_AUTO_EXIT_FRAME:
            self.exit_frame = self._best_exit_frame()
        first = self.images[GROUP_SWIM][0]
        self.aspect = first.height() / first.width()

    @property
    def has_turn(self) -> bool:
        return bool(self.images[GROUP_TURN])

    def _best_exit_frame(self) -> int:
        """마지막 turn 그림(turn_08)과 모양이 가장 비슷한 "좌우 반전한 헤엄 프레임" 번호 (0부터).

        turn 이 끝나면 turn_08 → 헤엄 그림으로 짧게 섞는데, 꼬리 자세가 다르면 꼬리가 두 개로 겹쳐 보이고 몸이 흔들려 보인다.
        그래서 꼬리 파도 프레임 중 실루엣 차이(XOR)가 가장 작은 것에서 헤엄을 이어간다.
        """
        def bits(im: QImage) -> int:
            a8 = im.convertToFormat(QImage.Format.Format_Alpha8)
            w, h, bpl = a8.width(), a8.height(), a8.bytesPerLine()
            data = bytes(a8.constBits())
            if bpl != w:
                data = b"".join(data[y * bpl : y * bpl + w] for y in range(h))
            return int.from_bytes(data.translate(_AREA_TABLE), "big")

        last = bits(self.images[GROUP_TURN][-1])
        diffs = [(last ^ bits(im.flipped(Qt.Orientation.Horizontal))).bit_count() for im in self.images[GROUP_SWIM]]
        best = min(range(len(diffs)), key=diffs.__getitem__)
        log.info("turn 종료 후 이어받을 꼬리 프레임: %d (차이 %d → 기본 0번은 %d)", best, diffs[best], diffs[0])
        return best

    # -- 로딩 ---------------------------------------------------------------

    def _read_group(self, folder: str) -> Optional[list[QImage]]:
        """폴더의 모든 파일이 정상일 때만 이미지 리스트를 돌려준다. 하나라도 문제면 None."""
        checks = self.report.group(folder)
        if not checks or not all(c.ok for c in checks):
            return None
        out: list[QImage] = []
        for c in checks:  # 체크 목록은 settings 에 적힌 파일 순서(번호순)라서 정렬이 항상 같다
            reader = QImageReader(str(c.path))
            img = reader.read()
            if img.isNull():  # 검사 후 읽기 사이에 파일이 바뀐 경우 등
                log.warning("이미지 읽기 실패: %s (%s)", c.path, reader.errorString())
                return None
            out.append(img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied))
        return out

    def _problems(self, folder: str) -> str:
        return "\n".join(p for p in self.report.problems if p.startswith(folder + "/"))

    def _load(self, force_placeholder: bool) -> None:
        for p in self.report.problems:
            log.warning("에셋 문제: %s", p)
        for w in self.report.global_warnings:
            log.warning(w)

        swim = None if force_placeholder else self._read_group("swim_right")
        if swim is None:
            # 헤엄 이미지가 없으면 스타일/크기가 섞이지 않도록 전부 placeholder 로 간다.
            self.is_placeholder = True
            if not force_placeholder:
                self.notes.append(
                    "헤엄 에셋(swim_right)을 사용할 수 없어 임시 상어(placeholder)로 실행합니다.\n"
                    + "\n".join(self.report.problems[:12])
                )
            frames = make_placeholder_frames(settings.TURN_FRAME_COUNT)
            self.images[GROUP_SWIM] = frames["swim"]
            self.images[GROUP_TURN] = frames["turn"]
            self.eye_src = QPointF(1040, 240)
            self.eye_radius_src = 11.0
            self.skin = QColor("#3b4249")
            self._finalize(offsets_swim=(), offsets_turn=())
            log.info("placeholder 상어 사용")
            return

        turn = None if force_placeholder else self._read_group("turn_right_to_left")
        if turn is None:
            self.notes.append(
                "turn 에셋(turn_right_to_left)에 문제가 있어 방향 전환 애니메이션 없이 헤엄만 합니다.\n"
                + self._problems("turn_right_to_left")
            )
            turn = []
        offsets_swim: Sequence[tuple[int, int]] = settings.SWIM_FRAME_OFFSETS
        # 꼬리가 원본 그림보다 바깥으로 더 펴지려면 그림 왼쪽(꼬리 쪽)에 여백이 필요하다.
        # 모든 그림에 같은 여백을 붙여야 크기/위치가 서로 맞는다 (눈 위치도 같이 옮긴다).
        self.pad_left = 0
        if settings.SWIM_PROCEDURAL and settings.TAIL_SWAY_OUT > 0:
            b0 = min(max(int(settings.SWIM_BASE_FRAME), 1), len(swim)) - 1
            self.pad_left = math.ceil(settings.TAIL_SWAY_OUT * alpha_bbox(swim[b0]).width()) \
                + 2 * max(1, int(settings.TAIL_WAVE_STRIP)) + 4
            swim = [_pad_left(im, self.pad_left) for im in swim]
            turn = [_pad_left(im, self.pad_left) for im in turn]
            self.eye_src = QPointF(self.eye_src.x() + self.pad_left, self.eye_src.y())
        self.turn_scales: list[float] = []
        if turn and settings.TURN_NORMALIZE_SIZE:
            ref = swim[min(max(int(settings.SWIM_BASE_FRAME), 1), len(swim)) - 1]
            self.turn_scales = normalize_turn_sizes(turn, alpha_area(ref))
            log.info("turn 크기 보정 배율: %s", ", ".join(f"{s:.3f}" for s in self.turn_scales))
        offsets_turn: Sequence[tuple[int, int]] = settings.TURN_FRAME_OFFSETS
        if turn and settings.TURN_AUTO_ALIGN:
            ref_img = swim[min(max(int(settings.SWIM_BASE_FRAME), 1), len(swim)) - 1]
            bdx, bdy = settings.SWIM_FRAME_OFFSETS[min(max(int(settings.SWIM_BASE_FRAME), 1), len(swim)) - 1] \
                if settings.SWIM_PROCEDURAL else (0, 0)
            offsets_turn = auto_turn_offsets(turn, _shift_image(ref_img, bdx, bdy))
            log.info("turn 위치 자동 보정: %s", offsets_turn)
        if settings.SWIM_PROCEDURAL:
            # 기준 프레임 한 장의 위치를 보정한 뒤, 꼬리를 휜 프레임들로 바꿔서 쓴다
            b = min(max(int(settings.SWIM_BASE_FRAME), 1), len(swim)) - 1
            dx, dy = offsets_swim[b] if b < len(offsets_swim) else (0, 0)
            swim = make_tail_wave_frames(_shift_image(swim[b], dx, dy), settings.TAIL_WAVE_FRAMES)
            offsets_swim = ()  # 이미 보정했다
            self.procedural = True
        self.images[GROUP_SWIM] = swim
        self.images[GROUP_TURN] = turn

        if settings.USE_LEGACY_IDLE_ASSETS:
            for folder, group in (("idle", GROUP_IDLE), ("blink", GROUP_BLINK)):
                imgs = self._read_group(folder)
                if imgs is None:
                    self.notes.append(f"{folder} 에셋에 문제가 있어 사용하지 않습니다.\n" + self._problems(folder))
                    imgs = []
                self.images[group] = [_pad_left(im, self.pad_left) for im in imgs]

        self._finalize(offsets_swim, offsets_turn)
        log.info("PNG 에셋 로딩 완료: swim=%d turn=%d", len(swim), len(turn))

    def _finalize(self, offsets_swim: Sequence[tuple[int, int]], offsets_turn: Sequence[tuple[int, int]]) -> None:
        """크기 통일 → 위치 보정 → 공통 영역으로 자르기 → 눈 색 샘플링."""
        base = self.images[GROUP_SWIM][0].size()
        # 크기가 다른 파일이 섞여 있으면 첫 이미지 크기에 맞춘다 (정렬이 어긋날 수 있음)
        for imgs in self.images.values():
            for i, im in enumerate(imgs):
                if im.size() != base:
                    imgs[i] = im.scaled(base, Qt.AspectRatioMode.IgnoreAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation)

        # 프레임별 위치 보정 (원본 PNG 는 그대로, 메모리상의 복사본만 이동)
        for group, offs in ((GROUP_SWIM, offsets_swim), (GROUP_TURN, offsets_turn)):
            imgs = self.images[group]
            for i in range(len(imgs)):
                dx, dy = offs[i] if i < len(offs) else (0, 0)
                imgs[i] = _shift_image(imgs[i], dx, dy)

        swim_union = QRect()
        for im in self.images[GROUP_SWIM]:
            swim_union = swim_union.united(alpha_bbox(im))
        union = QRect(swim_union)
        for group in (GROUP_TURN, GROUP_IDLE, GROUP_BLINK):
            for im in self.images[group]:
                union = union.united(alpha_bbox(im))
        full = QRect(0, 0, base.width(), base.height())
        if union.isEmpty():
            union = QRect(full)
        pad = settings.CROP_PADDING
        union = union.adjusted(-pad, -pad, pad, pad).intersected(full)
        self.crop = union
        log.info("공통 크롭 영역: %s (원본 %dx%d)", union, base.width(), base.height())

        for group, imgs in self.images.items():
            self.images[group] = [im.copy(union) for im in imgs]
        self.swim_bbox = swim_union.translated(-union.topLeft())
        self.eye_src = QPointF(self.eye_src.x() - union.x(), self.eye_src.y() - union.y())  # 잘린 이미지 좌표

        if not self.is_placeholder:
            self.skin = self._sample_skin(self.images[GROUP_SWIM][0])

    def _sample_skin(self, img: QImage) -> QColor:
        """눈 주변(고리 모양 영역)의 평균 피부색 - 눈꺼풀 색으로 쓴다."""
        cx, cy, r = self.eye_src.x(), self.eye_src.y(), self.eye_radius_src
        r0, r1 = r * 1.5, r * 2.6
        sr = sg = sb = n = 0
        for y in range(int(cy - r1), int(cy + r1) + 1, 2):
            for x in range(int(cx - r1), int(cx + r1) + 1, 2):
                d = math.hypot(x - cx, y - cy)
                if not (r0 <= d <= r1) or not (0 <= x < img.width() and 0 <= y < img.height()):
                    continue
                c = img.pixelColor(x, y)
                lum = (c.red() + c.green() + c.blue()) / 3
                if c.alpha() > 250 and 8 < lum < 120:
                    sr, sg, sb, n = sr + c.red(), sg + c.green(), sb + c.blue(), n + 1
        if n < 10:
            return QColor(40, 44, 48)
        return QColor(sr // n, sg // n, sb // n)

    # -- 크기별 렌더링 --------------------------------------------------------

    def build(self, logical_width: int, dpr: float = 1.0) -> RenderSet:
        """주어진 논리 가로 크기와 dpr 에 맞춰 모든 프레임을 미리 렌더링한다."""
        dpr = max(1.0, float(dpr))
        lw = max(16, int(logical_width))
        lh = max(8, round(lw * self.aspect))
        pw, ph = round(lw * dpr), round(lh * dpr)
        rs = RenderSet(QSize(lw, lh), dpr)
        scale = lw / self.images[GROUP_SWIM][0].width()
        mirror_tr = QTransform().scale(-1, 1)

        for group, imgs in self.images.items():
            for idx, src in enumerate(imgs):
                phys = src.scaled(pw, ph, Qt.AspectRatioMode.IgnoreAspectRatio,
                                  Qt.TransformationMode.SmoothTransformation)
                logical = phys if abs(dpr - 1.0) < 0.01 else phys.scaled(
                    lw, lh, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
                for mirror in (1, -1):
                    pimg = phys if mirror == 1 else phys.transformed(mirror_tr)
                    pm = QPixmap.fromImage(pimg)
                    pm.setDevicePixelRatio(dpr)
                    rs.add((group, idx, mirror), RenderedFrame(pm))
                    limg = logical if mirror == 1 else logical.transformed(mirror_tr)
                    region = _make_mask(limg)
                    if group == GROUP_TURN:
                        rs.wide_masks[mirror] = rs.wide_masks[mirror].united(region)
                    else:
                        rs.masks[mirror] = rs.masks[mirror].united(region)
                        rs.wide_masks[mirror] = rs.wide_masks[mirror].united(region)

        # 방향이 다른 두 그림을 섞는 순간(turn 종료)을 위한 양쪽 방향 합집합 (키 0)
        rs.masks[0] = rs.masks[1].united(rs.masks[-1])
        rs.wide_masks[0] = rs.wide_masks[1].united(rs.wide_masks[-1])

        ex, ey = self.eye_src.x() * scale, self.eye_src.y() * scale
        rs.eye = {1: QPointF(ex, ey), -1: QPointF(lw - ex, ey)}
        rs.eye_radius = self.eye_radius_src * scale
        rs.skin = self.skin
        rs.lid = QColor(self.skin).darker(300)
        bb = self.swim_bbox
        rs.body_rect = QRect(round(bb.x() * scale), round(bb.y() * scale),
                             round(bb.width() * scale), round(bb.height() * scale))
        return rs


def _make_mask(logical_image: QImage) -> QRegion:
    """알파 → 창 모양(QRegion). 반투명한 가장자리도 살리기 위해 같은 이미지를 여러 번 겹쳐 알파를 키운 뒤 자른다."""
    boosted = QImage(logical_image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    boosted.fill(Qt.GlobalColor.transparent)
    p = QPainter(boosted)
    for _ in range(4):
        p.drawImage(0, 0, logical_image)
    p.end()
    return QRegion(QPixmap.fromImage(boosted).mask())


# ---------------------------------------------------------------------------
# 프레임 재생기
# ---------------------------------------------------------------------------


class AnimationPlayer:
    """behavior(상태) 를 읽어서 이번 틱에 그릴 FrameSpec 을 결정한다.

    - 헤엄 중: 꼬리 위상이 시간에 따라 흐르고, 타임라인이 프레임 두 장 + 섞는 비율을 정한다.
    - 가만히: 같은 타임라인을 더 천천히(IDLE_TAIL_SLOWDOWN 배) 재생해서 떠 있는 느낌을 낸다.
    - turn  : 진행도(0~1)에 따라 turn_01 → turn_08 순서대로 재생. 이 동안 헤엄 위상은 멈춘다.
    - 상태가 바뀔 때(헤엄 ↔ turn) 짧게(STATE_XFADE_SECONDS) 두 그림을 섞어서 튀지 않게 한다.
    - 눈 깜빡임: 어떤 상태든(turn 제외) 눈꺼풀을 덮어 그린다.
    """

    def __init__(self, library: SpriteLibrary, rng: Optional[random.Random] = None) -> None:
        self.lib = library
        self.rng = rng or random.Random()
        self.timeline = library.timeline
        self.tail_period = settings.SPEED_PRESETS[settings.DEFAULT_SPEED].tail_period
        self.phase = 0.0
        self._rate = 1.0 / self.tail_period
        self._was_turning = False
        self._last_single: Key = (GROUP_SWIM, self.timeline.path[0], 1)
        self._xfade_from: Optional[Key] = None
        self._xfade_to: Optional[Key] = None
        self._xfade_left = 0.0
        # 눈 깜빡임
        self._blink_step = -1
        self._blink_left = 0.0
        self._since_blink = 99.0
        self.force_blink_loop = False  # 테스트 모드: 계속 깜빡임
        self._next_blink = self._roll_blink()
        self._clock = 0.0
        self.blink_enabled = settings.BLINK_ENABLED
        if settings.USE_LEGACY_IDLE_ASSETS and library.images[GROUP_BLINK]:
            self.blink_enabled = True
        self.current = FrameSpec(self._last_single)

    # -- 외부 설정 ------------------------------------------------------------

    def set_tail_period(self, seconds: float) -> None:
        self.tail_period = max(0.5, float(seconds))

    def _roll_blink(self) -> float:
        lo, hi = settings.BLINK_INTERVAL_RANGE
        return self.rng.uniform(lo, hi)

    # -- 한 틱 ----------------------------------------------------------------

    def update(self, dt: float, beh) -> FrameSpec:  # beh: PetBehavior (순환 import 방지를 위해 타입 생략)
        self._clock += dt
        mirror = beh.facing
        turning = beh.is_turning

        # 상태가 바뀐 순간: 직전 그림에서 새 그림으로 짧게 섞는다
        art = self.lib.turn_mode == "art"  # flip 방식은 같은 헤엄 그림만 쓰므로 섞을 필요가 없다
        if turning != self._was_turning and art:
            self._xfade_from = self._last_single
            self._xfade_to = None  # 섞는 동안 도착 그림은 고정한다 (도중에 바뀌면 그림이 튄다)
            self._xfade_left = settings.STATE_XFADE_SECONDS
            if not turning:  # turn 이 끝나면 turn_08 을 반전한 모습과 비슷한 꼬리 자세에서 헤엄을 시작
                self.phase = self.timeline.phase_for(self.lib.exit_frame, forward=True)
                self._rate = 1.0 / self.tail_period
        self._was_turning = turning

        if turning and art:
            spec = self._turn_spec(beh, mirror)
        elif turning:
            spec = self._flip_spec(dt, beh, mirror)
        else:
            spec = self._swim_spec(dt, beh, mirror)

        # 상태 전환 크로스페이드
        if self._xfade_left > 0 and self._xfade_from is not None:
            self._xfade_left = max(0.0, self._xfade_left - dt)
            k = 1.0 - self._xfade_left / settings.STATE_XFADE_SECONDS
            t = round(k * BLEND_STEPS) / BLEND_STEPS
            if self._xfade_to is None:
                self._xfade_to = spec.a if spec.t < 0.5 or spec.b is None else spec.b
            target = self._xfade_to
            if t < 1.0 and target != self._xfade_from:
                spec = FrameSpec(self._xfade_from, target, t, spec.blink, wide_mask=True)
            else:
                spec = FrameSpec(target, None, 0.0, spec.blink, wide_mask=spec.wide_mask)

        self._last_single = spec.a if spec.b is None or spec.t < 0.5 else spec.b
        self.current = spec
        return spec

    def _flip_spec(self, dt: float, beh, mirror: int) -> FrameSpec:
        """flip 방식 방향 전환: 헤엄 그림(꼬리는 계속 흔들림)을 가로로 눌러 납작하게 만들었다가 반대 방향으로 편다.

        몸이 납작할 때(진행도 50%)에 좌우 반전을 바꾸므로 그림이 튀지 않는다. 다른 그림을 섞지 않아서 모양이 흔들리지 않는다.
        눈꺼풀은 눌린 그림에 맞춰 그릴 수 없으므로 이 동안은 깜빡이지 않는다.
        """
        prog = min(1.0, max(0.0, beh.turn_progress))
        flipped = prog >= 0.5
        sp = self._swim_spec(dt, beh, -mirror if flipped else mirror)
        squash = max(settings.TURN_FLIP_MIN_SCALE, abs(math.cos(math.pi * prog)))
        return FrameSpec(sp.a, sp.b, sp.t, 0.0, wide_mask=False, squash=round(squash, 3))

    def _turn_spec(self, beh, mirror: int) -> FrameSpec:
        n = len(self.lib.images[GROUP_TURN])
        prog = min(1.0, max(0.0, beh.turn_progress))
        active = 1.0 - settings.TURN_HOLD_LAST
        u = min(n - 1.0, prog / active * (n - 1)) if active > 0 else n - 1.0
        i = min(int(u), n - 1)
        a: Key = (GROUP_TURN, i, mirror)
        segs = settings.TURN_CROSSFADE_SEGMENTS
        if i < n - 1 and i < len(segs) and segs[i]:
            t = round((u - i) * BLEND_STEPS) / BLEND_STEPS
            if t > 0:
                return FrameSpec(a, (GROUP_TURN, i + 1, mirror), t, 0.0, wide_mask=True)
        return FrameSpec(a, None, 0.0, 0.0, wide_mask=True)

    def _swim_spec(self, dt: float, beh, mirror: int) -> FrameSpec:
        idle_like = not beh.is_moving and beh.effective_mode == "idle"
        period = self.tail_period * (settings.IDLE_TAIL_SLOWDOWN if idle_like else 1.0)
        target_rate = 1.0 / period
        k = min(1.0, dt / settings.TAIL_RATE_SMOOTHING)
        self._rate += (target_rate - self._rate) * k  # 꼬리 속도가 바뀔 때도 부드럽게
        if self._xfade_left <= 0:  # turn → 헤엄으로 섞는 동안에는 꼬리 자세를 고정
            self.phase = (self.phase + dt * self._rate) % 1.0

        blink = self._update_blink(dt, allow=True)

        if settings.USE_LEGACY_IDLE_ASSETS and idle_like and self.lib.images[GROUP_IDLE]:
            n_idle = len(self.lib.images[GROUP_IDLE])
            if blink > 0 and self.lib.images[GROUP_BLINK]:
                bi = min(len(self.lib.images[GROUP_BLINK]) - 1, 0 if blink < 1 else 1)
                return FrameSpec((GROUP_BLINK, bi, mirror))
            return FrameSpec((GROUP_IDLE, int(self._clock / settings.IDLE_FRAME_INTERVAL) % n_idle, mirror))

        ia, ib, t = self.timeline.sample(self.phase)
        a: Key = (GROUP_SWIM, ia, mirror)
        if t > 0 and ib != ia:
            return FrameSpec(a, (GROUP_SWIM, ib, mirror), t, blink)
        return FrameSpec(a, None, 0.0, blink)

    def _update_blink(self, dt: float, allow: bool) -> float:
        """눈 깜빡임 진행. 반환: 눈 감김 정도(0/0.5/1)."""
        if not (self.blink_enabled and allow):
            self._blink_step = -1
            return 0.0
        self._since_blink += dt
        seq = settings.BLINK_SEQUENCE
        if self._blink_step >= 0:
            self._blink_left -= dt
            if self._blink_left <= 0:
                self._blink_step += 1
                if self._blink_step >= len(seq):
                    self._blink_step = -1
                    self._since_blink = 0.0
                    self._next_blink = settings.BLINK_TEST_INTERVAL if self.force_blink_loop else self._roll_blink()
                else:
                    self._blink_left = seq[self._blink_step][1]
        else:
            self._next_blink -= dt
            if self._next_blink <= 0 and (self._since_blink >= settings.BLINK_MIN_GAP or self.force_blink_loop):
                self._blink_step = 0
                self._blink_left = seq[0][1]
        return seq[self._blink_step][0] if self._blink_step >= 0 else 0.0

    @property
    def is_blinking(self) -> bool:
        return self._blink_step >= 0
