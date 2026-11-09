"""Conversão de íntegras HTML reais e verificação de fidelidade."""

from collections import Counter
from pathlib import Path

import pytest

from repositorio_cvm.conversao.fidelidade import verificar
from repositorio_cvm.conversao.html import converter_html

FIX = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("nome", ["resol247.htm", "resol245.htm", "resol249.htm", "deli906.htm"])
def test_todas_as_palavras_do_original_estao_no_markdown(nome):
    c = converter_html((FIX / nome).read_bytes())
    resultado = verificar(c.texto_fonte, c.markdown)
    assert resultado.ok, resultado.detalhe
    assert resultado.palavras_fonte > 300


def test_fidelidade_detecta_omissao_e_troca_de_ordem():
    fonte = "Art. 1º Esta Resolução dispõe sobre fundos. Art. 2º Revoga-se a norma."
    assert not verificar(fonte, "**Art. 1º** Esta Resolução dispõe sobre fundos.").ok
    assert not verificar(fonte, "**Art. 2º** Revoga-se a norma. **Art. 1º** Esta Resolução dispõe sobre fundos.").ok
    assert verificar(fonte, "**Art. 1º** Esta Resolução dispõe sobre fundos.\n\n**Art. 2º** Revoga-se a norma.").ok


def test_resolucao_249_estrutura_de_dispositivos():
    c = converter_html((FIX / "resol249.htm").read_bytes())
    tipos = Counter(d.tipo for d in c.dispositivos)
    assert tipos["artigo"] == 26
    assert tipos["inciso"] == 99
    rotulos = [d.rotulo for d in c.dispositivos]
    assert "art. 1º, § 3º, inciso I" in rotulos
    assert "## CAPÍTULO I – ÂMBITO, FINALIDADE E CARÁTER EXPERIMENTAL" in c.markdown
    assert "**§ 1º**" in c.markdown
    assert c.vigencia_na_publicacao


def test_texto_alterado_de_outra_norma_fica_separado():
    c = converter_html((FIX / "resol247.htm").read_bytes())
    artigos = [d.artigo for d in c.dispositivos if d.tipo == "artigo"]
    assert artigos == ["1", "2", "3", "4", "5"]
    alterados = [d for d in c.dispositivos if d.tipo == "texto_alterado"]
    assert alterados and all(d.artigo in {"1", "2"} for d in alterados)
    assert any(d.texto.startswith("Art. 51-A.") for d in alterados)
    assert "> Art. 51-A." in c.markdown


def test_vigencia_com_data_expressa():
    assert converter_html((FIX / "resol247.htm").read_bytes()).vigencia_data == "2026-11-01"
    assert converter_html((FIX / "resol245.htm").read_bytes()).vigencia_data == "2026-07-15"
    deli = converter_html((FIX / "deli906.htm").read_bytes())
    assert deli.vigencia_na_publicacao and deli.vigencia_data is None


def test_legibilidade_aceita_anexo_em_tabela_e_recusa_texto_embaralhado():
    """Ofício-Circular SMI 02/2023: 3 páginas de ofício e 20 de tabela (ticker, ISIN, lote mínimo). A tabela quase
    não tem palavras comuns do português, mas é texto legível; fonte sem mapeamento Unicode continua recusada."""
    from repositorio_cvm.conversao.pdf import TextoPdf

    prosa = ("Trata-se de ofício que divulga às entidades administradoras de mercados organizados a lista de ações "
             "e ativos representativos de ações passíveis de negociação em operações com grandes lotes, e que "
             "deve ser observada pelos participantes do mercado de valores mobiliários a partir de sua publicação.")
    tabela = " ".join(f"{g} {t} {i} 8.500.000,00" for g, t, i in [("1", "VALE3", "BRVALEACNOR0"),
                      ("1", "PETR4", "BRPETRACNPR6"), ("2", "ITUB4", "BRITUBACNPR1"), ("3", "BBDC4", "BRBBDCACNPR8"),
                      ("3", "B3SA3", "BRB3SAACNOR6"), ("3", "BBAS3", "BRBBASACNOR3")] * 3)
    embaralhado = "lkjq wqer zxcv pqowi eurt yalsk djfh gzmx ncbv qpwo eiru tyal skdj fhgz mxnc bvqp woei rutyx " * 8  # página longa, como as reais

    def texto(*paginas):
        return TextoPdf(paginas=len(paginas), paragrafos=list(paginas), textos_paginas=list(paginas))

    assert texto(prosa, tabela, tabela, tabela).legibilidade()[0]
    assinatura = ("A autenticidade do documento pode ser conferida no site https://super.cvm.gov.br/"
                  "conferir_autenticidade informando o código verificador 1909583 e o código CRC 4F2A9B1C")
    assert texto(prosa, prosa, assinatura, tabela, tabela).legibilidade()[0]  # página do SEI, curta
    assert not texto(embaralhado, embaralhado).legibilidade()[0]
    assert not texto(prosa, embaralhado, embaralhado, embaralhado).legibilidade()[0]
    assert not texto(tabela, tabela).legibilidade()[0]  # sem nenhuma página de prosa, não há como conferir


def test_versao_em_ingles_nao_e_o_texto_do_ato():
    """Deliberação CVM 339: a ficha traz deli339.pdf e deli339en.pdf; a versão em inglês não é a íntegra."""
    from repositorio_cvm.coleta.coletor import _versao_em_ingles

    base = "https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/deliberacoes/anexos/0300/"
    nomes = {("integra", "pdf", "deli339"), ("integra", "pdf", "deli339en")}
    assert _versao_em_ingles({"url": base + "deli339en.pdf", "papel": "integra", "formato": "pdf"}, nomes)
    assert not _versao_em_ingles({"url": base + "deli339.pdf", "papel": "integra", "formato": "pdf"}, nomes)
    # Sem o arquivo em português ao lado, nada é descartado (um nome terminado em "en" pode ser só o nome).
    assert not _versao_em_ingles({"url": base + "deli339en.pdf", "papel": "integra", "formato": "pdf"},
                                 {("integra", "pdf", "deli339en")})
