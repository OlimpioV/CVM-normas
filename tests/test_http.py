"""Cliente HTTP da coleta: conduta educada e integridade dos arquivos, com servidor e relógio falsos."""

import hashlib
import json
import urllib.error

import pytest

from repositorio_cvm.coleta.http import (DEFAULT_USER_AGENT, BlockedError, ConteudoInesperadoError, FetchError,
                                         NotModifiedError, PoliteClient, conferir_formato)
from repositorio_cvm.modelos import Artifact

from tests.falsos import FakeClock, FakeOpener

ROBOTS = "User-agent: *\nDisallow: /restrito/\n"
HTML = {"Content-Type": "text/html; charset=utf-8"}
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF"


def _cliente(rotas, **opcoes):
    relogio = FakeClock()
    abridor = FakeOpener({"https://a.test/robots.txt": (200, {"Content-Type": "text/plain"}, ROBOTS, "OK"), **rotas})
    padrao = {"min_interval": 3.0, "max_retries": 2, "backoff_base": 5.0}
    cliente = PoliteClient(opener=abridor, clock=relogio, sleep=relogio.sleep, monotonic=relogio.monotonic,
                           **(padrao | opcoes))
    return cliente, abridor, relogio


# ---------------------------------------------------------------------- resultado
def test_devolve_os_bytes_exatos_com_hash_e_metadados():
    cliente, _, relogio = _cliente({"https://a.test/doc": (
        200, {**HTML, "ETag": '"v1"', "Last-Modified": "Tue, 27 Oct 2026 10:00:00 GMT"}, b"<h1>norma</h1>", "OK")})
    a = cliente.fetch("https://a.test/doc")
    assert a.bytes == b"<h1>norma</h1>" and a.sha256 == hashlib.sha256(b"<h1>norma</h1>").hexdigest()
    assert a.content_type.startswith("text/html") and a.etag == '"v1"' and a.last_modified.startswith("Tue")
    assert a.fetched_at == relogio.agora.isoformat()


def test_identificacao_padrao_e_enviada_em_toda_requisicao():
    cliente, abridor, _ = _cliente({"https://a.test/doc": (200, HTML, b"<p>x</p>", "OK")})
    cliente.fetch("https://a.test/doc")
    assert all(p["cabecalhos"]["user-agent"] == DEFAULT_USER_AGENT for p in abridor.pedidos)
    assert "RepositorioNormativoCVM" in DEFAULT_USER_AGENT and "coleta educada" in DEFAULT_USER_AGENT


# ---------------------------------------------------------------------- robots.txt
def test_robots_e_lido_antes_e_proibicao_interrompe_sem_requisitar():
    cliente, abridor, _ = _cliente({"https://a.test/restrito/x": (200, HTML, b"<p>x</p>", "OK")})
    with pytest.raises(BlockedError):
        cliente.fetch("https://a.test/restrito/x")
    assert abridor.urls() == ["https://a.test/robots.txt"]


def test_robots_ausente_nao_restringe():
    abridor_rotas = {"https://a.test/robots.txt": (404, {}, b"", "Not Found"),
                     "https://a.test/restrito/x": (200, HTML, b"<p>x</p>", "OK")}
    cliente, _, _ = _cliente(abridor_rotas)
    assert cliente.fetch("https://a.test/restrito/x").bytes == b"<p>x</p>"


def test_robots_recusado_ou_indisponivel_nao_e_tratado_como_permissao():
    cliente, _, _ = _cliente({"https://a.test/robots.txt": (403, {}, b"", "Forbidden"),
                              "https://a.test/doc": (200, HTML, b"<p>x</p>", "OK")})
    with pytest.raises(BlockedError):
        cliente.fetch("https://a.test/doc")
    cliente, abridor, _ = _cliente({"https://a.test/robots.txt": (500, {}, b"", "Erro"),
                                    "https://a.test/doc": (200, HTML, b"<p>x</p>", "OK")}, max_retries=1)
    with pytest.raises(FetchError):
        cliente.fetch("https://a.test/doc")
    assert "https://a.test/doc" not in abridor.urls()


def test_redirecionamento_do_robots_e_seguido_e_vale_para_a_origem_consultada():
    rotas = {"https://a.test/robots.txt": (301, {"Location": "https://b.test/robots.txt"}, b"", "Moved"),
             "https://b.test/robots.txt": (200, {}, "User-agent: *\nDisallow: /privado/\n", "OK"),
             "https://a.test/privado/x": (200, HTML, b"<p>x</p>", "OK")}
    cliente, _, _ = _cliente(rotas)
    with pytest.raises(BlockedError):
        cliente.fetch("https://a.test/privado/x")


def test_robots_e_relido_em_coletas_longas():
    cliente, abridor, relogio = _cliente({"https://a.test/doc": (200, HTML, b"<p>x</p>", "OK")}, validade_robots=3600)
    cliente.fetch("https://a.test/doc")
    cliente.fetch("https://a.test/doc")
    relogio.sleep(3700)
    cliente.fetch("https://a.test/doc")
    assert abridor.urls().count("https://a.test/robots.txt") == 2


def test_crawl_delay_maior_que_o_intervalo_e_respeitado():
    rotas = {"https://a.test/robots.txt": (200, {}, "User-agent: *\nCrawl-delay: 10\n", "OK"),
             "https://a.test/a": (200, HTML, b"<p>a</p>", "OK"), "https://a.test/b": (200, HTML, b"<p>b</p>", "OK")}
    cliente, _, relogio = _cliente(rotas)
    cliente.fetch("https://a.test/a")
    cliente.fetch("https://a.test/b")
    assert relogio.esperas[-1] == 10.0


# ---------------------------------------------------------------------- intervalo e redirecionamentos
def test_intervalo_minimo_por_servidor_com_piso_de_1_segundo():
    rotas = {"https://a.test/a": (200, HTML, b"<p>a</p>", "OK"), "https://a.test/b": (200, HTML, b"<p>b</p>", "OK")}
    cliente, _, relogio = _cliente(rotas, min_interval=0.1)
    assert cliente.min_interval == 1.0
    cliente.fetch("https://a.test/a")
    cliente.fetch("https://a.test/b")
    assert relogio.esperas == [1.0, 1.0]  # robots -> a -> b


def test_cada_destino_de_redirecionamento_passa_pelo_robots():
    rotas = {"https://a.test/velho": (302, {"Location": "/restrito/novo"}, b"", "Found"),
             "https://a.test/restrito/novo": (200, HTML, b"<p>x</p>", "OK")}
    cliente, abridor, _ = _cliente(rotas)
    with pytest.raises(BlockedError):
        cliente.fetch("https://a.test/velho")
    assert "https://a.test/restrito/novo" not in abridor.urls()


def test_redirecionamento_permitido_e_seguido_e_url_final_registrada():
    rotas = {"https://a.test/velho": (301, {"Location": "https://a.test/novo"}, b"", "Moved"),
             "https://a.test/novo": (200, HTML, b"<p>x</p>", "OK")}
    cliente, _, _ = _cliente(rotas)
    assert cliente.fetch("https://a.test/velho").url == "https://a.test/novo"


def test_redirecionamento_em_ciclo_falha():
    rotas = {"https://a.test/x": (302, {"Location": "https://a.test/y"}, b"", "Found"),
             "https://a.test/y": (302, {"Location": "https://a.test/x"}, b"", "Found")}
    cliente, _, _ = _cliente(rotas)
    with pytest.raises(FetchError, match="redirecionamentos"):
        cliente.fetch("https://a.test/x")


# ---------------------------------------------------------------------- bloqueio, novas tentativas e Retry-After
@pytest.mark.parametrize("status", [401, 403, 429])
def test_bloqueio_para_sem_nova_tentativa(status):
    cliente, abridor, _ = _cliente({"https://a.test/doc": (status, {}, b"", "Bloqueado")})
    with pytest.raises(BlockedError) as erro:
        cliente.fetch("https://a.test/doc")
    assert erro.value.status == status and abridor.urls().count("https://a.test/doc") == 1


def test_erro_do_servidor_tenta_de_novo_com_espera_crescente():
    rotas = {"https://a.test/doc": [(500, {}, b"", "Erro"), (502, {}, b"", "Erro"), (200, HTML, b"<p>x</p>", "OK")]}
    cliente, _, relogio = _cliente(rotas)
    assert cliente.fetch("https://a.test/doc").bytes == b"<p>x</p>"
    assert 5.0 in relogio.esperas and 10.0 in relogio.esperas
    assert cliente.stats["a.test"]["failures"] == 2


def test_erro_persistente_desiste_apos_as_tentativas():
    cliente, abridor, _ = _cliente({"https://a.test/doc": (503, {}, b"", "Indisponível")}, max_retries=2)
    with pytest.raises(FetchError) as erro:
        cliente.fetch("https://a.test/doc")
    assert erro.value.status == 503 and abridor.urls().count("https://a.test/doc") == 3


def test_falha_de_rede_tenta_de_novo():
    rotas = {"https://a.test/doc": [urllib.error.URLError("sem rede"), (200, HTML, b"<p>x</p>", "OK")]}
    cliente, _, _ = _cliente(rotas)
    assert cliente.fetch("https://a.test/doc").bytes == b"<p>x</p>"


def test_retry_after_e_respeitado_uma_vez():
    rotas = {"https://a.test/doc": [(429, {"Retry-After": "40"}, b"", "Too Many"), (200, HTML, b"<p>x</p>", "OK")]}
    cliente, _, relogio = _cliente(rotas)
    assert cliente.fetch("https://a.test/doc").bytes == b"<p>x</p>"
    assert 40.0 in relogio.esperas


def test_segundo_429_e_bloqueio_e_espera_longa_demais_nao_e_aceita():
    cliente, _, _ = _cliente({"https://a.test/doc": (429, {"Retry-After": "40"}, b"", "Too Many")})
    with pytest.raises(BlockedError):
        cliente.fetch("https://a.test/doc")
    cliente, _, relogio = _cliente({"https://a.test/doc": (429, {"Retry-After": "86400"}, b"", "Too Many")})
    with pytest.raises(BlockedError):
        cliente.fetch("https://a.test/doc")
    assert 86400.0 not in relogio.esperas


# ---------------------------------------------------------------------- integridade
def test_corpo_incompleto_e_baixado_de_novo():
    rotas = {"https://a.test/a.pdf": [(200, {"Content-Type": "application/pdf", "Content-Length": "999"}, PDF, "OK"),
                                      (200, {"Content-Type": "application/pdf", "Content-Length": str(len(PDF))}, PDF, "OK")]}
    cliente, abridor, _ = _cliente(rotas)
    assert cliente.fetch("https://a.test/a.pdf", esperado="pdf").bytes == PDF
    assert abridor.urls().count("https://a.test/a.pdf") == 2


def test_corpo_sempre_incompleto_falha():
    rotas = {"https://a.test/a.pdf": (200, {"Content-Length": "999"}, PDF, "OK")}
    cliente, _, _ = _cliente(rotas, max_retries=1)
    with pytest.raises(FetchError, match="falha de transporte"):
        cliente.fetch("https://a.test/a.pdf")


def test_arquivo_acima_do_limite_e_recusado():
    cliente, _, _ = _cliente({"https://a.test/a.pdf": (200, {}, PDF, "OK")}, max_bytes=10)
    with pytest.raises(FetchError, match="limite"):
        cliente.fetch("https://a.test/a.pdf")


def test_pagina_de_erro_no_lugar_do_pdf_e_recusada():
    cliente, _, _ = _cliente({"https://a.test/a.pdf": (200, HTML, b"<html>Em manutencao</html>", "OK")})
    with pytest.raises(ConteudoInesperadoError):
        cliente.fetch("https://a.test/a.pdf", esperado="pdf")


def test_assinaturas_de_formato():
    assert conferir_formato(PDF, "application/pdf", "pdf") is None
    assert conferir_formato(b"PK\x03\x04resto", "application/octet-stream", "docx") is None
    assert conferir_formato(b"<html></html>", "text/html", "docx")
    assert conferir_formato(PDF, "application/pdf", "html")
    assert conferir_formato(b"\n  <!DOCTYPE html>", "", "html") is None
    assert conferir_formato(b"qualquer", "x", None) is None


def test_requisicao_condicional_e_304():
    cliente, abridor, _ = _cliente({"https://a.test/doc": (304, {}, b"", "Not Modified")})
    with pytest.raises(NotModifiedError):
        cliente.fetch("https://a.test/doc", etag='"v1"', last_modified="Tue, 27 Oct 2026 10:00:00 GMT")
    cabecalhos = abridor.pedidos[-1]["cabecalhos"]
    assert cabecalhos["if-none-match"] == '"v1"' and cabecalhos["if-modified-since"].startswith("Tue")


def test_url_nao_http_e_recusada():
    cliente, _, _ = _cliente({})
    with pytest.raises(FetchError):
        cliente.fetch("ftp://a.test/x")


# ---------------------------------------------------------------------- registro
def test_eventos_vao_para_o_log_jsonl(tmp_path):
    log = tmp_path / "http.jsonl"
    cliente, _, _ = _cliente({"https://a.test/doc": (200, HTML, b"<p>x</p>", "OK")}, log_path=log)
    cliente.fetch("https://a.test/doc")
    eventos = [json.loads(l)["evento"] for l in log.read_text(encoding="utf-8").splitlines()]
    assert eventos[0] == "requisicao" and "robots" in eventos and eventos[-1] == "obtido"
    assert cliente.stats == {"a.test": {"requests": 2, "robots_checks": 1, "failures": 0}}


def test_artifact_confere_hash_url_e_fuso():
    a = Artifact.from_bytes("https://a.test/x", b"abc", "text/plain", "2026-10-27T00:00:00+00:00")
    assert a.sha256 == hashlib.sha256(b"abc").hexdigest()
    with pytest.raises(ValueError):
        Artifact("https://a.test/x", b"abc", "text/plain", "0" * 64, "2026-10-27T00:00:00+00:00")
    with pytest.raises(ValueError):
        Artifact.from_bytes("arquivo.pdf", b"abc", "text/plain")
    with pytest.raises(ValueError):
        Artifact.from_bytes("https://a.test/x", b"abc", "text/plain", "2026-10-27T00:00:00-03:00")
