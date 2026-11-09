"""Leitura de um documento do acervo para visualização, exportação e API local.

Tudo o que é exibido vem do banco: metadados com a evidência mais recente de cada campo (origem da
informação), relações com a evidência que as sustenta, arquivos oficiais e versões de texto aprovadas.
A versão de texto segue a mesma regra da pesquisa: a aprovada mais recente do tipo preferido.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from lxml import html as lhtml
import re

from markdown_it import MarkdownIt

# Três versões por norma alterada (D-21): a original, a alterada com a redação anterior tachada (o consolidado
# oficial da CVM ou, quando há alterações que ele não incorpora, a gerada automaticamente) e a consolidada,
# só com o texto vigente.
TIPO_ORIGINAL = "texto original"
TIPO_OFICIAL = "texto consolidado oficial"
TIPO_ALTERADO = "texto alterado com tachado (gerado)"
TIPO_VIGENTE = "texto consolidado vigente"
NOMES_VERSAO = {
    TIPO_VIGENTE: "Consolidada (texto vigente)",
    TIPO_OFICIAL: "Alterada, com tachado (consolidado oficial da CVM)",
    TIPO_ALTERADO: "Alterada, com tachado (gerada automaticamente)",
    TIPO_ORIGINAL: "Original",
}
PREFERENCIA = {
    "consolidado": (TIPO_VIGENTE, TIPO_OFICIAL, TIPO_ALTERADO, TIPO_ORIGINAL),
    "alterada": (TIPO_ALTERADO, TIPO_OFICIAL, TIPO_VIGENTE, TIPO_ORIGINAL),
    "oficial": (TIPO_OFICIAL, TIPO_ALTERADO, TIPO_VIGENTE, TIPO_ORIGINAL),
    "original": (TIPO_ORIGINAL, TIPO_VIGENTE, TIPO_OFICIAL, TIPO_ALTERADO),
}
_CHAVE_VERSAO = {TIPO_VIGENTE: "consolidado", TIPO_OFICIAL: "oficial", TIPO_ALTERADO: "alterada",
                 TIPO_ORIGINAL: "original"}


def chave_versao(tipo: str) -> str:
    """Chave da versão na URL e na exportação: consolidado, alterada (gerada), oficial ou original."""
    return _CHAVE_VERSAO.get(tipo, "original")
ESPECIES = {
    "resolucao": "Resolução",
    "instrucao": "Instrução",
    "deliberacao": "Deliberação",
    "parecer_orientacao": "Parecer de Orientação",
    "oficio_circular": "Ofício-Circular",
    "nota_explicativa": "Nota Explicativa",
}
_CAMPOS = [
    ("titulo", "Título"), ("especie", "Espécie"), ("numero", "Número"), ("ano", "Ano"), ("ementa", "Ementa"),
    ("assunto", "Assunto"), ("area_tecnica", "Área técnica"), ("data_edicao", "Data de edição"),
    ("data_publicacao", "Publicação no DOU"), ("data_inicio_vigencia", "Início de vigência"),
    ("data_fim_vigencia", "Fim de vigência"), ("situacao", "Situação normativa"), ("url_oficial", "Ficha oficial"),
    ("status_coleta", "Status da coleta"), ("ultima_verificacao", "Última verificação"),
]
_ROTULO_RELACAO = {"altera": "Altera", "revoga": "Revoga", "alterada_por": "Alterada por",
                   "revogada_por": "Revogada por", "vide": "Vide"}

# Sem linha horizontal: uma linha só de "____" (campo a preencher em formulários) é texto da norma.
_md = MarkdownIt("commonmark", {"html": True, "typographer": False}).enable(["table", "strikethrough"]).disable("hr")
# Notas de rodapé do conversor: "[^n]" no texto e "[^n]: texto" na definição. São tratadas aqui, e não por plugin,
# porque o plugin renumera as notas pela ordem de chamada e descarta as definições sem chamada (chamadas dentro
# de tabelas HTML não são lidas por ele); o número da nota no original deve ser preservado.
_NOTA_DEFINICAO = re.compile(r"^\[\^([^\]\s]+)\]:[ \t]?", re.M)
_NOTA_CHAMADA = re.compile(r"\[\^([^\]\s]+)\]")
_SUBLINHADO = re.compile(r"_{2,}")
# Asterisco simples entre caracteres ("b.1.3*b.1.4", multiplicação) é texto; o conversor só usa "*" e "**" junto
# de espaço ou início/fim de linha (itálico da ementa, negrito do rótulo do artigo).
_ASTERISCO = re.compile(r"(?<=[^\s*\\])\*(?=[^\s*])")


@dataclass
class Versao:
    id: int
    tipo: str
    conversor: str
    qualidade: str
    caminho_md: str
    gerado_em: str
    url_fonte: str
    sha256: str
    coletado_em: str
    conferencia_cruzada: str | None

    base_versao_id: int | None = None

    @property
    def nome(self) -> str:
        return NOMES_VERSAO.get(self.tipo, self.tipo)

    @property
    def chave(self) -> str:
        return chave_versao(self.tipo)

    @property
    def gerada(self) -> bool:
        """Consolidação gerada automaticamente pela aplicação de alterações (não oficial)."""
        return self.conversor.startswith("consolidacao-gerada")

    @property
    def aviso(self) -> str:
        """Como o texto desta versão foi obtido (exibido na página e no cabeçalho da exportação)."""
        if self.tipo == TIPO_VIGENTE and self.gerada:
            return ("Consolidação gerada automaticamente, não oficial: alterações aplicadas pelo sistema a partir "
                    "do texto das normas alteradoras. Confira com as normas alteradoras antes de citar.")
        if self.tipo == TIPO_VIGENTE:
            return ("Texto vigente derivado do consolidado oficial da CVM, com a redação anterior tachada retirada "
                    "e as notas de alteração mantidas.")
        if self.tipo == TIPO_ALTERADO:
            return ("Consolidação gerada automaticamente, não oficial: trechos riscados são redação anterior; "
                    "as notas indicam a norma alteradora. Confira com as normas alteradoras antes de citar.")
        if self.tipo == TIPO_OFICIAL:
            return "Consolidado oficial da CVM: trechos riscados são redação anterior, mantida como no arquivo oficial."
        return "Redação original (não é texto consolidado)."

    @property
    def nivel(self) -> str:
        """alta, média, baixa (primeira palavra da qualidade)."""
        return self.qualidade.split(":", 1)[0].strip()


@dataclass
class Documento:
    linha: dict
    evidencias: dict[str, dict]
    relacoes: list[dict]
    links: list[dict]
    versoes: list[Versao]
    lacunas: list[dict] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.linha["id"]

    @property
    def titulo(self) -> str:
        return self.linha["titulo"] or self.linha["id"]

    def campos(self) -> list[tuple[str, str, object, dict | None]]:
        """(campo, rótulo, valor, evidência) na ordem de exibição."""
        return [(c, r, self.linha.get(c), self.evidencias.get(c)) for c, r in _CAMPOS]

    def versao(self, preferida: str = "consolidado") -> Versao | None:
        for tipo in PREFERENCIA.get(preferida, PREFERENCIA["consolidado"]):
            if v := next((v for v in self.versoes if v.tipo == tipo), None):
                return v
        return self.versoes[0] if self.versoes else None

    def aviso_vigencia(self) -> str:
        """Aviso exigido na exportação (§10) quando a vigência não está confirmada."""
        situacao = self.linha["situacao"]
        if situacao == "não verificado":
            return "Situação normativa não verificada. Confirme a vigência na fonte oficial antes de utilizar."
        verificado = (self.linha["ultima_verificacao"] or "")[:10]
        aviso = (f"Situação conforme as marcações da ficha oficial da CVM consultada em {data_br(verificado)}. "
                 "Revogações feitas pelo texto de outras normas ainda não são cruzadas automaticamente; "
                 "confirme a vigência na fonte oficial antes de citar.")
        if situacao == "vigência futura" and self.linha["data_inicio_vigencia"]:
            aviso = f"Norma com vigência futura: início em {data_br(self.linha['data_inicio_vigencia'])}. " + aviso
        return aviso


def data_br(data: str | None) -> str:
    return f"{data[8:10]}/{data[5:7]}/{data[0:4]}" if data and len(data) >= 10 else "—"


def carregar(conexao: sqlite3.Connection, documento_id: str) -> Documento | None:
    linha = conexao.execute("SELECT * FROM documento WHERE id = ?", (documento_id,)).fetchone()
    if linha is None:
        return None
    evidencias: dict[str, dict] = {}
    for e in conexao.execute("SELECT * FROM evidencia WHERE documento_id = ? ORDER BY id", (documento_id,)):
        evidencias[e["campo"]] = dict(e)  # a mais recente de cada campo prevalece
    urls = {r["url_oficial"]: r["id"] for r in conexao.execute("SELECT id, url_oficial FROM documento")}
    relacoes = []
    for r in conexao.execute(
            "SELECT r.*, e.trecho, e.url AS evidencia_url FROM relacao r JOIN evidencia e ON e.id = r.evidencia_id "
            "WHERE r.documento_id = ? ORDER BY r.tipo, r.id", (documento_id,)):
        rel = dict(r)
        rel["rotulo_tipo"] = _ROTULO_RELACAO.get(rel["tipo"], rel["tipo"])
        rel["alvo_no_acervo"] = rel["alvo_id"] or urls.get(rel["alvo_url"])
        relacoes.append(rel)
    links = [dict(l) for l in conexao.execute(
        "SELECT * FROM link_documento WHERE documento_id = ? ORDER BY id", (documento_id,))]
    lacunas = [dict(l) for l in conexao.execute(
        "SELECT * FROM lacuna WHERE chave = ? ORDER BY id DESC", (documento_id,))]
    return Documento(dict(linha), evidencias, relacoes, links, versoes_aprovadas(conexao, documento_id), lacunas)


def versoes_aprovadas(conexao: sqlite3.Connection, documento_id: str) -> list[Versao]:
    """A versão aprovada mais recente de cada tipo, na ordem: consolidada, alterada (oficial, gerada), original."""
    vistas: dict[str, Versao] = {}
    for v in conexao.execute(
            "SELECT v.*, a.url AS url_fonte, a.sha256, a.coletado_em FROM versao_texto v "
            "JOIN arquivo a ON a.id = v.arquivo_id WHERE v.documento_id = ? AND v.fidelidade_ok = 1 "
            # Consolidação gerada que não aplicou nenhuma alteração não substitui a derivada do oficial.
            "AND NOT (v.conversor LIKE 'consolidacao-gerada%' AND NOT EXISTS (SELECT 1 FROM alteracao_aplicada x "
            "WHERE x.versao_id = v.id AND x.status = 'aplicada')) "
            "ORDER BY v.id DESC", (documento_id,)):
        if v["tipo"] not in vistas:
            vistas[v["tipo"]] = Versao(v["id"], v["tipo"], v["conversor"], v["qualidade"], v["caminho_md"],
                                       v["gerado_em"], v["url_fonte"], v["sha256"], v["coletado_em"],
                                       v["conferencia_cruzada"], v["base_versao_id"])
    ordem = PREFERENCIA["consolidado"]
    return sorted(vistas.values(), key=lambda v: ordem.index(v.tipo) if v.tipo in ordem else len(ordem))


def markdown(pasta_dados: Path, versao: Versao) -> str:
    """Corpo do Markdown convertido, sem o cabeçalho (front matter)."""
    return corpo_markdown(pasta_dados, versao.caminho_md)


def corpo_markdown(pasta_dados: Path, caminho_md: str) -> str:
    texto = (pasta_dados / caminho_md).read_text(encoding="utf-8")
    if texto.startswith("---\n"):
        fim = texto.find("\n---\n", 4)
        if fim != -1:
            texto = texto[fim + 5:]
    return texto.lstrip("\n")


@dataclass
class Parte:
    """Parte de uma norma com anexos (ex.: Res. 175: Parte Geral, Anexos Normativos I a XII e Suplementos)."""

    chave: str  # para a URL: "principal", "anexo-normativo-i", "suplementos"
    nome: str  # "Parte Geral", "Anexo Normativo I", "Anexo A", "Suplementos"
    titulo: str  # com o tema, quando a ficha ou o título do anexo o trazem
    parte: str | None  # valor de dispositivo.parte (None no texto principal)
    dispositivos: int
    url_oficial: str | None = None  # PDF oficial só desta parte, quando a ficha o oferece


def chave_parte(parte: str | None) -> str:
    if parte is None:
        return "principal"
    sem_acento = unicodedata.normalize("NFKD", parte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", sem_acento.lower()).strip("-")


def partes(conexao: sqlite3.Connection, doc: Documento, versao: Versao) -> list[Parte]:
    """Partes da versão de texto, na ordem do documento; lista vazia quando a norma não tem anexos.

    A divisão vem do próprio texto (títulos "ANEXO ..." e "SUPLEMENTO ..."). Os nomes completos e os PDFs
    oficiais por parte vêm da ficha, quando ela os lista (caso da Res. 175); os PDFs por parte da ficha são
    do texto consolidado e por isso só são indicados na versão consolidada.
    """
    linhas = conexao.execute(
        "SELECT parte, MIN(ordem) AS inicio, COUNT(*) AS n FROM dispositivo WHERE versao_id = ? "
        "GROUP BY parte ORDER BY inicio", (versao.id,)).fetchall()
    if len(linhas) < 2:
        return []
    da_ficha = [l for l in doc.links if l["papel"] in ("anexo", "complementar") and l["rotulo"]]
    principal = "Parte Geral" if any(l["rotulo"].strip().lower() == "parte geral" for l in da_ficha) else "Texto principal"
    consolidado = versao.tipo != TIPO_ORIGINAL
    resultado = []
    for linha in linhas:
        nome = linha["parte"] or principal
        link = next((l for l in da_ficha if l["rotulo"] == nome or l["rotulo"].startswith(nome + " ")), None)
        titulo = link["rotulo"] if link else nome
        if not link and linha["parte"]:
            cabecalho = conexao.execute(
                "SELECT texto FROM dispositivo WHERE versao_id = ? AND parte = ? AND tipo = 'cabecalho' "
                "ORDER BY ordem LIMIT 1", (versao.id, linha["parte"])).fetchone()
            titulo = cabecalho["texto"] if cabecalho else nome
        url = link["url"] if link and consolidado and "consolid" in link["url"].lower() else None
        resultado.append(Parte(chave_parte(linha["parte"]), nome, titulo, linha["parte"], linha["n"], url))
    return resultado


def markdown_parte(pasta_dados: Path, conexao: sqlite3.Connection, versao: Versao, parte: Parte) -> str:
    """Só os blocos da parte. Cada bloco do Markdown do conversor é um dispositivo, na mesma ordem."""
    blocos = markdown(pasta_dados, versao).rstrip("\n").split("\n\n")
    total = conexao.execute("SELECT COUNT(*) FROM dispositivo WHERE versao_id = ?", (versao.id,)).fetchone()[0]
    if len(blocos) != total:
        raise ValueError(f"o Markdown da versão {versao.id} tem {len(blocos)} blocos e {total} dispositivos; "
                         "não é possível separar a parte com segurança")
    ordens = [r[0] for r in conexao.execute(
        "SELECT ordem FROM dispositivo WHERE versao_id = ? AND parte IS ? ORDER BY ordem", (versao.id, parte.parte))]
    return "\n\n".join(blocos[o - 1] for o in ordens) + "\n"


def _marcador_de_lista(self, tokens, idx, options, env):
    token = tokens[idx]
    token.attrSet("data-marcador", f"{token.info}{token.markup}" if token.info else token.markup)
    return self.renderToken(tokens, idx, options, env)


_md.add_render_rule("list_item_open", _marcador_de_lista)


def html(texto_md: str) -> str:
    """Markdown -> HTML (tabelas em HTML do conversor, tachado e notas de rodapé preservados).

    Linhas como "1. PÚBLICO-ALVO" ou "* Quando se referir..." são texto da norma, não listas: o Markdown as
    leria como listas e o número ou o asterisco deixariam de fazer parte do texto (e poderiam ser renumerados).
    Por isso cada item vira um parágrafo com o marcador original, literal.
    """
    texto_md = _NOTA_DEFINICAO.sub(
        lambda m: f'<span class="nota-rodape" id="fn-{m.group(1)}"></span>\\[{m.group(1)}\\] ', texto_md)
    texto_md = _NOTA_CHAMADA.sub(
        lambda m: f'<sup class="nota-ref"><a href="#fn-{m.group(1)}">[{m.group(1)}]</a></sup>', texto_md)
    # "__", "___" e "a*b" seriam lidos como negrito/itálico; fora das linhas de HTML (tabelas), escapam-se.
    texto_md = "\n".join(
        l if l.lstrip().startswith("<")
        else _ASTERISCO.sub(r"\\*", _SUBLINHADO.sub(lambda m: "\\_" * len(m.group(0)), l))
        for l in texto_md.split("\n"))
    bruto = _md.render(texto_md)
    if "<li" not in bruto:
        return bruto
    raiz = lhtml.fragment_fromstring(bruto, create_parent="div")
    for lista in reversed(list(raiz.iter("ol", "ul"))):
        lista.tag = "div"
        lista.attrib.clear()
        lista.set("class", "lista")
        for item in list(lista):
            if item.tag != "li":
                continue
            marcador = item.get("data-marcador", "")
            alvo = item[0] if len(item) and item[0].tag == "p" and not (item.text or "").strip() else None
            if alvo is None:
                item.tag = "p"
                item.attrib.clear()
                alvo = item
            else:
                item.tag = "div"
                item.attrib.clear()
            alvo.text = f"{marcador} " + (alvo.text or "")
    return (raiz.text or "") + "".join(lhtml.tostring(f, encoding="unicode") for f in raiz)


def listar(conexao: sqlite3.Connection, especie: str | None = None, situacao: str | None = None,
           ano: int | None = None) -> list[sqlite3.Row]:
    filtros, args = [], []
    for campo, valor in (("especie", especie), ("situacao", situacao), ("ano", ano)):
        if valor:
            filtros.append(f"d.{campo} = ?")
            args.append(valor)
    onde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    return conexao.execute(
        # Versões existentes, na ordem de exibição: "original, alterada (tachado), consolidada".
        "SELECT d.*, (SELECT group_concat(nome, ', ') FROM (SELECT DISTINCT "
        f"CASE v.tipo WHEN '{TIPO_ORIGINAL}' THEN 'original' WHEN '{TIPO_VIGENTE}' THEN 'consolidada' "
        "ELSE 'alterada (tachado)' END AS nome, "
        f"CASE v.tipo WHEN '{TIPO_ORIGINAL}' THEN 1 WHEN '{TIPO_VIGENTE}' THEN 3 ELSE 2 END AS ordem "
        "FROM versao_texto v WHERE v.documento_id = d.id AND v.fidelidade_ok = 1 ORDER BY ordem)) AS versoes "
        f"FROM documento d {onde} "
        "ORDER BY d.especie, d.ano DESC, CAST(d.numero AS INTEGER) DESC, d.id", args).fetchall()
