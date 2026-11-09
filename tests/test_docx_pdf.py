"""Conversão de DOCX e PDF oficiais reais e conferência cruzada (fixtures de 27/10/2026)."""

from collections import Counter
from pathlib import Path

from repositorio_cvm.conversao.docx import blocos_docx, cabecalhos_docx, converter_docx
from repositorio_cvm.conversao.fidelidade import conferir_com_pdf, verificar
from repositorio_cvm.conversao.html import Bloco, estruturar
from repositorio_cvm.conversao.pdf import extrair

FIX = Path(__file__).parent / "fixtures"


def test_docx_da_resolucao_62_confere_palavra_a_palavra_com_o_pdf():
    docx = (FIX / "resol062.docx").read_bytes()
    c = converter_docx(docx)
    assert verificar(c.texto_fonte, c.markdown).ok
    cruzada = conferir_com_pdf(c.markdown, extrair((FIX / "resol062.pdf").read_bytes(), cabecalhos_docx(docx)).texto)
    assert cruzada.consistente
    assert cruzada.cobertura_markdown_no_pdf == 1.0 and cruzada.cobertura_pdf_no_markdown == 1.0
    assert Counter(d.tipo for d in c.dispositivos)["artigo"] == 6


def test_numeracao_automatica_e_notas_de_rodape_do_docx():
    docx = (FIX / "resol021consolid.docx").read_bytes()
    c = converter_docx(docx)
    rotulos = {d.rotulo: d.texto for d in c.dispositivos}
    # Os rótulos "I –", "II –" vêm da numeração automática do Word, não do texto do parágrafo.
    assert rotulos["art. 3º, inciso I"].startswith("I – ser domiciliado no Brasil")
    assert rotulos["art. 3º, inciso IV"] == "IV – ter reputação ilibada;"
    notas = [d for d in c.dispositivos if d.tipo == "nota"]
    assert notas and notas[0].texto.startswith("[^1]: ")
    cruzada = conferir_com_pdf(c.markdown,
                               extrair((FIX / "resol021consolid.pdf").read_bytes(), cabecalhos_docx(docx)).texto)
    assert cruzada.consistente, (cruzada.faltam_no_markdown, cruzada.faltam_no_pdf)


def test_cabecalho_do_docx_e_removido_do_pdf_sem_tocar_o_corpo():
    docx = (FIX / "resol062.docx").read_bytes()
    texto = extrair((FIX / "resol062.pdf").read_bytes(), cabecalhos_docx(docx))
    assert any("COMISSÃO DE VALORES MOBILIÁRIOS" in r for r in texto.removidos)
    assert texto.paragrafos[0].startswith("RESOLUÇÃO CVM Nº 62")  # título da capa preservado
    assert texto.legibilidade()[0]


def test_pdf_com_camada_de_texto_ilegivel_e_detectado():
    texto = extrair((FIX / "oc-sse-0326.pdf").read_bytes())
    legivel, motivo = texto.legibilidade()
    assert not legivel and "exige OCR" in motivo


def test_estilo_norma_alterada_so_marca_citacao_fora_do_consolidado():
    blocos = [Bloco("Art. 1º Texto da norma.", "NormaAlterada"), Bloco("Art. 2º Outro.", "NormaAlterada")]
    original = estruturar(blocos, "Art. 1º Texto da norma. Art. 2º Outro.", estilo_citacao=True)
    consolidado = estruturar(blocos, "Art. 1º Texto da norma. Art. 2º Outro.", estilo_citacao=False)
    assert {d.tipo for d in original.dispositivos} == {"texto_alterado"}
    assert [d.tipo for d in consolidado.dispositivos] == ["artigo", "artigo"]


def test_termo_entre_aspas_no_inicio_nao_abre_citacao():
    blocos = [Bloco("Art. 1º Considera-se:"), Bloco("“lavagem” de dinheiro: crime;"), Bloco("Art. 2º Fim.")]
    c = estruturar(blocos, " ".join(b.texto for b in blocos))
    assert [d.tipo for d in c.dispositivos] == ["artigo", "texto", "artigo"]


def test_partes_com_articulado_proprio_e_vigencia_com_redacoes_sucessivas():
    blocos = [Bloco("Art. 40. Parte geral."), Bloco("Art. 140. Esta Resolução entra em vigor em 3 de abril de 2023."),
              Bloco("Art. 140. Esta Resolução entra em vigor em 2 de outubro de 2023."),
              Bloco("ANEXO NORMATIVO I – FUNDOS", "TtulodaResoluo"), Bloco("Art. 40. Do anexo.")]
    c = estruturar(blocos, " ".join(b.texto for b in blocos), estilo_citacao=False)
    rotulos = [d.rotulo for d in c.dispositivos if d.tipo == "artigo"]
    assert rotulos == ["art. 40", "art. 140", "art. 140", "Anexo Normativo I, art. 40"]
    assert c.vigencia_data is None and any("mais de uma cláusula" in a for a in c.avisos)


def _partes(blocos):
    c = estruturar(blocos, " ".join(b.texto for b in blocos), estilo_citacao=False)
    return c, [(d.tipo, d.parte) for d in c.dispositivos]


def test_sumario_em_texto_corrido_nao_abre_partes():
    # Sumário do PDF da Res. 175 original: entradas com pontilhado, uma delas quebrada em duas linhas.
    c, partes = _partes([
        Bloco("ANEXO NORMATIVO I – FUNDOS DE INVESTIMENTO FINANCEIRO ........ 70"),
        Bloco("SUPLEMENTO F – LÂMINA DE INFORMAÇÕES BÁSICAS DE CLASSES DE INVESTIMENTO EM COTAS DE"),
        Bloco("FIDC .............................. 168"),
        Bloco("RESOLUÇÃO CVM Nº 175, DE 23 DE DEZEMBRO DE 2022."),
        Bloco("CAPÍTULO I – ÂMBITO E FINALIDADE"), Bloco("Art. 1º Esta Resolução dispõe."),
        Bloco("ANEXO NORMATIVO I – FUNDOS DE INVESTIMENTO FINANCEIRO"), Bloco("Art. 1º Este Anexo."),
    ])
    assert [t for t, _ in partes[:3]] == ["sumario", "sumario", "preambulo"]
    assert partes[4] == ("cabecalho", None)  # título real depois do sumário
    assert [d.rotulo for d in c.dispositivos if d.tipo == "artigo"] == ["art. 1º", "Anexo Normativo I, art. 1º"]


def test_remissao_quebrada_nao_abre_anexo_e_suplementos_formam_parte():
    c, partes = _partes([
        Bloco("ANEXO NORMATIVO I – EMPRÉSTIMO"), Bloco("Art. 23. Aplicam-se os arts. 9º a 12 deste"),
        Bloco("Anexo I."), Bloco("Art. 24. Garantias."),
        Bloco("Anexo B à Resolução CVM nº 30, de 11 de maio de 2021"),
        Bloco("Ver o Suplemento E ou Suplemento F."),
        Bloco("SUPLEMENTO A – TERMO DE CIÊNCIA"), Bloco("Declaro que [^1]"), Bloco("[^1]: Nota do suplemento.", "nota"),
    ])
    assert [p for _, p in partes] == ["Anexo Normativo I"] * 4 + ["Anexo B"] * 2 + ["Suplementos"] * 3
    assert partes[2][0] == "texto"
    assert c.dispositivos[3].rotulo == "Anexo Normativo I, art. 24"
