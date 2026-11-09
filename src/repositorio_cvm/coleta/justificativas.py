"""Justificativas de dispensa de Análise de Impacto Regulatório (AIR) citadas na ficha da norma (D-24).

A ficha oficial de muitas resoluções traz, ao lado de [HTML] / [PDF] / [DOC], um link "Justificativa - Dispensa
de Análise de Impacto Regulatório (AIR)". Ele aponta para:
- um PDF anexo (`.../anexos/200/resol245_Justificativa_DispensaAIR.pdf`); ou
- a página da decisão do Colegiado que aprovou a norma (`/decisoes/2025/20250708_R1/20250708_D3308.html`), cujo
  texto, no elemento <article>, registra a dispensa e o fundamento.

Como as audiências públicas, a justificativa é um documento próprio ligado à norma: a ligação vem da ficha
(evidência registrada), o arquivo é guardado como original imutável e o texto é convertido à parte. Ficha sem
o link não prova que não houve justificativa: nada é registrado nesse caso.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.coleta.coletor import Coletor, UrlProibida
from repositorio_cvm.coleta.http import FetchError
from repositorio_cvm.conversao.docx import blocos_docx
from repositorio_cvm.conversao.fidelidade import verificar
from repositorio_cvm.conversao.html import normalizar
from repositorio_cvm.conversao.pdf import extrair as extrair_pdf

log = logging.getLogger("repositorio_cvm.justificativas")

CONVERSOR = "justificativa-texto/2"
_ROTULO = re.compile(r"impacto\s+regulat[óo]rio", re.I)


def _formato(url: str) -> str | None:
    sufixo = Path(urlsplit(url).path).suffix.lower().lstrip(".")
    return {"htm": "html"}.get(sufixo, sufixo) or None


def links_da_ficha(html: bytes | str, url: str) -> list[tuple[str, str]]:
    """(rótulo, URL absoluta) de cada link de justificativa de AIR na ficha, na ordem e sem repetição."""
    sopa = BeautifulSoup(html, "lxml")
    vistos, links = set(), []
    for a in sopa.find_all("a", href=True):
        rotulo = normalizar(a.get_text(" "))
        alvo = urljoin(url, a["href"])
        if _ROTULO.search(rotulo) and alvo not in vistos:
            vistos.add(alvo)
            links.append((rotulo, alvo))
    return links


def paragrafos_da_decisao(html: bytes | str) -> list[str]:
    """Parágrafos do texto da decisão do Colegiado (elemento <article> da página); vazio se não houver."""
    artigo = BeautifulSoup(html, "lxml").find("article")
    if artigo is None:
        return []
    for lixo in artigo.find_all(["script", "style"]):
        lixo.decompose()
    # Quebra de parágrafo só nos blocos; elementos dentro da linha (chamadas de nota "(1)", negrito, links)
    # continuam na mesma frase.
    for quebra in artigo.find_all("br"):
        quebra.replace_with("\n")
    for bloco in artigo.find_all(_BLOCOS):
        bloco.insert_before("\n")
        bloco.insert_after("\n")
    linhas = (normalizar(l) for l in artigo.get_text("").split("\n"))
    return [l for l in linhas if l]


_BLOCOS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "section", "blockquote"]


class ColetorJustificativas:
    def __init__(self, coletor: Coletor):
        self.coletor = coletor
        self.db = coletor.db
        self.config = coletor.config

    def da_ficha(self, documento_id: str) -> list[int]:
        """Registra as justificativas citadas na ficha já guardada (sem acessar a rede). Devolve os ids."""
        ficha = self.db.execute(
            "SELECT * FROM arquivo WHERE documento_id = ? AND papel = 'ficha' ORDER BY coletado_em DESC, id DESC LIMIT 1",
            (documento_id,)).fetchone()
        if ficha is None:
            return []
        ids = []
        for rotulo, url in links_da_ficha((self.config.pasta_dados / ficha["caminho"]).read_bytes(), ficha["url"]):
            evid = self.coletor._evidencia(documento_id, "justificativa_air", url, ficha["url"], ficha["sha256"], rotulo)
            self.db.execute(
                "INSERT INTO justificativa (documento_id, rotulo, url, formato, evidencia_id, status) "
                "VALUES (?, ?, ?, ?, ?, 'não baixada') ON CONFLICT(documento_id, url) DO UPDATE SET "
                "rotulo = excluded.rotulo, evidencia_id = excluded.evidencia_id",
                (documento_id, rotulo, url, _formato(url), evid))
            ids.append(self.db.execute("SELECT id FROM justificativa WHERE documento_id = ? AND url = ?",
                                       (documento_id, url)).fetchone()[0])
        self.db.commit()
        return ids

    def baixar_e_converter(self, justificativa_id: int, refazer: bool = False) -> str:
        j = self.db.execute("SELECT * FROM justificativa WHERE id = ?", (justificativa_id,)).fetchone()
        if j["arquivo_id"] is None or refazer:
            try:
                artefato = self.coletor.baixar(j["url"], f"justificativa:{j['documento_id']}", j["formato"])
            except UrlProibida as erro:
                return self._status(justificativa_id, "proibida pelo robots.txt", str(erro))
            except FetchError as erro:
                return self._status(justificativa_id, "indisponível", str(erro))
            arquivo_id = self.coletor.registrar_arquivo(j["documento_id"], artefato, "justificativa", j["formato"])
            self.db.execute("UPDATE justificativa SET arquivo_id = ?, status = 'baixada', detalhe = NULL WHERE id = ?",
                            (arquivo_id, justificativa_id))
            self.db.commit()
            j = self.db.execute("SELECT * FROM justificativa WHERE id = ?", (justificativa_id,)).fetchone()
        if j["conversor"] != CONVERSOR or refazer:
            self._converter(j)
        return "baixada"

    def _status(self, justificativa_id: int, status: str, detalhe: str) -> str:
        log.warning("justificativa %s: %s (%s)", justificativa_id, status, detalhe)
        self.db.execute("UPDATE justificativa SET status = ?, detalhe = ? WHERE id = ?", (status, detalhe, justificativa_id))
        self.db.commit()
        return status

    def _converter(self, j) -> None:
        arq = self.db.execute("SELECT * FROM arquivo WHERE id = ?", (j["arquivo_id"],)).fetchone()
        bruto = (self.config.pasta_dados / arq["caminho"]).read_bytes()
        if j["formato"] == "html":
            paragrafos = paragrafos_da_decisao(bruto)
            fonte = " ".join(paragrafos)
            legivel, motivo = (bool(paragrafos), "página sem o texto da decisão (<article>)")
            descricao = "texto da decisão do Colegiado (página oficial)"
        elif j["formato"] == "docx":
            blocos, fonte, _ = blocos_docx(bruto)
            paragrafos = [b.texto for b in blocos if b.texto]
            legivel, motivo, descricao = True, "", "DOCX oficial"
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
        relativo = (Path("convertidos") / "justificativas" / j["documento_id"]
                    / f"{Path(urlsplit(j['url']).path).stem}-{arq['sha256'][:16]}.md")
        destino = self.config.pasta_dados / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        frente = {"documento": j["documento_id"], "rotulo": j["rotulo"], "url_fonte": j["url"],
                  "sha256_fonte": arq["sha256"], "coletado_em": arq["coletado_em"], "conversor": CONVERSOR,
                  "qualidade": qualidade,
                  "aviso": "Conversão automática do texto oficial. Em caso de divergência, prevalece o original."}
        destino.write_text("---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in frente.items())
                           + "---\n\n" + (markdown if ok else ""), encoding="utf-8")
        self.db.execute("UPDATE justificativa SET caminho_md = ?, conversor = ?, fidelidade_ok = ?, qualidade = ?, "
                        "convertida_em = ? WHERE id = ?",
                        (relativo.as_posix(), CONVERSOR, int(ok), qualidade, agora(), j["id"]))
        self.db.commit()

    def executar(self, documentos: list[str] | None = None, refazer: bool = False, ao_avancar=None) -> dict[str, int]:
        """Justificativas das normas do acervo (ou de `documentos`). Retomável: o que já foi baixado e convertido
        por esta versão do conversor não é refeito, salvo `refazer`."""
        documentos = documentos or [r[0] for r in self.db.execute("SELECT id FROM documento ORDER BY id")]
        ids = [i for doc in documentos for i in self.da_ficha(doc)]
        contagem: dict[str, int] = {"normas": len(documentos), "justificativas citadas": len(ids)}
        for jid in ids:
            j = self.db.execute("SELECT * FROM justificativa WHERE id = ?", (jid,)).fetchone()
            if j["arquivo_id"] is not None and j["conversor"] == CONVERSOR and not refazer:
                status = "já baixada"
            else:
                status = self.baixar_e_converter(jid, refazer)
            contagem[status] = contagem.get(status, 0) + 1
            if ao_avancar:
                ao_avancar(j["documento_id"], status)
        return contagem
