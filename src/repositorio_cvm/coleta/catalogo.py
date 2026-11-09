"""Leitura das páginas de resultado da pesquisa avançada de legislação da CVM.

URL paginada (conferida em 27/10/2026):
`https://conteudo.cvm.gov.br/legislacao/index.html?buscado=true&contCategoriasCheck=1&vimDaCategoria=/legislacao/<família>/&searchPage=N`,
ordenada da mais recente para a mais antiga, com 10 itens por página.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

BASE = "https://conteudo.cvm.gov.br/legislacao/index.html"

FAMILIAS = {
    "resolucao": "resolucoes",
    "instrucao": "instrucoes",
    "deliberacao": "deliberacoes",
    "parecer_orientacao": "pareceres-orientacao",
    "oficio_circular": "oficios-circulares",
    "nota_explicativa": "notas-explicativas",
}


class CatalogoError(Exception):
    """Página de catálogo em formato inesperado; a coleta não deve prosseguir às cegas."""


@dataclass(frozen=True)
class ItemCatalogo:
    titulo: str
    url: str
    data: str | None  # AAAA-MM-DD
    descricao: str | None
    tags: tuple[str, ...]


@dataclass
class PaginaCatalogo:
    url: str
    pagina: int | None
    total_paginas: int | None
    total_resultados: int | None
    itens: list[ItemCatalogo] = field(default_factory=list)


def url_catalogo(familia: str, pagina: int = 1) -> str:
    pasta = FAMILIAS.get(familia, familia)
    consulta = urlencode(
        {"buscado": "true", "contCategoriasCheck": "1", "vimDaCategoria": f"/legislacao/{pasta}/",
         "searchPage": str(pagina)},
        safe="/",
    )
    return f"{BASE}?{consulta}"


def _texto(no) -> str:
    return " ".join(no.get_text(" ", strip=True).split()) if no is not None else ""


def ler_pagina_catalogo(html: bytes | str, url: str) -> PaginaCatalogo:
    sopa = BeautifulSoup(html, "lxml")
    texto = " ".join(sopa.get_text(" ").split())
    m_pag = re.search(r"Páginas\s+(\d+)\s*/\s*(\d+)", texto)
    m_res = re.search(r"(\d+)\s+resultados?\s+encontrados?", texto)
    pagina = PaginaCatalogo(
        url=url,
        pagina=int(m_pag.group(1)) if m_pag else None,
        total_paginas=int(m_pag.group(2)) if m_pag else None,
        total_resultados=int(m_res.group(1)) if m_res else None,
    )
    for artigo in sopa.find_all("article"):
        a = artigo.select_one("h3 a[href]")
        if a is None:
            continue
        data = None
        tags: list[str] = []
        for p in artigo.select("div.infoItem p"):
            rotulo = _texto(p.find("b")).rstrip(":").lower()
            if rotulo == "data":
                m = re.search(r"(\d{2})/(\d{2})/(\d{4})", _texto(p))
                data = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
            elif rotulo == "tag":
                tags = [_texto(t) for t in p.find_all("a")]
        pagina.itens.append(
            ItemCatalogo(
                titulo=_texto(a),
                url=urljoin(url, a["href"]),
                data=data,
                descricao=_texto(artigo.select_one("div.contentDesc")) or None,
                tags=tuple(tags),
            )
        )
    if pagina.total_paginas is None and pagina.itens:
        raise CatalogoError("paginação ausente numa página com resultados")
    return pagina
