"""合成应用图标母图（B10，用户指定：雪之国的索尔缇娅的头像）。

头像 c2111_s.png 来自官方指南站（static.smilegatemegaport.com/.../hero/c2111_s.png，112×112，带圆形透明边），
加游戏风的深蓝圆角底和金色头像框，输出 icon-1024.png。再在 app/ 下生成各尺寸：
    python -m uv run --project ../engine python src-tauri/icons/source/make_icon.py
    pnpm tauri icon src-tauri/icons/source/icon-1024.png
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
SIZE = 1024
SS = 4  # 超采样，画完再缩小，边缘平滑

NAVY_TOP, NAVY_BOTTOM = (34, 53, 92), (11, 17, 32)  # GUI 的 --color-abyss 一系
GOLD_HI, GOLD, GOLD_LO = (246, 226, 176), (216, 182, 121), (143, 122, 85)  # --color-gold / --color-gold-line


def vertical_gradient(size: int, top, bottom) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize((size, size))


def main() -> None:
    S = SIZE * SS
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # 深蓝圆角底
    bg_mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(bg_mask).rounded_rectangle((16 * SS, 16 * SS, S - 16 * SS, S - 16 * SS), radius=200 * SS, fill=255)
    canvas.paste(vertical_gradient(S, NAVY_TOP, NAVY_BOTTOM), (0, 0), bg_mask)

    draw = ImageDraw.Draw(canvas)
    c = S // 2
    # 金色头像框：外圈粗金边（上亮下暗）+ 内圈细线
    ring_r, ring_w = 468 * SS, 40 * SS
    ring = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ring).ellipse((c - ring_r, c - ring_r, c + ring_r, c + ring_r), fill=255)
    ImageDraw.Draw(ring).ellipse((c - ring_r + ring_w, c - ring_r + ring_w, c + ring_r - ring_w, c + ring_r - ring_w), fill=0)
    canvas.paste(vertical_gradient(S, GOLD_HI, GOLD_LO), (0, 0), ring)
    inner = ring_r - ring_w - 10 * SS
    draw.ellipse((c - inner, c - inner, c + inner, c + inner), outline=GOLD_LO, width=8 * SS)

    # 头像：放大到内圈，按圆形裁切
    face_r = inner - 12 * SS
    face = Image.open(HERE / "c2111_s.png").convert("RGBA")
    face = face.resize((face_r * 2 // SS, face_r * 2 // SS), Image.LANCZOS)
    face = face.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2)).resize((face_r * 2, face_r * 2), Image.LANCZOS)
    mask = Image.new("L", face.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, face_r * 2, face_r * 2), fill=255)
    alpha = Image.composite(face.getchannel("A"), Image.new("L", face.size, 0), mask)
    # 原图圆形边缘半透明：底下先垫一层深色，避免透出金边
    disc = Image.new("RGBA", face.size, (*NAVY_BOTTOM, 255))
    canvas.paste(disc, (c - face_r, c - face_r), mask)
    face.putalpha(alpha)
    canvas.alpha_composite(face, (c - face_r, c - face_r))

    canvas.resize((SIZE, SIZE), Image.LANCZOS).save(HERE / "icon-1024.png")
    print(f"写入 {HERE / 'icon-1024.png'}")


if __name__ == "__main__":
    main()
