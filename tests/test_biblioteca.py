"""Biblioteca legível (dados/biblioteca): vínculos para os originais, somente leitura, regenerável."""

import os
import stat

import pytest

from repositorio_cvm import biblioteca
from repositorio_cvm.armazenamento import originais

from tests.test_coletor import ambiente  # noqa: F401 (fixture)
from tests.test_exportacao import res21  # noqa: F401 (fixture)


def test_nome_seguro_para_o_windows():
    assert biblioteca.nome_seguro("Ofício Circular CVM/SSE 03/26") == "Ofício Circular CVM-SSE 03-26"
    assert biblioteca.nome_seguro('Anexo: "A"?* <x>|.  ') == "Anexo A x"


def test_biblioteca_com_vinculos_somente_leitura_e_regeneravel(res21):  # noqa: F811
    cfg, db, doc = res21
    r = biblioteca.gerar(cfg.pasta_dados, db)
    pasta = r.pasta / "Resoluções" / biblioteca.nome_seguro(doc.titulo)
    docx = pasta / "Texto consolidado.docx"
    original = db.execute("SELECT caminho, sha256 FROM arquivo WHERE documento_id = 'resolucao-cvm-21' "
                          "AND formato = 'docx'").fetchone()
    # Mesmo arquivo do original (vínculo), sem cópia, e protegido contra edição.
    assert os.path.samefile(docx, cfg.pasta_dados / original["caminho"]) and r.vinculos >= 2
    assert not os.stat(cfg.pasta_dados / original["caminho"]).st_mode & stat.S_IWRITE
    with pytest.raises(PermissionError):
        docx.open("ab")
    # A conversão é cópia (o conversor a regenera), e o LEIAME traz a origem com o hash.
    md = pasta / "Texto consolidado - só o texto vigente.md"
    assert md.is_file() and not os.path.samefile(md, cfg.pasta_dados / doc.versao().caminho_md)
    leiame = (pasta / "LEIAME.txt").read_text(encoding="utf-8-sig")
    assert original["sha256"] in leiame and "Partes (texto consolidado vigente): Texto principal; ANEXO A" in leiame
    assert (pasta / "Texto alterado com tachado (consolidado oficial, conversão).md").is_file()

    # Gerar de novo substitui a biblioteca sem tocar nos originais.
    biblioteca.gerar(cfg.pasta_dados, db)
    assert docx.is_file() and originais.verificar(cfg.pasta_dados, original["caminho"], original["sha256"])
    assert not (cfg.pasta_dados / "biblioteca.nova").exists()


def test_nao_apaga_pasta_que_nao_foi_gerada_pelo_comando(res21):  # noqa: F811
    cfg, db, _ = res21
    alheia = cfg.pasta_dados / "biblioteca"
    alheia.mkdir()
    (alheia / "meu-arquivo.txt").write_text("não apagar")
    with pytest.raises(RuntimeError, match="nada foi apagado"):
        biblioteca.gerar(cfg.pasta_dados, db)
    assert (alheia / "meu-arquivo.txt").read_text() == "não apagar"


def test_original_gravado_ja_fica_somente_leitura(ambiente):  # noqa: F811
    cfg, _, _ = ambiente
    _, relativo = originais.gravar(cfg.pasta_dados, b"conteudo", "text/plain")
    assert not os.stat(cfg.pasta_dados / relativo).st_mode & stat.S_IWRITE
