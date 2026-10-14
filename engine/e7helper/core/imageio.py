"""图片读写。cv2.imread / imwrite 不支持中文路径，统一走 imdecode / imencode。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def read_image(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    """读取图片，默认返回 BGR uint8 (H, W, 3)。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, flags)
    if image is None:
        raise ValueError(f"无法解码图片：{path}")
    return image


def write_image(path: str | Path, image: np.ndarray) -> Path:
    """按扩展名编码并写入，自动创建父目录。"""
    path = Path(path)
    ok, buf = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise ValueError(f"无法编码图片：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())
    return path
