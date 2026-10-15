"""핵심 로직 테스트. 실행:  .venv\\Scripts\\python.exe -m unittest discover tests -v

화면 없이(offscreen) 돌아가므로 터미널에서 바로 실행할 수 있다.
"""
from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

import settings  # noqa: E402
from animation import (  # noqa: E402
    GROUP_SWIM,
    GROUP_TURN,
    AnimationPlayer,
    SpriteLibrary,
    SwimTimeline,
    make_timeline,
)
from asset_check import check_assets  # noqa: E402
from behavior import PetBehavior, PetState  # noqa: E402

_app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

BOUNDS = (0.0, 0.0, 1600.0, 800.0)
N_SWIM, N_TURN = 10, 8  # PNG 파일 수
# 화면에서 쓰는 swim 프레임 수 (꼬리 파도 모드면 코드로 만든 프레임 수)
N_FRAMES = settings.TAIL_WAVE_FRAMES if settings.SWIM_PROCEDURAL else N_SWIM


def simulate(beh: PetBehavior, seconds: float, dt: float = 0.02, bounds=BOUNDS, on_step=None) -> None:
    for _ in range(int(seconds / dt)):
        beh.update(dt, bounds)
        if on_step:
            on_step()


def make_beh(seed: int = 1, **kw) -> PetBehavior:
    beh = PetBehavior(random.Random(seed), **kw)
    beh.set_forced("swim")  # 자동 idle 전환 방지
    return beh


class AssetCheckTest(unittest.TestCase):
    def test_all_pngs_ok(self) -> None:
        report = check_assets()
        self.assertEqual(len(report.files), N_SWIM + N_TURN)
        self.assertTrue(report.all_ok, report.format())
        for f in report.files:
            self.assertTrue(f.has_alpha, f.name)

    def test_missing_files_are_named(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            report = check_assets(Path(td))
            self.assertFalse(report.all_ok)
            self.assertEqual(len(report.problems), N_SWIM + N_TURN)
            self.assertIn("swim_right/frame_01.png", report.problems[0])
            self.assertTrue(any("turn_right_to_left/turn_08.png" in p for p in report.problems))

    def test_fake_and_truncated_png_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(settings.ASSETS_DIR, Path(td) / "a")
            a = Path(td) / "a"
            (a / "swim_right" / "frame_03.png").write_bytes(b"not a png at all")
            src = settings.ASSETS_DIR / "turn_right_to_left" / "turn_02.png"
            (a / "turn_right_to_left" / "turn_02.png").write_bytes(src.read_bytes()[:3000])  # 잘린(손상) PNG
            report = check_assets(a)
            bad = {f"{f.group}/{f.name}" for f in report.files if not f.ok}
            self.assertEqual(bad, {"swim_right/frame_03.png", "turn_right_to_left/turn_02.png"})

    def test_paths_do_not_depend_on_cwd(self) -> None:
        old = Path.cwd()
        with tempfile.TemporaryDirectory() as td:
            os.chdir(td)
            try:
                self.assertTrue(check_assets().all_ok)
            finally:
                os.chdir(old)


class SpriteLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lib = SpriteLibrary()

    def test_real_assets_loaded_same_size(self) -> None:
        lib = self.lib
        self.assertFalse(lib.is_placeholder)
        self.assertEqual(lib.notes, [])
        sizes = {im.size().toTuple() for g in lib.images.values() for im in g}
        self.assertEqual(len(sizes), 1, f"모든 프레임 크기가 같아야 함: {sizes}")
        self.assertEqual(len(lib.images[GROUP_SWIM]), N_FRAMES)
        self.assertEqual(len(lib.images[GROUP_TURN]), N_TURN)
        self.assertTrue(lib.has_turn)

    def test_turn_frames_have_same_size_as_swim(self) -> None:
        """turn 프레임마다 상어가 차지하는 면적이 헤엄 그림과 같아서, 방향 전환 때 몸집이 커졌다 작아지지 않는다."""
        if not settings.TURN_NORMALIZE_SIZE:
            self.skipTest("TURN_NORMALIZE_SIZE=False")
        from animation import alpha_area

        ref = alpha_area(self.lib.images[GROUP_SWIM][0])
        for i, im in enumerate(self.lib.images[GROUP_TURN]):
            ratio = alpha_area(im) / ref
            self.assertAlmostEqual(ratio, 1.0, delta=0.05, msg=f"turn_{i + 1:02d} 면적비 {ratio:.3f}")

    def test_turn_body_center_stays_level_and_glides_smoothly(self) -> None:
        """turn 중에 몸 중심 높이가 흔들리지 않고, 가로 이동은 한 프레임에 크게 튀지 않는다 (몸이 유지되는 느낌)."""
        if not settings.TURN_AUTO_ALIGN:
            self.skipTest("TURN_AUTO_ALIGN=False")
        from animation import alpha_centroid

        cs = [alpha_centroid(im) for im in self.lib.images[GROUP_TURN]]
        ys = [c[1] for c in cs]
        self.assertLess(max(ys) - min(ys), 4.0, f"몸 중심 높이 편차(원본 px): {ys}")
        steps = [abs(b[0] - a[0]) for a, b in zip(cs, cs[1:])]
        total = abs(cs[-1][0] - cs[0][0])
        self.assertLess(max(steps), 0.45 * total + 1, f"가로 이동이 한 번에 몰리면 안 됨: {steps}")
        # 시작은 헤엄 그림과, 끝은 좌우 반전한 헤엄 그림과 같은 위치
        # (꼬리가 흔들리는 만큼 헤엄 그림의 중심도 프레임마다 조금 달라지므로 전체 평균과 비교한다)
        sw_x = sum(alpha_centroid(im)[0] for im in self.lib.images[GROUP_SWIM]) / len(self.lib.images[GROUP_SWIM])
        w = self.lib.images[GROUP_SWIM][0].width()
        self.assertAlmostEqual(cs[0][0], sw_x, delta=20)
        self.assertAlmostEqual(cs[-1][0], w - 1 - sw_x, delta=20)

    def test_exit_frame_is_best_match(self) -> None:
        if not (self.lib.procedural and settings.TURN_AUTO_EXIT_FRAME):
            self.skipTest("꼬리 파도 + 자동 선택 모드가 아님")
        self.assertTrue(0 <= self.lib.exit_frame < len(self.lib.images[GROUP_SWIM]))

    def test_turn_head_matches_swim_head_at_both_ends(self) -> None:
        """turn 시작(오른쪽 끝)·끝(왼쪽 끝)에서 코 위치가 헤엄 그림과 같아야 이어질 때 위치가 튀지 않는다."""
        from asset_check import alpha_bbox

        sw = self.lib.images[GROUP_SWIM][0]
        w = sw.width()
        nose = alpha_bbox(sw).right()
        first = alpha_bbox(self.lib.images[GROUP_TURN][0]).right()
        last = alpha_bbox(self.lib.images[GROUP_TURN][-1]).left()
        self.assertAlmostEqual(first, nose, delta=6)
        self.assertAlmostEqual(last, w - 1 - nose, delta=6)  # 반전한 헤엄의 코(왼쪽 끝)

    def test_tail_wave_keeps_body_fixed_and_moves_only_tail(self) -> None:
        """꼬리 파도 프레임: 몸 길이/앞쪽 몸/머리는 모든 프레임에서 같고, 꼬리 쪽만 달라야 한다 (깜빡임·크기 변화 방지)."""
        if not self.lib.procedural:
            self.skipTest("SWIM_PROCEDURAL=False")
        from asset_check import alpha_bbox

        imgs = self.lib.images[GROUP_SWIM]
        widths = [alpha_bbox(im).width() for im in imgs]
        # 꼬리가 좌우로 흔들리는 만큼(0~2배 진폭)만 길이가 달라진다. 그 이상 변하면 안 된다.
        limit = (settings.TAIL_SWAY_OUT + settings.TAIL_SWAY_IN) * max(widths) + 3
        self.assertLessEqual(max(widths) - min(widths), limit, f"몸 길이 변화 범위: {widths}")
        # 위아래로는 움직이지 않는다 (진폭 0 이면 위아래 범위가 모든 프레임에서 거의 같다)
        # (꼬리가 화면 쪽으로 오면 커 보이는 깊이 표현은 TAIL_DEPTH_SCALE 만큼만 높이를 바꾼다)
        if settings.TAIL_WAVE_AMPLITUDE == 0:
            lim = settings.TAIL_DEPTH_SCALE * imgs[0].height() * 0.6 + 2
            tops = [alpha_bbox(im).top() for im in imgs]
            bottoms = [alpha_bbox(im).bottom() for im in imgs]
            self.assertLessEqual(max(tops) - min(tops), lim, f"위아래로 움직임: {tops}")
            self.assertLessEqual(max(bottoms) - min(bottoms), lim, f"위아래로 움직임: {bottoms}")
        w, h = imgs[0].width(), imgs[0].height()
        front_x0 = int(w * 0.6)  # 꼬리 쪽 55% 바깥(머리 쪽, 경계의 여유 포함)은 완전히 같아야 한다
        tail_diff = 0
        for im in imgs[1:]:
            for y in range(0, h, 9):
                for x in range(front_x0, w, 9):
                    self.assertEqual(im.pixel(x, y), imgs[0].pixel(x, y), (x, y))
            for y in range(0, h, 9):
                for x in range(0, int(w * 0.25), 9):
                    tail_diff += im.pixel(x, y) != imgs[0].pixel(x, y)
        self.assertGreater(tail_diff, 50, "꼬리 쪽은 프레임마다 달라야 함")

    def test_tail_wave_is_a_smooth_loop(self) -> None:
        """인접 프레임(마지막→처음 포함)의 꼬리 모양 차이가 비슷해서 주기가 매끈하게 이어진다."""
        if not self.lib.procedural:
            self.skipTest("SWIM_PROCEDURAL=False")
        imgs = self.lib.images[GROUP_SWIM]
        n, h, w = len(imgs), imgs[0].height(), imgs[0].width()

        def diff(a, b) -> int:
            return sum(
                (a.pixelColor(x, y).alpha() > 128) != (b.pixelColor(x, y).alpha() > 128)
                for y in range(0, h, 5) for x in range(0, int(w * 0.5), 5)
            )

        steps = [diff(imgs[i], imgs[(i + 1) % n]) for i in range(n)]
        self.assertLess(max(steps), 2.5 * (sum(steps) / n) + 5, f"{steps}")

    def test_render_set_sizes_flip_and_masks(self) -> None:
        for dpr in (1.0, 1.5, 2.0):
            rs = self.lib.build(300, dpr)
            self.assertEqual(rs.size.width(), 300)
            sizes = set()
            for group, n in ((GROUP_SWIM, N_FRAMES), (GROUP_TURN, N_TURN)):
                for i in range(n):
                    for m in (1, -1):
                        fr = rs.get((group, i, m))
                        self.assertIsNotNone(fr, (group, i, m))
                        self.assertEqual(fr.pixmap.devicePixelRatio(), dpr)
                        sizes.add(fr.pixmap.size().toTuple())
            self.assertEqual(len(sizes), 1, "모든 프레임 크기 동일 → 전환 시 크기 튀지 않음")
            self.assertEqual(sizes.pop()[0], round(300 * dpr))
            # 마스크: 비어 있지 않고 창보다 작다 (투명 부분 클릭 통과). 키 0 은 양쪽 합집합
            for key in (1, -1, 0):
                area = sum(r.width() * r.height() for r in rs.masks[key])
                self.assertGreater(area, 0)
                self.assertLess(area, rs.size.width() * rs.size.height() * 0.8)
                wide = sum(r.width() * r.height() for r in rs.wide_masks[key])
                self.assertGreaterEqual(wide, area)
            self.assertEqual(rs.masks[1].boundingRect().right(),
                             rs.size.width() - 1 - rs.masks[-1].boundingRect().left())

    def test_mirror_is_really_flipped(self) -> None:
        rs = self.lib.build(300, 1.0)
        for group in (GROUP_SWIM, GROUP_TURN):
            r_img = rs.get((group, 0, 1)).pixmap.toImage()
            l_img = rs.get((group, 0, -1)).pixmap.toImage()
            w, h = r_img.width(), r_img.height()
            diff = 0
            for y in range(0, h, 7):
                for x in range(0, w, 7):
                    if abs(r_img.pixelColor(x, y).alpha() - l_img.pixelColor(w - 1 - x, y).alpha()) > 3:
                        diff += 1
            self.assertEqual(diff, 0, group)

    def test_missing_swim_falls_back_to_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            lib = SpriteLibrary(Path(td))
            self.assertTrue(lib.is_placeholder)
            self.assertTrue(lib.notes)
            rs = lib.build(200, 1.0)
            self.assertIsNotNone(rs.get((GROUP_SWIM, 3, -1)))
            self.assertIsNotNone(rs.get((GROUP_TURN, N_TURN - 1, 1)))

    def test_missing_turn_disables_turn_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            shutil.copytree(settings.ASSETS_DIR, Path(td) / "a")
            (Path(td) / "a" / "turn_right_to_left" / "turn_04.png").unlink()  # 임시 복사본에서만 삭제
            lib = SpriteLibrary(Path(td) / "a")
            self.assertFalse(lib.is_placeholder)
            self.assertFalse(lib.has_turn)
            self.assertTrue(any("turn_04.png" in n for n in lib.notes), lib.notes)
            # turn 이 없으면 끝에서 바로 방향만 바꾼다
            beh = make_beh(use_turn=lib.has_turn)
            beh.set_position(1400, 400)
            states = set()
            simulate(beh, 40, on_step=lambda: states.add(beh.state))
            self.assertEqual(states, {PetState.SWIMMING_RIGHT, PetState.SWIMMING_LEFT})


class TimelineTest(unittest.TestCase):
    def test_pingpong_has_no_duplicate_end_frames(self) -> None:
        tl = make_timeline(10, "pingpong")
        self.assertEqual(tl.describe(), [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 9, 8, 7, 6, 5, 4, 3, 2])

    def test_file_order(self) -> None:
        self.assertEqual(make_timeline(10, "file").describe(), list(range(1, 11)))

    def test_smooth_path_is_pingpong_of_settings_path(self) -> None:
        tl = make_timeline(10, "smooth")
        self.assertEqual(tl.path, [n - 1 for n in settings.SWIM_SMOOTH_PATH])
        seen = set()
        for k in range(2000):
            a, b, t = tl.sample(k / 2000)
            seen.update((a, b))
            self.assertTrue(0.0 <= t < 1.0)
        self.assertEqual(seen, set(tl.path))

    def test_smooth_phase_is_continuous(self) -> None:
        """위상을 조금씩 올릴 때 보이는 모양이 급하게 튀지 않는다 (섞는 비율이 연속적으로 변함)."""
        tl = make_timeline(10, "smooth")

        def weight(ph: float) -> dict[int, float]:
            a, b, t = tl.sample(ph)
            w = {a: 1.0 - t}
            if b != a:
                w[b] = w.get(b, 0.0) + t
            return w

        worst = 0.0
        n = 3000  # 3초 주기 → 1ms 단위
        for k in range(n):
            w0, w1 = weight(k / n), weight((k + 1) / n)
            keys = set(w0) | set(w1)
            worst = max(worst, sum(abs(w0.get(i, 0) - w1.get(i, 0)) for i in keys))
        self.assertLess(worst, 0.25, "1ms 사이에 모양이 25% 이상 바뀌면 안 됨")

    def test_phase_for_returns_that_frame(self) -> None:
        tl = make_timeline(10, "smooth")
        for f in tl.path:
            a, b, t = tl.sample(tl.phase_for(f))
            self.assertEqual((a, t), (f, 0.0))

    def test_ease_slows_down_at_ends(self) -> None:
        tl = SwimTimeline(range(5), pingpong=True, crossfade=True, ease=0.8)
        u0, _ = tl.position(0.0)
        u1, _ = tl.position(0.02)
        um, _ = tl.position(0.25)
        um2, _ = tl.position(0.27)
        self.assertLess(u1 - u0, um2 - um)


class BehaviorTest(unittest.TestCase):
    def test_turns_at_both_edges_and_stays_inside(self) -> None:
        beh = make_beh(3)
        beh.speed = 120
        beh._turn_left = 1e9
        beh.set_position(100, 400)
        seen = set()
        left_edge = right_edge = False

        def check() -> None:
            nonlocal left_edge, right_edge
            self.assertGreaterEqual(beh.x, BOUNDS[0])
            self.assertLessEqual(beh.x, BOUNDS[2])
            seen.add(beh.state)
            # 화면 끝에는 trigger 거리 근처에서 turn 이 시작되어야 함 (벽에 박지 않는다)
            left_edge |= beh.x <= BOUNDS[0] + 1
            right_edge |= beh.x >= BOUNDS[2] - 1

        simulate(beh, 120, on_step=check)
        self.assertEqual(seen, set(PetState))
        self.assertFalse(left_edge or right_edge, "turn 이 먼저 일어나서 벽까지 가지 않아야 함")

    def test_turn_starts_inside_trigger_zone(self) -> None:
        for seed in range(6):
            beh = make_beh(seed)
            beh.speed = 100
            beh._turn_left = 1e9
            beh.set_position(1000, 400)
            while not beh.is_turning:
                beh.update(0.02, BOUNDS)
            dist = BOUNDS[2] - beh.x
            lo, hi = settings.TURN_TRIGGER_RANGE
            self.assertGreaterEqual(dist, lo - 8)
            self.assertLessEqual(dist, hi + 1)

    def test_slows_down_near_edge(self) -> None:
        beh = make_beh(1)
        beh.speed = 100
        beh._turn_left = 1e9
        beh.set_position(300, 400)
        simulate(beh, 3)
        v_far = abs(beh.vx)
        beh.set_position(BOUNDS[2] - settings.TURN_TRIGGER_RANGE[1] - 40, 400)
        simulate(beh, 1.0)
        if not beh.is_turning:
            self.assertLess(abs(beh.vx), v_far * 0.8)

    def test_turn_is_atomic_and_flips_once(self) -> None:
        beh = make_beh(2)
        beh.set_position(500, 300)
        beh.force_turn(True)
        self.assertEqual(beh.state, PetState.TURNING_RIGHT_TO_LEFT)
        facings = set()
        start_x = beh.x
        t = 0.0
        while beh.is_turning:
            facings.add(beh.facing)
            beh.start_turn()  # 중간에 다시 요청해도 무시
            self.assertEqual(beh.state, PetState.TURNING_RIGHT_TO_LEFT)
            beh.update(0.02, BOUNDS)
            t += 0.02
            self.assertLess(t, settings.TURN_DURATION + 0.1)
        self.assertEqual(facings, {1}, "turn 도중에는 방향(그림 반전)이 바뀌지 않는다")
        self.assertEqual(beh.state, PetState.SWIMMING_LEFT)
        self.assertEqual(beh.facing, -1)
        self.assertAlmostEqual(t, settings.TURN_DURATION, delta=0.05)
        # turn 동안은 거의 제자리
        self.assertLess(abs(beh.x - start_x), 0.2 * settings.SPEED_PRESETS["normal"].pixels_per_sec * t)

    def test_left_to_right_turn(self) -> None:
        beh = make_beh(2)
        beh.set_position(700, 300)
        beh.force_turn(False)
        self.assertEqual(beh.state, PetState.TURNING_LEFT_TO_RIGHT)
        self.assertEqual(beh.facing, -1)
        while beh.is_turning:
            beh.update(0.02, BOUNDS)
        self.assertEqual(beh.state, PetState.SWIMMING_RIGHT)
        self.assertEqual(beh.facing, 1)

    def test_bob_amplitude_is_smooth_across_turn(self) -> None:
        """둥실거림 폭이 turn 시작/끝에서 갑자기 바뀌지 않는다 (turn 직후 몸이 튀지 않게)."""
        beh = make_beh(3)
        beh._turn_left = 1e9
        beh.set_position(700, 300)
        simulate(beh, 3)
        beh.force_turn(True)
        last = beh.bob_amplitude_ratio
        worst = 0.0
        for _ in range(int(4.0 / 0.02)):
            beh.update(0.02, BOUNDS)
            worst = max(worst, abs(beh.bob_amplitude_ratio - last))
            last = beh.bob_amplitude_ratio
        self.assertLess(worst, 0.0005)
        self.assertAlmostEqual(beh.bob_amplitude_ratio, settings.BOB_AMPLITUDE_SWIM, delta=0.001)

    def test_resumes_normal_speed_after_turn(self) -> None:
        beh = make_beh(2)
        beh.speed = 100
        beh._turn_left = 1e9
        beh.set_position(800, 300)
        beh.force_turn(True)
        while beh.is_turning:
            beh.update(0.02, BOUNDS)
        simulate(beh, 6)
        self.assertLess(beh.vx, -beh.speed * 0.6)

    def test_drag_ends_turn_immediately(self) -> None:
        beh = make_beh(2)
        beh.set_position(700, 300)
        beh.force_turn(True)
        simulate(beh, 0.5)
        beh.dragging = True
        self.assertFalse(beh.is_turning)
        self.assertEqual(beh.state, PetState.SWIMMING_LEFT)

    def test_swim_idle_cycle_happens(self) -> None:
        beh = PetBehavior(random.Random(5))
        beh.set_position(500, 300)
        modes = set()
        simulate(beh, 200, on_step=lambda: modes.add(beh.effective_mode))
        self.assertEqual(modes, {"swim", "idle"})

    def test_no_teleport(self) -> None:
        beh = make_beh(9)
        beh.speed = 120
        beh.set_position(300, 300)
        last = (beh.x, beh.y)
        worst = 0.0

        def step() -> None:
            nonlocal last, worst
            worst = max(worst, abs(beh.x - last[0]), abs(beh.y - last[1]))
            last = (beh.x, beh.y)

        simulate(beh, 90, on_step=step)
        self.assertLess(worst, 120 * 1.3 * 0.02 + 0.5)

    def test_no_abrupt_acceleration(self) -> None:
        beh = make_beh(4)
        beh.speed = 90
        beh.set_position(300, 300)
        last = beh.vx
        worst = 0.0

        def step() -> None:
            nonlocal last, worst
            worst = max(worst, abs(beh.vx - last) / 0.02)
            last = beh.vx

        simulate(beh, 90, on_step=step)
        self.assertLessEqual(worst, max(20.0, beh.speed * settings.ACCEL_FACTOR) + 1.0)

    def test_pause_stops(self) -> None:
        beh = PetBehavior(random.Random(2))
        beh.set_position(500, 300)
        simulate(beh, 3)
        beh.paused = True
        simulate(beh, 5)
        x = beh.x
        simulate(beh, 5)
        self.assertAlmostEqual(beh.x, x, delta=0.01)
        self.assertEqual(beh.effective_mode, "idle")

    def test_forced_direction_instant(self) -> None:
        beh = make_beh(2)
        beh.set_direction(-1, instant=True)
        self.assertEqual(beh.facing, -1)
        beh.set_direction(1, instant=True)
        self.assertEqual(beh.facing, 1)

    def test_screen_shrink_clamps(self) -> None:
        beh = PetBehavior(random.Random(2))
        beh.set_position(1500, 700)
        beh.update(0.02, (0, 0, 800, 400))
        self.assertLessEqual(beh.x, 800)
        self.assertLessEqual(beh.y, 400)


class AnimationPlayerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lib = SpriteLibrary()
        cls.lib.turn_mode = "art"  # 이 클래스의 turn 테스트는 turn PNG 재생 방식 기준 (flip 은 아래 별도 테스트)

    def setUp(self) -> None:
        self.player = AnimationPlayer(self.lib, random.Random(4))

    def test_flip_turn_squashes_and_mirrors_at_the_middle(self) -> None:
        """flip 방식: 헤엄 그림만 쓰고, 가장 납작할 때 좌우 반전이 바뀌며, 끝나면 원래 크기로 돌아온다."""
        self.lib.turn_mode = "flip"
        try:
            for r2l in (True, False):
                beh = make_beh(1, turn_duration=settings.TURN_FLIP_DURATION)
                beh.set_position(600, 300)
                for _ in range(60):
                    self.player.update(0.02, beh)
                beh.force_turn(r2l)
                old = 1 if r2l else -1
                squashes, mirrors, groups = [], [], set()
                while beh.is_turning:
                    beh.update(0.02, BOUNDS)
                    spec = self.player.update(0.02, beh)
                    if not beh.is_turning:
                        break
                    squashes.append(spec.squash)
                    mirrors.append(spec.a[2])
                    groups.add(spec.a[0])
                self.assertEqual(groups, {GROUP_SWIM})
                self.assertLess(min(squashes), 0.15)
                self.assertEqual(mirrors[0], old)
                self.assertEqual(mirrors[-1], -old)
                self.assertEqual(sum(1 for a, b in zip(mirrors, mirrors[1:]) if a != b), 1, "반전은 한 번만")
                k = mirrors.index(-old)  # 반전이 바뀌는 순간은 가장 납작한 근처여야 한다
                self.assertLess(squashes[k], 0.25)
                # 크기 변화는 매끈하게 (한 틱에 갑자기 뛰지 않음)
                self.assertLess(max(abs(a - b) for a, b in zip(squashes, squashes[1:])), 0.45)
                self.assertEqual(self.player.update(0.02, beh).squash, 1.0)
        finally:
            self.lib.turn_mode = "art"

    def test_turn_plays_all_frames_in_order_without_swim(self) -> None:
        for r2l in (True, False):
            beh = make_beh(1)
            beh.set_position(600, 300)
            for _ in range(60):  # 먼저 헤엄 중인 모습
                self.player.update(0.02, beh)
            beh.force_turn(r2l)
            mirror = 1 if r2l else -1
            shown: list[int] = []
            pure = 0
            saw_swim_in_turn = False
            xfade_steps = int(settings.STATE_XFADE_SECONDS / 0.02) + 2
            n = 0
            while beh.is_turning:
                beh.update(0.02, BOUNDS)
                spec = self.player.update(0.02, beh)
                n += 1
                if not beh.is_turning:  # 이 틱에서 turn 이 끝났다 → 헤엄 쪽으로 섞기 시작하는 것은 정상
                    break
                if n > xfade_steps:  # 시작 직후 짧은 크로스페이드 이후부터는 turn 그림만
                    if spec.a[0] != GROUP_TURN or (spec.b and spec.b[0] != GROUP_TURN):
                        saw_swim_in_turn = True
                    self.assertEqual(spec.a[2], mirror)
                if spec.a[0] == GROUP_TURN:
                    pure += 1
                    idx = spec.a[1] if (spec.b is None or spec.t < 0.5) else spec.b[1]
                    if not shown or shown[-1] != idx:
                        shown.append(idx)
            self.assertFalse(saw_swim_in_turn, "turn 중에는 일반 헤엄 프레임이 끼어들면 안 됨")
            self.assertEqual(shown, sorted(shown), "프레임 번호가 되돌아가면 안 됨")
            self.assertEqual(shown[-1], N_TURN - 1)
            self.assertGreaterEqual(len(shown), N_TURN - 1)
            # 끝난 직후 헤엄 그림으로 돌아온다
            for _ in range(40):
                spec = self.player.update(0.02, beh)
            self.assertEqual(spec.a[0], GROUP_SWIM)
            self.assertEqual(spec.a[2], -mirror)

    def test_facing_never_flips_back_and_forth(self) -> None:
        """한 틱 안에서 그림 방향이 바뀌더라도 turn 시작/종료 때 각 한 번뿐이어야 한다."""
        beh = make_beh(5)
        beh.speed = 120
        beh._turn_left = 1e9
        beh.set_position(200, 300)
        mirrors: list[int] = []
        for _ in range(int(120 / 0.02)):
            beh.update(0.02, BOUNDS)
            spec = self.player.update(0.02, beh)
            if spec.b is None:
                if not mirrors or mirrors[-1] != spec.a[2]:
                    mirrors.append(spec.a[2])
        # 한 번 방향이 바뀌고 나면 다음 turn 까지 다시 바뀌지 않는다: 연속 같은 값이 없고 번갈아가야 함
        self.assertGreater(len(mirrors), 2)
        for a, b in zip(mirrors, mirrors[1:]):
            self.assertNotEqual(a, b)

    def _run_tail(self, period: float, seconds: float, dt: float, speed: float) -> float:
        player = AnimationPlayer(self.lib, random.Random(1))
        player.set_tail_period(period)
        beh = make_beh(1)
        beh.speed = speed
        beh.set_position(300, 300)
        player.phase = 0.0
        player._rate = 1.0 / period
        total = 0.0
        steps = int(seconds / dt)
        for _ in range(steps):
            beh.update(dt, (0, 0, 100000, 800))
            before = player.phase
            player.update(dt, beh)
            total += (player.phase - before) % 1.0
        return total

    def test_tail_cycle_follows_real_time(self) -> None:
        for name, preset in settings.SPEED_PRESETS.items():
            for dt in (0.01, 0.025, 0.05):
                cycles = self._run_tail(preset.tail_period, 12.0, dt, preset.pixels_per_sec)
                expect = 12.0 / preset.tail_period
                self.assertAlmostEqual(cycles, expect, delta=0.05 * expect, msg=f"{name} dt={dt}")

    def test_tail_cycle_independent_of_move_speed(self) -> None:
        slow = self._run_tail(3.0, 12.0, 0.025, 20.0)
        fast = self._run_tail(3.0, 12.0, 0.025, 200.0)
        self.assertAlmostEqual(slow, fast, delta=0.1)

    def test_preset_cycles(self) -> None:
        self.assertEqual(settings.SPEED_PRESETS["slow"].tail_period, 4.0)
        self.assertEqual(settings.SPEED_PRESETS["normal"].tail_period, 3.0)
        self.assertEqual(settings.SPEED_PRESETS["fast"].tail_period, 2.0)

    def test_blink_not_too_often(self) -> None:
        beh = make_beh(1)
        beh.set_position(500, 300)
        starts = []
        t = 0.0
        prev = False
        for _ in range(int(120 / 0.02)):
            beh.update(0.02, (0, 0, 10 ** 7, 800))
            spec = self.player.update(0.02, beh)
            t += 0.02
            now = spec.blink > 0
            if now and not prev:
                starts.append(t)
            prev = now
        self.assertGreaterEqual(len(starts), 8)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertGreaterEqual(min(gaps), settings.BLINK_MIN_GAP - 0.1)


if __name__ == "__main__":
    unittest.main()
