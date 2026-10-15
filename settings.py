"""부캉이 전역 설정.

모든 "숫자/문구/경로"는 이 파일에 모아 둡니다.
움직임이 마음에 들지 않으면 대부분 여기 숫자만 바꾸면 됩니다.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "Bukangi"
APP_TITLE = "부캉이"

# ---------------------------------------------------------------------------
# 경로 처리 (cwd에 의존하지 않음 / PyInstaller 대응)
# ---------------------------------------------------------------------------


def is_frozen() -> bool:
    """PyInstaller로 만든 exe에서 실행 중인지."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """리소스가 들어 있는 기준 폴더.

    - 개발 중: 이 파일이 있는 폴더
    - PyInstaller: onefile이면 임시 해제 폴더(_MEIPASS), onedir이면 _internal 폴더
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    """번들 리소스 경로를 돌려준다. 예: resource_path('assets')."""
    return bundle_root().joinpath(*parts)


def _find_assets_dir() -> Path:
    """에셋 폴더 찾기.

    exe 바로 옆에 `assets` 폴더가 있으면 그것을 우선한다.
    (exe를 다시 빌드하지 않아도 사용자가 PNG를 바꿔 끼울 수 있게 하기 위함)
    """
    if is_frozen():
        beside_exe = Path(sys.executable).resolve().parent / "assets"
        if beside_exe.is_dir():
            return beside_exe
    return resource_path("assets")


ASSETS_DIR: Path = _find_assets_dir()

# 필수 에셋: 폴더 이름 -> 파일 목록. (파일 이름 순서 = 번호 순서. 정렬이 흔들리지 않게 명시한다.)
SWIM_FRAME_COUNT = 10
TURN_FRAME_COUNT = 8
ASSET_GROUPS: dict[str, list[str]] = {
    "swim_right": [f"frame_{i:02d}.png" for i in range(1, SWIM_FRAME_COUNT + 1)],
    "turn_right_to_left": [f"turn_{i:02d}.png" for i in range(1, TURN_FRAME_COUNT + 1)],
}

# 예전(이전 그림체) idle/blink PNG. 새 swim/turn 과 그림체가 달라서 기본은 사용하지 않는다.
# True 로 바꾸면 assets/idle, assets/blink 가 있을 때 예전 방식(PNG)으로 idle/눈 깜빡임을 보여준다.
USE_LEGACY_IDLE_ASSETS = False
LEGACY_ASSET_GROUPS: dict[str, list[str]] = {
    "idle": ["idle_01.png", "idle_02.png"],
    "blink": ["blink_01.png", "blink_02.png"],
}

# 알파값이 이 값보다 커야 "캐릭터 픽셀"로 취급한다 (경계 계산/검사용)
ALPHA_THRESHOLD = 10
# 공통 크롭 영역에 더해 주는 여백(원본 픽셀 단위)
CROP_PADDING = 4

# ---------------------------------------------------------------------------
# 프레임 정렬 (원본 PNG 는 수정하지 않고, 불러올 때 코드에서 위치만 보정한다)
# ---------------------------------------------------------------------------
# 값은 (dx, dy) = "그림을 이동시키는 양"(원본 픽셀 단위, +x 오른쪽 / +y 아래쪽).
# tools/analyze_frames.py 로 머리 위치를 비교해서 구한 값이다.
# 순서는 파일 번호 순서(0번째 = frame_01).
SWIM_FRAME_OFFSETS: tuple[tuple[int, int], ...] = (
    (0, 0),    # frame_01 (기준)
    (-1, 0),   # frame_02
    (-2, 2),   # frame_03
    (-1, 2),   # frame_04
    (0, 1),    # frame_05
    (0, -4),   # frame_06
    (0, 0),    # frame_07
    (0, 1),    # frame_08
    (0, -17),  # frame_09  (몸 전체가 약 17px 아래에 그려져 있어서 올려 준다)
    (1, 0),    # frame_10
)
# turn_01~08. 05~08 은 왼쪽을 보는 그림이라, 좌우 반전한 swim 프레임과 머리 위치가 맞도록 보정한다.
# 02~04 는 01 과 05 의 보정값을 직선으로 이어서 중간 프레임이 갑자기 튀지 않게 한다.
TURN_FRAME_OFFSETS: tuple[tuple[int, int], ...] = (
    (3, -1),     # turn_01  (swim 과 거의 일치)
    (-5, -13),   # turn_02
    (-14, -24),  # turn_03
    (-22, -36),  # turn_04  (몸이 가장 크게 휘는 프레임)
    (-30, -48),  # turn_05
    (-20, -40),  # turn_06
    (-26, -42),  # turn_07
    (-28, -42),  # turn_08
)

# ---------------------------------------------------------------------------
# 헤엄 애니메이션 (꼬리 왕복)
# ---------------------------------------------------------------------------

# 재생 방식:
#   "smooth"   : 꼬리 자세가 가장 비슷한 순서(SWIM_SMOOTH_PATH)로 왕복 + 프레임 사이를 부드럽게 섞기 (권장)
#   "pingpong" : 1→2→…→10→9→…→2 (파일 번호 순서 왕복. 비교/테스트용)
#   "file"     : 1→2→…→10 반복 (원래 순서. 비교/테스트용)
SWIM_ORDER_MODE = "smooth"

# "smooth" 모드의 왕복 경로. 파일 번호(1부터)이며 양 끝에서 되돌아온다.
# 분석 결과: frame_02 는 다른 프레임과 꼬리 모양 차이가 너무 커서(57~76%) 기본 경로에서 뺐다.
# 넣어 보고 싶으면 맨 앞에 2 를 추가:  (2, 8, 1, 10, 7, 5, 4, 6, 3, 9)
SWIM_SMOOTH_PATH: tuple[int, ...] = (8, 1, 10, 7, 5, 4, 6, 3, 9)

# ---- 꼬리 파도 (코드로 꼬리를 휘게 하기) ----
# 새 swim PNG 10장은 프레임마다 몸 길이/모양/명암이 조금씩 달라서, 섞어 재생하면 깜빡이고 크기가 변해 보이고
# 꼬리는 "휘는" 게 아니라 "번졌다 선명해지는" 것처럼 보인다. 그래서 PNG 한 장(SWIM_BASE_FRAME)만 기준으로 삼고,
# 몸 뒤쪽을 코드로 사인파처럼 휘게 한 프레임을 TAIL_WAVE_FRAMES 장 만들어 재생한다. (PNG 원본은 수정하지 않는다)
# False 로 하면 예전처럼 10장을 SWIM_SMOOTH_PATH 순서로 섞어 재생한다.
SWIM_PROCEDURAL = True
SWIM_BASE_FRAME = 1  # 기준 프레임 번호(파일 번호, 1부터). 이 프레임의 머리/몸/지느러미가 그대로 쓰인다
TAIL_WAVE_FRAMES = 16  # 꼬리 한 주기를 나눈 프레임 수 (많을수록 부드럽지만 메모리 증가)
TAIL_WAVE_AMPLITUDE = 0.0  # 꼬리 끝이 위아래로 휘는 최대 폭 (몸 길이 대비). 상어는 위아래로 흔들리지 않게 0. 쓰려면 0.01~0.03
TAIL_DEPTH_SCALE = 0.0  # 꼬리가 화면 쪽으로 오면 커지고(+) 멀어지면 작아지는(-) 정도 (꼬리 끝 기준 비율). 0 이면 끔
# 꼬리 끝이 좌우(몸 앞뒤 방향)로 흔들리는 폭 (몸 길이 대비). 원본 그림 기준으로
TAIL_SWAY_OUT = 0.06  # 바깥(몸에서 멀어지는 쪽, 더 길게 펴짐)으로 가는 최대 폭. 클수록 꼬리가 펄럭이듯 바깥으로 크게 흔들린다
TAIL_SWAY_IN = 0.02  # 안쪽(몸 쪽으로 오므라듦)으로 가는 최대 폭. 작을수록 "안쪽으로 휜 것처럼" 보이는 느낌이 줄어든다
TAIL_WAVE_REGION = 0.55  # 꼬리 쪽에서 몇 %까지(몸 길이 대비)를 휘게 할지. 앞쪽 몸/지느러미는 고정
TAIL_WAVE_POWER = 2.2  # 클수록 꼬리 끝만 휘고 몸 중간은 덜 휜다
TAIL_WAVE_LAG = 1.1  # 꼬리 끝이 몸통보다 늦게 따라오는 정도(라디안). 0 이면 뻣뻣한 막대처럼 흔들림
TAIL_WAVE_STRIP = 2  # 세로 띠 한 장의 폭(원본 픽셀). 작을수록 매끈하지만 만드는 시간이 늘어난다

# 구간별 재생 시간 가중치(길이 = 경로 길이 - 1). None 이면 모두 같은 시간.
# 예: 양 끝 구간을 더 천천히 → (1.4, 1, 1, 1, 1, 1, 1, 1.4)
SWIM_SEGMENT_WEIGHTS: tuple[float, ...] | None = None
# 프레임 사이를 부드럽게 섞기(크로스페이드). False 이면 프레임이 뚝뚝 바뀐다.
SWIM_CROSSFADE = True
# 왕복의 양 끝에서 천천히 멈췄다 돌아오는 정도 (0 = 일정한 속도, 1 = 사인파처럼 끝에서 완전히 느려짐)
SWIM_EASE_STRENGTH = 0.6
# 가만히 있을(idle) 때는 꼬리를 이 배수만큼 더 천천히 저어서 떠 있는 느낌을 낸다
IDLE_TAIL_SLOWDOWN = 2.0
# 꼬리 속도가 바뀔 때 부드럽게 따라가는 정도(초). 클수록 천천히 변한다.
TAIL_RATE_SMOOTHING = 0.6

# idle 이미지(예전 PNG 사용 시) 번갈아 보여주는 간격(초)
IDLE_FRAME_INTERVAL = 0.9

# ---------------------------------------------------------------------------
# 방향 전환(turn) 애니메이션
# ---------------------------------------------------------------------------

# turn 이 끝난 직후 swim 에서 시작할 프레임(파일 번호). turn_08 을 반전한 모습과 가장 비슷한 프레임.
TURN_EXIT_SWIM_FRAME = 7
# turn 전체 재생 시간(초). 프레임 8장 → 장당 약 0.22초.
# turn 그림은 몸을 틀며 카메라 쪽으로 다가오는 모습이라 프레임마다 상어 크기(면적)가 다르다 (turn_04 는 헤엄 때의 1.6배).
# True 면 프레임마다 면적이 헤엄 그림과 같아지게 코드에서 크기를 맞춘다 (PNG 원본은 수정 안 함).
TURN_NORMALIZE_SIZE = True
TURN_SIZE_STRENGTH = 1.0  # 1.0 = 완전히 같은 크기로 / 0.5 = 절반만 보정 / 0 = 끔
TURN_SIZE_SCALE_RANGE = (0.6, 1.25)  # 한 프레임을 이 배율 범위 밖으로는 줄이거나 키우지 않는다
TURN_HEAD_RIGHT_FRAMES = 4  # turn 앞쪽 N장은 머리가 오른쪽, 나머지는 왼쪽 (크기 보정 때 머리 쪽 끝을 고정하는 데 사용)
# turn 프레임의 위치를 자동으로 맞춘다: 몸 중심 높이는 헤엄 그림과 같게 고정하고, 가로는 "헤엄 → 좌우 반전한 헤엄"
# 위치로 부드럽게 미끄러지게 한다. False 면 아래 TURN_FRAME_OFFSETS(손으로 정한 값)를 쓴다.
TURN_AUTO_ALIGN = True
TURN_ALIGN_EASE = True  # 가로 이동을 처음/끝에서 천천히 (smoothstep)
# turn 이 끝난 뒤 이어받을 꼬리 프레임을 turn_08 과 가장 비슷한 것으로 자동 선택 (꼬리가 겹쳐 보이는 것을 줄인다)
TURN_AUTO_EXIT_FRAME = True
TURN_DURATION = 1.8
# 방향 전환 방식: "flip" = 헤엄 그림 그대로 가로로 납작하게 눌렀다가 반대로 펴기 (그림이 달라서 생기는 흔들림이 없다),
#               "art"  = turn PNG 8장 재생 (아래 TURN_* 설정들은 이 방식에서만 쓰인다)
TURN_STYLE = "art"
TURN_FLIP_DURATION = 0.5  # flip 방식 전체 시간(초). 이동 속도가 줄어드는 시간도 이만큼
TURN_FLIP_MIN_SCALE = 0.04  # 가장 납작해졌을 때의 가로 배율 (0 이면 사라지는 순간이 생겨서 조금 남겨둔다)
# 마지막 프레임(turn_08)을 보여주고 있는 비율(0~1)
TURN_HOLD_LAST = 0.12
# turn 프레임 사이 섞기 허용 여부 (7칸: 01→02, 02→03 … 07→08).
# 앞쪽(몸이 크게 휘는 구간)은 모양 차이가 너무 커서 섞으면 상어가 두 마리처럼 겹쳐 보이므로 끈다.
TURN_CROSSFADE_SEGMENTS: tuple[bool, ...] = (False, False, False, False, True, True, True)
# swim ↔ turn 으로 바뀔 때 두 그림을 섞는 시간(초)
STATE_XFADE_SECONDS = 0.25

# 화면 끝에서 turn 을 시작하는 거리(논리 px, 창 가장자리 ~ 화면 가장자리). 범위 안에서 매번 랜덤.
TURN_TRIGGER_RANGE = (80.0, 120.0)
# 화면 끝에서 이 거리 안으로 들어오면 서서히 느려지기 시작
TURN_SLOW_ZONE = 260.0
# 느려지는 구간에서 turn 시작 지점까지 줄어드는 최소 속도 비율
TURN_MIN_SPEED_FACTOR = 0.4
# turn 하는 동안 앞으로 흘러가는 속도 비율 (거의 제자리에서 도는 느낌)
TURN_DRIFT_FACTOR = 0.08

# ---------------------------------------------------------------------------
# 눈 깜빡임 (새 그림체용: 코드로 눈꺼풀을 덮어 그린다)
# ---------------------------------------------------------------------------

BLINK_ENABLED = True
# 눈 위치/크기: swim 기준 원본 픽셀 좌표 (frame_01 의 눈)
EYE_POS_SRC = (1121, 608)
EYE_RADIUS_SRC = 17
# 깜빡임 순서: (감은 정도 0.5=반쯤/1=완전히, 유지 시간[초])
BLINK_SEQUENCE: tuple[tuple[float, float], ...] = ((0.5, 0.08), (1.0, 0.12), (0.5, 0.09))
# 깜빡이는 간격(초) 범위. 너무 자주 깜빡이지 않도록 넉넉하게.
BLINK_INTERVAL_RANGE = (3.0, 7.0)
# 직전 깜빡임 이후 최소 간격(초)
BLINK_MIN_GAP = 4.0
# 테스트 모드 "눈 깜빡이는 모습" 에서의 반복 간격(초)
BLINK_TEST_INTERVAL = 0.9

# ---------------------------------------------------------------------------
# 크기 / 속도 프리셋
# ---------------------------------------------------------------------------

# 논리(DPI 보정 전) 픽셀 기준 가로 크기
SIZE_PRESETS: dict[str, int] = {"small": 200, "normal": 300, "large": 440}
SIZE_LABELS: dict[str, str] = {"small": "작게", "normal": "보통", "large": "크게"}


@dataclass(frozen=True)
class SpeedPreset:
    pixels_per_sec: float  # 화면 이동 속도(논리 px/초)
    tail_period: float  # 꼬리 한 번 왕복(끝→반대 끝→처음)에 걸리는 시간(초). 이동 속도와 별개!


SPEED_PRESETS: dict[str, SpeedPreset] = {
    "slow": SpeedPreset(30, 4.0),
    "normal": SpeedPreset(50, 3.0),
    "fast": SpeedPreset(90, 2.0),
}
SPEED_LABELS: dict[str, str] = {"slow": "느리게", "normal": "보통", "fast": "빠르게"}

DEFAULT_SIZE = "normal"
DEFAULT_SPEED = "normal"

# ---------------------------------------------------------------------------
# 이동 / 행동 로직
# ---------------------------------------------------------------------------

# 메인 루프 간격(ms). 33ms = 약 30fps (느린 유영에는 충분하고 CPU 를 아낀다). 더 부드럽게 → 25 또는 16.
TICK_MS = 33
# dt 상한(초). 창이 멈췄다 풀릴 때 순간이동하지 않도록 제한.
MAX_DT = 0.08

SWIM_DURATION_RANGE = (14.0, 30.0)  # 한 번 헤엄치는 시간(초)
IDLE_DURATION_RANGE = (3.0, 6.0)  # 멈춰 있는 시간(초)
KEEP_DIRECTION_CHANCE = 0.6  # idle 후 같은 방향으로 다시 출발할 확률 (아니면 turn)
RANDOM_TURN_INTERVAL = (10.0, 22.0)  # 헤엄 중 가끔 방향을 바꿔 보는 주기(초)
RANDOM_TURN_CHANCE = 0.35  # 위 주기가 왔을 때 실제로 turn 할 확률

ACCEL_FACTOR = 0.6  # 가속도 = 속도 * 이 값 (속도 도달까지 약 1.7초 → 급가속/급감속 없음)
VERTICAL_RANGE_FACTOR = 0.10  # 위아래 흐름 속도 = 속도 * 이 값 이내 (아주 미세하게)
VERTICAL_RETARGET_RANGE = (3.0, 7.0)  # 위아래 방향을 새로 정하는 주기(초)
VERTICAL_EDGE_MARGIN = 40  # 위/아래 가장자리에서 이만큼 가까워지면 안쪽으로 유도
SPEED_WOBBLE = 0.08  # 속도가 살짝 출렁이는 비율(직선적이지 않게)
MOVING_SPEED_THRESHOLD = 8.0  # 이보다 느리면 "멈춤"으로 본다 (idle 꼬리 속도)

# 둥실둥실 떠 있는 느낌 (창 가로 크기 대비 비율)
BOB_AMPLITUDE_SWIM = 0.0  # 헤엄 중에는 몸이 위아래로 둥실거리지 않는다 (좌우 꼬리 흔들림만)
BOB_AMPLITUDE_IDLE = 0.010
BOB_FREQUENCY = 0.3  # Hz
BOB_AMP_SMOOTHING = 1.0  # 둥실거림 폭이 바뀔 때 따라가는 시간(초). 클수록 천천히 변한다

# 드래그해서 화면 밖에 놔도 최소 이만큼은 화면에 남긴다(논리 px)
MIN_VISIBLE_PX = 60

# ---------------------------------------------------------------------------
# 말풍선
# ---------------------------------------------------------------------------

SPEECH_LINES: tuple[str, ...] = (
    "부캉!",
    "헤엄치는 중…",
    "오늘도 바다 대신 바탕화면",
    "슝~",
    "여기가 내 바다야",
    "잠깐 쉬는 중…",
)
SPEECH_DURATION_MS = 2300
SPEECH_FONT_FAMILY = "Malgun Gothic"
SPEECH_FONT_POINT_SIZE = 10

# ---------------------------------------------------------------------------
# 사용자 설정 저장 (속도/크기/항상 위)
# ---------------------------------------------------------------------------


class UserPrefs:
    """QSettings(레지스트리)에 속도/크기/항상 위 값을 저장한다. 실패해도 앱은 계속 동작."""

    def __init__(self, persist: bool = True) -> None:
        self.speed = DEFAULT_SPEED
        self.size = DEFAULT_SIZE
        self.always_on_top = True
        self._qs = None
        if persist:
            try:
                from PySide6.QtCore import QSettings

                self._qs = QSettings(APP_NAME, APP_NAME)
                speed = str(self._qs.value("speed", DEFAULT_SPEED))
                size = str(self._qs.value("size", DEFAULT_SIZE))
                top = self._qs.value("always_on_top", True)
                if speed in SPEED_PRESETS:
                    self.speed = speed
                if size in SIZE_PRESETS:
                    self.size = size
                self.always_on_top = str(top).lower() in ("true", "1")
            except Exception:  # noqa: BLE001 - 설정 로딩 실패는 무시
                self._qs = None

    def save(self) -> None:
        if self._qs is None:
            return
        try:
            self._qs.setValue("speed", self.speed)
            self._qs.setValue("size", self.size)
            self._qs.setValue("always_on_top", self.always_on_top)
            self._qs.sync()
        except Exception:  # noqa: BLE001
            pass
