"""Relatório de conferência do gabarito: tabela para a conferência manual do usuário (Fase 2)."""

from __future__ import annotations

import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from repositorio_cvm.gabarito import AtoGabarito

_FONTE = {"html-word": "HTML", "docx-ooxml": "DOCX", "pdf-pymupdf": "PDF"}
_MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
          "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def data_da_descricao(descricao: str) -> str | None:
    m = re.search(r"de\s+(\d{1,2})\s*[º°]?\s+de\s+([a-zç]+)\s+de\s+(\d{4})", descricao, re.I)
    if not m or m.group(2).lower() not in _MESES:
        return None
    return f"{int(m.group(3)):04d}-{_MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _br(data: str | None) -> str:
    return f"{data[8:10]}/{data[5:7]}/{data[0:4]}" if data and len(data) >= 10 else "—"


def _celula(texto: str | None, limite: int | None = None) -> str:
    if not texto:
        return "—"
    texto = " ".join(str(texto).split()).replace("|", "\\|")
    return texto if limite is None or len(texto) <= limite else texto[: limite - 1] + "…"


def linhas_conferencia(conexao: sqlite3.Connection, atos: list[AtoGabarito]) -> list[dict]:
    linhas = []
    for ato in atos:
        doc = conexao.execute("SELECT * FROM documento WHERE id = ?", (ato.chave,)).fetchone()
        lacuna = conexao.execute("SELECT * FROM lacuna WHERE chave = ? ORDER BY id DESC LIMIT 1", (ato.chave,)).fetchone()
        linha = {"chave": ato.chave, "descricao_usuario": ato.descricao_usuario}
        if doc is None:
            linha.update(status=lacuna["classificacao"] if lacuna else "não coletado",
                         observacoes=(lacuna["detalhe"] if lacuna else ""))
            linhas.append(linha)
            continue
        evid_sit = conexao.execute(
            "SELECT trecho FROM evidencia WHERE documento_id = ? AND campo = 'situacao' ORDER BY id DESC LIMIT 1",
            (ato.chave,)).fetchone()
        evid_vig = conexao.execute(
            "SELECT trecho FROM evidencia WHERE documento_id = ? AND campo = 'data_inicio_vigencia' ORDER BY id DESC LIMIT 1",
            (ato.chave,)).fetchone()
        relacoes = conexao.execute(
            "SELECT tipo, alvo_titulo FROM relacao WHERE documento_id = ? ORDER BY id", (ato.chave,)).fetchall()
        versao = conexao.execute(
            "SELECT id, tipo, conversor, fidelidade_ok, qualidade, caminho_md FROM versao_texto WHERE documento_id = ? "
            "AND fidelidade_ok = 1 ORDER BY (tipo = 'texto consolidado oficial') DESC, id DESC LIMIT 1",
            (ato.chave,)).fetchone()
        versoes = conexao.execute(
            "SELECT tipo, conversor, fidelidade_ok, qualidade, caminho_md FROM versao_texto WHERE documento_id = ? "
            "AND id IN (SELECT MAX(id) FROM versao_texto WHERE documento_id = ? GROUP BY tipo) ORDER BY id",
            (ato.chave, ato.chave)).fetchall()
        trecho = None
        if versao:
            art1 = conexao.execute(
                "SELECT rotulo, texto FROM dispositivo WHERE versao_id = ? AND tipo IN ('artigo', 'inciso') ORDER BY ordem LIMIT 1",
                (versao["id"],)).fetchone()
            trecho = f"{art1['rotulo']}: {art1['texto']}" if art1 else None
        arquivos = conexao.execute(
            "SELECT papel, sha256, coletado_em, origem_coleta FROM arquivo WHERE documento_id = ? ORDER BY id",
            (ato.chave,)).fetchall()
        pendentes = conexao.execute(
            "SELECT formato, papel FROM link_documento WHERE documento_id = ? AND baixado = 0", (ato.chave,)).fetchall()

        observacoes = []
        data_usuario = data_da_descricao(ato.descricao_usuario)
        if data_usuario and doc["data_edicao"] and data_usuario != doc["data_edicao"]:
            observacoes.append(f"data informada no gabarito ({_br(data_usuario)}) difere da data da ficha ({_br(doc['data_edicao'])})")
        importados = [a for a in arquivos if a["origem_coleta"] != "coleta direta"]
        if importados:
            observacoes.append(f"{len(importados)} original(is) importado(s) de coleta anterior")
        linha.update(
            status=doc["status_coleta"] + (f" ({doc['motivo_pendencia']})" if doc["motivo_pendencia"] else ""),
            titulo=doc["titulo"], url_oficial=doc["url_oficial"], data_edicao=doc["data_edicao"],
            data_publicacao=doc["data_publicacao"], data_inicio_vigencia=doc["data_inicio_vigencia"],
            vigencia_trecho=evid_vig["trecho"] if evid_vig else None,
            ementa=doc["ementa"], assunto=doc["assunto"], area_tecnica=doc["area_tecnica"],
            situacao=doc["situacao"], situacao_fundamento=evid_sit["trecho"] if evid_sit else None,
            relacoes="; ".join(f"{r['tipo']}: {r['alvo_titulo']}" for r in relacoes),
            integra=", ".join(sorted({_FONTE.get(v["conversor"].split("/")[0], v["conversor"])
                                      for v in versoes if v["fidelidade_ok"]})) or "não",
            versoes=" || ".join(f"{v['tipo']} ({_FONTE.get(v['conversor'].split('/')[0], v['conversor'])}): "
                                f"{v['qualidade']} · `{v['caminho_md']}`" for v in versoes),
            fidelidade=("aprovada" if versao else ("reprovada" if versoes else None)),
            markdown=versao["caminho_md"] if versao else None,
            trecho_verificacao=trecho,
            pendentes=", ".join(sorted({f"{p['papel']}/{p['formato']}" for p in pendentes if p["formato"]})),
            observacoes="; ".join(observacoes),
        )
        linhas.append(linha)
    return linhas


def oficio_relacoes_cruzadas(conexao: sqlite3.Connection) -> list[str]:
    """Normas que declaram alterar/revogar outra cuja ficha não registra essa relação."""
    avisos = []
    for r in conexao.execute(
        "SELECT r.documento_id, r.tipo, r.alvo_url, d.titulo FROM relacao r JOIN documento d ON d.id = r.documento_id "
        "WHERE r.tipo IN ('altera', 'revoga')"
    ):
        alvo = conexao.execute("SELECT id, titulo FROM documento WHERE url_oficial = ?", (r["alvo_url"],)).fetchone()
        if not alvo:
            continue
        inversa = "alterada_por" if r["tipo"] == "altera" else "revogada_por"
        url_origem = conexao.execute("SELECT url_oficial FROM documento WHERE id = ?", (r["documento_id"],)).fetchone()[0]
        existe = conexao.execute(
            "SELECT 1 FROM relacao WHERE documento_id = ? AND tipo = ? AND alvo_url = ?",
            (alvo["id"], inversa, url_origem)).fetchone()
        if not existe:
            avisos.append(f"A ementa da {r['titulo']} declara que {r['tipo']} a {alvo['titulo']}, mas a ficha oficial "
                          f"da {alvo['titulo']} não lista essa relação ({inversa}).")
    return avisos


def gerar_conferencia(conexao: sqlite3.Connection, atos: list[AtoGabarito], destino_md: Path, destino_csv: Path) -> None:
    linhas = linhas_conferencia(conexao, atos)
    destino_csv.parent.mkdir(parents=True, exist_ok=True)
    campos = list(dict.fromkeys(k for l in linhas for k in l))
    with destino_csv.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos, delimiter=";")
        escritor.writeheader()
        escritor.writerows(linhas)

    total = len(linhas)
    coletados = sum(1 for l in linhas if l["status"].startswith("coletado"))
    pendentes = sum(1 for l in linhas if l["status"].startswith("pendente"))
    outros = total - coletados - pendentes
    md = [
        "# Conferência do gabarito de validação (Fase 2)",
        "",
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} a partir de `dados/acervo.sqlite`. "
        "Todos os valores abaixo foram extraídos das fontes oficiais da CVM; nada foi preenchido a partir da "
        "descrição do gabarito. A situação normativa é a indicada pela ficha oficial (critério D-09) e **precisa "
        "da conferência do escritório**.",
        "",
        "Texto integral: a fonte preferida é a íntegra HTML oficial; na falta dela, o DOCX oficial, conferido "
        "palavra a palavra com o PDF oficial do mesmo texto (cobertura mínima de 99,5% nos dois sentidos); na falta "
        "de DOCX, a camada de texto do PDF (qualidade \"média\": sem segunda fonte para conferência). Quando a CVM "
        "publica texto consolidado e redação original, as duas versões são guardadas; a pesquisa usa o consolidado.",
        "",
        f"- Atos no gabarito: **{total}**",
        f"- Com texto convertido e aprovado: **{coletados}**",
        f"- Pendentes (texto ainda não convertido; motivo em cada ato): **{pendentes}**",
        f"- Não localizados ou indisponíveis: **{outros}**",
        "",
        "## Resumo",
        "",
        "| # | Ato (gabarito) | Status | Data da ficha | DOU | Situação indicada | Texto (fonte) |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, l in enumerate(linhas, 1):
        md.append(f"| {i} | {_celula(l['descricao_usuario'], 70)} | {_celula(l['status'], 60)} | "
                  f"{_br(l.get('data_edicao'))} | {_br(l.get('data_publicacao'))} | {_celula(l.get('situacao'))} | "
                  f"{_celula(l.get('integra'))} |")
    cruzadas = oficio_relacoes_cruzadas(conexao)
    if cruzadas:
        md += ["", "## Divergências entre fichas oficiais", ""] + [f"- {a}" for a in cruzadas]
    md += ["", "## Detalhe por ato", ""]
    for i, l in enumerate(linhas, 1):
        md += [f"### {i}. {l.get('titulo') or l['descricao_usuario']}", "",
               f"- **Gabarito:** {l['descricao_usuario']}",
               f"- **Status da coleta:** {l['status']}"]
        if l.get("url_oficial"):
            md += [
                f"- **URL oficial:** {l['url_oficial']}",
                f"- **Data (ficha):** {_br(l.get('data_edicao'))} · **Publicação no DOU:** {_br(l.get('data_publicacao'))}",
                f"- **Ementa:** {_celula(l.get('ementa'))}",
                f"- **Assunto (tags da ficha):** {_celula(l.get('assunto'))}",
            ]
            if l.get("area_tecnica"):
                md.append(f"- **Área técnica:** {l['area_tecnica']}")
            md += [
                f"- **Situação indicada:** {l.get('situacao')} — fundamento: {_celula(l.get('situacao_fundamento'), 300)}",
                f"- **Início de vigência:** {_br(l.get('data_inicio_vigencia'))}"
                + (f" — trecho: {_celula(l.get('vigencia_trecho'), 250)}" if l.get("vigencia_trecho") else ""),
                f"- **Relações (ficha/ementa):** {_celula(l.get('relacoes'))}",
                f"- **Texto convertido a partir de:** {l.get('integra')}",
            ]
            for v in (l.get("versoes") or "").split(" || "):
                if v:
                    md.append(f"  - {_celula(v, 420)}")
            if l.get("trecho_verificacao"):
                md.append(f"- **Trecho de verificação:** {_celula(l['trecho_verificacao'], 400)}")
            if l.get("pendentes"):
                md.append(f"- **Arquivos não baixados nesta etapa:** {l['pendentes']}")
        if l.get("observacoes"):
            md.append(f"- **Observações:** {l['observacoes']}")
        md += ["", "- [ ] Conferido pelo escritório · situação correta? ____ · observações: ____", ""]
    destino_md.parent.mkdir(parents=True, exist_ok=True)
    destino_md.write_text("\n".join(md) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------- cobertura em relação à CVM (Fase 3)
def _ultima_leitura(conexao: sqlite3.Connection, familia: str) -> dict | None:
    linha = conexao.execute("SELECT * FROM leitura_catalogo WHERE familia = ? AND terminada_em IS NOT NULL "
                            "ORDER BY id DESC LIMIT 1", (familia,)).fetchone()
    return dict(linha) if linha else None


def _intervalos(numeros: list[int]) -> str:
    """[1, 2, 3, 7, 9, 10] -> '1–3, 7, 9–10'."""
    partes: list[str] = []
    for n in numeros:
        if partes and n == fim + 1:
            fim = n
            inicio_txt = partes[-1].split("–")[0]
            partes[-1] = f"{inicio_txt}–{n}"
        else:
            partes.append(str(n))
            fim = n
    return ", ".join(partes)


def _pct(parte: int, todo: int) -> float | None:
    return round(100 * parte / todo, 1) if todo else None


def cobertura(conexao: sqlite3.Connection) -> dict:
    """Acervo em relação ao catálogo oficial da CVM (última leitura de cada família) e situação do acervo."""
    from repositorio_cvm.acervo import versoes_aprovadas
    from repositorio_cvm.coleta.catalogo import FAMILIAS
    from repositorio_cvm.coleta.inventario import NUMERADAS

    documentos = {d["url_oficial"]: d for d in conexao.execute("SELECT * FROM documento") if d["url_oficial"]}
    nivel = {}
    for d in documentos.values():
        versoes = versoes_aprovadas(conexao, d["id"])
        if versoes:
            nivel[d["id"]] = versoes[0].nivel
    familias, linhas = [], []
    for familia in FAMILIAS:
        leitura = _ultima_leitura(conexao, familia)
        itens = [dict(r) for r in conexao.execute(
            "SELECT * FROM catalogo_oficial WHERE familia = ? AND leitura_id = ?",
            (familia, leitura["id"]))] if leitura else []
        urls = {i["url"] for i in itens}
        no_acervo = [i for i in itens if i["url"] in documentos]
        com_texto = [i for i in no_acervo if documentos[i["url"]]["id"] in nivel]
        fora = [d for d in documentos.values() if d["especie"] == familia and d["url_oficial"] not in urls]
        ausentes: list[int] = []
        maior = None
        if familia in NUMERADAS and itens:
            numeros = sorted({i["numero"] for i in itens if i["numero"]})
            maior = numeros[-1] if numeros else None
            ausentes = sorted(set(range(1, maior + 1)) - set(numeros)) if maior else []
        familias.append({
            "familia": familia, "leitura": leitura, "catalogo": len(itens), "no_acervo": len(no_acervo),
            "com_texto": len(com_texto), "pct": _pct(len(no_acervo), len(itens)),
            "fora_do_catalogo": [{"id": d["id"], "titulo": d["titulo"]} for d in fora],
            "maior_numero": maior, "numeros_ausentes": _intervalos(ausentes), "qtd_numeros_ausentes": len(ausentes),
        })
        por_ano: dict[str, dict] = {}
        for i in itens:
            ano = (i["data"] or "")[:4] or "sem data"
            l = por_ano.setdefault(ano, {"familia": familia, "ano": ano, "catalogo": 0, "no_acervo": 0, "com_texto": 0})
            l["catalogo"] += 1
            if i["url"] in documentos:
                l["no_acervo"] += 1
                l["com_texto"] += documentos[i["url"]]["id"] in nivel
        for l in sorted(por_ano.values(), key=lambda l: l["ano"], reverse=True):
            l["pct"] = _pct(l["no_acervo"], l["catalogo"])
            linhas.append(l)
    lidas = [f for f in familias if f["leitura"]]
    incompletas = [f["familia"] for f in familias
                   if not f["leitura"] or f["leitura"]["status"] not in ("completa", "divergente na fonte")]
    totais = {k: sum(f[k] for f in familias) for k in ("catalogo", "no_acervo", "com_texto")}
    totais["pct"] = _pct(totais["no_acervo"], totais["catalogo"])
    if not lidas:
        aviso = ("O catálogo oficial da CVM ainda não foi lido: rode o comando ler-catalogo para comparar o acervo com a "
                 "base da CVM.")
    elif incompletas:
        aviso = ("Leitura do catálogo oficial incompleta ou ausente para: " + ", ".join(incompletas) +
                 ". Nessas espécies os números não representam a base completa da CVM.")
    else:
        aviso = None
    qualidade = {"alta": 0, "média": 0, "baixa": 0}
    for n in nivel.values():
        qualidade[n] = qualidade.get(n, 0) + 1
    lacunas = [dict(r) for r in conexao.execute(
        "SELECT l.* FROM lacuna l WHERE l.id = (SELECT MAX(id) FROM lacuna x WHERE x.chave = l.chave) "
        "AND NOT EXISTS (SELECT 1 FROM documento d WHERE d.id = l.chave AND d.status_coleta = 'coletado') "
        "ORDER BY l.chave")]
    pendentes = [dict(r) for r in conexao.execute(
        "SELECT id, titulo, motivo_pendencia FROM documento WHERE status_coleta != 'coletado' ORDER BY id")]
    coletas = [dict(r) for r in conexao.execute("SELECT * FROM coleta ORDER BY id DESC LIMIT 30")]
    tentativas = {r["resultado"]: r["n"] for r in conexao.execute(
        "SELECT resultado, COUNT(*) AS n FROM tentativa GROUP BY resultado")}
    return {"familias": familias, "linhas": linhas, "totais": totais, "aviso": aviso,
            "acervo": {"documentos": len(documentos), "com_texto": len(nivel), "qualidade": qualidade},
            "lacunas": lacunas, "pendentes": pendentes, "coletas": coletas, "tentativas": tentativas}


def faltantes(conexao: sqlite3.Connection, familia: str, ano: str | None = None) -> list[dict]:
    """Atos do catálogo oficial (última leitura) que não estão no acervo."""
    leitura = _ultima_leitura(conexao, familia)
    if leitura is None:
        return []
    conhecidas = {r[0] for r in conexao.execute("SELECT url_oficial FROM documento")}
    itens = [dict(r) for r in conexao.execute(
        "SELECT * FROM catalogo_oficial WHERE familia = ? AND leitura_id = ? ORDER BY data DESC, numero DESC",
        (familia, leitura["id"]))]
    return [i for i in itens if i["url"] not in conhecidas
            and (ano is None or ((i["data"] or "")[:4] or "sem data") == ano)]


def gerar_cobertura(conexao: sqlite3.Connection, destino_md: Path, destino_csv: Path) -> dict:
    from repositorio_cvm.acervo import ESPECIES

    dados = cobertura(conexao)
    destino_csv.parent.mkdir(parents=True, exist_ok=True)
    with destino_csv.open("w", encoding="utf-8-sig", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=["familia", "ano", "catalogo", "no_acervo", "com_texto", "pct"],
                                  delimiter=";")
        escritor.writeheader()
        escritor.writerows(dados["linhas"])
    t = dados["totais"]
    md = ["# Cobertura do acervo em relação ao catálogo oficial da CVM", "",
          f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} a partir de `dados/acervo.sqlite`. Referência: "
          "a pesquisa de legislação do portal da CVM (conteudo.cvm.gov.br), lida página a página.", ""]
    if dados["aviso"]:
        md += [f"> {dados['aviso']}", ""]
    md += [f"- Atos no catálogo oficial: **{t['catalogo']}** · no acervo: **{t['no_acervo']}** "
           f"({t['pct'] if t['pct'] is not None else '—'}%) · com texto integral aprovado: **{t['com_texto']}**", "",
           "## Por espécie", "",
           "| Espécie | Leitura do catálogo | No catálogo | No acervo | % | Com texto | Números ausentes do catálogo |",
           "|---|---|---|---|---|---|---|"]
    for f in dados["familias"]:
        l = f["leitura"]
        leitura = (f"{l['status']} em {_br(l['terminada_em'])} ({l['total_lido']} de {l['total_informado']} informados)"
                   + (f"; {l['observacao']}" if l.get("observacao") else "") if l else "não lida")
        md.append(f"| {ESPECIES.get(f['familia'], f['familia'])} | {leitura} | {f['catalogo']} | {f['no_acervo']} | "
                  f"{f['pct'] if f['pct'] is not None else '—'} | {f['com_texto']} | "
                  f"{_celula(f['numeros_ausentes'], 300) if f['maior_numero'] else '—'} |")
    md += ["", "Números ausentes do catálogo ficam como \"não localizado\": a ausência no catálogo não prova que o ato "
           "não exista.", "", "## Por espécie e ano", "", "| Espécie | Ano | No catálogo | No acervo | % | Com texto |",
           "|---|---|---|---|---|---|"]
    md += [f"| {ESPECIES.get(l['familia'], l['familia'])} | {l['ano']} | {l['catalogo']} | {l['no_acervo']} | "
           f"{l['pct'] if l['pct'] is not None else '—'} | {l['com_texto']} |" for l in dados["linhas"]]
    fora = [(f["familia"], d) for f in dados["familias"] for d in f["fora_do_catalogo"]]
    if fora:
        md += ["", "## No acervo, mas fora da última leitura do catálogo", ""] + [
            f"- {d['titulo'] or d['id']} ({ESPECIES.get(fam, fam)})" for fam, d in fora]
    if dados["pendentes"] or dados["lacunas"]:
        md += ["", "## Pendências e lacunas do acervo", ""]
        md += [f"- {p['titulo'] or p['id']}: {p['motivo_pendencia'] or 'sem motivo registrado'}" for p in dados["pendentes"]]
        md += [f"- {l['chave']}: {l['classificacao']} ({_celula(l['detalhe'])})" for l in dados["lacunas"]]
    destino_md.parent.mkdir(parents=True, exist_ok=True)
    destino_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    return dados
