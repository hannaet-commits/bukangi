"""프레임 분석 도구 (개발용, 원본 PNG는 읽기만 한다).

    .venv\\Scripts\\python.exe tools\\analyze_frames.py [swim_right|turn_right_to_left|all]

출력: 프레임별 크기/알파/캐릭터 영역/코 위치/머리 정렬 오차/몸 중심선(곡선)/꼬리 각도,
      연속 프레임 간 차이, 비교 이미지(.tmp/analysis_*.png)

필요 패키지: Pillow, numpy (requirements-dev.txt)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUT = ROOT / ".tmp"
OUT.mkdir(exist_ok=True)
THR = 10


def load(folder: str) -> list[tuple[str, np.ndarray]]:
    files = sorted((ASSETS / folder).glob("*.png"))
    return [(f.name, np.array(Image.open(f).convert("RGBA"))) for f in files]


def bbox(alpha: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(alpha > THR)
    return xs.min(), ys.min(), xs.max(), ys.max()


def centerline(alpha: np.ndarray, xs: list[int]) -> list[float]:
    """각 x 열에서 상어 몸이 차지하는 세로 범위의 중앙 y (꼬리/몸통 곡선 비교용)."""
    out = []
    for x in xs:
        col = np.where(alpha[:, x] > THR)[0]
        out.append((col.min() + col.max()) / 2 if len(col) else float("nan"))
    return out


def head_shift(ref: np.ndarray, cur: np.ndarray, x0: int, x1: int, y0: int, y1: int, r: int = 14) -> tuple[int, int, float]:
    """머리 영역 알파 마스크를 ref와 가장 잘 겹치게 하는 이동량(dx,dy)과 그때의 IoU."""
    ref = np.pad(ref, r)  # 캔버스 가장자리를 넘어 이동해도 오류가 나지 않도록 0(투명)으로 채운다
    cur = np.pad(cur, r)
    x0, x1, y0, y1 = x0 + r, x1 + r, y0 + r, y1 + r
    a = (ref[y0:y1, x0:x1] > THR)
    best = (0, 0, -1.0)
    for dy in range(-r, r + 1, 2):
        for dx in range(-r, r + 1, 2):
            b = (cur[y0 + dy : y1 + dy, x0 + dx : x1 + dx] > THR)
            iou = (a & b).sum() / max(1, (a | b).sum())
            if iou > best[2]:
                best = (dx, dy, iou)
    return best


def analyze(folder: str) -> None:
    frames = load(folder)
    if not frames:
        print(f"[{folder}] 파일 없음")
        return
    print(f"\n===== {folder} ({len(frames)}장) =====")
    alphas = [a[..., 3] for _, a in frames]
    boxes = [bbox(al) for al in alphas]
    H, W = alphas[0].shape
    # 코(오른쪽 끝) 위치
    noses = []
    for al, bb in zip(alphas, boxes):
        x = bb[2]
        ys = np.where(al[:, x - 3] > THR)[0]
        noses.append((x, float(ys.mean()) if len(ys) else float("nan")))
    ref_i = 0
    # 머리 영역: 코에서 왼쪽으로 300px
    hx1 = int(np.median([n[0] for n in noses])) + 1
    hx0 = hx1 - 300
    hy0 = int(np.median([b[1] for b in boxes])) + 120
    hy1 = int(np.median([b[3] for b in boxes])) - 60
    cols = list(range(150, 1150, 100))
    ref_cl = None
    print(f"{'파일':<14}{'크기':<11}{'알파':<6}{'캐릭터영역(x0,y0~x1,y1)':<28}{'코(x,y)':<14}{'머리정렬(dx,dy,IoU)':<22}{'꼬리끝x':<8}{'꼬리 y범위'}")
    cls = []
    for i, ((name, arr), al, bb, nose) in enumerate(zip(frames, alphas, boxes, noses)):
        sh = head_shift(alphas[ref_i], al, hx0, hx1, hy0, hy1)
        tail_cols = np.where(al[:, bb[0] : bb[0] + 160] > THR)
        ty = (tail_cols[0].min(), tail_cols[0].max())
        has_a = "있음" if arr[..., 3].min() < 255 else "없음"
        print(f"{name:<14}{arr.shape[1]}x{arr.shape[0]:<5}{has_a:<6}{str(bb):<28}{nose[0]},{nose[1]:.0f}".ljust(80)
              + f"{sh[0]:+d},{sh[1]:+d},{sh[2]:.3f}".ljust(22) + f"{bb[0]:<8}{ty[0]}~{ty[1]}")
        cls.append(centerline(al, cols))
    cl = np.array(cls)
    print("\n몸 중심선 y (x=150..1050, 100px 간격) - 앞 프레임과의 차이가 클수록 꼬리 쪽이 크게 휘어짐")
    mean_cl = np.nanmean(cl, axis=0)
    for (name, _), row in zip(frames, cl):
        print(f"{name:<14}" + " ".join(f"{v - m:+6.0f}" for v, m in zip(row, mean_cl)))
    # 꼬리 휨 지표: 꼬리 근처(x=150~350) 중심선 평균 - 몸통(x=550~750) 중심선 평균
    print("\n꼬리 휨 지표(꼬리 중심 y - 몸통 중심 y, +는 꼬리가 아래) / 꼬리 길이(코~꼬리끝) / 연속 프레임 알파 차이(XOR%)")
    for i, ((name, _), al) in enumerate(zip(frames, alphas)):
        tail = np.nanmean(cl[i][:3])
        body = np.nanmean(cl[i][5:8])
        length = noses[i][0] - boxes[i][0]
        nxt = alphas[(i + 1) % len(alphas)]
        xor = ((al > THR) ^ (nxt > THR)).sum() / max(1, (al > THR).sum()) * 100
        print(f"{name:<14}tail-body={tail - body:+7.1f}  length={length:5d}  XOR(next)={xor:5.2f}%")

    # 비교 시트
    pad = 40
    x0 = max(0, min(b[0] for b in boxes) - pad)
    y0 = max(0, min(b[1] for b in boxes) - pad)
    x1 = min(W, max(b[2] for b in boxes) + pad)
    y1 = min(H, max(b[3] for b in boxes) + pad)
    tw = 560
    th = int((y1 - y0) * tw / (x1 - x0))
    ncol = 2
    nrow = (len(frames) + ncol - 1) // ncol
    sheet = Image.new("RGBA", (tw * ncol, th * nrow), (120, 170, 210, 255))
    for i, (name, arr) in enumerate(frames):
        im = Image.fromarray(arr).crop((x0, y0, x1, y1)).resize((tw, th), Image.LANCZOS)
        cell = Image.new("RGBA", im.size, (120, 170, 210, 255))
        cell.alpha_composite(im)
        d = ImageDraw.Draw(cell)
        d.text((8, 6), name, fill=(255, 255, 255, 255))
        # 공통 기준선: 코 위치 / 몸 중심 y
        nx = (np.median([n[0] for n in noses]) - x0) * tw / (x1 - x0)
        d.line([(nx, 0), (nx, th)], fill=(255, 80, 80, 160))
        sheet.paste(cell, ((i % ncol) * tw, (i // ncol) * th))
    sheet.convert("RGB").save(OUT / f"analysis_{folder}.png")
    print(f"→ 비교 시트 저장: .tmp/analysis_{folder}.png (빨간선 = 코 기준선)")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    folders = ["swim_right", "turn_right_to_left", "idle", "blink"] if target == "all" else [target]
    for f in folders:
        analyze(f)
