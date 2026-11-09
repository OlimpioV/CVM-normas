"""Leitura das justificativas de dispensa de AIR para a interface, a API, a biblioteca e o acervo público
(a coleta está em coleta/justificativas.py)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from repositorio_cvm.acervo import corpo_markdown


def justificativas_do_documento(conexao: sqlite3.Connection, documento_id: str) -> list[dict]:
    try:
        linhas = conexao.execute(
            "SELECT j.*, a.sha256, a.coletado_em, a.caminho AS caminho_original, e.trecho AS evidencia_trecho, "
            "e.url AS evidencia_url FROM justificativa j LEFT JOIN arquivo a ON a.id = j.arquivo_id "
            "LEFT JOIN evidencia e ON e.id = j.evidencia_id WHERE j.documento_id = ? ORDER BY j.id",
            (documento_id,)).fetchall()
    except sqlite3.OperationalError:  # banco ainda sem a migração v9
        return []
    return [dict(l) for l in linhas]


def paragrafos(pasta_dados: Path, justificativa: dict) -> list[str]:
    """Parágrafos do texto convertido (vazio se a conversão não foi aprovada)."""
    if not (justificativa.get("caminho_md") and justificativa.get("fidelidade_ok")):
        return []
    return [p for p in corpo_markdown(pasta_dados, justificativa["caminho_md"]).split("\n\n") if p.strip()]
