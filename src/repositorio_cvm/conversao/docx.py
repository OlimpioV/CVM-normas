"""Leitura do DOCX oficial da CVM (lxml direto sobre o OOXML) para blocos de texto na ordem do corpo.

- Parágrafos (`w:p`) e tabelas (`w:tbl`) do corpo, na ordem do documento.
- Texto das execuções (`w:t`), tabulações e quebras; texto excluído em revisão (`w:delText`) não entra.
- Numeração automática do Word (`w:numPr`) é reconstruída a partir de `numbering.xml`, porque o
  rótulo ("I –", "a)", "1.") não está no texto do parágrafo, mas aparece no documento impresso.
- Cabeçalhos, rodapés e notas de rodapé não entram no corpo (as notas são registradas como aviso).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field

from lxml import etree

from repositorio_cvm.conversao.html import Bloco, Conversao, estruturar, normalizar

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CONVERSOR = "docx-ooxml/9"


def _romano(n: int) -> str:
    valores = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
               (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    saida = ""
    for v, s in valores:
        while n >= v:
            saida += s
            n -= v
    return saida


def _letra(n: int) -> str:
    saida = ""
    while n > 0:
        n, resto = divmod(n - 1, 26)
        saida = chr(97 + resto) + saida
    return saida


def _formatar(n: int, formato: str) -> str:
    if formato == "upperRoman":
        return _romano(n)
    if formato == "lowerRoman":
        return _romano(n).lower()
    if formato == "lowerLetter":
        return _letra(n)
    if formato == "upperLetter":
        return _letra(n).upper()
    if formato == "ordinal":
        return f"{n}º"
    if formato in ("bullet", "none"):
        return ""
    return str(n)


@dataclass
class _Nivel:
    formato: str = "decimal"
    texto: str = "%1."
    inicio: int = 1


@dataclass
class Numeracao:
    """Contadores de numeração automática (por numId, como o Word faz por instância de lista)."""

    abstratos: dict[str, dict[int, _Nivel]] = field(default_factory=dict)
    instancias: dict[str, tuple[str, dict[int, int]]] = field(default_factory=dict)  # numId -> (abstrato, inícios)
    contadores: dict[str, dict[int, int]] = field(default_factory=dict)

    @classmethod
    def ler(cls, xml: bytes | None) -> Numeracao:
        num = cls()
        if not xml:
            return num
        raiz = etree.fromstring(xml)
        for abs_ in raiz.findall(f"{W}abstractNum"):
            niveis = {}
            for lvl in abs_.findall(f"{W}lvl"):
                ilvl = int(lvl.get(f"{W}ilvl"))
                fmt = lvl.find(f"{W}numFmt")
                txt = lvl.find(f"{W}lvlText")
                ini = lvl.find(f"{W}start")
                niveis[ilvl] = _Nivel(fmt.get(f"{W}val") if fmt is not None else "decimal",
                                      txt.get(f"{W}val") if txt is not None else "",
                                      int(ini.get(f"{W}val")) if ini is not None else 1)
            num.abstratos[abs_.get(f"{W}abstractNumId")] = niveis
        for n in raiz.findall(f"{W}num"):
            inicios = {}
            for ov in n.findall(f"{W}lvlOverride"):
                so = ov.find(f"{W}startOverride")
                if so is not None:
                    inicios[int(ov.get(f"{W}ilvl"))] = int(so.get(f"{W}val"))
            num.instancias[n.get(f"{W}numId")] = (n.find(f"{W}abstractNumId").get(f"{W}val"), inicios)
        return num

    def rotulo(self, num_id: str, ilvl: int) -> str:
        if num_id not in self.instancias or num_id == "0":
            return ""
        abstrato, inicios = self.instancias[num_id]
        niveis = self.abstratos.get(abstrato, {})
        cont = self.contadores.setdefault(num_id, {})
        nivel = niveis.get(ilvl, _Nivel())
        if nivel.formato == "bullet":
            # Marcador de lista: o Word guarda o glifo da fonte Symbol/Wingdings em área de uso privado
            # (ex.: U+F0B7), que não é um caractere legível fora dessas fontes.
            return "•"
        inicio = inicios.get(ilvl, nivel.inicio)
        cont[ilvl] = cont[ilvl] + 1 if ilvl in cont else inicio
        for mais_fundo in [k for k in cont if k > ilvl]:
            del cont[mais_fundo]

        def troca(m: re.Match) -> str:
            nv = int(m.group(1)) - 1
            n = cont.get(nv, inicios.get(nv, niveis.get(nv, _Nivel()).inicio))
            return _formatar(n, niveis.get(nv, _Nivel()).formato)

        return re.sub(r"%(\d)", troca, nivel.texto).strip()


def _texto_paragrafo(p, chamadas: list[str] | None = None) -> str:
    """Texto do parágrafo; chamadas de nota de rodapé viram "[^id]" e o id é anotado em `chamadas`."""
    partes = []
    for no in p.iter(f"{W}t", f"{W}tab", f"{W}br", f"{W}cr", f"{W}noBreakHyphen", f"{W}sym",
                     f"{W}footnoteReference"):
        nome = etree.QName(no).localname
        if nome == "t":
            partes.append(no.text or "")
        elif nome == "noBreakHyphen":
            partes.append("-")
        elif nome == "footnoteReference":
            if chamadas is not None:
                chamadas.append(no.get(f"{W}id"))
                partes.append(f"[^{len(chamadas)}]")
        else:
            partes.append(" ")
    return "".join(partes)


def _tachado(run) -> bool:
    for nome in ("strike", "dstrike"):
        el = run.find(f"{W}rPr/{W}{nome}")
        if el is not None and el.get(f"{W}val") not in ("0", "false", "off"):
            return True
    return False


def _oculto(run) -> bool:
    """Texto oculto (w:vanish) não sai na impressão nem no PDF oficial; na Res. 92 são segmentos em inglês de
    memória de tradução ("{0>An investment entity...<}100{>...<0}")."""
    el = run.find(f"{W}rPr/{W}vanish")
    return el is not None and el.get(f"{W}val") not in ("0", "false", "off")


def _segmentos(p, chamadas: list[str] | None) -> list[tuple[str, bool]]:
    """Trechos do parágrafo com a indicação de tachado (redação anterior nos textos consolidados da CVM)."""
    segmentos: list[tuple[str, bool]] = []
    for run in p.iter(f"{W}r"):
        if _oculto(run):
            continue
        texto = _texto_paragrafo(run, chamadas)
        if texto:
            segmentos.append((texto, _tachado(run)))
    return segmentos


def _estilo(p) -> str:
    st = p.find(f"{W}pPr/{W}pStyle")
    return st.get(f"{W}val") if st is not None else ""


def _num(p, estilos_num: dict[str, tuple[str, int]]) -> tuple[str, int] | None:
    np_ = p.find(f"{W}pPr/{W}numPr")
    if np_ is not None:
        nid = np_.find(f"{W}numId")
        lvl = np_.find(f"{W}ilvl")
        if nid is not None:
            return nid.get(f"{W}val"), int(lvl.get(f"{W}val")) if lvl is not None else 0
    return estilos_num.get(_estilo(p))


def _estilos_numerados(xml: bytes | None) -> dict[str, tuple[str, int]]:
    """Estilos de parágrafo que carregam numeração (numPr no próprio estilo)."""
    saida = {}
    if not xml:
        return saida
    for st in etree.fromstring(xml).findall(f"{W}style"):
        np_ = st.find(f"{W}pPr/{W}numPr")
        if np_ is not None and np_.find(f"{W}numId") is not None:
            lvl = np_.find(f"{W}ilvl")
            saida[st.get(f"{W}styleId")] = (np_.find(f"{W}numId").get(f"{W}val"),
                                            int(lvl.get(f"{W}val")) if lvl is not None else 0)
    return saida


def _ler(zip_: zipfile.ZipFile, nome: str) -> bytes | None:
    return zip_.read(nome) if nome in zip_.namelist() else None


def blocos_docx(dados: bytes) -> tuple[list[Bloco], str, list[str]]:
    """Devolve (blocos, texto_fonte, avisos). texto_fonte inclui os rótulos de numeração automática."""
    zip_ = zipfile.ZipFile(io.BytesIO(dados))
    corpo = etree.fromstring(zip_.read("word/document.xml")).find(f"{W}body")
    numeracao = Numeracao.ler(_ler(zip_, "word/numbering.xml"))
    estilos_num = _estilos_numerados(_ler(zip_, "word/styles.xml"))
    blocos: list[Bloco] = []
    fonte: list[str] = []
    avisos: list[str] = []
    chamadas: list[str] = []

    def paragrafo_detalhado(p) -> tuple[str, str, str | None, str | None]:
        """(texto completo, tachado: ''|'total'|'parcial', texto com ~~marcação~~, texto vigente)."""
        segmentos = _segmentos(p, chamadas)
        texto = normalizar("".join(t for t, _ in segmentos))
        com_texto = [(t, s) for t, s in segmentos if t.strip()]
        riscados = [s for _, s in com_texto]
        tachado = "total" if riscados and all(riscados) else ("parcial" if any(riscados) else "")
        rotulo = ""
        num = _num(p, estilos_num)
        if num and texto:
            rotulo = numeracao.rotulo(*num)
            if rotulo:
                texto = f"{rotulo} {texto}"
        if tachado != "parcial":
            return texto, tachado, None, None
        marcado = "".join(f"~~{t}~~" if s and t.strip() else t for t, s in segmentos)
        marcado = normalizar(re.sub(r"~~(\s*)~~", r"\1", marcado))
        vigente = normalizar("".join(t for t, s in segmentos if not s))
        if rotulo:
            marcado, vigente = f"{rotulo} {marcado}", f"{rotulo} {vigente}"
        return texto, tachado, marcado, vigente

    for filho in corpo:
        nome = etree.QName(filho).localname
        if nome == "p":
            texto, tachado, marcado, vigente = paragrafo_detalhado(filho)
            fonte.append(texto)
            blocos.append(Bloco(texto, _estilo(filho), tachado=tachado, texto_md=marcado, texto_vigente=vigente))
        elif nome == "tbl":
            # Redação anterior riscada dentro das células: o trecho fica entre <s></s> no HTML da tabela
            # (o Markdown não é interpretado dentro de HTML) e fora do texto vigente da tabela.
            linhas, textos, vigentes, riscos = [], [], [], set()
            for tr in filho.iter(f"{W}tr"):
                celulas, marcadas, vigentes_linha = [], [], []
                for tc in tr.findall(f"{W}tc"):
                    completo, marcado, vigente = [], [], []
                    for p in tc.iter(f"{W}p"):
                        texto, tachado, texto_md, texto_vigente = paragrafo_detalhado(p)
                        if not texto:
                            continue
                        riscos.add(tachado)
                        completo.append(texto)
                        if tachado == "total":
                            marcado.append(f"<s>{texto}</s>")
                        elif tachado == "parcial":
                            marcado.append(re.sub(r"~~(.+?)~~", r"<s>\1</s>", texto_md))
                            vigente.append(texto_vigente)
                        else:
                            marcado.append(texto)
                            vigente.append(texto)
                    celulas.append(" ".join(completo))
                    marcadas.append(" ".join(marcado))
                    vigentes_linha.append(" ".join(t for t in vigente if t))
                if any(celulas):
                    linhas.append("<tr>" + "".join(f"<td>{c}</td>" for c in marcadas) + "</tr>")
                    textos.append(" ".join(c for c in celulas if c))
                    vigentes.append(" ".join(c for c in vigentes_linha if c))
            texto = " ".join(textos)
            fonte.append(texto)
            riscos.discard("")
            tachado = ("total" if not any(vigentes) else "parcial") if riscos else ""
            blocos.append(Bloco(texto, "tabela", "<table>\n" + "\n".join(linhas) + "\n</table>", tachado=tachado,
                                texto_vigente=normalizar(" ".join(v for v in vigentes if v)) if tachado else None))
        elif nome == "sdt":
            for p in filho.iter(f"{W}p"):
                texto, tachado, marcado, vigente = paragrafo_detalhado(p)
                fonte.append(texto)
                blocos.append(Bloco(texto, _estilo(p), tachado=tachado, texto_md=marcado, texto_vigente=vigente))
    # Notas de rodapé: incorporadas ao fim, no formato de nota do Markdown ("[^1]: texto").
    notas_xml = _ler(zip_, "word/footnotes.xml")
    if chamadas and notas_xml:
        notas = {n.get(f"{W}id"): n for n in etree.fromstring(notas_xml).findall(f"{W}footnote")}
        for numero, ident in enumerate(chamadas, 1):
            nota = notas.get(ident)
            if nota is None:
                continue
            texto = normalizar(" ".join(_texto_paragrafo(p) for p in nota.iter(f"{W}p")))
            texto = f"[^{numero}]: {texto}"
            fonte.append(texto)
            blocos.append(Bloco(texto, "nota"))
        avisos.append(f"{len(chamadas)} nota(s) de rodapé incorporada(s) ao fim do texto")
    return blocos, normalizar(" ".join(fonte)), avisos


def cabecalhos_docx(dados: bytes) -> set[str]:
    """Textos dos cabeçalhos e rodapés do DOCX (para removê-los do PDF correspondente)."""
    zip_ = zipfile.ZipFile(io.BytesIO(dados))
    textos = set()
    for nome in zip_.namelist():
        if re.fullmatch(r"word/(header|footer)\d*\.xml", nome):
            for p in etree.fromstring(zip_.read(nome)).iter(f"{W}p"):
                texto = normalizar(_texto_paragrafo(p))
                if texto:
                    textos.add(texto)
    return textos


def converter_docx(dados: bytes) -> Conversao:
    blocos, fonte, avisos = blocos_docx(dados)
    conversao = estruturar(blocos, fonte)
    conversao.avisos = list(dict.fromkeys(avisos + conversao.avisos))
    return conversao
