"""Acervo público em Markdown: uma pasta `acervo/` pronta para versionar e publicar (ex.: no GitHub).

Gerado a partir do banco e das conversões aprovadas, como a biblioteca (`biblioteca.py`), mas pensado para
leitura direta num navegador de repositório:

    <destino>/
      COBERTURA.md                         acervo × catálogo oficial da CVM, por espécie e ano
      acervo/
        README.md                          índice geral (contagens e links)
        cobertura.csv
        resolucoes/
          README.md                        tabela de todas as resoluções (número, data, situação, ementa)
          2022/resolucao-cvm-175.md        texto preferido (consolidado vigente, se houver) + cabeçalho YAML
          2022/resolucao-cvm-175.original.md   redação original, quando a principal é consolidada
        audiencias-publicas/2020/sdm-2020-sdm0820.md

Cada arquivo traz um cabeçalho YAML com os metadados, a situação normativa e a origem (URL oficial, SHA-256 e
data da coleta do arquivo convertido). Só entram versões de texto aprovadas na conferência de fidelidade.

A saída é determinística (mesma base, mesmos arquivos), para que o histórico do Git mostre só o que mudou.
Só a pasta `acervo/` com a marca desta geração é substituída; nada mais no destino é apagado.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from repositorio_cvm import acervo, relatorios
from repositorio_cvm.justificativas import justificativas_do_documento, paragrafos as paragrafos_justificativa

MARCA = ".acervo-gerado"
PASTAS = {
    "resolucao": "resolucoes", "instrucao": "instrucoes", "deliberacao": "deliberacoes",
    "parecer_orientacao": "pareceres-de-orientacao", "oficio_circular": "oficios-circulares",
    "nota_explicativa": "notas-explicativas",
}
PLURAIS = {
    "resolucao": "Resoluções", "instrucao": "Instruções", "deliberacao": "Deliberações",
    "parecer_orientacao": "Pareceres de Orientação", "oficio_circular": "Ofícios-Circulares",
    "nota_explicativa": "Notas Explicativas",
}
PASTA_AUDIENCIAS = "audiencias-publicas"
PASTA_JUSTIFICATIVAS = "justificativas-air"
AVISO = ("Texto convertido automaticamente a partir do arquivo oficial da CVM, apenas para consulta. "
         "Em caso de divergência, prevalece o original publicado pela CVM.")


# Caracteres de controle vindos de PDFs com fonte sem mapeamento Unicode viram "□" (caractere não identificado,
# a mesma marca do conversor), para que o arquivo continue sendo texto: o GitHub trata NUL como binário.
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def texto_publicavel(texto: str) -> str:
    return _CONTROLE.sub("□", texto)


@dataclass
class Resultado:
    pasta: Path
    normas: int = 0
    arquivos: int = 0
    sem_texto: int = 0
    audiencias: int = 0
    avisos: list[str] = field(default_factory=list)


def _yaml(valor) -> str:
    """Valor YAML numa linha: strings entre aspas (JSON é YAML válido), números e nulos sem aspas."""
    if valor is None or valor == "":
        return "null"
    if isinstance(valor, bool) or isinstance(valor, (int, float)):
        return json.dumps(valor)
    return json.dumps(str(valor), ensure_ascii=False)


def cabecalho(campos: list[tuple[str, object]]) -> str:
    linhas = ["---"]
    for chave, valor in campos:
        if isinstance(valor, list):
            if not valor:
                linhas.append(f"{chave}: []")
                continue
            linhas.append(f"{chave}:")
            for item in valor:
                if isinstance(item, dict):
                    pares = list(item.items())
                    linhas.append(f"  - {pares[0][0]}: {_yaml(pares[0][1])}")
                    linhas += [f"    {k}: {_yaml(v)}" for k, v in pares[1:]]
                else:
                    linhas.append(f"  - {_yaml(item)}")
        else:
            linhas.append(f"{chave}: {_yaml(valor)}")
    return "\n".join(linhas + ["---"]) + "\n"


def _ano(linha: dict) -> str:
    if linha.get("ano"):
        return str(linha["ano"])
    return (linha.get("data_edicao") or "")[:4] or "sem-ano"


def _celula(texto: str | None, limite: int = 160) -> str:
    texto = " ".join((texto or "").split()).replace("|", "\\|")
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def _escrever(caminho: Path, texto: str) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with caminho.open("w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write(texto)


class Gerador:
    def __init__(self, pasta_dados: Path, conexao: sqlite3.Connection, destino: Path):
        self.dados = pasta_dados
        self.db = conexao
        self.destino = destino
        self.alvo = destino / "acervo"
        self.resultado = Resultado(self.alvo)
        self.indice: dict[str, list[dict]] = {}
        self.justificativas: list[dict] = []

    # ------------------------------------------------------------------ normas
    def _relacoes(self, doc: acervo.Documento) -> list[dict]:
        return [{"tipo": r["tipo"], "norma": r["alvo_no_acervo"] or r["alvo_url"], "evidencia": r["evidencia_url"]}
                for r in doc.relacoes]

    def _audiencias(self, documento_id: str) -> list[str]:
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'documento_audiencia'").fetchone():
            return []
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT audiencia_id FROM documento_audiencia WHERE documento_id = ? ORDER BY 1", (documento_id,))]

    def _arquivo_norma(self, pasta_rel: str, doc: acervo.Documento, versao: acervo.Versao, sufixo: str) -> str:
        l = doc.linha
        situacao = doc.evidencias.get("situacao") or {}
        campos = [
            ("id", l["id"]), ("titulo", doc.titulo), ("especie", acervo.ESPECIES.get(l["especie"], l["especie"])),
            ("numero", l["numero"]), ("ano", l["ano"]), ("ementa", l["ementa"]),
            ("data_edicao", l["data_edicao"]), ("data_publicacao_dou", l["data_publicacao"]),
            ("inicio_vigencia", l["data_inicio_vigencia"]), ("fim_vigencia", l["data_fim_vigencia"]),
            ("situacao", l["situacao"]), ("situacao_fonte", situacao.get("url")),
            ("situacao_verificada_em", (l["ultima_verificacao"] or "")[:10] or None),
            ("ficha_oficial", l["url_oficial"]),
            ("versao", versao.nome), ("versao_aviso", versao.aviso),
            ("fonte", versao.url_fonte), ("fonte_sha256", versao.sha256),
            ("fonte_coletada_em", (versao.coletado_em or "")[:10] or None),
            ("conversor", versao.conversor), ("qualidade", versao.qualidade),
            ("relacoes", self._relacoes(doc)), ("audiencias_publicas", self._audiencias(l["id"])),
            ("justificativa_air", self._caminho_justificativa(l)),
            ("aviso_vigencia", doc.aviso_vigencia()), ("aviso", AVISO),
        ]
        nome = f"{l['id']}{sufixo}.md"
        _escrever(self.temporaria / pasta_rel / nome,
                  cabecalho(campos) + "\n" + texto_publicavel(acervo.markdown(self.dados, versao).rstrip("\n")) + "\n")
        self.resultado.arquivos += 1
        return nome

    def _norma(self, documento_id: str) -> None:
        doc = acervo.carregar(self.db, documento_id)
        l = doc.linha
        especie = PASTAS.get(l["especie"], "outros")
        pasta_rel = f"{especie}/{_ano(l)}"
        principal = doc.versao("consolidado")
        entrada = {"id": l["id"], "titulo": doc.titulo, "numero": l["numero"], "data": l["data_edicao"],
                   "situacao": l["situacao"], "ementa": l["ementa"], "arquivo": None, "original": None,
                   "ficha": l["url_oficial"]}
        if principal is None:
            self.resultado.sem_texto += 1
        else:
            entrada["arquivo"] = f"{_ano(l)}/{self._arquivo_norma(pasta_rel, doc, principal, '')}"
            original = next((v for v in doc.versoes if v.tipo == acervo.TIPO_ORIGINAL), None)
            if original is not None and original.id != principal.id:
                entrada["original"] = f"{_ano(l)}/{self._arquivo_norma(pasta_rel, doc, original, '.original')}"
        entrada["justificativa"] = self._justificativa(doc)
        self.indice.setdefault(l["especie"], []).append(entrada)
        self.resultado.normas += 1

    # ------------------------------------------------------------------ justificativas de dispensa de AIR
    def _publicaveis(self, documento_id: str) -> list[dict]:
        return [j for j in justificativas_do_documento(self.db, documento_id) if j["arquivo_id"]]

    def _caminho_justificativa(self, linha: dict) -> str | None:
        """Caminho relativo a acervo/ do arquivo da justificativa da norma (None se não houver)."""
        if not self._publicaveis(linha["id"]):
            return None
        return f"{PASTA_JUSTIFICATIVAS}/{_ano(linha)}/{linha['id']}.md"

    def _justificativa(self, doc: acervo.Documento) -> str | None:
        js = self._publicaveis(doc.id)
        caminho = self._caminho_justificativa(doc.linha)
        if not caminho:
            return None
        arquivos = [{"rotulo": j["rotulo"], "url": j["url"], "sha256": j["sha256"],
                     "coletado_em": (j["coletado_em"] or "")[:10] or None, "qualidade": j["qualidade"],
                     "citada_na_ficha": j["evidencia_url"]} for j in js]
        campos = [("norma", doc.id), ("titulo", f"Justificativa de dispensa de AIR: {doc.titulo}"),
                  ("ficha_oficial", doc.linha["url_oficial"]), ("documentos", arquivos), ("aviso", AVISO)]
        secoes = []
        for j in js:
            corpo = paragrafos_justificativa(self.dados, j)
            texto = (texto_publicavel("\n\n".join(corpo)) if corpo else
                     f"Sem texto convertido ({j['qualidade'] or 'não convertido'}). Consulte o documento oficial: "
                     f"{j['url']}")
            secoes.append(f"## {j['rotulo']}\n\n{texto}")
        titulo = f"# Justificativa de dispensa de Análise de Impacto Regulatório: {doc.titulo}"
        _escrever(self.temporaria / caminho, cabecalho(campos) + "\n" + "\n\n".join([titulo, *secoes]) + "\n")
        self.resultado.arquivos += 1
        self.justificativas.append({"id": doc.id, "titulo": doc.titulo, "data": doc.linha["data_edicao"],
                                    "arquivo": caminho, "convertida": all(paragrafos_justificativa(self.dados, j)
                                                                          for j in js)})
        return caminho

    def _indice_justificativas(self) -> None:
        if not self.justificativas:
            return
        linhas = ["# Justificativas de dispensa de Análise de Impacto Regulatório (AIR)", "",
                  "Justificativas citadas na ficha oficial de cada norma: o documento anexo ou o trecho da decisão do "
                  "Colegiado que dispensou a AIR. A ficha sem esse link não prova que não houve justificativa.", "",
                  "| Norma | Data | Justificativa |", "|---|---|---|"]
        for j in sorted(self.justificativas, key=lambda j: (j["data"] or "", j["id"]), reverse=True):
            rel = j["arquivo"].split("/", 1)[1]
            linhas.append(f"| {j['titulo']} | {acervo.data_br(j['data'])} | [texto]({rel})"
                          + ("" if j["convertida"] else " (sem texto convertido)") + " |")
        _escrever(self.temporaria / PASTA_JUSTIFICATIVAS / "README.md", "\n".join(linhas) + "\n")

    def _indice_especie(self, especie: str, entradas: list[dict]) -> None:
        def ordem(e):
            numero = str(e["numero"] or "")
            return (e["data"] or "", int(numero) if numero.isdigit() else -1, e["id"])
        entradas = sorted(entradas, key=ordem, reverse=True)
        com_texto = sum(1 for e in entradas if e["arquivo"])
        revogados = sum(1 for e in entradas if e["situacao"] == REVOGADA)
        vigentes = sum(1 for e in entradas if e["situacao"] not in (REVOGADA, "não verificado"))
        linhas = [f"# {PLURAIS.get(especie, especie)}", "",
                  f"{_milhar(len(entradas))} atos no acervo: {_milhar(vigentes)} vigentes e {_milhar(revogados)} "
                  f"revogados. {_milhar(com_texto)} com texto integral. Mais recentes primeiro. "
                  "A situação é a indicada pela ficha oficial da CVM; confirme a vigência na fonte antes de citar.", "",
                  "| Ato | Data | Situação | Ementa | Texto |", "|---|---|---|---|---|"]
        for e in entradas:
            if e["arquivo"]:
                texto = f"[texto]({e['arquivo']})" + (f" · [original]({e['original']})" if e["original"] else "")
            else:
                texto = f"não localizado · [ficha]({e['ficha']})" if e["ficha"] else "não localizado"
            if e.get("justificativa"):
                texto += f" · [justificativa AIR](../{e['justificativa']})"
            linhas.append(f"| {_celula(e['titulo'], 60)} | {acervo.data_br(e['data'])} | {e['situacao']} | "
                          f"{_celula(e['ementa'])} | {texto} |")
        _escrever(self.temporaria / PASTAS.get(especie, "outros") / "README.md", "\n".join(linhas) + "\n")

    # ------------------------------------------------------------------ audiências
    def _audiencia(self, aud: sqlite3.Row) -> dict:
        ano = aud["id"].split("-")[1] if aud["id"].count("-") >= 2 else "sem-ano"
        normas = [r[0] for r in self.db.execute(
            "SELECT DISTINCT documento_id FROM documento_audiencia WHERE audiencia_id = ? ORDER BY 1", (aud["id"],))]
        arquivos, secoes = [], []
        for l in self.db.execute(
                "SELECT l.*, a.sha256, a.coletado_em, t.caminho_md, t.fidelidade_ok FROM audiencia_link l "
                "JOIN arquivo a ON a.id = l.arquivo_id "
                "LEFT JOIN audiencia_texto t ON t.id = (SELECT MAX(id) FROM audiencia_texto WHERE arquivo_id = l.arquivo_id) "
                "WHERE l.audiencia_id = ? ORDER BY l.ordem", (aud["id"],)):
            convertido = bool(l["caminho_md"] and l["fidelidade_ok"])
            arquivos.append({"secao": l["secao"], "rotulo": l["rotulo"], "url": l["url"], "sha256": l["sha256"],
                             "coletado_em": (l["coletado_em"] or "")[:10] or None,
                             "texto": "convertido" if convertido else "sem camada de texto legível (não convertido)"})
            if convertido:
                secoes.append(f"## {l['rotulo'] or l['secao'].capitalize()}\n\n"
                              + texto_publicavel(acervo.corpo_markdown(self.dados, l["caminho_md"]).rstrip("\n")))
        campos = [
            ("id", aud["id"]), ("codigo", aud["codigo"]), ("titulo", aud["titulo"]), ("tema", aud["tema"]),
            ("fase", aud["fase"]), ("prazo", aud["prazo_texto"]), ("prazo_no_edital", aud["prazo_edital_texto"]),
            ("pagina_oficial", aud["url"]), ("normas", normas), ("arquivos", arquivos),
            ("manifestacoes", "não coletadas (consulte a página oficial)"), ("aviso", AVISO),
        ]
        titulo = f"# Audiência Pública {aud['codigo'] or aud['id']}"
        corpo = "\n\n".join([titulo, *secoes]) if secoes else titulo + "\n\nSem texto convertido."
        nome = f"{ano}/{aud['id']}.md"
        _escrever(self.temporaria / PASTA_AUDIENCIAS / nome, cabecalho(campos) + "\n" + corpo + "\n")
        self.resultado.arquivos += 1
        self.resultado.audiencias += 1
        return {"id": aud["id"], "codigo": aud["codigo"], "tema": aud["tema"], "arquivo": nome, "normas": normas}

    def _audiencias_publicas(self) -> list[dict]:
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'audiencia'").fetchone():
            return []
        entradas = [self._audiencia(a) for a in
                    self.db.execute("SELECT * FROM audiencia WHERE status = 'lida' ORDER BY id DESC").fetchall()]
        if entradas:
            linhas = ["# Audiências públicas", "",
                      "Edital e relatório das audiências que deram origem a normas do acervo. As manifestações "
                      "recebidas não são coletadas.", "", "| Audiência | Tema | Normas |", "|---|---|---|"]
            linhas += [f"| [{e['codigo'] or e['id']}]({e['arquivo']}) | {_celula(e['tema'])} | "
                       f"{', '.join(e['normas']) or '—'} |" for e in entradas]
            _escrever(self.temporaria / PASTA_AUDIENCIAS / "README.md", "\n".join(linhas) + "\n")
        return entradas

    # ------------------------------------------------------------------ geração
    def gerar(self) -> Resultado:
        self.destino.mkdir(parents=True, exist_ok=True)
        if self.alvo.exists() and not (self.alvo / MARCA).exists():
            raise RuntimeError(f"{self.alvo} existe e não foi gerada por este comando; nada foi apagado.")
        self.temporaria = self.destino / "acervo.novo"
        if self.temporaria.exists():
            shutil.rmtree(self.temporaria)
        self.temporaria.mkdir()
        (self.temporaria / MARCA).write_text("pasta gerada por: repositorio-cvm publicar-acervo\n", encoding="utf-8")

        for (doc_id,) in self.db.execute("SELECT id FROM documento ORDER BY especie, id").fetchall():
            self._norma(doc_id)
        for especie, entradas in self.indice.items():
            self._indice_especie(especie, entradas)
        audiencias = self._audiencias_publicas()
        self._indice_justificativas()

        relatorios.gerar_cobertura(self.db, self.destino / "COBERTURA.md", self.temporaria / "cobertura.csv")
        self.situacao = situacao_por_especie(self.db)
        com_texto = sum(1 for entradas in self.indice.values() for e in entradas if e["arquivo"])
        total = sum(len(entradas) for entradas in self.indice.values())
        linhas = ["# Acervo", "",
                  "Atos normativos da CVM convertidos para Markdown, com cabeçalho YAML de metadados e origem. "
                  "Gerado pelo comando `repositorio-cvm publicar-acervo`; não edite à mão.", "",
                  f"> {AVISO}", "", tabela_situacao(self.situacao, prefixo=""), "",
                  f"Todos os {_milhar(total)} atos do acervo têm texto integral." if com_texto == total else
                  f"{_milhar(com_texto)} dos {_milhar(total)} atos têm texto integral; os demais aparecem nos índices "
                  "como \"não localizado\", com link para a ficha oficial."]
        if audiencias:
            linhas += ["", f"Mais {len(audiencias)} [audiências públicas]({PASTA_AUDIENCIAS}/README.md) "
                       "(edital e relatório) das normas que lhes deram origem."]
        if self.justificativas:
            linhas += ["", f"Mais {len(self.justificativas)} [justificativas de dispensa de Análise de Impacto "
                       f"Regulatório]({PASTA_JUSTIFICATIVAS}/README.md) citadas nas fichas das normas."]
        linhas += ["", "Cobertura por espécie e ano, e a lista do que falta: [COBERTURA.md](../COBERTURA.md) e "
                   "[cobertura.csv](cobertura.csv)."]
        _escrever(self.temporaria / "README.md", "\n".join(linhas) + "\n")

        if self.alvo.exists():
            shutil.rmtree(self.alvo)
        self.temporaria.rename(self.alvo)
        self._atualizar_readme_principal(audiencias)
        return self.resultado

    def _atualizar_readme_principal(self, audiencias: list[dict]) -> None:
        """Reescreve só o trecho entre os marcadores do README da raiz do destino (se existir)."""
        readme = self.destino / "README.md"
        if not readme.is_file():
            return
        texto = readme.read_text(encoding="utf-8")
        if INICIO_TABELA not in texto or FIM_TABELA not in texto:
            self.resultado.avisos.append(f"{readme}: marcadores da tabela ausentes; tabela do README não atualizada")
            return
        verificacao = self.db.execute("SELECT MAX(ultima_verificacao) FROM documento").fetchone()[0]
        bloco = [f"Posição em {acervo.data_br((verificacao or '')[:10])} (última verificação nas fontes oficiais). "
                 "Tabela atualizada automaticamente pelo `publicar-acervo`.", "",
                 tabela_situacao(self.situacao, prefixo="acervo/")]
        if audiencias:
            bloco += ["", f"Mais {len(audiencias)} [audiências públicas](acervo/{PASTA_AUDIENCIAS}/README.md) "
                      "(edital e relatório) das normas que lhes deram origem."]
        if self.justificativas:
            bloco += ["", f"Mais {len(self.justificativas)} [justificativas de dispensa de Análise de Impacto "
                      f"Regulatório](acervo/{PASTA_JUSTIFICATIVAS}/README.md) citadas nas fichas das normas."]
        inicio = texto.index(INICIO_TABELA) + len(INICIO_TABELA)
        fim = texto.index(FIM_TABELA)
        novo = texto[:inicio] + "\n" + "\n".join(bloco) + "\n" + texto[fim:]
        if novo != texto:
            _escrever(readme, novo)


# ---------------------------------------------------------------------- vigentes e revogados
INICIO_TABELA = "<!-- tabela-acervo:inicio (gerada pelo publicar-acervo; não edite à mão) -->"
FIM_TABELA = "<!-- tabela-acervo:fim -->"
REVOGADA = "integralmente revogada"


def _revogado_no_catalogo(titulo: str | None) -> bool:
    return "revogad" in (titulo or "").lower()


def situacao_por_especie(conexao: sqlite3.Connection) -> list[dict]:
    """Vigentes e revogados no acervo e na CVM, por espécie.

    Revogado é "integralmente revogada"; vigente é todo o resto que tem situação verificada (vigente, vigente com
    alterações, vigência futura, parcialmente revogada). Na CVM, os atos que estão no acervo seguem a ficha oficial;
    os que ainda não foram coletados seguem a marca "(Revogada)" do catálogo, que é incompleta (a ficha prevalece).
    """
    documentos = {d["url_oficial"]: d for d in conexao.execute("SELECT * FROM documento") if d["url_oficial"]}
    linhas = []
    for especie in PASTAS:
        no_acervo = [d for d in conexao.execute("SELECT * FROM documento WHERE especie = ?", (especie,))]
        leitura = conexao.execute(
            "SELECT id FROM leitura_catalogo WHERE familia = ? AND terminada_em IS NOT NULL ORDER BY id DESC LIMIT 1",
            (especie,)).fetchone() if _tem_tabela(conexao, "leitura_catalogo") else None
        catalogo = list(conexao.execute("SELECT * FROM catalogo_oficial WHERE familia = ? AND leitura_id = ?",
                                        (especie, leitura[0]))) if leitura else []
        if not no_acervo and not catalogo:
            continue
        linha = {"especie": especie,
                 "acervo_vigentes": sum(1 for d in no_acervo if d["situacao"] not in (REVOGADA, "não verificado")),
                 "acervo_revogados": sum(1 for d in no_acervo if d["situacao"] == REVOGADA),
                 "acervo_nao_verificados": sum(1 for d in no_acervo if d["situacao"] == "não verificado"),
                 "cvm_vigentes": 0, "cvm_revogados": 0, "catalogo_lido": bool(catalogo)}
        for item in catalogo:
            doc = documentos.get(item["url"])
            if doc is not None and doc["situacao"] == "não verificado":
                revogado = _revogado_no_catalogo(item["titulo"])
            elif doc is not None:
                revogado = doc["situacao"] == REVOGADA
            else:
                revogado = _revogado_no_catalogo(item["titulo"])
            linha["cvm_revogados" if revogado else "cvm_vigentes"] += 1
        linhas.append(linha)
    return linhas


def _tem_tabela(conexao: sqlite3.Connection, nome: str) -> bool:
    return conexao.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (nome,)).fetchone() is not None


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _pct(parte: int, todo: int) -> str:
    """Percentual com uma casa, arredondado; nunca mostra 100% sem estar completo (99,96% vira 99,9%)."""
    if not todo:
        return "—"
    if parte >= todo:
        return "100%"
    return f"{min(round(100 * parte / todo, 1), 99.9):.1f}".replace(".", ",") + "%"


def tabela_situacao(linhas: list[dict], prefixo: str) -> str:
    cab = ["| Espécie | No acervo (vigentes) | No acervo (revogados) | Na CVM (vigentes) | Na CVM (revogados) | "
           "Cobertura total | Cobertura vigentes |", "|---|---:|---:|---:|---:|---:|---:|"]
    soma = {k: 0 for k in ("acervo_vigentes", "acervo_revogados", "cvm_vigentes", "cvm_revogados",
                           "acervo_nao_verificados")}
    corpo = []
    for l in linhas:
        for k in soma:
            soma[k] += l[k]
        nome = f"[{PLURAIS[l['especie']]}]({prefixo}{PASTAS[l['especie']]}/README.md)"
        acervo_total = l["acervo_vigentes"] + l["acervo_revogados"] + l["acervo_nao_verificados"]
        cvm_total = l["cvm_vigentes"] + l["cvm_revogados"]
        if l["catalogo_lido"]:
            cvm = [_milhar(l["cvm_vigentes"]), _milhar(l["cvm_revogados"]), _pct(acervo_total, cvm_total),
                   _pct(l["acervo_vigentes"], l["cvm_vigentes"])]
        else:
            cvm = ["—", "—", "—", "—"]
        corpo.append(f"| {nome} | {_milhar(l['acervo_vigentes'])} | {_milhar(l['acervo_revogados'])} | "
                     + " | ".join(cvm) + " |")
    acervo_total = soma["acervo_vigentes"] + soma["acervo_revogados"] + soma["acervo_nao_verificados"]
    corpo.append(f"| **Total** | **{_milhar(soma['acervo_vigentes'])}** | **{_milhar(soma['acervo_revogados'])}** | "
                 f"**{_milhar(soma['cvm_vigentes'])}** | **{_milhar(soma['cvm_revogados'])}** | "
                 f"**{_pct(acervo_total, soma['cvm_vigentes'] + soma['cvm_revogados'])}** | "
                 f"**{_pct(soma['acervo_vigentes'], soma['cvm_vigentes'])}** |")
    nota = ("Vigentes inclui os atos vigentes com alterações e os já publicados com vigência futura; revogados são os "
            "integralmente revogados. No acervo, a situação é a da ficha oficial de cada ato. Na CVM, os atos que "
            "estão no acervo seguem a ficha oficial e os ainda não coletados seguem a marca \"(Revogada)\" do "
            "catálogo da CVM, que é incompleta: esses números podem mudar quando forem coletados.")
    if soma["acervo_nao_verificados"]:
        nota += f" {soma['acervo_nao_verificados']} ato(s) do acervo com situação não verificada não entram nas colunas."
    return "\n".join(cab + corpo) + "\n\n" + nota


def gerar(pasta_dados: Path, conexao: sqlite3.Connection, destino: Path) -> Resultado:
    return Gerador(pasta_dados, conexao, destino).gerar()
