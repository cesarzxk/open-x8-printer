"""Transporte Bluetooth RFCOMM (SPP) para a X8.

O app Android usa `createRfcommSocketToServiceRecord(SPP)`. No Linux
conectamos direto nos canais RFCOMM expostos pela impressora; o canal 3
foi o que aceitou conexao nos testes, mas tentamos 3, 2 e 1 em ordem.
"""

from __future__ import annotations

import socket
import time

DEFAULT_MAC = "41:1A:11:0A:04:A1"
DEFAULT_CHANNELS = (3, 2, 1)


class PrinterError(RuntimeError):
    pass


class Printer:
    """Conexao RFCOMM com reconexao e envio em blocos de 512 bytes."""

    def __init__(
        self,
        mac: str = DEFAULT_MAC,
        channels: tuple[int, ...] = DEFAULT_CHANNELS,
        timeout: float = 6.0,
    ) -> None:
        self.mac = mac
        self.channels = channels
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.channel: int | None = None

    def connect(self) -> int:
        errors = []
        for channel in self.channels:
            sock = socket.socket(
                socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM
            )
            sock.settimeout(self.timeout)
            try:
                sock.connect((self.mac, channel))
            except OSError as exc:
                errors.append(f"canal {channel}: {exc}")
                sock.close()
                continue
            self.sock = sock
            self.channel = channel
            return channel
        raise PrinterError("nao foi possivel conectar: " + "; ".join(errors))

    def send(
        self,
        data: bytes,
        chunk: int = 512,
        delay: float = 0.02,
        read_timeout: float = 1.5,
    ) -> bytes:
        if self.sock is None:
            self.connect()
        assert self.sock is not None
        for offset in range(0, len(data), chunk):
            self.sock.sendall(data[offset:offset + chunk])
            if delay:
                time.sleep(delay)
        return self.read(read_timeout)

    def read(self, timeout: float = 1.5) -> bytes:
        if self.sock is None:
            return b""
        old = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        try:
            return self.sock.recv(256)
        except (socket.timeout, OSError):
            return b""
        finally:
            if self.sock is not None:
                self.sock.settimeout(old)

    def wait_done(self, timeout: float = 30.0) -> bool:
        """Espera o ACK de fim de impressao (0xAA ou 'OK').

        Devolve False em timeout/desconexao; o chamador pode seguir mesmo
        assim (a impressora costuma concluir o job em fila).
        """
        if self.sock is None:
            return False
        end = time.time() + timeout
        buf = b""
        self.sock.settimeout(0.5)
        while time.time() < end:
            try:
                chunk = self.sock.recv(64)
            except socket.timeout:
                continue
            except OSError:
                return False
            if not chunk:
                return False
            buf += chunk
            if b"\xaa" in buf or b"OK" in buf:
                return True
        return False

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None
                self.channel = None

    def __enter__(self) -> "Printer":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
