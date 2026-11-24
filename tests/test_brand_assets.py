"""Check the bundled PNG assets without third-party imaging dependencies."""
import struct
import unittest
import zlib
from pathlib import Path

BRAND = Path(__file__).resolve().parents[1] / 'custom_components' / 'mova_nutripal' / 'brand'


def png_size(path):
    data = path.read_bytes()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('Invalid PNG signature')
    offset = 8
    dimensions = None
    while offset + 12 <= len(data):
        length, kind = struct.unpack_from('>I4s', data, offset)
        end = offset + 8 + length
        if end + 4 > len(data):
            raise ValueError('Truncated PNG chunk')
        payload = data[offset + 8:end]
        crc = struct.unpack_from('>I', data, end)[0]
        if zlib.crc32(kind + payload) != crc:
            raise ValueError('Invalid PNG CRC')
        if kind == b'IHDR':
            w, h, depth, color = struct.unpack_from('>IIBB', payload)
            if depth != 8 or color != 6:
                raise ValueError('Expected transparent RGBA PNG')
            dimensions = (w, h)
        offset = end + 4
        if kind == b'IEND' and offset == len(data) and dimensions:
            return dimensions
    raise ValueError('Incomplete PNG')


class BrandAssetTests(unittest.TestCase):
    def test_icon_dimensions(self):
        self.assertEqual(png_size(BRAND / 'icon.png'), (256, 256))
        self.assertEqual(png_size(BRAND / 'icon@2x.png'), (512, 512))

    def test_logo_dimensions(self):
        for prefix in ('', 'dark_'):
            with self.subTest(prefix=prefix):
                w, h = png_size(BRAND / f'{prefix}logo.png')
                hi_w, hi_h = png_size(BRAND / f'{prefix}logo@2x.png')
                self.assertEqual((h, hi_h), (256, 512))
                self.assertGreater(w, h)
                self.assertLessEqual(abs(hi_w - w * 2), 1)

    def test_theme_wordmarks_differ(self):
        self.assertNotEqual((BRAND / 'logo.png').read_bytes(),
                            (BRAND / 'dark_logo.png').read_bytes())
        self.assertEqual(png_size(BRAND / 'logo.png'),
                         png_size(BRAND / 'dark_logo.png'))
