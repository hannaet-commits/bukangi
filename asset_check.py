"""PNG 에셋 검사 도구.

확인 항목: 파일 존재 / 실제 PNG 여부 / 손상 여부 / 알파(투명도) / 크기·비율 / 모서리 투명 여부.
이 모듈은 에셋을 읽기만 하고 절대 덮어쓰거나 삭제하지 않습니다.

단독 실행:  .venv\\Scripts\\python.exe asset_check.py [에셋폴더]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QImageReader

import settings

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def alpha_bbox(image: QImage, threshold: int = settings.ALPHA_THRESHOLD) -> QRect:
    """알파값이 threshold보다 큰 픽셀을 모두 감싸는 사각형. 없으면 빈 QRect.

    파이썬 픽셀 루프 대신 바이트 슬라이스(C 속도)로 계산해서 빠르다.
    """
    if image.isNull():
        return QRect()
    a8 = image.convertToFormat(QImage.Format.Format_Alpha8)
    w, h, bpl = a8.width(), a8.height(), a8.bytesPerLine()
    data = bytes(a8.constBits())

    def row_has(y: int) -> bool:
        return max(data[y * bpl : y * bpl + w]) > threshold

    def col_has(x: int) -> bool:
        return max(data[x : x + bpl * (h - 1) + 1 : bpl]) > threshold

    top = next((y for y in range(h) if row_has(y)), None)
    if top is None:
        return QRect()
    bottom = next(y for y in range(h - 1, -1, -1) if row_has(y))
    left = next(x for x in range(w) if col_has(x))
    right = next(x for x in range(w - 1, -1, -1) if col_has(x))
    return QRect(left, top, right - left + 1, bottom - top + 1)


@dataclass
class FileCheck:
    group: str
    name: str
    path: Path
    exists: bool = False
    is_png: bool = False
    loadable: bool = False
    has_alpha: bool = False
    width: int = 0
    height: int = 0
    content_bbox: QRect = field(default_factory=QRect)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """사용 가능한 파일인지(없거나 깨졌으면 False). 경고는 사용 가능으로 본다."""
        return self.exists and self.is_png and self.loadable and not self.errors


@dataclass
class AssetReport:
    assets_dir: Path
    files: list[FileCheck] = field(default_factory=list)
    global_warnings: list[str] = field(default_factory=list)

    def group(self, name: str) -> list[FileCheck]:
        return [f for f in self.files if f.group == name]

    def group_ok(self, name: str) -> bool:
        items = self.group(name)
        return bool(items) and all(f.ok for f in items)

    @property
    def all_ok(self) -> bool:
        return bool(self.files) and all(f.ok for f in self.files)

    @property
    def problems(self) -> list[str]:
        """사용자에게 보여줄 문제 목록(누락/손상)."""
        out: list[str] = []
        for f in self.files:
            for e in f.errors:
                out.append(f"{f.group}/{f.name}: {e}")
        return out

    def format(self) -> str:
        lines = [f"에셋 폴더: {self.assets_dir}"]
        for f in self.files:
            mark = "OK  " if f.ok else "FAIL"
            if f.ok:
                bb = f.content_bbox
                ratio = f"{bb.width() / bb.height():.2f}:1" if bb.height() else "-"
                lines.append(
                    f"[{mark}] {f.group}/{f.name}  {f.width}x{f.height}  "
                    f"알파={'있음' if f.has_alpha else '없음'}  "
                    f"캐릭터영역={bb.width()}x{bb.height()} (가로:세로 {ratio})"
                )
            else:
                lines.append(f"[{mark}] {f.group}/{f.name}")
            lines += [f"         ✗ {e}" for e in f.errors]
            lines += [f"         ! {w}" for w in f.warnings]
        lines += [f"! {w}" for w in self.global_warnings]
        total = len(self.files)
        okc = sum(1 for f in self.files if f.ok)
        lines.append(f"결과: {okc}/{total} 파일 정상")
        return "\n".join(lines)


def check_file(group: str, name: str, path: Path) -> FileCheck:
    """파일 하나를 검사한다. 어떤 경우에도 예외를 밖으로 던지지 않는다."""
    fc = FileCheck(group=group, name=name, path=path)
    try:
        if not path.is_file():
            fc.errors.append(f"파일이 없습니다: {path}")
            return fc
        fc.exists = True

        with open(path, "rb") as fp:
            head = fp.read(8)
        fc.is_png = head == PNG_SIGNATURE
        if not fc.is_png:
            fc.errors.append("확장자는 .png 이지만 실제 PNG 파일이 아닙니다(다른 형식이거나 손상됨).")
            return fc

        reader = QImageReader(str(path))
        reader.setAutoTransform(False)
        image = reader.read()
        if image.isNull():
            fc.errors.append(f"이미지를 읽을 수 없습니다(손상 의심): {reader.errorString()}")
            return fc
        fc.loadable = True
        fc.width, fc.height = image.width(), image.height()
        fc.has_alpha = image.hasAlphaChannel()

        if not fc.has_alpha:
            fc.warnings.append("알파(투명도) 채널이 없습니다 → 배경이 검은/흰 사각형으로 보일 수 있습니다.")
        else:
            fc.content_bbox = alpha_bbox(image)
            if fc.content_bbox.isEmpty():
                fc.errors.append("완전히 투명한 이미지입니다(캐릭터 픽셀이 없음).")
            else:
                # 네 모서리 픽셀이 불투명하면 배경이 안 지워진 이미지일 가능성이 높다
                corners = [(0, 0), (image.width() - 1, 0), (0, image.height() - 1),
                           (image.width() - 1, image.height() - 1)]
                if all(image.pixelColor(x, y).alpha() > 200 for x, y in corners):
                    fc.warnings.append("네 모서리가 불투명합니다 → 배경이 제거되지 않았을 수 있습니다.")
    except Exception as exc:  # noqa: BLE001 - 검사 도구는 절대 죽지 않게
        fc.errors.append(f"검사 중 예외: {exc!r}")
    return fc


def required_groups() -> dict[str, list[str]]:
    """검사할 에셋 목록. 예전 idle/blink 는 USE_LEGACY_IDLE_ASSETS 가 켜져 있을 때만 포함."""
    groups = dict(settings.ASSET_GROUPS)
    if settings.USE_LEGACY_IDLE_ASSETS:
        groups.update(settings.LEGACY_ASSET_GROUPS)
    return groups


def check_assets(assets_dir: Path | None = None) -> AssetReport:
    """settings.ASSET_GROUPS 에 정의된 모든 파일을 검사한다."""
    base = Path(assets_dir) if assets_dir else settings.ASSETS_DIR
    report = AssetReport(assets_dir=base)
    for group, names in required_groups().items():
        for name in names:
            report.files.append(check_file(group, name, base / group / name))

    good = [f for f in report.files if f.ok]
    sizes = {(f.width, f.height) for f in good}
    if len(sizes) > 1:
        report.global_warnings.append(
            f"이미지 크기가 서로 다릅니다: {sorted(sizes)} → 첫 이미지 크기에 맞춰 자동 보정합니다."
        )
    return report


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    report = check_assets(Path(args[0]) if args else None)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    print(report.format())
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
