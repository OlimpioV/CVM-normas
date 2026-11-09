"""Pesquisa determinística no acervo: referência normativa ("Resolução CVM 175, artigo 40") ou texto (FTS5).

Quando o ato tem mais de uma versão de texto, a pesquisa usa a consolidada, só com o texto vigente
(`versao="consolidado"`, padrão), a alterada com a redação anterior tachada (`versao="alterada"`) ou a
redação original (`versao="original"`), na ordem de preferência de `acervo.PREFERENCIA`. A redação
tachada nunca entra nos resultados. Cada resultado indica qual versão foi usada.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from repositorio_cvm.acervo import PREFERENCIA

_ESPECIES = [
    (r"resolu[cç][aã]o|res\.?|rcvm", "resolucao"),
    (r"instru[cç][aã]o|icvm|inst\.?", "instrucao"),
    (r"delibera[cç][aã]o|deli\.?", "deliberacao"),
    (r"parecer(?:\s+de\s+orienta[cç][aã]o)?|po", "parecer_orientacao"),
]
_REFERENCIA = re.compile(
    r"^\s*(?P<especie>" + "|".join(p for p, _ in _ESPECIES) + r")\s*(?:cvm)?\s*(?:n[º°o.]*)?\s*(?P<numero>\d+)"
    r"(?:\s*/\s*\d{2,4})?"
    r"(?:[\s,;-]+anexo(?:\s+normativo)?\s+(?P<anexo>[IVXLC]+|[A-Z]))?"
    r"(?:[\s,;-]+(?:art(?:igo)?s?\.?|art)\s*(?P<artigo>\d+(?:-[a-z])?)\s*[º°o]?)?",
    re.I,
)


@dataclass
class Achado:
    documento_id: str
    titulo: str | None
    situacao: str
    rotulo: str
    texto: str
    url_oficial: str | None
    versao: str | None = None
    dispositivo_id: int | None = None
    inicio: str | None = None  # início do texto integral do dispositivo (para localizá-lo na página da norma)
    parte: str | None = None  # parte da norma com anexos (ex.: "Anexo Normativo I"); None no texto principal


@dataclass(frozen=True)
class Referencia:
    especie: str
    numero: str
    artigo: str | None
    anexo: str | None


def interpretar_referencia(consulta: str) -> Referencia | None:
    m = _REFERENCIA.match(consulta)
    if not m:
        return None
    bruto = m.group("especie").lower()
    especie = next(nome for padrao, nome in _ESPECIES if re.fullmatch(padrao, bruto, re.I))
    artigo = m.group("artigo").upper() if m.group("artigo") else None
    anexo = m.group("anexo").upper() if m.group("anexo") else None
    return Referencia(especie, str(int(m.group("numero"))), artigo, anexo)


def _fts(consulta: str) -> str:
    termos = re.findall(r'"[^"]+"|\S+', consulta)
    return " ".join(t if t.startswith('"') else '"' + t.replace('"', "") + '"' for t in termos)


def _versao_escolhida(versao: str) -> str:
    """Subconsulta: id da versão aprovada a usar para o documento `d` (preferência configurável)."""
    ordem = PREFERENCIA.get(versao, PREFERENCIA["consolidado"])
    caso = " ".join(f"WHEN '{tipo}' THEN {i}" for i, tipo in enumerate(ordem))
    return ("(SELECT v.id FROM versao_texto v WHERE v.documento_id = d.id AND v.fidelidade_ok = 1 "
            "AND NOT (v.conversor LIKE 'consolidacao-gerada%' AND NOT EXISTS (SELECT 1 FROM alteracao_aplicada x "
            "WHERE x.versao_id = v.id AND x.status = 'aplicada')) "
            f"ORDER BY CASE v.tipo {caso} ELSE {len(ordem)} END, v.id DESC LIMIT 1)")


def _achados(linhas) -> list[Achado]:
    return [Achado(l["id"], l["titulo"], l["situacao"], l["rotulo"], l["texto"], l["url_oficial"], l["versao"],
                   l["dispositivo_id"], l["inicio"], l["parte"]) for l in linhas]


def pesquisar(conexao: sqlite3.Connection, consulta: str, especie: str | None = None, situacao: str | None = None,
              desde: str | None = None, ate: str | None = None, limite: int = 20,
              versao: str = "consolidado") -> list[Achado]:
    filtros, args = [], []
    ref = interpretar_referencia(consulta)
    base = ("SELECT d.id, d.titulo, d.situacao, d.url_oficial, x.rotulo, {texto} AS texto, v.tipo AS versao, "
            "x.id AS dispositivo_id, substr(x.texto, 1, 200) AS inicio, x.parte "
            "FROM {origem} JOIN documento d ON d.id = x.documento_id JOIN versao_texto v ON v.id = x.versao_id "
            f"WHERE x.versao_id = {_versao_escolhida(versao)} AND x.tipo != 'redacao_anterior'")
    if ref:
        sql = base.format(texto="x.texto", origem="dispositivo x") + " AND d.especie = ? AND d.numero = ?"
        args = [ref.especie, ref.numero]
        if ref.anexo:
            sql += " AND x.parte LIKE ?"
            args.append(f"Anexo% {ref.anexo}")
        elif ref.artigo:
            sql += " AND x.parte IS NULL"
        if ref.artigo:
            sql += " AND x.artigo = ? AND x.tipo NOT IN ('texto_alterado', 'assinatura', 'sumario', 'nota_alteracao')"
            args.append(ref.artigo)
        sql += " ORDER BY x.ordem LIMIT ?"
        args.append(limite if ref.artigo else 5)
        linhas = conexao.execute(sql, args).fetchall()
        if not linhas:
            linhas = conexao.execute(
                "SELECT id, titulo, situacao, url_oficial, 'ementa (texto integral não convertido)' AS rotulo, "
                "COALESCE(ementa, '') AS texto, NULL AS versao, NULL AS dispositivo_id, NULL AS inicio, NULL AS parte FROM documento WHERE especie = ? AND numero = ?",
                (ref.especie, ref.numero)).fetchall()
        return _achados(linhas)

    if especie:
        filtros.append("d.especie = ?")
        args.append(especie)
    if situacao:
        filtros.append("d.situacao = ?")
        args.append(situacao)
    if desde:
        filtros.append("d.data_edicao >= ?")
        args.append(desde)
    if ate:
        filtros.append("d.data_edicao <= ?")
        args.append(ate)
    onde = (" AND " + " AND ".join(filtros)) if filtros else ""
    sql = base.format(texto="snippet(dispositivo_fts, 0, '[', ']', ' … ', 24)",
                      origem="dispositivo_fts JOIN dispositivo x ON x.id = dispositivo_fts.rowid")
    sql += f" AND dispositivo_fts MATCH ?{onde} ORDER BY rank LIMIT ?"
    return _achados(conexao.execute(sql, [_fts(consulta), *args, limite]).fetchall())
