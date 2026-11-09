"""Decodificação de fontes Type3 sem tabela de caracteres (PDFs do SEI "impressos" pelo PDF24/Ghostscript).

Nesses PDFs cada letra é um desenho (CharProc) com um código próprio e não há `ToUnicode`: o texto existe,
mas "cifrado". Como o mesmo código, na mesma fonte, é sempre o mesmo desenho, descobre-se a letra de cada
desenho por votação com o OCR da mesma linha e aplica-se o mapa à camada de texto original. O resultado não
traz os erros pontuais do OCR: a letra é traduzida, não lida em cada posição.

Etapas (D-14):
1. identidade do desenho = SHA-1 do programa do glifo (CharProc); desenhos idênticos em páginas, fontes ou
   documentos diferentes são a mesma letra;
2. 1ª rodada: linhas do PDF e do OCR pareadas pela posição; nas que têm a mesma quantidade de caracteres,
   vota-se posição a posição;
3. rodadas seguintes: a linha decifrada e a do OCR (agora no mesmo alfabeto) são alinhadas por comparação
   de sequências; vota-se nos trechos casados com contexto (≥ 3 caracteres) e nas trocas de mesmo tamanho;
4. desenho com concordância < 75% ou sem voto: usa-se o dicionário de glifos do acervo (desenhos já
   decifrados em outros documentos com concordância ≥ 90%); sem isso, o caractere fica marcado com "□".
Nada é adivinhado: caractere incerto aparece como "□" e entra na contagem do relatório.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import median

import pymupdf

CONVERSOR = "pdf-type3-decifrado/3"
INCERTO = "□"
LIMIAR_CONCORDANCIA = 0.75
LIMIAR_DICIONARIO = 0.90
_FONTE_TYPE3 = re.compile(r"Type3 \((\d+) 0 R\)")


@dataclass
class Decifracao:
    mapa: dict[tuple[int, int], str]  # (xref da fonte, código) -> caractere ("□" se incerto)
    votos: dict[str, Counter]  # hash do desenho -> votos de letras do OCR
    hash_por_codigo: dict[tuple[int, int], str]
    ocorrencias: int = 0
    incertas: int = 0
    resolvidos_pelo_dicionario: int = 0
    resolvidos_pelo_lexico: int = 0
    decididos_pelo_lexico: dict[str, str] = field(default_factory=dict)
    exemplos_incertos: list[str] = field(default_factory=list)

    @property
    def fracao_incerta(self) -> float:
        return self.incertas / self.ocorrencias if self.ocorrencias else 1.0


def fontes_type3_sem_unicode(doc: pymupdf.Document) -> set[int]:
    xrefs = set()
    for pagina in doc:
        for xref, _ext, tipo, *_ in pagina.get_fonts(full=True):
            if tipo == "Type3" and doc.xref_get_key(xref, "ToUnicode")[0] == "null":
                xrefs.add(xref)
    return xrefs


def _hashes_dos_glifos(doc: pymupdf.Document, xref: int) -> dict[int, str]:
    """código -> SHA-1 do programa do glifo, a partir de /Encoding /Differences e /CharProcs."""
    procs = dict(re.findall(r"/([^\s/<>\[\]]+)\s+(\d+)\s+0\s+R", doc.xref_get_key(xref, "CharProcs")[1]))
    tipo, valor = doc.xref_get_key(xref, "Encoding")
    if tipo == "xref":
        diferencas = doc.xref_get_key(int(valor.split()[0]), "Differences")[1]
    else:
        diferencas = doc.xref_get_key(xref, "Encoding/Differences")[1]
    saida, codigo = {}, None
    for token in re.findall(r"\d+|/[^\s/\[\]]+", diferencas):
        if token.startswith("/"):
            if codigo is not None and token[1:] in procs:
                saida[codigo] = hashlib.sha1(doc.xref_stream(int(procs[token[1:]]))).hexdigest()
            codigo = codigo + 1 if codigo is not None else None
        else:
            codigo = int(token)
    return saida


def _linhas(pagina_dict: dict, fontes: set[int] | None = None) -> list[tuple[tuple, list]]:
    """[(bbox, [(xref, código) ou caractere, ...])]; com `fontes`, só linhas com glifos Type3."""
    saida = []
    for b in pagina_dict["blocks"]:
        for l in b.get("lines", []):
            itens = []
            for s in l["spans"]:
                m = _FONTE_TYPE3.match(s["font"])
                for c in s["chars"]:
                    if fontes is not None and m and int(m.group(1)) in fontes:
                        itens.append((int(m.group(1)), ord(c["c"])))
                    elif fontes is None:
                        itens.append(c["c"])
            if itens:
                saida.append((l["bbox"], itens))
    return saida


def _melhor_deslocamento(orig: list, ocr: list) -> float:
    candidatos = {round(bb[1] - ob[1]) for bb, _ in orig for ob, _ in ocr if abs(bb[1] - ob[1]) <= 25}

    def pontuacao(desl: float) -> int:
        casadas = 0
        for bb, ks in orig:
            for ob, t in ocr:
                if abs(bb[1] - desl - ob[1]) <= 3 and abs(bb[0] - ob[0]) <= 6 and len(t) == len(ks):
                    casadas += 1
                    break
        return casadas

    return max(sorted(candidatos), key=pontuacao, default=0.0)


def _resolver_pelo_lexico(votos: dict[str, Counter], linhas: list[list[str]], lexico: set[str],
                          mapa: dict[str, str]) -> dict[str, tuple[str, float]]:
    """Desenhos incertos: entre as letras votadas pelo OCR, escolhe a que forma palavras existentes nos textos
    oficiais do acervo (critérios no corpo da função; D-14)."""
    decididos = {}
    for k, cont in votos.items():
        total = sum(cont.values())
        if cont.most_common(1)[0][1] / total >= LIMIAR_CONCORDANCIA:
            continue
        candidatas = [letra for letra, _ in cont.most_common(3) if letra.isalpha()]
        if len(candidatas) < 2:
            continue
        palavras_com_k = []
        for ks in linhas:
            if k not in ks:
                continue
            texto = "".join("\x00" if x == k else mapa.get(x, "\x01") for x in ks)
            palavras_com_k += [w for w in re.findall(r"[\w\x00]+", texto) if "\x00" in w and "\x01" not in w]
        if not palavras_com_k:
            continue
        validas = {c: sum(w.replace("\x00", c).lower() in lexico for w in palavras_com_k) for c in candidatas}
        ordem = sorted(validas.items(), key=lambda t: -t[1])
        (melhor, n1), (_, n2) = ordem[0], ordem[1]
        taxa1, taxa2 = n1 / len(palavras_com_k), n2 / len(palavras_com_k)
        # Decide se a escolhida valida ≥ 80% das palavras com folga de 30 pontos, ou se forma ≥ 2 palavras
        # existentes enquanto as alternativas não formam nenhuma (ex.: "Ofício" x "Oficio").
        if (taxa1 >= 0.8 and taxa1 - taxa2 >= 0.3) or (n1 >= 2 and n2 == 0):
            decididos[k] = (melhor, taxa1)
    return decididos


def decifrar(dados: bytes, tessdata: str, dicionario: dict[str, tuple[str, float, int]] | None = None,
             lexico: set[str] | None = None, rodadas: int = 6) -> Decifracao:
    """`dicionario`: hash do desenho -> (caractere, concordância, votos), acumulado no acervo.
    `lexico`: palavras (minúsculas) dos textos oficiais já convertidos, para desempatar letras incertas."""
    doc = pymupdf.open(stream=dados, filetype="pdf")
    fontes = fontes_type3_sem_unicode(doc)
    hash_por_codigo: dict[tuple[int, int], str] = {}
    for xref in fontes:
        for codigo, h in _hashes_dos_glifos(doc, xref).items():
            hash_por_codigo[(xref, codigo)] = h

    def chave(item: tuple[int, int]) -> str:
        return hash_por_codigo.get(item, f"{item[0]}:{item[1]}")

    pares: list[tuple[list[str], str]] = []  # (desenhos da linha do PDF, texto OCR da linha correspondente)
    todas_linhas: list[list[str]] = []
    ocorrencias = 0
    for pagina in doc:
        tp = pagina.get_textpage_ocr(language="por", dpi=400, full=True, tessdata=tessdata)
        ocr = [(bbox, "".join(cs)) for bbox, cs in _linhas(pagina.get_text("rawdict", textpage=tp))]
        orig = [(bbox, [chave(i) for i in itens]) for bbox, itens in _linhas(pagina.get_text("rawdict"), fontes)]
        ocorrencias += sum(len(i) for _, i in orig)
        todas_linhas += [ks for _, ks in orig]
        if not ocr or not orig:
            continue
        # As caixas dos glifos Type3 vêm deslocadas na vertical e as linhas ficam a ~13 pt umas das outras,
        # então "a mais próxima" pode ser a vizinha. Escolhe-se o deslocamento que faz mais linhas casarem
        # (mesma margem esquerda e mesma quantidade de caracteres).
        deslocamento = _melhor_deslocamento(orig, ocr)
        for bbox, ks in orig:
            dist, texto = min(((abs(bbox[1] - deslocamento - ob[1]) + abs(bbox[0] - ob[0]), t) for ob, t in ocr),
                              key=lambda x: x[0])
            if dist <= 6:
                pares.append((ks, texto))

    votos: dict[str, Counter] = defaultdict(Counter)
    for ks, texto in pares:
        if len(ks) == len(texto):
            for k, letra in zip(ks, texto):
                votos[k][letra] += 1
    mapa = {k: v.most_common(1)[0][0] for k, v in votos.items()}
    for _ in range(rodadas):
        rodada: dict[str, Counter] = defaultdict(Counter)
        for ks, texto in pares:
            decifrado = "".join(mapa.get(k, "\x00") for k in ks)
            sm = difflib.SequenceMatcher(None, decifrado, texto, autojunk=False)
            for op, a1, a2, b1, b2 in sm.get_opcodes():
                if (op == "equal" and a2 - a1 >= 3) or (op == "replace" and a2 - a1 == b2 - b1):
                    for k in range(a2 - a1):
                        rodada[ks[a1 + k]][texto[b1 + k]] += 1
        novo = dict(mapa)
        novo.update({k: v.most_common(1)[0][0] for k, v in rodada.items()})
        estavel = novo == mapa
        mapa = novo
        if estavel:
            # Votos finais: os da rodada estável (mapa já convergido) somados aos da 1ª rodada para desenhos
            # que não voltaram a aparecer em trechos alinhados.
            for k, v in votos.items():
                if k not in rodada:
                    rodada[k] = v
            votos = rodada
            break
    else:
        for k, v in rodada.items():
            votos[k] = v

    resultado = Decifracao(mapa={}, votos=dict(votos), hash_por_codigo=hash_por_codigo, ocorrencias=ocorrencias)
    dicionario = dicionario or {}
    pelo_lexico = _resolver_pelo_lexico(votos, todas_linhas, lexico, mapa) if lexico else {}
    resultado.decididos_pelo_lexico = {k: v[0] for k, v in pelo_lexico.items()}
    for pagina in doc:
        for _, itens in _linhas(pagina.get_text("rawdict"), fontes):
            for item in itens:
                k = chave(item)
                cont = votos.get(k)
                letra = None
                if cont:
                    melhor, n = cont.most_common(1)[0]
                    if n / sum(cont.values()) >= LIMIAR_CONCORDANCIA:
                        letra = melhor
                if letra is None and k in pelo_lexico:
                    letra = pelo_lexico[k][0]
                    resultado.resolvidos_pelo_lexico += 1
                if letra is None and k in dicionario and dicionario[k][1] >= LIMIAR_DICIONARIO:
                    letra = dicionario[k][0]
                    resultado.resolvidos_pelo_dicionario += 1
                if letra is None:
                    letra = INCERTO
                    resultado.incertas += 1
                    if len(resultado.exemplos_incertos) < 10 and cont:
                        resultado.exemplos_incertos.append(
                            "/".join(f"{l}×{n}" for l, n in cont.most_common(2)))
                resultado.mapa[item] = letra
    return resultado
