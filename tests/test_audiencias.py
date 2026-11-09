"""Audiências públicas (edital, prazo, fase, relatório; sem manifestações) e partes das normas com anexos."""

from pathlib import Path

from fastapi.testclient import TestClient
from fpdf import FPDF

from repositorio_cvm import acervo, audiencias, exportacao
from repositorio_cvm.coleta.audiencias import ColetorAudiencias, id_audiencia, ler_pagina_audiencia, prazo_do_edital
from repositorio_cvm.coleta.ficha import ler_ficha
from repositorio_cvm.web.app import criar_app

from tests.test_coletor import B, HTML, ambiente, ato  # noqa: F401 (fixture)
from tests.test_exportacao import res21  # noqa: F401 (fixture)

FIX = Path(__file__).parent / "fixtures"
AP = "https://conteudo.cvm.gov.br/audiencias_publicas/ap_sdm"
ANEXOS = "https://conteudo.cvm.gov.br/export/sites/cvm/audiencias_publicas/ap_sdm/anexos"


def test_ficha_indica_as_audiencias_com_o_trecho_de_evidencia():
    ficha = ler_ficha((FIX / "resol175.html").read_bytes(), f"{B}/resolucoes/resol175.html")
    assert [(a.codigo, a.url) for a in ficha.audiencias] == [
        ("SDM 08/20", f"{AP}/2020/sdm0820.html"), ("SDM 08/21", f"{AP}/2021/sdm0821.html")]
    assert ficha.audiencias[0].trecho == "AUDIÊNCIAS PÚBLICAS: SDM 08/20 e SDM 08/21"
    assert not any("audiencias_publicas" in l.url for l in ficha.links)
    assert id_audiencia(f"{AP}/2020/sdm0820.html") == "sdm-2020-sdm0820"


def test_pagina_da_audiencia_le_secoes_e_ignora_manifestacoes():
    p = ler_pagina_audiencia((FIX / "ap-sdm0820.html").read_bytes(), f"{AP}/2020/sdm0820.html")
    assert p.codigo == "SDM 08/20" and p.fase == "Norma publicada"
    assert p.tema.startswith("Minuta de resolução que dispõem sobre a constituição")
    assert (p.prazo, p.prazo_texto) == ("2021-04-15", "Thu Apr 15 23:59:00 BRT 2021")
    assert p.secoes[:3] == ["Edital", "Tema", "Attachments (english version)"]
    por_secao = {}
    for l in p.links:
        por_secao.setdefault(l.secao, []).append(l.rotulo)
    assert len(por_secao["edital"]) == 2 and "Aviso de Prorrogação" in por_secao["edital"][1]
    assert len(por_secao["versão em inglês"]) == 2
    assert por_secao["relatório"][0].startswith("Relatório da Audiência Pública SDM 08/20 (Revisado")
    assert por_secao["norma editada"] == ["Resolução CVM 175"]
    assert "manifestações" not in por_secao and not any("ABRAPP" in l.url for l in p.links)
    # Prazo como o servidor exibe (fuso de horário de verão): guardado sem correção.
    p21 = ler_pagina_audiencia((FIX / "ap-sdm0821.html").read_bytes(), f"{AP}/2021/sdm0821.html")
    assert (p21.prazo, p21.prazo_texto) == ("2022-02-12", "Sat Feb 12 00:59:00 BRST 2022")


def test_prazo_declarado_no_edital():
    assert prazo_do_edital("EDITAL DE AUDIÊNCIA PÚBLICA SDM Nº 08/20\nPrazo: 2 de abril de 2021\nObjeto: x") == (
        "2021-04-02", "Prazo: 2 de abril de 2021")
    assert prazo_do_edital("Sem linha de prazo.") == (None, None)


def _pdf(*linhas: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    for linha in linhas:
        pdf.multi_cell(0, 6, linha)
        pdf.ln(3)
    return bytes(pdf.output())


def test_coleta_da_audiencia_de_ponta_a_ponta(ambiente):  # noqa: F811
    cfg, db, criar = ambiente
    PDF = {"Content-Type": "application/pdf"}
    corpo = ("A Comissão de Valores Mobiliários submete à audiência pública minuta de resolução sobre a constituição, "
             "o funcionamento e a divulgação de informações dos fundos de investimento. ") * 6
    edital = _pdf("EDITAL DE AUDIÊNCIA PÚBLICA SDM Nº 08/20", "Prazo: 2 de abril de 2021", corpo)
    relatorio = _pdf("RELATÓRIO DE ANÁLISE", "Audiência Pública SDM nº 08/20", corpo + "Taxa de performance. ")
    extra = {
        f"{AP}/2020/sdm0820.html": (200, HTML, (FIX / "ap-sdm0820.html").read_bytes(), "OK"),
        f"{AP}/2021/sdm0821.html": (200, HTML, (FIX / "ap-sdm0821.html").read_bytes(), "OK"),
        f"{ANEXOS}/2020/SDM0820_Edital_20201203.pdf": (200, PDF, edital, "OK"),
        f"{ANEXOS}/2020/sdm0820_edital_aviso_prorrogacao.pdf": (200, PDF, _pdf("Aviso de prorrogação.", corpo), "OK"),
        f"{ANEXOS}/2020/sdm0820_Relatorio_Fundos_vRevisada_Res_181_e_184.pdf": (200, PDF, relatorio, "OK"),
        f"{ANEXOS}/2021/sdm0821_edital_.pdf": (200, PDF, _pdf("EDITAL SDM 08/21", "Prazo: 11 de fevereiro de 2022", corpo), "OK"),
        f"{ANEXOS}/2021/sdm0821_Relatorio.pdf": (200, PDF, relatorio, "OK"),
    }
    coletor = criar(extra)
    assert coletor.coletar_ato(ato("resolucao-cvm-175", "resolucao", f"{B}/resolucoes/resol175.html", "175")).status
    contagem = ColetorAudiencias(coletor).executar(["resolucao-cvm-175"])
    assert contagem["audiências citadas"] == 2 and contagem["lida"] == 2

    aud = audiencias.carregar(db, "sdm-2020-sdm0820")
    assert (aud["prazo"], aud["prazo_edital"], aud["prazos_divergem"]) == ("2021-04-15", "2021-04-02", True)
    assert aud["prazo_edital_texto"] == "Prazo: 2 de abril de 2021"
    baixados = [a for a in aud["arquivos"] if a["arquivo_id"]]
    assert {a["secao"] for a in baixados} == {"edital", "relatório"} and all(a["fidelidade_ok"] for a in baixados)
    # Duas origens da relação, cada uma com evidência: a ficha da norma e a seção "Norma editada" da audiência.
    origens = {n["origem"]: n["trecho"] for n in aud["normas"]}
    assert origens["ficha da norma"] == "AUDIÊNCIAS PÚBLICAS: SDM 08/20 e SDM 08/21"
    assert origens["página da audiência (norma editada)"].endswith("Norma editada: Resolução CVM 175")
    # Nenhuma manifestação é baixada; páginas e PDFs são originais verificáveis por hash.
    urls = [r[0] for r in db.execute("SELECT url FROM arquivo WHERE documento_id IS NULL")]
    assert len(urls) == 7 and not any("ABRAPP" in u or "ANBIMA" in u for u in urls)
    assert audiencias.pesquisar(db, "performance")[0]["secao"] == "relatório"

    # Retomada: páginas recentes não são relidas e nada é baixado de novo.
    pedidos = len(coletor.cliente._abridor.pedidos)
    assert ColetorAudiencias(coletor).executar(["resolucao-cvm-175"])["já lida"] == 2
    assert len(coletor.cliente._abridor.pedidos) == pedidos

    db.commit()
    cliente = TestClient(criar_app(cfg))
    norma = cliente.get("/norma/resolucao-cvm-175").text
    assert "Audiência pública" in norma and "SDM 08/20" in norma and "o edital diz 02/04/2021" in norma
    pagina = cliente.get("/audiencia/sdm-2020-sdm0820")
    assert pagina.status_code == 200 and "As manifestações recebidas não são coletadas" in pagina.text
    texto_id = next(a["texto_id"] for a in aud["arquivos"] if a["secao"] == "relatório")
    assert "RELATÓRIO DE ANÁLISE" in cliente.get(f"/audiencia/sdm-2020-sdm0820?texto={texto_id}").text
    busca = cliente.get("/", params={"q": "performance", "ap": "1"}).text
    assert "Audiência Pública SDM 08/20" in busca
    assert cliente.get("/api/audiencia/sdm-2020-sdm0820").json()["prazo_edital"] == "2021-04-02"
    assert cliente.get("/audiencia/nao-existe").status_code == 404

    # Biblioteca legível: a audiência na sua pasta e dentro da pasta da norma.
    from repositorio_cvm import biblioteca
    raiz = biblioteca.gerar(cfg.pasta_dados, db).pasta
    pasta = raiz / "Audiências públicas" / "2020 - SDM 08-20 (Resolução CVM 175)"
    nomes = sorted(p.name for p in pasta.iterdir())
    assert {"Edital.pdf", "Edital - Aviso de Prorrogação.pdf", "Relatório.pdf", "Relatório (conversão).md"} <= set(nomes)
    leiame = (pasta / "LEIAME.txt").read_text(encoding="utf-8-sig")
    assert "Prazo declarado no edital: Prazo: 2 de abril de 2021" in leiame and "não coletadas" in leiame
    assert (raiz / "Resoluções" / "Resolução CVM 175" / "Audiência SDM 08-20" / "LEIAME.txt").is_file()


def test_partes_da_norma_com_anexos(res21):  # noqa: F811
    cfg, db, doc = res21
    versao = doc.versao()
    partes = acervo.partes(db, doc, versao)
    assert [p.nome for p in partes] == ["Texto principal", "Anexo A", "Anexo B", "Anexo C", "Anexo D", "Anexo E"]
    assert [p.chave for p in partes][:2] == ["principal", "anexo-a"]
    anexo_e = acervo.markdown_parte(cfg.pasta_dados, db, versao, partes[-1])
    principal = acervo.markdown_parte(cfg.pasta_dados, db, versao, partes[0])
    assert anexo_e.lstrip().startswith("## ANEXO E") and "[^" in anexo_e  # notas chamadas no anexo vão com ele
    assert "Art. 1" in principal and "ANEXO E" not in principal
    assert len(anexo_e) + len(principal) < len(acervo.markdown(cfg.pasta_dados, versao))

    md = exportacao.exportar(doc, cfg.pasta_dados, "md", conexao=db, parte="anexo-a")
    assert md.nome == "resolucao-cvm-21-consolidado-anexo-a.md"
    assert "**Parte:**" in md.conteudo.decode("utf-8") and "somente esta parte" in md.conteudo.decode("utf-8")
    assert exportacao.exportar(doc, cfg.pasta_dados, "pdf", conexao=db, parte="anexo-b").conteudo[:4] == b"%PDF"

    db.commit()
    cliente = TestClient(criar_app(cfg))
    pagina = cliente.get("/norma/resolucao-cvm-21", params={"parte": "anexo-a"}).text
    assert "Exibindo só" in pagina and 'class="ativa">Anexo A' in pagina
    assert "exportar/docx?versao=consolidado&amp;parte=anexo-a" in pagina
    assert "não existe" in cliente.get("/norma/resolucao-cvm-21", params={"parte": "anexo-z"}).text
    assert cliente.get("/norma/resolucao-cvm-21/exportar/md", params={"parte": "anexo-z"}).status_code == 422
    api = cliente.get("/api/norma/resolucao-cvm-21").json()
    assert [p["chave"] for p in api["versoes"][0]["partes"]][-1] == "anexo-e"


def test_edital_sem_texto_nao_herda_o_prazo_do_aviso(ambiente):  # noqa: F811
    _, db, criar = ambiente
    PDF = {"Content-Type": "application/pdf"}
    vazio = FPDF()
    vazio.add_page()  # PDF digitalizado: página sem camada de texto
    aviso = _pdf("AVISO DE PRORROGAÇÃO", "Prazo: 30 de abril de 2021",
                 "O prazo para manifestações fica prorrogado. " * 20)
    coletor = criar({
        f"{AP}/2020/sdm0820.html": (200, HTML, (FIX / "ap-sdm0820.html").read_bytes(), "OK"),
        f"{ANEXOS}/2020/SDM0820_Edital_20201203.pdf": (200, PDF, bytes(vazio.output()), "OK"),
        f"{ANEXOS}/2020/sdm0820_edital_aviso_prorrogacao.pdf": (200, PDF, aviso, "OK"),
        f"{ANEXOS}/2020/sdm0820_Relatorio_Fundos_vRevisada_Res_181_e_184.pdf": (200, PDF, aviso, "OK"),
    })
    ColetorAudiencias(coletor)._garantir(f"{AP}/2020/sdm0820.html")
    assert ColetorAudiencias(coletor).ler("sdm-2020-sdm0820") == "lida"
    aud = audiencias.carregar(db, "sdm-2020-sdm0820")
    assert aud["prazo_edital"] is None and aud["prazo_edital_texto"] is None
    edital = next(a for a in aud["arquivos"] if a["secao"] == "edital")
    assert edital["fidelidade_ok"] == 0 and "reprovada" in edital["qualidade"]
