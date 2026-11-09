"""Versão consolidada (só o texto vigente) das normas alteradas (D-21).

Os consolidados oficiais da CVM em DOCX mantêm a redação substituída tachada, seguida da redação vigente e de
uma nota ("Alínea b com redação dada pela Resolução CVM nº 194..."). A versão consolidada é derivada do
consolidado oficial já convertido, sem reconversão:

- os blocos de redação anterior (parágrafo ou tabela inteiramente tachados) saem;
- os trechos tachados de parágrafos (`~~ ~~`) e de tabelas (`<s></s>`) saem; a linha de tabela que fica vazia sai;
- as notas de alteração e as notas de rodapé ficam (só sai a definição de nota cuja chamada estava no tachado).

Cada bloco do Markdown do conversor é um dispositivo, na mesma ordem (`acervo.markdown_parte` depende disso),
então os dispositivos da versão nova são os do consolidado oficial, sem os de redação anterior. A conferência
exige que as palavras do Markdown novo sejam exatamente as dos dispositivos mantidos.

Só o DOCX traz a marcação de tachado (D-13): consolidado oficial convertido de PDF não é derivado.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from repositorio_cvm import acervo, alteracoes
from repositorio_cvm import motor_alteracoes as motor
from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.conversao.fidelidade import palavras, texto_do_markdown

CONVERSOR_LIMPO = "consolidacao-limpa/1"
_TACHADO_MD = re.compile(r"~~(.+?)~~", re.S)
_TACHADO_HTML = re.compile(r"<s>.*?</s>", re.S)
_LINHA = re.compile(r"<tr>(.*?)</tr>\n?", re.S)
_CELULA = re.compile(r"<td>(.*?)</td>", re.S)
_NOTA_CHAMADA = re.compile(r"\[\^([^\]\s]+)\](?!:)")
_NOTA_DEFINICAO = re.compile(r"^\[\^([^\]\s]+)\]:")


class ConsolidacaoError(RuntimeError):
    pass


@dataclass
class Resultado:
    documento_id: str
    status: str  # gerada | já existia | sem consolidado em DOCX | reprovada
    versao_id: int | None = None
    removidos: int = 0  # blocos de redação anterior retirados
    trechos: int = 0  # trechos tachados retirados de parágrafos e tabelas
    detalhe: str = ""
    avisos: list[str] = field(default_factory=list)
    aplicadas: int | None = None  # consolidação gerada: alterações aplicadas


def limpar_bloco(bloco: str) -> tuple[str, int]:
    """Bloco do Markdown sem os trechos tachados. Devolve (bloco, trechos retirados)."""
    trechos = len(_TACHADO_MD.findall(bloco)) + len(_TACHADO_HTML.findall(bloco))
    if not trechos:
        return bloco, 0
    if bloco.startswith("<table>"):
        bloco = _TACHADO_HTML.sub("", bloco)

        def linha(m: re.Match) -> str:
            celulas = [re.sub(r"\s+", " ", c).strip() for c in _CELULA.findall(m.group(1))]
            if not any(celulas):
                return ""
            return "<tr>" + "".join(f"<td>{c}</td>" for c in celulas) + "</tr>\n"

        bloco = _LINHA.sub(linha, bloco)
        return bloco.replace("<table>\n</table>", ""), trechos
    bloco = _TACHADO_MD.sub("", bloco)
    # Espaços que sobram onde estava o trecho riscado; o rótulo em negrito ("**Art. 5º** ") é mantido.
    bloco = re.sub(r"[ \t]{2,}", " ", bloco).strip()
    return bloco, trechos


def derivar_texto_vigente(blocos: list[str], dispositivos: list[sqlite3.Row]) -> tuple[list[str], list[sqlite3.Row], int, int]:
    """(blocos, dispositivos mantidos, blocos removidos, trechos retirados)."""
    if len(blocos) != len(dispositivos):
        raise ConsolidacaoError(f"o Markdown tem {len(blocos)} blocos e a versão tem {len(dispositivos)} dispositivos; "
                                "não é possível derivar o texto vigente com segurança")
    saida_blocos, saida_disp, removidos, trechos = [], [], 0, 0
    for bloco, disp in zip(blocos, dispositivos):
        if disp["tipo"] == "redacao_anterior":
            removidos += 1
            continue
        limpo, n = limpar_bloco(bloco)
        trechos += n
        if not limpo.strip():
            removidos += 1
            continue
        saida_blocos.append(limpo)
        saida_disp.append(disp)
    # Notas de rodapé cuja chamada estava só na redação anterior (nota sem chamada no original fica).
    chamadas_antes = {c for b in blocos for c in _NOTA_CHAMADA.findall(b)}
    chamadas = {c for b in saida_blocos for c in _NOTA_CHAMADA.findall(b)}
    manter = [i for i, b in enumerate(saida_blocos)
              if not ((m := _NOTA_DEFINICAO.match(b)) and m.group(1) in chamadas_antes - chamadas)]
    removidos += len(saida_blocos) - len(manter)
    return [saida_blocos[i] for i in manter], [saida_disp[i] for i in manter], removidos, trechos


def conferir(blocos: list[str], dispositivos: list[sqlite3.Row], markdown_base: str) -> str | None:
    """Erro de conferência ou None. As palavras do Markdown novo devem ser exatamente as dos dispositivos
    mantidos (texto vigente) e estar todas no Markdown de origem."""
    novo = palavras(texto_do_markdown("\n\n".join(blocos)))
    esperado = palavras(" ".join(d["texto"] for d in dispositivos))
    if novo != esperado:
        import difflib
        for op, a1, a2, b1, b2 in difflib.SequenceMatcher(a=esperado, b=novo, autojunk=False).get_opcodes():
            if op != "equal":
                return (f"palavras divergentes dos dispositivos vigentes: {op} esperado[{' '.join(esperado[a1:a2][:8])}] "
                        f"markdown[{' '.join(novo[b1:b2][:8])}]")
    sobra = Counter(novo) - Counter(palavras(texto_do_markdown(markdown_base)))
    if sobra:
        return f"palavras que não estão no texto de origem: {', '.join(list(sobra)[:8])}"
    return None


def gravar_versao(conexao: sqlite3.Connection, pasta_dados: Path, base: sqlite3.Row, tipo: str, conversor: str,
                  blocos: list[str], dispositivos: list[dict], qualidade: str, ok: bool, detalhe: dict,
                  cabecalho: dict, nome_arquivo: str) -> int:
    """Grava o Markdown, a versão de texto (ligada à versão de origem) e os dispositivos com o índice FTS."""
    relativo = Path("convertidos") / base["documento_id"] / nome_arquivo
    destino = pasta_dados / relativo
    destino.parent.mkdir(parents=True, exist_ok=True)
    frente = "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in cabecalho.items()) + "---\n\n"
    destino.write_text(frente + "\n\n".join(blocos) + "\n", encoding="utf-8")
    cur = conexao.execute(
        """INSERT INTO versao_texto (documento_id, arquivo_id, tipo, caminho_md, conversor, fidelidade_ok,
                                     fidelidade_detalhe, qualidade, gerado_em, base_versao_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (base["documento_id"], base["arquivo_id"], tipo, relativo.as_posix(), conversor, int(ok),
         json.dumps(detalhe, ensure_ascii=False), qualidade, agora(), base["id"]))
    versao_id = cur.lastrowid
    conexao.executemany(
        "INSERT INTO dispositivo (versao_id, documento_id, ordem, tipo, artigo, rotulo, texto, parte) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(versao_id, base["documento_id"], i, d["tipo"], d["artigo"], d["rotulo"], d["texto"], d["parte"])
         for i, d in enumerate(dispositivos, 1)])
    conexao.execute("INSERT INTO dispositivo_fts (rowid, texto, rotulo) SELECT id, texto, rotulo FROM dispositivo "
                    "WHERE versao_id = ?", (versao_id,))
    return versao_id


def _base_oficial(conexao: sqlite3.Connection, documento_id: str) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT v.*, a.url AS url_fonte, a.sha256, a.coletado_em, a.formato FROM versao_texto v "
        "JOIN arquivo a ON a.id = v.arquivo_id WHERE v.documento_id = ? AND v.tipo = ? AND v.fidelidade_ok = 1 "
        "ORDER BY v.id DESC LIMIT 1", (documento_id, acervo.TIPO_OFICIAL)).fetchone()


def consolidar_oficial(conexao: sqlite3.Connection, pasta_dados: Path, documento_id: str) -> Resultado:
    """Deriva a versão consolidada (texto vigente) do consolidado oficial em DOCX. Idempotente."""
    base = _base_oficial(conexao, documento_id)
    if base is None:
        return Resultado(documento_id, "sem consolidado oficial")
    if not base["conversor"].startswith("docx"):
        return Resultado(documento_id, "sem consolidado em DOCX",
                         detalhe=f"o consolidado oficial foi convertido de {base['formato'].upper()}, que não marca "
                                 "a redação tachada")
    conversor = f"{CONVERSOR_LIMPO} sobre {base['conversor']}"
    existente = conexao.execute("SELECT id, fidelidade_ok FROM versao_texto WHERE arquivo_id = ? AND conversor = ?",
                                (base["arquivo_id"], conversor)).fetchone()
    if existente:
        return Resultado(documento_id, "já existia", existente["id"])
    markdown_base = acervo.corpo_markdown(pasta_dados, base["caminho_md"])
    blocos = markdown_base.rstrip("\n").split("\n\n")
    disp = conexao.execute("SELECT * FROM dispositivo WHERE versao_id = ? ORDER BY ordem", (base["id"],)).fetchall()
    blocos_novos, disp_novos, removidos, trechos = derivar_texto_vigente(blocos, disp)
    erro = conferir(blocos_novos, disp_novos, markdown_base)
    ok = erro is None
    avisos_base = base["qualidade"].split("; avisos: ", 1)[1].split("; ") if "; avisos: " in base["qualidade"] else []
    avisos = [a for a in avisos_base if "tachad" not in a]
    if ok:
        qualidade = (f"alta: derivada do consolidado oficial da CVM (DOCX), com a redação tachada retirada "
                     f"({removidos} bloco(s) de redação anterior e {trechos} trecho(s) tachado(s)); notas de "
                     "alteração mantidas")
    else:
        qualidade = f"reprovada: {erro}"
    if avisos:
        qualidade += "; avisos: " + "; ".join(avisos)
    doc = conexao.execute("SELECT titulo, url_oficial FROM documento WHERE id = ?", (documento_id,)).fetchone()
    cabecalho = {
        "id": documento_id,
        "titulo": doc["titulo"] if doc else None,
        "versao_texto": acervo.TIPO_VIGENTE,
        "derivada_de": f"{acervo.TIPO_OFICIAL} ({base['caminho_md']})",
        "url_ficha": doc["url_oficial"] if doc else None,
        "url_fonte": base["url_fonte"],
        "sha256_fonte": base["sha256"],
        "coletado_em": base["coletado_em"],
        "conversor": conversor,
        "fidelidade": "aprovada" if ok else qualidade,
        "aviso": ("Texto vigente derivado automaticamente do consolidado oficial da CVM, sem a redação anterior "
                  "tachada. Em caso de divergência, prevalece o original."),
    }
    versao_id = gravar_versao(
        conexao, pasta_dados, base, acervo.TIPO_VIGENTE, conversor, blocos_novos, [dict(d) for d in disp_novos],
        qualidade, ok, {"blocos_removidos": removidos, "trechos_tachados": trechos, "erro": erro}, cabecalho,
        f"consolidado-vigente-{base['sha256'][:16]}-v{base['id']}.md")
    conexao.commit()
    return Resultado(documento_id, "gerada" if ok else "reprovada", versao_id, removidos, trechos, erro or "")


def consolidar(conexao: sqlite3.Connection, pasta_dados: Path, documentos: list[str] | None = None,
               hoje: date | None = None) -> list[Resultado]:
    """Para cada norma alterada: deriva a consolidada do consolidado oficial em DOCX e, quando há alterações que
    ele não incorpora (ou não há consolidado em DOCX), gera a consolidação pela aplicação das alterações."""
    hoje = hoje or date.today()
    com_alteradoras = {d for a in alteracoes.alteradoras(conexao) for d in a.alteradas}
    if documentos is None:
        oficiais = {r[0] for r in conexao.execute(
            "SELECT DISTINCT documento_id FROM versao_texto WHERE tipo = ? AND fidelidade_ok = 1",
            (acervo.TIPO_OFICIAL,))}
        documentos = sorted(oficiais | com_alteradoras)
    resultados = []
    for d in documentos:
        resultados.append(consolidar_oficial(conexao, pasta_dados, d))
        if d in com_alteradoras:
            resultados.append(gerar(conexao, pasta_dados, d, hoje))
    return resultados


# ====================================================================== consolidação gerada (etapas 2 e 3)
_CITACAO_NOTA = re.compile(r"Resolu[çc][ãa]o\s+(?:CVM\s+)?(?:n[º°o.]*\s*)?(\d+)", re.I)
CONVERSOR_GERADO = "consolidacao-gerada/4"
NOTA_GERADA = "(alteração aplicada automaticamente)"


def _versao(conexao: sqlite3.Connection, documento_id: str, tipo: str) -> sqlite3.Row | None:
    return conexao.execute(
        "SELECT v.*, a.url AS url_fonte, a.sha256, a.coletado_em, a.formato FROM versao_texto v "
        "JOIN arquivo a ON a.id = v.arquivo_id WHERE v.documento_id = ? AND v.tipo = ? AND v.fidelidade_ok = 1 "
        "ORDER BY v.id DESC LIMIT 1", (documento_id, tipo)).fetchone()


def _texto(conexao: sqlite3.Connection, pasta_dados: Path, versao: sqlite3.Row) -> motor.Texto:
    blocos = acervo.corpo_markdown(pasta_dados, versao["caminho_md"]).rstrip("\n").split("\n\n")
    disp = conexao.execute("SELECT * FROM dispositivo WHERE versao_id = ? ORDER BY ordem", (versao["id"],)).fetchall()
    return motor.Texto.de_versao(blocos, disp)


def ato(conexao: sqlite3.Connection, documento_id: str) -> motor.Ato | None:
    """Alteradora com a redação original aprovada (o texto dos comandos de alteração)."""
    doc = conexao.execute("SELECT * FROM documento WHERE id = ?", (documento_id,)).fetchone()
    versao = _versao(conexao, documento_id, acervo.TIPO_ORIGINAL)
    if doc is None or versao is None:
        return None
    disp = conexao.execute("SELECT * FROM dispositivo WHERE versao_id = ? ORDER BY ordem", (versao["id"],)).fetchall()
    return motor.Ato(documento_id, doc["numero"] or documento_id.rsplit("-", 1)[1], doc["data_edicao"],
                     doc["data_inicio_vigencia"], disp)


def citadas_nas_notas(conexao: sqlite3.Connection, versao_id: int) -> set[str]:
    """Números das normas citadas nas notas de alteração do consolidado oficial."""
    return {str(int(n)) for (t,) in conexao.execute(
        "SELECT texto FROM dispositivo WHERE versao_id = ? AND tipo = 'nota_alteracao'", (versao_id,))
        for n in _CITACAO_NOTA.findall(t)}


def pendentes(conexao: sqlite3.Connection, documento_id: str) -> tuple[sqlite3.Row | None, list[str], str]:
    """(versão de partida, alteradoras a aplicar, explicação).

    Com consolidado oficial em DOCX, partida é ele, e as alteradoras a aplicar são as que nenhuma nota dele
    cita e que são posteriores à última alteradora citada. Sem consolidado em DOCX, parte-se da redação
    original e aplicam-se todas as alteradoras conhecidas."""
    conhecidas = [a for a in alteracoes.alteradoras(conexao) if documento_id in a.alteradas]
    datas = {a.documento_id: (conexao.execute("SELECT data_edicao FROM documento WHERE id = ?",
                                              (a.documento_id,)).fetchone() or [None])[0] for a in conhecidas}
    oficial = _versao(conexao, documento_id, acervo.TIPO_OFICIAL)
    if oficial is not None and oficial["conversor"].startswith("docx"):
        citadas = citadas_nas_notas(conexao, oficial["id"])
        ultima = max((datas[a.documento_id] or "" for a in conhecidas if a.numero in citadas), default="")
        lista = [a.documento_id for a in conhecidas if a.numero not in citadas and (datas[a.documento_id] or "") > ultima]
        return oficial, lista, (f"consolidado oficial cita {len(citadas & {a.numero for a in conhecidas})} das "
                                f"{len(conhecidas)} alteradoras conhecidas; a última citada é de {ultima or '—'}")
    original = _versao(conexao, documento_id, acervo.TIPO_ORIGINAL)
    return original, [a.documento_id for a in conhecidas], "sem consolidado oficial em DOCX: parte-se da redação original"


def _dispositivos(texto: motor.Texto) -> list[dict]:
    return [{"tipo": i.tipo, "artigo": i.artigo, "rotulo": i.rotulo, "texto": i.texto, "parte": i.parte}
            for i in texto.itens]


def _resumo(registros: list[motor.Registro]) -> tuple[int, list[str]]:
    aplicadas = sum(1 for r in registros if r.status == "aplicada")
    problemas = [f"Res. {r.ato_id.rsplit('-', 1)[1]}: {r.status}{' ' + r.alvo if r.alvo else ''}"
                 f"{' (' + r.detalhe + ')' if r.detalhe else ''}"
                 for r in registros if r.status in ("alvo não localizado", "não reconhecido")]
    return aplicadas, problemas


def gerar(conexao: sqlite3.Connection, pasta_dados: Path, documento_id: str, hoje: date) -> Resultado:
    """Gera as versões "alterada com tachado (gerada)" e "consolidada (gerada)" quando há alterações a aplicar."""
    base, lista, explicacao = pendentes(conexao, documento_id)
    if base is None:
        return Resultado(documento_id, "sem texto de partida", detalhe=explicacao)
    if not lista:
        return Resultado(documento_id, "sem alterações pendentes", detalhe=explicacao)
    atos, faltam = [], []
    for ident in lista:
        a = ato(conexao, ident)
        (atos if a else faltam).append(a or ident)
    derivada = _versao(conexao, documento_id, acervo.TIPO_VIGENTE)
    assinatura = json.dumps({"base": base["id"], "derivada": derivada["id"] if derivada and not
                             derivada["conversor"].startswith(CONVERSOR_GERADO) else None,
                             "atos": sorted((a.documento_id, a.vigencia) for a in atos),
                             "futuras": sorted(a.documento_id for a in atos if a.vigencia and a.vigencia > hoje.isoformat()),
                             "faltam": faltam})
    marca = hashlib.sha1(assinatura.encode()).hexdigest()[:12]
    conversor = f"{CONVERSOR_GERADO} {marca}"
    existente = conexao.execute("SELECT id FROM versao_texto WHERE arquivo_id = ? AND conversor = ? AND tipo = ?",
                                (base["arquivo_id"], f"{conversor} com tachado", acervo.TIPO_ALTERADO)).fetchone()
    if existente:
        return Resultado(documento_id, "já existia", existente["id"])

    markdown_base = acervo.corpo_markdown(pasta_dados, base["caminho_md"])
    numero = documento_id.rsplit("-", 1)[1]
    com_futuras = _texto(conexao, pasta_dados, base)
    reg_alterada = motor.consolidar_texto(com_futuras, atos, numero, hoje, incluir_futuras=True)
    vigente = _texto(conexao, pasta_dados, base)
    reg_vigente = motor.consolidar_texto(vigente, atos, numero, hoje, incluir_futuras=False)

    # Conferências: a versão com tachado não perde nenhuma palavra do texto de partida; a consolidada tem
    # exatamente as palavras dos dispositivos vigentes.
    blocos_alt = [i.md for i in com_futuras.itens]
    perdidas = Counter(palavras(texto_do_markdown(markdown_base))) - Counter(palavras(texto_do_markdown("\n\n".join(blocos_alt))))
    erro_alt = f"palavras do texto de partida ausentes: {', '.join(list(perdidas)[:8])}" if perdidas else None
    blocos_vig, disp_vig, removidos, trechos = derivar_texto_vigente([i.md for i in vigente.itens], _dispositivos(vigente))
    erro_vig = conferir(blocos_vig, disp_vig, "\n\n".join(i.md for i in vigente.itens))

    aplicadas, problemas = _resumo(reg_vigente)
    futuras = sorted({r.ato_id for r in reg_vigente if r.status == "vigência futura"})
    oficial_pdf = None
    if not base["tipo"] == acervo.TIPO_OFICIAL:
        oficial_pdf = _versao(conexao, documento_id, acervo.TIPO_OFICIAL)
    cruzada = None
    if oficial_pdf is not None:
        # Res. 9: o texto gerado deve estar contido no consolidado oficial em PDF (que traz o tachado sem marcação).
        oficial_md = acervo.corpo_markdown(pasta_dados, oficial_pdf["caminho_md"])
        # As notas geradas pelo sistema ("alteração aplicada automaticamente") não existem no PDF da CVM.
        gerado = Counter(p.lower() for d in disp_vig
                         if not (d["tipo"] == "nota_alteracao" and NOTA_GERADA in d["texto"])
                         for p in palavras(d["texto"]))
        pdf = Counter(p.lower() for p in palavras(texto_do_markdown(oficial_md)))
        cruzada = round(sum((gerado & pdf).values()) / max(1, sum(gerado.values())), 5)
    nivel = "média" if not problemas and not faltam and (cruzada is None or cruzada >= 0.995) else "baixa"
    descricao = (f"{nivel}: consolidação gerada automaticamente, não oficial, a partir do "
                 f"{'consolidado oficial da CVM' if base['tipo'] == acervo.TIPO_OFICIAL else 'texto original'}; "
                 f"{aplicadas} alteração(ões) aplicada(s) de {', '.join('Res. ' + a.numero for a in atos)}")
    if cruzada is not None:
        descricao += f"; {cruzada:.2%} das palavras estão no consolidado oficial em PDF"
    avisos = [f"alteradora sem texto no acervo: {f}" for f in faltam] + problemas
    if futuras:
        avisos.append("alterações com vigência futura só na versão com tachado: "
                      + ", ".join("Res. " + f.rsplit("-", 1)[1] for f in futuras))
    doc = conexao.execute("SELECT titulo, url_oficial FROM documento WHERE id = ?", (documento_id,)).fetchone()
    detalhe = {"partida": base["id"], "explicacao": explicacao, "atos": [a.documento_id for a in atos],
               "faltam": faltam, "conferencia_pdf": cruzada}

    def cabecalho(tipo: str, ok: bool, qualidade: str) -> dict:
        return {"id": documento_id, "titulo": doc["titulo"] if doc else None, "versao_texto": tipo,
                "partida": f"{base['tipo']} ({base['caminho_md']})",
                "alteradoras": ", ".join(a.documento_id for a in atos), "url_ficha": doc["url_oficial"] if doc else None,
                "conversor": conversor, "fidelidade": "aprovada" if ok else qualidade,
                "aviso": ("Consolidação gerada automaticamente, não oficial. Confira com as normas alteradoras; "
                          "em caso de divergência, prevalecem os textos oficiais.")}

    # A versão com tachado também mostra as alterações com vigência futura.
    aplicadas_alt = sum(1 for r in reg_alterada if r.status == "aplicada")
    descricao_alt = descricao.replace(f"; {aplicadas} alteração(ões) aplicada(s)",
                                      f"; {aplicadas_alt} alteração(ões) aplicada(s)"
                                      + (f", {aplicadas_alt - aplicadas} delas com vigência futura"
                                         if aplicadas_alt > aplicadas else ""), 1)
    qual_alt = (descricao_alt if not erro_alt else f"reprovada: {erro_alt}") + ("; avisos: " + "; ".join(avisos) if avisos else "")
    id_alt = gravar_versao(conexao, pasta_dados, base, acervo.TIPO_ALTERADO, f"{conversor} com tachado", blocos_alt,
                           _dispositivos(com_futuras), qual_alt, erro_alt is None, detalhe | {"erro": erro_alt},
                           cabecalho(acervo.TIPO_ALTERADO, erro_alt is None, qual_alt),
                           f"alterado-gerado-{base['sha256'][:16]}-v{base['id']}-{marca}.md")
    _registrar(conexao, id_alt, reg_alterada)
    if aplicadas == 0 and base["tipo"] == acervo.TIPO_OFICIAL:
        # Nenhuma alteração em vigor a aplicar (ex.: só alterações com vigência futura): a consolidada continua
        # a derivada do consolidado oficial; só a versão com tachado mostra o que vem.
        conexao.commit()
        return Resultado(documento_id, "só a versão com tachado", id_alt, aplicadas=0,
                         detalhe="; ".join(avisos) or explicacao, avisos=avisos)
    base_vig = dict(base) | {"id": id_alt}
    ok_vig = erro_vig is None and erro_alt is None
    qual_vig = (descricao if ok_vig else f"reprovada: {erro_vig or erro_alt}") + ("; avisos: " + "; ".join(avisos) if avisos else "")
    id_vig = gravar_versao(conexao, pasta_dados, base_vig, acervo.TIPO_VIGENTE, conversor, blocos_vig, disp_vig,
                           qual_vig, ok_vig, detalhe | {"erro": erro_vig, "blocos_removidos": removidos},
                           cabecalho(acervo.TIPO_VIGENTE, ok_vig, qual_vig),
                           f"consolidado-gerado-{base['sha256'][:16]}-v{base['id']}-{marca}.md")
    _registrar(conexao, id_vig, reg_vigente)
    conexao.commit()
    return Resultado(documento_id, "gerada" if ok_vig else "reprovada", id_vig, removidos, aplicadas=aplicadas,
                     detalhe=("; ".join(avisos) if avisos else explicacao) if ok_vig else (erro_vig or erro_alt or ""),
                     avisos=avisos)


def _registrar(conexao: sqlite3.Connection, versao_id: int, registros: list[motor.Registro]) -> None:
    conexao.executemany(
        "INSERT INTO alteracao_aplicada (versao_id, ato_id, comando, operacao, alvo, status, vigencia, detalhe) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(versao_id, r.ato_id, r.comando, r.operacao, r.alvo, r.status, r.vigencia, r.detalhe) for r in registros])


# ---------------------------------------------------------------------- validação do motor contra a CVM
@dataclass
class Validacao:
    documento_id: str
    comparados: int = 0  # dispositivos do consolidado oficial (texto vigente)
    iguais: int = 0
    divergentes: list[tuple[str, str, str]] = field(default_factory=list)  # (rótulo, oficial, gerado)
    faltam: list[str] = field(default_factory=list)  # no oficial, não no gerado
    sobram: list[str] = field(default_factory=list)  # no gerado, não no oficial
    problemas: list[str] = field(default_factory=list)
    atos: list[str] = field(default_factory=list)
    sem_texto: list[str] = field(default_factory=list)

    @property
    def concordancia(self) -> float:
        return self.iguais / self.comparados if self.comparados else 0.0


def validar(conexao: sqlite3.Connection, pasta_dados: Path, documento_id: str) -> Validacao | None:
    """Aplica à redação original as alteradoras citadas no consolidado oficial e compara, dispositivo a
    dispositivo, com a consolidada derivada do consolidado oficial. Não grava nada."""
    oficial = _versao(conexao, documento_id, acervo.TIPO_OFICIAL)
    original = _versao(conexao, documento_id, acervo.TIPO_ORIGINAL)
    derivada = conexao.execute(
        "SELECT * FROM versao_texto WHERE documento_id = ? AND tipo = ? AND fidelidade_ok = 1 AND conversor LIKE ? "
        "ORDER BY id DESC LIMIT 1", (documento_id, acervo.TIPO_VIGENTE, CONVERSOR_LIMPO + "%")).fetchone()
    if not (oficial and original and derivada):
        return None
    v = Validacao(documento_id)
    citadas = citadas_nas_notas(conexao, oficial["id"])
    for n in sorted(citadas, key=int):
        a = ato(conexao, f"resolucao-cvm-{n}")
        if a is None:
            v.sem_texto.append(n)
        else:
            v.atos.append(a)
    texto = _texto(conexao, pasta_dados, original)
    registros = motor.consolidar_texto(texto, v.atos, documento_id.rsplit("-", 1)[1], date.max, incluir_futuras=True)
    v.problemas = _resumo(registros)[1]
    v.atos = [a.documento_id for a in v.atos]

    def mapa(t: motor.Texto) -> dict[str, str]:
        saida = {}
        for i, it in enumerate(t.itens):
            if it.tipo in motor.ESTRUTURAIS:
                saida.setdefault(it.rotulo, " ".join(p.lower() for p in palavras(t.texto_completo(i))))
        return saida

    gerado = mapa(motor.Texto([i for i in texto.itens if i.tipo != "redacao_anterior"]))
    referencia = mapa(_texto(conexao, pasta_dados, derivada))
    for rot, txt in referencia.items():
        v.comparados += 1
        if rot not in gerado:
            v.faltam.append(rot)
        elif gerado[rot] == txt:
            v.iguais += 1
        else:
            v.divergentes.append((rot, txt[:160], gerado[rot][:160]))
    v.sobram = [r for r in gerado if r not in referencia]
    return v


def relatorio_validacao(validacoes: list[Validacao], quando: str) -> str:
    """Relatório em Markdown da comparação entre a consolidação gerada e a oficial."""
    linhas = [f"# Validação do motor de consolidação ({quando})", "",
              "Para cada norma com consolidado oficial em DOCX, as alteradoras citadas nas notas do consolidado foram "
              "aplicadas à redação original e o resultado foi comparado, dispositivo a dispositivo, com o texto "
              "vigente do consolidado oficial. Divergências podem vir do motor ou da conversão da redação original "
              "(PDF), que tem a divisão em parágrafos reconstruída.", "",
              "| Norma | Alteradoras aplicadas | Sem texto | Dispositivos | Iguais | Concordância | Divergentes | "
              "Faltam | Sobram | Comandos não aplicados |",
              "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for v in validacoes:
        linhas.append(f"| {v.documento_id} | {', '.join(a.rsplit('-', 1)[1] for a in v.atos) or '—'} | "
                      f"{', '.join(v.sem_texto) or '—'} | {v.comparados} | {v.iguais} | {v.concordancia:.1%} | "
                      f"{len(v.divergentes)} | {len(v.faltam)} | {len(v.sobram)} | {len(v.problemas)} |")
    for v in validacoes:
        linhas += ["", f"## {v.documento_id}", ""]
        if v.problemas:
            linhas += ["Comandos não aplicados:", *[f"- {p}" for p in v.problemas], ""]
        if v.divergentes:
            linhas += ["Divergentes (oficial / gerado):"]
            for rot, ofi, ger in v.divergentes[:40]:
                linhas += [f"- **{rot}**", f"  - oficial: {ofi}", f"  - gerado: {ger}"]
            linhas.append("")
        if v.faltam:
            linhas += [f"Faltam no gerado: {', '.join(v.faltam[:60])}", ""]
        if v.sobram:
            linhas += [f"Sobram no gerado: {', '.join(v.sobram[:60])}", ""]
    return "\n".join(linhas) + "\n"
