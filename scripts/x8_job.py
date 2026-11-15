#!/usr/bin/env python3
"""Job de impressao para a X8-04A1 (Marklife, protocolo 10 / X8Protocol).

Extraido do APK com.feioou.deliprint.yxq:

  config:  1F FD 01 A5 <param> <valor>   (params 1..10)
  faixa:   1F 01 05 A5 wL wH hL hH lenL lenH + JBIG(T.82)
  fim:     1F 01 06 A5 02

Faixas tem no maximo 100 linhas (o app divide assim). Cada faixa e uma
imagem JBIG independente, codificada com jbigkit.
"""
import argparse
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MAC = "41:1A:11:0A:04:A1"
DOTS_PER_MM = 8
BAND_ROWS = 100


def encode_jbig(width: int, height: int, sequential: bool = True) -> bytes:
    """Codifica uma imagem toda branca em JBIG via pbmtojbg.

    O app usa jbigkit com defaults (ordem 0, options 0, sem camadas
    diferenciais) — equivalente a `-q -o 0 -p 0`.
    """
    raw = b"\x00" * (((width + 7) // 8) * height)
    with tempfile.TemporaryDirectory() as td:
        pbm = Path(td) / "b.pbm"
        jbg = Path(td) / "b.jbg"
        pbm.write_bytes(f"P4\n{width} {height}\n".encode() + raw)
        cmd = ["pbmtojbg"]
        if sequential:
            cmd.append("-q")
        cmd += ["-o", "0", "-p", "0", str(pbm), str(jbg)]
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return jbg.read_bytes()


def config(density: int = 2, speed: int = 30,
           paper_type: int = 2, algorithm: int = 1) -> bytes:
    def p(param: int, value: int) -> bytes:
        return bytes([0x1F, 0xFD, 0x01, 0xA5, param, value & 0xFF])
    out = b""
    out += p(1, 0x10)
    out += p(2, speed)
    out += p(3, 1)
    out += p(4, 2)
    out += p(5, density)
    out += p(6, 0x30)
    out += p(8, 1)
    out += p(9, algorithm)
    out += p(10, paper_type)
    return out


def band(width: int, height: int, sequential: bool = False) -> bytes:
    data = encode_jbig(width, height, sequential)
    wb = width // 8
    header = (b"\x1F\x01\x05\xA5"
              + bytes([wb & 0xFF, (wb >> 8) & 0xFF])
              + bytes([height & 0xFF, (height >> 8) & 0xFF])
              + bytes([len(data) & 0xFF, (len(data) >> 8) & 0xFF]))
    return header + data


def job(mm: float, width: int, sequential: bool,
        density: int, speed: int, paper_type: int) -> bytes:
    rows = round(mm * DOTS_PER_MM)
    out = config(density, speed, paper_type)
    done = 0
    while done < rows:
        h = min(BAND_ROWS, rows - done)
        out += band(width, h, sequential)
        done += h
    out += b"\x1F\x01\x06\xA5\x02"
    return out


def send(data: bytes, channel: int):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                      socket.BTPROTO_RFCOMM)
    s.settimeout(6)
    s.connect((MAC, channel))
    try:
        for i in range(0, len(data), 512):
            s.sendall(data[i:i + 512])
            time.sleep(0.02)
        time.sleep(1.5)
        s.settimeout(2.0)
        try:
            return s.recv(256)
        except socket.timeout:
            return b""
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mm", type=float)
    ap.add_argument("--channel", "-c", type=int, default=3)
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--density", type=int, default=2)
    ap.add_argument("--speed", type=int, default=30)
    ap.add_argument("--paper-type", type=int, default=2,
                    help="1=imagem/rolo, 2=documento (padrao do app), 3=tatuagem")
    ap.add_argument("--differential", action="store_true",
                    help="usa camadas diferenciais (nao use na X8)")
    ap.add_argument("--save", metavar="FILE")
    args = ap.parse_args()

    data = job(args.mm, args.width, not args.differential,
               args.density, args.speed, args.paper_type)
    print(f"{args.mm:g} mm = {round(args.mm * DOTS_PER_MM)} linhas, "
          f"job {len(data)} bytes, {args.width} dots de largura")
    if args.save:
        Path(args.save).write_bytes(data)
        print("salvo em", args.save)
    try:
        resp = send(data, args.channel)
        print("resposta:", resp if resp else "(nenhuma)")
    except Exception as e:
        print("erro:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
