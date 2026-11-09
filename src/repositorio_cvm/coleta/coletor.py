"""Coleta de atos: ficha oficial -> metadados com evidência -> íntegra HTML -> Markdown e dispositivos.

Regras aplicadas:
- todo arquivo baixado é guardado como original imutável (por hash) e registrado em `arquivo`;
- cada metadado gravado em `documento` tem uma linha em `evidencia` (URL, hash e trecho);
- nesta etapa (D-08) só a íntegra em HTML é baixada e convertida; PDF/DOC ficam anotados em
  `link_documento` e o documento fica "pendente: sem íntegra HTML";
- bloqueio (401/403/429 ou robots.txt) interrompe a coleta inteira, sem insistir;
- a situação normativa segue D-09 (marcações oficiais da ficha e cláusula de vigência).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from repositorio_cvm.armazenamento import originais
from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.coleta.catalogo import ItemCatalogo, ler_pagina_catalogo, url_catalogo
from repositorio_cvm.coleta.ficha import _norma_do_nome, Ficha, ler_ficha
from repositorio_cvm.coleta.http import BlockedError, FetchError, PoliteClient, ProibidoPeloRobotsError
from repositorio_cvm.config import Config
from repositorio_cvm.conversao.docx import CONVERSOR as CONVERSOR_DOCX, blocos_docx, cabecalhos_docx
from repositorio_cvm.conversao.fidelidade import (ResultadoCruzado, cobertura_ementa, conferir_com_pdf,
                                                  palavras, verificar)
from repositorio_cvm.conversao.html import CONVERSOR, Bloco, Conversao, converter_html, estruturar
from repositorio_cvm.conversao.pdf import CONVERSOR as CONVERSOR_PDF, CONVERSOR_OCR, caminho_tessdata
from repositorio_cvm.conversao.pdf import extrair as extrair_pdf
from repositorio_cvm.conversao import type3
from repositorio_cvm.gabarito import AtoGabarito, identificar_oficio, oficio_corresponde
from repositorio_cvm.modelos import Artifact

log = logging.getLogger("repositorio_cvm.coleta")
LIMIAR_EMENTA_OCR = 0.75  # D-12
_NORMA_CITADA = re.compile(r"\b(Resolução|Instrução)\s+CVM\s+n[º°o]?\s*([\d.]+)", re.I)
_FICHA_POR_ESPECIE = {"resol": ("resolucoes", "resol"), "instr": ("instrucoes", "inst")}


class ColetaInterrompida(Exception):
    """Bloqueio de acesso: a coleta para e registra, em vez de insistir."""


class UrlProibida(ColetaInterrompida):
    """O `robots.txt` proíbe uma URL específica (ex.: a Deliberação 233, desindexada por processo SEI). A coleta
    do catálogo pula o ato e segue; os outros comandos param, como em qualquer bloqueio."""


@dataclass
class Resultado:
    chave: str
    status: str
    detalhe: str = ""


def _versao_em_ingles(arquivo: sqlite3.Row, nomes: set[tuple[str, str, str]]) -> bool:
    nome = Path(arquivo["url"]).stem.lower()
    m = re.fullmatch(r"(.+?)[_-]?(?:en|eng|english|ingles)", nome)
    return bool(m) and (arquivo["papel"], arquivo["formato"], m.group(1)) in nomes


class Coletor:
    def __init__(self, config: Config, conexao: sqlite3.Connection, cliente: PoliteClient, hoje: date | None = None):
        self.config = config
        self.db = conexao
        self.cliente = cliente
        self.hoje = hoje or date.today()
        self.coleta_id: int | None = None

    # ------------------------------------------------------------------ registro da execução
    def iniciar(self, escopo: str) -> int:
        cur = self.db.execute("INSERT INTO coleta (escopo, iniciada_em, status) VALUES (?, ?, 'em andamento')",
                              (escopo, agora()))
        self.db.commit()
        self.coleta_id = cur.lastrowid
        return self.coleta_id

    def encerrar(self, status: str, resumo: dict) -> None:
        self.db.execute("UPDATE coleta SET terminada_em = ?, status = ?, resumo = ? WHERE id = ?",
                        (agora(), status, json.dumps(resumo, ensure_ascii=False), self.coleta_id))
        self.db.commit()

    def _tentativa(self, chave: str | None, url: str, resultado: str, detalhe: str = "") -> None:
        self.db.execute("INSERT INTO tentativa (coleta_id, chave, url, resultado, detalhe, em) VALUES (?, ?, ?, ?, ?, ?)",
                        (self.coleta_id, chave, url, resultado, detalhe, agora()))
        self.db.commit()

    # ------------------------------------------------------------------ download
    def baixar(self, url: str, chave: str | None, formato: str | None = None) -> Artifact:
        """`formato` (html, pdf, docx...): o cliente recusa conteúdo de outro tipo (ex.: página de erro)."""
        try:
            artefato = self.cliente.fetch(url, esperado=formato)
        except ProibidoPeloRobotsError as erro:
            self._tentativa(chave, url, "proibido pelo robots.txt", str(erro))
            raise UrlProibida(f"{url}: {erro}") from erro
        except BlockedError as erro:
            self._tentativa(chave, url, "bloqueado", str(erro))
            raise ColetaInterrompida(f"acesso bloqueado em {url}: {erro}") from erro
        except FetchError as erro:
            self._tentativa(chave, url, "erro", str(erro))
            raise
        self._tentativa(chave, url, "ok", artefato.sha256)
        return artefato

    def registrar_arquivo(self, documento_id: str | None, artefato: Artifact, papel: str, formato: str | None,
                          origem: str = "coleta direta") -> int:
        """`documento_id` None: arquivo que não é de uma norma (ex.: edital de audiência pública)."""
        sha, relativo = originais.gravar(self.config.pasta_dados, artefato.bytes, artefato.content_type, artefato.url)
        linha = self.db.execute("SELECT id FROM arquivo WHERE documento_id IS ? AND url = ? AND sha256 = ?",
                                (documento_id, artefato.url, sha)).fetchone()
        if linha:
            return linha["id"]
        cur = self.db.execute(
            """INSERT INTO arquivo (documento_id, sha256, url, papel, formato, content_type, tamanho, caminho, etag,
                                    last_modified, coletado_em, origem_coleta)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (documento_id, sha, artefato.url, papel, formato, artefato.content_type, len(artefato.bytes),
             relativo.as_posix(), artefato.etag, artefato.last_modified, artefato.fetched_at, origem),
        )
        return cur.lastrowid

    # ------------------------------------------------------------------ localização
    def localizar_oficios(self, atos: list[AtoGabarito], max_paginas: int = 25) -> dict[str, ItemCatalogo]:
        """Percorre a pesquisa de ofícios-circulares (mais recentes primeiro) até achar todos os alvos."""
        alvos = [a for a in atos if a.especie == "oficio_circular" and not a.ficha]
        achados: dict[str, ItemCatalogo] = {}
        if not alvos:
            return achados
        ano_minimo = min(a.ano for a in alvos if a.ano)
        for pagina in range(1, max_paginas + 1):
            url = url_catalogo("oficio_circular", pagina)
            artefato = self.baixar(url, "catalogo:oficio_circular", "html")
            resultado = ler_pagina_catalogo(artefato.bytes, url)
            for item in resultado.itens:
                for ato in alvos:
                    if ato.chave not in achados and oficio_corresponde(ato, item.titulo):
                        achados[ato.chave] = item
                        log.info("localizado %s -> %s (%s)", ato.chave, item.titulo, item.url)
            if len(achados) == len(alvos):
                break
            datas = [i.data for i in resultado.itens if i.data]
            if datas and max(datas) < f"{ano_minimo}-01-01":
                break
            if resultado.total_paginas and pagina >= resultado.total_paginas:
                break
        self._paginas_consultadas_oficios = pagina
        return achados

    # ------------------------------------------------------------------ ato
    def coletar_ato(self, ato: AtoGabarito, item: ItemCatalogo | None = None,
                    artefato_ficha: Artifact | None = None) -> Resultado:
        """`artefato_ficha`: ficha já baixada (atualização incremental), para não repetir a requisição."""
        url_ficha = ato.ficha or (item.url if item else None)
        if url_ficha is None:
            paginas = getattr(self, "_paginas_consultadas_oficios", 0)
            self._lacuna(ato.chave, "não localizado",
                         f"não encontrado nas {paginas} primeiras páginas da pesquisa de ofícios-circulares",
                         fontes=url_catalogo("oficio_circular", 1))
            return Resultado(ato.chave, "não localizado")
        try:
            artefato = artefato_ficha or self.baixar(url_ficha, ato.chave, "html")
        except FetchError as erro:
            classificacao = "não localizado" if erro.status in (404, 410) and ato.ficha else "indisponível para download"
            self._lacuna(ato.chave, classificacao, "ficha oficial não obtida", url=url_ficha, erro=str(erro),
                         fontes=url_ficha)
            return Resultado(ato.chave, classificacao, str(erro))

        ficha = ler_ficha(artefato.bytes, artefato.url)
        if not ficha.titulo:
            self._lacuna(ato.chave, "indisponível para download", "página sem ficha reconhecível", url=url_ficha,
                         fontes=url_ficha)
            return Resultado(ato.chave, "indisponível para download", "ficha não reconhecida")

        self._garantir_documento(ato, ficha)
        arquivo_ficha = self.registrar_arquivo(ato.chave, artefato, "ficha", "html")
        self._metadados_da_ficha(ato, ficha, artefato)
        self._links(ato.chave, ficha)

        conversao: Conversao | None = None
        integra = ficha.integra_html
        status, motivo = "pendente", None
        if integra is None:
            disponiveis = sorted({l.formato for l in ficha.links if l.formato and l.papel in ("integra", "original", "consolidado")})
            motivo = "sem íntegra HTML" + (f" (disponível: {', '.join(disponiveis)})" if disponiveis else "")
        else:
            try:
                art_integra = self.baixar(integra.url, ato.chave, "html")
            except FetchError as erro:
                self._lacuna(ato.chave, "indisponível para download", "íntegra HTML indicada na ficha não obtida",
                             url=integra.url, erro=str(erro), fontes=url_ficha)
                motivo = f"íntegra HTML indisponível ({erro})"
            else:
                arquivo_integra = self.registrar_arquivo(ato.chave, art_integra, "integra", "html")
                self.db.execute("UPDATE link_documento SET baixado = 1 WHERE documento_id = ? AND url = ?",
                                (ato.chave, integra.url))
                conversao = converter_html(art_integra.bytes)
                ok = self._registrar_conversao(ato, ficha, art_integra, arquivo_integra, conversao)
                status = "coletado" if ok else "pendente"
                motivo = None if ok else "conversão reprovada na verificação de fidelidade"
                self._vigencia(ato, ficha, art_integra, conversao)

        self._situacao(ato, ficha, artefato)
        self.db.execute(
            "UPDATE documento SET status_coleta = ?, motivo_pendencia = ?, atualizado_em = ?, ultima_verificacao = ? WHERE id = ?",
            (status, motivo, agora(), agora(), ato.chave),
        )
        self.db.commit()
        return Resultado(ato.chave, status, motivo or "")

    # ------------------------------------------------------------------ arquivos PDF/DOCX
    PAPEIS_TEXTO = ("integra", "original", "consolidado")
    FORMATOS_TEXTO = ("pdf", "docx")

    def baixar_arquivos(self, documento_id: str, papeis: tuple[str, ...] = PAPEIS_TEXTO) -> list[Resultado]:
        """Baixa os PDF/DOCX de texto (íntegra, original, consolidado) anotados na ficha e ainda não baixados.

        Anexos e partes separadas (ex.: Res. 175 por anexo) e arquivos complementares (justificativas)
        ficam para depois: o texto consolidado completo já os contém. `.doc` binário não é baixado
        porque ainda não há conversor para ele (D-11).
        """
        resultados = []
        links = self.db.execute(
            f"SELECT url, formato, papel FROM link_documento WHERE documento_id = ? AND baixado = 0 "
            f"AND papel IN ({','.join('?' * len(papeis))}) "
            f"AND formato IN ({','.join('?' * len(self.FORMATOS_TEXTO))}) ORDER BY id",
            (documento_id, *papeis, *self.FORMATOS_TEXTO),
        ).fetchall()
        for link in links:
            ja = self.db.execute("SELECT 1 FROM arquivo WHERE documento_id = ? AND url = ?",
                                 (documento_id, link["url"])).fetchone()
            if not ja:
                try:
                    artefato = self.baixar(link["url"], documento_id, link["formato"])
                except FetchError as erro:
                    self._lacuna(documento_id, "indisponível para download", f"{link['papel']}/{link['formato']} indicado na ficha",
                                 url=link["url"], erro=str(erro), fontes=link["url"])
                    resultados.append(Resultado(documento_id, "erro", f"{link['url']}: {erro}"))
                    continue
                self.registrar_arquivo(documento_id, artefato, link["papel"], link["formato"])
            self.db.execute("UPDATE link_documento SET baixado = 1 WHERE documento_id = ? AND url = ?",
                            (documento_id, link["url"]))
            self.db.commit()
            resultados.append(Resultado(documento_id, "ok", link["url"]))
        return resultados

    # ------------------------------------------------------------------ auxiliares de gravação
    def _garantir_documento(self, ato: AtoGabarito, ficha: Ficha) -> None:
        if self.db.execute("SELECT 1 FROM documento WHERE id = ?", (ato.chave,)).fetchone():
            return
        self.db.execute(
            "INSERT INTO documento (id, especie, status_coleta, criado_em, atualizado_em, url_oficial) VALUES (?, ?, 'pendente', ?, ?, ?)",
            (ato.chave, ato.especie, agora(), agora(), ficha.url),
        )

    def _evidencia(self, documento_id: str, campo: str, valor, url: str, sha: str | None, trecho: str | None) -> int:
        valor_txt = None if valor is None else str(valor)
        linha = self.db.execute(
            "SELECT id FROM evidencia WHERE documento_id = ? AND campo = ? AND valor IS ? AND sha256 IS ? AND trecho IS ?",
            (documento_id, campo, valor_txt, sha, trecho),
        ).fetchone()
        if linha:
            return linha["id"]
        cur = self.db.execute(
            "INSERT INTO evidencia (documento_id, campo, valor, url, sha256, trecho, registrado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (documento_id, campo, valor_txt, url, sha, trecho, agora()),
        )
        return cur.lastrowid

    def _definir(self, documento_id: str, campo: str, valor, url: str, sha: str | None, trecho: str | None) -> None:
        if valor is None:
            return
        self.db.execute(f"UPDATE documento SET {campo} = ? WHERE id = ?", (valor, documento_id))
        self._evidencia(documento_id, campo, valor, url, sha, trecho)

    def _metadados_da_ficha(self, ato: AtoGabarito, ficha: Ficha, artefato: Artifact) -> None:
        doc, url, sha = ato.chave, artefato.url, artefato.sha256
        self._definir(doc, "titulo", ficha.titulo, url, sha, ficha.trechos.get("titulo"))
        numero = None
        if ato.especie == "oficio_circular":
            ident = identificar_oficio(ficha.titulo or "")
            numero = None if ident.anual else (str(ident.numero) if ident.numero else None)
            if ident.areas:
                self._definir(doc, "area_tecnica", "/".join(sorted(ident.areas)), url, sha, ficha.titulo)
        elif ato.especie != "nota_explicativa" and ficha.titulo:
            m = re.search(r"\b0*(\d+)\s*$", ficha.titulo.replace("(Revogada)", "").strip())
            numero = m.group(1) if m else None
        self._definir(doc, "numero", numero, url, sha, ficha.titulo)
        self._definir(doc, "data_edicao", ficha.data_edicao, url, sha, ficha.trechos.get("data_edicao"))
        if ficha.data_edicao:
            self._definir(doc, "ano", int(ficha.data_edicao[:4]), url, sha, ficha.trechos.get("data_edicao"))
        self._definir(doc, "ementa", ficha.ementa, url, sha, ficha.trechos.get("ementa"))
        if ficha.assuntos:
            self._definir(doc, "assunto", "; ".join(ficha.assuntos), url, sha, ficha.trechos.get("assuntos"))
        publicacao = next((e for e in ficha.eventos if e.evento == "publicacao" and e.veiculo.upper() == "DOU"), None)
        if publicacao:
            self._definir(doc, "data_publicacao", publicacao.data, url, sha, publicacao.trecho)
        for evento in ficha.eventos:
            if evento is not publicacao:
                self._evidencia(doc, f"evento_{evento.evento}", evento.data, url, sha, evento.trecho)
        self._definir(doc, "url_oficial", ficha.url, url, sha, "URL da ficha oficial do ato")
        for rel in ficha.relacoes:
            evid = self._evidencia(doc, f"relacao_{rel.tipo}", rel.alvo_url, url, sha, rel.trecho)
            self.db.execute(
                "INSERT OR IGNORE INTO relacao (documento_id, tipo, alvo_titulo, alvo_url, evidencia_id) VALUES (?, ?, ?, ?, ?)",
                (doc, rel.tipo, rel.alvo_titulo, rel.alvo_url, evid),
            )

    def _links(self, documento_id: str, ficha: Ficha) -> None:
        for link in ficha.links:
            self.db.execute(
                "INSERT OR IGNORE INTO link_documento (documento_id, rotulo, url, formato, papel) VALUES (?, ?, ?, ?, ?)",
                (documento_id, link.rotulo, link.url, link.formato, link.papel),
            )

    def _registrar_conversao(self, ato: AtoGabarito, ficha: Ficha, artefato: Artifact, arquivo_id: int,
                             conversao: Conversao) -> bool:
        return self._gravar_versao(ato.chave, ficha.titulo, ficha.url, artefato.url, artefato.sha256,
                                   artefato.fetched_at, arquivo_id, conversao, CONVERSOR, "texto original",
                                   "íntegra HTML oficial")

    def _gravar_versao(self, documento_id: str, titulo: str | None, url_ficha: str | None, url_fonte: str,
                       sha: str, coletado_em: str, arquivo_id: int, conversao: Conversao, conversor: str,
                       tipo: str, descricao_fonte: str, cruzada: ResultadoCruzado | None = None) -> bool:
        """Grava Markdown, versão de texto e dispositivos. Idempotente por (arquivo, conversor).

        Aprovação: todas as palavras do original no Markdown e, quando há segundo arquivo oficial (PDF),
        conferência cruzada consistente (D-11).
        """
        existente = self.db.execute("SELECT fidelidade_ok FROM versao_texto WHERE arquivo_id = ? AND conversor = ?",
                                    (arquivo_id, conversor)).fetchone()
        if existente:
            return bool(existente["fidelidade_ok"])
        fidelidade = verificar(conversao.texto_fonte, conversao.markdown)
        ok = fidelidade.ok and (cruzada is None or cruzada.consistente)
        if ok:
            qualidade = f"alta: {descricao_fonte}; todas as palavras do original estão no Markdown"
            if cruzada:
                qualidade += (f"; conferido com o PDF oficial (cobertura {cruzada.cobertura_markdown_no_pdf:.2%}"
                              f" / {cruzada.cobertura_pdf_no_markdown:.2%})")
            elif conversor.startswith("pdf-type3"):
                qualidade = (f"média: {descricao_fonte}; cada letra foi traduzida da fonte do arquivo, sem erros "
                             "pontuais de OCR; conferir apenas os caracteres marcados com □")
            elif conversor.startswith("pdf-ocr"):
                qualidade = (f"baixa: {descricao_fonte}; texto reconhecido por OCR, sem segunda fonte oficial; "
                             "conferência manual obrigatória antes de citar")
            elif conversor.startswith("pdf"):
                qualidade = (f"média: {descricao_fonte}; camada de texto do PDF, sem segunda fonte oficial "
                             "para conferência; divisão em parágrafos reconstruída")
        elif not fidelidade.ok:
            qualidade = f"reprovada: similaridade {fidelidade.similaridade} com o original"
        else:
            qualidade = (f"revisar: diverge do PDF oficial (cobertura {cruzada.cobertura_markdown_no_pdf:.2%}"
                         f" / {cruzada.cobertura_pdf_no_markdown:.2%})")
        if conversao.avisos:
            qualidade += "; avisos: " + "; ".join(conversao.avisos)
        sufixo = "consolidado" if "consolidado" in tipo else "original"
        relativo = Path("convertidos") / documento_id / f"{sufixo}-{sha[:16]}.md"
        destino = self.config.pasta_dados / relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        cabecalho = {
            "id": documento_id,
            "titulo": titulo,
            "versao_texto": tipo + (" (não é texto consolidado)" if tipo == "texto original" else ""),
            "url_ficha": url_ficha,
            "url_fonte": url_fonte,
            "sha256_fonte": sha,
            "coletado_em": coletado_em,
            "conversor": conversor,
            "fidelidade": "aprovada" if ok else qualidade,
            "aviso": "Conversão automática do texto oficial. Em caso de divergência, prevalece o original.",
        }
        frente = "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in cabecalho.items()) + "---\n\n"
        destino.write_text(frente + conversao.markdown, encoding="utf-8")
        cur = self.db.execute(
            """INSERT INTO versao_texto (documento_id, arquivo_id, tipo, caminho_md, conversor, fidelidade_ok,
                                         fidelidade_detalhe, qualidade, gerado_em, conferencia_cruzada)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (documento_id, arquivo_id, tipo, relativo.as_posix(), conversor, int(ok),
             json.dumps(fidelidade.__dict__, ensure_ascii=False), qualidade, agora(),
             json.dumps(cruzada.__dict__, ensure_ascii=False) if cruzada else None),
        )
        versao_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO dispositivo (versao_id, documento_id, ordem, tipo, artigo, rotulo, texto, parte) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(versao_id, documento_id, d.ordem, d.tipo, d.artigo, d.rotulo, d.texto, d.parte)
             for d in conversao.dispositivos],
        )
        self.db.execute(
            "INSERT INTO dispositivo_fts (rowid, texto, rotulo) SELECT id, texto, rotulo FROM dispositivo WHERE versao_id = ?",
            (versao_id,),
        )
        return ok

    # ------------------------------------------------------------------ conversão de PDF/DOCX
    def converter_arquivos(self, documento_id: str) -> list[Resultado]:
        """Converte a íntegra/original e o consolidado a partir dos arquivos já baixados (D-11).

        Para cada papel, a fonte é o DOCX oficial (conferido contra o PDF do mesmo papel) ou, sem DOCX,
        o PDF. Atos com íntegra HTML já convertida não são reconvertidos a partir do PDF/DOCX.
        """
        doc = self.db.execute("SELECT * FROM documento WHERE id = ?", (documento_id,)).fetchone()
        if doc is None:
            return []
        resultados: list[Resultado] = []
        arquivos = self.db.execute(
            "SELECT * FROM arquivo WHERE documento_id = ? AND papel IN ('integra', 'original', 'consolidado') "
            "AND formato IN ('docx', 'pdf', 'html') ORDER BY id", (documento_id,)).fetchall()
        # Arquivo cujo nome identifica outra norma (ex.: alteradora citada na ficha) não é texto desta.
        propria = _norma_do_nome(doc["url_oficial"] or "")
        arquivos = [a for a in arquivos if not (propria and (outra := _norma_do_nome(a["url"])) and outra != propria)]
        # Versão em inglês publicada ao lado da íntegra (ex.: deli339en.pdf junto de deli339.pdf) não é o texto
        # oficial do ato: fica de fora quando existe o arquivo de mesmo nome sem o sufixo "en".
        nomes = {(a["papel"], a["formato"], Path(a["url"]).stem.lower()) for a in arquivos}
        arquivos = [a for a in arquivos if not _versao_em_ingles(a, nomes)]
        por_papel: dict[str, dict[str, sqlite3.Row]] = {}
        for a in arquivos:
            por_papel.setdefault(a["papel"], {})[a["formato"]] = a
        # Mais de um PDF no mesmo papel (ex.: Res. 181, íntegra e "Sumário Executivo"): a conferência do DOCX
        # usa o PDF do mesmo nome (o mais recente, se houver nova versão).
        for papel, formatos in por_papel.items():
            if "docx" in formatos and "pdf" in formatos:
                nome = Path(formatos["docx"]["url"]).stem.lower()
                mesmo = [a for a in arquivos if a["papel"] == papel and a["formato"] == "pdf"
                         and Path(a["url"]).stem.lower() == nome]
                if mesmo:
                    formatos["pdf"] = mesmo[-1]
        if "html" in por_papel.get("integra", {}):
            # Íntegra HTML é a fonte preferida: (re)converte com a versão atual do conversor e encerra.
            fonte = por_papel["integra"]["html"]
            conversao = converter_html((self.config.pasta_dados / fonte["caminho"]).read_bytes())
            ok = self._gravar_versao(documento_id, doc["titulo"], doc["url_oficial"], fonte["url"], fonte["sha256"],
                                     fonte["coletado_em"], fonte["id"], conversao, CONVERSOR, "texto original",
                                     "íntegra HTML oficial")
            resultados.append(Resultado(documento_id, "ok" if ok else "revisar", f"texto original via {CONVERSOR}"))
            self.db.commit()
            outros = {f for f in por_papel["integra"] if f != "html"}
            if ok or not outros:
                return resultados
            # D-22: HTML reprovado (ex.: Res. 217, tabela aninhada repetida); segue para o DOCX/PDF da íntegra.
            del por_papel["integra"]["html"]

        def ler(a: sqlite3.Row) -> bytes:
            return (self.config.pasta_dados / a["caminho"]).read_bytes()

        conversao_original: tuple[Conversao, sqlite3.Row] | None = None
        conversao_consolidada: tuple[Conversao, sqlite3.Row] | None = None
        pendencias: list[str] = []
        # Conferência do OCR: as palavras da ementa da ficha devem estar no texto (D-12). Ficha sem ementa
        # (ex.: Ofício-Circular SNC/GNA 01/18): confere-se o título do ato, que o documento traz no cabeçalho.
        referencia = doc["ementa"] or doc["titulo"]
        nome_referencia = "da ementa da ficha" if doc["ementa"] else "do título do ato (ficha sem ementa)"
        for papel, formatos in por_papel.items():
            tipo = "texto consolidado oficial" if papel == "consolidado" else "texto original"
            if "docx" in formatos:
                fonte = formatos["docx"]
                bruto = ler(fonte)
                blocos, texto_fonte, avisos = blocos_docx(bruto)
                conversao = estruturar(blocos, texto_fonte, estilo_citacao=(papel != "consolidado"))
                conversao.avisos = list(dict.fromkeys(avisos + conversao.avisos))
                cruzada = None
                if "pdf" in formatos:
                    texto_pdf = extrair_pdf(ler(formatos["pdf"]), cabecalhos_docx(bruto)).texto
                    cruzada = conferir_com_pdf(conversao.markdown, texto_pdf)
                conversor, descricao = CONVERSOR_DOCX, "DOCX oficial"
            elif "pdf" in formatos:
                fonte = formatos["pdf"]
                texto = extrair_pdf(ler(fonte))
                legivel, motivo = texto.legibilidade()
                conversor, descricao, ementa_ocr = CONVERSOR_PDF, "PDF oficial", None
                if not legivel:
                    # Não gera Markdown a partir de texto ilegível; versões anteriores desse arquivo
                    # (geradas antes desta verificação) são marcadas como reprovadas.
                    self.db.execute("UPDATE versao_texto SET fidelidade_ok = 0, qualidade = ? "
                                    "WHERE arquivo_id = ? AND conversor NOT LIKE 'pdf-ocr%'",
                                    (f"reprovada: {motivo}", fonte["id"]))
                    self._evidencia(documento_id, "qualidade_extracao", motivo, fonte["url"], fonte["sha256"], motivo)
                    tessdata = caminho_tessdata(self.config.tessdata)
                    if tessdata is None:
                        pendencias.append(motivo)
                        resultados.append(Resultado(documento_id, "ilegível", f"{tipo}: {motivo}"))
                        continue
                    decifrado = self._decifrar_type3(documento_id, ler(fonte), tessdata)
                    if decifrado is not None:
                        texto, dec = decifrado
                        conversor = type3.CONVERSOR
                        descricao = "texto decifrado da fonte Type3 do PDF oficial (OCR usado só para identificar as letras)"
                        ementa_ocr = cobertura_ementa(referencia, texto.texto)
                        aviso_t3 = (f"{dec.incertas} de {dec.ocorrencias} caracteres não identificados, marcados com "
                                    f"□ ({dec.fracao_incerta:.1%}); {dec.resolvidos_pelo_lexico} resolvidos pelo léxico "
                                    f"do acervo e {dec.resolvidos_pelo_dicionario} pelo dicionário de glifos")
                    else:
                        # D-12: OCR do PDF oficial. Sem segunda fonte; confere-se ao menos a ementa da ficha.
                        texto = extrair_pdf(ler(fonte), tessdata=tessdata)
                        legivel, motivo_ocr = texto.legibilidade()
                        if not legivel:
                            pendencias.append(f"OCR sem resultado legível: {motivo_ocr}")
                            resultados.append(Resultado(documento_id, "ilegível", f"{tipo}: OCR sem resultado legível"))
                            continue
                        conversor, descricao = CONVERSOR_OCR, "OCR (Tesseract, modelo por) do PDF oficial"
                        ementa_ocr = cobertura_ementa(referencia, texto.texto)
                        aviso_t3 = None
                conversao = estruturar([Bloco(p) for p in texto.paragrafos], texto.texto,
                                       estilo_citacao=(papel != "consolidado"))
                conversao.avisos = ["divisão em parágrafos reconstruída a partir do PDF"] + conversao.avisos
                if ementa_ocr is not None:
                    ausentes = sorted(set(p.lower() for p in palavras(referencia or ""))
                                      - set(p.lower() for p in palavras(texto.texto)))
                    inicio = (aviso_t3 if conversor == type3.CONVERSOR else
                              "texto obtido por OCR: erros de reconhecimento são esperados (nomes, e-mails, "
                              "tabelas); conferência manual obrigatória")
                    conversao.avisos.insert(0, f"{inicio}; {ementa_ocr:.0%} das palavras {nome_referencia} "
                                               f"encontradas no texto"
                                               + (f" (ausentes: {', '.join(ausentes)})" if ausentes else ""))
                if texto.paginas_sem_texto:
                    conversao.avisos.append(f"páginas sem camada de texto (exigem OCR): {texto.paginas_sem_texto}")
                cruzada = None
                # A ementa da ficha pode parafrasear o documento ("Esclarecimento sobre... CRIs" x "CRI"); a
                # checagem serve para detectar texto ilegível ou documento trocado, daí o mínimo de 75% (D-12).
                if ementa_ocr is not None and ementa_ocr < LIMIAR_EMENTA_OCR:
                    conversao.avisos.append(f"palavras {nome_referencia} não encontradas no texto do OCR; versão não aprovada")
                    conversao.texto_fonte = ""  # força reprovação na verificação de fidelidade
            else:
                continue
            ok = self._gravar_versao(documento_id, doc["titulo"], doc["url_oficial"], fonte["url"], fonte["sha256"],
                                     fonte["coletado_em"], fonte["id"], conversao, conversor, tipo, descricao, cruzada)
            if not ok and conversor == CONVERSOR_DOCX and "pdf" in formatos:
                # D-22: DOCX que diverge do PDF do mesmo texto (diagramas, caixas de texto, numeração automática):
                # o texto vem do PDF, com qualidade "média", como nos atos que só têm PDF. A versão do DOCX fica
                # registrada como "revisar".
                pdf = formatos["pdf"]
                texto = extrair_pdf(ler(pdf), cabecalhos_docx(ler(fonte)))
                if texto.legibilidade()[0]:
                    conv_pdf = estruturar([Bloco(p) for p in texto.paragrafos], texto.texto,
                                          estilo_citacao=(papel != "consolidado"))
                    motivo_docx = (f"o DOCX oficial divergiu do PDF na conferência cruzada (cobertura "
                                   f"{cruzada.cobertura_markdown_no_pdf:.2%} / {cruzada.cobertura_pdf_no_markdown:.2%})"
                                   if cruzada else "a conversão do DOCX oficial foi reprovada")
                    conv_pdf.avisos = [f"{motivo_docx}; texto obtido do PDF",
                                       "divisão em parágrafos reconstruída a partir do PDF"] + conv_pdf.avisos
                    if self._gravar_versao(documento_id, doc["titulo"], doc["url_oficial"], pdf["url"], pdf["sha256"],
                                           pdf["coletado_em"], pdf["id"], conv_pdf, CONVERSOR_PDF, tipo, "PDF oficial"):
                        fonte, conversao, conversor, ok = pdf, conv_pdf, CONVERSOR_PDF, True
            resultados.append(Resultado(documento_id, "ok" if ok else "revisar", f"{tipo} via {conversor}"))
            if papel == "consolidado":
                conversao_consolidada = (conversao, fonte)
                self._relacoes_das_notas(documento_id, conversao, fonte)
            else:
                conversao_original = (conversao, fonte)
        aprovadas = self.db.execute("SELECT COUNT(*) FROM versao_texto WHERE documento_id = ? AND fidelidade_ok = 1",
                                    (documento_id,)).fetchone()[0]
        if aprovadas:
            self.db.execute("UPDATE documento SET status_coleta = 'coletado', motivo_pendencia = NULL, atualizado_em = ? "
                            "WHERE id = ?", (agora(), documento_id))
        elif resultados:
            self.db.execute("UPDATE documento SET status_coleta = 'pendente', motivo_pendencia = ?, atualizado_em = ? "
                            "WHERE id = ?",
                            ("; ".join(pendencias) or "conversão de PDF/DOCX a revisar", agora(), documento_id))
        # Vigência: prefere-se o texto consolidado oficial, em que a redação anterior da cláusula (tachada) já
        # foi descartada; na falta dele, a redação original. Se o consolidado ainda trouxer mais de uma
        # cláusula vigente, nenhuma data é preenchida automaticamente e os trechos ficam como evidência.
        sucessivas = conversao_consolidada and any("mais de uma cláusula de vigência" in a
                                                   for a in conversao_consolidada[0].avisos)
        if sucessivas:
            consolidada, fonte_cons = conversao_consolidada
            trecho = ("redações sucessivas da cláusula de vigência no texto consolidado oficial: "
                      + consolidada.vigencia_trecho)
            self._evidencia(documento_id, "vigencia_clausula", None, fonte_cons["url"], fonte_cons["sha256"], trecho)
            if doc["data_inicio_vigencia"] is not None:
                # Correção de valor gravado antes desta regra: a evidência registra o motivo.
                self.db.execute("UPDATE documento SET data_inicio_vigencia = NULL WHERE id = ?", (documento_id,))
                self._evidencia(documento_id, "data_inicio_vigencia", None, fonte_cons["url"], fonte_cons["sha256"],
                                "removida a data tirada da redação original: " + trecho)
        else:
            escolhida = (conversao_consolidada if conversao_consolidada and conversao_consolidada[0].vigencia_trecho
                         else conversao_original)
            if escolhida and escolhida[0].vigencia_trecho:
                self._vigencia_de_arquivo(documento_id, doc, escolhida[0], escolhida[1])
        self.db.commit()
        return resultados

    LIMIAR_INCERTOS_TYPE3 = 0.10

    def _lexico(self) -> set[str]:
        """Palavras dos textos oficiais já convertidos (HTML, DOCX e PDF com camada de texto)."""
        if getattr(self, "_lexico_cache", None) is None:
            self._lexico_cache = set()
            for (texto,) in self.db.execute(
                    "SELECT x.texto FROM dispositivo x JOIN versao_texto v ON v.id = x.versao_id "
                    "WHERE v.fidelidade_ok = 1 AND v.conversor NOT LIKE 'pdf-ocr%' AND v.conversor NOT LIKE 'pdf-type3%'"):
                self._lexico_cache.update(p.lower() for p in palavras(texto))
        return self._lexico_cache

    def _decifrar_type3(self, documento_id: str, dados: bytes, tessdata: str):
        """D-14: decifra fontes Type3 sem tabela de caracteres; devolve (TextoPdf, Decifracao) ou None."""
        import pymupdf

        if not type3.fontes_type3_sem_unicode(pymupdf.open(stream=dados, filetype="pdf")):
            return None
        dicionario = {r["hash"]: (r["caractere"], r["concordancia"], r["votos"])
                      for r in self.db.execute("SELECT * FROM glifo")}
        dec = type3.decifrar(dados, tessdata, dicionario=dicionario, lexico=self._lexico())
        if dec.fracao_incerta > self.LIMIAR_INCERTOS_TYPE3:
            return None
        texto = extrair_pdf(dados, mapa_type3=dec.mapa)
        if not texto.legibilidade()[0]:
            return None
        self._atualizar_dicionario_glifos(documento_id, dec)
        return texto, dec

    def _atualizar_dicionario_glifos(self, documento_id: str, dec: type3.Decifracao) -> None:
        """Acrescenta ao dicionário os desenhos decifrados com concordância ≥ 90% e ≥ 5 votos. Se outro
        documento tiver decifrado o mesmo desenho como outra letra, a entrada fica em conflito (concordância 0)
        e deixa de ser usada."""
        for h, cont in dec.votos.items():
            letra, n = cont.most_common(1)[0]
            total = sum(cont.values())
            if ":" in h or total < 5 or n / total < 0.9:
                continue
            atual = self.db.execute("SELECT * FROM glifo WHERE hash = ?", (h,)).fetchone()
            if atual is None:
                self.db.execute("INSERT INTO glifo VALUES (?, ?, ?, ?, ?, ?)",
                                (h, letra, total, round(n / total, 4), documento_id, agora()))
            elif documento_id not in atual["documentos"].split(","):
                conc = atual["concordancia"] if atual["caractere"] == letra else 0.0
                self.db.execute("UPDATE glifo SET votos = votos + ?, concordancia = ?, documentos = documentos || ?, "
                                "atualizado_em = ? WHERE hash = ?",
                                (total, conc, "," + documento_id, agora(), h))

    def _relacoes_das_notas(self, documento_id: str, conversao: Conversao, fonte: sqlite3.Row) -> None:
        """Normas alteradoras citadas nas notas do consolidado ("Alínea b com redação dada pela Resolução CVM
        nº 194..."). A URL da ficha segue o padrão oficial conferido (resolNNN.html, instNNN.html); a evidência
        é a nota, com o dispositivo a que se refere."""
        for rotulo, nota in conversao.notas_alteracao:
            for especie, numero in _NORMA_CITADA.findall(nota):
                numero_int = int(numero.replace(".", ""))
                pasta, prefixo = _FICHA_POR_ESPECIE[especie.lower()[:5]]
                url = f"https://conteudo.cvm.gov.br/legislacao/{pasta}/{prefixo}{numero_int:03d}.html"
                evid = self._evidencia(documento_id, "relacao_alterada_por", url, fonte["url"], fonte["sha256"],
                                       f"{rotulo}: {nota}")
                self.db.execute(
                    "INSERT OR IGNORE INTO relacao (documento_id, tipo, alvo_titulo, alvo_url, evidencia_id) "
                    "VALUES (?, 'alterada_por', ?, ?, ?)",
                    (documento_id, f"{especie} CVM nº {numero_int} (nota do texto consolidado)", url, evid),
                )

    def _vigencia_de_arquivo(self, documento_id: str, doc: sqlite3.Row, conversao: Conversao,
                             fonte: sqlite3.Row) -> None:
        inicio, trecho = conversao.vigencia_data, conversao.vigencia_trecho
        if conversao.vigencia_na_publicacao and doc["data_publicacao"]:
            inicio = doc["data_publicacao"]
            evid = self.db.execute("SELECT trecho FROM evidencia WHERE documento_id = ? AND campo = 'data_publicacao' "
                                   "ORDER BY id DESC LIMIT 1", (documento_id,)).fetchone()
            trecho = f"{trecho} | {evid['trecho'] if evid else 'data de publicação da ficha'}"
        if inicio is None:
            self._evidencia(documento_id, "vigencia_clausula", None, fonte["url"], fonte["sha256"], trecho)
            return
        if doc["data_inicio_vigencia"] == inicio:
            return
        if doc["data_inicio_vigencia"] is not None:
            # Valor anterior substituído: a evidência registra de onde vinha e por quê.
            self._evidencia(documento_id, "data_inicio_vigencia_substituida", doc["data_inicio_vigencia"],
                            fonte["url"], fonte["sha256"], f"substituída por {inicio} a partir de: {trecho}")
        self._definir(documento_id, "data_inicio_vigencia", inicio, fonte["url"], fonte["sha256"], trecho)
        if inicio > self.hoje.isoformat():
            self._definir(documento_id, "situacao", "vigência futura", fonte["url"], fonte["sha256"],
                          f"início de vigência em {inicio} (cláusula de vigência do texto oficial)")

    def _vigencia(self, ato: AtoGabarito, ficha: Ficha, artefato: Artifact, conversao: Conversao) -> None:
        if not conversao.vigencia_trecho:
            return
        inicio = conversao.vigencia_data
        trecho = conversao.vigencia_trecho
        if conversao.vigencia_na_publicacao and ficha.data_publicacao:
            inicio = ficha.data_publicacao
            trecho = f"{trecho} | {next(e.trecho for e in ficha.eventos if e.evento == 'publicacao')}"
        self._definir(ato.chave, "data_inicio_vigencia", inicio, artefato.url, artefato.sha256, trecho)

    def _situacao(self, ato: AtoGabarito, ficha: Ficha, artefato: Artifact) -> None:
        """D-09: situação a partir das marcações oficiais da ficha e da cláusula de vigência."""
        doc = self.db.execute("SELECT data_inicio_vigencia FROM documento WHERE id = ?", (ato.chave,)).fetchone()
        revogacoes = [r for r in ficha.relacoes if r.tipo == "revogada_por"]
        alteracoes = [r for r in ficha.relacoes if r.tipo == "alterada_por"]
        if ficha.revogada_no_titulo or revogacoes:
            parcial = any(re.search(r"parcialmente", r.trecho, re.I) for r in revogacoes)
            situacao = "parcialmente revogada" if parcial else "integralmente revogada"
            trecho = revogacoes[0].trecho if revogacoes else ficha.titulo
        elif doc and doc["data_inicio_vigencia"] and doc["data_inicio_vigencia"] > self.hoje.isoformat():
            situacao = "vigência futura"
            trecho = f"início de vigência em {doc['data_inicio_vigencia']} (cláusula de vigência do texto oficial)"
        elif alteracoes:
            situacao = "vigente com alterações"
            trecho = alteracoes[0].trecho + " | ficha sem marcação de revogação"
        else:
            situacao = "vigente"
            trecho = f"ficha oficial sem marcação de revogação ou alteração (consultada em {self.hoje.isoformat()})"
        self._definir(ato.chave, "situacao", situacao, artefato.url, artefato.sha256, trecho)

    def _lacuna(self, chave: str, classificacao: str, detalhe: str, url: str | None = None, erro: str | None = None,
                fontes: str | None = None) -> None:
        self.db.execute(
            "INSERT INTO lacuna (chave, classificacao, detalhe, fontes_consultadas, url, erro, registrado_em) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chave, classificacao, detalhe, fontes, url, erro, agora()),
        )
        self.db.commit()
