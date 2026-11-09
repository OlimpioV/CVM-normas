"""Extração da camada de texto de PDFs oficiais com PyMuPDF (D-03).

- Cabeçalhos e rodapés: quando há DOCX oficial do mesmo ato, removem-se do PDF só as linhas que
  correspondem ao cabeçalho/rodapé do DOCX; sem DOCX, só linhas que se repetem na mesma altura em
  todas as páginas (documentos curtos) ou na maioria delas. Número isolado só é removido se for o
  número da própria página.
- Parágrafos: as linhas de cada bloco do PyMuPDF são reagrupadas; um parágrafo novo começa em linha
  iniciada por marcador normativo (Art., §, inciso, alínea, CAPÍTULO...). Parágrafo que continua na
  página seguinte (sem pontuação final e seguido de minúscula) é reunido.
- Quebra de linha após hífen é unida sem espaço, mantendo o hífen ("considera-" + "se").
- Páginas sem camada de texto são listadas: exigem OCR (etapa separada, ainda não implementada).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from repositorio_cvm.conversao.html import Bloco, Conversao, estruturar, normalizar

CONVERSOR = "pdf-pymupdf/5"
CONVERSOR_OCR = "pdf-ocr-tesseract/6"  # v6: ficha sem ementa é conferida pelo título do ato
_TITULO = re.compile(r"^(RESOLUÇÃO|INSTRUÇÃO|DELIBERAÇÃO|PARECER|OF[IÍ]CIO|NOTA EXPLICATIVA)\b", re.I)
_MARCADOR = re.compile(
    r"^(Art\.\s*\d|§\s*\d|Parágrafo\s+único|[IVXLCDM]+(-[A-Z])?\s*[–—-]\s|[a-z]\)\s|\d{1,3}\.\s|"
    r"(LIVRO|PARTE|T[IÍ]TULO|CAP[IÍ]TULO|SE[CÇ][AÃ]O|SUBSE[CÇ][AÃ]O|ANEXO)\b)"
)
_PALAVRAS_COMUNS = {"de", "a", "o", "que", "e", "do", "da", "em", "para", "com", "não", "os", "as", "no", "na",
                    "por", "dos", "das", "ao", "se", "ou", "à", "um", "uma"}
# Faixas da página onde ficam timbre/cabeçalho e rodapé.
FAIXA_SUPERIOR = 0.22
FAIXA_INFERIOR = 0.15


@dataclass
class TextoPdf:
    paginas: int
    paginas_sem_texto: list[int] = field(default_factory=list)
    paragrafos: list[str] = field(default_factory=list)
    removidos: list[str] = field(default_factory=list)  # amostra de cabeçalhos/rodapés removidos
    textos_paginas: list[str] = field(default_factory=list)  # texto de cada página (para a legibilidade)

    @property
    def texto(self) -> str:
        return " ".join(self.paragrafos)

    def legibilidade(self) -> tuple[bool, str]:
        """Detecta camada de texto ilegível (fonte sem mapeamento Unicode, comum em PDFs do SEI).

        Critério: caracteres de controle acima de 1% do texto ou palavras muito comuns do português
        ("de", "a", "que"...) abaixo de 12% das palavras (em textos normativos ficam entre 27% e 36%).
        """
        texto = self.texto
        if not texto.strip():
            return False, "PDF sem camada de texto (exige OCR)"
        controle = sum(1 for c in texto if ord(c) < 32) / len(texto)
        palavras = re.findall(r"\w+", texto.lower())
        comuns = sum(1 for p in palavras if p in _PALAVRAS_COMUNS) / max(len(palavras), 1)
        if controle <= 0.01 and comuns < 0.12 and self._prosa_e_tabelas():
            return True, ""  # anexos em tabela (códigos, números) com páginas de texto corrido legíveis
        if controle > 0.01 or comuns < 0.12:
            return False, (f"camada de texto do PDF ilegível (fonte sem mapeamento Unicode; caracteres de "
                           f"controle {controle:.0%}, palavras comuns {comuns:.0%}); exige OCR")
        return True, ""

    def _prosa_e_tabelas(self) -> bool:
        """Página a página: cada página com 100 termos ou mais é prosa legível (palavras comuns >= 12%) ou tabela
        (metade ou mais dos termos com algarismos ou em códigos maiúsculos, como tickers e ISIN), e há ao menos
        uma página de prosa. Texto de fonte sem mapeamento Unicode não é nem uma coisa nem outra."""
        prosa = 0
        for pagina in self.textos_paginas:
            termos = re.findall(r"\w+", pagina)
            if len(termos) < 20:
                continue
            comuns = sum(1 for t in termos if t.lower() in _PALAVRAS_COMUNS) / len(termos)
            if comuns >= 0.12:
                prosa += 1
                continue
            if len(termos) < 100:
                continue  # página curta, como a de assinatura eletrônica do SEI (códigos verificadores, URL)
            codigos = sum(1 for t in termos if any(c.isdigit() for c in t) or (len(t) >= 3 and t.isupper()))
            if codigos / len(termos) < 0.5:
                return False
        return prosa > 0


def _chave(texto: str) -> str:
    return re.sub(r"\d+", "#", normalizar(texto)).lower()


def _letras(texto: str) -> int:
    return sum(c.isalpha() for c in texto)


def _unir(atual: str, linha: str) -> str:
    if not atual:
        return linha
    if re.search(r"\w-$", atual):
        return atual + linha
    return f"{atual} {linha}"


def _e_cabecalho(ocorrencias: list[tuple[int, float]], total: int) -> bool:
    """Mesma linha, na mesma altura (±12 pt), em todas as páginas (até 3) ou em metade delas (mais longos)."""
    if total < 2:
        return False
    exigido = total if total <= 3 else max(3, int(0.5 * total))
    alturas = sorted(y for _, y in ocorrencias)
    mediana = alturas[len(alturas) // 2]
    return len({p for p, y in ocorrencias if abs(y - mediana) <= 12}) >= exigido


def _do_cabecalho_conhecido(chave: str, cabecalhos: set[str]) -> bool:
    return chave in cabecalhos or (len(chave) >= 12 and any(chave in c for c in cabecalhos))


def _numero_de_pagina(texto: str, pagina: int, total: int) -> bool:
    m = re.fullmatch(r"(?:p[áa]g(?:ina)?\.?\s*)?(\d{1,4})(?:\s*(?:/|de)\s*(\d{1,4}))?", texto, re.I)
    return bool(m) and int(m.group(1)) == pagina and (m.group(2) is None or int(m.group(2)) == total)


def caminho_tessdata(pasta: Path) -> str | None:
    """Caminho da pasta de modelos do Tesseract utilizável pela biblioteca em C.

    A biblioteca não abre caminhos com acentos (ex.: "Laboratório"); no Windows usa-se o nome curto 8.3.
    """
    if not (pasta / "por.traineddata").is_file():
        return None
    caminho = str(pasta.resolve())
    if not caminho.isascii() and sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(caminho, buffer, 1024):
            caminho = buffer.value
    return caminho if caminho.isascii() else None


def _texto_da_linha(linha: dict, mapa_type3: dict[tuple[int, int], str] | None) -> str:
    if mapa_type3 is None:
        return "".join(s["text"] for s in linha["spans"])
    partes = []
    for s in linha["spans"]:
        m = re.match(r"Type3 \((\d+) 0 R\)", s["font"])
        xref = int(m.group(1)) if m else None
        for c in s["chars"]:
            partes.append(mapa_type3.get((xref, ord(c["c"])), c["c"]) if xref is not None else c["c"])
    return "".join(partes)


def extrair(dados: bytes, cabecalhos: set[str] | None = None, tessdata: str | None = None,
            mapa_type3: dict[tuple[int, int], str] | None = None) -> TextoPdf:
    """Extrai o texto do PDF. Com `tessdata`, o texto vem de OCR (Tesseract embutido no PyMuPDF, 300 dpi,
    modelo de português) em vez da camada de texto do arquivo. Com `mapa_type3` (ver `type3.decifrar`), os
    códigos das fontes Type3 sem tabela de caracteres são traduzidos para as letras decifradas."""
    doc = pymupdf.open(stream=dados, filetype="pdf")
    conhecidos = {_chave(c) for c in cabecalhos} if cabecalhos else None
    paginas = []
    margens: dict[str, list[tuple[int, float]]] = {}
    for numero_pagina, pagina in enumerate(doc, 1):
        altura = pagina.rect.height
        blocos = []
        camada = (pagina.get_textpage_ocr(language="por", dpi=300, full=True, tessdata=tessdata)
                  if tessdata else None)
        modo = "rawdict" if mapa_type3 is not None else "dict"
        for b in pagina.get_text(modo, sort=False, textpage=camada)["blocks"]:
            if b.get("type") != 0:
                continue
            linhas = []
            for linha in b["lines"]:
                texto = normalizar(_texto_da_linha(linha, mapa_type3))
                if not texto:
                    continue
                y0, y1 = linha["bbox"][1], linha["bbox"][3]
                na_margem = y0 < altura * FAIXA_SUPERIOR or y1 > altura * (1 - FAIXA_INFERIOR)
                linhas.append((texto, na_margem))
                if na_margem and _letras(texto) >= 3:
                    margens.setdefault(_chave(texto), []).append((numero_pagina, round(y0, 1)))
            blocos.append(linhas)
        paginas.append(blocos)
    total = len(paginas)
    if conhecidos is not None:
        repetidas = {k for k in margens if _do_cabecalho_conhecido(k, conhecidos)}
    else:
        repetidas = {k for k, oc in margens.items() if _e_cabecalho(oc, total)}

    resultado = TextoPdf(paginas=total)
    atual = ""
    resultado.textos_paginas = [" ".join(t for linhas in blocos for t, _ in linhas) for blocos in paginas]
    for numero, blocos in enumerate(paginas, 1):
        tem_texto = False
        for i_bloco, linhas in enumerate(blocos):
            for i_linha, (texto, na_margem) in enumerate(linhas):
                titulo_na_capa = numero == 1 and _TITULO.match(texto)
                if na_margem and not titulo_na_capa and (
                        (_letras(texto) >= 3 and _chave(texto) in repetidas) or _numero_de_pagina(texto, numero, total)):
                    if len(resultado.removidos) < 20 and texto not in resultado.removidos:
                        resultado.removidos.append(texto)
                    continue
                tem_texto = True
                inicio_de_bloco = i_linha == 0
                continua = (inicio_de_bloco and atual and not re.search(r"[.;:!?]$", atual)
                            and texto[:1].islower() and not _MARCADOR.match(texto))
                if atual and (_MARCADOR.match(texto) or (inicio_de_bloco and not continua)):
                    resultado.paragrafos.append(atual)
                    atual = ""
                atual = _unir(atual, texto)
        if not tem_texto:
            resultado.paginas_sem_texto.append(numero)
    if atual:
        resultado.paragrafos.append(atual)
    return resultado


def converter_pdf(dados: bytes, cabecalhos: set[str] | None = None) -> Conversao:
    """Conversão quando o PDF é a única fonte (ofícios, pareceres, redações originais)."""
    texto = extrair(dados, cabecalhos)
    conversao = estruturar([Bloco(p) for p in texto.paragrafos], texto.texto)
    avisos = ["texto extraído da camada de texto do PDF; a divisão em parágrafos é reconstruída e deve ser conferida"]
    if texto.paginas_sem_texto:
        avisos.append(f"páginas sem camada de texto (exigem OCR): {texto.paginas_sem_texto}")
    if texto.removidos:
        avisos.append("cabeçalhos/rodapés removidos: " + " | ".join(texto.removidos[:5]))
    conversao.avisos = list(dict.fromkeys(avisos + conversao.avisos))
    return conversao
