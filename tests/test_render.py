"""Testes de renderizacao/polaridade (1 = preto)."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from src import render


class PackTest(unittest.TestCase):
    def test_blank_is_zero(self):
        self.assertEqual(set(render.blank(32, 4)), {0})

    def test_left_half_black(self):
        image = Image.new("L", (16, 8), 255)
        image.paste(0, (0, 0, 8, 8))
        packed = render.pack_bilevel(image)
        for row in range(8):
            self.assertEqual(packed[row * 2], 0xFF)
            self.assertEqual(packed[row * 2 + 1], 0x00)

    def test_text_has_ink(self):
        image = render.text_image("X8-04A1", 400, 40, 10)
        packed = render.pack_bilevel(image)
        self.assertTrue(any(packed), "texto deveria gerar pixels pretos")

    def test_render_text_shape(self):
        raster, height = render.render_text("teste", 320, 24, 8)
        self.assertEqual(len(raster), (320 // 8) * height)
        self.assertEqual(height % 8, 0)


if __name__ == "__main__":
    unittest.main()
