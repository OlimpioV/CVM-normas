"""Leitura das audiências públicas do acervo para a interface e a API local (a coleta está em coleta/audiencias.py).

Cada audiência vem com a origem da relação com a norma (ficha da norma ou seção "Norma editada" da página da
audiência), os arquivos oficiais e os textos convertidos. As manifestações recebidas não fazem parte do acervo.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from repositorio_cvm.pesquisa import _fts


def _arquivos(conexao: sqlite3.Connection, audiencia_id: str) -> list[dict]:
    return [dict(l) for l in conexao.execute(
        "SELECT l.*, a.sha256, a.coletado_em, a.tamanho, t.id AS texto_id, t.fidelidade_ok, t.qualidade "
        "FROM audiencia_link l LEFT JOIN arquivo a ON a.id = l.arquivo_id "
        "LEFT JOIN audiencia_texto t ON t.id = (SELECT MAX(id) FROM audiencia_texto WHERE arquivo_id = l.arquivo_id) "
        "WHERE l.audiencia_id = ? ORDER BY l.ordem", (audiencia_id,))]


def carregar(conexao: sqlite3.Connection, audiencia_id: str) -> dict | None:
    linha = conexao.execute(
        "SELECT au.*, a.sha256 AS pagina_sha256, a.coletado_em AS pagina_coletada_em FROM audiencia au "
        "LEFT JOIN arquivo a ON a.id = au.arquivo_id WHERE au.id = ?", (audiencia_id,)).fetchone()
    if linha is None:
        return None
    aud = dict(linha)
    aud["arquivos"] = _arquivos(conexao, audiencia_id)
    aud["normas"] = [dict(r) for r in conexao.execute(
        "SELECT da.documento_id, da.origem, d.titulo, e.trecho, e.url AS evidencia_url, e.registrado_em "
        "FROM documento_audiencia da JOIN documento d ON d.id = da.documento_id "
        "JOIN evidencia e ON e.id = da.evidencia_id WHERE da.audiencia_id = ? ORDER BY d.id, da.origem", (audiencia_id,))]
    aud["prazos_divergem"] = bool(aud["prazo"] and aud["prazo_edital"] and aud["prazo"] != aud["prazo_edital"])
    return aud


def audiencias_do_documento(conexao: sqlite3.Connection, documento_id: str) -> list[dict]:
    """Audiências ligadas à norma, cada uma com as origens da ligação (evidências)."""
    try:
        ids = [r[0] for r in conexao.execute(
            "SELECT DISTINCT da.audiencia_id FROM documento_audiencia da JOIN audiencia a ON a.id = da.audiencia_id "
            "WHERE da.documento_id = ? ORDER BY a.prazo, a.id", (documento_id,))]
    except sqlite3.OperationalError:  # banco ainda sem a migração v7
        return []
    resultado = []
    for aud_id in ids:
        aud = carregar(conexao, aud_id)
        aud["origens"] = [dict(r) for r in conexao.execute(
            "SELECT da.origem, e.trecho, e.url, e.registrado_em FROM documento_audiencia da "
            "JOIN evidencia e ON e.id = da.evidencia_id WHERE da.documento_id = ? AND da.audiencia_id = ?",
            (documento_id, aud_id))]
        resultado.append(aud)
    return resultado


def paragrafos(pasta_dados: Path, conexao: sqlite3.Connection, texto_id: int) -> list[str]:
    linha = conexao.execute("SELECT caminho_md FROM audiencia_texto WHERE id = ?", (texto_id,)).fetchone()
    if linha is None:
        return []
    texto = (pasta_dados / linha["caminho_md"]).read_text(encoding="utf-8")
    if texto.startswith("---\n"):
        fim = texto.find("\n---\n", 4)
        texto = texto[fim + 5:] if fim != -1 else texto
    return [p for p in re.split(r"\n{2,}", texto.strip()) if p]


def pesquisar(conexao: sqlite3.Connection, consulta: str, limite: int = 30) -> list[dict]:
    """Pesquisa nos editais e relatórios convertidos (FTS5), com o trecho e o arquivo de origem."""
    if not consulta.strip():
        return []
    try:
        return [dict(r) for r in conexao.execute(
            "SELECT t.audiencia_id, au.codigo, au.tema, l.secao, l.rotulo, l.url, t.texto_id, t.ordem, "
            "snippet(audiencia_trecho_fts, 0, '[', ']', ' … ', 24) AS trecho "
            "FROM audiencia_trecho_fts JOIN audiencia_trecho t ON t.id = audiencia_trecho_fts.rowid "
            "JOIN audiencia au ON au.id = t.audiencia_id JOIN audiencia_texto x ON x.id = t.texto_id "
            "JOIN audiencia_link l ON l.id = x.link_id "
            "WHERE audiencia_trecho_fts MATCH ? ORDER BY rank LIMIT ?",
            (_fts(consulta), limite))]
    except sqlite3.OperationalError:
        return []
