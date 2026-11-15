"""Renderizacao de texto/imagem para o raster 1-bit da impressora.

Formato do raster: 1 bit por pixel, MSB primeiro, 1 = preto,
cada linha alinhada em byte — igual ao PBM P4 e ao esperado pelo JBIG.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:  # numpy acelera o empacotamento; sem ele usamos PIL
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def default_font(size: int = 28) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def pack_bilevel(image: Image.Image, threshold: int = 128) -> bytes:
    """Empacota uma imagem em 1 bit/pixel, 1 = preto."""
    gray = image.convert("L")
    width, height = gray.size
    if np is not None:
        arr = np.asarray(gray)
        packed = np.packbits(arr < threshold, axis=1)
        return packed.tobytes()

    data = gray.load()
    stride = (width + 7) // 8
    out = bytearray(stride * height)
    for y in range(height):
        base = y * stride
        for x in range(width):
            if data[x, y] < threshold:
                out[base + (x >> 3)] |= 0x80 >> (x & 7)
    return bytes(out)


def blank(width: int, height: int) -> bytes:
    return b"\x00" * (((width + 7) // 8) * height)


def text_image(
    text: str,
    width: int = 1600,
    font_size: int = 28,
    margin: int = 32,
) -> Image.Image:
    """Renderiza texto com quebra de linha e devolve uma imagem L."""
    font = default_font(font_size)
    max_width = width - 2 * margin
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split(" ")
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if font.getlength(candidate) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        lines.append(current)

    line_height = font_size + 6
    height = margin * 2 + line_height * max(1, len(lines))
    # altura multipla de 8 evita sobras no ultimo byte
    height = (height + 7) // 8 * 8

    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    y = margin
    for line in lines:
        draw.text((margin, y), line, font=font, fill=0)
        y += line_height
    return image


def render_text(
    text: str,
    width: int = 1600,
    font_size: int = 28,
    margin: int = 32,
) -> tuple[bytes, int]:
    """Renderiza texto e devolve (raster 1-bit, altura)."""
    image = text_image(text, width, font_size, margin)
    return pack_bilevel(image), image.height


def render_image(
    path: str | Path,
    width: int = 1600,
    threshold: int = 128,
    rotate: int = 0,
) -> tuple[bytes, int]:
    """Carrega uma imagem, ajusta a largura e converte para 1-bit."""
    image = Image.open(path)
    if rotate:
        image = image.rotate(rotate, expand=True)
    image = image.convert("L")
    if image.width != width:
        ratio = width / image.width
        image = image.resize((width, max(1, round(image.height * ratio))),
                             Image.LANCZOS)
    height = (image.height + 7) // 8 * 8
    if height != image.height:
        canvas = Image.new("L", (width, height), 255)
        canvas.paste(image, (0, 0))
        image = canvas
    return pack_bilevel(image, threshold), height
