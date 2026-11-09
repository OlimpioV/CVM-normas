"""Leitura completa do catálogo oficial da CVM, para medir o acervo em relação à base da CVM.

Percorre todas as páginas da pesquisa de legislação de uma família (10 itens por página) e guarda título,
data, descrição e URL de cada ato. Não baixa fichas nem arquivos. A leitura é "completa" só quando a
quantidade de atos distintos lidos bate com o total informado pela própria página ("N resultados
encontrados"); caso contrário fica "incompleta" e o relatório avisa, em vez de apresentar números errados.
Se a própria CVM informar totais diferentes em páginas diferentes da mesma pesquisa e a quantidade lida bater
com um deles, a leitura fica "divergente na fonte", com a explicação registrada.
"""

from __future__ import annotations

import logging
import re

from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.coleta.catalogo import FAMILIAS, ler_pagina_catalogo, url_catalogo
from repositorio_cvm.coleta.coletor import Coletor
from repositorio_cvm.coleta.http import FetchError

log = logging.getLogger("repositorio_cvm.inventario")

# Espécies numeradas em sequência única: permitem apontar números ausentes do catálogo.
NUMERADAS = {"resolucao", "instrucao", "deliberacao", "parecer_orientacao"}
_NUMERO = re.compile(r"\bCVM\s*(?:n[º°o.]*\s*)?(\d+)\b", re.I)


def numero_do_titulo(familia: str, titulo: str | None) -> int | None:
    if familia not in NUMERADAS or not titulo:
        return None
    m = _NUMERO.search(titulo)
    return int(m.group(1)) if m else None


def ler_catalogo(coletor: Coletor, familia: str, ao_avancar=None) -> dict:
    """Lê todas as páginas do catálogo de `familia`. Bloqueio interrompe (ColetaInterrompida propaga)."""
    db = coletor.db
    leitura_id = db.execute("INSERT INTO leitura_catalogo (familia, iniciada_em, status) VALUES (?, ?, 'em andamento')",
                            (familia, agora())).lastrowid
    db.commit()
    vistos: set[str] = set()
    total_informado = paginas = None
    totais: dict[int, list[int]] = {}  # total informado -> páginas que o informam
    observacao = None
    pagina = lidas = 0
    status = "interrompida"
    try:
        while True:
            pagina += 1
            url = url_catalogo(familia, pagina)
            try:
                artefato = coletor.baixar(url, f"catalogo:{familia}", "html")
            except FetchError as erro:
                log.warning("%s: página %d não obtida: %s", familia, pagina, erro)
                status = "incompleta"
                break
            resultado = ler_pagina_catalogo(artefato.bytes, url)
            lidas += 1
            if resultado.total_resultados is not None:
                totais.setdefault(resultado.total_resultados, []).append(pagina)
            if pagina == 1:
                total_informado, paginas = resultado.total_resultados, resultado.total_paginas
            if paginas and pagina < paginas and len(resultado.itens) != 10:
                log.warning("%s: página %d com %d itens (esperados 10)", familia, pagina, len(resultado.itens))
            for item in resultado.itens:
                if item.url in vistos:
                    log.warning("%s: ato repetido na página %d: %s (%s)", familia, pagina, item.titulo, item.url)
                vistos.add(item.url)
                db.execute(
                    "INSERT INTO catalogo_oficial (url, familia, titulo, data, descricao, numero, leitura_id, primeira_vez) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET familia = excluded.familia, "
                    "titulo = excluded.titulo, data = excluded.data, descricao = excluded.descricao, "
                    "numero = excluded.numero, leitura_id = excluded.leitura_id",
                    (item.url, familia, item.titulo, item.data, item.descricao, numero_do_titulo(familia, item.titulo),
                     leitura_id, agora()))
            db.execute("UPDATE leitura_catalogo SET paginas_lidas = ?, total_lido = ?, total_informado = ?, "
                       "paginas_informadas = ? WHERE id = ?", (lidas, len(vistos), total_informado, paginas, leitura_id))
            db.commit()
            if ao_avancar:
                ao_avancar(familia, pagina, paginas, len(vistos), total_informado)
            if not resultado.itens or (paginas and pagina >= paginas):
                if total_informado is not None and len(vistos) == total_informado and len(totais) == 1:
                    status = "completa"
                elif len(totais) > 1 and len(vistos) in totais:
                    status = "divergente na fonte"
                    observacao = ("a CVM informa totais diferentes na mesma pesquisa: " + "; ".join(
                        f"{t} (página{'s' if len(p) > 1 else ''} {_paginas(p)})" for t, p in sorted(totais.items(), key=lambda tp: tp[1][0]))
                        + f". Foram lidos {len(vistos)} atos distintos, sem repetição.")
                else:
                    status = "incompleta"
                break
    finally:
        db.execute("UPDATE leitura_catalogo SET terminada_em = ?, status = ?, total_lido = ?, paginas_lidas = ?, "
                   "observacao = ? WHERE id = ?", (agora(), status, len(vistos), lidas, observacao, leitura_id))
        db.commit()
    return {"familia": familia, "status": status, "observacao": observacao, "total_informado": total_informado, "total_lido": len(vistos),
            "paginas": paginas, "paginas_lidas": lidas}


def _paginas(paginas: list[int]) -> str:
    return f"{paginas[0]}" if len(paginas) == 1 else f"{paginas[0]} a {paginas[-1]}" if paginas == list(
        range(paginas[0], paginas[-1] + 1)) else ", ".join(map(str, paginas))


def familias_a_ler(db, familias: list[str] | None, refazer: bool, dias: int = 7) -> list[str]:
    """Retomada: pula famílias com leitura completa nos últimos `dias`, salvo `refazer`."""
    familias = familias or list(FAMILIAS)
    if refazer:
        return familias
    recentes = {r[0] for r in db.execute(
        "SELECT familia FROM leitura_catalogo WHERE status IN ('completa', 'divergente na fonte') "
        "AND terminada_em >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
        (f"-{dias} days",))}
    return [f for f in familias if f not in recentes]
