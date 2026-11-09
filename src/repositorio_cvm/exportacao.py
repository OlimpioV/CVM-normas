"""Exportação de um documento do acervo para Word (.docx), PDF, Markdown e texto simples (§10).

O conteúdo exportado é o Markdown da versão escolhida, sem alteração do texto: na versão alterada, a
redação anterior continua riscada (no TXT, marcada com "[redação anterior]"); na consolidada, só há o
texto vigente; as notas de alteração e de rodapé são mantidas. Todo arquivo começa com o cabeçalho de identificação: norma, versão
do texto e data de coleta, situação normativa conhecida, fonte oficial e aviso de vigência.
"""

from __future__ import annotations

import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from lxml import html as lhtml

from repositorio_cvm import acervo

FORMATOS = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "md": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
}
AVISO_CONVERSAO = ("Conversão automática do texto oficial. Em caso de divergência, prevalece o original "
                   "publicado pela CVM.")


class ExportacaoError(Exception):
    pass


@dataclass
class Exportado:
    conteudo: bytes
    nome: str
    tipo_mime: str


def cabecalho(doc: acervo.Documento, versao: acervo.Versao, agora: datetime,
              parte: acervo.Parte | None = None) -> list[tuple[str, str]]:
    linha = doc.linha
    return [
        ("Norma", doc.titulo),
        *([("Parte", f"{parte.titulo} (somente esta parte da norma)")] if parte else []),
        ("Ementa", linha["ementa"] or "—"),
        ("Versão do texto", f"{versao.nome}, arquivo oficial coletado em {acervo.data_br(versao.coletado_em[:10])}"),
        ("Sobre esta versão", versao.aviso),
        ("Situação normativa", linha["situacao"]),
        ("Fonte oficial", linha["url_oficial"] or "—"),
        ("Arquivo de origem", f"{versao.url_fonte} (SHA-256 {versao.sha256[:16]}…)"),
        ("Qualidade da conversão", versao.qualidade.split(";", 1)[0]),
        ("Aviso de vigência", doc.aviso_vigencia()),
        ("Aviso", AVISO_CONVERSAO),
        ("Exportado em", agora.strftime("%d/%m/%Y %H:%M")),
    ]


def nome_arquivo(doc: acervo.Documento, versao: acervo.Versao, formato: str, parte: acervo.Parte | None = None) -> str:
    sufixo = {"consolidado": "consolidado", "alterada": "alterado-com-tachado-gerado",
              "oficial": "consolidado-oficial-com-tachado"}.get(versao.chave, "original")
    return f"{doc.id}-{sufixo}{'-' + parte.chave if parte else ''}.{formato}"


def exportar(doc: acervo.Documento, pasta_dados: Path, formato: str, versao_preferida: str = "consolidado",
             agora: datetime | None = None, conexao=None, parte: str | None = None) -> Exportado:
    """`parte`: chave de uma parte da norma (ex.: "anexo-normativo-i"); exige a `conexao` com o banco."""
    if formato not in FORMATOS:
        raise ExportacaoError(f"formato não suportado: {formato}")
    versao = doc.versao(versao_preferida)
    if versao is None:
        raise ExportacaoError("documento sem texto integral convertido e aprovado")
    agora = agora or datetime.now()
    escolhida = None
    if parte:
        if conexao is None:
            raise ExportacaoError("exportação de parte exige acesso ao banco")
        lista = acervo.partes(conexao, doc, versao)
        escolhida = next((p for p in lista if p.chave == parte), None)
        if escolhida is None:
            disponiveis = ", ".join(p.chave for p in lista) or "a norma não tem partes"
            raise ExportacaoError(f"parte '{parte}' não existe no {versao.tipo} ({disponiveis})")
        try:
            corpo_md = acervo.markdown_parte(pasta_dados, conexao, versao, escolhida)
        except ValueError as erro:
            raise ExportacaoError(str(erro)) from erro
    else:
        corpo_md = acervo.markdown(pasta_dados, versao)
    campos = cabecalho(doc, versao, agora, escolhida)
    gerador = {"md": _md, "txt": _txt, "docx": _docx, "pdf": _pdf}[formato]
    return Exportado(gerador(campos, corpo_md), nome_arquivo(doc, versao, formato, escolhida), FORMATOS[formato])


# ---------------------------------------------------------------------- Markdown e texto
def _md(campos: list[tuple[str, str]], corpo: str) -> bytes:
    topo = "".join(f"> **{rotulo}:** {valor}  \n" for rotulo, valor in campos)
    return (topo + "\n---\n\n" + corpo).encode("utf-8")


def texto_simples(corpo_md: str) -> str:
    """Texto do HTML renderizado; redação anterior (tachada) marcada, tabelas com células separadas por " | "."""
    arvore = lhtml.fragment_fromstring(acervo.html(corpo_md) or "<p></p>", create_parent="div")
    for s in arvore.iter("s", "del", "strike"):
        s.text = "[redação anterior] " + (s.text or "")
    linhas: list[str] = []
    for bloco in arvore.iter("h1", "h2", "h3", "h4", "h5", "h6", "p", "tr", "blockquote", "pre"):
        if bloco.tag == "blockquote" or (bloco.tag == "p" and _dentro(bloco, ("td", "th"))):
            continue
        if bloco.tag == "tr":
            texto = " | ".join(" ".join(c.text_content().split()) for c in bloco if c.tag in ("td", "th"))
        else:
            texto = " ".join(bloco.text_content().split())
        if not texto:
            continue
        if _dentro(bloco, ("blockquote",)):
            texto = "    " + texto
        linhas.append(texto)
    return "\n\n".join(linhas) + "\n"


def _dentro(no, tags: tuple[str, ...]) -> bool:
    pai = no.getparent()
    while pai is not None:
        if pai.tag in tags:
            return True
        pai = pai.getparent()
    return False


def _txt(campos: list[tuple[str, str]], corpo: str) -> bytes:
    topo = "\n".join(f"{rotulo}: {valor}" for rotulo, valor in campos)
    return (topo + "\n" + "=" * 72 + "\n\n" + texto_simples(corpo)).encode("utf-8")


# ---------------------------------------------------------------------- PDF (fpdf2)
# Conjuntos de fontes aceitos, em ordem de preferência: (pastas, {estilo: arquivo}, arquivo de símbolos).
# Windows: Arial + Segoe UI Symbol (□ e outros símbolos ausentes da Arial). Linux e macOS: DejaVu Sans, que já
# tem os símbolos (pacote fonts-dejavu no Debian/Ubuntu; no macOS, instale-a ou use o conjunto Arial).
CONJUNTOS_FONTES = [
    ([Path("C:/Windows/Fonts")],
     {"": "arial.ttf", "B": "arialbd.ttf", "I": "ariali.ttf", "BI": "arialbi.ttf"}, "seguisym.ttf"),
    ([Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"), Path("/usr/share/fonts/TTF"),
      Path("/usr/local/share/fonts"), Path.home() / "Library/Fonts", Path("/Library/Fonts"),
      Path.home() / ".local/share/fonts"],
     {"": "DejaVuSans.ttf", "B": "DejaVuSans-Bold.ttf", "I": "DejaVuSans-Oblique.ttf",
      "BI": "DejaVuSans-BoldOblique.ttf"}, "DejaVuSans.ttf"),
]


def localizar_fontes() -> tuple[dict[str, Path], Path]:
    """Arquivos de fonte do primeiro conjunto completo encontrado (todos os estilos na mesma pasta)."""
    for pastas, estilos, simbolos in CONJUNTOS_FONTES:
        for pasta in pastas:
            if all((pasta / n).is_file() for n in [*estilos.values(), simbolos]):
                return {e: pasta / n for e, n in estilos.items()}, pasta / simbolos
    raise ExportacaoError("fontes para o PDF não encontradas: no Windows, Arial e Segoe UI Symbol "
                          "(C:/Windows/Fonts); no Linux ou macOS, DejaVu Sans (ex.: apt install fonts-dejavu)")


def conferir_pdf(dados: bytes, referencia: str) -> list[str]:
    """Palavras do texto de referência que não aparecem no PDF (vazio = completo).

    Comparação por contagem de palavras após normalização NFKC (ligaduras "ﬁ" saem expandidas na extração).
    Sequências longas sem espaço (URLs, pontilhado de sumário) são quebradas pelo layout no meio; por isso
    são conferidas à parte, sem os espaços, em vez de palavra por palavra.
    """
    from repositorio_cvm.conversao.fidelidade import palavras

    texto_pdf = unicodedata.normalize("NFKC", _texto_pdf(dados))
    referencia = unicodedata.normalize("NFKC", referencia)
    longas = re.findall(r"\S{40,}", referencia)
    contagem_ref = Counter(palavras(re.sub(r"\S{40,}", " ", referencia)))
    faltando = contagem_ref - Counter(palavras(texto_pdf))
    compacto = re.sub(r"[^\w]", "", texto_pdf)
    # Palavra partida pelo layout numa célula estreita ("fin anceiros") continua presente no texto sem espaços:
    # aceita-se se ali aparecer ao menos tantas vezes quanto na referência.
    ausentes = [p for p, n in faltando.items() if compacto.count(p) < contagem_ref[p] for _ in range(n)]
    ausentes += [l for l in longas if "".join(palavras(l)) not in compacto]
    return ausentes


def _texto_pdf(dados: bytes) -> str:
    import pymupdf

    return "\n".join(p.get_text(flags=0) for p in pymupdf.open(stream=dados, filetype="pdf"))


def _html_para_pdf(texto_html: str) -> str:
    """Ajustes para o fpdf2: links internos (notas de rodapé) viram texto simples."""
    raiz = lhtml.fragment_fromstring(texto_html, create_parent="div")
    for a in raiz.iter("a"):
        if (a.get("href") or "").startswith("#"):
            del a.attrib["href"]
            a.tag = "span"
    for no in raiz.iter():
        no.attrib.pop("id", None)
    # O fpdf2 dimensiona a grade pela primeira linha e descarta células excedentes das demais: linhas com
    # menos células têm a última estendida (colspan) até o número máximo de colunas da tabela.
    for tabela in raiz.iter("table"):
        linhas = [[c for c in tr if c.tag in ("td", "th")] for tr in tabela.iter("tr")]
        maximo = max((sum(int(c.get("colspan", 1)) for c in l) for l in linhas if l), default=0)
        for celulas in linhas:
            largura = sum(int(c.get("colspan", 1)) for c in celulas)
            if celulas and largura < maximo:
                ultima = celulas[-1]
                ultima.set("colspan", str(int(ultima.get("colspan", 1)) + maximo - largura))
    # Dentro de células o fpdf2 só aceita formatação simples; outras marcas são removidas, mantendo o texto. O
    # tachado não é aceito na célula: a redação anterior fica identificada entre colchetes, como no TXT.
    for celula in raiz.iter("td", "th"):
        for no in list(celula.iterdescendants()):
            if no.tag in ("s", "del", "strike"):
                no.text = "[redação anterior: " + (no.text or "")
                no.tail = "]" + (no.tail or "")
                no.drop_tag()
            elif no.tag not in ("b", "strong", "i", "em", "u", "br"):
                no.drop_tag()
    return (raiz.text or "") + "".join(lhtml.tostring(f, encoding="unicode") for f in raiz)


def _pdf(campos: list[tuple[str, str]], corpo: str) -> bytes:
    """Gera o PDF e confere, palavra por palavra, que todo o texto do Markdown está nele; se faltar algo,
    a exportação falha em vez de entregar um documento incompleto."""
    import logging

    from fpdf import FPDF
    from fpdf.fonts import TextStyle

    from repositorio_cvm.conversao.fidelidade import texto_do_markdown

    fontes, fonte_simbolos = localizar_fontes()
    norma = dict(campos)["Norma"]

    class Documento(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("arial", size=7)
            self.set_text_color(110)
            self.cell(0, 5, f"{norma} — página {self.page_no()} de {{nb}}", align="C")

    pdf = Documento(format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.set_auto_page_break(True, 18)
    for estilo, caminho in fontes.items():
        pdf.add_font("arial", estilo, str(caminho))
    pdf.add_font("simbolos", "", str(fonte_simbolos))
    pdf.set_fallback_fonts(["simbolos"])
    pdf.set_title(norma)
    pdf.set_creator("Repositório Normativo CVM")
    pdf.add_page()
    for rotulo, valor in campos:
        pdf.set_font("arial", "B", 8)
        pdf.write(4, f"{rotulo}: ")
        pdf.set_font("arial", "", 8)
        pdf.write(4, str(valor))
        pdf.ln(5)
    pdf.ln(2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(4)
    pdf.set_font("arial", size=10)
    # O fpdf2 avisa (logging) a cada glifo resolvido pela fonte de símbolos; não é erro.
    logging.getLogger("fpdf").setLevel(logging.ERROR)
    logging.getLogger("fontTools").setLevel(logging.ERROR)
    try:
        titulos = {f"h{n}": TextStyle(font_family="arial", font_style="B", font_size_pt=t, color=0, t_margin=4,
                                      b_margin=2, l_margin="C") for n, t in ((1, 12), (2, 11), (3, 10.5), (4, 10))}
        pdf.write_html(_html_para_pdf(acervo.html(corpo)), font_family="arial", tag_styles=titulos,
                       table_line_separators=True)
    except Exception as erro:  # noqa: BLE001 - qualquer falha de layout vira erro de exportação explícito
        raise ExportacaoError(f"PDF: falha no layout do texto ({type(erro).__name__}: {erro})") from erro
    dados = bytes(pdf.output())
    ausentes = conferir_pdf(dados, " ".join(f"{r} {v}" for r, v in campos) + " " + texto_do_markdown(corpo))
    if ausentes:
        raise ExportacaoError(f"PDF incompleto: {len(ausentes)} palavras do texto não foram encontradas no PDF "
                              f"gerado (ex.: {', '.join(ausentes[:5])})")
    return dados


# ---------------------------------------------------------------------- Word (python-docx)
def _docx(campos: list[tuple[str, str]], corpo: str) -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    documento = Document()
    estilo = documento.styles["Normal"]
    estilo.font.name = "Arial"
    estilo.font.size = Pt(10)
    tabela = documento.add_table(rows=0, cols=2)
    tabela.style = "Table Grid"
    for rotulo, valor in campos:
        celulas = tabela.add_row().cells
        celulas[0].text = rotulo
        celulas[1].text = str(valor)
        for c in celulas:
            for p in c.paragraphs:
                for run in p.runs:
                    run.font.size = Pt(8)
        celulas[0].paragraphs[0].runs[0].bold = True
    documento.add_paragraph()

    arvore = lhtml.fragment_fromstring(acervo.html(corpo) or "<p></p>", create_parent="div")

    def inline(paragrafo, no, negrito=False, italico=False, riscado=False, sobrescrito=False):
        def run(texto):
            if not texto:
                return
            r = paragrafo.add_run(texto)
            r.bold, r.italic = negrito or None, italico or None
            if riscado:
                r.font.strike = True
                r.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
            if sobrescrito:
                r.font.superscript = True
        run(no.text)
        for filho in no:
            if filho.tag == "br":
                paragrafo.add_run().add_break()
            elif isinstance(filho.tag, str):
                inline(paragrafo, filho,
                       negrito or filho.tag in ("strong", "b"),
                       italico or filho.tag in ("em", "i"),
                       riscado or filho.tag in ("s", "del", "strike"),
                       sobrescrito or filho.tag == "sup")
            run(filho.tail)

    def bloco(no, recuo=0):
        tag = no.tag
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            p = documento.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            inline(p, no, negrito=True)
            for r in p.runs:
                r.font.size = Pt({"h1": 12, "h2": 11}.get(tag, 10))
        elif tag == "p":
            p = documento.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            if recuo:
                p.paragraph_format.left_indent = Pt(18 * recuo)
            inline(p, no)
        elif tag == "blockquote":
            for filho in no:
                bloco(filho, recuo + 1)
        elif tag == "table":
            linhas = [tr for tr in no.iter("tr")]
            colunas = max((len([c for c in tr if c.tag in ("td", "th")]) for tr in linhas), default=0)
            if not colunas:
                return
            t = documento.add_table(rows=0, cols=colunas)
            t.style = "Table Grid"
            for tr in linhas:
                celulas = t.add_row().cells
                for i, c in enumerate([c for c in tr if c.tag in ("td", "th")]):
                    paragrafo = celulas[i].paragraphs[0]
                    inline(paragrafo, c, negrito=c.tag == "th")
            documento.add_paragraph()
        elif tag == "hr":
            documento.add_paragraph("—" * 20).alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif tag in ("section", "div"):
            for filho in no:
                bloco(filho, recuo)
        elif tag == "pre":
            documento.add_paragraph(no.text_content())

    for filho in arvore:
        bloco(filho)
    saida = io.BytesIO()
    documento.core_properties.title = dict(campos)["Norma"]
    documento.save(saida)
    return saida.getvalue()

