"""Servidor e relógio falsos para testar a coleta sem rede.

Rotas: {url: (status, cabeçalhos, corpo, motivo)}. Uma lista de respostas é servida em sequência (a última se
repete); uma exceção na rota é levantada; URL sem rota simula falha de conexão.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


class RespostaFalsa:
    def __init__(self, url, status, cabecalhos, corpo, motivo):
        self.url = url
        self.status = status
        self.reason = motivo
        self.headers = dict(cabecalhos or {})
        self._corpo = io.BytesIO(corpo.encode("utf-8") if isinstance(corpo, str) else corpo)
        self.fechada = False

    def read(self, n=-1):
        return self._corpo.read(n)

    def getcode(self):
        return self.status

    def close(self):
        self.fechada = True


class FakeOpener:
    def __init__(self, rotas):
        self.rotas = {url: (list(r) if isinstance(r, list) else r) for url, r in rotas.items()}
        self.pedidos: list[dict] = []
        self.respostas: list[RespostaFalsa] = []

    def open(self, pedido, timeout=None):
        url = pedido.full_url
        self.pedidos.append({"url": url, "cabecalhos": {k.lower(): v for k, v in pedido.header_items()}})
        rota = self.rotas.get(url)
        if isinstance(rota, list):
            rota = rota.pop(0) if len(rota) > 1 else rota[0]
        if rota is None:
            raise ConnectionError(f"sem rota para {url}")
        if isinstance(rota, BaseException):
            raise rota
        resposta = RespostaFalsa(url, *rota)
        self.respostas.append(resposta)
        return resposta

    def urls(self) -> list[str]:
        return [p["url"] for p in self.pedidos]


class FakeClock:
    """Relógio de parede e monotônico que só avançam quando o cliente "dorme"."""

    def __init__(self):
        self.agora = T0
        self.decorrido = 0.0
        self.esperas: list[float] = []

    def __call__(self):
        return self.agora

    def sleep(self, segundos):
        self.esperas.append(round(segundos, 3))
        self.agora += timedelta(seconds=segundos)
        self.decorrido += segundos

    def monotonic(self):
        return self.decorrido
