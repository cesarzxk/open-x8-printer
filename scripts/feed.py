#!/usr/bin/env python3
"""Avança papel na impressora X8-04A1 usando o protocolo S8 (Marklife).

Uso:
    ./feed.py 100            # avança 100 mm
    ./feed.py 100 --channel 2

Protocolo extraído do APK com.feioou.deliprint.yxq (Marklife):
  wakeup        00 x 15
  enable        10 FF F1 03
  feed         1B 4A n      (n = pontos, máx. 255 por comando)
  stop          10 FF F1 45
"""
import argparse
import socket
import sys
import time

MAC = "41:1A:11:0A:04:A1"
DOTS_PER_MM = 8  # 203 dpi

WAKEUP = b"\x00" * 15
ENABLE = b"\x10\xff\xf1\x03"
STOP = b"\x10\xff\xf1\x45"


def feed_cmd(dots: int) -> bytes:
    out = b""
    while dots > 0:
        n = min(dots, 255)
        out += b"\x1b\x4a" + bytes([n])
        dots -= n
    return out


def build(mm: float, wakeup: bool = True) -> bytes:
    dots = round(mm * DOTS_PER_MM)
    seq = (WAKEUP if wakeup else b"") + ENABLE + feed_cmd(dots) + STOP
    return seq, dots


def send(seq: bytes, channel: int, timeout: float = 5.0, read: bool = True):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                      socket.BTPROTO_RFCOMM)
    s.settimeout(timeout)
    s.connect((MAC, channel))
    try:
        s.sendall(seq)
        time.sleep(0.5)
        if read:
            s.settimeout(1.0)
            try:
                data = s.recv(128)
                return data
            except socket.timeout:
                return b""
    finally:
        time.sleep(0.3)
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mm", type=float, help="quantidade de papel em milímetros")
    ap.add_argument("--channel", "-c", type=int, default=0,
                    help="canal RFCOMM (0 = todos: 1, 2, 3)")
    ap.add_argument("--no-wakeup", action="store_true")
    args = ap.parse_args()

    seq, dots = build(args.mm, wakeup=not args.no_wakeup)
    print(f"{dots} dots ({args.mm:g} mm @ {DOTS_PER_MM} dots/mm), "
          f"{len(seq)} bytes: {seq.hex(' ')}")

    channels = [1, 2, 3] if args.channel == 0 else [args.channel]
    for ch in channels:
        try:
            resp = send(seq, ch)
            print(f"canal {ch}: enviado" +
                  (f", resposta {resp.hex(' ')}" if resp else ", sem resposta"))
        except Exception as e:
            print(f"canal {ch}: erro {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
