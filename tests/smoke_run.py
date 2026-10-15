"""실제 Windows 화면에서 창을 띄워 보는 스모크 테스트 (화면이 있는 환경에서 실행).

    .venv\\Scripts\\python.exe tests\\smoke_run.py

확인 내용: 창 속성, 투명 배경(데스크톱 스크린샷 비교), 클릭 통과 마스크, 드래그, 더블클릭 말풍선,
메뉴 항목, 크기/항상 위 변경, 좌우 반전 스크린샷, 10초 CPU 사용률. 스크린샷은 .tmp/ 에 저장.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import settings  # noqa: E402
from animation import SpriteLibrary  # noqa: E402
from pet_window import PetWindow  # noqa: E402

OUT = ROOT / ".tmp"
OUT.mkdir(exist_ok=True)
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def wait(ms: int) -> None:
    QTest.qWait(ms)


def grab_desktop(rect: QRect) -> QImage:
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    return screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height()).toImage()


def main() -> int:
    from PySide6.QtCore import QCoreApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    screen = QGuiApplication.primaryScreen()
    print(f"화면: {screen.geometry()} avail={screen.availableGeometry()} dpr={screen.devicePixelRatio()}")

    lib = SpriteLibrary()
    check("PNG 18장 로딩(placeholder 아님)", not lib.is_placeholder, f"notes={lib.notes}")
    prefs = settings.UserPrefs(persist=False)
    win = PetWindow(lib, prefs, test_mode=True)
    win.start()
    wait(300)

    flags = win.windowFlags()
    check("테두리 없음", bool(flags & Qt.WindowType.FramelessWindowHint))
    check("항상 위", bool(flags & Qt.WindowType.WindowStaysOnTopHint))
    check("투명 배경 속성", win.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
    check("창이 화면에 표시됨", win.isVisible())
    check("창 모양 마스크 적용(클릭 통과)", not win.mask().isEmpty())
    m = win.mask()
    check("마스크: 투명한 모서리는 창에 포함되지 않음(클릭 통과)",
          not m.contains(QPoint(2, 2)) and not m.contains(QPoint(win.width() - 3, win.height() - 3)))
    check("마스크: 상어 몸통은 창에 포함됨(클릭 가능)", m.contains(QPoint(win.width() // 2, win.height() // 2)))

    # ---- 투명 배경 검사: 창이 없을 때와 있을 때 데스크톱을 비교 ----
    win.set_test_state("idle")  # 위치 고정
    wait(1500)
    geo = win.geometry()
    dpr = screen.devicePixelRatio()
    win.hide()
    wait(250)
    before = grab_desktop(geo)
    win.show()
    wait(300)
    after = grab_desktop(geo)
    before.save(str(OUT / "desk_before.png"))
    after.save(str(OUT / "desk_after.png"))
    # 창 모서리 영역 (상어가 없는 곳) 이 데스크톱과 같으면 투명한 것
    pts = [(2, 2), (after.width() - 3, 2), (2, after.height() - 3), (after.width() - 3, after.height() - 3)]
    same = [
        max(abs(before.pixelColor(x, y).red() - after.pixelColor(x, y).red()),
            abs(before.pixelColor(x, y).green() - after.pixelColor(x, y).green()),
            abs(before.pixelColor(x, y).blue() - after.pixelColor(x, y).blue())) <= 6
        for x, y in pts
    ]
    check("창 네 모서리가 데스크톱과 동일(검은/흰 사각형 없음)", all(same), f"{same}")
    # 상어 몸통 위치는 데스크톱과 달라야 한다
    cx, cy = after.width() // 2, int(after.height() * 0.5)
    diff = sum(
        1 for dx in range(-20, 20, 4)
        if abs(before.pixelColor(cx + dx, cy).red() - after.pixelColor(cx + dx, cy).red()) > 20
    )
    check("상어 몸통이 실제로 그려짐", diff >= 3, f"differing samples={diff}")

    # 렌더 결과 자체 검사 (창 grab: 모서리 알파 0)
    g = win.grab().toImage()
    check("창 렌더 모서리 알파=0", g.pixelColor(0, 0).alpha() == 0 and g.pixelColor(g.width() - 1, 0).alpha() == 0)

    # ---- 프레임 섞기(크로스페이드)가 몸통을 반투명하게 만들지 않는지 ----
    from animation import FrameSpec
    win._timer.stop()
    d = win.devicePixelRatioF()
    bx, by = int(win.width() * 0.5 * d), int(win.height() * 0.5 * d)
    alphas = []
    for t in (0.25, 0.5, 0.75):
        win._set_spec(FrameSpec(("swim", 7, 1), ("swim", 0, 1), t), force=True)
        alphas.append(win.grab().toImage().pixelColor(bx, by).alpha())
    check("크로스페이드 중에도 몸통 불투명(알파≥245)", min(alphas) >= 245, f"{alphas}")
    win._timer.start(settings.TICK_MS)

    # ---- 좌우 반전 스크린샷 ----
    win.set_test_state("swim")
    for d, name in ((1, "right"), (-1, "left")):
        win.test_direction(d)
        wait(250)
        win.grab().save(str(OUT / f"face_{name}.png"))
        check(f"방향 {name} 표시", win.behavior.facing == d)

    # ---- 헤엄 프레임 전환 관찰 (3초 = 한 주기) ----
    win.set_test_state("swim")
    wait(400)
    seen = set()
    size0 = win.size()
    # 꼬리 한 주기(가장 느린 설정 4초)보다 길게 관찰해야 모든 프레임이 나온다
    for _ in range(100):
        wait(50)
        sp = win.player.current
        seen.add(sp.a[1])
        if sp.b:
            seen.add(sp.b[1])
    check("헤엄 프레임: 타임라인의 모든 프레임을 표시", seen == set(lib.timeline.path), f"{sorted(seen)}")
    check("헤엄 중 창 크기 변화 없음", win.size() == size0)

    # ---- 눈 깜빡임 (눈꺼풀 덮어그리기) ----
    win.set_test_state("blink")
    blink_seen = set()
    for _ in range(160):
        wait(50)
        blink_seen.add(win.player.current.blink)
    check("blink 단계(반쯤/감김) 표시", {0.5, 1.0} <= blink_seen, f"{sorted(blink_seen)}")
    win.set_test_state("swim")

    # ---- 방향 전환(turn) 테스트: 오른쪽→왼쪽, 왼쪽→오른쪽 ----
    for r2l in (True, False):
        label = "R→L" if r2l else "L→R"
        win.set_test_state("swim")
        wait(300)
        win.test_turn(r2l)
        size_before, geo_w = win.size(), win.width()
        expect_state = "turning_right_to_left" if r2l else "turning_left_to_right"
        check(f"{label} turn 상태 진입", win.behavior.state.value == expect_state, win.behavior.state.value)
        xs, sizes, states, groups = [], set(), [], []
        turn_shots = []
        frames_seen: list[int] = []
        flip = lib.turn_mode == "flip"
        t_end = time.perf_counter() + win.behavior.turn_duration + 0.6
        squashes: list[float] = []
        last_squash = 1.0
        while time.perf_counter() < t_end:
            wait(25)
            sp = win.player.current
            xs.append(win.x())
            sizes.add(win.size().toTuple())
            states.append(win.behavior.state.value)
            groups.append(sp.a[0])
            if flip:
                if win.behavior.is_turning:
                    squashes.append(sp.squash)
                    if abs(sp.squash - last_squash) > 0.08:  # 눌리는 모습을 몇 장 저장
                        last_squash = sp.squash
                        turn_shots.append(win.grab().toImage())
            elif win.behavior.is_turning and sp.a[0] == "turn" and (not frames_seen or frames_seen[-1] != sp.a[1]):
                frames_seen.append(sp.a[1])
                turn_shots.append(win.grab().toImage())
        if flip:
            check(f"{label} flip: 가로로 납작해졌다 펴짐", bool(squashes) and min(squashes) < 0.3 and squashes[0] > 0.7,
                  f"min={min(squashes) if squashes else None}")
            check(f"{label} flip: 헤엄 그림만 사용", set(groups) == {"swim"}, f"{set(groups)}")
        else:
            check(f"{label} turn 프레임 1→8 순서 재생", frames_seen == sorted(frames_seen) and frames_seen[-1] == 7
                  and frames_seen[0] <= 1, f"{frames_seen}")
        check(f"{label} turn 중 창 크기 고정", sizes == {size_before.toTuple()}, f"{sizes}")
        end_state = "swimming_left" if r2l else "swimming_right"
        check(f"{label} turn 후 {end_state}", win.behavior.state.value == end_state, win.behavior.state.value)
        # 상태 변화가 turn → 헤엄 한 번뿐 (중간에 되돌아가지 않음)
        changes = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
        check(f"{label} 상태 전이 한 번", changes == [expect_state, end_state], f"{changes}")
        # 위치 튐: 한 틱(약 25ms)당 가로 이동이 작아야 한다
        jump = max(abs(b - a) for a, b in zip(xs, xs[1:]))
        check(f"{label} 위치 튐 없음(틱당 최대 이동 px)", jump <= 6, f"max={jump}")
        # 스크린샷 시트 저장
        if turn_shots:
            w, h = turn_shots[0].width(), turn_shots[0].height()
            cols = 4
            rows = (len(turn_shots) + cols - 1) // cols
            sheet = QImage(w * cols, h * rows, QImage.Format.Format_ARGB32)
            sheet.fill(Qt.GlobalColor.gray)
            from PySide6.QtGui import QPainter
            p = QPainter(sheet)
            for i, im in enumerate(turn_shots):
                p.drawImage((i % cols) * w, (i // cols) * h, im)
            p.end()
            sheet.save(str(OUT / f"turn_{'r2l' if r2l else 'l2r'}.png"))
        corner = win.grab().toImage()
        check(f"{label} 끝난 뒤 모서리 투명", corner.pixelColor(0, 0).alpha() == 0)

    # 드래그가 turn 을 끊는 유일한 예외
    win.test_turn(True)
    wait(300)
    check("drag 직전 turn 중", win.behavior.is_turning)
    win.behavior.dragging = True
    check("drag 하면 turn 즉시 종료", not win.behavior.is_turning)
    win.behavior.dragging = False
    win.set_test_state("swim")

    # ---- 드래그 ----
    win.set_test_state("idle")
    wait(300)
    start_pos = win.pos()
    click = QPoint(win.width() * 3 // 4, win.height() // 2)  # 몸통 안쪽
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    QTest.mouseMove(win, click + QPoint(60, 40))
    wait(30)
    # 창이 (60,40) 이동했으므로 위젯 기준 좌표로는 +(60,40) 이 전체 (120,80) 이동에 해당한다
    QTest.mouseMove(win, click + QPoint(60, 40))
    wait(30)
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click + QPoint(60, 40))
    wait(100)
    moved = win.pos() - start_pos
    check("드래그로 위치 이동", abs(moved.x() - 120) <= 3 and abs(moved.y() - 80) <= 6, f"moved={moved}")

    # 화면 밖으로 끌었다 놓으면 화면 안으로 복귀
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    QTest.mouseMove(win, click + QPoint(-6000, -6000))
    wait(30)
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    wait(100)
    check("화면 밖으로 놓아도 화면 안으로 복귀", screen.availableGeometry().contains(win.geometry()), f"{win.geometry()}")

    # ---- 더블클릭 말풍선 ----
    QTest.mouseDClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    wait(200)
    check("더블클릭 말풍선 표시", win.bubble.isVisible(), f"text={win.bubble._text!r}")
    desk = grab_desktop(win.bubble.geometry().adjusted(-10, -10, 10, 10))
    desk.save(str(OUT / "bubble.png"))
    wait(settings.SPEECH_DURATION_MS + 300)
    check("말풍선 자동 사라짐", not win.bubble.isVisible())

    # ---- 메뉴 구성 ----
    menu = win.build_menu()
    texts = [a.text() for a in menu.actions() if a.text()]
    print("메뉴:", texts)
    for needed in ("일시정지", "속도", "크기", "항상 위", "종료"):
        check(f"메뉴 항목 '{needed}'", needed in texts)
    sub = {a.text(): [x.text() for x in a.menu().actions() if x.text()] for a in menu.actions() if a.menu()}
    check("속도 하위 메뉴", sub.get("속도") == ["느리게", "보통", "빠르게"], str(sub.get("속도")))
    check("크기 하위 메뉴", sub.get("크기") == ["작게", "보통", "크게"], str(sub.get("크기")))
    # 메뉴가 실제로 화면에 뜨는지
    menu.popup(win.geometry().bottomLeft() + QPoint(0, 10))
    wait(300)
    check("컨텍스트 메뉴 표시", menu.isVisible())
    desk = grab_desktop(menu.geometry())
    desk.save(str(OUT / "menu.png"))
    menu.close()

    # ---- 일시정지 / 속도 / 크기 / 항상 위 ----
    win.set_test_state(None)
    win.toggle_pause()
    wait(1500)
    p1 = win.pos()
    wait(600)
    check("일시정지 시 이동 없음", win.pos().x() == p1.x(), f"{p1} -> {win.pos()}")
    menu2 = win.build_menu()  # 변수에 붙들어 둬야 가비지 컬렉션되지 않는다
    check("메뉴 문구 전환", "다시 움직이기" in [a.text() for a in menu2.actions()])
    win.toggle_pause()

    for k in ("small", "large", "normal"):
        win.set_size(k)
        wait(150)
        check(f"크기 {k}", win.width() == settings.SIZE_PRESETS[k], f"width={win.width()}")
        check(f"크기 {k} 후에도 화면 안", screen.availableGeometry().contains(win.geometry()))
    for k in ("slow", "fast", "normal"):
        win.set_speed(k)
        check(f"속도 {k}", win.behavior.speed == settings.SPEED_PRESETS[k].pixels_per_sec)

    win.set_always_on_top(False)
    wait(200)
    check("항상 위 끄기", not (win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) and win.isVisible())
    win.set_always_on_top(True)
    wait(200)
    check("항상 위 켜기", bool(win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) and win.isVisible())
    check("토글 후 마스크 유지", not win.mask().isEmpty())

    # ---- 자동 모드 10초 CPU ----
    win.set_test_state(None)
    wait(500)
    t0, c0 = time.perf_counter(), time.process_time()
    pos_samples = set()
    for _ in range(100):
        wait(100)
        pos_samples.add((win.x(), win.y()))
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    pct = cpu / wall * 100
    check("10초간 위치가 계속 변함(이동)", len(pos_samples) > 20, f"unique positions={len(pos_samples)}")
    import os
    # 1코어 기준 값이다 (작업관리자의 전체 CPU 값은 이 값 / 코어 수). 큰 창(turn 여백) + 크로스페이드 + HiDPI 2배 기준.
    check("CPU 사용률(1코어 기준) < 15%", pct < 15, f"{pct:.1f}% (전체 {os.cpu_count()}코어 기준 약 {pct / (os.cpu_count() or 1):.1f}%)")
    check("창이 화면 안", screen.availableGeometry().contains(win.geometry()))

    win.close()
    fails = [r for r in results if not r[1]]
    print(f"\n결과: {len(results) - len(fails)}/{len(results)} 통과")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
