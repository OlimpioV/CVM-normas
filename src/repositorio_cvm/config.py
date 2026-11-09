"""Configuração: lê `config.toml` (e `config.local.toml`, se existir) na raiz do projeto."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

RAIZ_PROJETO = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    pasta_dados: Path
    intervalo_minimo: float = 3.0
    retentativas: int = 3
    user_agent: str | None = None

    @property
    def originais(self) -> Path:
        return self.pasta_dados / "originais"

    @property
    def convertidos(self) -> Path:
        return self.pasta_dados / "convertidos"

    @property
    def banco(self) -> Path:
        return self.pasta_dados / "acervo.sqlite"

    @property
    def logs(self) -> Path:
        return self.pasta_dados / "logs"

    @property
    def relatorios(self) -> Path:
        return self.pasta_dados / "relatorios"

    @property
    def backups(self) -> Path:
        return self.pasta_dados / "backups"

    pasta_tessdata: Path | None = None

    @property
    def tessdata(self) -> Path:
        """Modelos de idioma do Tesseract para OCR (por.traineddata, de tesseract-ocr/tessdata_best)."""
        return self.pasta_tessdata or RAIZ_PROJETO / "ferramentas" / "tessdata"


def carregar(raiz: Path = RAIZ_PROJETO) -> Config:
    dados: dict = {}
    for nome in ("config.toml", "config.local.toml"):
        caminho = raiz / nome
        if caminho.is_file():
            with caminho.open("rb") as arquivo:
                dados.update(tomllib.load(arquivo))
    pasta = Path(dados.get("pasta_dados", "dados"))
    if not pasta.is_absolute():
        pasta = raiz / pasta
    coleta = dados.get("coleta", {})
    return Config(
        pasta_dados=pasta,
        intervalo_minimo=float(coleta.get("intervalo_minimo", 3.0)),
        retentativas=int(coleta.get("retentativas", 3)),
        user_agent=coleta.get("user_agent"),
    )
