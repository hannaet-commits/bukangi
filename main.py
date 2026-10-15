"""부캉이 데스크톱 펫 - 진입점.

실행:
    .venv\\Scripts\\python.exe main.py            # 일반 실행
    .venv\\Scripts\\python.exe main.py --test     # 우클릭 메뉴에 테스트 항목 추가
    .venv\\Scripts\\python.exe main.py --check    # 에셋(PNG 8장) 검사만 하고 종료
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import settings


def setup_logging(verbose: bool) -> None:
    """파일(+가능하면 콘솔)로 로그를 남긴다. --noconsole exe 에서도 문제 추적이 가능하다."""
    handlers: list[logging.Handler] = []
    try:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / settings.APP_NAME
        base.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(base / "bukangi.log", maxBytes=300_000, backupCount=1, encoding="utf-8"))
    except OSError:
        pass
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="부캉이 - 바탕화면을 헤엄치는 흑상어")
    p.add_argument("--test", action="store_true", help="우클릭 메뉴에 애니메이션 테스트 항목을 추가")
    p.add_argument("--state", choices=["swim", "idle", "blink"], help="시작할 때 상태 고정 (테스트용)")
    p.add_argument("--direction", choices=["left", "right"], help="시작 방향 (테스트용)")
    p.add_argument("--turn", choices=["r2l", "l2r", "loop"],
                   help="시작하자마자 방향 전환 실행 (r2l: 오른쪽→왼쪽, l2r: 왼쪽→오른쪽, loop: 계속 반복) - 테스트용")
    p.add_argument("--check", action="store_true", help="에셋 검사만 실행하고 종료")
    p.add_argument("--placeholder", action="store_true", help="PNG 대신 임시 상어 사용")
    p.add_argument("--assets", type=Path, help="에셋 폴더를 직접 지정")
    p.add_argument("--multi", action="store_true", help="중복 실행 허용")
    p.add_argument("--no-dialog", action="store_true", help="에셋 문제 안내 창을 띄우지 않음")
    p.add_argument("--no-persist", action="store_true", help="설정(속도/크기)을 저장/불러오지 않음")
    p.add_argument("-v", "--verbose", action="store_true", help="자세한 로그")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.verbose or args.test)
    log = logging.getLogger("bukangi")

    if args.check:
        import asset_check

        return asset_check.main([str(args.assets)] if args.assets else [])

    from PySide6.QtCore import QDir, QLockFile, Qt
    from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

    # HiDPI: 125%/150% 같은 배율도 반올림하지 않고 그대로 사용 (너무 작아 보이는 것 방지)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(settings.APP_NAME)
    app.setQuitOnLastWindowClosed(False)  # 말풍선 창 등이 닫혀도 앱이 종료되지 않게

    # 중복 실행 방지
    lock = QLockFile(QDir.temp().filePath("bukangi.lock"))
    lock.setStaleLockTime(0)
    if not args.multi and not lock.tryLock(200):
        log.warning("이미 부캉이가 실행 중입니다.")
        QMessageBox.information(None, settings.APP_TITLE, "부캉이가 이미 실행 중입니다.")
        return 0

    from animation import SpriteLibrary
    from pet_window import PetWindow

    try:
        library = SpriteLibrary(args.assets, force_placeholder=args.placeholder)
    except Exception:  # noqa: BLE001 - 최후의 방어: 어떤 에러가 나도 placeholder 로 실행
        log.exception("에셋 로딩 중 예상치 못한 오류 → placeholder 로 실행")
        library = SpriteLibrary(None, force_placeholder=True)
        library.notes.append("에셋 로딩 중 오류가 발생해 임시 상어로 실행합니다. 로그를 확인하세요.")

    prefs = settings.UserPrefs(persist=not args.no_persist)
    window = PetWindow(library, prefs, test_mode=args.test)
    if args.state:
        window.set_test_state(args.state)
    if args.direction:
        window.behavior.set_direction(1 if args.direction == "right" else -1, instant=True)
    if args.turn == "loop":
        window.set_test_state("swim")
        window.set_turn_loop(True)
    elif args.turn:
        window.test_turn(args.turn == "r2l")
    window.start()

    # 에셋 문제 안내 (창 + 로그)
    if library.notes:
        text = "\n\n".join(library.notes)
        log.warning("에셋 안내:\n%s", text)
        if not args.no_dialog:
            box = QMessageBox(QMessageBox.Icon.Warning, settings.APP_TITLE, text)
            box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            box.setModal(False)
            box.show()
            app._asset_box = box  # type: ignore[attr-defined]  # 참조 유지(가비지 컬렉션 방지)

    # 트레이 아이콘: 부캉이를 숨기거나 종료하는 비상 통로
    if QSystemTrayIcon.isSystemTrayAvailable():
        icon_src = library.images["swim"][0].scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        tray = QSystemTrayIcon(QIcon(QPixmap.fromImage(icon_src)), app)
        tray.setToolTip(settings.APP_TITLE)
        tray_menu = QMenu()
        tray_menu.addAction("보이기 / 숨기기", lambda: window.setVisible(not window.isVisible()))
        tray_menu.addAction("말하기", window.say)
        tray_menu.addSeparator()
        tray_menu.addAction("종료", app.quit)
        tray.setContextMenu(tray_menu)
        tray.show()
        app._tray, app._tray_menu = tray, tray_menu  # type: ignore[attr-defined]

    app.aboutToQuit.connect(lambda: (prefs.save(), window.bubble.hide()))
    log.info("부캉이 시작 (placeholder=%s, 에셋=%s)", library.is_placeholder, library.assets_dir)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
