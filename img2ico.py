# -*- coding: utf-8 -*-
"""图片转 ICO 终端小工具。

用法：运行后把图片文件拖进终端窗口，回车确认；
输出路径直接回车，则生成在图片同目录（同名 .ico）。
"""
import io
import shlex
import struct
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("未找到 Pillow，请先安装：pip install pillow")

# ---------- 可自己调的参数 ----------
MODE = "crop"    # "crop" = 居中裁成正方形（不变形，裁掉多余边）
                 # "pad"  = 透明填充成正方形（内容完整，上下/左右留白）
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48),
         (64, 64), (128, 128), (256, 256)]
# ------------------------------------


def clean(s: str) -> str:
    """去掉拖拽路径自带的引号和首尾空白。"""
    return s.strip().strip('"').strip("'")


def to_square(im: Image.Image) -> Image.Image:
    """按 MODE 把图片变成正方形，不拉伸变形。"""
    w, h = im.size
    if w == h:
        return im
    if MODE == "crop":
        s = min(w, h)
        return im.crop(((w - s) // 2, (h - s) // 2,
                        (w + s) // 2, (h + s) // 2))
    # pad：等比缩到最长边后贴进透明画布
    s = max(w, h)
    canvas = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    im.thumbnail((s, s), Image.LANCZOS)
    canvas.paste(im, ((s - im.width) // 2, (s - im.height) // 2))
    return canvas


def save_ico(im: Image.Image, dst: Path) -> None:
    """手动写 ico 文件，帧从大到小排列。

    Pillow 自带的保存固定从小到大写帧，而 Windows 照片查看器双击打开
    时显示第一帧（16x16），放大看就像糊了。从大到小写，预览即是清晰
    大图；Windows 取用图标时按尺寸挑帧，顺序不影响使用。
    """
    blobs = []
    usable = sorted((s for s in SIZES if s[0] <= im.width and s[1] <= im.height),
                    reverse=True)
    for size in usable:
        f = im.copy()
        f.thumbnail(size, Image.LANCZOS)
        b = io.BytesIO()
        f.save(b, "PNG")
        blobs.append((size[0], size[1], b.getvalue()))

    out = struct.pack("<HHH", 0, 1, len(blobs))  # ICONDIR: 保留0 / 类型1 / 帧数
    entries = b""
    datas = b""
    offset = 6 + 16 * len(blobs)
    for w, h, data in blobs:
        # ICONDIRENTRY：宽高各 1 字节（256 写成 0）、颜色数、保留、
        # 色板数、位深、数据长度、数据偏移
        entries += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32,
                               len(data), offset)
        datas += data
        offset += len(data)
    dst.write_bytes(out + entries + datas)


def convert(src: Path, dst: Path) -> None:
    im = Image.open(src).convert("RGBA")
    if min(im.size) < 256:
        print(f"  提示：原图最小边 {min(im.size)} < 256，"
              f"超过它的尺寸不会生成（不影响使用）")
    im = to_square(im)
    save_ico(im, dst)
    print(f"  已生成：{dst}")


def resolve_out(out_s: str, src: Path) -> Path:
    """解析用户输入的输出路径：空=同目录；目录=放进去；否则当文件路径。"""
    out_s = clean(out_s)
    if not out_s:
        return src.with_suffix(".ico")
    p = Path(out_s)
    if p.is_dir() or out_s.endswith(("\\", "/")) or out_s.endswith(":"):
        return p / src.with_suffix(".ico").name
    if p.suffix.lower() != ".ico":
        p = p.with_suffix(".ico")
    return p


def parse_paths(line: str) -> list[Path]:
    """一行里可以拖多个文件（带引号也能正确按空格拆开）。"""
    return [Path(clean(t)) for t in shlex.split(line, posix=False) if clean(t)]


def main() -> None:
    paths = [Path(clean(a)) for a in sys.argv[1:]]  # 也支持命令行直接传参
    while True:
        if not paths:
            try:
                line = input("拖入图片文件（可多个），回车开始；直接回车退出: ")
            except EOFError:
                break
            paths = parse_paths(line)

        out_s = input("输出路径（直接回车=与图片同目录）: ") if len(paths) == 1 else ""
        for src in paths:
            if not src.is_file():
                print(f"  跳过：找不到文件 {src}")
                continue
            try:
                convert(src, resolve_out(out_s, src))
            except Exception as e:
                print(f"  失败：{src.name} — {e}")
        paths = []


if __name__ == "__main__":
    main()
