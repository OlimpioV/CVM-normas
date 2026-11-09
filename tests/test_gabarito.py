"""Gabarito de validação: estrutura do arquivo e identificação de ofícios-circulares."""

from repositorio_cvm import gabarito


def test_gabarito_tem_os_32_atos_do_usuario_com_chaves_unicas():
    atos = gabarito.carregar()
    assert len(atos) == 32
    assert len({a.chave for a in atos}) == 32
    especies = [a.especie for a in atos]
    assert especies.count("resolucao") == 20 and especies.count("oficio_circular") == 7
    assert all(a.ficha or a.areas for a in atos)


def test_identificacao_de_oficios():
    atos = {a.chave: a for a in gabarito.carregar()}
    assert gabarito.oficio_corresponde(atos["oficio-circular-cvm-sse-03-2026"], "Ofício Circular CVM/SSE 03/26")
    assert not gabarito.oficio_corresponde(atos["oficio-circular-cvm-sse-02-2026"], "Ofício Circular CVM/SSE 03/26")
    assert gabarito.oficio_corresponde(atos["oficio-circular-anual-cvm-sre-2026"], "Ofício Circular Anual 2026 CVM/SRE")
    assert not gabarito.oficio_corresponde(atos["oficio-circular-cvm-sre-05-2026"], "Ofício Circular Anual 2026 CVM/SRE")
    assert gabarito.oficio_corresponde(atos["oficio-circular-conjunto-cvm-sin-sse-01-2025"],
                                       "Ofício Circular Conjunto nº 1/2025/CVM/SIN/SSE")
    assert not gabarito.oficio_corresponde(atos["oficio-circular-cvm-sin-01-2026"],
                                           "Ofício Circular Conjunto nº 1/2026/CVM/SIN/SSE")
