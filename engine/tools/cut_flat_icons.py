"""单色（白色）小图标：按和底色的差距算透明度，颜色一律白色（选中行是白底黑图标，也能统一成白图标）。

用法：python cut_flat_icons.py <截图> <输出目录> <名字:x,y,w,h> ...
"""

import sys
from pathlib import Path

import cv2
import numpy as np


def cut(frame: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    crop = frame[y:y + h, x:x + w].astype(np.float32)
    border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    bg = np.median(border, axis=0)
    diff = np.abs(crop - bg).max(axis=2)
    top = np.percentile(diff, 97)
    alpha = np.clip((diff - 12) / max(top - 12, 1), 0, 1)
    out = np.dstack([np.full(crop.shape, 255, np.float32), alpha * 255]).astype(np.uint8)
    ys, xs = np.nonzero(alpha > 0.05)
    out = out[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = max(out.shape[:2]) + 2
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
        icon = cut(frame, *map(int, rect.split(",")))
        ok, buf = cv2.imencode(".png", icon)
        (Path(out_dir) / f"{name}.png").write_bytes(buf.tobytes())
        print(name, icon.shape)


if __name__ == "__main__":
    main()
