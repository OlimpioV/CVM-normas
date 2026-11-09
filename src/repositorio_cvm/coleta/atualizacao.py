"""Atualização incremental do acervo (Fase 3; agendamento na Fase 5).

Para cada norma do acervo (da verificada há mais tempo para a mais recente, o que torna a rotina retomável):
1. baixa a ficha oficial e compara o conteúdo lido (título, ementa, datas, links, relações, marcações) com o da
   última ficha guardada; o HTML bruto muda sem alteração de conteúdo (D-10), por isso não se compara o hash;
2. ficha igual: só registra a verificação; ficha diferente: guarda a nova ficha (original imutável), atualiza os
   metadados com evidência, registra as relações novas e a mudança de situação (possível revogação);
3. quando a ficha mudou (ou com `arquivos=True`), baixa de novo os arquivos de texto (íntegra, original,
   consolidado) e os links novos; arquivo com hash diferente é guardado como nova versão, convertido, e as
   diferenças entre a versão anterior e a nova são registradas por dispositivo.

Além disso, lê a primeira página do catálogo de cada família e registra os itens que ainda não tinham sido
vistos (publicações novas). Itens novos não são baixados nesta etapa: aparecem no relatório.
Nada é apagado: versões anteriores, evidências e fichas antigas permanecem.
"""

from __future__ import annotations

import difflib
import logging
import sqlite3
from dataclasses import dataclass, field

from repositorio_cvm.acervo import versoes_aprovadas
from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.coleta.catalogo import FAMILIAS, ler_pagina_catalogo, url_catalogo
from repositorio_cvm.coleta.coletor import Coletor
from repositorio_cvm.coleta.ficha import Ficha, ler_ficha
from repositorio_cvm.coleta.http import FetchError
from repositorio_cvm.gabarito import AtoGabarito

log = logging.getLogger("repositorio_cvm.atualizacao")
PAPEIS_TEXTO = ("integra", "original", "consolidado")


@dataclass
class Mudanca:
    documento_id: str
    tipo: str  # sem alteração, ficha alterada, relação nova, relação retirada, situação, arquivo novo, texto alterado, erro
    detalhe: str = ""


@dataclass
class ResultadoAtualizacao:
    mudancas: list[Mudanca] = field(default_factory=list)
    novidades: list[dict] = field(default_factory=list)
    primeira_leitura: list[str] = field(default_factory=list)  # famílias lidas pela primeira vez (base inicial)

    def resumo(self) -> dict:
        contagem: dict[str, int] = {}
        for m in self.mudancas:
            contagem[m.tipo] = contagem.get(m.tipo, 0) + 1
        return contagem | {"publicações novas no catálogo": len(self.novidades)}


def assinatura(ficha: Ficha) -> tuple:
    """Conteúdo da ficha que importa para o acervo (independe de menus, datas de página e formatação)."""
    return (
        ficha.titulo, ficha.data_edicao, ficha.ementa, tuple(ficha.assuntos), tuple(ficha.marcacoes),
        tuple((e.evento, e.veiculo, e.data) for e in ficha.eventos),
        tuple(sorted((l.url, l.papel, l.formato or "") for l in ficha.links)),
        tuple(sorted((r.tipo, r.alvo_url) for r in ficha.relacoes)),
    )


def _trecho_alterado(antes: str, depois: str, contexto: int = 6) -> str:
    """'art. 1º: … palavras [antigas → novas] palavras …' para um dispositivo alterado."""
    rotulo, _, texto_antes = antes.partition(": ")
    a, b = texto_antes.split(), depois.partition(": ")[2].split()
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            inicio = " ".join(a[max(0, a1 - contexto):a1])
            fim = " ".join(a[a2:a2 + contexto])
            return f"{rotulo}: …{inicio} [{' '.join(a[a1:a2]) or '∅'} → {' '.join(b[b1:b2]) or '∅'}] {fim}…"
    return rotulo


def diferencas_de_texto(conexao: sqlite3.Connection, versao_antiga: int, versao_nova: int,
                        limite: int = 8) -> str:
    """Resumo das diferenças entre duas versões de texto, por dispositivo (redação anterior excluída)."""
    def dispositivos(versao_id: int) -> list[str]:
        return [f"{r['rotulo']}: {r['texto']}" for r in conexao.execute(
            "SELECT rotulo, texto FROM dispositivo WHERE versao_id = ? AND tipo != 'redacao_anterior' ORDER BY ordem",
            (versao_id,))]

    antes, depois = dispositivos(versao_antiga), dispositivos(versao_nova)
    incluidos, retirados, alterados, exemplos = 0, 0, 0, []
    for op, a1, a2, b1, b2 in difflib.SequenceMatcher(None, antes, depois, autojunk=False).get_opcodes():
        if op == "insert":
            incluidos += b2 - b1
            exemplos += [f"+ {d}" for d in depois[b1:b2]]
        elif op == "delete":
            retirados += a2 - a1
            exemplos += [f"- {d}" for d in antes[a1:a2]]
        elif op == "replace":
            alterados += max(a2 - a1, b2 - b1)
            exemplos += [f"~ {_trecho_alterado(x, y)}" for x, y in zip(antes[a1:a2], depois[b1:b2])]
            exemplos += [f"- {d}" for d in antes[a1 + (b2 - b1):a2]] + [f"+ {d}" for d in depois[b1 + (a2 - a1):b2]]
    if not (incluidos or retirados or alterados):
        return "mesmo texto, dispositivo por dispositivo"
    amostra = "; ".join(e[:240] for e in exemplos[:limite])
    return (f"{incluidos} dispositivo(s) incluído(s), {retirados} retirado(s), {alterados} alterado(s)"
            + (f". Exemplos: {amostra}" if amostra else ""))


class Atualizador:
    def __init__(self, coletor: Coletor, arquivos: bool = False):
        self.coletor = coletor
        self.db = coletor.db
        self.arquivos = arquivos

    # ------------------------------------------------------------------ publicações novas
    def novidades(self, familias: list[str] | None = None) -> tuple[list[dict], list[str]]:
        familias = familias or list(FAMILIAS)
        conhecidas = {r[0] for r in self.db.execute("SELECT url_oficial FROM documento WHERE url_oficial IS NOT NULL")}
        novas, primeiras = [], []
        for familia in familias:
            url = url_catalogo(familia, 1)
            try:
                artefato = self.coletor.baixar(url, f"catalogo:{familia}", "html")
            except FetchError as erro:
                log.warning("catálogo %s indisponível: %s", familia, erro)
                continue
            pagina = ler_pagina_catalogo(artefato.bytes, url)
            primeira = not self.db.execute("SELECT 1 FROM catalogo_visto WHERE familia = ?", (familia,)).fetchone()
            if primeira:
                primeiras.append(familia)
            for item in pagina.itens:
                if self.db.execute("SELECT 1 FROM catalogo_visto WHERE url = ?", (item.url,)).fetchone():
                    continue
                self.db.execute("INSERT INTO catalogo_visto VALUES (?, ?, ?, ?, ?, ?)",
                                (item.url, familia, item.titulo, item.data, agora(), self.coletor.coleta_id))
                if not primeira:
                    novas.append({"familia": familia, "titulo": item.titulo, "url": item.url, "data": item.data,
                                  "no_acervo": item.url in conhecidas})
            self.db.commit()
        return novas, primeiras

    # ------------------------------------------------------------------ reverificação de uma norma
    def reverificar(self, documento_id: str) -> list[Mudanca]:
        doc = self.db.execute("SELECT * FROM documento WHERE id = ?", (documento_id,)).fetchone()
        if doc is None or not doc["url_oficial"]:
            return [Mudanca(documento_id, "erro", "norma sem ficha oficial registrada")]
        try:
            artefato = self.coletor.baixar(doc["url_oficial"], documento_id, "html")
        except FetchError as erro:
            return [Mudanca(documento_id, "erro", f"ficha não obtida: {erro}")]
        ficha_nova = ler_ficha(artefato.bytes, artefato.url)
        anterior = self.db.execute("SELECT caminho FROM arquivo WHERE documento_id = ? AND papel = 'ficha' "
                                   "ORDER BY id DESC LIMIT 1", (documento_id,)).fetchone()
        ficha_antiga = (ler_ficha((self.coletor.config.pasta_dados / anterior["caminho"]).read_bytes(), artefato.url)
                        if anterior else None)
        mudou = ficha_antiga is None or assinatura(ficha_antiga) != assinatura(ficha_nova)
        mudancas: list[Mudanca] = []
        versoes_antes = {v.tipo: v.id for v in versoes_aprovadas(self.db, documento_id)}

        if mudou:
            if not ficha_nova.titulo:
                return [Mudanca(documento_id, "erro", "ficha obtida sem conteúdo reconhecível; nada foi alterado")]
            mudancas += self._diferencas_de_ficha(documento_id, ficha_antiga, ficha_nova)
            situacao_antes = doc["situacao"]
            ato = AtoGabarito(chave=documento_id, especie=doc["especie"], numero=doc["numero"],
                              descricao_usuario="atualização incremental", ficha=doc["url_oficial"])
            self.coletor.coletar_ato(ato, artefato_ficha=artefato)
            situacao = self.db.execute("SELECT situacao FROM documento WHERE id = ?", (documento_id,)).fetchone()[0]
            if situacao != situacao_antes:
                alerta = " (possível revogação)" if "revogada" in situacao else ""
                mudancas.append(Mudanca(documento_id, "situação", f"{situacao_antes} → {situacao}{alerta}"))
        else:
            self.db.execute("UPDATE documento SET ultima_verificacao = ? WHERE id = ?", (agora(), documento_id))

        novos = self._arquivos_de_texto(documento_id) if (mudou or self.arquivos) else []
        mudancas += [Mudanca(documento_id, "arquivo novo", n) for n in novos]
        if novos:
            self.coletor.converter_arquivos(documento_id)
        self._status_pelo_texto(documento_id)
        for v in versoes_aprovadas(self.db, documento_id):
            if v.tipo in versoes_antes and versoes_antes[v.tipo] != v.id:
                mudancas.append(Mudanca(documento_id, "texto alterado",
                                        f"{v.tipo}: {diferencas_de_texto(self.db, versoes_antes[v.tipo], v.id)}"))
            elif v.tipo not in versoes_antes:
                mudancas.append(Mudanca(documento_id, "texto alterado", f"{v.tipo}: primeira versão aprovada"))
        self.db.commit()
        return mudancas or [Mudanca(documento_id, "sem alteração")]

    def _diferencas_de_ficha(self, documento_id: str, antiga: Ficha | None, nova: Ficha) -> list[Mudanca]:
        if antiga is None:
            return [Mudanca(documento_id, "ficha alterada", "primeira ficha guardada")]
        saida = []
        for campo in ("titulo", "data_edicao", "ementa"):
            if getattr(antiga, campo) != getattr(nova, campo):
                saida.append(Mudanca(documento_id, "ficha alterada",
                                     f"{campo}: {getattr(antiga, campo)!r} → {getattr(nova, campo)!r}"))
        rel_antes = {(r.tipo, r.alvo_url): r for r in antiga.relacoes}
        rel_depois = {(r.tipo, r.alvo_url): r for r in nova.relacoes}
        for chave in rel_depois.keys() - rel_antes.keys():
            r = rel_depois[chave]
            saida.append(Mudanca(documento_id, "relação nova", f"{r.tipo}: {r.alvo_titulo} ({r.trecho[:200]})"))
        for chave in rel_antes.keys() - rel_depois.keys():
            r = rel_antes[chave]
            saida.append(Mudanca(documento_id, "relação retirada da ficha",
                                 f"{r.tipo}: {r.alvo_titulo} (a relação gravada antes continua no acervo, com sua evidência)"))
        links_novos = {l.url for l in nova.links} - {l.url for l in antiga.links}
        if links_novos:
            saida.append(Mudanca(documento_id, "ficha alterada", "links novos: " + ", ".join(sorted(links_novos))))
        if not saida:
            saida.append(Mudanca(documento_id, "ficha alterada", "outras informações da ficha (eventos, tags ou marcações)"))
        return saida

    def _arquivos_de_texto(self, documento_id: str) -> list[str]:
        """Baixa de novo os arquivos de texto já conhecidos e os links ainda não baixados; devolve os novos."""
        novos = []
        for r in self.db.execute(
                "SELECT a.url, a.papel, a.formato, a.sha256 FROM arquivo a WHERE a.documento_id = ? AND a.papel IN "
                f"({','.join('?' * len(PAPEIS_TEXTO))}) AND a.id = (SELECT MAX(id) FROM arquivo b "
                "WHERE b.documento_id = a.documento_id AND b.url = a.url)", (documento_id, *PAPEIS_TEXTO)).fetchall():
            try:
                artefato = self.coletor.baixar(r["url"], documento_id, r["formato"])
            except FetchError as erro:
                log.warning("%s: %s não obtido: %s", documento_id, r["url"], erro)
                continue
            if artefato.sha256 != r["sha256"]:
                self.coletor.registrar_arquivo(documento_id, artefato, r["papel"], r["formato"])
                novos.append(f"{r['papel']}/{r['formato']} com conteúdo diferente: {r['url']}")
        antes = self.db.execute("SELECT COUNT(*) FROM arquivo WHERE documento_id = ?", (documento_id,)).fetchone()[0]
        baixados = [r.detalhe for r in self.coletor.baixar_arquivos(documento_id) if r.status == "ok"]
        depois = self.db.execute("SELECT COUNT(*) FROM arquivo WHERE documento_id = ?", (documento_id,)).fetchone()[0]
        if depois > antes:
            novos += [f"link novo da ficha: {u}" for u in baixados]
        self.db.commit()
        return novos

    def _status_pelo_texto(self, documento_id: str) -> None:
        """A recoleta da ficha marca "sem íntegra HTML" quando o texto vem de PDF/DOCX; com versão aprovada, o
        documento continua coletado."""
        if versoes_aprovadas(self.db, documento_id):
            self.db.execute("UPDATE documento SET status_coleta = 'coletado', motivo_pendencia = NULL "
                            "WHERE id = ? AND status_coleta != 'coletado'", (documento_id,))

    # ------------------------------------------------------------------ execução completa
    def executar(self, documentos: list[str] | None = None, novidades: bool = True,
                 ao_avancar=None) -> ResultadoAtualizacao:
        resultado = ResultadoAtualizacao()
        if novidades:
            resultado.novidades, resultado.primeira_leitura = self.novidades()
        ids = documentos or [r[0] for r in self.db.execute(
            "SELECT id FROM documento ORDER BY ultima_verificacao IS NOT NULL, ultima_verificacao, id")]
        for i, documento_id in enumerate(ids, 1):
            mudancas = self.reverificar(documento_id)
            resultado.mudancas += mudancas
            if ao_avancar:
                ao_avancar(i, len(ids), documento_id, mudancas)
        return resultado


def relatorio_markdown(resultado: ResultadoAtualizacao, inicio: str, fim: str) -> str:
    alteradas = [m for m in resultado.mudancas if m.tipo not in ("sem alteração", "erro")]
    erros = [m for m in resultado.mudancas if m.tipo == "erro"]
    sem = sorted({m.documento_id for m in resultado.mudancas if m.tipo == "sem alteração"})
    linhas = ["# Relatório de atualização do acervo", "",
              f"Início: {inicio} · fim: {fim} (UTC).", "",
              "Resumo: " + ", ".join(f"{k}: {v}" for k, v in resultado.resumo().items()), ""]
    linhas += ["## Publicações novas no catálogo oficial", ""]
    if resultado.primeira_leitura:
        linhas.append("Primeira leitura do catálogo de " + ", ".join(resultado.primeira_leitura) +
                      ": os itens da primeira página foram registrados como base; publicações novas serão "
                      "apontadas a partir da próxima atualização.")
    if resultado.novidades:
        linhas += [f"- {n['titulo']} ({n['data'] or 'sem data'}) — {n['url']}" +
                   (" (já no acervo)" if n["no_acervo"] else " (não baixada; fora do acervo atual)")
                   for n in resultado.novidades]
    elif not resultado.primeira_leitura:
        linhas.append("Nenhuma publicação nova na primeira página do catálogo de cada família.")
    linhas += ["", "## Alterações em normas do acervo", ""]
    linhas += [f"- **{m.documento_id}** · {m.tipo}: {m.detalhe}" for m in alteradas] or ["Nenhuma alteração detectada."]
    if erros:
        linhas += ["", "## Erros (verificar na próxima execução)", ""] + [f"- {m.documento_id}: {m.detalhe}" for m in erros]
    linhas += ["", f"## Sem alteração ({len(sem)})", "", ", ".join(sem) or "—"]
    return "\n".join(linhas) + "\n"
