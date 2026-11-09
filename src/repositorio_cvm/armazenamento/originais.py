"""Armazenamento imutável dos arquivos originais, endereçado pelo SHA-256 dos bytes.

Caminho: `<dados>/originais/<2 primeiros caracteres>/<sha256>.<extensão>`. Um arquivo já
gravado nunca é sobrescrito; se existir com conteúdo diferente do hash, é erro de integridade.
Cada original fica com o atributo "somente leitura" (a biblioteca legível usa vínculos para ele).
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

_EXTENSOES = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "application/rss+xml": "xml",
    "text/xml": "xml",
}


class IntegridadeError(Exception):
    pass


def extensao(content_type: str | None, url: str = "") -> str:
    tipo = (content_type or "").split(";", 1)[0].strip().lower()
    if tipo in _EXTENSOES:
        return _EXTENSOES[tipo]
    sufixo = Path(url.split("?", 1)[0]).suffix.lower().lstrip(".")
    return {"htm": "html"}.get(sufixo, sufixo) or "bin"


def caminho_relativo(sha256: str, ext: str) -> Path:
    return Path("originais") / sha256[:2] / f"{sha256}.{ext}"


def gravar(pasta_dados: Path, dados: bytes, content_type: str | None, url: str = "") -> tuple[str, Path]:
    """Grava os bytes (se ainda não existirem) e devolve (sha256, caminho relativo à pasta de dados)."""
    sha = hashlib.sha256(dados).hexdigest()
    relativo = caminho_relativo(sha, extensao(content_type, url))
    destino = pasta_dados / relativo
    if destino.exists():
        if hashlib.sha256(destino.read_bytes()).hexdigest() != sha:
            raise IntegridadeError(f"arquivo existente não confere com o hash: {destino}")
        return sha, relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(destino.suffix + ".tmp")
    temporario.write_bytes(dados)
    os.replace(temporario, destino)
    destino.chmod(stat.S_IREAD)
    return sha, relativo


def verificar(pasta_dados: Path, relativo: Path | str, sha256: str) -> bool:
    caminho = pasta_dados / relativo
    return caminho.is_file() and hashlib.sha256(caminho.read_bytes()).hexdigest() == sha256
