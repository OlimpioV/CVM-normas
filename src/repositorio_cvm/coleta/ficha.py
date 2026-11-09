"""Leitura da ficha oficial de um ato no portal da CVM (conteudo.cvm.gov.br).

A ficha é a página `.../legislacao/<família>/<ato>.html` com título, data, ementa, publicação
no DOU, links de download e as marcações oficiais de alteração e revogação. Datas do DOU com ano
de 2 dígitos são aceitas; revogação só por marcação explícita; alteração e revogação ficam separadas.

Nada aqui é inferido: cada valor vem de um trecho da ficha, guardado em `trechos` para servir
de evidência (origem da informação).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

MESES_EN = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
            "sep": 9, "oct": 10, "nov": 11, "dec": 12}
TAGS_GENERICAS = {"ofício circular", "nota", "nota explicativa"}

_DATA_EN = re.compile(r"^[A-Z][a-z]{2}\s+([A-Z][a-z]{2})\s+(\d{1,2})\s+\d{2}:\d{2}:\d{2}\s+\w+\s+(\d{4})$")
_DOU = re.compile(
    r"\((?P<evento>Publicad[ao]|Retificad[ao]|Republicad[ao])\s+no\s+(?P<veiculo>DOU|site)\s+"
    r"(?:de\s+|em\s+)?(?P<data>\d{1,2}[./]\d{1,2}[./]\d{2,4})(?P<resto>[^)]*)\)",
    re.I,
)
_MARCACAO = re.compile(r"^\s*(ALTERAD[AO]S?|REVOGAD[AO]S?|VIDE)\b", re.I)
_PALAVRA_MARCACAO = re.compile(r"\b(ALTERAD[AO]S?|REVOGAD[AO]S?|VIDE)\b", re.I)


@dataclass(frozen=True)
class Link:
    rotulo: str
    url: str
    formato: str | None  # html, pdf, doc, docx ou None
    papel: str  # integra, consolidado, original, anexo, complementar


@dataclass(frozen=True)
class Relacao:
    tipo: str  # altera, revoga, alterada_por, revogada_por, vide
    alvo_titulo: str
    alvo_url: str
    trecho: str


@dataclass(frozen=True)
class EventoDOU:
    evento: str  # publicacao, retificacao, republicacao
    veiculo: str  # DOU ou site
    data: str | None  # AAAA-MM-DD
    trecho: str


@dataclass(frozen=True)
class AudienciaCitada:
    """Audiência pública indicada na ficha ("AUDIÊNCIA PÚBLICA: SDM 02/21", com link para a página)."""

    codigo: str  # texto do link: "SDM 02/21"
    url: str
    trecho: str  # parágrafo da ficha em que aparece (evidência)


@dataclass
class Ficha:
    url: str
    titulo: str | None = None
    data_edicao: str | None = None
    ementa: str | None = None
    eventos: list[EventoDOU] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    relacoes: list[Relacao] = field(default_factory=list)
    assuntos: list[str] = field(default_factory=list)
    marcacoes: list[str] = field(default_factory=list)
    audiencias: list[AudienciaCitada] = field(default_factory=list)
    trechos: dict[str, str] = field(default_factory=dict)

    @property
    def data_publicacao(self) -> str | None:
        for evento in self.eventos:
            if evento.evento == "publicacao" and evento.veiculo.upper() == "DOU":
                return evento.data
        return None

    @property
    def integra_html(self) -> Link | None:
        return next((l for l in self.links if l.formato == "html" and l.papel == "integra"), None)

    @property
    def revogada_no_titulo(self) -> bool:
        return bool(self.titulo and re.search(r"\(\s*revogad[ao]\s*\)", self.titulo, re.I))


def _texto(no: Tag | NavigableString | None) -> str:
    if no is None:
        return ""
    if isinstance(no, NavigableString):
        return " ".join(str(no).split())
    return " ".join(no.get_text(" ", strip=True).split())


def _limpar_pontuacao(texto: str) -> str:
    return re.sub(r"\s+([,.;:)])", r"\1", texto).replace("( ", "(")


def converter_data_curta(valor: str) -> str | None:
    """'02.09.2021' ou '17.10.05' -> 'AAAA-MM-DD'; ano de 2 dígitos: <=50 é 20xx, senão 19xx."""
    partes = re.split(r"[./]", valor.strip())
    if len(partes) != 3:
        return None
    dia, mes, ano = (int(p) for p in partes)
    if ano < 100:
        ano += 2000 if ano <= 50 else 1900
    try:
        return date(ano, mes, dia).isoformat()
    except ValueError:
        return None


def _data_em_ingles(texto: str) -> str | None:
    m = _DATA_EN.match(texto.strip())
    if not m or m.group(1).lower() not in MESES_EN:
        return None
    try:
        return date(int(m.group(3)), MESES_EN[m.group(1).lower()], int(m.group(2))).isoformat()
    except ValueError:
        return None


def _formato(url: str) -> str | None:
    caminho = urlsplit(url).path.lower()
    for ext, nome in ((".html", "html"), (".htm", "html"), (".pdf", "pdf"), (".docx", "docx"), (".doc", "doc")):
        if caminho.endswith(ext):
            return nome
    return None


def _papel(rotulo: str, url: str, contexto: str) -> str:
    alvo = f"{rotulo} {contexto}".lower()
    if "consolidad" in alvo:
        return "consolidado"
    if "redação original" in alvo or "redacao original" in alvo:
        return "original"
    if rotulo.strip("[] ").lower() in {"html", "pdf", "p df", "doc", "docx"}:
        return "integra"
    if re.search(r"\banexo", rotulo, re.I):
        return "anexo"
    if _COMPLEMENTAR.search(rotulo):
        return "complementar"
    return "integra"


_COMPLEMENTAR = re.compile(
    r"justificativa|parte geral|suplemento|relat[óo]rio|voto|minuta|edital|an[áa]lise|perguntas|apresenta",
    re.I,
)


_PAGINA_AUDIENCIA = re.compile(r"^/audiencias_publicas/ap_[a-z]+/\d{4}/[^/]+\.html?$", re.I)


_NOME_NORMA = re.compile(r"^(inst|resol|deli|pare)0*(\d+)(?![\d])", re.I)


def _norma_do_nome(url: str) -> tuple[str, int] | None:
    """('inst', 1) para .../inst001.html ou .../inst001.pdf; None quando o nome não identifica uma norma."""
    m = _NOME_NORMA.match(urlsplit(url).path.rsplit("/", 1)[-1])
    return (m.group(1).lower(), int(m.group(2))) if m else None


def _eh_arquivo(url: str) -> bool:
    caminho = urlsplit(url).path.lower()
    return "/anexos/" in caminho or caminho.startswith("/export/")


def ler_ficha(html: bytes | str, url: str) -> Ficha:
    sopa = BeautifulSoup(html, "lxml")
    artigo = sopa.select_one("article.contentTextoGeral")
    ficha = Ficha(url=url)
    if artigo is None:
        return ficha

    titulo = artigo.find("h2")
    ficha.titulo = _texto(titulo) or None
    if ficha.titulo:
        ficha.trechos["titulo"] = ficha.titulo

    corpo = artigo.select_one("section.contentArticle") or artigo
    paragrafos = corpo.find_all("p")

    # Data de edição: primeiro parágrafo com data no formato do servidor ("Tue Aug 31 20:39:00 BRT 2021").
    indice_data = None
    for i, p in enumerate(paragrafos):
        data = _data_em_ingles(_texto(p))
        if data:
            ficha.data_edicao = data
            ficha.trechos["data_edicao"] = _texto(p)
            indice_data = i
            break

    # Ementa: primeiro parágrafo de texto depois da data que não seja só publicação/download.
    if indice_data is not None:
        for p in paragrafos[indice_data + 1:]:
            bruto = _texto(p)
            sem_dou = _limpar_pontuacao(_DOU.sub("", bruto)).strip()
            if not sem_dou or sem_dou.startswith("-") or _MARCACAO.match(sem_dou):
                continue
            ficha.ementa = sem_dou
            ficha.trechos["ementa"] = _limpar_pontuacao(bruto)
            _relacoes_da_ementa(p, url, ficha)
            break

    # Publicação, retificação e republicação (em qualquer parágrafo da ficha).
    for p in paragrafos:
        bruto = _texto(p)
        for m in _DOU.finditer(bruto):
            evento = m.group("evento").lower()
            tipo = "publicacao" if evento.startswith("publicad") else (
                "retificacao" if evento.startswith("retificad") else "republicacao")
            ficha.eventos.append(EventoDOU(tipo, m.group("veiculo"), converter_data_curta(m.group("data")),
                                           _limpar_pontuacao(m.group(0))))

    # Marcações oficiais (ALTERADA pelas..., REVOGADA pela..., VIDE ...). Um mesmo parágrafo
    # pode ter mais de uma marcação; cada link pertence à última palavra-chave que o precede.
    # Nas fichas das instruções e deliberações, o link da marcação aponta direto para o PDF da outra norma
    # ("REVOGADA pela Instrução 247/96" -> inst247consolid.pdf): é relação, não arquivo desta norma.
    paragrafos_marcacao: set[int] = set()
    for p in paragrafos:
        bruto = _limpar_pontuacao(_texto(p))
        if not _MARCACAO.match(bruto):
            continue
        paragrafos_marcacao.add(id(p))
        ficha.marcacoes.append(bruto)
        tipo: str | None = None
        for no in p.descendants:
            if isinstance(no, NavigableString) and no.parent.name != "a":
                achados = _PALAVRA_MARCACAO.findall(str(no))
                if achados:
                    palavra = achados[-1].lower()
                    tipo = "vide" if palavra == "vide" else (
                        "revogada_por" if palavra.startswith("revogad") else "alterada_por")
            elif isinstance(no, Tag) and no.name == "a" and no.get("href") and tipo:
                alvo = urljoin(url, no["href"])
                if not _eh_arquivo(alvo) or re.search(r"\d", _texto(no)):
                    ficha.relacoes.append(Relacao(tipo, _texto(no), alvo, bruto))

    # Links de arquivos (íntegra, consolidado, original, anexos).
    vistos: set[str] = set()
    propria = _norma_do_nome(url)
    for a in corpo.find_all("a", href=True):
        alvo = urljoin(url, a["href"])
        if not _eh_arquivo(alvo) or alvo in vistos:
            continue
        if any(id(pai) in paragrafos_marcacao for pai in a.parents):
            continue
        outra = _norma_do_nome(alvo)
        if propria and outra and outra != propria:
            continue  # arquivo de outra norma citado na ficha (ex.: alteradora), não desta
        rotulo = _texto(a)
        if not rotulo:
            continue
        vistos.add(alvo)
        contexto = _texto(a.find_parent(["tr", "li", "p"]))
        ficha.links.append(Link(rotulo, alvo, _formato(alvo), _papel(rotulo, alvo, contexto)))

    # Audiências públicas que deram origem ao ato (páginas, não arquivos: não entram em `links`).
    for a in corpo.find_all("a", href=True):
        alvo = urljoin(url, a["href"])
        if _PAGINA_AUDIENCIA.search(urlsplit(alvo).path) and alvo not in {x.url for x in ficha.audiencias}:
            trecho = _limpar_pontuacao(_texto(a.find_parent(["p", "li", "tr", "div"])))
            ficha.audiencias.append(AudienciaCitada(_texto(a), alvo, trecho))

    # Assuntos (tags da ficha).
    for div in artigo.select("div.pull-left"):
        for a in div.find_all("a", href="#"):
            tag = _texto(a)
            if tag and tag.lower() not in TAGS_GENERICAS and tag not in ficha.assuntos:
                ficha.assuntos.append(tag)
    if ficha.assuntos:
        ficha.trechos["assuntos"] = ", ".join(ficha.assuntos)
    return ficha


_VERBOS = re.compile(r"\b(altera|alteram|revoga|revogam|disp[õo]e|referente|regulamenta|acrescenta)\b", re.I)


def _relacoes_da_ementa(paragrafo: Tag, url: str, ficha: Ficha) -> None:
    """Relações ativas citadas na ementa: 'Altera a Resolução CVM nº 60' -> (altera, resol060)."""
    verbo: str | None = None
    texto_ementa = ficha.trechos.get("ementa", "")
    for no in paragrafo.descendants:
        if isinstance(no, NavigableString) and no.parent.name != "a":
            achados = _VERBOS.findall(str(no))
            if achados:
                verbo = achados[-1].lower()
        elif isinstance(no, Tag) and no.name == "a" and no.get("href"):
            alvo = urljoin(url, no["href"])
            if _eh_arquivo(alvo) or verbo is None:
                continue
            if verbo.startswith("altera") or verbo == "acrescenta":
                tipo = "altera"
            elif verbo.startswith("revoga"):
                tipo = "revoga"
            else:
                continue
            ficha.relacoes.append(Relacao(tipo, _texto(no), alvo, texto_ementa))
