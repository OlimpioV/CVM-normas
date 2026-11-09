"""Gabarito de validação (seção 19): lista de atos conferida pelo usuário."""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from repositorio_cvm.config import RAIZ_PROJETO

ARQUIVO_PADRAO = RAIZ_PROJETO / "tests" / "gabarito" / "gabarito.toml"
AREAS = {"SIN", "SSE", "SRE", "SEP", "SMI", "SNC", "SOI", "SGE", "SDM", "SPS", "SSR", "SMA", "SAD", "GNA",
         "GNC", "SFI", "SCI", "SEC", "SAS", "SFA", "SOC", "SSI"}


@dataclass(frozen=True)
class AtoGabarito:
    chave: str
    especie: str
    numero: str | None
    descricao_usuario: str
    ficha: str | None = None
    areas: frozenset[str] = field(default_factory=frozenset)
    ano: int | None = None
    anual: bool = False


def carregar(caminho: Path = ARQUIVO_PADRAO) -> list[AtoGabarito]:
    with caminho.open("rb") as arquivo:
        dados = tomllib.load(arquivo)
    atos = []
    for item in dados["ato"]:
        loc = item.get("localizar", {})
        atos.append(AtoGabarito(
            chave=item["chave"],
            especie=item["especie"],
            numero=item.get("numero"),
            descricao_usuario=item["descricao_usuario"],
            ficha=item.get("ficha"),
            areas=frozenset(loc.get("areas", [])),
            ano=loc.get("ano"),
            anual=bool(loc.get("anual", False)),
        ))
    return atos


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


@dataclass(frozen=True)
class IdentidadeOficio:
    areas: frozenset[str]
    numero: int | None
    ano: int | None
    anual: bool


def identificar_oficio(titulo: str) -> IdentidadeOficio:
    """'Ofício Circular CVM/SSE 03/26' -> ({SSE}, 3, 2026); 'Ofício Circular nº 4/2026/CVM/SMI' -> ({SMI}, 4, 2026)."""
    simples = _sem_acento(titulo).upper()
    areas = frozenset(t for t in re.findall(r"(?<![A-Z])[A-Z]{3}(?![A-Z])", simples) if t in AREAS)
    anual = "ANUAL" in simples
    numero = ano = None
    if anual:
        m = re.search(r"ANUAL\D*(\d{4})", simples) or re.search(r"(\d{4})", simples)
        ano = int(m.group(1)) if m else None
    else:
        m = re.search(r"(\d{1,3})\s*/\s*(\d{4}|\d{2})\b", simples)
        if m:
            numero = int(m.group(1))
            # Ano com dois dígitos: a CVM é de 1976 ("02/96" é 1996, "03/26" é 2026).
            ano = int(m.group(2)) if len(m.group(2)) == 4 else (1900 if int(m.group(2)) >= 76 else 2000) + int(m.group(2))
    return IdentidadeOficio(areas, numero, ano, anual)


def oficio_corresponde(ato: AtoGabarito, titulo: str) -> bool:
    ident = identificar_oficio(titulo)
    if ident.areas != ato.areas or ident.ano != ato.ano or ident.anual != ato.anual:
        return False
    return ato.anual or (ato.numero is not None and ident.numero == int(ato.numero))
