"""从游戏截图里裁图标，按和按钮底色的差距抠成透明 PNG（B13 审核：属性 / 职业 / 套装图标）。

用法：python cut_icons.py <截图> <输出目录> [--grabcut] [--max N] <名字:x,y,w,h> ...

--grabcut（B14e1：世界竞技场段位图标）：底色不是纯色（模糊的立绘、渐变）、图标自己又有深色描边时用。
按颜色差抠会留下灰色方块，改用 GrabCut 分前景 / 背景（框往里缩 4 像素当初始范围），只留最大的一块，边缘柔一像素。
图标中间镂空的地方会留一点原来的深灰底，放在深色界面上看不出来。
--max N：裁好后最长边缩到 N 像素以内。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

LOW, HIGH = 10, 70  # 和底色差距小于 LOW 全透明，大于 HIGH 全不透明


def _alpha_grabcut(crop: np.ndarray) -> np.ndarray:
    h, w = crop.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(crop, mask, (4, 4, w - 8, h - 8), bgm, fgm, 8, cv2.GC_INIT_WITH_RECT)
    fg = np.isin(mask, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
    num, lab, stats, _ = cv2.connectedComponentsWithStats(fg)
    if num > 1:  # 只留最大的一块
        fg = (lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])).astype(np.uint8)
    return cv2.GaussianBlur(fg.astype(np.float32), (3, 3), 0)


def cut(frame: np.ndarray, x: int, y: int, w: int, h: int, grabcut: bool = False) -> np.ndarray:
    crop = frame[y:y + h, x:x + w].astype(np.float32)
    if grabcut:
        alpha = _alpha_grabcut(frame[y:y + h, x:x + w].copy())
        return _square(np.dstack([crop, alpha * 255]).astype(np.uint8), alpha)  # 不按底色反混：底色不均匀
    border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    bg = np.median(border, axis=0)
    diff = np.abs(crop - bg).max(axis=2)
    alpha = np.clip((diff - LOW) / (HIGH - LOW), 0, 1)
    a = alpha[..., None]
    color = np.where(a > 0.01, (crop - (1 - a) * bg) / np.maximum(a, 0.01), 0)
    out = np.dstack([np.clip(color, 0, 255), alpha * 255]).astype(np.uint8)
    return _square(out, alpha)


def _square(out: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(alpha > 0.05)
    out = out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = max(out.shape[:2]) + 2  # 放进正方形画布居中
    canvas = np.zeros((side, side, 4), np.uint8)
    oy, ox = (side - out.shape[0]) // 2, (side - out.shape[1]) // 2
    canvas[oy:oy + out.shape[0], ox:ox + out.shape[1]] = out
    return canvas


def main() -> None:
    args = sys.argv[1:]
    grabcut = "--grabcut" in args
    if grabcut:
        args.remove("--grabcut")
    limit = 0
    if "--max" in args:
        i = args.index("--max")
        limit = int(args[i + 1])
        del args[i:i + 2]
    src, out_dir, *specs = args
    frame = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for spec in specs:
        name, rect = spec.split(":")
        x, y, w, h = map(int, rect.split(","))
        icon = cut(frame, x, y, w, h, grabcut=grabcut)
        if limit and max(icon.shape[:2]) > limit:
            s = limit / max(icon.shape[:2])
            icon = cv2.resize(icon, (round(icon.shape[1] * s), round(icon.shape[0] * s)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", icon)
        (Path(out_dir) / f"{name}.png").write_bytes(buf.tobytes())
        print(name, icon.shape)


if __name__ == "__main__":
    main()
