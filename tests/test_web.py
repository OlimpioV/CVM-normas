"""Interface web local: rotas de pesquisa, norma, exportação, relatórios e API JSON (sem rede)."""

from fastapi.testclient import TestClient

from repositorio_cvm.web.app import ancora_texto, criar_app

from tests.test_exportacao import res21  # noqa: F401 (fixture)
from tests.test_coletor import ambiente  # noqa: F401 (fixture)


def _cliente(res21):  # noqa: F811
    cfg, db, _ = res21
    db.commit()
    return TestClient(criar_app(cfg))


def test_pesquisa_por_referencia_e_por_palavras(res21):  # noqa: F811
    cliente = _cliente(res21)
    pagina = cliente.get("/", params={"q": "Resolução CVM 21, artigo 1"})
    assert pagina.status_code == 200
    assert "art. 1º" in pagina.text and "/norma/resolucao-cvm-21" in pagina.text and "#:~:text=" in pagina.text
    assert "Norma localizada" in pagina.text
    palavras = cliente.get("/", params={"q": "administração de carteiras", "especie": "resolucao"})
    assert "<mark>" in palavras.text and "resultado" in palavras.text
    vazio = cliente.get("/", params={"q": "xyzinexistente"})
    assert "Nenhum resultado no acervo local" in vazio.text


def test_pagina_da_norma_mostra_texto_metadados_origem_e_exportacao(res21):  # noqa: F811
    cliente = _cliente(res21)
    pagina = cliente.get("/norma/resolucao-cvm-21")
    assert pagina.status_code == 200
    texto = pagina.text
    # Padrão: a consolidada, só com o texto vigente; a versão com a redação anterior riscada continua acessível.
    assert "Consolidada (texto vigente)" in texto and "<s>" not in texto and "~~" not in texto
    assert "?versao=oficial" in texto
    oficial = cliente.get("/norma/resolucao-cvm-21", params={"versao": "oficial"}).text
    assert "Alterada, com tachado (consolidado oficial da CVM)" in oficial and "<s>" in oficial
    assert "vigente com alterações" in texto and "confirme a vigência" in texto
    assert "/norma/resolucao-cvm-21/exportar/docx?versao=consolidado" in texto
    assert "origem" in texto
    assert cliente.get("/norma/nao-existe").status_code == 404


def test_exportacao_pela_interface(res21):  # noqa: F811
    cliente = _cliente(res21)
    docx = cliente.get("/norma/resolucao-cvm-21/exportar/docx")
    assert docx.status_code == 200
    assert 'filename="resolucao-cvm-21-consolidado.docx"' in docx.headers["content-disposition"]
    assert docx.content[:2] == b"PK"
    assert cliente.get("/norma/resolucao-cvm-21/exportar/xls").status_code == 422


def test_api_devolve_trecho_com_identificacao_e_fonte(res21):  # noqa: F811
    cliente = _cliente(res21)
    resposta = cliente.get("/api/pesquisa", params={"q": "Resolução CVM 21, artigo 1", "limite": 2}).json()
    item = resposta["resultados"][0]
    assert item["norma"] and item["dispositivo"].startswith("art. 1")
    assert item["redacao"].startswith("Art. 1")
    assert item["url_fonte"].endswith("resol021consolid.docx") and item["data_referencia"]
    assert "prevalece o original" in resposta["aviso"]
    norma = cliente.get("/api/norma/resolucao-cvm-21").json()
    assert norma["documento"]["situacao"] == "vigente com alterações" and norma["versoes"]


def test_relatorios_e_lista_de_normas(res21):  # noqa: F811
    cliente = _cliente(res21)
    relatorio = cliente.get("/relatorios").text
    assert "Cobertura do acervo em relação à CVM" in relatorio and "ainda não foi lido" in relatorio
    assert cliente.get("/relatorios/faltantes", params={"familia": "resolucao"}).status_code == 200
    assert cliente.get("/relatorios/faltantes", params={"familia": "xyz"}).status_code == 404
    normas = cliente.get("/normas", params={"especie": "resolucao"})
    # A Res. 21 da fixture tem o consolidado oficial (alterada) e a consolidada derivada dele, sem a original.
    assert normas.status_code == 200 and "alterada (tachado), consolidada" in normas.text


def test_ancora_de_texto_codifica_hifen():
    assert ancora_texto("I – o regulamento deve-se") == "#:~:text=I%20%E2%80%93%20o%20regulamento%20deve%2Dse"
    assert ancora_texto(None) == ""
