"""Coleta histórica (Fase 4): o que coletar do catálogo oficial e com que identificador."""

from repositorio_cvm.armazenamento import banco
from repositorio_cvm.coleta.historica import _espalhados, a_coletar, identificador

BASE = "https://conteudo.cvm.gov.br/legislacao"


def test_identificadores_seguem_o_padrao_do_acervo():
    assert identificador("resolucao", "Resolução CVM 175", f"{BASE}/resolucoes/resol175.html", 175) == "resolucao-cvm-175"
    assert identificador("parecer_orientacao", "Parecer de Orientação CVM 32", f"{BASE}/pareceres-orientacao/pare032.html",
                         32) == "parecer-orientacao-cvm-32"
    assert identificador("oficio_circular", "Ofício Circular CVM/SSE 03/26", f"{BASE}/oficios-circulares/sse1/oc-sse-0326.html",
                         None) == "oficio-circular-cvm-sse-03-2026"
    assert identificador("oficio_circular", "Ofício-Circular Conjunto CVM/SIN/SSE 01/2025",
                         f"{BASE}/oficios-circulares/sin/occ-sin-sse-0125.html", None) == "oficio-circular-conjunto-cvm-sin-sse-01-2025"
    assert identificador("nota_explicativa", "Nota Explicativa à Resolução CVM 50",
                         f"{BASE}/notas-explicativas/nota_resol050.html", None) == "nota-explicativa-resolucao-cvm-50"
    assert identificador("nota_explicativa", "Nota Explicativa à Instrução CVM 056",
                         f"{BASE}/notas-explicativas/nota056.html", None) == "nota-explicativa-instrucao-cvm-56"
    assert identificador("oficio_circular", "Ofício-Circular CVM/SNC 02/96", f"{BASE}/oficios-circulares/snc/oc-snc-0296.html",
                         None) == "oficio-circular-cvm-snc-02-1996"
    # Sem número nem título reconhecível: o nome da ficha na URL.
    assert identificador("oficio_circular", "Ofício", f"{BASE}/oficios-circulares/x/oc-xyz-9.html", None) == \
        "oficio-circular-oc-xyz-9"


def test_espalhados_cobre_do_mais_antigo_ao_mais_recente():
    assert _espalhados(list(range(100)), 5) == [0, 25, 50, 74, 99]
    assert _espalhados([1, 2], 5) == [1, 2]


def test_a_coletar_pula_o_que_ja_esta_no_acervo_e_resolve_colisao(tmp_path):
    db = banco.abrir(tmp_path / "acervo.sqlite")
    db.execute("INSERT INTO leitura_catalogo (id, familia, iniciada_em, terminada_em, status) "
               "VALUES (1, 'resolucao', 'x', 'y', 'completa'), (2, 'oficio_circular', 'x', 'y', 'completa')")
    itens = [(f"{BASE}/resolucoes/resol{n:03d}.html", "resolucao", f"Resolução CVM {n}", f"2020-01-{n:02d}", n, 1)
             for n in range(1, 11)]
    itens += [(f"{BASE}/oficios-circulares/sin/oc-sin-0118.html", "oficio_circular", "Ofício-Circular CVM/SIN 01/2018",
               "2018-01-01", None, 2),
              (f"{BASE}/oficios-circulares/sin/oc-sin-0118a.html", "oficio_circular", "Ofício Circular CVM/SIN 01/18",
               "2018-02-01", None, 2)]
    db.executemany("INSERT INTO catalogo_oficial (url, familia, titulo, data, numero, leitura_id, primeira_vez) "
                   "VALUES (?, ?, ?, ?, ?, ?, 'x')", itens)
    db.execute("INSERT INTO documento (id, especie, status_coleta, criado_em, atualizado_em, url_oficial, "
               "ultima_verificacao) VALUES ('resolucao-cvm-3', 'resolucao', 'coletado', 'x', 'x', ?, 'x')",
               (f"{BASE}/resolucoes/resol003.html",))
    atos = a_coletar(db)
    assert [a.chave for a in atos if a.especie == "resolucao"] == [f"resolucao-cvm-{n}" for n in range(1, 11) if n != 3]
    assert [a.chave for a in atos if a.especie == "oficio_circular"] == [
        "oficio-circular-cvm-sin-01-2018", "oficio-circular-cvm-sin-01-2018-oc-sin-0118a"]
    assert all(a.ficha for a in atos)
    piloto = a_coletar(db, ["resolucao"], amostra=3)
    assert [a.chave for a in piloto] == ["resolucao-cvm-1", "resolucao-cvm-5", "resolucao-cvm-10"]
    assert len(a_coletar(db, ["resolucao"], limite=4)) == 4


def test_ficha_de_instrucao_nao_atribui_arquivos_de_outras_normas():
    """Instrução 1: as marcações apontam direto para o PDF das normas citadas (caso real, ficha de 06/11/2026)."""
    from repositorio_cvm.coleta.ficha import ler_ficha

    html = """<html><body><article class="contentTextoGeral"><h2>Instrução CVM 001 (Revogada)</h2>
    <section class="contentArticle"><p>Dispõe sobre o teste.</p>
    <table><tr><td><a href="/export/sites/cvm/legislacao/instrucoes/anexos/001/inst001.pdf">Instrução CVM 001
    (redação original)</a></td></tr></table>
    <p>VIDE Instruções <a href="/export/sites/cvm/legislacao/instrucoes/anexos/001/inst015.pdf">15/80</a> .</p>
    <p>REVOGADA pela Instrução <a href="/export/sites/cvm/legislacao/instrucoes/anexos/200/inst247consolid.pdf">247/96</a> .</p>
    </section></article></body></html>"""
    ficha = ler_ficha(html.encode("utf-8"), f"{BASE}/instrucoes/inst001.html")
    assert [l.url.rsplit("/", 1)[-1] for l in ficha.links] == ["inst001.pdf"]
    assert [(r.tipo, r.alvo_titulo) for r in ficha.relacoes] == [("vide", "15/80"), ("revogada_por", "247/96")]


def test_sem_revogados_usa_a_marca_do_catalogo(tmp_path):
    db = banco.abrir(tmp_path / "acervo.sqlite")
    db.execute("INSERT INTO leitura_catalogo (id, familia, iniciada_em, terminada_em, status) "
               "VALUES (1, 'instrucao', 'x', 'y', 'completa')")
    db.executemany("INSERT INTO catalogo_oficial (url, familia, titulo, data, numero, leitura_id, primeira_vez) "
                   "VALUES (?, 'instrucao', ?, '2000-01-01', ?, 1, 'x')",
                   [(f"{BASE}/instrucoes/inst400.html", "Instrução CVM 400 (Revogada)", 400),
                    (f"{BASE}/instrucoes/inst617.html", "Instrução CVM 617", 617)])
    assert [a.chave for a in a_coletar(db, sem_revogados=True)] == ["instrucao-cvm-617"]
    assert len(a_coletar(db)) == 2
