"""Interface web local (D-04): pesquisa, visualização, exportação, relatórios e API JSON.

Roda só em 127.0.0.1 e só lê o banco: nenhuma rota coleta, altera ou apaga dados. A API JSON devolve os
trechos com identificação da norma, dispositivo, redação, situação, data de referência e URL oficial (§12),
base para integração futura com ferramentas de IA sem que elas acessem o banco diretamente.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from repositorio_cvm import acervo, audiencias, exportacao
from repositorio_cvm.audiencias import audiencias_do_documento
from repositorio_cvm import justificativas as justif
from repositorio_cvm.armazenamento import banco
from repositorio_cvm.config import Config
from repositorio_cvm.pesquisa import interpretar_referencia, pesquisar
from repositorio_cvm.relatorios import cobertura, faltantes

PASTA_MODELOS = Path(__file__).parent / "modelos"
SITUACOES = [s for s in banco.SITUACOES]


def _trecho_marcado(texto: str) -> str:
    """Trecho do FTS5 com os termos entre [ ]: escapa o HTML e destaca os termos."""
    from markupsafe import escape

    seguro = str(escape(texto))
    return re.sub(r"\[([^\[\]]+)\]", r"<mark>\1</mark>", seguro)


def ancora_texto(inicio: str | None) -> str:
    """Fragmento de texto (#:~:text=) com as primeiras palavras do dispositivo: o navegador rola até ele."""
    if not inicio:
        return ""
    palavras = inicio.split()[:10]
    return "#:~:text=" + quote(" ".join(palavras), safe="").replace("-", "%2D")


def criar_app(config: Config) -> FastAPI:
    banco.abrir(config.banco, config.backups).close()  # aplica migrações pendentes (com backup) antes de servir
    app = FastAPI(title="Repositório Normativo CVM", docs_url="/api/docs", redoc_url=None)
    modelos = Jinja2Templates(directory=str(PASTA_MODELOS))
    modelos.env.globals.update(especies=acervo.ESPECIES, situacoes=SITUACOES, data_br=acervo.data_br,
                               ancora_texto=ancora_texto, trecho_marcado=_trecho_marcado, urlencode=urlencode,
                               chave_parte=acervo.chave_parte)

    def conexao():
        c = sqlite3.connect(config.banco, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    def _documento(c: sqlite3.Connection, documento_id: str) -> acervo.Documento:
        doc = acervo.carregar(c, documento_id)
        if doc is None:
            raise HTTPException(404, "documento não encontrado no acervo")
        return doc

    @app.get("/", response_class=HTMLResponse)
    def inicio(request: Request, q: str = "", especie: str = "", situacao: str = "", desde: str = "", ate: str = "",
               versao: str = "consolidado", ap: str = "", c: sqlite3.Connection = Depends(conexao)):
        achados, referencia, abrir, achados_ap = [], None, None, []
        if q.strip():
            referencia = interpretar_referencia(q)
            achados = pesquisar(c, q, especie=especie or None, situacao=situacao or None, desde=desde or None,
                                ate=ate or None, limite=100, versao=versao)
            if referencia:
                linha = c.execute("SELECT id, titulo FROM documento WHERE especie = ? AND numero = ?",
                                  (referencia.especie, referencia.numero)).fetchone()
                abrir = dict(linha) if linha else None
            elif ap:
                achados_ap = audiencias.pesquisar(c, q)
        cob = cobertura(c)
        return modelos.TemplateResponse(request, "inicio.html", {
            "q": q, "especie": especie, "situacao": situacao, "desde": desde, "ate": ate, "versao": versao,
            "achados": achados, "referencia": referencia, "abrir": abrir, "cob": cob, "ap": ap,
            "achados_ap": achados_ap})

    @app.get("/normas", response_class=HTMLResponse)
    def normas(request: Request, especie: str = "", situacao: str = "", ano: str = "",
               c: sqlite3.Connection = Depends(conexao)):
        linhas = acervo.listar(c, especie or None, situacao or None, int(ano) if ano.isdigit() else None)
        anos = [r[0] for r in c.execute("SELECT DISTINCT ano FROM documento WHERE ano IS NOT NULL ORDER BY ano DESC")]
        return modelos.TemplateResponse(request, "normas.html", {
            "linhas": linhas, "especie": especie, "situacao": situacao, "ano": ano, "anos": anos})

    @app.get("/norma/{documento_id}", response_class=HTMLResponse)
    def norma(request: Request, documento_id: str, versao: str = "consolidado", parte: str = "",
              c: sqlite3.Connection = Depends(conexao)):
        doc = _documento(c, documento_id)
        escolhida = doc.versao(versao)
        lista = acervo.partes(c, doc, escolhida) if escolhida else []
        selecionada = next((p for p in lista if p.chave == parte), None)
        corpo, aviso_parte = None, None
        if escolhida:
            md = None
            if selecionada:
                try:
                    md = acervo.markdown_parte(config.pasta_dados, c, escolhida, selecionada)
                except ValueError as erro:
                    selecionada, aviso_parte = None, f"Não foi possível separar a parte: {erro}. Texto completo exibido."
            elif parte:
                aviso_parte = f"A parte pedida não existe no {escolhida.tipo}; texto completo exibido."
            corpo = acervo.html(md if md is not None else acervo.markdown(config.pasta_dados, escolhida))
        # Consolidação gerada: cada alteração aplicada (ou não) pelo sistema, com o trecho do ato alterador.
        alteracoes = c.execute(
            "SELECT ato_id, operacao, alvo, status, vigencia, detalhe, comando FROM alteracao_aplicada "
            "WHERE versao_id = ? ORDER BY id", (escolhida.id,)).fetchall() if escolhida and escolhida.gerada else []
        return modelos.TemplateResponse(request, "norma.html", {
            "doc": doc, "versao": escolhida, "corpo": corpo, "incertos": corpo.count("□") if corpo else 0,
            "alteracoes": alteracoes,
            "preferida": versao, "partes": lista, "parte": selecionada, "aviso_parte": aviso_parte,
            "audiencias": audiencias_do_documento(c, documento_id),
            "justificativas": [dict(j, paragrafos=justif.paragrafos(config.pasta_dados, j))
                               for j in justif.justificativas_do_documento(c, documento_id)]})

    @app.get("/norma/{documento_id}/exportar/{formato}")
    def exportar(documento_id: str, formato: str, versao: str = "consolidado", parte: str = "",
                 c: sqlite3.Connection = Depends(conexao)):
        doc = _documento(c, documento_id)
        try:
            saida = exportacao.exportar(doc, config.pasta_dados, formato, versao, conexao=c, parte=parte or None)
        except exportacao.ExportacaoError as erro:
            raise HTTPException(422, str(erro)) from erro
        return Response(saida.conteudo, media_type=saida.tipo_mime,
                        headers={"Content-Disposition": f'attachment; filename="{saida.nome}"'})

    @app.get("/audiencia/{audiencia_id}", response_class=HTMLResponse)
    def audiencia(request: Request, audiencia_id: str, texto: int | None = None,
                  c: sqlite3.Connection = Depends(conexao)):
        aud = audiencias.carregar(c, audiencia_id)
        if aud is None:
            raise HTTPException(404, "audiência não encontrada no acervo")
        escolhido = next((a for a in aud["arquivos"] if texto and a["texto_id"] == texto), None)
        return modelos.TemplateResponse(request, "audiencia.html", {
            "aud": aud, "escolhido": escolhido,
            "paragrafos": audiencias.paragrafos(config.pasta_dados, c, texto) if escolhido else []})

    @app.get("/relatorios", response_class=HTMLResponse)
    def relatorios(request: Request, c: sqlite3.Connection = Depends(conexao)):
        return modelos.TemplateResponse(request, "relatorios.html", {"dados": cobertura(c)})

    @app.get("/relatorios/faltantes", response_class=HTMLResponse)
    def lista_faltantes(request: Request, familia: str, ano: str = "", c: sqlite3.Connection = Depends(conexao)):
        if familia not in acervo.ESPECIES:
            raise HTTPException(404, "espécie desconhecida")
        return modelos.TemplateResponse(request, "faltantes.html", {
            "familia": familia, "ano": ano, "itens": faltantes(c, familia, ano or None)})

    # ------------------------------------------------------------------ API JSON (§12)
    @app.get("/api/pesquisa")
    def api_pesquisa(q: str = Query(..., min_length=1), especie: str | None = None, situacao: str | None = None,
                     desde: str | None = None, ate: str | None = None, versao: str = "consolidado",
                     limite: int = Query(20, ge=1, le=200), c: sqlite3.Connection = Depends(conexao)):
        resultado = []
        for a in pesquisar(c, q, especie=especie, situacao=situacao, desde=desde, ate=ate, limite=limite,
                           versao=versao):
            item = {"documento_id": a.documento_id, "norma": a.titulo, "dispositivo": a.rotulo,
                    "situacao": a.situacao, "versao_texto": a.versao, "url_oficial": a.url_oficial,
                    "trecho": a.texto, "redacao": None, "data_referencia": None, "url_fonte": None}
            if a.dispositivo_id:
                d = c.execute(
                    "SELECT x.texto, a.coletado_em, a.url FROM dispositivo x JOIN versao_texto v ON v.id = x.versao_id "
                    "JOIN arquivo a ON a.id = v.arquivo_id WHERE x.id = ?", (a.dispositivo_id,)).fetchone()
                item.update(redacao=d["texto"], data_referencia=d["coletado_em"], url_fonte=d["url"])
            resultado.append(item)
        return JSONResponse({"consulta": q, "resultados": resultado,
                             "aviso": "Conversão automática do texto oficial; em divergência, prevalece o original."})

    @app.get("/api/audiencia/{audiencia_id}")
    def api_audiencia(audiencia_id: str, c: sqlite3.Connection = Depends(conexao)):
        aud = audiencias.carregar(c, audiencia_id)
        if aud is None:
            raise HTTPException(404, "audiência não encontrada no acervo")
        return aud

    @app.get("/api/norma/{documento_id}")
    def api_norma(documento_id: str, c: sqlite3.Connection = Depends(conexao)):
        doc = _documento(c, documento_id)
        return {
            "documento": doc.linha,
            "origem": {campo: {"url": e["url"], "sha256": e["sha256"], "trecho": e["trecho"],
                               "registrado_em": e["registrado_em"]} for campo, e in doc.evidencias.items()},
            "relacoes": [{"tipo": r["tipo"], "alvo": r["alvo_titulo"], "alvo_url": r["alvo_url"],
                          "alvo_no_acervo": r["alvo_no_acervo"], "evidencia": r["trecho"]} for r in doc.relacoes],
            "versoes": [dict(v.__dict__, partes=[p.__dict__ for p in acervo.partes(c, doc, v)]) for v in doc.versoes],
            "audiencias_publicas": audiencias_do_documento(c, documento_id),
            "justificativas_air": [{k: j[k] for k in ("rotulo", "url", "formato", "status", "sha256", "coletado_em",
                                                       "qualidade", "evidencia_url")}
                                   for j in justif.justificativas_do_documento(c, documento_id)],
            "aviso_vigencia": doc.aviso_vigencia(),
        }

    return app
