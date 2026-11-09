"""Conversão da íntegra oficial em HTML (exportação do Word publicada pela CVM) para Markdown.

Cada parágrafo do original vira um bloco do Markdown e um "dispositivo" (artigo, parágrafo,
inciso, alínea...), com rótulo hierárquico (ex.: "art. 8º, § 1º, inciso II") para pesquisa
e citação. O texto não é reescrito: só recebe marcação (títulos, negrito do rótulo, citação
para texto de outra norma alterada). O original continua sendo a fonte; ver `fidelidade.py`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

CONVERSOR = "html-word/5"

_TITULO_ATO = re.compile(r"^(RESOLUÇÃO|INSTRUÇÃO|DELIBERAÇÃO|PARECER|OF[IÍ]CIO|NOTA EXPLICATIVA)\b.*\b(N[º°O.]|CVM)", re.I)
_CABECALHO = re.compile(r"^(LIVRO|PARTE|T[IÍ]TULO|CAP[IÍ]TULO|SE[CÇ][AÃ]O|SUBSE[CÇ][AÃ]O|ANEXO)\b", re.I)
_ARTIGO = re.compile(r"^Art\.\s*(\d+)\s*([º°]|o\b)?(?:\s*-\s*([A-Z])\b)?\.?", re.I)
_PARAGRAFO = re.compile(r"^§\s*(\d+)\s*([º°]|o\b)?(?:\s*-\s*([A-Z])\b)?")
_PARAGRAFO_UNICO = re.compile(r"^Parágrafo\s+único\b\.?", re.I)
_INCISO = re.compile(r"^([IVXLCDM]+)(?:\s*-\s*([A-Z]))?\s*[–—-]\s*")
_ALINEA = re.compile(r"^([a-z])\)\s*")
_ITEM = re.compile(r"^(\d+)[.)]\s+")
_FIM_CITACAO = re.compile(r"[”\"]\s*(\(N\.?\s?R\.?\))?\s*[.;,]?\s*$")
_CLAUSULA_VIGENCIA = re.compile(r"\b(Esta|Este|A presente|O presente)\s+[\wçãõáéíóú ]{3,40}?\s+entra(?:rá)?\s+em\s+vigor", re.I)
_VIGOR = re.compile(r"entra(?:rá|m)?\s+em\s+vigor", re.I)
_MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
          "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_DATA_EXTENSO = re.compile(r"(\d{1,2})\s*[º°o]?\s+(?:dia\s+)?de\s+([a-zç]+)\s+de\s+(\d{4})", re.I)


@dataclass
class Dispositivo:
    ordem: int
    tipo: str
    artigo: str | None
    rotulo: str
    texto: str
    parte: str | None = None  # ex.: "Anexo Normativo I" (normas com anexos de articulado próprio)


@dataclass
class Conversao:
    markdown: str
    texto_fonte: str  # todo o texto visível do corpo do original, na ordem
    dispositivos: list[Dispositivo] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    vigencia_trecho: str | None = None
    vigencia_data: str | None = None  # AAAA-MM-DD quando há data expressa
    vigencia_na_publicacao: bool = False
    notas_alteracao: list[tuple[str, str]] = field(default_factory=list)  # (rótulo, texto da nota)


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto).replace("\xa0", " ").replace("​", "")
    return " ".join(texto.split())


def _numero(m: re.Match) -> str:
    base = m.group(1)
    sufixo = m.group(3) if m.lastindex and m.lastindex >= 3 and m.group(3) else None
    return f"{base}-{sufixo.upper()}" if sufixo else base


def _ordinal(numero: str) -> str:
    """'5' -> '5º', '5-A' -> '5º-A', '10' -> '10' (convenção de citação de artigos e parágrafos)."""
    base, _, sufixo = numero.partition("-")
    rotulo = f"{base}º" if base.isdigit() and int(base) < 10 else base
    return f"{rotulo}-{sufixo}" if sufixo else rotulo


def _negrito_rotulo(texto: str, m: re.Match) -> str:
    """'Art. 48 Os...' -> '**Art. 48** Os...' (o espaço do original é preservado fora do negrito)."""
    rotulo = m.group(0).rstrip()
    return f"**{rotulo}**{texto[len(rotulo):]}"


def _blocos(corpo: Tag):
    """Parágrafos e tabelas do corpo, na ordem do documento (sem repetir o conteúdo das tabelas)."""
    for no in corpo.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "table"]):
        if no.name != "table" and no.find_parent("table") is not None:
            continue
        if no.name in {"p", "li"} and no.find_parent("li") is not None and no.name == "p":
            continue
        yield no


def _tabela_markdown(tabela: Tag) -> tuple[str, str]:
    linhas = []
    textos = []
    for tr in tabela.find_all("tr"):
        if tr.find_parent("table") is not tabela:
            continue
        celulas = [normalizar(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"]) if c.find_parent("tr") is tr]
        if any(celulas):
            linhas.append("<tr>" + "".join(f"<td>{c}</td>" for c in celulas) + "</tr>")
            textos.append(" ".join(c for c in celulas if c))
    return "<table>\n" + "\n".join(linhas) + "\n</table>", " ".join(textos)


@dataclass
class Bloco:
    """Unidade de texto do original, na ordem: parágrafo (com estilo/classe) ou tabela."""

    texto: str
    estilo: str = ""
    tabela_md: str | None = None
    tachado: str = ""  # "" | "total" | "parcial": redação anterior riscada nos consolidados da CVM
    texto_md: str | None = None  # com ~~marcação~~ dos trechos tachados (tachado parcial)
    texto_vigente: str | None = None  # sem os trechos tachados (tachado parcial; tabela com <s></s>)


def converter_html(html: bytes | str) -> Conversao:
    sopa = BeautifulSoup(html, "lxml")
    for lixo in sopa(["script", "style", "head", "title", "meta"]):
        lixo.decompose()
    corpo = sopa.body or sopa
    blocos = []
    for no in _blocos(corpo):
        if no.name == "table":
            tabela_md, tabela_txt = _tabela_markdown(no)
            blocos.append(Bloco(tabela_txt, "tabela", tabela_md))
        else:
            blocos.append(Bloco(normalizar(no.get_text(" ")), " ".join(no.get("class") or [])))
    return estruturar(blocos, normalizar(corpo.get_text(" ")))


_PARTE = re.compile(r"^ANEXO(\s+NORMATIVO)?\s+([IVXLC]+\b|[A-Z]\b|\d+)", re.I)
# Suplementos (formulários e informes) à norma, em bloco próprio: "SUPLEMENTO A – TERMO DE CIÊNCIA..." ou
# "SUPLEMENTO A À RESOLUÇÃO CVM Nº 60...". Só em caixa alta: "Suplemento E ou F" no texto é remissão.
_SUPLEMENTO = re.compile(r"^SUPLEMENTO\s+[A-Z]{1,2}\b(?!\s+(?:ou|e)\b)")
PARTE_SUPLEMENTOS = "Suplementos"
# Linha de sumário com pontilhado ("CAPÍTULO I – ÂMBITO .......... 12"): não é título nem abre parte.
_PONTILHADO = re.compile(r"\.{5,}|(?:\. ){4,}|…{2,}")
# Depois do identificador do anexo, um título continua com travessão, dois-pontos, "à Resolução..." ou nada.
# "Anexo I." solto (fim de remissão quebrada pela paginação do PDF) não é título.
_CONTINUACAO_TITULO_ANEXO = re.compile(r"^(?:$|[–—\-:]|(?:à|a|ao|da|do)\s)", re.I)
_NOTA_ALTERACAO = re.compile(
    r"^(?:(?:Al[ií]neas?|Incisos?|Itens?|Item|Par[aá]grafos?|Artigos?|Caput|Se[cç][aã]o|Subse[cç][aã]o|"
    r"Cap[ií]tulo|T[ií]tulo|Anexos?|Ementa|Pre[aâ]mbulo|Nota|Suplemento|Ap[eê]ndice|Quadro|Tabela)\b.{0,80}?"
    # "§ 1º com redação dada..." e "Art. 13 com redação dada...": depois de "§" e "Art." não há fronteira de
    # palavra, e o verbo vem logo depois do número (um artigo comum pode ter "incluído pela" no texto).
    r"|(?:§+|Arts?\.)\s*\d+\s*[º°]?(?:\s*-\s*[A-Z])?(?:\s*(?:,|e|a)\s*\d+\s*[º°]?(?:\s*-\s*[A-Z])?)*\s+)"
    r"\b(com reda[cç][aã]o dada|inclu[ií]d[oa]s?|acrescid[oa]s?|acrescentad[oa]s?|revogad[oa]s?|renumerad[oa]s?|"
    r"alterad[oa]s?|suprimid[oa]s?)\b.{0,60}?\bpel[ao]s?\b",
    re.I,
)
_SUMARIO = ("ndice", "sumrio", "sumário", "índice", "toc")
# Estilos de título do Word da CVM (o Word remove acentos do identificador: "TítulodaResolução" -> "TtulodaResoluo").
_ESTILOS_TITULO = ("ttulo", "captulo", "seo", "subseo", "heading")


def _rotulo_parte(texto: str) -> str | None:
    m = _PARTE.match(texto)
    if not m:
        return None
    if not texto[:5].isupper() and not _CONTINUACAO_TITULO_ANEXO.match(texto[m.end():].strip()):
        return None
    return ("Anexo Normativo " if m.group(1) else "Anexo ") + m.group(2).upper()


def _eh_titulo_de_anexo(texto: str) -> bool:
    """Título "ANEXO ..." em caixa alta (mesmo sem identificador) ou "Anexo X à Resolução..." / "Anexo X – ..."."""
    return texto[:5].isupper() or _rotulo_parte(texto) is not None


def _partes_das_notas(dispositivos: list[Dispositivo]) -> None:
    """Nota de rodapé (ao fim do documento) pertence à parte em que é chamada pela primeira vez."""
    for nota in (d for d in dispositivos if d.tipo == "nota"):
        m = re.match(r"\[\^([^\]\s]+)\]", nota.texto)
        if not m:
            continue
        chamada = f"[^{m.group(1)}]"
        origem = next((d for d in dispositivos if d.tipo != "nota" and chamada in d.texto), None)
        if origem is not None:
            nota.parte = origem.parte


def estruturar(blocos: list[Bloco], texto_fonte: str, estilo_citacao: bool = True) -> Conversao:
    """Classifica os blocos em dispositivos e gera o Markdown (comum a HTML, DOCX e PDF).

    `estilo_citacao`: considerar o estilo "NormaAlterada" como texto de outra norma citada. Vale para a
    redação original; nos textos consolidados da CVM o mesmo estilo marca o próprio texto vigente.
    """
    md: list[str] = []
    dispositivos: list[Dispositivo] = []
    avisos: list[str] = []
    conversao = Conversao(markdown="", texto_fonte=texto_fonte)

    artigo: str | None = None
    paragrafo: str | None = None
    inciso: str | None = None
    parte: str | None = None
    em_citacao = False
    apos_assinatura = False
    primeiro = True
    # Sumário em texto corrido (PDF): da primeira linha com pontilhado até o primeiro artigo, títulos são
    # entradas do sumário, mesmo quando a entrada quebra em duas linhas e só a segunda tem o pontilhado.
    em_sumario = False
    clausulas: list[tuple[str, str | None, bool]] = []

    def contexto(*partes: str | None) -> str:
        return ", ".join(p for p in partes if p)

    def art() -> str | None:
        return contexto(parte, f"art. {_ordinal(artigo)}" if artigo else None) or None

    def novo(tipo: str, rot: str, texto_: str) -> None:
        dispositivos.append(Dispositivo(len(dispositivos) + 1, tipo, artigo, rot, texto_, parte))

    for bloco in blocos:
        if bloco.tabela_md is not None:
            if bloco.texto:
                md.append(bloco.tabela_md)
                if bloco.tachado == "total":
                    novo("redacao_anterior", contexto(art(), "tabela (redação anterior)"), bloco.texto)
                else:
                    novo("tabela", contexto(art(), "tabela"), bloco.texto_vigente or bloco.texto)
                avisos.append("tabela convertida em HTML simples; conferir mesclagens de células")
                if bloco.tachado:
                    avisos.append("tabelas com trechos tachados (redação anterior) marcados com <s> </s>")
            continue
        texto = bloco.texto
        if not texto:
            continue
        classes = bloco.estilo.lower().replace(" ", "")
        if classes == "nota":
            md.append(texto)
            numero_nota = re.match(r"\[\^(\d+)\]", texto)
            rot = f"nota de rodapé {numero_nota.group(1)}" if numero_nota else "nota de rodapé"
            dispositivos.append(Dispositivo(len(dispositivos) + 1, "nota", None, rot, texto))
            continue
        if classes.startswith(_SUMARIO):
            md.append(texto)
            dispositivos.append(Dispositivo(len(dispositivos) + 1, "sumario", None, "sumário", texto))
            continue
        # Nota de alteração dos consolidados ("• Alínea b com redação dada pela Resolução CVM nº 194...").
        sem_marcador = texto.lstrip("•▪·◦-– ").strip()
        if len(sem_marcador) < 400 and _NOTA_ALTERACAO.match(sem_marcador):
            rot = contexto(art(), paragrafo, inciso, "nota de alteração")
            md.append(f"*{texto}*")
            novo("nota_alteracao", rot, texto)
            conversao.notas_alteracao.append((rot, texto))
            continue
        # Texto de outra norma que está sendo alterada: classe "NormaAlterada" do Word da CVM ou
        # trecho entre aspas iniciado por “ e encerrado por ” (com ou sem "(NR)").
        # Aspas no início só abrem citação se não fecharem no meio do parágrafo ("“lavagem” de
        # dinheiro..." é termo entre aspas, não texto de outra norma).
        fechamentos = texto.count("”") + texto[1:].count('"')
        abre_aspas = texto.startswith(("“", '"')) and (
            fechamentos == 0 or (fechamentos == 1 and bool(_FIM_CITACAO.search(texto))))
        # Salvaguardas: título de anexo/capítulo (estilo de título ou cabeçalho em caixa alta) encerra
        # citação aberta; citação que não fecha em 60 parágrafos é encerrada com aviso.
        if em_citacao and (classes.startswith(_ESTILOS_TITULO) or (_CABECALHO.match(texto) and texto.isupper())):
            em_citacao = False
        # "Art. N" sem aspas que continua a numeração da norma principal (até 3 à frente) encerra a citação.
        if em_citacao and "normaalterada" not in classes and artigo and artigo.split("-")[0].isdigit() \
                and (m_art := _ARTIGO.match(texto)) and 0 < int(m_art.group(1)) - int(artigo.split("-")[0]) <= 3:
            em_citacao = False
        if em_citacao and dispositivos and sum(1 for d in dispositivos[-60:] if d.tipo == "texto_alterado") >= 60:
            em_citacao = False
            avisos.append("citação entre aspas sem fechamento; encerrada automaticamente — conferir")
        if ("normaalterada" in classes and estilo_citacao) or em_citacao or abre_aspas:
            if _FIM_CITACAO.search(texto):
                em_citacao = False
            elif abre_aspas:
                em_citacao = True
            md.append("> " + texto)
            novo("texto_alterado", contexto(art(), "texto alterado/acrescido"), texto)
            continue

        tipo = "texto"
        marcado = texto
        if em_sumario and not _PONTILHADO.search(texto) and not (_CABECALHO.match(texto) or _SUPLEMENTO.match(texto)):
            em_sumario = False
        if primeiro and _TITULO_ATO.match(texto):
            tipo = "titulo"
            marcado = "# " + texto
        elif "ementa" in classes:
            tipo = "ementa"
            marcado = "*" + texto + "*"
        elif (em_sumario or _PONTILHADO.search(texto)) and (_CABECALHO.match(texto) or _SUPLEMENTO.match(texto)):
            tipo = "sumario"
            em_sumario = True
        elif _SUPLEMENTO.match(texto) and len(texto) < 250:
            tipo = "cabecalho"
            marcado = f"## {texto}"
            apos_assinatura = False
            artigo, paragrafo, inciso = None, None, None
            parte = PARTE_SUPLEMENTOS
        elif _CABECALHO.match(texto) and len(texto) < 250 and (
                not re.match(r"^ANEXO", texto, re.I) or _eh_titulo_de_anexo(texto)):
            tipo = "cabecalho"
            nivel = "###" if re.match(r"^(SE[CÇ][AÃ]O|SUBSE[CÇ][AÃ]O)", texto, re.I) else "##"
            marcado = f"{nivel} {texto}"
            apos_assinatura = False
            if re.match(r"^ANEXO", texto, re.I):
                artigo, paragrafo, inciso = None, None, None
                parte = _rotulo_parte(texto) or parte
        elif m := _ARTIGO.match(texto):
            tipo = "artigo"
            em_sumario = False
            artigo, paragrafo, inciso = _numero(m), None, None
            marcado = _negrito_rotulo(texto, m)
        elif m := _PARAGRAFO.match(texto):
            tipo = "paragrafo"
            paragrafo, inciso = f"§ {_ordinal(_numero(m))}", None
            marcado = _negrito_rotulo(texto, m)
        elif m := _PARAGRAFO_UNICO.match(texto):
            tipo = "paragrafo"
            paragrafo, inciso = "parágrafo único", None
            marcado = _negrito_rotulo(texto, m)
        elif m := _INCISO.match(texto):
            tipo = "inciso"
            inciso = f"inciso {m.group(1)}" + (f"-{m.group(2)}" if m.group(2) else "")
        elif m := _ALINEA.match(texto):
            tipo = "alinea"
        elif _ITEM.match(texto):
            tipo = "item"
        elif texto.startswith("Assinado eletronicamente") or apos_assinatura:
            tipo = "assinatura"
            apos_assinatura = True
        elif artigo is None:
            tipo = "preambulo"
        primeiro = False

        if tipo == "alinea":
            rot = contexto(art(), paragrafo, inciso, f"alínea {m.group(1)}")
        elif tipo in {"artigo"}:
            rot = art()
        elif tipo == "paragrafo":
            rot = contexto(art(), paragrafo)
        elif tipo == "inciso":
            rot = contexto(art(), paragrafo, inciso)
        elif tipo == "item":
            rot = contexto(art(), paragrafo, inciso,
                           f"item {_ITEM.match(texto).group(1)}")
        elif tipo == "cabecalho":
            rot = texto[:120]
        elif tipo == "sumario":
            rot = "sumário"
        elif tipo == "assinatura":
            rot = "assinatura"
        else:
            rot = tipo if artigo is None else contexto(art(), paragrafo, inciso, tipo)
        if bloco.tachado == "total":
            # Redação anterior (riscada): guardada para o histórico, fora da pesquisa e da vigência.
            md.append(f"~~{texto}~~")
            novo("redacao_anterior", f"{rot} (redação anterior)", texto)
            continue
        if bloco.tachado == "parcial":
            md.append(bloco.texto_md or texto)
            novo(tipo, rot, bloco.texto_vigente or texto)
            avisos.append("parágrafos com trechos tachados (redação anterior) marcados com ~~ ~~ no Markdown")
        else:
            md.append(marcado)
            novo(tipo, rot, texto)

        if _CLAUSULA_VIGENCIA.search(texto):
            na_publicacao = bool(re.search(r"na\s+data\s+de\s+sua\s+publica", texto, re.I))
            data = None
            if not na_publicacao and (d := _DATA_EXTENSO.search(texto[_VIGOR.search(texto).end():])):
                mes = _MESES.get(d.group(2).lower())
                if mes:
                    data = f"{int(d.group(3)):04d}-{mes:02d}-{int(d.group(1)):02d}"
            clausulas.append((texto, data, na_publicacao))
            if re.search(r"\bexceto\b|\bressalvad|\bquanto\s+a", texto, re.I):
                avisos.append("cláusula de vigência com exceções; conferir datas por dispositivo")

    # Vigência: só é preenchida quando há uma única cláusula ("Esta Resolução entra em vigor...") ou
    # todas concordam. Textos consolidados podem trazer redações sucessivas com datas diferentes.
    if clausulas:
        conversao.vigencia_trecho = " | ".join(c[0] for c in clausulas[:4])
        distintas = {(c[1], c[2]) for c in clausulas}
        if len(distintas) == 1:
            conversao.vigencia_data, conversao.vigencia_na_publicacao = clausulas[0][1], clausulas[0][2]
        else:
            avisos.append("há mais de uma cláusula de vigência (redações sucessivas); data de início não preenchida")

    _partes_das_notas(dispositivos)
    conversao.markdown = "\n\n".join(md) + "\n"
    conversao.dispositivos = dispositivos
    conversao.avisos = list(dict.fromkeys(avisos))
    return conversao
