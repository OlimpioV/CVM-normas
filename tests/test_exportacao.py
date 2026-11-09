"""Visualização e exportação (Fase 3): o texto exportado é o da versão aprovada, sem perdas, com cabeçalho."""

import io
import unicodedata
from collections import Counter
from datetime import datetime

import pytest

from repositorio_cvm import acervo, consolidacao, exportacao
from repositorio_cvm.conversao.fidelidade import palavras, texto_do_markdown

from tests.test_coletor import _documento_com_arquivos, ambiente  # noqa: F401 (fixture)

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _contagem(texto: str) -> Counter:
    return Counter(palavras(unicodedata.normalize("NFKC", texto)))


@pytest.fixture
def res21(ambiente):  # noqa: F811
    """Res. 21 consolidada real (DOCX conferido com o PDF): redação anterior tachada, notas e tabelas."""
    cfg, db, criar = ambiente
    coletor = criar()
    _documento_com_arquivos(db, coletor, "resolucao-cvm-21", [
        ("resol021consolid.docx", "consolidado", "docx", DOCX),
        ("resol021consolid.pdf", "consolidado", "pdf", "application/pdf")])
    db.execute("UPDATE documento SET situacao = 'vigente com alterações', numero = '21', "
               "ultima_verificacao = '2026-10-27T10:00:00'")
    assert [r.status for r in coletor.converter_arquivos("resolucao-cvm-21")] == ["ok"]
    # A ficha da Res. 21 lista alteradoras que o consolidado já cita: nada a aplicar além da derivação.
    assert [r.status for r in consolidacao.consolidar(db, cfg.pasta_dados)] == ["gerada", "sem alterações pendentes"]
    return cfg, db, acervo.carregar(db, "resolucao-cvm-21")


def test_markdown_vira_html_sem_perder_marcadores_nem_notas():
    h = acervo.html("Texto[^7] e campo ___________ e b.1.3*b.1.4 e (=b.2.3*b.2.4)\n\n"
                    "1. PÚBLICO-ALVO\n\n* Quando se referir\n\n____\n\n[^7]: Nota sete.\n\n[^3]: Nota sem chamada.\n")
    # Notas: número original preservado, inclusive a definição sem chamada no texto.
    assert "[7]</a></sup>" in h and "[7] Nota sete." in h and "[3] Nota sem chamada." in h
    # Itens numerados e marcadores ficam literais, não viram lista renumerável.
    assert "<p>1. PÚBLICO-ALVO</p>" in h and "<p>* Quando se referir</p>" in h and "<ol" not in h
    # Sublinhado de formulário e asterisco de multiplicação são texto, não ênfase ou linha horizontal.
    assert "___________" in h and "<p>____</p>" in h and "b.1.3*b.1.4" in h and "b.2.3*b.2.4" in h
    assert "<hr" not in h and "<em>" not in h


def test_exportacoes_tem_cabecalho_e_todo_o_texto(res21):
    cfg, _, doc = res21
    versao = doc.versao("oficial")
    assert versao.tipo == "texto consolidado oficial"
    corpo = acervo.markdown(cfg.pasta_dados, versao)
    referencia = _contagem(texto_do_markdown(corpo))
    agora = datetime(2026, 10, 28, 9, 0)

    md = exportacao.exportar(doc, cfg.pasta_dados, "md", "oficial", agora=agora)
    assert md.nome == "resolucao-cvm-21-consolidado-oficial-com-tachado.md"
    texto_md = md.conteudo.decode("utf-8")
    for trecho in ("**Situação normativa:** vigente com alterações", "**Fonte oficial:** https://conteudo.cvm.gov.br",
                   "consultada em 27/10/2026", "prevalece o original", "**Exportado em:** 28/10/2026 09:00"):
        assert trecho in texto_md
    assert texto_md.endswith(corpo)  # corpo idêntico ao Markdown convertido

    txt = exportacao.exportar(doc, cfg.pasta_dados, "txt", "oficial", agora=agora).conteudo.decode("utf-8")
    assert not referencia - _contagem(txt)
    assert "[redação anterior]" in txt  # a redação tachada continua no texto, identificada

    from docx import Document
    arquivo = Document(io.BytesIO(exportacao.exportar(doc, cfg.pasta_dados, "docx", "oficial", agora=agora).conteudo))
    texto_docx = "\n".join(p.text for p in arquivo.paragraphs) + "\n" + "\n".join(
        c.text for t in arquivo.tables for linha in t.rows for c in linha.cells)
    assert not referencia - _contagem(texto_docx)
    assert any(r.font.strike for p in arquivo.paragraphs for r in p.runs)
    assert arquivo.tables[0].rows[0].cells[0].text == "Norma"

    # Tabela com célula riscada (Res. 21, Anexo): o fpdf2 não aceita <s> na célula; o trecho sai identificado.
    pdf = exportacao.exportar(doc, cfg.pasta_dados, "pdf", "oficial", agora=agora)
    assert pdf.conteudo.startswith(b"%PDF") and pdf.tipo_mime == "application/pdf"


def test_exportacao_da_consolidada_so_tem_o_texto_vigente(res21):
    cfg, _, doc = res21
    versao = doc.versao()
    assert versao.tipo == acervo.TIPO_VIGENTE and versao.base_versao_id == doc.versao("oficial").id
    md = exportacao.exportar(doc, cfg.pasta_dados, "md").conteudo.decode("utf-8")
    assert "derivado do consolidado oficial da CVM" in md and "~~" not in md and "<s>" not in md
    txt = exportacao.exportar(doc, cfg.pasta_dados, "txt").conteudo.decode("utf-8")
    assert "[redação anterior]" not in txt and "com redação dada" in txt  # notas de alteração mantidas
    from docx import Document
    arquivo = Document(io.BytesIO(exportacao.exportar(doc, cfg.pasta_dados, "docx").conteudo))
    assert not any(r.font.strike for p in arquivo.paragraphs for r in p.runs)
    assert exportacao.exportar(doc, cfg.pasta_dados, "md").nome == "resolucao-cvm-21-consolidado.md"


def test_pdf_incompleto_e_detectado(res21):
    cfg, _, doc = res21
    versao = doc.versao()
    corpo = acervo.markdown(cfg.pasta_dados, versao)
    metade = exportacao._pdf(exportacao.cabecalho(doc, versao, datetime(2026, 10, 28)), corpo[: len(corpo) // 2])
    assert exportacao.conferir_pdf(metade, texto_do_markdown(corpo))


def test_documento_sem_texto_aprovado_nao_exporta(ambiente):  # noqa: F811
    _, db, criar = ambiente
    _documento_com_arquivos(db, criar(), "resolucao-cvm-1", [])
    doc = acervo.carregar(db, "resolucao-cvm-1")
    assert doc.versao() is None
    with pytest.raises(exportacao.ExportacaoError):
        exportacao.exportar(doc, criar().config.pasta_dados, "pdf")
    assert "não verificada" in doc.aviso_vigencia()
