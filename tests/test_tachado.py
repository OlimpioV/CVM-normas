"""Redação anterior tachada e notas de alteração dos textos consolidados da CVM.

O DOCX mínimo reproduz o trecho do art. 25, IV, da Res. CVM 60 consolidada (DOCX oficial de 27/10/2026):
alínea "b" antiga tachada, alínea "b" vigente e a nota "Alínea b com redação dada pela Resolução CVM nº 194",
em parágrafo com marcador da fonte Symbol (U+F0B7).
"""

import io
import zipfile

from repositorio_cvm.conversao.docx import blocos_docx, converter_docx
from repositorio_cvm.conversao.fidelidade import verificar
from repositorio_cvm.conversao.html import estruturar

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _run(texto, tachado=False):
    rpr = "<w:rPr><w:strike/></w:rPr>" if tachado else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{texto}</w:t></w:r>'


def _p(*runs, numerado=False):
    ppr = '<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="16"/></w:numPr></w:pPr>' if numerado else ""
    return f"<w:p>{ppr}{''.join(runs)}</w:p>"


def _docx(*paragrafos) -> bytes:
    documento = f'<w:document {W}><w:body>{"".join(paragrafos)}</w:body></w:document>'
    numeracao = (f'<w:numbering {W}><w:abstractNum w:abstractNumId="3"><w:lvl w:ilvl="0">'
                 f'<w:numFmt w:val="bullet"/><w:lvlText w:val=""/></w:lvl></w:abstractNum>'
                 f'<w:num w:numId="16"><w:abstractNumId w:val="3"/></w:num></w:numbering>')
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w") as z:
        z.writestr("word/document.xml", documento)
        z.writestr("word/numbering.xml", numeracao)
    return saida.getvalue()


TRECHO = _docx(
    _p(_run("Art. 25. Compete privativamente à assembleia especial de investidores deliberar sobre:")),
    _p(_run("IV – qualquer deliberação pertinente à administração ou liquidação do patrimônio separado:")),
    _p(_run("a) a realização de aporte de capital por parte dos investidores;")),
    _p(_run("b) a dação em pagamento aos investidores dos valores integrantes do patrimônio separado;", tachado=True)),
    _p(_run("b) a "), _run("dação"), _run(" de ativos em pagamento aos investidores dos valores integrantes do "
                                         "patrimônio separado;")),
    _p(_run("Alínea b "), _run("com redação dada "), _run("pela Resolução CVM nº 194 de 17 de novembro de 2023."),
       numerado=True),
    _p(_run("c) o leilão dos ativos componentes do patrimônio separado; ou")),
    _p(_run("§ 1º Texto "), _run("antigo", tachado=True), _run(" vigente do parágrafo.")),
)


def test_alinea_tachada_e_redacao_anterior_e_a_seguinte_e_a_vigente():
    c = converter_docx(TRECHO)
    alineas_b = [(d.tipo, d.rotulo) for d in c.dispositivos if d.texto.startswith("b)")]
    assert alineas_b == [("redacao_anterior", "art. 25, inciso IV, alínea b (redação anterior)"),
                         ("alinea", "art. 25, inciso IV, alínea b")]
    assert "~~b) a dação em pagamento aos investidores" in c.markdown
    assert verificar(c.texto_fonte, c.markdown).ok  # nenhuma palavra perdida: o tachado continua no Markdown


def test_nota_de_alteracao_com_marcador_legivel():
    c = converter_docx(TRECHO)
    notas = [d for d in c.dispositivos if d.tipo == "nota_alteracao"]
    assert [d.texto for d in notas] == ["• Alínea b com redação dada pela Resolução CVM nº 194 de 17 de novembro de 2023."]
    assert "" not in c.markdown
    assert c.notas_alteracao == [("art. 25, inciso IV, nota de alteração", notas[0].texto)]


def test_tachado_parcial_fica_marcado_e_fora_do_texto_vigente():
    c = converter_docx(TRECHO)
    paragrafo = next(d for d in c.dispositivos if d.rotulo == "art. 25, § 1º")
    assert paragrafo.texto == "§ 1º Texto vigente do parágrafo."
    assert "Texto ~~antigo~~ vigente" in c.markdown


def test_clausula_de_vigencia_tachada_nao_conta():
    blocos, fonte, _ = blocos_docx(_docx(
        _p(_run("Art. 140. Esta Resolução entra em vigor em 3 de abril de 2023.", tachado=True)),
        _p(_run("Art. 140. Esta Resolução entra em vigor em 2 de outubro de 2023.")),
    ))
    c = estruturar(blocos, fonte, estilo_citacao=False)
    assert c.vigencia_data == "2023-10-02"


def test_texto_oculto_do_word_nao_entra():
    """Res. 92: segmentos ocultos (w:vanish) de memória de tradução não são impressos nem estão no PDF."""
    oculto = '<w:r><w:rPr><w:vanish/></w:rPr><w:t xml:space="preserve">{0&gt;An investment entity&lt;}100{&gt;</w:t></w:r>'
    c = converter_docx(_docx(f"<w:p>{oculto}{_run('Art. 1º Texto visível.')}</w:p>"))
    assert "investment" not in c.markdown and "**Art. 1º** Texto visível." in c.markdown
