"""CPU 사용률 측정 도구 (개발용). 옵션 조합별로 6초씩 측정한다.

    .venv\\Scripts\\python.exe tests\\bench_cpu.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import settings  # noqa: E402
from animation import SpriteLibrary  # noqa: E402
from pet_window import PetWindow  # noqa: E402


def measure(label: str, tick_ms: int, no_mask: bool, secs: float = 6.0) -> None:
    settings.TICK_MS = tick_ms
    win = PetWindow(LIB, settings.UserPrefs(persist=False))
    if no_mask:
        win.setMask = lambda *_a, **_k: None  # type: ignore[method-assign]
    win.start()
    win.set_test_state("swim")  # 측정 조건을 같게: 헤엄 고정
    QTest.qWait(800)
    t0, c0 = time.perf_counter(), time.process_time()
    while time.perf_counter() - t0 < secs:
        QTest.qWait(200)
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    print(f"{label:<28} CPU {cpu / wall * 100:5.1f}%")
    win.close()
    QTest.qWait(300)


if __name__ == "__main__":
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    LIB = SpriteLibrary()
    for label, ms in (("tick 16ms (60fps)", 16), ("tick 20ms (50fps)", 20), ("tick 25ms (40fps)", 25),
                      ("tick 33ms (30fps)", 33)):
        measure(label, ms, False)
