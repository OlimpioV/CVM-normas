"""Justificativas de dispensa de AIR citadas na ficha (D-24): PDF anexo e página da decisão do Colegiado.

Fixtures reais da CVM: fichas e íntegras das Res. 233 e 245, a justificativa em PDF da Res. 245 e a página da
decisão do Colegiado (Reg. 3308/25) citada na ficha da Res. 233.
"""

import yaml
from fastapi.testclient import TestClient

from repositorio_cvm import biblioteca, justificativas, publicacao
from repositorio_cvm.coleta.justificativas import ColetorJustificativas, links_da_ficha, paragrafos_da_decisao
from repositorio_cvm.web.app import criar_app

from tests.test_coletor import B, FIX, HTML, ambiente, ato  # noqa: F401 (fixture)

DECISAO = "https://conteudo.cvm.gov.br/decisoes/2025/20250708_R1/20250708_D3308.html"
PDF_245 = "https://conteudo.cvm.gov.br/export/sites/cvm/legislacao/resolucoes/anexos/200/resol245_Justificativa_DispensaAIR.pdf"
ROTULO = "Justificativa - Dispensa de Análise de Impacto Regulatório (AIR)"


def test_link_da_justificativa_na_ficha():
    assert links_da_ficha((FIX / "resol233.html").read_bytes(), f"{B}/resolucoes/resol233.html") == [(ROTULO, DECISAO)]
    assert links_da_ficha((FIX / "resol245.html").read_bytes(), f"{B}/resolucoes/resol245.html") == [(ROTULO, PDF_245)]
    # Ficha sem o link: nada (não prova que não houve justificativa).
    assert links_da_ficha((FIX / "resol050.html").read_bytes(), f"{B}/resolucoes/resol050.html") == []


def test_texto_da_decisao_do_colegiado_sem_menus_do_portal():
    p = paragrafos_da_decisao((FIX / "decisao-20250708_D3308.html").read_bytes())
    texto = " ".join(p)
    assert "Trata-se de proposta de edição da Resolução CVM nº 233/2025" in texto
    assert "Análise de Impacto Regulatório - AIR, nos termos do art. 3º, § 2º, I, do Decreto nº 10.411/2020" in texto
    assert "O Colegiado, por unanimidade, aprovou a edição da Resolução CVM nº 233/2025." in p
    assert not any(menu in p for menu in ("Facebook", "Mapa do Site", "Busca Avançada"))


def test_coleta_conversao_interface_biblioteca_e_acervo(ambiente, tmp_path):  # noqa: F811
    cfg, db, criar = ambiente
    PDF = {"Content-Type": "application/pdf"}
    coletor = criar({
        f"{B}/resolucoes/resol233.html": (200, HTML, (FIX / "resol233.html").read_bytes(), "OK"),
        f"{B}/resolucoes/anexos/200/resol233.htm": (200, HTML, (FIX / "resol233.htm").read_bytes(), "OK"),
        f"{B}/resolucoes/resol245.html": (200, HTML, (FIX / "resol245.html").read_bytes(), "OK"),
        f"{B}/resolucoes/anexos/200/resol245.htm": (200, HTML, (FIX / "resol245.htm").read_bytes(), "OK"),
        DECISAO: (200, HTML, (FIX / "decisao-20250708_D3308.html").read_bytes(), "OK"),
        PDF_245: (200, PDF, (FIX / "resol245_Justificativa_DispensaAIR.pdf").read_bytes(), "OK"),
    })
    for n in ("233", "245"):
        assert coletor.coletar_ato(ato(f"resolucao-cvm-{n}", "resolucao", f"{B}/resolucoes/resol{n}.html", n)).status

    contagem = ColetorJustificativas(coletor).executar(["resolucao-cvm-233", "resolucao-cvm-245"])
    assert contagem["justificativas citadas"] == 2 and contagem["baixada"] == 2

    [j233] = justificativas.justificativas_do_documento(db, "resolucao-cvm-233")
    [j245] = justificativas.justificativas_do_documento(db, "resolucao-cvm-245")
    assert (j233["formato"], j245["formato"]) == ("html", "pdf") and j233["fidelidade_ok"] and j245["fidelidade_ok"]
    # A ligação com a norma tem evidência: a ficha oficial que cita a justificativa.
    assert j233["evidencia_url"] == f"{B}/resolucoes/resol233.html" and j233["evidencia_trecho"] == ROTULO
    assert any("Impacto Regulatório" in p for p in justificativas.paragrafos(cfg.pasta_dados, j245))

    # Retomada: nada é baixado de novo.
    pedidos = len(coletor.cliente._abridor.pedidos)
    assert ColetorJustificativas(coletor).executar(["resolucao-cvm-233"])["já baixada"] == 1
    assert len(coletor.cliente._abridor.pedidos) == pedidos

    db.commit()
    cliente = TestClient(criar_app(cfg))
    pagina = cliente.get("/norma/resolucao-cvm-233").text
    assert "Justificativa de dispensa de AIR" in pagina and "aprovou a edição da Resolução CVM nº 233/2025" in pagina
    api = cliente.get("/api/norma/resolucao-cvm-233").json()
    assert api["justificativas_air"][0]["url"] == DECISAO

    # Biblioteca: o original e a conversão na pasta da norma, sem duplicar o arquivo como se fosse da norma.
    raiz = biblioteca.gerar(cfg.pasta_dados, db).pasta
    nomes = {p.name for p in (raiz / "Resoluções" / "Resolução CVM 245").iterdir()}
    assert {"Justificativa - Dispensa de AIR.pdf", "Justificativa - Dispensa de AIR (conversão).md"} <= nomes
    assert "Justificativa.pdf" not in nomes

    # Acervo público: arquivo próprio, citado no cabeçalho da norma e no índice da espécie.
    destino = tmp_path / "publico"
    r = publicacao.gerar(cfg.pasta_dados, db, destino)
    arquivo = destino / "acervo" / "justificativas-air" / "2025" / "resolucao-cvm-233.md"
    texto = arquivo.read_text(encoding="utf-8")
    meta = yaml.safe_load(texto[4:texto.index("\n---\n", 4)])
    assert meta["norma"] == "resolucao-cvm-233" and meta["documentos"][0]["url"] == DECISAO
    assert meta["documentos"][0]["sha256"] == j233["sha256"] and "Decreto nº 10.411/2020" in texto
    [norma] = (destino / "acervo" / "resolucoes").rglob("resolucao-cvm-233.md")
    cab = norma.read_text(encoding="utf-8")
    assert yaml.safe_load(cab[4:cab.index("\n---\n", 4)])["justificativa_air"] == "justificativas-air/2025/resolucao-cvm-233.md"
    assert "[justificativa AIR](../justificativas-air/2025/resolucao-cvm-233.md)" in \
        (destino / "acervo" / "resolucoes" / "README.md").read_text(encoding="utf-8")
    assert "2 [justificativas de dispensa" in (destino / "acervo" / "README.md").read_text(encoding="utf-8")
    assert r.arquivos >= 4


def test_justificativa_indisponivel_fica_registrada_sem_interromper(ambiente):  # noqa: F811
    _, db, criar = ambiente
    coletor = criar({
        f"{B}/resolucoes/resol233.html": (200, HTML, (FIX / "resol233.html").read_bytes(), "OK"),
        f"{B}/resolucoes/anexos/200/resol233.htm": (200, HTML, (FIX / "resol233.htm").read_bytes(), "OK"),
        DECISAO: (404, {}, b"", "Not Found"),
    })
    assert coletor.coletar_ato(ato("resolucao-cvm-233", "resolucao", f"{B}/resolucoes/resol233.html", "233")).status
    assert ColetorJustificativas(coletor).executar(["resolucao-cvm-233"])["indisponível"] == 1
    [j] = justificativas.justificativas_do_documento(db, "resolucao-cvm-233")
    assert j["status"] == "indisponível" and j["arquivo_id"] is None
