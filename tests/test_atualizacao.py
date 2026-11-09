"""Atualização incremental sem rede: fichas e íntegras reais servidas por opener falso, com variações."""

from repositorio_cvm.coleta.atualizacao import Atualizador, relatorio_markdown
from repositorio_cvm.coleta.catalogo import url_catalogo

from tests.test_coletor import B, FIX, HTML, ambiente, ato  # noqa: F401 (fixture)

FICHA_906 = f"{B}/deliberacoes/deli0900/deli906.html"
INTEGRA_906 = f"{B}/deliberacoes/anexos/0900/deli906.htm"
FICHA_50 = f"{B}/resolucoes/resol050.html"


def _servir(url, corpo):
    return {url: (200, HTML, corpo, "OK")}


def test_ficha_sem_mudanca_de_conteudo_so_registra_a_verificacao(ambiente):  # noqa: F811
    _, db, criar = ambiente
    criar().coletar_ato(ato("deliberacao-cvm-906", "deliberacao", FICHA_906, "906"))
    arquivos = db.execute("SELECT COUNT(*) FROM arquivo").fetchone()[0]
    # HTML bruto diferente (comentário) com o mesmo conteúdo: não é alteração (D-10).
    ficha = (FIX / "deli906.html").read_bytes().replace(b"</body>", b"<!-- gerado em outra data --></body>")
    mudancas = Atualizador(criar(_servir(FICHA_906, ficha))).reverificar("deliberacao-cvm-906")
    assert [m.tipo for m in mudancas] == ["sem alteração"]
    assert db.execute("SELECT COUNT(*) FROM arquivo").fetchone()[0] == arquivos


def test_relacao_nova_e_revogacao_na_ficha_sao_detectadas(ambiente):  # noqa: F811
    _, db, criar = ambiente
    criar().coletar_ato(ato("resolucao-cvm-50", "resolucao", FICHA_50, "50"))
    assert db.execute("SELECT situacao FROM documento").fetchone()[0] == "vigente com alterações"
    original = (FIX / "resol050.html").read_bytes()
    alterada = original.replace(
        '<a href="/legislacao/resolucoes/resol245.html" target="_blank">245/26</a>'.encode(),
        '<a href="/legislacao/resolucoes/resol245.html" target="_blank">245/26</a>, '
        '<a href="/legislacao/resolucoes/resol250.html" target="_blank">250/26</a>'.encode())
    assert alterada != original
    mudancas = Atualizador(criar(_servir(FICHA_50, alterada))).reverificar("resolucao-cvm-50")
    assert any(m.tipo == "relação nova" and "250" in m.detalhe for m in mudancas)
    assert db.execute("SELECT COUNT(*) FROM arquivo WHERE papel = 'ficha'").fetchone()[0] == 2  # nova ficha guardada

    revogada = alterada.replace("ALTERADA pelas".encode(), "REVOGADA pelas".encode())
    mudancas = Atualizador(criar(_servir(FICHA_50, revogada))).reverificar("resolucao-cvm-50")
    situacao = [m for m in mudancas if m.tipo == "situação"]
    assert situacao and "possível revogação" in situacao[0].detalhe
    assert "revogada" in db.execute("SELECT situacao FROM documento").fetchone()[0]
    # Histórico preservado: a evidência da situação anterior continua registrada.
    assert db.execute("SELECT COUNT(*) FROM evidencia WHERE campo = 'situacao'").fetchone()[0] >= 2


def test_integra_alterada_gera_nova_versao_com_diferencas(ambiente):  # noqa: F811
    _, db, criar = ambiente
    criar().coletar_ato(ato("deliberacao-cvm-906", "deliberacao", FICHA_906, "906"))
    versoes = db.execute("SELECT COUNT(*) FROM versao_texto").fetchone()[0]
    integra = (FIX / "deli906.htm").read_bytes()
    assert b"Eco Invest" in integra
    nova = integra.replace(b"Eco Invest", b"Eco Investimento", 1)
    mudancas = Atualizador(criar(_servir(INTEGRA_906, nova)), arquivos=True).reverificar("deliberacao-cvm-906")
    tipos = [m.tipo for m in mudancas]
    assert "arquivo novo" in tipos and "texto alterado" in tipos
    texto = next(m for m in mudancas if m.tipo == "texto alterado").detalhe
    assert "1 alterado" in texto and "Eco [Invest → Investimento] Brasil" in texto
    assert db.execute("SELECT COUNT(*) FROM versao_texto").fetchone()[0] == versoes + 1  # anterior preservada
    # Sem nova alteração, a segunda passagem não muda nada.
    de_novo = Atualizador(criar(_servir(INTEGRA_906, nova)), arquivos=True).reverificar("deliberacao-cvm-906")
    assert [m.tipo for m in de_novo] == ["sem alteração"]


def test_catalogo_lido_pela_primeira_vez_vira_base_e_depois_aponta_novidades(ambiente):  # noqa: F811
    _, db, criar = ambiente
    catalogo = (FIX / "oc-cat1.html").read_bytes()
    url = url_catalogo("oficio_circular", 1)
    novas, primeiras = Atualizador(criar(_servir(url, catalogo))).novidades(["oficio_circular"])
    assert novas == [] and primeiras == ["oficio_circular"]
    base = db.execute("SELECT COUNT(*) FROM catalogo_visto").fetchone()[0]
    assert base > 0
    # Um item sai da página e outro entra: só o que entrou é novidade.
    alterado = catalogo.replace(b"oc-sse-0326.html", b"oc-sse-0426.html", 1)
    novas, primeiras = Atualizador(criar(_servir(url, alterado))).novidades(["oficio_circular"])
    assert primeiras == [] and [n["url"].rsplit("/", 1)[-1] for n in novas] == ["oc-sse-0426.html"]


def test_execucao_completa_gera_relatorio(ambiente):  # noqa: F811
    _, db, criar = ambiente
    criar().coletar_ato(ato("deliberacao-cvm-906", "deliberacao", FICHA_906, "906"))
    resultado = Atualizador(criar()).executar(novidades=False)
    assert resultado.resumo()["sem alteração"] == 1
    md = relatorio_markdown(resultado, "inicio", "fim")
    assert "Nenhuma alteração detectada." in md and "deliberacao-cvm-906" in md


def test_restaurar_guarda_o_banco_atual_antes(tmp_path, monkeypatch):
    from repositorio_cvm import cli, config
    from repositorio_cvm.armazenamento import banco

    cfg = config.Config(pasta_dados=tmp_path / "dados")
    monkeypatch.setattr(config, "carregar", lambda *a, **k: cfg)
    db = banco.abrir(cfg.banco, cfg.backups)
    db.execute("INSERT INTO coleta (escopo, iniciada_em, status) VALUES ('antes', 'x', 'concluída')")
    db.commit()
    copia = banco.fazer_backup(db, cfg.backups)
    db.execute("INSERT INTO coleta (escopo, iniciada_em, status) VALUES ('depois', 'x', 'concluída')")
    db.commit()
    db.close()
    assert cli.main(["restaurar", copia.name]) == 1  # sem --confirmar não altera nada
    assert cli.main(["restaurar", copia.name, "--confirmar"]) == 0
    db = banco.abrir(cfg.banco, cfg.backups)
    assert [r[0] for r in db.execute("SELECT escopo FROM coleta")] == ["antes"]
    guardada = next(cfg.backups.glob("*antes-restauracao.sqlite"))
    import sqlite3
    assert [r[0] for r in sqlite3.connect(guardada).execute("SELECT escopo FROM coleta")] == ["antes", "depois"]


def _catalogo_em_duas_paginas():
    """Página real do catálogo de ofícios, reduzida a 2 páginas: a 2ª com os mesmos atos em outro endereço."""
    real = (FIX / "oc-cat1.html").read_bytes()
    p1 = real.replace("601 resultados".encode(), b"20 resultados").replace("Páginas 1/61".encode(), "Páginas 1/2".encode())
    p2 = p1.replace("Páginas 1/2".encode(), "Páginas 2/2".encode()).replace(
        b'href="/legislacao/oficios-circulares/', b'href="/legislacao/oficios-circulares/antigos/')
    return p1, p2


def test_leitura_completa_do_catalogo_e_cobertura(ambiente):  # noqa: F811
    from repositorio_cvm.coleta.inventario import familias_a_ler, ler_catalogo
    from repositorio_cvm.relatorios import cobertura, faltantes

    _, db, criar = ambiente
    coletor = criar()
    item =coletor.localizar_oficios([ato("oficio-circular-cvm-sse-03-2026", "oficio_circular", numero="3",
                                          areas=frozenset({"SSE"}), ano=2026)])
    coletor.coletar_ato(ato("oficio-circular-cvm-sse-03-2026", "oficio_circular", numero="3"),
                        item["oficio-circular-cvm-sse-03-2026"])
    p1, p2 = _catalogo_em_duas_paginas()
    rotas = {url_catalogo("oficio_circular", 1): (200, HTML, p1, "OK"),
             url_catalogo("oficio_circular", 2): (200, HTML, p2, "OK")}
    r = ler_catalogo(criar(rotas), "oficio_circular")
    assert r["status"] == "completa" and r["total_lido"] == r["total_informado"] == 20
    assert familias_a_ler(db, ["oficio_circular", "resolucao"], refazer=False) == ["resolucao"]  # retomada

    dados = cobertura(db)
    oficios = next(f for f in dados["familias"] if f["familia"] == "oficio_circular")
    assert (oficios["catalogo"], oficios["no_acervo"], oficios["pct"]) == (20, 1, 5.0)
    assert "resolucao" in dados["aviso"]  # espécies não lidas são apontadas
    assert len(faltantes(db, "oficio_circular")) == 19
    assert any(l["familia"] == "oficio_circular" and l["ano"] == "2026" for l in dados["linhas"])


def test_leitura_com_total_divergente_fica_incompleta(ambiente):  # noqa: F811
    from repositorio_cvm.coleta.inventario import ler_catalogo
    from repositorio_cvm.relatorios import cobertura

    _, db, criar = ambiente
    p1, _ = _catalogo_em_duas_paginas()
    # A 2ª página repete os atos da 1ª (catálogo mudou durante a leitura): 10 distintos de 20 informados.
    rotas = {url_catalogo("oficio_circular", 1): (200, HTML, p1, "OK"),
             url_catalogo("oficio_circular", 2): (200, HTML, p1.replace("Páginas 1/2".encode(), "Páginas 2/2".encode()), "OK")}
    r = ler_catalogo(criar(rotas), "oficio_circular")
    assert r["status"] == "incompleta" and r["total_lido"] == 10
    assert "oficio_circular" in cobertura(db)["aviso"]


def test_numeros_ausentes_do_catalogo():
    from repositorio_cvm.coleta.inventario import numero_do_titulo
    from repositorio_cvm.relatorios import _intervalos

    assert numero_do_titulo("resolucao", "Resolução CVM 175") == 175
    assert numero_do_titulo("instrucao", "Instrução CVM 627 (Revogada)") == 627
    assert numero_do_titulo("parecer_orientacao", "Parecer de Orientação CVM 41") == 41
    assert numero_do_titulo("oficio_circular", "Ofício Circular CVM/SSE 03/26") is None
    assert _intervalos([1, 2, 3, 7, 9, 10]) == "1–3, 7, 9–10"


def test_total_divergente_informado_pela_propria_cvm(ambiente):  # noqa: F811
    """Caso real (28/10/2026): a página 1 dos ofícios informa 601 resultados em 61 páginas; as demais, 600 em 60."""
    from repositorio_cvm.coleta.inventario import familias_a_ler, ler_catalogo

    _, db, criar = ambiente
    p1, p2 = _catalogo_em_duas_paginas()
    p1 = p1.replace(b"20 resultados", b"21 resultados").replace("Páginas 1/2".encode(), "Páginas 1/3".encode())
    vazia = p2.replace("Páginas 2/2".encode(), "Páginas 3/3".encode())
    vazia = vazia[:vazia.index(b"<article")] + vazia[vazia.rindex(b"</article>") + len(b"</article>"):]
    rotas = {url_catalogo("oficio_circular", 1): (200, HTML, p1, "OK"),
             url_catalogo("oficio_circular", 2): (200, HTML, p2, "OK"),
             url_catalogo("oficio_circular", 3): (200, HTML, vazia, "OK")}
    r = ler_catalogo(criar(rotas), "oficio_circular")
    assert r["status"] == "divergente na fonte" and r["total_lido"] == 20
    assert "informa totais diferentes na mesma pesquisa: 21 (página 1); 20 (páginas 2 a 3)" in r["observacao"]
    assert familias_a_ler(db, ["oficio_circular"], refazer=False) == []
