"""Verificação de fidelidade: o Markdown gerado deve conter exatamente as palavras do original.

Em vez de comparar a saída do conversor com ela mesma (verificação circular), aqui a
referência é o texto visível extraído diretamente do arquivo original, de forma independente da
estruturação. Compara-se a sequência de palavras (letras e números), ignorando só espaços,
pontuação de marcação Markdown e as etiquetas da tabela HTML.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

_PALAVRA = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class ResultadoFidelidade:
    ok: bool
    palavras_fonte: int
    palavras_markdown: int
    similaridade: float
    detalhe: str | None


def palavras(texto: str) -> list[str]:
    return _PALAVRA.findall(unicodedata.normalize("NFC", texto))


def texto_do_markdown(markdown: str) -> str:
    texto = re.sub(r"</?(table|tr|td|s)>", " ", markdown)
    texto = re.sub(r"(?m)^\s*(#{1,6}|>)\s+", "", texto)
    return texto.replace("**", "").replace("*", " ")


@dataclass(frozen=True)
class ResultadoCruzado:
    """Conferência do Markdown (gerado de uma fonte) contra outro arquivo oficial do mesmo texto (PDF)."""

    consistente: bool
    cobertura_markdown_no_pdf: float  # fração das palavras do Markdown encontradas no PDF
    cobertura_pdf_no_markdown: float  # fração das palavras do PDF encontradas no Markdown
    similaridade_sequencia: float
    faltam_no_markdown: tuple[str, ...]
    faltam_no_pdf: tuple[str, ...]


LIMIAR_COBERTURA = 0.995
_COLADA = re.compile(r"^(\D+?)(\d{1,3})$")


def conferir_com_pdf(markdown: str, texto_pdf: str) -> ResultadoCruzado:
    """Compara palavras (sem diferenciar maiúsculas: o Word aplica caixa alta por formatação).

    Critério: cada lado deve conter pelo menos 99,5% das palavras do outro (contagem com repetição).
    A similaridade de sequência é informativa: notas de rodapé e células de tabela mudam de posição
    entre o DOCX e o PDF sem alterar o texto.
    """
    from collections import Counter

    # Chamada de nota de rodapé: no Markdown é "[^n]"; no PDF o número pode sair colado à palavra ("iii1").
    a = [p.lower() for p in palavras(texto_do_markdown(markdown))]
    vocabulario = set(a)
    b = []
    for p in (p.lower() for p in palavras(texto_pdf)):
        m = _COLADA.match(p)
        b += m.groups() if m and p not in vocabulario and m.group(1) in vocabulario else [p]
    ca, cb = Counter(a), Counter(b)
    comuns = sum((ca & cb).values())
    cob_a = comuns / len(a) if a else 0.0
    cob_b = comuns / len(b) if b else 0.0
    sequencia = difflib.SequenceMatcher(a=a, b=b, autojunk=len(a) > 100_000).ratio() if a and b else 0.0
    faltam_md = tuple(f"{p}×{n}" for p, n in (cb - ca).most_common(12))
    faltam_pdf = tuple(f"{p}×{n}" for p, n in (ca - cb).most_common(12))
    return ResultadoCruzado(min(cob_a, cob_b) >= LIMIAR_COBERTURA, round(cob_a, 5), round(cob_b, 5),
                            round(sequencia, 4), faltam_md, faltam_pdf)


def cobertura_ementa(ementa: str | None, texto: str) -> float:
    """Fração das palavras da ementa (da ficha oficial) presentes no texto. Usada para conferir OCR."""
    from collections import Counter

    alvo = Counter(p.lower() for p in palavras(ementa or ""))
    if not alvo:
        return 0.0
    achadas = Counter(p.lower() for p in palavras(texto)) & alvo
    return sum(achadas.values()) / sum(alvo.values())


def verificar(texto_fonte: str, markdown: str) -> ResultadoFidelidade:
    fonte = palavras(texto_fonte)
    saida = palavras(texto_do_markdown(markdown))
    if fonte == saida:
        return ResultadoFidelidade(True, len(fonte), len(saida), 1.0, None)
    matcher = difflib.SequenceMatcher(a=fonte, b=saida, autojunk=False)
    diferencas = []
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op != "equal":
            diferencas.append(f"{op}: original[{' '.join(fonte[a1:a2][:8])}] markdown[{' '.join(saida[b1:b2][:8])}]")
        if len(diferencas) >= 3:
            break
    return ResultadoFidelidade(False, len(fonte), len(saida), round(matcher.ratio(), 4), "; ".join(diferencas))
