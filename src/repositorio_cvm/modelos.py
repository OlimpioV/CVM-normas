"""Registro imutável de um arquivo baixado, compartilhado pela coleta e pelo armazenamento."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Artifact:
    """Os bytes exatamente como recebidos da fonte, com o SHA-256 deles e os dados da resposta.

    O hash identifica o original imutável: nunca descreve texto convertido ou normalizado.
    """

    url: str
    bytes: bytes
    content_type: str
    sha256: str
    fetched_at: str  # ISO 8601 em UTC
    etag: str | None = None
    last_modified: str | None = None

    def __post_init__(self) -> None:
        partes = urlsplit(self.url)
        if partes.scheme not in ("http", "https") or not partes.hostname:
            raise ValueError(f"URL de origem deve ser absoluta (http/https): {self.url!r}")
        if not isinstance(self.bytes, bytes):
            raise TypeError("o conteúdo deve ser bytes")
        if hashlib.sha256(self.bytes).hexdigest() != self.sha256:
            raise ValueError("SHA-256 não corresponde ao conteúdo")
        quando = datetime.fromisoformat(self.fetched_at.replace("Z", "+00:00"))
        if quando.utcoffset() != timedelta(0):
            raise ValueError("a data da coleta deve estar em UTC")

    @classmethod
    def from_bytes(cls, url: str, data: bytes, content_type: str, fetched_at: str | None = None,
                   etag: str | None = None, last_modified: str | None = None) -> Artifact:
        return cls(url, data, content_type, hashlib.sha256(data).hexdigest(),
                   fetched_at or datetime.now(timezone.utc).isoformat(), etag, last_modified)
