"""Coleta de ponta a ponta sem rede: opener falso servindo páginas reais salvas."""

import hashlib
from datetime import date
from pathlib import Path

import pytest

from repositorio_cvm.armazenamento import banco, originais
from repositorio_cvm.coleta.catalogo import url_catalogo
from repositorio_cvm.coleta.coletor import ColetaInterrompida, Coletor
from repositorio_cvm.coleta.http import PoliteClient
from repositorio_cvm.config import Config
from repositorio_cvm.gabarito import AtoGabarito
from repositorio_cvm.pesquisa import pesquisar

from tests.falsos import FakeClock, FakeOpener

FIX = Path(__file__).parent / "fixtures"
B = "https://conteudo.cvm.gov.br/legislacao"
HTML = {"Content-Type": "text/html;charset=UTF-8"}


def rotas(extra=None):
    r = {
        "https://conteudo.cvm.gov.br/robots.txt": (200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /apoio\n", "OK"),
        f"{B}/resolucoes/resol247.html": (200, HTML, (FIX / "resol247.html").read_bytes(), "OK"),
        f"{B}/resolucoes/anexos/200/resol247.htm": (200, HTML, (FIX / "resol247.htm").read_bytes(), "OK"),
        f"{B}/resolucoes/resol050.html": (200, HTML, (FIX / "resol050.html").read_bytes(), "OK"),
        f"{B}/resolucoes/resol175.html": (200, HTML, (FIX / "resol175.html").read_bytes(), "OK"),
        f"{B}/deliberacoes/deli0900/deli906.html": (200, HTML, (FIX / "deli906.html").read_bytes(), "OK"),
        f"{B}/deliberacoes/anexos/0900/deli906.htm": (200, HTML, (FIX / "deli906.htm").read_bytes(), "OK"),
        url_catalogo("oficio_circular", 1): (200, HTML, (FIX / "oc-cat1.html").read_bytes(), "OK"),
        f"{B}/oficios-circulares/sse1/oc-sse-0326.html": (200, HTML, (FIX / "oc-sse-0326.html").read_bytes(), "OK"),
        f"{B}/resolucoes/resol999.html": (404, {}, b"", "Not Found"),
    }
    r.update(extra or {})
    return r


@pytest.fixture
def ambiente(tmp_path):
    cfg = Config(pasta_dados=tmp_path / "dados", pasta_tessdata=tmp_path / "sem-modelo-ocr")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    clock = FakeClock()
    def criar(extra=None):
        cliente = PoliteClient(opener=FakeOpener(rotas(extra)), clock=clock, sleep=clock.sleep,
                               monotonic=clock.monotonic, min_interval=1.0, max_retries=0)
        coletor = Coletor(cfg, conexao, cliente, hoje=date(2026, 10, 27))
        coletor.iniciar("teste")
        return coletor
    return cfg, conexao, criar


def ato(chave, especie, ficha=None, numero=None, **kw):
    return AtoGabarito(chave=chave, especie=especie, numero=numero, descricao_usuario="teste", ficha=ficha, **kw)


def test_resolucao_com_integra_html_e_vigencia_futura(ambiente):
    cfg, db, criar = ambiente
    r = criar().coletar_ato(ato("resolucao-cvm-247", "resolucao", f"{B}/resolucoes/resol247.html", "247"))
    assert r.status == "coletado"
    doc = db.execute("SELECT * FROM documento WHERE id = 'resolucao-cvm-247'").fetchone()
    assert (doc["numero"], doc["ano"], doc["data_edicao"], doc["data_publicacao"]) == ("247", 2026, "2026-10-02", "2026-10-06")
    assert doc["data_inicio_vigencia"] == "2026-11-01"
    assert doc["situacao"] == "vigência futura"
    # Cada metadado gravado tem evidência com URL e hash do original.
    campos = {e["campo"] for e in db.execute("SELECT campo FROM evidencia WHERE documento_id = 'resolucao-cvm-247'")}
    assert {"titulo", "ementa", "data_edicao", "data_publicacao", "data_inicio_vigencia", "situacao"} <= campos
    for a in db.execute("SELECT caminho, sha256 FROM arquivo"):
        assert originais.verificar(cfg.pasta_dados, a["caminho"], a["sha256"])
    md = db.execute("SELECT caminho_md, fidelidade_ok FROM versao_texto").fetchone()
    assert md["fidelidade_ok"] == 1 and (cfg.pasta_dados / md["caminho_md"]).is_file()
    achados = pesquisar(db, "Resolução CVM 247, artigo 5")
    assert [a.rotulo for a in achados] == ["art. 5º"] and "entra em vigor" in achados[0].texto
    assert achados[0].url_oficial == f"{B}/resolucoes/resol247.html"
    assert pesquisar(db, "companhia securitizadora SCR")


def test_resolucao_sem_html_fica_pendente_com_links_anotados(ambiente):
    _, db, criar = ambiente
    r = criar().coletar_ato(ato("resolucao-cvm-50", "resolucao", f"{B}/resolucoes/resol050.html", "50"))
    assert r.status == "pendente" and "sem íntegra HTML" in r.detalhe
    doc = db.execute("SELECT * FROM documento WHERE id = 'resolucao-cvm-50'").fetchone()
    assert doc["situacao"] == "vigente com alterações"
    assert db.execute("SELECT COUNT(*) FROM link_documento WHERE documento_id = 'resolucao-cvm-50' AND baixado = 0").fetchone()[0] >= 3
    assert db.execute("SELECT COUNT(*) FROM arquivo WHERE documento_id = 'resolucao-cvm-50'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM relacao WHERE documento_id = 'resolucao-cvm-50' AND tipo = 'alterada_por'").fetchone()[0] == 2


def test_recoleta_e_idempotente(ambiente):
    _, db, criar = ambiente
    a = ato("deliberacao-cvm-906", "deliberacao", f"{B}/deliberacoes/deli0900/deli906.html", "906")
    criar().coletar_ato(a)
    contagens = [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("arquivo", "evidencia", "versao_texto", "dispositivo", "relacao")]
    criar().coletar_ato(a)
    assert contagens == [db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                         for t in ("arquivo", "evidencia", "versao_texto", "dispositivo", "relacao")]
    doc = db.execute("SELECT data_inicio_vigencia, situacao FROM documento WHERE id = 'deliberacao-cvm-906'").fetchone()
    assert doc["data_inicio_vigencia"] == "2026-03-12"  # "entra em vigor na data de sua publicação" + DOU
    assert doc["situacao"] == "vigente"


def test_oficio_localizado_pela_pesquisa(ambiente):
    _, db, criar = ambiente
    coletor = criar()
    alvo = ato("oficio-circular-cvm-sse-03-2026", "oficio_circular", numero="3", areas=frozenset({"SSE"}), ano=2026)
    achados = coletor.localizar_oficios([alvo], max_paginas=1)
    assert achados[alvo.chave].url == f"{B}/oficios-circulares/sse1/oc-sse-0326.html"
    r = coletor.coletar_ato(alvo, achados[alvo.chave])
    assert r.status == "pendente"
    doc = db.execute("SELECT area_tecnica, numero, data_publicacao FROM documento WHERE id = ?", (alvo.chave,)).fetchone()
    assert (doc["area_tecnica"], doc["numero"], doc["data_publicacao"]) == ("SSE", "3", None)


def test_ficha_inexistente_vira_lacuna_nao_localizado(ambiente):
    _, db, criar = ambiente
    r = criar().coletar_ato(ato("resolucao-cvm-999", "resolucao", f"{B}/resolucoes/resol999.html", "999"))
    assert r.status == "não localizado"
    lac = db.execute("SELECT classificacao, fontes_consultadas FROM lacuna").fetchone()
    assert lac["classificacao"] == "não localizado" and "resol999" in lac["fontes_consultadas"]
    assert db.execute("SELECT COUNT(*) FROM documento").fetchone()[0] == 0


def test_bloqueio_interrompe_a_coleta(ambiente):
    _, db, criar = ambiente
    coletor = criar({f"{B}/resolucoes/resol050.html": (403, {}, b"", "Forbidden")})
    with pytest.raises(ColetaInterrompida):
        coletor.coletar_ato(ato("resolucao-cvm-50", "resolucao", f"{B}/resolucoes/resol050.html", "50"))
    assert db.execute("SELECT resultado FROM tentativa ORDER BY id DESC").fetchone()[0] == "bloqueado"


def test_url_proibida_pelo_robots_e_pulada_sem_requisitar(ambiente):
    """Caso real (06/11/2026): o robots.txt da CVM proíbe só a ficha da Deliberação 233."""
    from repositorio_cvm.coleta.coletor import UrlProibida
    _, db, criar = ambiente
    coletor = criar({"https://conteudo.cvm.gov.br/robots.txt": (
        200, {"Content-Type": "text/plain"}, "User-agent: *\nDisallow: /legislacao/deliberacoes/deli0200/deli233.html\n", "OK")})
    with pytest.raises(UrlProibida):
        coletor.coletar_ato(ato("deliberacao-cvm-233", "deliberacao", f"{B}/deliberacoes/deli0200/deli233.html", "233"))
    assert db.execute("SELECT resultado FROM tentativa ORDER BY id DESC").fetchone()[0] == "proibido pelo robots.txt"
    assert coletor.coletar_ato(ato("resolucao-cvm-50", "resolucao", f"{B}/resolucoes/resol050.html", "50")).status


def test_relacao_cruzada_divergente_aparece_no_relatorio(ambiente, tmp_path):
    from repositorio_cvm.relatorios import oficio_relacoes_cruzadas
    _, db, criar = ambiente
    c = criar()
    c.coletar_ato(ato("resolucao-cvm-247", "resolucao", f"{B}/resolucoes/resol247.html", "247"))
    c.coletar_ato(ato("resolucao-cvm-175", "resolucao", f"{B}/resolucoes/resol175.html", "175"))
    avisos = oficio_relacoes_cruzadas(db)
    assert any("Resolução CVM 247" in a and "Resolução CVM 175" in a for a in avisos)


def _documento_com_arquivos(db, coletor, chave, arquivos):
    from repositorio_cvm.modelos import Artifact
    db.execute("INSERT INTO documento (id, especie, status_coleta, criado_em, atualizado_em, titulo, url_oficial) "
               "VALUES (?, 'resolucao', 'pendente', 'x', 'x', 'Teste', 'https://conteudo.cvm.gov.br/x.html')", (chave,))
    for nome, papel, formato, tipo in arquivos:
        art = Artifact.from_bytes(f"{B}/anexos/{nome}", (FIX / nome).read_bytes(), tipo, "2026-10-27T00:00:00+00:00")
        coletor.registrar_arquivo(chave, art, papel, formato)


def test_conversao_docx_conferida_com_pdf_aprova_o_documento(ambiente):
    _, db, criar = ambiente
    coletor = criar()
    _documento_com_arquivos(db, coletor, "resolucao-cvm-62", [
        ("resol062.docx", "integra", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("resol062.pdf", "integra", "pdf", "application/pdf")])
    resultados = coletor.converter_arquivos("resolucao-cvm-62")
    assert [r.status for r in resultados] == ["ok"]
    v = db.execute("SELECT conversor, fidelidade_ok, conferencia_cruzada, qualidade FROM versao_texto").fetchone()
    assert v["conversor"].startswith("docx") and v["fidelidade_ok"] == 1 and '"consistente": true' in v["conferencia_cruzada"]
    assert db.execute("SELECT status_coleta FROM documento").fetchone()[0] == "coletado"
    assert coletor.converter_arquivos("resolucao-cvm-62")[0].status == "ok"  # idempotente
    assert db.execute("SELECT COUNT(*) FROM versao_texto").fetchone()[0] == 1


def test_pdf_ilegivel_deixa_documento_pendente_sem_versao_aprovada(ambiente):
    _, db, criar = ambiente
    coletor = criar()
    _documento_com_arquivos(db, coletor, "oficio-x", [("oc-sse-0326.pdf", "integra", "pdf", "application/pdf")])
    resultados = coletor.converter_arquivos("oficio-x")
    assert [r.status for r in resultados] == ["ilegível"]
    doc = db.execute("SELECT status_coleta, motivo_pendencia FROM documento").fetchone()
    assert doc["status_coleta"] == "pendente" and "exige OCR" in doc["motivo_pendencia"]
    assert db.execute("SELECT COUNT(*) FROM versao_texto WHERE fidelidade_ok = 1").fetchone()[0] == 0


_SEM_MODELO_OCR = pytest.mark.skipif(
    not (Config(pasta_dados=Path(".")).tessdata / "por.traineddata").is_file(),
    reason="modelo de OCR (ferramentas/tessdata/por.traineddata) não instalado")
_EMENTA_SSE_03 = "Impossibilidade de vinculação da taxa de performance de FIDC à remuneração da consultoria."


def _oficio_ilegivel(tmp_path):
    cfg = Config(pasta_dados=tmp_path / "dados")
    db = banco.abrir(cfg.banco, cfg.backups)
    coletor = Coletor(cfg, db, cliente=None, hoje=date(2026, 10, 27))
    _documento_com_arquivos(db, coletor, "oficio-x", [("oc-sse-0326.pdf", "integra", "pdf", "application/pdf")])
    db.execute("UPDATE documento SET ementa = ?", (_EMENTA_SSE_03,))
    return db, coletor


@_SEM_MODELO_OCR
def test_fonte_type3_e_decifrada_com_o_texto_exato_do_arquivo(tmp_path):
    db, coletor = _oficio_ilegivel(tmp_path)
    # Léxico para o desempate "i" x "í": no acervo vem dos textos oficiais já convertidos; aqui, das fixtures.
    from repositorio_cvm.conversao.docx import converter_docx
    from repositorio_cvm.conversao.fidelidade import palavras
    from repositorio_cvm.conversao.html import converter_html
    textos = (converter_html((FIX / "resol249.htm").read_bytes()).markdown
              + converter_docx((FIX / "resol021consolid.docx").read_bytes()).markdown)
    coletor._lexico_cache = {w.lower() for w in palavras(textos)} | {"ofício"}
    assert [r.status for r in coletor.converter_arquivos("oficio-x")] == ["ok"]
    v = db.execute("SELECT conversor, qualidade, fidelidade_ok, caminho_md FROM versao_texto").fetchone()
    assert v["conversor"].startswith("pdf-type3") and v["qualidade"].startswith("média") and v["fidelidade_ok"] == 1
    assert "100% das palavras da ementa" in v["qualidade"] and "caracteres não identificados" in v["qualidade"]
    md = (coletor.config.pasta_dados / v["caminho_md"]).read_text(encoding="utf-8")
    # Trechos em que o OCR puro errava ("sse(devm.gov.br", "l." no lugar de "1.") saem exatos da fonte.
    assert "Ofício-Circular nº 3/2026/CVM/SSE" in md
    assert "o art. 35 do Anexo Normativo II à RCVM 175 estabelece" in md
    assert "Resolução CVM nº 175 (\"RCVM 175\")" in md
    assert db.execute("SELECT COUNT(*) FROM glifo").fetchone()[0] > 50  # dicionário de glifos alimentado
    assert pesquisar(db, "consultor especializado taxa de performance")


@_SEM_MODELO_OCR
def test_sem_fonte_type3_o_pdf_ilegivel_vai_para_ocr_de_qualidade_baixa(tmp_path, monkeypatch):
    from repositorio_cvm.conversao import type3
    monkeypatch.setattr(type3, "fontes_type3_sem_unicode", lambda doc: set())
    db, coletor = _oficio_ilegivel(tmp_path)
    assert [r.status for r in coletor.converter_arquivos("oficio-x")] == ["ok"]
    v = db.execute("SELECT conversor, qualidade, fidelidade_ok FROM versao_texto").fetchone()
    assert v["conversor"].startswith("pdf-ocr") and v["qualidade"].startswith("baixa") and v["fidelidade_ok"] == 1
    assert "100% das palavras da ementa" in v["qualidade"]


def test_migracao_registra_versao_e_backup_manual(tmp_path):
    caminho = tmp_path / "acervo.sqlite"
    db = banco.abrir(caminho)
    assert banco.versao_atual(db) == len(banco.MIGRACOES)
    destino = banco.fazer_backup(db, tmp_path / "backups")
    assert destino.is_file()
    db.close()
    assert banco.versao_atual(banco.abrir(caminho)) == len(banco.MIGRACOES)


def test_migracao_de_banco_existente_faz_backup_e_preserva_dados(tmp_path, monkeypatch):
    caminho = tmp_path / "acervo.sqlite"
    monkeypatch.setattr(banco, "MIGRACOES", banco.MIGRACOES[:1])
    db = banco.abrir(caminho)
    db.execute("INSERT INTO documento (id, especie, status_coleta, criado_em, atualizado_em) "
               "VALUES ('x', 'resolucao', 'pendente', 'agora', 'agora')")
    db.commit()
    db.close()
    monkeypatch.undo()
    db = banco.abrir(caminho, tmp_path / "backups")
    assert banco.versao_atual(db) == len(banco.MIGRACOES)
    assert db.execute("SELECT id FROM documento").fetchone()[0] == "x"
    assert "parte" in [c[1] for c in db.execute("PRAGMA table_info(dispositivo)")]
    backups = list((tmp_path / "backups").glob("*antes-v2.sqlite"))
    assert len(backups) == 1


def test_original_nunca_e_sobrescrito(tmp_path):
    sha, rel = originais.gravar(tmp_path, b"abc", "text/html")
    assert sha == hashlib.sha256(b"abc").hexdigest()
    assert originais.gravar(tmp_path, b"abc", "text/html") == (sha, rel)
    (tmp_path / rel).chmod(0o666)  # o original fica somente leitura; simula adulteração fora do sistema
    (tmp_path / rel).write_bytes(b"adulterado")
    with pytest.raises(originais.IntegridadeError):
        originais.gravar(tmp_path, b"abc", "text/html")


def test_pagina_de_erro_no_lugar_do_pdf_vira_lacuna_e_nao_original(ambiente):
    _, db, criar = ambiente
    coletor = criar({f"{B}/resolucoes/resol175.html": (200, HTML, (FIX / "resol175.html").read_bytes(), "OK")})
    coletor.coletar_ato(ato("resolucao-cvm-175", "resolucao", f"{B}/resolucoes/resol175.html", "175"))
    links = db.execute("SELECT url FROM link_documento WHERE formato = 'pdf' AND papel IN "
                       "('integra', 'original', 'consolidado')").fetchall()
    assert links
    erro = {l["url"]: (200, HTML, b"<html><body>Servico indisponivel</body></html>", "OK") for l in links}
    resultados = criar(erro).baixar_arquivos("resolucao-cvm-175")
    assert any(r.status == "erro" and "conteúdo inesperado" in r.detalhe for r in resultados)
    assert not db.execute("SELECT 1 FROM arquivo WHERE formato = 'pdf'").fetchone()
    assert db.execute("SELECT classificacao FROM lacuna WHERE chave = 'resolucao-cvm-175'").fetchone()[0] == \
        "indisponível para download"


def test_docx_que_diverge_do_pdf_usa_o_texto_do_pdf(ambiente):
    """D-22: DOCX reprovado na conferência cruzada; o texto aprovado vem do PDF, com qualidade média e aviso.
    (Os dois arquivos de normas diferentes forçam a divergência.)"""
    _, db, criar = ambiente
    coletor = criar()
    _documento_com_arquivos(db, coletor, "resolucao-cvm-62", [
        ("resol062.docx", "integra", "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("resol021consolid.pdf", "integra", "pdf", "application/pdf")])
    assert [r.status for r in coletor.converter_arquivos("resolucao-cvm-62")] == ["ok"]
    versoes = db.execute("SELECT conversor, fidelidade_ok, qualidade FROM versao_texto ORDER BY id").fetchall()
    assert [(v["conversor"][:4], v["fidelidade_ok"]) for v in versoes] == [("docx", 0), ("pdf-", 1)]
    assert versoes[1]["qualidade"].startswith("média") and "divergiu do PDF" in versoes[1]["qualidade"]
    assert db.execute("SELECT status_coleta FROM documento").fetchone()[0] == "coletado"
