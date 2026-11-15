"""Pacotes do protocolo X8 (protocol id 10) da Marklife.

Formato extraido de `com.feioou.deliprint.yxq.factory.protocol.X8Protocol`:

  config   1F FD 01 A5 <param> <valor>
  faixa    1F 01 05 A5 <wL wH hL hH lenL lenH> + JBIG
  fim      1F 01 06 A5 <01|02>

- largura e altura em dots, little-endian
- cada faixa tem no maximo 100 linhas
- o payload de cada faixa e uma imagem JBIG (ITU-T T.82) independente
"""

from __future__ import annotations

import struct

PROTOCOL_ID = 10

CONFIG_MAGIC = b"\x1f\xfd\x01\xa5"
BAND_MAGIC = b"\x1f\x01\x05\xa5"
END_MAGIC = b"\x1f\x01\x06\xa5"

STATUS_QUERY = b"\x10\x04\x0a\xa5"

MAX_BAND_ROWS = 100

# Parametros fixos observados no app. O significado e inferido do contexto.
PARAM_FIXED = 0x10
PARAM_SPEED = 2
PARAM_ECHO = 3
PARAM_MODE = 4
PARAM_DENSITY = 5
PARAM_LENGTH = 6
PARAM_ENTER_PAGE = 8
PARAM_ALGORITHM = 9
PARAM_PAPER_TYPE = 10


def _param(index: int, value: int) -> bytes:
    return CONFIG_MAGIC + bytes([index, value & 0xFF])


def build_config(
    density: int = 2,
    speed: int = 30,
    paper_type: int = 2,
    enter_page: int = 1,
    algorithm: int = 1,
) -> bytes:
    """Monta o bloco de configuracao que precede cada job.

    paper_type: 1 = imagem/rolo, 2 = documento/texto (padrao do app),
                3 = papel de tatuagem.
    enter_page: 1 = normal, 2 = imagem, 3 = digitalizacao, 4 = web,
                5 = tatuagem.
    algorithm: 1 = padrao, 2 = imagem (dithering alternativo).

    O parametro 7 (backPaperNum no modelo) foi testado e nao e retrocesso:
    com ele o firmware ignora o job. Nao enviamos.
    """
    params = [
        (1, PARAM_FIXED),
        (PARAM_SPEED, speed),
        (PARAM_ECHO, 1),
        (PARAM_MODE, 2),
        (PARAM_DENSITY, density),
        (PARAM_LENGTH, 0x30),
        (PARAM_ENTER_PAGE, enter_page),
        (PARAM_ALGORITHM, algorithm),
        (PARAM_PAPER_TYPE, paper_type),
    ]
    return b"".join(_param(index, value) for index, value in params)


def build_band(width_dots: int, height_dots: int, jbig: bytes) -> bytes:
    """Monta uma faixa (<= 100 linhas) com payload JBIG."""
    if width_dots % 8:
        raise ValueError("largura precisa ser multipla de 8")
    if not 1 <= height_dots <= MAX_BAND_ROWS:
        raise ValueError(f"altura da faixa deve ser 1..{MAX_BAND_ROWS}")
    width_bytes = width_dots // 8
    header = BAND_MAGIC + struct.pack(
        "<HHH", width_bytes, height_dots, len(jbig)
    )
    return header + jbig


def end_job(last_copy: bool = True) -> bytes:
    """Terminador do job. 02 = ultima copia, 01 = ainda ha copias."""
    return END_MAGIC + bytes([2 if last_copy else 1])


def split_bands(height_dots: int, rows: int = MAX_BAND_ROWS) -> list[int]:
    """Divide uma altura total em faixas de no maximo `rows` linhas."""
    out: list[int] = []
    remaining = height_dots
    while remaining > 0:
        out.append(min(rows, remaining))
        remaining -= out[-1]
    return out


def build_job(
    width_dots: int,
    height_dots: int,
    encode_band,
    *,
    density: int = 2,
    speed: int = 30,
    paper_type: int = 2,
    enter_page: int = 1,
    algorithm: int = 1,
    last_copy: bool = True,
) -> bytes:
    """Monta um job completo.

    `encode_band(top, rows)` deve devolver os bytes JBIG da faixa que
    comeca na linha `top` e tem `rows` linhas.

    `last_copy=False` usa o terminador 01 (pagina nao final); em alguns
    modelos isso evita a ejeção da folha ao fim do job.
    """
    chunks = [build_config(density, speed, paper_type, enter_page, algorithm)]
    top = 0
    for rows in split_bands(height_dots):
        jbig = encode_band(top, rows)
        chunks.append(build_band(width_dots, rows, jbig))
        top += rows
    chunks.append(end_job(last_copy))
    return b"".join(chunks)
