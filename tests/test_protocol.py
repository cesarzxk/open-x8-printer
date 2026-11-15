"""Testes dos pacotes do protocolo X8 (sem hardware)."""

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import protocol


class ConfigTest(unittest.TestCase):
    def test_default_config_matches_app(self):
        expected = bytes.fromhex(
            "1ffd01a50110"  # param 1  = 0x10
            "1ffd01a5021e"  # param 2  = speed 30
            "1ffd01a50301"  # param 3  = 1
            "1ffd01a50402"  # param 4  = 2
            "1ffd01a50502"  # param 5  = densidade 2
            "1ffd01a50630"  # param 6  = 0x30
            "1ffd01a50801"  # param 8  = enter page 1
            "1ffd01a50901"  # param 9  = algoritmo 1
            "1ffd01a50a02"  # param 10 = paper type 2
        )
        self.assertEqual(protocol.build_config(), expected)


class BandTest(unittest.TestCase):
    def test_band_header(self):
        jbig = b"\x00\x01\x02"
        packet = protocol.build_band(1600, 100, jbig)
        self.assertEqual(packet[:4], bytes.fromhex("1f0105a5"))
        width_bytes, height, length = struct.unpack("<HHH", packet[4:10])
        self.assertEqual(width_bytes, 200)
        self.assertEqual(height, 100)
        self.assertEqual(length, len(jbig))
        self.assertEqual(packet[10:], jbig)

    def test_band_height_limit(self):
        with self.assertRaises(ValueError):
            protocol.build_band(1600, 101, b"")

    def test_split_bands(self):
        self.assertEqual(protocol.split_bands(0), [])
        self.assertEqual(protocol.split_bands(100), [100])
        self.assertEqual(protocol.split_bands(250), [100, 100, 50])

    def test_end_job(self):
        self.assertEqual(protocol.end_job(), bytes.fromhex("1f0106a502"))
        self.assertEqual(protocol.end_job(False), bytes.fromhex("1f0106a501"))


if __name__ == "__main__":
    unittest.main()
