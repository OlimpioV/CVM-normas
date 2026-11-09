"""Banco SQLite do acervo: esquema versionado, migrações com backup automático e FTS5.

Regras:
- toda mudança de esquema é uma migração numerada em MIGRACOES;
- antes de aplicar qualquer migração num banco já existente, é feita uma cópia em
  `<dados>/backups/acervo-<data>-v<versão>.sqlite`;
- nada é apagado: atualizações de metadados acrescentam evidências, não substituem histórico.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SITUACOES = (
    "vigente",
    "vigente com alterações",
    "parcialmente revogada",
    "integralmente revogada",
    "vigência futura",
    "histórica",
    "não verificado",
)
CLASSIFICACOES_LACUNA = ("inexistente", "não localizado", "indisponível para download")

_V1 = """
CREATE TABLE documento (
    id                   TEXT PRIMARY KEY,           -- ex.: resolucao-cvm-50-2021
    especie              TEXT NOT NULL,              -- resolucao, deliberacao, oficio_circular...
    numero               TEXT,
    ano                  INTEGER,
    titulo               TEXT,
    ementa               TEXT,
    assunto              TEXT,
    area_tecnica         TEXT,
    data_edicao          TEXT,
    data_publicacao      TEXT,
    data_inicio_vigencia TEXT,
    data_fim_vigencia    TEXT,
    situacao             TEXT NOT NULL DEFAULT 'não verificado',
    url_oficial          TEXT,
    status_coleta        TEXT NOT NULL,              -- coletado, pendente, não localizado, indisponível
    motivo_pendencia     TEXT,
    criado_em            TEXT NOT NULL,
    atualizado_em        TEXT NOT NULL,
    ultima_verificacao   TEXT,
    CHECK (situacao IN ('vigente','vigente com alterações','parcialmente revogada',
                        'integralmente revogada','vigência futura','histórica','não verificado'))
);

CREATE TABLE arquivo (
    id            INTEGER PRIMARY KEY,
    documento_id  TEXT REFERENCES documento(id),
    sha256        TEXT NOT NULL,
    url           TEXT NOT NULL,
    papel         TEXT NOT NULL,                     -- ficha, integra, consolidado, original, anexo
    formato       TEXT,
    content_type  TEXT,
    tamanho       INTEGER NOT NULL,
    caminho       TEXT NOT NULL,                     -- relativo à pasta de dados
    etag          TEXT,
    last_modified TEXT,
    coletado_em   TEXT NOT NULL,                     -- UTC, ISO 8601
    origem_coleta TEXT NOT NULL,                     -- coleta direta | importado de coleta anterior
    UNIQUE (documento_id, url, sha256)
);

CREATE TABLE link_documento (
    id           INTEGER PRIMARY KEY,
    documento_id TEXT NOT NULL REFERENCES documento(id),
    rotulo       TEXT,
    url          TEXT NOT NULL,
    formato      TEXT,
    papel        TEXT,
    baixado      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (documento_id, url)
);

CREATE TABLE evidencia (
    id            INTEGER PRIMARY KEY,
    documento_id  TEXT NOT NULL REFERENCES documento(id),
    campo         TEXT NOT NULL,                     -- titulo, ementa, data_publicacao, situacao...
    valor         TEXT,
    url           TEXT NOT NULL,
    sha256        TEXT,                              -- hash do arquivo de onde veio o trecho
    trecho        TEXT,
    registrado_em TEXT NOT NULL
);

CREATE TABLE relacao (
    id            INTEGER PRIMARY KEY,
    documento_id  TEXT NOT NULL REFERENCES documento(id),
    tipo          TEXT NOT NULL CHECK (tipo IN ('altera','revoga','alterada_por','revogada_por','vide')),
    alvo_titulo   TEXT,
    alvo_url      TEXT NOT NULL,
    alvo_id       TEXT,                              -- preenchido quando o alvo está no acervo
    evidencia_id  INTEGER NOT NULL REFERENCES evidencia(id),
    UNIQUE (documento_id, tipo, alvo_url)
);

CREATE TABLE versao_texto (
    id                 INTEGER PRIMARY KEY,
    documento_id       TEXT NOT NULL REFERENCES documento(id),
    arquivo_id         INTEGER NOT NULL REFERENCES arquivo(id),
    tipo               TEXT NOT NULL,                -- texto original | texto consolidado oficial
    caminho_md         TEXT NOT NULL,
    conversor          TEXT NOT NULL,
    fidelidade_ok      INTEGER NOT NULL,
    fidelidade_detalhe TEXT,
    qualidade          TEXT NOT NULL,
    gerado_em          TEXT NOT NULL,
    UNIQUE (arquivo_id, conversor)
);

CREATE TABLE dispositivo (
    id           INTEGER PRIMARY KEY,
    versao_id    INTEGER NOT NULL REFERENCES versao_texto(id),
    documento_id TEXT NOT NULL REFERENCES documento(id),
    ordem        INTEGER NOT NULL,
    tipo         TEXT NOT NULL,                      -- preambulo, titulo, artigo, paragrafo, inciso...
    artigo       TEXT,                               -- número do artigo a que pertence (ex.: 1, 10-A)
    rotulo       TEXT NOT NULL,                      -- ex.: art. 5º, § 2º, inciso III
    texto        TEXT NOT NULL
);
CREATE INDEX dispositivo_documento ON dispositivo(documento_id, artigo);

CREATE VIRTUAL TABLE dispositivo_fts USING fts5(
    texto, rotulo, content='dispositivo', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE lacuna (
    id                 INTEGER PRIMARY KEY,
    chave              TEXT NOT NULL,                -- documento esperado (ex.: resolucao-cvm-12-2020)
    classificacao      TEXT NOT NULL CHECK (classificacao IN ('inexistente','não localizado','indisponível para download')),
    detalhe            TEXT,
    fontes_consultadas TEXT,
    url                TEXT,
    erro               TEXT,
    registrado_em      TEXT NOT NULL
);

CREATE TABLE coleta (
    id           INTEGER PRIMARY KEY,
    escopo       TEXT NOT NULL,
    iniciada_em  TEXT NOT NULL,
    terminada_em TEXT,
    status       TEXT NOT NULL,                      -- em andamento, concluída, interrompida
    resumo       TEXT
);

CREATE TABLE tentativa (
    id        INTEGER PRIMARY KEY,
    coleta_id INTEGER REFERENCES coleta(id),
    chave     TEXT,
    url       TEXT NOT NULL,
    resultado TEXT NOT NULL,                         -- ok, erro, bloqueado, não modificado
    detalhe   TEXT,
    em        TEXT NOT NULL
);
"""

# v2 (Fase 2, conversão de PDF/DOCX): parte da norma em cada dispositivo (ex.: "Anexo Normativo I")
# e resultado da conferência cruzada DOCX x PDF em cada versão de texto.
_V2 = """
ALTER TABLE dispositivo ADD COLUMN parte TEXT;
ALTER TABLE versao_texto ADD COLUMN conferencia_cruzada TEXT;
"""

# v3 (D-14): dicionário de glifos das fontes Type3 decifradas, compartilhado pelo acervo.
_V3 = """
CREATE TABLE glifo (
    hash          TEXT PRIMARY KEY,                  -- SHA-1 do programa do glifo (CharProc)
    caractere     TEXT NOT NULL,
    votos         INTEGER NOT NULL,
    concordancia  REAL NOT NULL,                     -- 0 quando documentos discordam (conflito)
    documentos    TEXT NOT NULL,                     -- ids dos documentos em que foi decifrado
    atualizado_em TEXT NOT NULL
);
"""

# v4 (Fase 3, atualização incremental): itens já vistos no catálogo oficial, para distinguir publicações
# novas das que já constavam da página na verificação anterior.
_V4 = """
CREATE TABLE catalogo_visto (
    url            TEXT PRIMARY KEY,
    familia        TEXT NOT NULL,
    titulo         TEXT,
    data           TEXT,
    primeira_vez   TEXT NOT NULL,                    -- quando o item apareceu pela primeira vez numa verificação
    coleta_id      INTEGER REFERENCES coleta(id)
);
"""

# v5 (cobertura em relação à CVM): leitura completa do catálogo oficial de cada família. Cada item guarda a
# última leitura em que apareceu; itens que saírem do catálogo não são apagados, só deixam de ser contados.
_V5 = """
CREATE TABLE leitura_catalogo (
    id                 INTEGER PRIMARY KEY,
    familia            TEXT NOT NULL,
    iniciada_em        TEXT NOT NULL,
    terminada_em       TEXT,
    total_informado    INTEGER,                      -- "N resultados encontrados" da página oficial
    total_lido         INTEGER,
    paginas_informadas INTEGER,
    paginas_lidas      INTEGER,
    status             TEXT NOT NULL                 -- em andamento, completa, incompleta, interrompida
);

CREATE TABLE catalogo_oficial (
    url           TEXT PRIMARY KEY,
    familia       TEXT NOT NULL,
    titulo        TEXT,
    data          TEXT,                              -- data exibida no catálogo (data de edição do ato)
    descricao     TEXT,
    numero        INTEGER,                           -- número do ato, nas espécies numeradas em sequência
    leitura_id    INTEGER NOT NULL REFERENCES leitura_catalogo(id),
    primeira_vez  TEXT NOT NULL
);
CREATE INDEX catalogo_oficial_familia ON catalogo_oficial(familia, leitura_id);
"""

# v6: observação da leitura do catálogo (ex.: a própria CVM informa totais diferentes em páginas diferentes).
_V6 = """
ALTER TABLE leitura_catalogo ADD COLUMN observacao TEXT;
"""

# v7: audiências públicas das normas (edital, prazo, fase, relatório e normas editadas; sem as manifestações).
# Os arquivos baixados (página, edital, relatório) ficam em `arquivo`, sem documento_id, e são verificados por hash
# como os demais originais. A relação norma <-> audiência guarda a evidência de cada origem.
_V7 = """
CREATE TABLE audiencia (
    id                 TEXT PRIMARY KEY,             -- do endereço oficial: ap_sdm/2021/sdm0221 -> sdm-2021-sdm0221
    url                TEXT NOT NULL UNIQUE,
    codigo             TEXT,                         -- como no título da página: "SDM 02/21"
    titulo             TEXT,
    tema               TEXT,
    prazo              TEXT,                         -- AAAA-MM-DD, "Prazo para Manifestação" como exibido na página
    prazo_texto        TEXT,
    prazo_edital       TEXT,                         -- AAAA-MM-DD, linha "Prazo:" do edital
    prazo_edital_texto TEXT,
    fase               TEXT,
    status             TEXT NOT NULL,                -- não lida, lida, indisponível
    detalhe            TEXT,
    arquivo_id         INTEGER REFERENCES arquivo(id), -- página lida por último (evidência de tema, prazo e fase)
    lida_em            TEXT
);

CREATE TABLE audiencia_link (
    id           INTEGER PRIMARY KEY,
    audiencia_id TEXT NOT NULL REFERENCES audiencia(id),
    secao        TEXT NOT NULL,                      -- edital, relatório, norma editada, versão em inglês...
    rotulo       TEXT,
    url          TEXT NOT NULL,
    formato      TEXT,
    ordem        INTEGER NOT NULL,
    arquivo_id   INTEGER REFERENCES arquivo(id),     -- versão baixada mais recente
    UNIQUE (audiencia_id, url)
);

CREATE TABLE audiencia_texto (
    id            INTEGER PRIMARY KEY,
    link_id       INTEGER NOT NULL REFERENCES audiencia_link(id),
    arquivo_id    INTEGER NOT NULL REFERENCES arquivo(id),
    caminho_md    TEXT NOT NULL,
    conversor     TEXT NOT NULL,
    fidelidade_ok INTEGER NOT NULL,
    qualidade     TEXT NOT NULL,
    gerado_em     TEXT NOT NULL,
    UNIQUE (arquivo_id, conversor)
);

CREATE TABLE audiencia_trecho (
    id           INTEGER PRIMARY KEY,
    texto_id     INTEGER NOT NULL REFERENCES audiencia_texto(id),
    audiencia_id TEXT NOT NULL REFERENCES audiencia(id),
    ordem        INTEGER NOT NULL,
    texto        TEXT NOT NULL
);
CREATE VIRTUAL TABLE audiencia_trecho_fts USING fts5(
    texto, content='audiencia_trecho', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE documento_audiencia (
    id           INTEGER PRIMARY KEY,
    documento_id TEXT NOT NULL REFERENCES documento(id),
    audiencia_id TEXT NOT NULL REFERENCES audiencia(id),
    origem       TEXT NOT NULL,                      -- ficha da norma | página da audiência (norma editada)
    evidencia_id INTEGER NOT NULL REFERENCES evidencia(id),
    UNIQUE (documento_id, audiencia_id, origem)
);
"""

# v8: versões derivadas de outra versão (consolidado sem tachado, consolidação gerada) e o registro de cada
# alteração aplicada automaticamente, com o trecho do ato alterador que a fundamenta (D-21).
_V8 = """
ALTER TABLE versao_texto ADD COLUMN base_versao_id INTEGER REFERENCES versao_texto(id);

CREATE TABLE alteracao_aplicada (
    id             INTEGER PRIMARY KEY,
    versao_id      INTEGER NOT NULL REFERENCES versao_texto(id),
    ato_id         TEXT NOT NULL REFERENCES documento(id),  -- norma alteradora
    comando        TEXT NOT NULL,                            -- trecho do ato alterador
    operacao       TEXT NOT NULL,                            -- redacao | acrescimo | revogacao | parte
    alvo           TEXT,                                     -- rótulo do dispositivo alterado
    status         TEXT NOT NULL,                            -- aplicada | alvo não localizado | não reconhecido | vigência futura
    vigencia       TEXT,                                     -- início de vigência da alteração (AAAA-MM-DD)
    detalhe        TEXT
);
CREATE INDEX alteracao_aplicada_versao ON alteracao_aplicada(versao_id);
"""

# v9: justificativas de dispensa de Análise de Impacto Regulatório (AIR) citadas na ficha da norma: PDF anexo
# ou página da decisão do Colegiado. Como as audiências, são documentos próprios ligados à norma (D-24).
_V9 = """
CREATE TABLE justificativa (
    id            INTEGER PRIMARY KEY,
    documento_id  TEXT NOT NULL REFERENCES documento(id),
    rotulo        TEXT NOT NULL,                      -- texto do link na ficha
    url           TEXT NOT NULL,
    formato       TEXT,                               -- pdf | docx | html
    evidencia_id  INTEGER REFERENCES evidencia(id),   -- a ficha que cita a justificativa
    arquivo_id    INTEGER REFERENCES arquivo(id),
    status        TEXT NOT NULL,                      -- não baixada | baixada | indisponível | proibida pelo robots.txt
    detalhe       TEXT,
    caminho_md    TEXT,
    conversor     TEXT,
    fidelidade_ok INTEGER,
    qualidade     TEXT,
    convertida_em TEXT,
    UNIQUE (documento_id, url)
);
"""

MIGRACOES: list[tuple[int, str]] = [(1, _V1), (2, _V2), (3, _V3), (4, _V4), (5, _V5), (6, _V6), (7, _V7), (8, _V8),
                                    (9, _V9)]


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def versao_atual(conexao: sqlite3.Connection) -> int:
    conexao.execute("CREATE TABLE IF NOT EXISTS esquema_versao (versao INTEGER PRIMARY KEY, aplicada_em TEXT NOT NULL)")
    linha = conexao.execute("SELECT MAX(versao) FROM esquema_versao").fetchone()
    return linha[0] or 0


def abrir(caminho: Path, pasta_backups: Path | None = None) -> sqlite3.Connection:
    """Abre (ou cria) o banco e aplica migrações pendentes, com backup prévio se já houver dados."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    existia = caminho.exists() and caminho.stat().st_size > 0
    conexao = sqlite3.connect(caminho)
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA foreign_keys = ON")
    conexao.execute("PRAGMA journal_mode = WAL")
    atual = versao_atual(conexao)
    pendentes = [(v, sql) for v, sql in MIGRACOES if v > atual]
    if pendentes and existia and atual > 0:
        fazer_backup(conexao, (pasta_backups or caminho.parent / "backups"), f"antes-v{pendentes[0][0]}")
    for versao, sql in pendentes:
        # Migração atômica: esquema e registro de versão na mesma transação.
        conexao.executescript(
            f"BEGIN;\n{sql}\nINSERT INTO esquema_versao (versao, aplicada_em) VALUES ({versao}, '{agora()}');\nCOMMIT;"
        )
    return conexao


def fazer_backup(conexao: sqlite3.Connection, pasta: Path, sufixo: str = "manual") -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = pasta / f"acervo-{carimbo}-{sufixo}.sqlite"
    copia = sqlite3.connect(destino)
    with copia:
        conexao.backup(copia)
    copia.close()
    return destino
