"""Codificacao JBIG (ITU-T T.82) usando o jbigkit do sistema.

O app usa `libjbigkit` com os defaults (ordem 0, options 0, sem camadas
diferenciais), que corresponde a `pbmtojbg -q -o 0 -p 0`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_pbmtojbg() -> str | None:
    env = os.environ.get("X8_PBMTOJBG") or os.environ.get("PBMTOJBG")
    if env and Path(env).is_file():
        return env

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
        candidates += [base / "pbmtojbg", base / "pbmtojbg.exe"]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates += [Path(meipass) / "pbmtojbg",
                           Path(meipass) / "pbmtojbg.exe"]

    found = shutil.which("pbmtojbg")
    if found:
        return found
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


PBMTOJBG = _find_pbmtojbg()


class JbigError(RuntimeError):
    pass


def available() -> bool:
    return PBMTOJBG is not None


def encode_pbm(width: int, height: int, raster: bytes) -> bytes:
    """Codifica um raster PBM (1 bit/pixel, MSB primeiro, 1 = preto)."""
    if PBMTOJBG is None:
        raise JbigError(
            "pbmtojbg nao encontrado; instale com: sudo apt install jbigkit-bin"
        )
    expected = ((width + 7) // 8) * height
    if len(raster) != expected:
        raise ValueError(f"raster tem {len(raster)} bytes, esperado {expected}")

    with tempfile.TemporaryDirectory() as td:
        pbm = Path(td) / "band.pbm"
        jbg = Path(td) / "band.jbg"
        pbm.write_bytes(f"P4\n{width} {height}\n".encode() + raster)
        flags = 0x08000000 if os.name == "nt" else 0
        subprocess.run(
            [PBMTOJBG, "-q", "-o", "0", "-p", "0", str(pbm), str(jbg)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return jbg.read_bytes()
