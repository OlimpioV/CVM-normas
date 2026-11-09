"""Acervo público em Markdown (publicar-acervo): cabeçalho YAML com origem, índices e substituição segura."""

import pytest
import yaml

from repositorio_cvm import exportacao, publicacao

from tests.test_coletor import ambiente  # noqa: F401 (fixture)
from tests.test_exportacao import res21  # noqa: F401 (fixture)


def _cabecalho(texto: str) -> dict:
    assert texto.startswith("---\n")
    return yaml.safe_load(texto[4:texto.index("\n---\n", 4)])


def test_cabecalho_e_yaml_valido_com_aspas_e_listas():
    texto = publicacao.cabecalho([
        ("titulo", 'Resolução "CVM": 1\nsegunda linha'), ("numero", 21), ("vazio", ""), ("lista", []),
        ("relacoes", [{"tipo": "altera", "norma": "resolucao-cvm-9", "evidencia": None}]), ("ids", ["a", "b"])])
    dados = _cabecalho(texto + "\n")
    assert dados == {"titulo": 'Resolução "CVM": 1\nsegunda linha', "numero": 21, "vazio": None, "lista": [],
                     "relacoes": [{"tipo": "altera", "norma": "resolucao-cvm-9", "evidencia": None}], "ids": ["a", "b"]}


def test_caracteres_de_controle_viram_caractere_nao_identificado():
    assert publicacao.texto_publicavel("a\x00b\x01c\td\ne") == "a□b□c\td\ne"


def test_acervo_publico_com_origem_indices_e_regeneravel(res21, tmp_path):  # noqa: F811
    cfg, db, doc = res21
    destino = tmp_path / "publico"
    r = publicacao.gerar(cfg.pasta_dados, db, destino)
    assert r.normas == 1 and r.arquivos == 1 and r.sem_texto == 0

    [arquivo] = (destino / "acervo" / "resolucoes").rglob("resolucao-cvm-21.md")
    texto = arquivo.read_text(encoding="utf-8")
    meta = _cabecalho(texto)
    versao = doc.versao("consolidado")
    # Origem rastreável: URL e hash do arquivo oficial convertido, e o aviso de que prevalece o original.
    assert meta["id"] == "resolucao-cvm-21" and meta["situacao"] == "vigente com alterações"
    assert meta["fonte"] == versao.url_fonte and meta["fonte_sha256"] == versao.sha256
    assert meta["versao"] == versao.nome and "prevalece o original" in meta["aviso"]
    # O corpo é o Markdown aprovado, sem o cabeçalho interno do conversor; sem BOM e com fim de linha LF.
    corpo = texto[texto.index("\n---\n", 4) + 5:]
    assert corpo.strip() == (cfg.pasta_dados / versao.caminho_md).read_text(encoding="utf-8").split("\n---\n", 1)[1].strip()
    assert "\r\n" not in texto and not arquivo.read_bytes().startswith(b"\xef\xbb\xbf")

    indice = (destino / "acervo" / "resolucoes" / "README.md").read_text(encoding="utf-8")
    assert f"[texto]({arquivo.parent.name}/resolucao-cvm-21.md)" in indice
    geral = (destino / "acervo" / "README.md").read_text(encoding="utf-8")
    assert "| [Resoluções](resolucoes/README.md) | 1 | 0 | — | — | — | — |" in geral  # catálogo não lido
    assert "Todos os 1 atos do acervo têm texto integral." in geral and (destino / "COBERTURA.md").is_file()
    assert "1 atos no acervo: 1 vigentes e 0 revogados." in indice

    # Gerar de novo substitui só acervo/ e produz os mesmos arquivos (diferenças mínimas no Git).
    (destino / "README.md").write_text("meu README")
    publicacao.gerar(cfg.pasta_dados, db, destino)
    assert arquivo.read_text(encoding="utf-8") == texto
    assert (destino / "README.md").read_text() == "meu README" and not (destino / "acervo.novo").exists()


def _catalogo(db, itens):
    db.execute("INSERT INTO leitura_catalogo (id, familia, iniciada_em, terminada_em, status) "
               "VALUES (1, 'resolucao', '2026-10-28', '2026-10-28', 'completa')")
    for url, titulo in itens:
        db.execute("INSERT INTO catalogo_oficial (url, familia, titulo, leitura_id, primeira_vez) "
                   "VALUES (?, 'resolucao', ?, 1, '2026-10-28')", (url, titulo))


def test_vigentes_e_revogados_no_acervo_e_na_cvm(res21, tmp_path):  # noqa: F811
    cfg, db, doc = res21
    # No acervo, a ficha prevalece sobre a marca do catálogo (Res. 21 vigente, mesmo marcada "Revogada").
    # Fora do acervo, vale a marca do catálogo.
    _catalogo(db, [(doc.linha["url_oficial"], "Resolução CVM 21 (Revogada)"),
                   ("https://exemplo.invalid/resol001.html", "Resolução CVM 1 (Revogada)"),
                   ("https://exemplo.invalid/resol002.html", "Resolução CVM 2"),
                   ("https://exemplo.invalid/resol003.html", "Resolução CVM 3")])
    [linha] = publicacao.situacao_por_especie(db)
    assert linha == {"especie": "resolucao", "acervo_vigentes": 1, "acervo_revogados": 0,
                     "acervo_nao_verificados": 0, "cvm_vigentes": 3, "cvm_revogados": 1, "catalogo_lido": True}
    tabela = publicacao.tabela_situacao([linha], prefixo="acervo/")
    # 1 de 4 atos (25%) e 1 de 3 vigentes (33,3%); links relativos à raiz.
    assert "| [Resoluções](acervo/resolucoes/README.md) | 1 | 0 | 3 | 1 | 25,0% | 33,3% |" in tabela
    assert "| **Total** | **1** | **0** | **3** | **1** | **25,0%** | **33,3%** |" in tabela

    # Vigente com alterações e vigência futura contam como vigentes; integralmente revogada, como revogado.
    db.execute("UPDATE documento SET situacao = 'integralmente revogada'")
    [linha] = publicacao.situacao_por_especie(db)
    assert (linha["acervo_vigentes"], linha["acervo_revogados"], linha["cvm_revogados"]) == (0, 1, 2)
    assert publicacao._pct(999, 1000) == "99,9%" and publicacao._pct(9999, 10000) == "99,9%"
    assert publicacao._pct(28, 627) == "4,5%" and publicacao._pct(480, 481) == "99,8%"
    assert publicacao._pct(5, 5) == "100%" and publicacao._milhar(1366) == "1.366"


def test_readme_principal_so_tem_o_trecho_marcado_atualizado(res21, tmp_path):  # noqa: F811
    cfg, db, _ = res21
    destino = tmp_path / "publico"
    destino.mkdir()
    antes, depois = "# Meu projeto\n\nTexto meu.\n\n", "\n\nMais texto meu.\n"
    readme = destino / "README.md"
    readme.write_text(antes + publicacao.INICIO_TABELA + "\ntabela antiga\n" + publicacao.FIM_TABELA + depois,
                      encoding="utf-8")
    publicacao.gerar(cfg.pasta_dados, db, destino)
    texto = readme.read_text(encoding="utf-8")
    assert texto.startswith(antes + publicacao.INICIO_TABELA) and texto.endswith(publicacao.FIM_TABELA + depois)
    assert "tabela antiga" not in texto and "| **Total** | **1** | **0** |" in texto
    assert "Posição em 27/10/2026" in texto  # data da última verificação da ficha, não a data da geração
    # Gerar de novo não muda nada (saída determinística).
    publicacao.gerar(cfg.pasta_dados, db, destino)
    assert readme.read_text(encoding="utf-8") == texto

    # Sem marcadores, o README não é tocado e fica um aviso.
    readme.write_text("README sem marcadores", encoding="utf-8")
    r = publicacao.gerar(cfg.pasta_dados, db, destino)
    assert readme.read_text(encoding="utf-8") == "README sem marcadores" and r.avisos


def test_nao_apaga_acervo_que_nao_foi_gerado_pelo_comando(res21, tmp_path):  # noqa: F811
    cfg, db, _ = res21
    alheia = tmp_path / "publico" / "acervo"
    alheia.mkdir(parents=True)
    (alheia / "meu.md").write_text("não apagar")
    with pytest.raises(RuntimeError, match="nada foi apagado"):
        publicacao.gerar(cfg.pasta_dados, db, tmp_path / "publico")
    assert (alheia / "meu.md").read_text() == "não apagar"


def test_fontes_do_pdf_em_outros_sistemas(tmp_path, monkeypatch):
    nomes = ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"]
    for n in nomes:
        (tmp_path / n).write_bytes(b"")
    estilos = {"": nomes[0], "B": nomes[1], "I": nomes[2], "BI": nomes[3]}
    monkeypatch.setattr(exportacao, "CONJUNTOS_FONTES", [
        ([tmp_path / "inexistente"], {"": "arial.ttf"}, "seguisym.ttf"), ([tmp_path], estilos, "DejaVuSans.ttf")])
    fontes, simbolos = exportacao.localizar_fontes()
    assert fontes["B"] == tmp_path / "DejaVuSans-Bold.ttf" and simbolos == tmp_path / "DejaVuSans.ttf"
    monkeypatch.setattr(exportacao, "CONJUNTOS_FONTES", [([tmp_path / "inexistente"], {"": "arial.ttf"}, "x.ttf")])
    with pytest.raises(exportacao.ExportacaoError, match="DejaVu"):
        exportacao.localizar_fontes()
