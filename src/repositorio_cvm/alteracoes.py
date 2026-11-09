"""Normas alteradoras das normas do acervo (D-21).

Para aplicar alterações é preciso o texto das normas alteradoras. Elas vêm de duas fontes registradas no
banco, sempre com evidência:

- relação `alterada_por` da ficha oficial da norma alterada ("ALTERADA pelas Resoluções...");
- relação `altera` da norma alteradora (ementa "Altera a Resolução CVM nº 60...", caso da Res. 247, que as
  fichas das Res. 60 e 175 ainda não listam).

As alteradoras que ainda não estão no acervo são coletadas como documentos comuns (ficha, íntegra e
conversão), sem entrar no gabarito.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from repositorio_cvm import gabarito
from repositorio_cvm.gabarito import AtoGabarito

_URL_RESOLUCAO = re.compile(r"/legislacao/resolucoes/resol0*(\d+)\.html?$", re.I)


@dataclass(frozen=True)
class Alteradora:
    documento_id: str  # id no acervo (ex.: resolucao-cvm-194)
    numero: str
    url_ficha: str
    alteradas: tuple[str, ...]  # normas do acervo que ela altera


def id_da_resolucao(url: str | None) -> str | None:
    m = _URL_RESOLUCAO.search(url or "")
    return f"resolucao-cvm-{int(m.group(1))}" if m else None


def alteradoras(conexao: sqlite3.Connection, alvos: set[str] | None = None) -> list[Alteradora]:
    """Alteradoras conhecidas das normas `alvos` (padrão: as do gabarito), com as normas que cada uma altera.

    As alteradoras coletadas para a consolidação também trazem as suas próprias relações; elas não são seguidas,
    para que a coleta não se estenda em cascata."""
    alvos = alvos if alvos is not None else {a.chave for a in gabarito.carregar()}
    pares: dict[str, tuple[str, set[str]]] = {}
    for r in conexao.execute("SELECT documento_id, alvo_url FROM relacao WHERE tipo = 'alterada_por'"):
        if r["documento_id"] not in alvos:
            continue
        if ident := id_da_resolucao(r["alvo_url"]):
            pares.setdefault(ident, (r["alvo_url"], set()))[1].add(r["documento_id"])
    for r in conexao.execute("SELECT documento_id, alvo_url FROM relacao WHERE tipo = 'altera'"):
        alterada = id_da_resolucao(r["alvo_url"])
        if alterada not in alvos:
            continue
        url = conexao.execute("SELECT url_oficial FROM documento WHERE id = ?", (r["documento_id"],)).fetchone()
        if alterada and url:
            pares.setdefault(r["documento_id"], (url["url_oficial"], set()))[1].add(alterada)
    return [Alteradora(ident, ident.rsplit("-", 1)[1], url, tuple(sorted(alt)))
            for ident, (url, alt) in sorted(pares.items(), key=lambda kv: int(kv[0].rsplit("-", 1)[1]))]


def a_coletar(conexao: sqlite3.Connection) -> list[AtoGabarito]:
    """Alteradoras que ainda não foram coletadas, no formato que o coletor recebe."""
    feitos = {r[0] for r in conexao.execute("SELECT id FROM documento WHERE ultima_verificacao IS NOT NULL")}
    return [AtoGabarito(a.documento_id, "resolucao", a.numero,
                        f"Resolução CVM nº {a.numero}, alteradora de {', '.join(a.alteradas)} (coletada para a "
                        "consolidação, D-21)", ficha=a.url_ficha)
            for a in alteradoras(conexao) if a.documento_id not in feitos]
