"""Versão consolidada (só o texto vigente) derivada do consolidado oficial em DOCX (D-21).

Usa o DOCX mínimo do art. 25, IV, da Res. CVM 60 (test_tachado) e uma tabela com célula parcialmente
riscada e linha inteiramente riscada, como nos anexos das Res. 60, 80 e 175.
"""

from dataclasses import asdict

from repositorio_cvm.consolidacao import conferir, derivar_texto_vigente, limpar_bloco
from repositorio_cvm.conversao.docx import blocos_docx, converter_docx
from repositorio_cvm.conversao.fidelidade import verificar
from tests.test_tachado import TRECHO, _docx, _p, _run


def _derivar(dados: bytes):
    c = converter_docx(dados)
    blocos = c.markdown.rstrip("\n").split("\n\n")
    disp = [asdict(d) for d in c.dispositivos]
    return c, *derivar_texto_vigente(blocos, disp)


def _tabela(*linhas) -> str:
    def celula(*runs):
        return f"<w:tc>{_p(*runs)}</w:tc>"
    return "<w:tbl>" + "".join(f"<w:tr>{''.join(celula(*c) for c in l)}</w:tr>" for l in linhas) + "</w:tbl>"


def test_res60_alinea_b_so_a_vigente_com_a_nota_da_res194():
    c, blocos, disp, removidos, trechos = _derivar(TRECHO)
    texto = "\n\n".join(blocos)
    assert [d["texto"] for d in disp if d["texto"].startswith("b)")] == [
        "b) a dação de ativos em pagamento aos investidores dos valores integrantes do patrimônio separado;"]
    assert "Alínea b com redação dada pela Resolução CVM nº 194" in texto  # nota de alteração mantida
    assert "~~" not in texto and "dação em pagamento" not in texto
    assert "Texto vigente do parágrafo." in texto and "antigo" not in texto  # tachado parcial
    assert (removidos, trechos) == (1, 1)
    assert conferir(blocos, disp, c.markdown) is None


def test_tabela_com_celula_e_linha_riscadas():
    dados = _docx(
        _p(_run("Art. 1º Tabela de prazos:")),
        _tabela([[_run("Documento")], [_run("Prazo")]],
                [[_run("Informe mensal")], [_run("15 dias", tachado=True), _run(" 10 dias")]],
                [[_run("Informe extinto", tachado=True)], [_run("30 dias", tachado=True)]]),
        _p(_run("Tabela com redação dada pela Resolução CVM nº 999 de 1º de janeiro de 2025.")))
    blocos, _, _ = blocos_docx(dados)
    tabela = next(b for b in blocos if b.tabela_md)
    assert tabela.tachado == "parcial" and "<s>15 dias</s>" in tabela.tabela_md
    assert tabela.texto_vigente == "Documento Prazo Informe mensal 10 dias"
    c = converter_docx(dados)
    assert verificar(c.texto_fonte, c.markdown).ok  # o texto riscado continua na versão oficial

    _, blocos, disp, _, trechos = _derivar(dados)
    md = next(b for b in blocos if b.startswith("<table>"))
    assert "Informe extinto" not in md and "15 dias" not in md and "<td>10 dias</td>" in md
    assert md.count("<tr>") == 2 and trechos == 3
    assert conferir(blocos, disp, c.markdown) is None


def test_tabela_inteiramente_riscada_e_redacao_anterior():
    dados = _docx(_p(_run("Art. 2º Texto.")),
                  _tabela([[_run("Antigo", tachado=True)], [_run("modelo", tachado=True)]]))
    c = converter_docx(dados)
    assert [d.tipo for d in c.dispositivos][-1] == "redacao_anterior"
    _, blocos, disp, removidos, _ = _derivar(dados)
    assert not any(b.startswith("<table>") for b in blocos) and removidos == 1


def test_nota_de_rodape_chamada_so_no_tachado_sai():
    blocos = ["**Art. 1º** Texto ~~antigo[^1]~~ novo.", "[^1]: Nota do trecho revogado.", "[^2]: Nota sem chamada."]
    disp = [{"tipo": "artigo", "texto": "Art. 1º Texto novo."}, {"tipo": "nota", "texto": "[^1]: Nota do trecho revogado."},
            {"tipo": "nota", "texto": "[^2]: Nota sem chamada."}]
    saida, _, removidos, _ = derivar_texto_vigente(blocos, disp)
    assert saida == ["**Art. 1º** Texto novo.", "[^2]: Nota sem chamada."] and removidos == 1


def test_limpar_bloco_sem_tachado_nao_muda_nada():
    bloco = "**Art. 3º** Texto com  espaço duplo original."
    assert limpar_bloco(bloco) == (bloco, 0)


# ---------------------------------------------------------------------- motor de aplicação das alterações
from datetime import date  # noqa: E402

from repositorio_cvm.conversao.html import Bloco, estruturar  # noqa: E402
from repositorio_cvm.motor_alteracoes import Ato, Texto, consolidar_texto, enderecos  # noqa: E402

NORMA = [
    "RESOLUÇÃO CVM Nº 900, DE 1º DE MARÇO DE 2024",
    "Art. 1º Esta Resolução dispõe sobre o teste.",
    "Art. 2º O participante deve:",
    "I – manter cadastro;",
    "II – enviar informações mensais; e",
    "III – guardar documentos por cinco anos.",
    "Parágrafo único. O prazo é de dez dias.",
    "Art. 3º Esta Resolução entra em vigor na data de sua publicação.",
]
ALTERADORA = [
    "RESOLUÇÃO CVM Nº 950, DE 2 DE OUTUBRO DE 2025",
    "Art. 1º A Resolução CVM nº 900, de 1º de março de 2024, passa a vigorar com as seguintes alterações:",
    "“Art. 2º ......................................",
    "II – enviar informações semanais;",
    "..............................................",
    "IV – comunicar mudanças de endereço.",
    "..............................................” (NR)",
    "“Art. 2º-A. O participante pode delegar o envio.” (NR)",
    "Art. 2º Fica revogado o parágrafo único do art. 2º da Resolução CVM nº 900, de 1º de março de 2024.",
    "Art. 3º Esta Resolução entra em vigor em 1º de dezembro de 2025.",
]


def _texto(linhas) -> Texto:
    c = estruturar([Bloco(l) for l in linhas], " ".join(linhas))
    return Texto.de_versao(c.markdown.rstrip("\n").split("\n\n"), [d.__dict__ for d in c.dispositivos])


def _ato(linhas, vigencia="2025-12-01") -> Ato:
    c = estruturar([Bloco(l) for l in linhas], " ".join(linhas))
    return Ato("resolucao-cvm-950", "950", "2025-10-02", vigencia, [d.__dict__ for d in c.dispositivos])


def test_redacao_nova_acrescimo_e_revogacao():
    t = _texto(NORMA)
    regs = consolidar_texto(t, [_ato(ALTERADORA)], "900", date(2026, 1, 1), incluir_futuras=True)
    assert [(r.operacao, r.alvo, r.status) for r in regs] == [
        ("redacao", "art. 2º, inciso II", "aplicada"),
        ("acrescimo", "art. 2º, inciso IV", "aplicada"),
        ("acrescimo", "art. 2º-A", "aplicada"),
        ("revogacao", "art. 2º, parágrafo único", "aplicada"),
    ]
    vigentes = [(i.tipo, i.texto) for i in t.itens if i.tipo not in ("redacao_anterior",)]
    textos = [x for _, x in vigentes]
    # Ordem: inciso III mantido, inciso IV depois dele, art. 2º-A depois do art. 2º e antes do art. 3º.
    assert textos.index("II – enviar informações semanais;") < textos.index("III – guardar documentos por cinco anos.")
    assert textos.index("III – guardar documentos por cinco anos.") < textos.index("IV – comunicar mudanças de endereço.")
    assert textos.index("Art. 2º-A. O participante pode delegar o envio.") < textos.index(
        "Art. 3º Esta Resolução entra em vigor na data de sua publicação.")
    anteriores = [i.texto for i in t.itens if i.tipo == "redacao_anterior"]
    assert anteriores == ["II – enviar informações mensais; e", "Parágrafo único. O prazo é de dez dias."]
    notas = [i.texto for i in t.itens if i.tipo == "nota_alteracao"]
    assert "• Inciso II com redação dada pela Resolução CVM nº 950, de 2 de outubro de 2025 " \
           "(alteração aplicada automaticamente)." in notas
    assert any(n.startswith("• Parágrafo único revogado pela Resolução CVM nº 950") for n in notas)
    # A versão com tachado mantém a redação anterior riscada.
    assert any(i.md == "~~II – enviar informações mensais; e~~" for i in t.itens)


def test_vigencia_futura_fica_fora_do_texto_vigente():
    t = _texto(NORMA)
    regs = consolidar_texto(t, [_ato(ALTERADORA, vigencia="2026-11-01")], "900", date(2026, 10, 28),
                            incluir_futuras=False)
    assert {r.status for r in regs} == {"vigência futura"}
    assert not any(i.tipo == "redacao_anterior" for i in t.itens)
    t2 = _texto(NORMA)
    consolidar_texto(t2, [_ato(ALTERADORA, vigencia="2026-11-01")], "900", date(2026, 10, 28), incluir_futuras=True)
    assert any("em vigor a partir de 1º de novembro de 2026" in i.texto for i in t2.itens)


def test_alvo_inexistente_e_comando_de_outra_norma_nao_sao_aplicados():
    t = _texto(NORMA)
    linhas = ALTERADORA[:2] + ["“Art. 7º ......", "§ 3º Texto novo.” (NR)",
                               "Art. 2º A Resolução CVM nº 901 passa a vigorar com a seguinte redação:",
                               "“Art. 1º Outra norma.” (NR)"]
    regs = consolidar_texto(t, [_ato(linhas)], "900", date(2026, 1, 1), incluir_futuras=True)
    assert [(r.alvo, r.status) for r in regs] == [("art. 7º", "alvo não localizado"),
                                                   ("art. 7º, § 3º", "alvo não localizado")]
    assert [i.texto for i in t.itens] == [i.texto for i in _texto(NORMA).itens]  # nada mudou


def test_enderecos_citados_nos_comandos():
    assert enderecos("o inciso III do art. 31 do Anexo II", "Anexo Normativo II") == \
        ["Anexo Normativo II, art. 31, inciso III"]
    assert enderecos("a alínea “b” do inciso IV do art. 25", None) == ["art. 25, inciso IV, alínea b"]
    assert enderecos("o § 2º do art. 10 e o parágrafo único do art. 12-A", None) == \
        ["art. 10, § 2º", "art. 12-A, parágrafo único"]
