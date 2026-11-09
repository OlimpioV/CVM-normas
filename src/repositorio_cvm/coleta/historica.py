"""Coleta histórica (Fase 4): os atos do catálogo oficial da CVM que ainda não estão no acervo.

A lista vem da última leitura completa do catálogo de cada família (`ler-catalogo`, D-16). Cada ato é coletado
como os do gabarito (ficha, arquivos de texto e conversão), sem entrar no gabarito. O ato já presente no acervo
é reconhecido pela URL da ficha, a mesma chave usada no relatório de cobertura.

O identificador segue o padrão do acervo: "resolucao-cvm-175", "parecer-orientacao-cvm-32",
"oficio-circular-cvm-sse-03-2026", "nota-explicativa-resolucao-cvm-50". Sem dados para isso, usa-se o nome
da ficha na URL.

Piloto (`amostra`): N atos por família, espalhados pelo período coberto pelo catálogo (do mais antigo ao mais
recente), para medir formatos, falhas e tempo antes da coleta completa.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import urlparse

from repositorio_cvm.coleta.catalogo import FAMILIAS
from repositorio_cvm.gabarito import AtoGabarito, identificar_oficio

NUMERADAS = {"resolucao": "resolucao", "instrucao": "instrucao", "deliberacao": "deliberacao",
             "parecer_orientacao": "parecer-orientacao"}


def _slug(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def _nome_na_url(url: str) -> str:
    return _slug(PurePosixPath(urlparse(url).path).stem)


def identificador(familia: str, titulo: str, url: str, numero: int | None) -> str:
    if familia in NUMERADAS and numero:
        return f"{NUMERADAS[familia]}-cvm-{int(numero)}"
    if familia == "oficio_circular":
        ident = identificar_oficio(titulo)
        if ident.areas and ident.ano and (ident.anual or ident.numero):
            conjunto = "-conjunto" if len(ident.areas) > 1 or re.search(r"conjunt", titulo, re.I) else ""
            areas = "-".join(sorted(a.lower() for a in ident.areas))
            if ident.anual:
                return f"oficio-circular-anual{conjunto}-cvm-{areas}-{ident.ano}"
            return f"oficio-circular{conjunto}-cvm-{areas}-{ident.numero:02d}-{ident.ano}"
    if familia == "nota_explicativa" and titulo:
        # "Nota Explicativa à Resolução CVM 50" -> "nota-explicativa-resolucao-cvm-50"
        return re.sub(r"-0+(?=\d)", "-", re.sub(r"-(?:a|ao|da|do)-", "-", _slug(titulo)))
    return f"{familia.replace('_', '-')}-{_nome_na_url(url)}"


def _itens_catalogo(conexao: sqlite3.Connection, familia: str) -> list[sqlite3.Row]:
    leitura = conexao.execute("SELECT id FROM leitura_catalogo WHERE familia = ? AND terminada_em IS NOT NULL "
                              "ORDER BY id DESC LIMIT 1", (familia,)).fetchone()
    if leitura is None:
        return []
    return conexao.execute("SELECT * FROM catalogo_oficial WHERE familia = ? AND leitura_id = ? "
                           "ORDER BY data, numero, url", (familia, leitura["id"])).fetchall()


def _espalhados(itens: list, n: int) -> list:
    """n itens em intervalos regulares da lista ordenada por data (do mais antigo ao mais recente)."""
    if n >= len(itens):
        return list(itens)
    if n == 1:
        return [itens[-1]]
    passo = (len(itens) - 1) / (n - 1)
    return [itens[round(i * passo)] for i in range(n)]


def revogado_no_catalogo(item) -> bool:
    """O catálogo marca "(Revogada)" no título dos atos revogados. A ausência da marca não prova vigência: a
    situação de cada ato coletado vem da ficha (D-09); 18 resoluções revogadas não têm a marca no catálogo."""
    return "revogad" in f"{item['titulo'] or ''} {item['descricao'] or ''}".lower()


def a_coletar(conexao: sqlite3.Connection, familias: list[str] | None = None, amostra: int | None = None,
              limite: int | None = None, sem_revogados: bool = False) -> list[AtoGabarito]:
    """Atos do catálogo ainda não verificados no acervo. Com `amostra`, só N por família (piloto); com
    `sem_revogados`, sem os atos marcados como revogados no catálogo."""
    familias = familias or list(FAMILIAS)
    documentos = {r["url_oficial"]: r for r in conexao.execute(
        "SELECT id, url_oficial, ultima_verificacao FROM documento WHERE url_oficial IS NOT NULL")}
    ids = {r[0] for r in conexao.execute("SELECT id FROM documento")}
    saida: list[AtoGabarito] = []
    for familia in familias:
        itens = _itens_catalogo(conexao, familia)
        if sem_revogados:
            itens = [i for i in itens if not revogado_no_catalogo(i)]
        if amostra:
            # O piloto é escolhido sobre todo o catálogo da família (sem depender do que já foi coletado), para
            # ser o mesmo a cada retomada.
            itens = _espalhados(itens, amostra)
        escolhidos = []
        for item in itens:
            doc = documentos.get(item["url"])
            if doc is not None and doc["ultima_verificacao"]:
                continue
            chave = doc["id"] if doc is not None else identificador(familia, item["titulo"] or "", item["url"],
                                                                      item["numero"])
            if doc is None and chave in ids:
                chave = f"{chave}-{_nome_na_url(item['url'])}"  # mesmo identificador para outra ficha
            ids.add(chave)
            escolhidos.append(AtoGabarito(chave, familia, str(item["numero"]) if item["numero"] else None,
                                          f"{item['titulo']} (catálogo oficial, coleta histórica)", ficha=item["url"]))
        saida += escolhidos[:limite] if limite else escolhidos
    return saida
