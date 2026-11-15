#!/usr/bin/env python3
"""Teste: imprime uma faixa em branco (sem marcas) e avança o papel.

O motor da X8 só engata durante um job de bitmap; um feed isolado é ignorado.
Sequência extraída do APK Marklife (PrintS8 / DeviceManager.printS8):

    wakeup      00 x 15
    enable      10 FF F1 03
    bitmap      1F 10 wH wL hH hL len4 + zlib(wbits=10, level=6)
    feed        1B 4A n
    stop        10 FF F1 45
"""
import argparse
import socket
import sys
import time
import zlib

MAC = "41:1A:11:0A:04:A1"
DOTS_PER_MM = 8

WAKEUP = b"\x00" * 15
ENABLE = b"\x10\xff\xf1\x03"
STOP = b"\x10\xff\xf1\x45"


def blank_bitmap(width_dots: int, height_dots: int) -> bytes:
    width_bytes = (width_dots + 7) // 8
    raw = b"\x00" * (width_bytes * height_dots)  # 0 = branco (sem tinta)
    co = zlib.compressobj(6, zlib.DEFLATED, 10)  # igual a DFunction.code
    comp = co.compress(raw) + co.flush()
    header = (b"\x1f\x10"
              + bytes([(width_bytes >> 8) & 0xFF, width_bytes & 0xFF])
              + bytes([(height_dots >> 8) & 0xFF, height_dots & 0xFF])
              + len(comp).to_bytes(4, "big"))
    return header + comp


def build(mm: float, width_dots: int = 1728) -> bytes:
    dots = round(mm * DOTS_PER_MM)
    return WAKEUP + ENABLE + blank_bitmap(width_dots, dots) + STOP


def send(seq: bytes, channel: int):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                      socket.BTPROTO_RFCOMM)
    s.settimeout(5)
    s.connect((MAC, channel))
    try:
        s.sendall(seq)
        time.sleep(1.0)
        s.settimeout(2.0)
        try:
            return s.recv(64)
        except socket.timeout:
            return b""
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mm", type=float, default=5, nargs="?")
    ap.add_argument("--channel", "-c", type=int, default=3)
    ap.add_argument("--width", type=int, default=1728)
    args = ap.parse_args()

    seq = build(args.mm, args.width)
    print(f"{args.mm:g} mm = {round(args.mm * DOTS_PER_MM)} linhas, "
          f"{len(seq)} bytes, canal {args.channel}")
    try:
        resp = send(seq, args.channel)
        print("resposta:", resp.hex(" ") if resp else "(nenhuma)")
    except Exception as e:
        print("erro:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
