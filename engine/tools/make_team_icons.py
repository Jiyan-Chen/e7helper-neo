"""群阵（开放型刻印）图示：从游戏截图里「34」那张（上、左亮，右、下暗）生成 7 种位置组合。

四个菱形按离各自中心最近来分；受影响的位置涂成截图里亮菱形的颜色，其余涂暗菱形的颜色，透明度按和底色的差距算。
位置：1 右、2 下、3 上、4 左（对照 e7.wiki 用的游戏原图 hero_dedi_p_*.png）。
用法：python make_team_icons.py <截图> <输出目录>
"""

import sys
from pathlib import Path

import cv2
import numpy as np

X, Y, W, H = 362, 343, 78, 66  # 截图里开放型刻印图示的范围
CENTERS = {"3": (39, 19), "4": (20, 34), "1": (57, 34), "2": (39, 49)}  # 各位置菱形的中心（裁剪坐标）
RADIUS = 16  # 菱形中心到顶点（L1 距离），再往外是背景
COMBOS = ["1234", "34", "23", "24", "13", "14", "12"]


def main() -> None:
    src, out_dir = sys.argv[1:]
    frame = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR).astype(np.float32)
    crop = frame[Y:Y + H, X:X + W]
    border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    bg = np.median(border, axis=0)
    diff = np.abs(crop - bg).max(axis=2)
    yy, xx = np.mgrid[0:H, 0:W]
    keys = list(CENTERS)
    dist = np.stack([np.abs(xx - CENTERS[k][0]) + np.abs(yy - CENTERS[k][1]) for k in keys])  # 菱形用 L1 距离
    region = np.array(keys)[dist.argmin(axis=0)]
    inside = dist.min(axis=0) <= RADIUS
    solid = diff > 40
    lit = np.median(crop[solid & np.isin(region, ["3", "4"])], axis=0)
    dim = np.median(crop[solid & np.isin(region, ["1", "2"])], axis=0)
    lit_d, dim_d = np.abs(lit - bg).max(), np.abs(dim - bg).max()
    # 每个像素的「覆盖度」：在亮的菱形里按亮色算，在暗的菱形里按暗色算
    cover = np.where(np.isin(region, ["3", "4"]), diff / lit_d, diff / dim_d).clip(0, 1)
    cover[(cover < 0.08) | ~inside] = 0  # 菱形以外的是背景纹理
    ys, xs = np.nonzero(cover)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    for combo in COMBOS:
        on = np.isin(region, list(combo))
        color = np.where(on[..., None], lit, dim)
        icon = np.dstack([color, cover * 255]).astype(np.uint8)[y0:y1, x0:x1]
        side = max(icon.shape[:2]) + 2
        canvas = np.zeros((side, side, 4), np.uint8)
        oy, ox = (side - icon.shape[0]) // 2, (side - icon.shape[1]) // 2
        canvas[oy:oy + icon.shape[0], ox:ox + icon.shape[1]] = icon
        ok, buf = cv2.imencode(".png", canvas)
        (Path(out_dir) / f"devotion_team_{combo}.png").write_bytes(buf.tobytes())
    print("lit", lit, "dim", dim, "bg", bg, "size", canvas.shape)


if __name__ == "__main__":
    main()
