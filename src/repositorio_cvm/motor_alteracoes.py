"""Aplicação automática das alterações de uma norma pelas normas alteradoras (D-21).

O texto da norma é uma lista de itens: os dispositivos, cada um com o seu bloco de Markdown. Cada comando da
alteradora vira operações sobre os itens, localizados pelo rótulo hierárquico que o conversor grava em
`dispositivo.rotulo` ("Anexo Normativo II, art. 31, inciso II"):

- "O art. 5º ... passa a vigorar com a seguinte redação:" / "... com as seguintes alterações:" / "... acrescido
  do seguinte inciso": o texto citado entre aspas é estruturado como um trecho de norma. Linha com o rótulo e
  só pontilhado ("Art. 31. ......") mantém o dispositivo; dispositivo que existe com outro texto recebe a
  redação nova (a anterior fica tachada); dispositivo que não existe é incluído depois do irmão anterior;
- "Fica revogado o inciso III do art. 31 do Anexo II da Resolução...": o dispositivo e os seus subdispositivos
  ficam tachados.

Depois de cada dispositivo alterado entra uma nota no formato das notas da CVM, marcada como gerada
("(alteração aplicada automaticamente)"). Nada é aplicado por suposição: comando não reconhecido ou
dispositivo não localizado fica registrado e aparece como aviso na versão gerada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from repositorio_cvm.conversao.fidelidade import palavras
from repositorio_cvm.conversao.html import (
    _ALINEA, _ARTIGO, _CABECALHO, _INCISO, _ITEM, _MESES, _PARAGRAFO, _PARAGRAFO_UNICO, Bloco, _ordinal,
    estruturar,
)

ESTRUTURAIS = ("artigo", "paragrafo", "inciso", "alinea", "item")
_SO_PONTOS = re.compile(r"^[\s.…_]*$")
_ASPAS = "“”\"‘’"
_FIM_NR = re.compile(r"[”\"]?\s*\(\s*(?:N\.?\s?R\.?|AC)\s*\)\s*[.;]?\s*$", re.I)
_FIM_ASPAS = re.compile(r"[”\"]\s*[.;]?\s*$")
_PASSA_A_VIGORAR = re.compile(r"passa(?:m)?\s+a\s+vigorar|fica(?:m)?\s+acrescid", re.I)
_NA_FORMA_DO_ANEXO = re.compile(r"passa(?:m)?\s+a\s+vigorar\s+na\s+forma\s+d[oa]", re.I)
_REVOGA = re.compile(r"\bfica(?:m)?\s+revogad|\brevoga(?:m)?-se\b", re.I)
_ANEXO_ALVO = re.compile(r"\bAnexo\s+(Normativo\s+)?([IVXLC]+|[A-Z])\b", re.I)
_DA_RESOLUCAO = re.compile(r"\bd[ao]\s+Resolu[çc][ãa]o\b", re.I)
_ROMANOS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def _romano(texto: str) -> int:
    total, maior = 0, 0
    for c in reversed(texto.upper()):
        v = _ROMANOS.get(c, 0)
        if v < maior:
            total -= v
        else:
            total, maior = total + v, v
    return total


def mencao(numero: str) -> re.Pattern:
    """"Resolução CVM nº 60" (sem casar "Resolução CVM nº 600" nem "60/22" de outra espécie)."""
    return re.compile(rf"Resolu[çc][ãa]o\s+(?:CVM\s+)?(?:n[º°o.]*\s*)?0*{int(numero)}(?!\d)", re.I)


def data_extenso(iso: str | None) -> str:
    if not iso:
        return "data não verificada"
    a, m, d = (int(x) for x in iso[:10].split("-"))
    mes = next(k for k, v in _MESES.items() if v == m and k != "marco")
    return f"{'1º' if d == 1 else d} de {mes} de {a}"


@dataclass
class Item:
    tipo: str
    artigo: str | None
    rotulo: str
    texto: str
    parte: str | None
    md: str


@dataclass
class Registro:
    ato_id: str
    comando: str
    operacao: str  # redacao | acrescimo | revogacao | parte
    alvo: str | None
    status: str  # aplicada | sem alteração | alvo não localizado | não reconhecido | vigência futura
    vigencia: str | None = None
    detalhe: str = ""


@dataclass
class Ato:
    """Norma alteradora: identificação, data e dispositivos da redação original."""

    documento_id: str
    numero: str
    data_edicao: str | None
    vigencia: str | None  # início de vigência (AAAA-MM-DD), quando há evidência
    dispositivos: list = field(default_factory=list)


@dataclass
class Comando:
    trecho: str
    operacao: str  # redacao | revogacao | parte
    parte: str | None
    contexto: list[str]  # art./§/inciso citados no próprio comando, como linhas inalteradas
    linhas: list[str]  # texto citado sem as aspas, ou os dispositivos revogados


# ---------------------------------------------------------------------- rótulos e endereços
def _comp_parte(nome: str) -> str:
    return re.sub(r"\s+", " ", nome.lower().replace("normativo", "")).strip()


def _chave_filho(componente: str) -> tuple:
    """Ordem entre irmãos: incisos do caput antes dos parágrafos; números e letras em ordem."""
    def num(t: str) -> tuple[int, str]:
        base, _, suf = t.replace("º", "").strip().partition("-")
        return (int(base) if base.isdigit() else 0, suf)
    if componente.startswith("art. "):
        return (0, *num(componente[5:]))
    if componente.startswith("inciso "):
        base, _, suf = componente[7:].partition("-")
        return (0, _romano(base), suf)
    if componente == "parágrafo único":
        return (1, 1, "")
    if componente.startswith("§ "):
        return (1, *num(componente[2:]))
    if componente.startswith("alínea "):
        return (0, ord(componente[-1]), "")
    if componente.startswith("item "):
        return (0, *num(componente[5:]))
    return (9, 0, componente)


def rotulo(parte: str | None, art: str | None = None, par: str | None = None, inc: str | None = None,
           ali: str | None = None) -> str:
    comps = [parte, f"art. {_ordinal(art)}" if art else None, par, f"inciso {inc}" if inc else None,
             f"alínea {ali}" if ali else None]
    return ", ".join(c for c in comps if c)


_ENDERECO = re.compile(
    r"(?:al[ií]nea\s+[“\"]?(?P<ali>[a-z])[”\"]?\s*,?\s*(?:d[oa]\s+)?)?"
    r"(?:inciso\s+(?P<inc>[IVXLC]+(?:-[A-Z])?)\s*,?\s*(?:d[oa]\s+)?)?"
    r"(?:(?:§\s*(?P<par>\d+)\s*[º°o]?(?:-(?P<parsuf>[A-Z]))?|(?P<unico>par[áa]grafo\s+[úu]nico))\s*,?\s*"
    r"(?:d[oa]\s+)?)?"
    r"(?:art(?:igo)?s?\.?\s*(?P<art>\d+)\s*[º°o]?(?:\s*-\s*(?P<artsuf>[A-Z])\b)?)",
    re.I)


def enderecos(texto: str, parte: str | None) -> list[str]:
    """Rótulos dos dispositivos citados ("o inciso III do art. 31", "a alínea "b" do inciso IV do art. 25")."""
    saida = []
    for m in _ENDERECO.finditer(texto):
        art = m.group("art") + (f"-{m.group('artsuf').upper()}" if m.group("artsuf") else "")
        par = None
        if m.group("unico"):
            par = "parágrafo único"
        elif m.group("par"):
            par = "§ " + _ordinal(m.group("par") + (f"-{m.group('parsuf').upper()}" if m.group("parsuf") else ""))
        saida.append(rotulo(parte, art, par, m.group("inc").upper() if m.group("inc") else None, m.group("ali")))
    return saida


def sem_rotulo(texto: str) -> str:
    """Texto do dispositivo da alteradora sem o seu próprio rótulo ("Art. 4º Fica revogado..." -> "Fica...")."""
    for rx in (_ARTIGO, _PARAGRAFO, _PARAGRAFO_UNICO, _INCISO, _ALINEA):
        if m := rx.match(texto):
            return texto[m.end():].lstrip(" .–—-")
    return texto


def _antes_da_norma(texto: str) -> str:
    m = _DA_RESOLUCAO.search(texto)
    return texto[:m.start()] if m else texto


class Texto:
    """Itens de uma versão de texto, com as operações de alteração."""

    def __init__(self, itens: list[Item]):
        self.itens = itens

    @classmethod
    def de_versao(cls, blocos: list[str], dispositivos: list) -> Texto:
        if len(blocos) != len(dispositivos):
            raise ValueError(f"o Markdown tem {len(blocos)} blocos e a versão tem {len(dispositivos)} dispositivos")
        return cls([Item(d["tipo"], d["artigo"], d["rotulo"], d["texto"], d["parte"], b)
                    for b, d in zip(blocos, dispositivos)])

    def parte_citada(self, texto: str, padrao: str | None = None) -> str | None:
        """Parte citada no comando ("o Anexo II da Resolução..." -> "Anexo Normativo II")."""
        m = _ANEXO_ALVO.search(texto)
        if not m:
            return padrao
        alvo = _comp_parte(f"Anexo {m.group(2)}")
        partes = dict.fromkeys(i.parte for i in self.itens if i.parte)
        return next((p for p in partes if _comp_parte(p) == alvo), f"Anexo {m.group(2).upper()}")

    def fim_continuacao(self, i: int) -> int:
        """Depois do item i e da sua continuação: no texto vindo de PDF, o parágrafo que passa de página pode
        ficar dividido, e o resto vira um bloco "texto" sem rótulo (o item i não termina em . ; ou :)."""
        j = i + 1
        while (j < len(self.itens) and self.itens[j].tipo == "texto"
               and not re.search(r"[.;:]\W*$", self.itens[j - 1].texto)):
            j += 1
        return j

    def texto_completo(self, i: int) -> str:
        return " ".join(it.texto for it in self.itens[i:self.fim_continuacao(i)])

    def indice(self, rot: str) -> int | None:
        return next((i for i, it in enumerate(self.itens) if it.tipo in ESTRUTURAIS and it.rotulo == rot), None)

    def fim_subarvore(self, i: int) -> int:
        """Índice logo depois do item i, dos seus subdispositivos e das notas que o acompanham."""
        prefixo = self.itens[i].rotulo + ","
        j = i + 1
        while j < len(self.itens):
            it = self.itens[j]
            if it.tipo == "cabecalho" or not (
                    it.tipo in ("nota_alteracao", "redacao_anterior", "texto_alterado", "tabela")
                    or it.rotulo.startswith(prefixo)):
                break
            j += 1
        return j

    def posicao_de_insercao(self, rot: str, parte: str | None) -> int | None:
        """Onde incluir um dispositivo novo: depois do irmão anterior e dos seus subdispositivos; sem irmão
        anterior, logo depois do dispositivo superior."""
        pai, _, proprio = rot.rpartition(", ")
        if pai == (parte or ""):
            pai = ""
        ip = None
        if pai:
            ip = self.indice(pai)
            if ip is None:
                return None
        chave = _chave_filho(proprio)
        anterior = None
        for i, it in enumerate(self.itens):
            if it.tipo not in ESTRUTURAIS or it.parte != parte:
                continue
            p, _, c = it.rotulo.rpartition(", ")
            if p == (parte or ""):
                p = ""
            if p == pai and _chave_filho(c) < chave:
                anterior = i
        if anterior is not None:
            return self.fim_subarvore(anterior)
        if ip is not None:
            j = ip + 1
            while j < len(self.itens) and self.itens[j].tipo in ("nota_alteracao", "redacao_anterior"):
                j += 1
            return j
        return None

    def riscar(self, i: int) -> None:
        it = self.itens[i]
        if it.tipo == "redacao_anterior":
            return
        if it.md.startswith("<table>"):
            md = re.sub(r"<td>(.*?)</td>",
                        lambda m: f"<td><s>{re.sub(r'</?s>', '', m.group(1))}</s></td>" if m.group(1).strip()
                        else "<td></td>", it.md, flags=re.S)
        else:
            md = "~~" + it.md.replace("~~", "") + "~~"
        self.itens[i] = Item("redacao_anterior", it.artigo, f"{it.rotulo} (redação anterior)", it.texto, it.parte, md)


def _nome_dispositivo(rot: str, tipo: str) -> tuple[str, str]:
    """Nome e gênero do dispositivo para a nota: ('Inciso II', 'o'), ('Alínea b', 'a')."""
    ultimo = rot.rpartition(", ")[2]
    if tipo == "cabecalho":
        primeira = re.split(r"\s+[–—-]\s+", ultimo)[0].strip()
        return primeira, ("a" if re.match(r"(sub)?se[cç][aã]o", primeira, re.I) else "o")
    if ultimo.startswith("art. "):
        return "Art. " + ultimo[5:], "o"
    if ultimo == "parágrafo único":
        return "Parágrafo único", "o"
    if ultimo.startswith("alínea "):
        return "Alínea " + ultimo[7:], "a"
    return ultimo[:1].upper() + ultimo[1:], "o"


def nota(ato: Ato, rot: str, tipo: str, verbo: str, parte: str | None, futura: bool) -> Item:
    nome, g = _nome_dispositivo(rot, tipo)
    verbos = {"redacao": "com redação dada", "inclusao": f"incluíd{g}", "revogacao": f"revogad{g}"}
    texto = (f"• {nome} {verbos[verbo]} pela Resolução CVM nº {ato.numero}, de {data_extenso(ato.data_edicao)}"
             + (f", em vigor a partir de {data_extenso(ato.vigencia)}" if futura else "")
             + " (alteração aplicada automaticamente).")
    art = re.search(r"art\. ([\dA-Z-]+)", rot.replace("º", ""))
    return Item("nota_alteracao", art.group(1) if art else None, f"{rot}, nota de alteração", texto, parte,
                f"*{texto}*")


# ---------------------------------------------------------------------- leitura dos comandos
def _linha_citada(texto: str) -> str:
    texto = texto.strip()
    texto = _FIM_NR.sub("", texto)
    texto = _FIM_ASPAS.sub("", texto)
    return texto.strip().lstrip(_ASPAS).strip()


def _contexto(antes: str) -> list[str]:
    """'O inciso IV do art. 25' -> linhas inalteradas 'Art. 25 ......' e 'IV – ......' (localizam o texto citado)."""
    rots = enderecos(antes, None)
    if not rots:
        return []
    linhas = []
    for c in rots[0].split(", "):
        if c.startswith("art. "):
            linhas.append(f"Art. {c[5:]} ......")
        elif c == "parágrafo único":
            linhas.append("Parágrafo único. ......")
        elif c.startswith("§"):
            linhas.append(f"{c} ......")
        elif c.startswith("inciso "):
            linhas.append(f"{c[7:]} – ......")
        elif c.startswith("alínea "):
            linhas.append(f"{c[7:]}) ......")
    return linhas


def comandos(ato: Ato, numero_alvo: str, texto: Texto) -> list[Comando]:
    """Comandos da alteradora dirigidos à norma `numero_alvo`, com o texto citado de cada um."""
    alvo = mencao(numero_alvo)
    saida: list[Comando] = []
    atual: Comando | None = None
    for d in ato.dispositivos:
        t = d["texto"]
        if d["tipo"] == "texto_alterado":
            if atual is not None and atual.operacao == "redacao":
                atual.linhas.append(_linha_citada(t))
            continue
        # Lista de revogados em incisos ("Ficam revogados: I – o inciso III do art. 31 da Resolução...").
        if atual is not None and atual.operacao == "revogacao" and d["tipo"] in ("inciso", "alinea"):
            if alvo.search(t) or not mencao_de_outra(t, numero_alvo):
                atual.linhas.append(sem_rotulo(t))
            continue
        atual = None
        if d["tipo"] not in ESTRUTURAIS or not alvo.search(t):
            continue
        t = sem_rotulo(t)
        antes = alvo.split(t, 1)[0]
        parte = texto.parte_citada(antes)
        if _REVOGA.search(t):
            atual = Comando(d["texto"], "revogacao", parte, [], [t])
        elif _NA_FORMA_DO_ANEXO.search(t):
            atual = Comando(d["texto"], "parte", parte, [], [])
        elif _PASSA_A_VIGORAR.search(t):
            atual = Comando(d["texto"], "redacao", parte, _contexto(_antes_da_norma(antes)), [])
        else:
            continue
        saida.append(atual)
    return saida


def mencao_de_outra(texto: str, numero_alvo: str) -> bool:
    return any(int(n) != int(numero_alvo) for n in re.findall(r"Resolu[çc][ãa]o\s+(?:CVM\s+)?(?:n[º°o.]*\s*)?(\d+)",
                                                             texto, re.I))


# ---------------------------------------------------------------------- aplicação
def _placeholder(texto: str) -> bool:
    for rx in (_ARTIGO, _PARAGRAFO, _PARAGRAFO_UNICO, _INCISO, _ALINEA, _ITEM):
        if m := rx.match(texto):
            return bool(_SO_PONTOS.match(texto[m.end():]))
    return bool(_SO_PONTOS.match(texto))


def _iguais(a: str, b: str) -> bool:
    return [p.lower() for p in palavras(a)] == [p.lower() for p in palavras(b)]


def _revogar(texto: Texto, ato: Ato, cmd: Comando, futura: bool) -> list[Registro]:
    alvos = []
    for linha in cmd.linhas:
        if linha is cmd.linhas[0] and not _ENDERECO.search(_antes_da_norma(linha).split(":")[-1]) and len(cmd.linhas) > 1:
            continue  # "Ficam revogados:" seguido da lista
        base = _antes_da_norma(linha)
        alvos += enderecos(base, texto.parte_citada(base, cmd.parte))
    if not alvos:
        return [Registro(ato.documento_id, cmd.trecho, "revogacao", None, "não reconhecido", ato.vigencia,
                         "dispositivos revogados não identificados no comando")]
    registros = []
    for alvo in dict.fromkeys(alvos):
        i = texto.indice(alvo)
        if i is None:
            registros.append(Registro(ato.documento_id, cmd.trecho, "revogacao", alvo, "alvo não localizado",
                                      ato.vigencia))
            continue
        tipo, parte = texto.itens[i].tipo, texto.itens[i].parte
        fim = texto.fim_subarvore(i)
        for k in range(i, fim):
            if texto.itens[k].tipo not in ("nota_alteracao", "redacao_anterior", "nota"):
                texto.riscar(k)
        texto.itens.insert(fim, nota(ato, alvo, tipo, "revogacao", parte, futura))
        registros.append(Registro(ato.documento_id, cmd.trecho, "revogacao", alvo, "aplicada", ato.vigencia))
    return registros


def aplicar(texto: Texto, ato: Ato, cmd: Comando, futura: bool) -> list[Registro]:
    vig = ato.vigencia
    if cmd.operacao == "parte":
        return [Registro(ato.documento_id, cmd.trecho, "parte", cmd.parte, "não reconhecido", vig,
                         "substituição de anexo inteiro ainda não é aplicada automaticamente")]
    if cmd.operacao == "revogacao":
        return _revogar(texto, ato, cmd, futura)

    linhas = [l for l in cmd.contexto + cmd.linhas if l]
    if not any(cmd.linhas):
        return [Registro(ato.documento_id, cmd.trecho, "redacao", None, "não reconhecido", vig,
                         "comando sem texto citado")]
    if not (_ARTIGO.match(linhas[0]) or _CABECALHO.match(linhas[0])):
        return [Registro(ato.documento_id, cmd.trecho, "redacao", None, "não reconhecido", vig,
                         f"texto citado sem artigo de referência: {linhas[0][:80]}")]
    c = estruturar([Bloco(l) for l in linhas], " ".join(linhas), estilo_citacao=False)
    blocos = c.markdown.rstrip("\n").split("\n\n")
    registros: list[Registro] = []
    titulos: list[Item] = []
    incluidos: set[str] = set()  # subdispositivo de dispositivo incluído no mesmo comando não leva nota própria
    for d, bloco in zip(c.dispositivos, blocos):
        if _SO_PONTOS.match(d.texto) or d.tipo in ("nota", "nota_alteracao", "sumario"):
            continue
        parte = d.parte or cmd.parte
        if d.tipo == "cabecalho":
            titulos.append(Item("cabecalho", d.artigo, d.texto[:120], d.texto, parte, bloco))
            continue
        if d.tipo not in ESTRUTURAIS:
            registros.append(Registro(ato.documento_id, cmd.trecho, "redacao", d.rotulo, "não reconhecido", vig,
                                      f"trecho citado sem rótulo de dispositivo: {d.texto[:80]}"))
            continue
        rot = f"{parte}, {d.rotulo}" if parte and not d.rotulo.startswith(parte) else d.rotulo
        i = texto.indice(rot)
        if _placeholder(d.texto):
            if i is None:
                registros.append(Registro(ato.documento_id, cmd.trecho, "redacao", rot, "alvo não localizado", vig,
                                          "dispositivo citado como inalterado não existe no texto"))
            continue
        novo = Item(d.tipo, d.artigo, rot, d.texto, parte, bloco)
        if i is not None:
            if _iguais(texto.texto_completo(i), d.texto):
                registros.append(Registro(ato.documento_id, cmd.trecho, "redacao", rot, "sem alteração", vig))
                continue
            for k in range(i, texto.fim_continuacao(i)):
                texto.riscar(k)
            fim = i + 1
            while fim < len(texto.itens) and texto.itens[fim].tipo == "redacao_anterior":
                fim += 1
            texto.itens[fim:fim] = [novo, nota(ato, rot, d.tipo, "redacao", parte, futura)]
            registros.append(Registro(ato.documento_id, cmd.trecho, "redacao", rot, "aplicada", vig))
            titulos = []
            continue
        pos = texto.posicao_de_insercao(rot, parte)
        if pos is None:
            registros.append(Registro(ato.documento_id, cmd.trecho, "acrescimo", rot, "alvo não localizado", vig,
                                      "dispositivo superior não localizado"))
            continue
        novos: list[Item] = []
        for t in titulos:
            novos += [t, nota(ato, t.rotulo, "cabecalho", "inclusao", parte, futura)]
            registros.append(Registro(ato.documento_id, cmd.trecho, "acrescimo", t.texto[:80], "aplicada", vig))
        titulos = []
        pai = rot.rpartition(", ")[0]
        novos.append(novo)
        if pai not in incluidos:
            novos.append(nota(ato, rot, d.tipo, "inclusao", parte, futura))
        incluidos.add(rot)
        texto.itens[pos:pos] = novos
        registros.append(Registro(ato.documento_id, cmd.trecho, "acrescimo", rot, "aplicada", vig))
    for t in titulos:
        registros.append(Registro(ato.documento_id, cmd.trecho, "acrescimo", t.texto[:80], "não reconhecido", vig,
                                  "título citado sem dispositivo seguinte"))
    return registros


def consolidar_texto(texto: Texto, atos: list[Ato], numero_alvo: str, hoje: date,
                     incluir_futuras: bool) -> list[Registro]:
    """Aplica, em ordem cronológica, os comandos das alteradoras. Devolve o registro de cada operação."""
    registros: list[Registro] = []
    for ato in sorted(atos, key=lambda a: (a.data_edicao or "", int(a.numero))):
        futura = bool(ato.vigencia and ato.vigencia > hoje.isoformat())
        cmds = comandos(ato, numero_alvo, texto)
        if not cmds:
            registros.append(Registro(ato.documento_id, "", "redacao", None, "não reconhecido", ato.vigencia,
                                      "nenhum comando dirigido a esta norma foi reconhecido no texto da alteradora"))
            continue
        for cmd in cmds:
            if futura and not incluir_futuras:
                registros.append(Registro(ato.documento_id, cmd.trecho, cmd.operacao, cmd.parte, "vigência futura",
                                          ato.vigencia, "não incluída no texto vigente"))
                continue
            registros += aplicar(texto, ato, cmd, futura)
    return registros
