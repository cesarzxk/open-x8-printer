"""CLI da X8-04A1."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import jbig, protocol, render
from .transport import DEFAULT_MAC, Printer, PrinterError

DEFAULT_WIDTH = 1600  # 200 mm a 203 dpi


def _encode_band(raster: bytes, width: int):
    stride = width // 8

    def encode(top: int, rows: int) -> bytes:
        chunk = raster[top * stride:(top + rows) * stride]
        return jbig.encode_pbm(width, rows, chunk)

    return encode


def _build(args, raster: bytes, height: int) -> bytes:
    paper_type = args.paper_type
    if paper_type is None:
        # feed usa modo continuo (para no meio da folha); impressao usa
        # modo documento (ejeta a pagina inteira)
        paper_type = 1 if args.command == "feed" else 2
    return protocol.build_job(
        args.width,
        height,
        _encode_band(raster, args.width),
        density=args.density,
        speed=args.speed,
        paper_type=paper_type,
        enter_page=args.enter_page,
        algorithm=args.algorithm,
        last_copy=not args.no_eject,
    )


def _send_or_save(args, data: bytes) -> int:
    print(f"job: {len(data)} bytes")
    if args.save:
        Path(args.save).write_bytes(data)
        print("salvo em", args.save)
    if args.dry_run:
        return 0
    printer = Printer(args.mac, (args.channel,) if args.channel else (3, 2, 1))
    try:
        channel = printer.connect()
        print(f"conectado no canal {channel}")
        response = printer.send(data, delay=args.delay)
        print("resposta:", response.hex(" ") if response else "(nenhuma)")
        return 0
    except (PrinterError, OSError) as exc:
        print("erro:", exc, file=sys.stderr)
        return 1
    finally:
        printer.close()


def cmd_feed(args) -> int:
    rows = max(1, round(args.mm * 8))
    raster = render.blank(args.width, rows)
    return _send_or_save(args, _build(args, raster, rows))


def cmd_text(args) -> int:
    text = " ".join(args.text) if args.text else sys.stdin.read()
    raster, height = render.render_text(
        text, args.width, args.font_size, args.margin
    )
    print(f"texto: {height} linhas ({height / 8:.1f} mm)")
    return _send_or_save(args, _build(args, raster, height))


def cmd_image(args) -> int:
    raster, height = render.render_image(
        args.path, args.width, args.threshold, args.rotate
    )
    print(f"imagem: {height} linhas ({height / 8:.1f} mm)")
    return _send_or_save(args, _build(args, raster, height))


def cmd_raw(args) -> int:
    data = Path(args.path).read_bytes()
    return _send_or_save(args, data)


def cmd_status(args) -> int:
    printer = Printer(args.mac, (args.channel,) if args.channel else (3, 2, 1))
    try:
        printer.connect()
        response = printer.send(protocol.STATUS_QUERY, delay=0, read_timeout=2.0)
    except (PrinterError, OSError) as exc:
        print("erro:", exc, file=sys.stderr)
        return 1
    finally:
        printer.close()

    if not response:
        print("sem resposta")
        return 1
    try:
        status = json.loads(response.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        print("resposta:", response.hex(" "))
        return 1

    labels = {
        "bat": "bateria (%)",
        "t": "temperatura",
        "paper": "papel (0=ok)",
        "cover": "tampa (0=fechada)",
        "busy": "ocupada (0=livre)",
    }
    for key, value in status.items():
        print(f"{labels.get(key, key):20} {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="x8", description=__doc__)
    parser.add_argument("--mac", default=os.environ.get("X8_MAC", DEFAULT_MAC))
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--density", type=int, default=2, choices=range(1, 4))
    parser.add_argument("--speed", type=int, default=30)
    parser.add_argument("--paper-type", type=int, default=None,
                        choices=(1, 2, 3),
                        help="1=continuo/rolo (feed), 2=documento (padrao), 3=tatuagem")
    parser.add_argument("--enter-page", type=int, default=1)
    parser.add_argument("--algorithm", type=int, default=1, choices=(1, 2))
    parser.add_argument("--channel", type=int, default=None,
                        help="canal RFCOMM fixo (padrao: tenta 3, 2, 1)")
    parser.add_argument("--delay", type=float, default=0.02)
    parser.add_argument("--save", metavar="FILE")
    parser.add_argument("--no-eject", action="store_true",
                        help="usa terminador de pagina nao-final (evita ejetar)")
    parser.add_argument("--dry-run", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p_feed = sub.add_parser("feed", help="avanca papel em branco")
    p_feed.add_argument("mm", type=float)
    p_feed.set_defaults(func=cmd_feed)

    p_text = sub.add_parser("text", help="imprime texto")
    p_text.add_argument("text", nargs="*")
    p_text.add_argument("--font-size", type=int, default=28)
    p_text.add_argument("--margin", type=int, default=32)
    p_text.set_defaults(func=cmd_text)

    p_image = sub.add_parser("image", help="imprime uma imagem")
    p_image.add_argument("path")
    p_image.add_argument("--threshold", type=int, default=128)
    p_image.add_argument("--rotate", type=int, default=0)
    p_image.set_defaults(func=cmd_image)

    p_raw = sub.add_parser("raw", help="envia um arquivo de job pronto")
    p_raw.add_argument("path")
    p_raw.set_defaults(func=cmd_raw)

    p_status = sub.add_parser("status", help="consulta bateria/papel/tampa")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
