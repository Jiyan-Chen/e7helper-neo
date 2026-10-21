"""从游戏截图里裁图标，按和按钮底色的差距抠成透明 PNG（B13 审核：属性 / 职业 / 套装图标）。

用法：python cut_icons.py <截图> <输出目录> <名字:x,y,w,h> ...
"""

import sys
from pathlib import Path

import cv2
import numpy as np

LOW, HIGH = 10, 70  # 和底色差距小于 LOW 全透明，大于 HIGH 全不透明


def cut(frame: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    crop = frame[y:y + h, x:x + w].astype(np.float32)
    border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    bg = np.median(border, axis=0)
    diff = np.abs(crop - bg).max(axis=2)
    alpha = np.clip((diff - LOW) / (HIGH - LOW), 0, 1)
    a = alpha[..., None]
    color = np.where(a > 0.01, (crop - (1 - a) * bg) / np.maximum(a, 0.01), 0)
    out = np.dstack([np.clip(color, 0, 255), alpha * 255]).astype(np.uint8)
    ys, xs = np.nonzero(alpha > 0.05)
    out = out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = max(out.shape[:2]) + 2  # 放进正方形画布居中
    canvas = np.zeros((side, side, 4), np.uint8)
    oy, ox = (side - out.shape[0]) // 2, (side - out.shape[1]) // 2
    canvas[oy:oy + out.shape[0], ox:ox + out.shape[1]] = out
    return canvas


def main() -> None:
    src, out_dir, *specs = sys.argv[1:]
    frame = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for spec in specs:
        name, rect = spec.split(":")
        x, y, w, h = map(int, rect.split(","))
        icon = cut(frame, x, y, w, h)
        ok, buf = cv2.imencode(".png", icon)
        (Path(out_dir) / f"{name}.png").write_bytes(buf.tobytes())
        print(name, icon.shape)


if __name__ == "__main__":
    main()
