"""Audiências públicas das normas: edital, tema, prazo, fase, relatório e normas editadas.

A relação norma -> audiência tem duas origens, ambas registradas como evidência:
- a ficha da norma ("AUDIÊNCIA PÚBLICA: SDM 02/21", com link para a página da audiência);
- a seção "Norma editada" da página da audiência (sentido inverso).
Ficha sem link de audiência não prova que não houve audiência: nesse caso nada é registrado.

A página oficial (`/audiencias_publicas/ap_<área>/<ano>/<código>.html`) tem as seções "Edital", "Tema",
"Prazo para Manifestação", "Fase", "Manifestações recebidas", "Relatório" e "Norma editada". O edital (com
aviso de prorrogação e anexos) e o relatório são baixados como originais imutáveis e convertidos em texto
pesquisável. As manifestações recebidas não são lidas nem baixadas (decisão do usuário, 28/10/2026).

O prazo é guardado como a página o exibe e, à parte, como o edital o declara ("Prazo: 2 de abril de 2021"):
os dois podem diferir (prorrogação, fuso do servidor) e nenhum é corrigido pelo outro.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.coleta.coletor import Coletor
from repositorio_cvm.coleta.ficha import _data_em_ingles, ler_ficha
from repositorio_cvm.coleta.http import FetchError
from repositorio_cvm.conversao.docx import blocos_docx
from repositorio_cvm.conversao.fidelidade import verificar
from repositorio_cvm.conversao.html import _DATA_EXTENSO, _MESES, normalizar
from repositorio_cvm.conversao.pdf import extrair as extrair_pdf

log = logging.getLogger("repositorio_cvm.audiencias")

CONVERSOR = "audiencia-texto/1"
SECOES_BAIXADAS = ("edital", "relatório")
_SECOES = {"edital": "edital", "tema": "tema", "prazo para manifestação": "prazo", "fase": "fase",
           "manifestações recebidas": "manifestações", "relatório": "relatório", "norma editada": "norma editada"}
_ENDERECO = re.compile(r"^/audiencias_publicas/(ap_[a-z]+)/(\d{4})/([^/]+?)\.html?$", re.I)
_TITULO = re.compile(r"(?:Audi[êe]ncia|Consulta)\s+P[úu]blica\s+(.+)$", re.I)
_PRAZO_EDITAL = re.compile(r"\bPrazo\s*:\s*(\d{1,2}\s*[º°o]?\s+de\s+[a-zç]+\s+de\s+\d{4})", re.I)
_NORMA = re.compile(r"^(Resolução|Instrução|Deliberação|Parecer de Orientação)\s+CVM\s+(?:n[º°o.]*\s*)?(\d+)", re.I)
_ESPECIE = {"resolução": "resolucao", "instrução": "instrucao", "deliberação": "deliberacao",
            "parecer de orientação": "parecer_orientacao"}


def id_audiencia(url: str) -> str | None:
    """'.../ap_sdm/2021/sdm0221.html' -> 'sdm-2021-sdm0221'."""
    m = _ENDERECO.match(urlsplit(url).path)
    return f"{m.group(1)[3:].lower()}-{m.group(2)}-{m.group(3).lower()}" if m else None


def _formato(url: str) -> str | None:
    sufixo = Path(urlsplit(url).path).suffix.lower().lstrip(".")
    return {"htm": "html"}.get(sufixo, sufixo) or None


@dataclass(frozen=True)
class LinkAudiencia:
    secao: str
    rotulo: str
    url: str
    formato: str | None


@dataclass
class PaginaAudiencia:
    url: str
    titulo: str | None = None
    codigo: str | None = None
    tema: str | None = None
    prazo: str | None = None
    prazo_texto: str | None = None
    fase: str | None = None
    links: list[LinkAudiencia] = field(default_factory=list)
    secoes: list[str] = field(default_factory=list)  # rótulos encontrados, na ordem (conferência de layout)


def _rotulo_de_secao(no: Tag) -> str | None:
    """`<p><b>Edital</b></p>`: parágrafo só com negrito e sem link é rótulo de seção."""
    if no.name != "p" or no.find("a") is not None or no.find(["b", "strong"]) is None:
        return None
    texto = normalizar(no.get_text(" ")).rstrip(":").strip()
    negrito = normalizar(" ".join(b.get_text(" ") for b in no.find_all(["b", "strong"]))).rstrip(":").strip()
    return texto if texto and texto == negrito else None


def ler_pagina_audiencia(html: bytes | str, url: str) -> PaginaAudiencia:
    sopa = BeautifulSoup(html, "lxml")
    pagina = PaginaAudiencia(url=url)
    titulo = next((h for h in sopa.find_all(["h1", "h2", "h3"]) if _TITULO.search(normalizar(h.get_text(" ")))), None)
    if titulo is not None:
        pagina.titulo = normalizar(titulo.get_text(" "))
        pagina.codigo = _TITULO.search(pagina.titulo).group(1)
    conteudo = next((s for s in sopa.select("section.contentArticle")
                     if any(_rotulo_de_secao(p) for p in s.find_all("p", recursive=False))), None)
    if conteudo is None:
        return pagina
    secao, textos = None, {}
    for no in conteudo.find_all(recursive=False):
        rotulo = _rotulo_de_secao(no)
        if rotulo:
            chave = rotulo.lower()
            if "english" in chave or "inglês" in chave:
                secao = "versão em inglês"
            else:
                secao = _SECOES.get(chave, chave)
            pagina.secoes.append(rotulo)
            continue
        if secao is None or secao == "manifestações":
            continue  # manifestações recebidas não são lidas
        links = [a for a in no.find_all("a", href=True) if normalizar(a.get_text(" "))]
        for a in links:
            alvo = urljoin(url, a["href"])
            if alvo not in {l.url for l in pagina.links}:
                pagina.links.append(LinkAudiencia(secao, normalizar(a.get_text(" ")), alvo, _formato(alvo)))
        if not links and secao in ("tema", "prazo", "fase"):
            texto = normalizar(no.get_text(" "))
            if texto:
                textos.setdefault(secao, []).append(texto)
    pagina.tema = " ".join(textos.get("tema", [])) or None
    pagina.fase = " ".join(textos.get("fase", [])) or None
    pagina.prazo_texto = " ".join(textos.get("prazo", [])) or None
    pagina.prazo = _data_em_ingles(pagina.prazo_texto) if pagina.prazo_texto else None
    return pagina


def prazo_do_edital(texto: str) -> tuple[str | None, str | None]:
    """Linha "Prazo: 8 de julho de 2021" do início do edital -> (AAAA-MM-DD, trecho)."""
    m = _PRAZO_EDITAL.search(texto[:4000])
    if not m:
        return None, None
    trecho = " ".join(m.group(0).split())
    d = _DATA_EXTENSO.search(m.group(1))
    mes = _MESES.get(d.group(2).lower()) if d else None
    return (f"{int(d.group(3)):04d}-{mes:02d}-{int(d.group(1)):02d}" if mes else None), trecho


def documento_da_norma_editada(rotulo: str) -> tuple[str, str] | None:
    """'Resolução CVM 175' -> ('resolucao', '175')."""
    m = _NORMA.match(rotulo)
    return (_ESPECIE[m.group(1).lower()], str(int(m.group(2)))) if m else None


class ColetorAudiencias:
    def __init__(self, coletor: Coletor):
        self.coletor = coletor
        self.db = coletor.db
        self.config = coletor.config

    # ------------------------------------------------------------------ ficha da norma
    def da_ficha(self, documento_id: str) -> list[str]:
        """Registra as audiências citadas na ficha já guardada (sem acessar a rede). Devolve os ids."""
        ficha_arq = self.db.execute(
            "SELECT * FROM arquivo WHERE documento_id = ? AND papel = 'ficha' ORDER BY coletado_em DESC, id DESC LIMIT 1",
            (documento_id,)).fetchone()
        if ficha_arq is None:
            return []
        ficha = ler_ficha((self.config.pasta_dados / ficha_arq["caminho"]).read_bytes(), ficha_arq["url"])
        ids = []
        for citada in ficha.audiencias:
            aud = self._garantir(citada.url)
            if aud is None:
                continue
            evid = self.coletor._evidencia(documento_id, "audiencia_publica", citada.codigo, ficha_arq["url"],
                                           ficha_arq["sha256"], citada.trecho)
            self.db.execute("INSERT OR IGNORE INTO documento_audiencia (documento_id, audiencia_id, origem, evidencia_id) "
                            "VALUES (?, ?, 'ficha da norma', ?)", (documento_id, aud, evid))
            ids.append(aud)
        self.db.commit()
        return ids

    def _garantir(self, url: str) -> str | None:
        aud = id_audiencia(url)
        if aud:
            self.db.execute("INSERT OR IGNORE INTO audiencia (id, url, status) VALUES (?, ?, 'não lida')", (aud, url))
        return aud

    # ------------------------------------------------------------------ página da audiência
    def ler(self, audiencia_id: str) -> str:
        """Lê a página, registra seções e links, baixa e converte edital e relatório. Devolve o status."""
        aud = self.db.execute("SELECT * FROM audiencia WHERE id = ?", (audiencia_id,)).fetchone()
        try:
            artefato = self.coletor.baixar(aud["url"], f"audiencia:{audiencia_id}", "html")
        except FetchError as erro:
            self.db.execute("UPDATE audiencia SET status = 'indisponível', detalhe = ? WHERE id = ?",
                            (str(erro), audiencia_id))
            self.db.commit()
            return "indisponível"
        arquivo_id = self.coletor.registrar_arquivo(None, artefato, "audiencia", "html")
        pagina = ler_pagina_audiencia(artefato.bytes, aud["url"])
        if not pagina.secoes:
            self.db.execute("UPDATE audiencia SET status = 'indisponível', detalhe = ?, arquivo_id = ?, lida_em = ? "
                            "WHERE id = ?", ("página sem as seções esperadas (Edital, Tema, Prazo...)", arquivo_id,
                                             agora(), audiencia_id))
            self.db.commit()
            return "indisponível"
        self.db.execute(
            "UPDATE audiencia SET codigo = ?, titulo = ?, tema = ?, prazo = ?, prazo_texto = ?, fase = ?, status = 'lida', "
            "detalhe = ?, arquivo_id = ?, lida_em = ? WHERE id = ?",
            (pagina.codigo, pagina.titulo, pagina.tema, pagina.prazo, pagina.prazo_texto, pagina.fase,
             json.dumps({"secoes": pagina.secoes}, ensure_ascii=False), arquivo_id, agora(), audiencia_id))
        for ordem, link in enumerate(pagina.links, 1):
            self.db.execute(
                "INSERT INTO audiencia_link (audiencia_id, secao, rotulo, url, formato, ordem) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(audiencia_id, url) DO UPDATE SET secao = excluded.secao, rotulo = excluded.rotulo, "
                "formato = excluded.formato, ordem = excluded.ordem",
                (audiencia_id, link.secao, link.rotulo, link.url, link.formato, ordem))
        self._normas_editadas(audiencia_id, pagina, artefato.url, artefato.sha256)
        self.db.commit()
        self._baixar_e_converter(audiencia_id)
        return "lida"

    def _normas_editadas(self, audiencia_id: str, pagina: PaginaAudiencia, url: str, sha: str) -> None:
        for link in (l for l in pagina.links if l.secao == "norma editada"):
            ident = documento_da_norma_editada(link.rotulo)
            if ident is None:
                continue
            doc = self.db.execute("SELECT id FROM documento WHERE especie = ? AND numero = ?", ident).fetchone()
            if doc is None:
                continue  # norma ainda fora do acervo; o link fica registrado em audiencia_link
            evid = self.coletor._evidencia(doc["id"], "audiencia_publica", pagina.codigo, url, sha,
                                           f"{pagina.titulo} — Norma editada: {link.rotulo}")
            self.db.execute("INSERT OR IGNORE INTO documento_audiencia (documento_id, audiencia_id, origem, evidencia_id) "
                            "VALUES (?, ?, 'página da audiência (norma editada)', ?)", (doc["id"], audiencia_id, evid))

    def _baixar_e_converter(self, audiencia_id: str) -> None:
        links = self.db.execute(
            f"SELECT * FROM audiencia_link WHERE audiencia_id = ? AND secao IN ({','.join('?' * len(SECOES_BAIXADAS))}) "
            "AND formato IN ('pdf', 'docx') ORDER BY ordem", (audiencia_id, *SECOES_BAIXADAS)).fetchall()
        # O primeiro arquivo da seção Edital é o edital; os seguintes são aviso de prorrogação e anexos. Se o edital
        # não tiver texto legível, o prazo do edital fica sem valor (o aviso traz o prazo prorrogado, não o do edital).
        edital = next((l["id"] for l in links if l["secao"] == "edital"), None)
        for link in links:
            if link["arquivo_id"] is None:
                try:
                    artefato = self.coletor.baixar(link["url"], f"audiencia:{audiencia_id}", link["formato"])
                except FetchError as erro:
                    log.warning("%s: %s não obtido: %s", audiencia_id, link["url"], erro)
                    continue
                arquivo_id = self.coletor.registrar_arquivo(None, artefato, f"audiencia:{link['secao']}", link["formato"])
                self.db.execute("UPDATE audiencia_link SET arquivo_id = ? WHERE id = ?", (arquivo_id, link["id"]))
                self.db.commit()
            else:
                arquivo_id = link["arquivo_id"]
            texto = self._converter(audiencia_id, link, arquivo_id)
            if texto and link["id"] == edital:
                data, trecho = prazo_do_edital(texto)
                if trecho:
                    self.db.execute("UPDATE audiencia SET prazo_edital = ?, prazo_edital_texto = ? WHERE id = ?",
                                    (data, trecho, audiencia_id))
                    self.db.commit()

    def _converter(self, audiencia_id: str, link, arquivo_id: int) -> str | None:
        """Texto do PDF/DOCX em parágrafos pesquisáveis. Devolve o texto convertido agora (None se ilegível
        ou se o arquivo já tinha sido convertido por esta versão do conversor)."""
        if self.db.execute("SELECT 1 FROM audiencia_texto WHERE arquivo_id = ? AND conversor = ?",
                           (arquivo_id, CONVERSOR)).fetchone():
            return None
        arq = self.db.execute("SELECT * FROM arquivo WHERE id = ?", (arquivo_id,)).fetchone()
        bruto = (self.config.pasta_dados / arq["caminho"]).read_bytes()
        if link["formato"] == "docx":
            blocos, fonte, _ = blocos_docx(bruto)
            paragrafos = [b.texto for b in blocos if b.texto]
            legivel, motivo = True, ""
            descricao = "DOCX oficial"
        else:
            extraido = extrair_pdf(bruto)
            paragrafos, fonte = extraido.paragrafos, extraido.texto
            legivel, motivo = extraido.legibilidade()
            descricao = "camada de texto do PDF oficial; divisão em parágrafos reconstruída"
        markdown = "\n\n".join(paragrafos) + "\n"
        fidelidade = verificar(fonte, markdown)
        ok = legivel and fidelidade.ok
        qualidade = (f"média: {descricao}; sem segunda fonte para conferência" if ok
                     else f"reprovada: {motivo or 'similaridade ' + str(fidelidade.similaridade)}")
        relativo = Path("convertidos") / "audiencias" / audiencia_id / f"{Path(urlsplit(link['url']).path).stem}-{arq['sha256'][:16]}.md"
        destino = self.config.pasta_dados / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        frente = {"audiencia": audiencia_id, "secao": link["secao"], "rotulo": link["rotulo"], "url_fonte": link["url"],
                  "sha256_fonte": arq["sha256"], "coletado_em": arq["coletado_em"], "conversor": CONVERSOR,
                  "qualidade": qualidade,
                  "aviso": "Conversão automática do texto oficial. Em caso de divergência, prevalece o original."}
        destino.write_text("---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in frente.items())
                           + "---\n\n" + (markdown if ok else ""), encoding="utf-8")
        cur = self.db.execute(
            "INSERT INTO audiencia_texto (link_id, arquivo_id, caminho_md, conversor, fidelidade_ok, qualidade, gerado_em) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)", (link["id"], arquivo_id, relativo.as_posix(), CONVERSOR, int(ok), qualidade, agora()))
        if ok:
            texto_id = cur.lastrowid
            self.db.executemany(
                "INSERT INTO audiencia_trecho (texto_id, audiencia_id, ordem, texto) VALUES (?, ?, ?, ?)",
                [(texto_id, audiencia_id, i, p) for i, p in enumerate(paragrafos, 1)])
            self.db.execute("INSERT INTO audiencia_trecho_fts (rowid, texto) SELECT id, texto FROM audiencia_trecho "
                            "WHERE texto_id = ?", (texto_id,))
        self.db.commit()
        return fonte if ok else None

    # ------------------------------------------------------------------ execução
    def executar(self, documentos: list[str] | None = None, refazer: bool = False, dias: int = 30,
                 ao_avancar=None) -> dict[str, int]:
        """Audiências das normas do acervo (ou de `documentos`). Retomável: pula páginas lidas há menos de
        `dias`, salvo `refazer`; arquivos já baixados não são baixados de novo."""
        documentos = documentos or [r[0] for r in self.db.execute("SELECT id FROM documento ORDER BY id")]
        auds: list[str] = []
        for doc in documentos:
            for aud in self.da_ficha(doc):
                if aud not in auds:
                    auds.append(aud)
        contagem: dict[str, int] = {"normas": len(documentos), "audiências citadas": len(auds)}
        for aud in auds:
            linha = self.db.execute(
                "SELECT status FROM audiencia WHERE id = ? AND lida_em >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
                (aud, f"-{dias} days")).fetchone()
            if linha and linha["status"] == "lida" and not refazer:
                self._baixar_e_converter(aud)  # retoma downloads interrompidos
                status = "já lida"
            else:
                status = self.ler(aud)
            contagem[status] = contagem.get(status, 0) + 1
            if ao_avancar:
                ao_avancar(aud, status)
        return contagem
