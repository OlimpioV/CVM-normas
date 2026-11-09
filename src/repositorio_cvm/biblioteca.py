"""Biblioteca legível: os documentos do acervo organizados em pastas com nomes de gente (`dados/biblioteca`).

A fonte de verdade continua sendo `dados/originais` (arquivos endereçados por hash, imutáveis) e o banco. A
biblioteca é só uma visão gerada a partir deles: pode ser apagada e gerada de novo a qualquer momento.

Estrutura:
    biblioteca/
      LEIAME.txt
      Resoluções/Resolução CVM 175/
        LEIAME.txt                       metadados, situação, partes, origem e hash de cada arquivo
        Ficha oficial.html
        Texto consolidado.pdf · Texto consolidado.docx · Redação original.pdf
        Texto consolidado - só o texto vigente.md · Redação original (conversão).md
        Texto alterado com tachado (consolidado oficial, conversão).md
        Audiência SDM 08-20/             edital, aviso, relatório e textos convertidos
        Versões anteriores/              arquivos oficiais que mudaram depois (data da coleta no nome)
      Audiências públicas/2020 - SDM 08-20/ ...

Os arquivos oficiais são vínculos físicos (hard links) para `dados/originais`: aparecem com nome legível sem
ocupar espaço de novo. Como são o mesmo arquivo, os originais ficam com o atributo "somente leitura", para que
nenhuma edição feita pela biblioteca altere o original. Sem suporte a vínculos (outro volume ou sistema de
arquivos), o arquivo é copiado. As conversões em Markdown são sempre copiadas: são regeneradas pelo conversor.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path

from repositorio_cvm import acervo
from repositorio_cvm.armazenamento import originais
from repositorio_cvm.armazenamento.banco import agora
from repositorio_cvm.justificativas import justificativas_do_documento

MARCA = ".biblioteca-gerada"  # só uma pasta com esta marca é apagada ao gerar de novo
PASTAS_ESPECIE = {
    "resolucao": "Resoluções", "instrucao": "Instruções", "deliberacao": "Deliberações",
    "parecer_orientacao": "Pareceres de Orientação", "oficio_circular": "Ofícios-Circulares",
    "nota_explicativa": "Notas Explicativas",
}
PASTA_AUDIENCIAS = "Audiências públicas"
_NOMES_PAPEL = {"ficha": "Ficha oficial", "integra": "Íntegra", "original": "Redação original",
                "consolidado": "Texto consolidado"}
_NOMES_VERSAO = {acervo.TIPO_VIGENTE: "Texto consolidado - só o texto vigente",
                 acervo.TIPO_OFICIAL: "Texto alterado com tachado (consolidado oficial, conversão)",
                 acervo.TIPO_ALTERADO: "Texto alterado com tachado (gerado automaticamente)",
                 acervo.TIPO_ORIGINAL: "Redação original (conversão)"}


@dataclass
class Resultado:
    pasta: Path
    normas: int = 0
    audiencias: int = 0
    vinculos: int = 0
    copias: int = 0
    avisos: list[str] = field(default_factory=list)


def nome_seguro(texto: str, limite: int = 90) -> str:
    """Nome de arquivo válido no Windows: sem / \\ : * ? " < > |, sem ponto ou espaço no fim."""
    texto = texto.replace("/", "-").replace("\\", "-")
    texto = re.sub(r'[:*?"<>|\x00-\x1f]', "", texto)
    texto = " ".join(texto.split())[:limite]
    return texto.rstrip(". ") or "sem nome"


def _data(iso: str | None) -> str:
    return (iso or "")[:10] or "sem data"


def marcar_originais_somente_leitura(pasta_dados: Path) -> int:
    """Atributo "somente leitura" em todos os originais (vale também para os vínculos da biblioteca)."""
    marcados = 0
    for arquivo in (pasta_dados / "originais").rglob("*"):
        if arquivo.is_file() and arquivo.stat().st_mode & stat.S_IWRITE:
            arquivo.chmod(stat.S_IREAD)
            marcados += 1
    return marcados


def _apagar_somente_leitura(funcao, caminho, _excecao):
    # Apagar um vínculo não apaga o original; no Windows, porém, o atributo precisa sair antes. Ele é
    # recolocado em todos os originais ao fim da geração.
    os.chmod(caminho, stat.S_IWRITE)
    funcao(caminho)


class Gerador:
    def __init__(self, pasta_dados: Path, conexao: sqlite3.Connection):
        self.dados = pasta_dados
        self.db = conexao
        self.destino = pasta_dados / "biblioteca"
        self.resultado = Resultado(self.destino)

    # ------------------------------------------------------------------ arquivos
    @staticmethod
    def _livre(destino: Path) -> Path:
        """Mesmo nome já usado na pasta (ex.: dois anexos com o mesmo rótulo): acrescenta " (2)", " (3)"..."""
        n = 2
        livre = destino
        while livre.exists():
            livre = destino.with_name(f"{destino.stem} ({n}){destino.suffix}")
            n += 1
        return livre

    def _vincular(self, relativo_original: str, destino: Path, sha256: str) -> None:
        origem = self.dados / relativo_original
        destino = self._livre(destino)
        if not originais.verificar(self.dados, relativo_original, sha256):
            self.resultado.avisos.append(f"original ausente ou com hash divergente, não incluído: {relativo_original}")
            return
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(origem, destino)
                self.resultado.vinculos += 1
                return
            except OSError:
                if len(str(destino)) >= 250:
                    raise  # caminho longo demais para o Windows: copiar também falharia
            shutil.copy2(origem, destino)
            destino.chmod(stat.S_IREAD)
            self.resultado.copias += 1
        except OSError as erro:
            self.resultado.avisos.append(f"não incluído ({erro.strerror or erro}): {destino}")

    def _copiar_md(self, relativo_md: str, destino: Path) -> None:
        origem = self.dados / relativo_md
        destino = self._livre(destino)
        if origem.is_file():
            try:
                destino.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(origem, destino)
                self.resultado.copias += 1
            except OSError as erro:
                self.resultado.avisos.append(f"não incluído ({erro.strerror or erro}): {destino}")

    # ------------------------------------------------------------------ normas
    def _norma(self, base: Path, documento_id: str) -> Path:
        doc = acervo.carregar(self.db, documento_id)
        pasta = base / PASTAS_ESPECIE.get(doc.linha["especie"], "Outros") / nome_seguro(doc.titulo)
        linhas_arquivos: list[str] = []
        arquivos = self.db.execute(
            "SELECT * FROM arquivo WHERE documento_id = ? AND papel != 'justificativa' ORDER BY papel, formato, coletado_em DESC, id DESC",
            (documento_id,)).fetchall()
        vistos: set[tuple[str, str]] = set()
        for a in arquivos:
            nome_papel = _NOMES_PAPEL.get(a["papel"], a["papel"].capitalize())
            ext = Path(a["caminho"]).suffix
            chave = (a["papel"], a["formato"] or ext)
            if chave in vistos:  # versão anterior do mesmo arquivo oficial
                nome = Path("Versões anteriores") / f"{_data(a['coletado_em'])} {nome_papel}{ext}"
            else:
                vistos.add(chave)
                nome = Path(f"{nome_papel}{ext}")
            self._vincular(a["caminho"], pasta / nome, a["sha256"])
            linhas_arquivos.append(f"- {nome.as_posix()}: {a['url']} (coletado em {acervo.data_br(_data(a['coletado_em']))}; "
                                   f"SHA-256 {a['sha256']})")
        for v in doc.versoes:
            nome = f"{_NOMES_VERSAO.get(v.tipo, v.tipo)}.md"
            self._copiar_md(v.caminho_md, pasta / nome)
            linhas_arquivos.append(f"- {nome}: {v.aviso} Conversão automática ({v.conversor}; qualidade {v.nivel}) de "
                                   f"{v.url_fonte.rsplit('/', 1)[-1]}. Em divergência, prevalece o original.")

        partes = []
        versao = doc.versao()
        if versao:
            partes = [p.titulo for p in acervo.partes(self.db, doc, versao)]
        audiencias = []
        for aud in self._audiencias_da_norma(documento_id):
            sub = pasta / f"Audiência {nome_seguro(aud['codigo'] or aud['id'])}"
            self._arquivos_da_audiencia(aud["id"], sub)
            audiencias.append(f"{aud['codigo'] or aud['id']} (pasta \"{sub.name}\")")

        for j in justificativas_do_documento(self.db, documento_id):
            if not j["arquivo_id"]:
                continue
            base = nome_seguro("Justificativa - Dispensa de AIR")
            self._vincular(j["caminho_original"], pasta / f"{base}.{j['formato']}", j["sha256"])
            linhas_arquivos.append(f"- {base}.{j['formato']}: “{j['rotulo']}”, {j['url']} (coletado em "
                                   f"{acervo.data_br(_data(j['coletado_em']))}; SHA-256 {j['sha256']})")
            if j["caminho_md"] and j["fidelidade_ok"]:
                self._copiar_md(j["caminho_md"], pasta / f"{base} (conversão).md")
                linhas_arquivos.append(f"- {base} (conversão).md: texto extraído automaticamente; prevalece o original.")

        l = doc.linha
        texto = [
            doc.titulo, "",
            f"Ementa: {l['ementa'] or 'não informada'}",
            f"Data de edição: {acervo.data_br(l['data_edicao'])} · Publicação no DOU: {acervo.data_br(l['data_publicacao'])}",
            f"Situação normativa: {l['situacao']}",
            f"Aviso: {doc.aviso_vigencia()}",
            f"Ficha oficial: {l['url_oficial'] or 'não informada'}",
        ]
        if partes:
            texto.append(f"Partes ({versao.tipo}): " + "; ".join(partes))
        if audiencias:
            texto.append("Audiências públicas: " + "; ".join(audiencias))
        texto += ["", "Arquivos desta pasta:", *linhas_arquivos, "", _RODAPE]
        self._escrever(pasta / "LEIAME.txt", "\n".join(texto))
        self.resultado.normas += 1
        return pasta

    # ------------------------------------------------------------------ audiências
    def _tem_audiencias(self) -> bool:
        return self.db.execute("SELECT 1 FROM sqlite_master WHERE name = 'audiencia'").fetchone() is not None

    def _audiencias_da_norma(self, documento_id: str) -> list[sqlite3.Row]:
        if not self._tem_audiencias():
            return []
        return self.db.execute(
            "SELECT DISTINCT a.* FROM audiencia a JOIN documento_audiencia da ON da.audiencia_id = a.id "
            "WHERE da.documento_id = ? ORDER BY a.id", (documento_id,)).fetchall()

    def _arquivos_da_audiencia(self, audiencia_id: str, pasta: Path) -> None:
        aud = self.db.execute("SELECT * FROM audiencia WHERE id = ?", (audiencia_id,)).fetchone()
        linhas = []
        secoes_vistas: set[str] = set()
        for l in self.db.execute(
                "SELECT l.*, a.caminho, a.sha256, a.coletado_em, t.caminho_md, t.fidelidade_ok FROM audiencia_link l "
                "JOIN arquivo a ON a.id = l.arquivo_id "
                "LEFT JOIN audiencia_texto t ON t.id = (SELECT MAX(id) FROM audiencia_texto WHERE arquivo_id = l.arquivo_id) "
                "WHERE l.audiencia_id = ? ORDER BY l.ordem", (audiencia_id,)):
            base = _nome_arquivo_audiencia(l["secao"], l["rotulo"] or Path(l["url"]).stem, l["secao"] in secoes_vistas)
            secoes_vistas.add(l["secao"])
            self._vincular(l["caminho"], pasta / f"{base}{Path(l['caminho']).suffix}", l["sha256"])
            linhas.append(f"- {base}{Path(l['caminho']).suffix}: “{l['rotulo']}”, {l['url']} (coletado em "
                          f"{acervo.data_br(_data(l['coletado_em']))}; SHA-256 {l['sha256']})")
            if l["caminho_md"] and l["fidelidade_ok"]:
                self._copiar_md(l["caminho_md"], pasta / f"{base} (conversão).md")
                linhas.append(f"- {base} (conversão).md: texto extraído automaticamente; prevalece o original.")
            elif l["caminho_md"]:
                linhas.append(f"  (sem texto convertido: arquivo sem camada de texto legível)")
        texto = [
            f"Audiência Pública {aud['codigo'] or aud['id']}", "",
            f"Tema: {aud['tema'] or 'não informado'}",
            f"Fase: {aud['fase'] or 'não informada'}",
            f"Prazo exibido na página oficial: {aud['prazo_texto'] or 'não informado'}",
            f"Prazo declarado no edital: {aud['prazo_edital_texto'] or 'não localizado no texto do edital'}",
            f"Página oficial: {aud['url']}",
            "Manifestações recebidas: não coletadas (consulte a página oficial).",
            "", "Arquivos desta pasta:", *linhas, "", _RODAPE,
        ]
        self._escrever(pasta / "LEIAME.txt", "\n".join(texto))

    # ------------------------------------------------------------------ geração
    def _escrever(self, caminho: Path, texto: str) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(texto + "\n", encoding="utf-8-sig")  # BOM: o Bloco de Notas abre com acentos certos

    def gerar(self) -> Resultado:
        temporaria = self.dados / "biblioteca.nova"
        if temporaria.exists():
            shutil.rmtree(temporaria, onexc=_apagar_somente_leitura)
        temporaria.mkdir(parents=True)
        (temporaria / MARCA).write_text(agora() + "\n", encoding="utf-8")
        for (doc_id,) in self.db.execute("SELECT id FROM documento ORDER BY especie, id").fetchall():
            self._norma(temporaria, doc_id)
        if self._tem_audiencias():
            for aud in self.db.execute("SELECT * FROM audiencia WHERE status = 'lida' ORDER BY id").fetchall():
                ano = aud["id"].split("-")[1] if aud["id"].count("-") >= 2 else ""
                normas = [r[0] for r in self.db.execute(
                    "SELECT DISTINCT d.titulo FROM documento_audiencia da JOIN documento d ON d.id = da.documento_id "
                    "WHERE da.audiencia_id = ? ORDER BY d.id", (aud["id"],))]
                nome = f"{ano} - {aud['codigo'] or aud['id']}" + (f" ({', '.join(normas)})" if normas else "")
                self._arquivos_da_audiencia(aud["id"], temporaria / PASTA_AUDIENCIAS / nome_seguro(nome, 80))
                self.resultado.audiencias += 1
        self._escrever(temporaria / "LEIAME.txt", "\n".join([
            "Biblioteca do Repositório Normativo CVM", "",
            f"Gerada em {agora()} (UTC) a partir de dados\\originais e do banco do acervo.",
            f"{self.resultado.normas} normas e {self.resultado.audiencias} audiências públicas.", "",
            "Cada pasta de norma tem um LEIAME.txt com os metadados, a situação normativa conhecida, as partes, as",
            "audiências e a origem (endereço oficial, data da coleta e SHA-256) de cada arquivo.", "", _RODAPE]))
        # Troca a biblioteca antiga pela nova. Só apaga uma pasta que tenha a marca desta geração automática.
        if self.destino.exists():
            if not (self.destino / MARCA).exists():
                raise RuntimeError(f"{self.destino} existe e não foi gerada por este comando; nada foi apagado. "
                                   f"A nova biblioteca está em {temporaria}.")
            shutil.rmtree(self.destino, onexc=_apagar_somente_leitura)
        temporaria.rename(self.destino)
        marcar_originais_somente_leitura(self.dados)
        return self.resultado


_CODIGO_AUDIENCIA = re.compile(r"^.*?\bSDM\s*(?:n[º°o.]*\s*)?\d+\s*/\s*\d+\s*[:–—-]?\s*", re.I)


def _nome_arquivo_audiencia(secao: str, rotulo: str, ja_ha_outro: bool) -> str:
    """O primeiro arquivo da seção é o próprio edital ou relatório ("Edital", "Relatório"); os seguintes levam só a
    parte que os distingue ("Edital - Aviso de Prorrogação"). O rótulo completo fica no LEIAME."""
    if not ja_ha_outro:
        return nome_seguro(secao.capitalize())
    resto = re.sub(r"\s*\([^)]*\)?", "", rotulo)          # observações entre parênteses
    resto = _CODIGO_AUDIENCIA.sub("", resto).strip(" :–—-") or resto
    return nome_seguro(f"{secao.capitalize()} - {resto}", 60)


_RODAPE = ("Esta pasta é gerada automaticamente (repositorio-cvm organizar) e pode ser apagada sem perda: os originais ficam em "
           "dados\\originais e os dados no banco. Os arquivos oficiais são vínculos para os originais, somente "
           "leitura; para trabalhar num documento, copie-o para outra pasta.")


def gerar(pasta_dados: Path, conexao: sqlite3.Connection) -> Resultado:
    return Gerador(pasta_dados, conexao).gerar()
