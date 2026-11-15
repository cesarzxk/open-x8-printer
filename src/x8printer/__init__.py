"""Pacote de controle da impressora Marklife X8 (X8-04A1).

Protocolo extraido por engenharia reversa do APK com.feioou.deliprint.yxq.
"""

from .protocol import (
    PROTOCOL_ID,
    build_band,
    build_config,
    build_job,
    end_job,
    split_bands,
)
from .transport import Printer, PrinterError

__all__ = [
    "PROTOCOL_ID",
    "build_config",
    "build_band",
    "build_job",
    "end_job",
    "split_bands",
    "Printer",
    "PrinterError",
]
