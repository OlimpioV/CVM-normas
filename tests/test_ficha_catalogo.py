"""Fichas e catálogo reais da CVM (fixtures salvas em 27/10/2026)."""

from pathlib import Path

import pytest

from repositorio_cvm.coleta.catalogo import ler_pagina_catalogo, url_catalogo
from repositorio_cvm.coleta.ficha import converter_data_curta, ler_ficha

FIX = Path(__file__).parent / "fixtures"
BASE = "https://conteudo.cvm.gov.br/legislacao"


def ficha(nome, caminho):
    return ler_ficha((FIX / nome).read_bytes(), f"{BASE}/{caminho}")


def test_resolucao_50_metadados_e_marcacoes():
    f = ficha("resol050.html", "resolucoes/resol050.html")
    assert f.titulo == "Resolução CVM 50"
    assert f.data_edicao == "2021-08-31"
    assert f.data_publicacao == "2021-09-02"
    assert f.ementa.startswith("Dispõe sobre a prevenção à lavagem de dinheiro")
    assert "Publicada" not in f.ementa
    assert f.assuntos == ["PLD/FTP"]
    assert f.integra_html is None
    tipos = [(r.tipo, r.alvo_url.rsplit("/", 1)[-1]) for r in f.relacoes]
    assert ("revoga", "inst617.html") in tipos
    assert ("vide", "nota_resol050.html") in tipos
    assert ("alterada_por", "resol179.html") in tipos and ("alterada_por", "resol245.html") in tipos
    assert not any(t == "revogada_por" for t, _ in tipos)
    papeis = {(l.papel, l.formato) for l in f.links}
    assert ("consolidado", "pdf") in papeis and ("original", "pdf") in papeis


def test_resolucao_175_retificacao_republicacao_e_alteracoes():
    f = ficha("resol175.html", "resolucoes/resol175.html")
    eventos = {(e.evento, e.veiculo, e.data) for e in f.eventos}
    assert ("publicacao", "DOU", "2022-12-28") in eventos
    assert ("retificacao", "DOU", "2023-03-31") in eventos
    alteradoras = [r.alvo_titulo for r in f.relacoes if r.tipo == "alterada_por"]
    assert alteradoras == ["181/23", "184/23", "187/23", "200/24", "206/24", "209/24", "214/24", "240/26"]
    assert f.integra_html is None


def test_resolucao_247_integra_html_e_relacoes_da_ementa():
    f = ficha("resol247.html", "resolucoes/resol247.html")
    assert f.data_edicao == "2026-10-02"
    assert f.data_publicacao == "2026-10-06"
    assert f.integra_html.url == f"{BASE}/resolucoes/anexos/200/resol247.htm"
    alvos = {(r.tipo, r.alvo_url.rsplit("/", 1)[-1]) for r in f.relacoes}
    assert alvos == {("altera", "resol060.html"), ("altera", "resol175.html")}


def test_parecer_com_ano_de_dois_digitos_no_dou():
    f = ficha("pare032.html", "pareceres-orientacao/pare032.html")
    assert f.data_edicao == "2005-09-30"
    assert f.data_publicacao == "2005-10-17"  # "(Publicado no DOU de 17.10.05)"
    assert [l.papel for l in f.links] == ["integra", "integra"]
    assert f.integra_html is None


def test_oficio_e_nota_sem_dou_nao_inventam_publicacao():
    of = ficha("oc-sse-0326.html", "oficios-circulares/sse1/oc-sse-0326.html")
    assert of.data_publicacao is None
    assert "Fundos de Investimento em Direitos Creditórios" in of.assuntos
    nota = ficha("nota_resol050.html", "notas-explicativas/nota_resol050.html")
    assert nota.titulo == "Nota Explicativa à Resolução CVM 50"
    assert nota.data_publicacao is None


@pytest.mark.parametrize("valor,esperado", [("02.09.2021", "2021-09-02"), ("17.10.05", "2005-10-17"),
                                            ("09.01.04", "2004-01-09"), ("31.02.2021", None), ("01.01.77", "1977-01-01")])
def test_datas_curtas(valor, esperado):
    assert converter_data_curta(valor) == esperado


def test_catalogo_de_oficios_paginacao_e_itens():
    url = url_catalogo("oficio_circular", 1)
    assert "vimDaCategoria=/legislacao/oficios-circulares/" in url and url.endswith("searchPage=1")
    pagina = ler_pagina_catalogo((FIX / "oc-cat1.html").read_bytes(), url)
    assert (pagina.pagina, pagina.total_paginas, pagina.total_resultados) == (1, 61, 601)
    assert len(pagina.itens) == 10
    sse = next(i for i in pagina.itens if i.titulo == "Ofício Circular CVM/SSE 03/26")
    assert sse.url == f"{BASE}/oficios-circulares/sse1/oc-sse-0326.html"
    assert sse.data and sse.data.startswith("2026-")
