"""Cliente HTTP da coleta: educado com as fontes, auditável e que só entrega arquivos íntegros.

Conduta (CLAUDE.md, "Coleta educada"):
- o `robots.txt` de cada origem é lido antes da primeira requisição e relido depois de `validade_robots`
  (coletas longas). Redirecionamentos do próprio `robots.txt` são seguidos (até 5, RFC 9309) e as regras
  obtidas valem para a origem consultada. 404/410 e demais 4xx: sem restrições declaradas; 401/403:
  acesso recusado (a coleta para); 5xx ou falha de rede: a origem não é acessada (não se presume permissão);
- intervalo mínimo entre requisições ao mesmo servidor: o maior entre `min_interval` (piso de 1 s) e o
  `Crawl-delay` do `robots.txt`;
- cada redirecionamento da requisição passa de novo pelo `robots.txt` e pelo intervalo do servidor de destino;
- 401/403 e 429 sem "Retry-After": `BlockedError`, sem insistir. 429 ou 503 com "Retry-After" de até
  `espera_maxima`: espera-se o tempo pedido e tenta-se uma vez mais; um segundo 429 é bloqueio;
- 5xx, falha de rede e corpo menor que o "Content-Length" anunciado: novas tentativas com espera crescente
  (`backoff_base` · 2^n), até `max_retries`;

Integridade:
- corpo maior que `max_bytes` é recusado sem ser guardado;
- com `esperado` (pdf, docx, doc, html), o conteúdo é conferido pela assinatura do arquivo: uma página de erro
  servida no lugar de um PDF é recusada (`ConteudoInesperadoError`), em vez de virar "original";
- requisição condicional (ETag/Last-Modified): `NotModifiedError` quando o servidor responde 304.

Cada evento vai para o log JSONL (`log_path`) e é contado em `stats` por servidor.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from repositorio_cvm.modelos import Artifact

__all__ = ["DEFAULT_USER_AGENT", "MIN_INTERVAL_FLOOR", "BlockedError", "ProibidoPeloRobotsError", "ConteudoInesperadoError", "FetchError",
           "NotModifiedError", "PoliteClient"]

DEFAULT_USER_AGENT = (
    "RepositorioNormativoCVM/1.0 (+https://github.com/OlimpioV/CVM-normas; pesquisa regulatoria; coleta educada)")
MIN_INTERVAL_FLOOR = 1.0
REDIRECIONAMENTOS = frozenset({301, 302, 303, 307, 308})
MAX_SALTOS = 10
MAX_SALTOS_ROBOTS = 5
_BLOCO = 64 * 1024


class FetchError(Exception):
    """Falha ao obter a URL. `status` é o código HTTP final, quando houve resposta."""

    def __init__(self, motivo: str, status: int | None = None) -> None:
        super().__init__(motivo)
        self.status = status


class BlockedError(FetchError):
    """A fonte recusou o acesso (401, 403, 429 ou robots.txt). A coleta deve parar."""


class ProibidoPeloRobotsError(BlockedError):
    """O `robots.txt` proíbe esta URL. As demais URLs da origem continuam permitidas."""


class NotModifiedError(FetchError):
    """Resposta 304 a uma requisição condicional."""

    def __init__(self, url: str) -> None:
        super().__init__(f"não modificado: {url}", 304)


class ConteudoInesperadoError(FetchError):
    """O servidor respondeu com sucesso, mas o conteúdo não é do formato esperado."""


@dataclass
class _Resposta:
    url: str
    status: int
    motivo: str
    cabecalhos: dict[str, str]
    corpo: bytes = b""

    def cabecalho(self, nome: str) -> str | None:
        return self.cabecalhos.get(nome.lower())


@dataclass
class _Regras:
    leitor: RobotFileParser | None  # None: sem restrições declaradas
    lidas_em: float


@dataclass
class _Servidor:
    ultima: float | None = None
    requests: int = 0
    robots_checks: int = 0
    failures: int = 0


class _CorpoIncompleto(Exception):
    pass


class _SemRedirecionamento(urllib.request.HTTPRedirectHandler):
    """Redirecionamentos são tratados pelo cliente, um a um (robots.txt e intervalo em cada destino)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - API do urllib
        return None


def _abridor_padrao() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_SemRedirecionamento())


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _origem(url: str) -> str:
    partes = urlsplit(url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        raise FetchError(f"URL não suportada: {url}")
    return f"{partes.scheme}://{partes.netloc.lower()}"


def _servidor(url: str) -> str:
    return urlsplit(url).netloc.lower()


def conferir_formato(dados: bytes, tipo: str, esperado: str | None) -> str | None:
    """Motivo da recusa se `dados` não forem do formato `esperado`; None se conferem (ou sem expectativa)."""
    if not esperado:
        return None
    esperado = esperado.lower()
    inicio = dados[:1024]
    if esperado == "pdf":
        ok = b"%PDF-" in inicio
    elif esperado in ("docx", "xlsx", "pptx"):
        ok = dados.startswith(b"PK\x03\x04")
    elif esperado in ("doc", "xls"):
        ok = dados.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif esperado in ("html", "htm"):
        binario = b"%PDF-" in inicio or dados.startswith((b"PK\x03\x04", b"\xd0\xcf\x11\xe0"))
        ok = not binario and ("html" in tipo.lower() or inicio.lstrip().startswith(b"<"))
    else:
        return None
    return None if ok else f"conteúdo inesperado: esperado {esperado}, recebido {tipo or 'sem tipo'} ({len(dados)} bytes)"


class PoliteClient:
    def __init__(
        self,
        *,
        min_interval: float = 3.0,
        max_retries: int = 3,
        backoff_base: float = 5.0,
        user_agent: str | None = None,
        log_path: str | Path | None = None,
        timeout: float = 60.0,
        max_bytes: int = 200 * 1024 * 1024,
        validade_robots: float = 6 * 3600,
        espera_maxima: float = 300.0,
        opener: object | None = None,
        clock=None,
        sleep=None,
        monotonic=None,
    ) -> None:
        self.min_interval = max(float(min_interval), MIN_INTERVAL_FLOOR)
        self.max_retries = max(int(max_retries), 0)
        self.backoff_base = float(backoff_base)
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        self.log_path = Path(log_path) if log_path else None
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.validade_robots = validade_robots
        self.espera_maxima = espera_maxima
        self._abridor = opener if opener is not None else _abridor_padrao()
        self._relogio = clock or _agora_utc
        self._dormir = sleep or time.sleep
        self._monotonico = monotonic or time.monotonic
        self._regras: dict[str, _Regras] = {}
        self._servidores: dict[str, _Servidor] = {}
        self._trava = threading.Lock()
        self.eventos: list[dict] = []

    # ------------------------------------------------------------------ API pública
    def fetch(self, url: str, *, etag: str | None = None, last_modified: str | None = None,
              esperado: str | None = None) -> Artifact:
        """Baixa `url` e devolve os bytes exatos. `esperado`: formato a conferir (pdf, docx, doc, html)."""
        with self._trava:
            condicionais = {}
            if etag:
                condicionais["If-None-Match"] = etag
            if last_modified:
                condicionais["If-Modified-Since"] = last_modified
            atual = url
            for _ in range(MAX_SALTOS + 1):
                self._autorizar(atual)
                resposta = self._obter(atual, condicionais)
                if resposta.status == 304 and condicionais:
                    self._registrar("nao_modificado", atual)
                    raise NotModifiedError(atual)
                if resposta.status in REDIRECIONAMENTOS:
                    destino = resposta.cabecalho("location")
                    if not destino:
                        raise FetchError("redirecionamento sem destino", resposta.status)
                    proximo = urljoin(atual, destino)
                    _origem(proximo)
                    self._registrar("redirecionamento", atual, destino=proximo, status=resposta.status)
                    atual = proximo
                    continue
                if not 200 <= resposta.status < 300:
                    self._falha(atual, f"HTTP {resposta.status}")
                    raise FetchError(resposta.motivo or f"HTTP {resposta.status}", resposta.status)
                tipo = resposta.cabecalho("content-type") or ""
                recusa = conferir_formato(resposta.corpo, tipo, esperado)
                if recusa:
                    self._falha(atual, recusa)
                    raise ConteudoInesperadoError(recusa, resposta.status)
                artefato = Artifact.from_bytes(atual, resposta.corpo, tipo or "application/octet-stream",
                                               self._relogio().isoformat(), etag=resposta.cabecalho("etag"),
                                               last_modified=resposta.cabecalho("last-modified"))
                self._registrar("obtido", atual, status=resposta.status, bytes=len(resposta.corpo),
                                sha256=artefato.sha256)
                return artefato
            raise FetchError(f"mais de {MAX_SALTOS} redirecionamentos a partir de {url}")

    @property
    def stats(self) -> dict[str, dict[str, int]]:
        return {nome: {"requests": s.requests, "robots_checks": s.robots_checks, "failures": s.failures}
                for nome, s in self._servidores.items()}

    # ------------------------------------------------------------------ robots.txt
    def _autorizar(self, url: str) -> None:
        origem = _origem(url)
        regras = self._regras.get(origem)
        if regras is None or self._monotonico() - regras.lidas_em >= self.validade_robots:
            regras = self._ler_robots(origem)
        if regras.leitor is not None and not regras.leitor.can_fetch(self.user_agent, url):
            self._registrar("bloqueio", url, motivo="robots.txt")
            raise ProibidoPeloRobotsError(f"proibido pelo robots.txt de {origem}")

    def _ler_robots(self, origem: str) -> _Regras:
        self._estado(_servidor(origem)).robots_checks += 1
        endereco = origem + "/robots.txt"
        for _ in range(MAX_SALTOS_ROBOTS + 1):
            resposta = self._obter(endereco, {})
            if resposta.status in REDIRECIONAMENTOS and resposta.cabecalho("location"):
                endereco = urljoin(endereco, resposta.cabecalho("location"))
                continue
            break
        else:
            raise FetchError(f"robots.txt de {origem}: redirecionamentos demais")
        if 200 <= resposta.status < 300:
            leitor = RobotFileParser()
            leitor.parse(resposta.corpo.decode("utf-8", errors="replace").splitlines())
            regras = _Regras(leitor, self._monotonico())
        elif 400 <= resposta.status < 500:
            regras = _Regras(None, self._monotonico())  # 401/403/429 já viraram BlockedError em _obter
        else:
            raise FetchError(f"robots.txt de {origem} indisponível (HTTP {resposta.status})", resposta.status)
        self._regras[origem] = regras
        self._registrar("robots", endereco, origem=origem, status=resposta.status,
                        crawl_delay=self._crawl_delay(origem))
        return regras

    def _crawl_delay(self, origem: str) -> float | None:
        regras = self._regras.get(origem)
        if regras is None or regras.leitor is None:
            return None
        atraso = regras.leitor.crawl_delay(self.user_agent)
        return float(atraso) if atraso is not None else None

    # ------------------------------------------------------------------ envio com novas tentativas
    def _obter(self, url: str, cabecalhos: dict[str, str]) -> _Resposta:
        """Envia com intervalo e novas tentativas; devolve a resposta (inclusive 3xx e 4xx não bloqueantes)."""
        tentativa = 0
        ja_esperou_retry_after = False
        while True:
            self._aguardar_vez(url)
            try:
                resposta = self._enviar(url, cabecalhos)
            except (_CorpoIncompleto, urllib.error.URLError, http.client.HTTPException, OSError) as erro:
                motivo = f"falha de transporte: {type(erro).__name__}: {erro}"
                self._falha(url, motivo)
                if tentativa >= self.max_retries:
                    raise FetchError(motivo) from erro
                self._esperar_nova_tentativa(url, tentativa, motivo)
                tentativa += 1
                continue
            status = resposta.status
            pedido = self._retry_after(resposta)
            if status in (401, 403):
                self._falha(url, f"HTTP {status}")
                self._registrar("bloqueio", url, status=status)
                raise BlockedError(resposta.motivo or f"HTTP {status}", status)
            if status in (429, 503) and pedido is not None and not ja_esperou_retry_after:
                ja_esperou_retry_after = True
                self._falha(url, f"HTTP {status}")
                self._registrar("espera_pedida", url, status=status, segundos=pedido)
                self._dormir(pedido)
                continue
            if status == 429:
                self._falha(url, "HTTP 429")
                self._registrar("bloqueio", url, status=status)
                raise BlockedError(resposta.motivo or "HTTP 429 (muitas requisições)", status)
            if status >= 500:
                self._falha(url, f"HTTP {status}")
                if tentativa >= self.max_retries:
                    raise FetchError(resposta.motivo or f"HTTP {status}", status)
                self._esperar_nova_tentativa(url, tentativa, f"HTTP {status}")
                tentativa += 1
                continue
            return resposta

    def _retry_after(self, resposta: _Resposta) -> float | None:
        """Segundos pedidos pelo servidor, se forem razoáveis (até `espera_maxima`)."""
        valor = (resposta.cabecalho("retry-after") or "").strip()
        if not valor:
            return None
        if valor.isdigit():
            segundos = float(valor)
        else:
            try:
                from email.utils import parsedate_to_datetime
                segundos = (parsedate_to_datetime(valor) - self._relogio()).total_seconds()
            except (TypeError, ValueError):
                return None
        return max(segundos, 0.0) if segundos <= self.espera_maxima else None

    def _esperar_nova_tentativa(self, url: str, tentativa: int, motivo: str) -> None:
        espera = self.backoff_base * (2 ** tentativa)
        self._registrar("nova_tentativa", url, tentativa=tentativa + 1, segundos=espera, motivo=motivo)
        self._dormir(espera)

    def _aguardar_vez(self, url: str) -> None:
        nome = _servidor(url)
        estado = self._estado(nome)
        intervalo = max(self.min_interval, self._crawl_delay(_origem(url)) or 0.0)
        if estado.ultima is not None:
            falta = intervalo - (self._monotonico() - estado.ultima)
            if falta > 0:
                self._registrar("espera", url, segundos=round(falta, 3))
                self._dormir(falta)
        estado.ultima = self._monotonico()
        estado.requests += 1

    def _enviar(self, url: str, extras: dict[str, str]) -> _Resposta:
        pedido = urllib.request.Request(url, method="GET", headers={
            "User-Agent": self.user_agent, "Accept-Encoding": "identity", **extras})
        self._registrar("requisicao", url)
        try:
            bruta = self._abridor.open(pedido, timeout=self.timeout)
        except urllib.error.HTTPError as erro:  # 3xx (sem redirecionamento automático), 4xx e 5xx
            bruta = erro
        try:
            status = getattr(bruta, "status", None) or bruta.getcode()
            cabecalhos = {k.lower(): v for k, v in (bruta.headers.items() if bruta.headers else [])}
            motivo = getattr(bruta, "reason", "") or ""
            corpo = self._ler_corpo(bruta, cabecalhos, url) if status not in REDIRECIONAMENTOS and status != 304 else b""
        finally:
            fechar = getattr(bruta, "close", None)
            if fechar:
                fechar()
        return _Resposta(url, int(status), str(motivo), cabecalhos, corpo)

    def _ler_corpo(self, bruta, cabecalhos: dict[str, str], url: str) -> bytes:
        declarado = cabecalhos.get("content-length")
        declarado = int(declarado) if declarado and declarado.isdigit() else None
        if declarado is not None and declarado > self.max_bytes:
            raise FetchError(f"arquivo de {declarado} bytes acima do limite de {self.max_bytes}")
        partes, total = [], 0
        while True:
            try:
                bloco = bruta.read(_BLOCO)
            except http.client.IncompleteRead as erro:
                raise _CorpoIncompleto(f"leitura interrompida após {total + len(erro.partial)} bytes") from erro
            if not bloco:
                break
            total += len(bloco)
            if total > self.max_bytes:
                raise FetchError(f"arquivo acima do limite de {self.max_bytes} bytes")
            partes.append(bloco)
        corpo = b"".join(partes)
        if declarado is not None and "chunked" not in cabecalhos.get("transfer-encoding", "") and len(corpo) != declarado:
            raise _CorpoIncompleto(f"recebidos {len(corpo)} de {declarado} bytes anunciados")
        return corpo

    # ------------------------------------------------------------------ estado e registro
    def _estado(self, nome: str) -> _Servidor:
        return self._servidores.setdefault(nome, _Servidor())

    def _falha(self, url: str, motivo: str) -> None:
        self._estado(_servidor(url)).failures += 1
        self._registrar("falha", url, motivo=motivo)

    def _registrar(self, evento: str, url: str, **dados) -> None:
        registro = {"em": self._relogio().isoformat(), "evento": evento, "url": url, **dados}
        self.eventos.append(registro)
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as arquivo:
                arquivo.write(json.dumps(registro, ensure_ascii=False) + "\n")
