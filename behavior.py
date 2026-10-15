"""부캉이의 이동/상태 로직 (화면 위젯과 무관한 순수 로직).

상태 (PetState) - 정확히 하나만 가진다:
    swimming_right        오른쪽을 보고 헤엄
    swimming_left         왼쪽을 보고 헤엄 (swim 이미지를 좌우 반전해서 표시)
    turning_right_to_left 오른쪽 → 왼쪽 방향 전환 (turn 이미지 그대로)
    turning_left_to_right 왼쪽 → 오른쪽 방향 전환 (turn 이미지를 좌우 반전)

방향 전환 흐름
    화면 끝에 가까워짐 → 서서히 감속 → 트리거 거리 안으로 들어오면 turn 시작
    → turn 동안은 거의 제자리(조금만 흘러감) → turn 시간이 끝나면 상태/방향을 한 번에 바꿈
    → 반대 방향으로 천천히 가속
방향(facing)은 "상태"로만 정해진다. 속도 부호와 무관하므로 방향이 바뀌는 순간 한 프레임 뒤집힘이 생기지 않는다.

시간 기반(dt)으로 움직여서 PC 성능/타이머 오차와 상관없이 같은 속도를 유지한다.
"""
from __future__ import annotations

import math
import random
from enum import Enum
from typing import Optional

import settings

# (left, top, right, bottom): 창의 "왼쪽 위 꼭짓점"이 움직일 수 있는 범위
Bounds = tuple[float, float, float, float]


class PetState(str, Enum):
    SWIMMING_RIGHT = "swimming_right"
    SWIMMING_LEFT = "swimming_left"
    TURNING_RIGHT_TO_LEFT = "turning_right_to_left"
    TURNING_LEFT_TO_RIGHT = "turning_left_to_right"


_TURNING = (PetState.TURNING_RIGHT_TO_LEFT, PetState.TURNING_LEFT_TO_RIGHT)


def _approach(value: float, target: float, max_delta: float) -> float:
    """value 를 target 쪽으로 최대 max_delta 만큼만 이동."""
    if value < target:
        return min(value + max_delta, target)
    return max(value - max_delta, target)


class PetBehavior:
    def __init__(self, rng: Optional[random.Random] = None, use_turn: bool = True,
                 turn_duration: Optional[float] = None) -> None:
        self.rng = rng or random.Random()
        self._turn_duration_cfg = settings.TURN_DURATION if turn_duration is None else float(turn_duration)
        self.use_turn = use_turn  # False 면 turn 에셋이 없는 경우: 끝에서 방향만 바로 바꾼다
        # 위치(창 왼쪽 위 좌표, 논리 px)와 속도(px/초)
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.state = PetState.SWIMMING_RIGHT
        self.turn_time = 0.0  # 현재 turn 이 시작된 후 경과 시간(초)
        self.turn_duration = self._turn_duration_cfg
        self.mode = "swim"  # 자동 모드에서의 활동: 'swim' | 'idle'
        self.speed = settings.SPEED_PRESETS[settings.DEFAULT_SPEED].pixels_per_sec

        self.paused = False
        self._dragging = False
        # 테스트용 고정 상태: None(자동) | 'swim' | 'idle' | 'blink'
        self.forced: Optional[str] = None

        self.clock = 0.0  # 누적 시간(출렁임/둥실 계산용)
        self._mode_left = self._roll(settings.SWIM_DURATION_RANGE)
        self._turn_left = self._roll(settings.RANDOM_TURN_INTERVAL)
        self._trigger_px = self._roll(settings.TURN_TRIGGER_RANGE)
        self._vy_left = 0.0
        self._vy_target = 0.0
        self.bob = 0.0  # -1..1 둥실둥실 값. 창이 실제 오프셋으로 환산한다.
        self._bob_amp = settings.BOB_AMPLITUDE_SWIM  # 현재 둥실거림 폭 (목표값을 천천히 따라간다)

    # -- 유틸 ---------------------------------------------------------------

    def _roll(self, rng_range: tuple[float, float]) -> float:
        return self.rng.uniform(*rng_range)

    # -- 상태 조회 ------------------------------------------------------------

    @property
    def is_turning(self) -> bool:
        return self.state in _TURNING

    @property
    def turn_progress(self) -> float:
        """turn 진행도 0~1 (turn 중이 아니면 0)."""
        if not self.is_turning or self.turn_duration <= 0:
            return 0.0
        return min(1.0, self.turn_time / self.turn_duration)

    @property
    def direction(self) -> int:
        """지금 향해 가는 방향 (+1 오른쪽 / -1 왼쪽). turn 중에는 turn 을 시작한 방향."""
        return 1 if self.state in (PetState.SWIMMING_RIGHT, PetState.TURNING_RIGHT_TO_LEFT) else -1

    @property
    def facing(self) -> int:
        """그림을 어느 쪽으로 그릴지 (+1 원본 / -1 좌우 반전).

        swimming_right: 원본, swimming_left: 반전,
        turning_right_to_left: 원본 turn 이미지, turning_left_to_right: 반전 turn 이미지.
        """
        return self.direction

    @property
    def dragging(self) -> bool:
        return self._dragging

    @dragging.setter
    def dragging(self, value: bool) -> None:
        # 드래그는 turn 을 끊어도 되는 유일한 예외 상황: 이 경우 turn 을 즉시 끝낸 상태(도착 방향)로 만든다
        if value and self.is_turning:
            self._finish_turn()
        self._dragging = bool(value)

    @property
    def effective_mode(self) -> str:
        """지금 실제로 적용되는 활동('swim' | 'idle')."""
        if self._dragging or self.paused:
            return "idle"
        if self.forced == "swim":
            return "swim"
        if self.forced in ("idle", "blink"):
            return "idle"
        return self.mode

    @property
    def is_moving(self) -> bool:
        """화면 위를 실제로 이동 중인가."""
        return math.hypot(self.vx, self.vy) > settings.MOVING_SPEED_THRESHOLD

    @property
    def bob_amplitude_ratio(self) -> float:
        """둥실거림 폭(창 너비 대비). 상태가 바뀔 때 갑자기 달라지지 않도록 update() 에서 천천히 따라간다."""
        return self._bob_amp

    def _bob_target(self) -> float:
        # turn 중에도 헤엄 때와 같은 폭을 유지한다 (몸이 흔들리지 않게)
        return settings.BOB_AMPLITUDE_IDLE if self.effective_mode == "idle" else settings.BOB_AMPLITUDE_SWIM

    # -- 외부 제어 ------------------------------------------------------------

    def set_position(self, x: float, y: float) -> None:
        self.x, self.y = float(x), float(y)

    def set_direction(self, direction: int, instant: bool = False) -> None:
        """turn 없이 즉시 그 방향을 보게 한다 (테스트/초기화용)."""
        self.turn_time = 0.0
        self.state = PetState.SWIMMING_RIGHT if direction >= 0 else PetState.SWIMMING_LEFT
        if instant:
            self.vx = self.direction * max(abs(self.vx), self.speed * 0.5)

    def flip_direction(self, instant: bool = False) -> None:
        """방향을 반대로. instant=True 면 turn 없이 즉시(테스트용), 아니면 turn 애니메이션으로."""
        if instant:
            self.set_direction(-self.direction, True)
        else:
            self.start_turn()

    def start_turn(self) -> bool:
        """현재 헤엄 방향의 반대로 방향 전환을 시작한다. 이미 turn 중이면 무시(중간에 끊지 않는다)."""
        if self.is_turning:
            return False
        if not self.use_turn:  # turn 에셋이 없으면 바로 반대 방향
            self.state = PetState.SWIMMING_LEFT if self.state == PetState.SWIMMING_RIGHT else PetState.SWIMMING_RIGHT
            self._trigger_px = self._roll(settings.TURN_TRIGGER_RANGE)
            return True
        self.state = (
            PetState.TURNING_RIGHT_TO_LEFT if self.state == PetState.SWIMMING_RIGHT else PetState.TURNING_LEFT_TO_RIGHT
        )
        self.turn_time = 0.0
        self.turn_duration = self._turn_duration_cfg
        return True

    def force_turn(self, right_to_left: bool) -> None:
        """테스트: 시작 방향을 맞춘 뒤 지정한 turn 을 실행한다."""
        if self.is_turning:
            self._finish_turn()
        self.state = PetState.SWIMMING_RIGHT if right_to_left else PetState.SWIMMING_LEFT
        self.start_turn()

    def set_forced(self, forced: Optional[str]) -> None:
        self.forced = forced
        if forced is None:
            self.mode = "swim"
            self._mode_left = self._roll(settings.SWIM_DURATION_RANGE)

    def _finish_turn(self) -> None:
        """turn 종료: 상태(=방향)를 한 번에 바꾸고 반대 방향 헤엄으로 전환."""
        if self.state == PetState.TURNING_RIGHT_TO_LEFT:
            self.state = PetState.SWIMMING_LEFT
        elif self.state == PetState.TURNING_LEFT_TO_RIGHT:
            self.state = PetState.SWIMMING_RIGHT
        self.turn_time = 0.0
        self._trigger_px = self._roll(settings.TURN_TRIGGER_RANGE)
        self._turn_left = self._roll(settings.RANDOM_TURN_INTERVAL)

    # -- 한 틱 갱신 -----------------------------------------------------------

    def _edge_distance(self, bounds: Bounds) -> float:
        """가려는 방향의 화면 끝까지 남은 거리(논리 px)."""
        left, _top, right, _bottom = bounds
        return (right - self.x) if self.direction > 0 else (self.x - left)

    def update(self, dt: float, bounds: Bounds) -> None:
        left, top, right, bottom = bounds
        right = max(left, right)
        bottom = max(top, bottom)
        bounds = (left, top, right, bottom)
        dt = max(0.0, min(dt, settings.MAX_DT))
        self.clock += dt

        # 드래그 중에는 사용자가 위치를 정한다. 속도만 0으로.
        if self._dragging:
            self.vx = self.vy = 0.0
            return

        # 1) turn 진행 / 자동 활동 타이머
        if self.is_turning:
            self.turn_time += dt
            if self.turn_time >= self.turn_duration:
                self._finish_turn()
        else:
            self._update_mode_timers(dt)

        mode = self.effective_mode
        turning = self.is_turning

        # 2) 가로 목표 속도
        if turning:
            # 거의 제자리에서 돈다 (회전하는 느낌)
            target_vx = self.direction * self.speed * settings.TURN_DRIFT_FACTOR
        elif mode == "swim":
            dist = self._edge_distance(bounds)
            trigger = self._trigger_px
            slow = max(settings.TURN_SLOW_ZONE, trigger + 1.0)
            if dist < slow:  # 화면 끝에 가까워지면 서서히 느려진다
                z = min(1.0, max(0.0, (dist - trigger) / (slow - trigger)))
                factor = settings.TURN_MIN_SPEED_FACTOR + (1.0 - settings.TURN_MIN_SPEED_FACTOR) * z
            else:
                factor = 1.0
            wobble = 1.0 + settings.SPEED_WOBBLE * math.sin(self.clock * 0.9)
            target_vx = self.direction * self.speed * wobble * factor
            if dist <= trigger:  # 트리거 거리 안으로 들어왔다 → turn 시작
                self.start_turn()
                if self.is_turning:
                    target_vx = self.direction * self.speed * settings.TURN_DRIFT_FACTOR
        else:
            target_vx = 0.0
        accel = max(20.0, self.speed * settings.ACCEL_FACTOR)
        self.vx = _approach(self.vx, target_vx, accel * dt)

        # 3) 세로 목표 속도 (아주 미세하게 천천히 흘러감)
        if mode == "swim" and not turning:
            self._vy_left -= dt
            if self._vy_left <= 0:
                lim = self.speed * settings.VERTICAL_RANGE_FACTOR
                self._vy_target = self.rng.uniform(-lim, lim)
                self._vy_left = self._roll(settings.VERTICAL_RETARGET_RANGE)
            margin = settings.VERTICAL_EDGE_MARGIN  # 위/아래 가장자리에 가까우면 안쪽으로 유도
            if self.y < top + margin:
                self._vy_target = abs(self._vy_target)
            elif self.y > bottom - margin:
                self._vy_target = -abs(self._vy_target)
            target_vy = self._vy_target
        else:
            target_vy = 0.0
        self.vy = _approach(self.vy, target_vy, accel * 0.25 * dt)

        # 4) 위치 적분 + 화면 안으로 제한 (안전장치. 정상 동작에서는 turn 이 먼저 일어나 닿지 않는다)
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.x <= left:
            self.x, self.vx = left, max(self.vx, 0.0)
        elif self.x >= right:
            self.x, self.vx = right, min(self.vx, 0.0)
        self.y = min(max(self.y, top), bottom)

        self.bob = math.sin(self.clock * 2 * math.pi * settings.BOB_FREQUENCY)
        k = min(1.0, dt / max(1e-3, settings.BOB_AMP_SMOOTHING))
        self._bob_amp += (self._bob_target() - self._bob_amp) * k

    def _update_mode_timers(self, dt: float) -> None:
        """자동 모드에서만: 헤엄 ↔ idle 전환, 가끔 방향 바꾸기(turn)."""
        if self.paused or self.forced is not None:
            return
        self._mode_left -= dt
        if self.mode == "swim":
            self._turn_left -= dt
            if self._turn_left <= 0:
                self._turn_left = self._roll(settings.RANDOM_TURN_INTERVAL)
                if self.rng.random() < settings.RANDOM_TURN_CHANCE:
                    self.start_turn()
                    return
            if self._mode_left <= 0:
                self.mode = "idle"
                self._mode_left = self._roll(settings.IDLE_DURATION_RANGE)
        else:
            if self._mode_left <= 0:
                self.mode = "swim"
                self._mode_left = self._roll(settings.SWIM_DURATION_RANGE)
                self._turn_left = self._roll(settings.RANDOM_TURN_INTERVAL)
                if self.rng.random() > settings.KEEP_DIRECTION_CHANCE:
                    self.start_turn()
