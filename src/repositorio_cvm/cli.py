"""Linha de comando: `python -m repositorio_cvm <comando>`."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from repositorio_cvm import config as configuracao
from repositorio_cvm import gabarito
from repositorio_cvm.armazenamento import banco, originais
from repositorio_cvm.coleta.coletor import ColetaInterrompida, Coletor, UrlProibida
from repositorio_cvm.coleta.http import PoliteClient
from repositorio_cvm.config import RAIZ_PROJETO


def _preparar(cfg: configuracao.Config, nome_log: str) -> logging.Logger:
    cfg.logs.mkdir(parents=True, exist_ok=True)
    arquivo = cfg.logs / f"{nome_log}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(arquivo, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("repositorio_cvm")


def _atualizar_biblioteca(cfg: configuracao.Config, conexao, log: logging.Logger) -> None:
    """Regera dados/biblioteca depois de mudanças no acervo; falha aqui não invalida a coleta."""
    from repositorio_cvm import biblioteca
    try:
        r = biblioteca.gerar(cfg.pasta_dados, conexao)
    except Exception as erro:  # noqa: BLE001
        log.warning("biblioteca não atualizada: %s (rode: repositorio-cvm organizar)", erro)
        return
    log.info("biblioteca atualizada: %s (%d normas, %d audiências)", r.pasta, r.normas, r.audiencias)
    for aviso in r.avisos:
        log.warning("biblioteca: %s", aviso)


def _consolidar(cfg: configuracao.Config, conexao, log: logging.Logger, documentos: list[str] | None = None) -> None:
    """Gera a versão consolidada (texto vigente) das normas com consolidado oficial (D-21)."""
    from repositorio_cvm import consolidacao
    for r in consolidacao.consolidar(conexao, cfg.pasta_dados, documentos):
        if r.aplicadas is not None:
            log.info("%s: consolidação gerada pelo sistema: %s (%d alteração(ões) aplicada(s))%s", r.documento_id,
                     r.status, r.aplicadas, f"; {r.detalhe}" if r.detalhe else "")
        elif r.status in ("gerada", "reprovada"):
            log.info("%s: consolidada %s (%d bloco(s) de redação anterior e %d trecho(s) tachado(s) retirados)%s",
                     r.documento_id, r.status, r.removidos, r.trechos, f"; {r.detalhe}" if r.detalhe else "")
        elif r.status != "já existia":
            log.info("%s: %s%s", r.documento_id, r.status, f" ({r.detalhe})" if r.detalhe else "")


def cmd_coletar_alteradoras(args: argparse.Namespace) -> int:
    """Coleta as normas alteradoras das normas do acervo (ficha, redação original e conversão), retomável."""
    from repositorio_cvm import alteracoes
    cfg = configuracao.carregar()
    log = _preparar(cfg, "coleta-alteradoras")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("normas alteradoras (consolidação)")
    try:
        resumo = _coletar_alteradoras(coletor, conexao, log)
    except ColetaInterrompida as erro:
        log.error("coleta interrompida: %s (rode de novo para retomar)", erro)
        coletor.encerrar("interrompida", {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", resumo)
    log.info("coleta concluída: %s; requisições: %s", resumo, json.dumps(cliente.stats))
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def _coletar_alteradoras(coletor: Coletor, conexao, log: logging.Logger) -> dict[str, int]:
    """Coleta as alteradoras das normas do gabarito ainda ausentes do acervo (ficha, redação original, conversão)."""
    from repositorio_cvm import alteracoes
    pendentes = alteracoes.a_coletar(conexao)
    log.info("alteradoras conhecidas: %d; a coletar: %d", len(alteracoes.alteradoras(conexao)), len(pendentes))
    resumo: dict[str, int] = {}
    for i, ato in enumerate(pendentes, 1):
        r = coletor.coletar_ato(ato)
        # Só a redação original da alteradora interessa à consolidação (o comando de alteração).
        arquivos = coletor.baixar_arquivos(ato.chave, papeis=("integra", "original"))
        conversoes = coletor.converter_arquivos(ato.chave)
        resumo[r.status] = resumo.get(r.status, 0) + 1
        log.info("[%d/%d] %s: %s; arquivos: %s; conversão: %s", i, len(pendentes), ato.chave, r.status,
                 ", ".join(a.status for a in arquivos) or "nenhum", ", ".join(c.status for c in conversoes) or "nenhuma")
    return resumo


def cmd_coletar_catalogo(args: argparse.Namespace) -> int:
    """Fase 4: coleta os atos do catálogo oficial ainda ausentes do acervo (retomável, em segundo plano)."""
    from collections import Counter

    from repositorio_cvm.coleta import historica
    cfg = configuracao.carregar()
    log = _preparar(cfg, "coleta-catalogo")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    atos = historica.a_coletar(conexao, args.familia or None, args.amostra, args.limite, args.sem_revogados)
    escopo = f"catálogo: {', '.join(args.familia or ['todas as famílias'])}" + (
        f" (piloto: {args.amostra} por família)" if args.amostra else "") + (
        " (sem os marcados como revogados no catálogo)" if args.sem_revogados else "")
    log.info("%s; a coletar: %d (%s)", escopo, len(atos), dict(Counter(a.especie for a in atos)))
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar(escopo)
    resumo: Counter = Counter()
    try:
        for i, ato in enumerate(atos, 1):
            inicio = datetime.now()
            try:
                r = coletor.coletar_ato(ato)
                arquivos = coletor.baixar_arquivos(ato.chave) if r.status in ("coletado", "pendente") else []
                conversoes = coletor.converter_arquivos(ato.chave) if r.status in ("coletado", "pendente") else []
            except UrlProibida as erro:  # o robots.txt proíbe só esta URL: o ato não é coletado e fica no log
                conexao.rollback()
                resumo["proibido pelo robots.txt"] += 1
                log.warning("[%d/%d] %s: não coletado, %s", i, len(atos), ato.chave, erro)
                continue
            except ColetaInterrompida:
                raise
            except Exception as erro:  # um ato com problema não interrompe a coleta; fica no log para análise
                conexao.rollback()
                resumo["erro inesperado"] += 1
                log.exception("[%d/%d] %s: erro inesperado (%s); seguindo para o próximo", i, len(atos), ato.chave, erro)
                continue
            resumo[f"ficha {r.status}"] += 1
            resumo.update(f"arquivo {a.status}" for a in arquivos)
            resumo.update(f"conversão {c.status}" for c in conversoes)
            log.info("[%d/%d] %s: %s%s; arquivos: %s; conversão: %s (%.0f s)", i, len(atos), ato.chave, r.status,
                     f" ({r.detalhe})" if r.detalhe else "", ", ".join(a.status for a in arquivos) or "nenhum",
                     "; ".join(f"{c.status} {c.detalhe}" for c in conversoes) or "nenhuma",
                     (datetime.now() - inicio).total_seconds())
    except ColetaInterrompida as erro:
        log.error("coleta interrompida: %s (rode de novo para retomar; os atos já verificados são pulados)", erro)
        coletor.encerrar("interrompida", dict(resumo) | {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", dict(resumo))
    log.info("coleta concluída: %s; requisições: %s", dict(resumo), json.dumps(cliente.stats))
    _consolidar(cfg, conexao, log)
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_validar_consolidacao(args: argparse.Namespace) -> int:
    """Compara a consolidação gerada pelo motor com a dos consolidados oficiais (não grava versões)."""
    from repositorio_cvm import consolidacao
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    documentos = args.documento or [r[0] for r in conexao.execute(
        "SELECT DISTINCT documento_id FROM versao_texto WHERE conversor LIKE 'consolidacao-limpa%' ORDER BY documento_id")]
    validacoes = [v for d in documentos if (v := consolidacao.validar(conexao, cfg.pasta_dados, d))]
    for v in validacoes:
        print(f"{v.documento_id}: {v.iguais}/{v.comparados} dispositivos iguais ({v.concordancia:.1%}); "
              f"{len(v.divergentes)} divergentes, {len(v.faltam)} faltam, {len(v.sobram)} sobram; "
              f"{len(v.problemas)} comando(s) não aplicado(s)")
    destino = cfg.relatorios / f"validacao-consolidacao-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(consolidacao.relatorio_validacao(validacoes, datetime.now().strftime("%d/%m/%Y %H:%M")),
                       encoding="utf-8")
    print(f"relatório: {destino}")
    return 0


def cmd_consolidar(args: argparse.Namespace) -> int:
    cfg = configuracao.carregar()
    log = _preparar(cfg, "consolidar")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    _consolidar(cfg, conexao, log, args.documento or None)
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_organizar(args: argparse.Namespace) -> int:
    from repositorio_cvm import biblioteca
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    try:
        r = biblioteca.gerar(cfg.pasta_dados, conexao)
    except RuntimeError as erro:
        print(f"biblioteca não gerada: {erro}")
        return 1
    print(f"{r.pasta}: {r.normas} normas, {r.audiencias} audiências públicas; "
          f"{r.vinculos} vínculos para os originais, {r.copias} cópias")
    for aviso in r.avisos:
        print(f"aviso: {aviso}")
    return 0


def cmd_coletar(args: argparse.Namespace) -> int:
    cfg = configuracao.carregar()
    log = _preparar(cfg, "coleta-gabarito")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    atos = gabarito.carregar(Path(args.arquivo) if args.arquivo else gabarito.ARQUIVO_PADRAO)
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("gabarito")
    feitos = {r["id"] for r in conexao.execute(
        "SELECT id FROM documento WHERE ultima_verificacao IS NOT NULL")} if not args.refazer else set()
    resumo: dict[str, int] = {}
    try:
        pendentes = [a for a in atos if a.chave not in feitos]
        log.info("atos no gabarito: %d; a coletar: %d (retomada: %d já verificados)", len(atos), len(pendentes),
                 len(atos) - len(pendentes))
        localizados = coletor.localizar_oficios(pendentes)
        for i, ato in enumerate(pendentes, 1):
            resultado = coletor.coletar_ato(ato, localizados.get(ato.chave))
            resumo[resultado.status] = resumo.get(resultado.status, 0) + 1
            log.info("[%d/%d] %s: %s %s", i, len(pendentes), ato.chave, resultado.status, resultado.detalhe)
    except ColetaInterrompida as erro:
        log.error("coleta interrompida: %s", erro)
        coletor.encerrar("interrompida", resumo | {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", resumo)
    log.info("coleta concluída: %s; requisições: %s", resumo, json.dumps(cliente.stats))
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_baixar_arquivos(args: argparse.Namespace) -> int:
    cfg = configuracao.carregar()
    log = _preparar(cfg, "baixar-arquivos")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("arquivos pdf/docx do gabarito")
    atos = gabarito.carregar()
    contagem: dict[str, int] = {}
    try:
        for i, ato in enumerate(atos, 1):
            for r in coletor.baixar_arquivos(ato.chave):
                contagem[r.status] = contagem.get(r.status, 0) + 1
                log.info("[%d/%d] %s: %s %s", i, len(atos), ato.chave, r.status, r.detalhe)
    except ColetaInterrompida as erro:
        log.error("coleta interrompida: %s", erro)
        coletor.encerrar("interrompida", contagem | {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", contagem)
    log.info("concluído: %s; requisições: %s", contagem, json.dumps(cliente.stats))
    return 0


def cmd_converter(args: argparse.Namespace) -> int:
    cfg = configuracao.carregar()
    log = _preparar(cfg, "converter")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    coletor = Coletor(cfg, conexao, cliente=None)  # conversão não acessa a rede
    contagem: dict[str, int] = {}
    # Os atos do gabarito e os demais documentos do acervo (ex.: normas alteradoras coletadas para a consolidação).
    chaves = [a.chave for a in gabarito.carregar()]
    chaves += [r[0] for r in conexao.execute("SELECT id FROM documento ORDER BY id") if r[0] not in chaves]
    for chave in chaves:
        for r in coletor.converter_arquivos(chave):
            contagem[r.status] = contagem.get(r.status, 0) + 1
            log.info("%s: %s %s", chave, r.status, r.detalhe)
    log.info("conversão concluída: %s", contagem)
    _consolidar(cfg, conexao, log)
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_relatorio(args: argparse.Namespace) -> int:
    from repositorio_cvm.relatorios import gerar_conferencia
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    atos = gabarito.carregar()
    md = Path(args.saida) if args.saida else RAIZ_PROJETO / "docs" / "CONFERENCIA_GABARITO.md"
    csv_ = cfg.relatorios / f"conferencia-gabarito-{datetime.now().strftime('%Y%m%d')}.csv"
    gerar_conferencia(conexao, atos, md, csv_)
    print(f"relatório: {md}\nplanilha: {csv_}")
    return 0


def cmd_pesquisar(args: argparse.Namespace) -> int:
    from repositorio_cvm.pesquisa import pesquisar
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    achados = pesquisar(conexao, " ".join(args.consulta), especie=args.especie, situacao=args.situacao,
                        desde=args.desde, ate=args.ate, limite=args.limite, versao=args.versao)
    if not achados:
        print("nenhum resultado")
        return 1
    for a in achados:
        print(f"{a.titulo} — {a.rotulo} [{a.situacao}] ({a.versao or 'sem texto integral'})\n"
              f"  {a.texto}\n  fonte: {a.url_oficial}\n")
    return 0


def cmd_verificar(args: argparse.Namespace) -> int:
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    falhas = 0
    total = 0
    for linha in conexao.execute("SELECT caminho, sha256 FROM arquivo"):
        total += 1
        if not originais.verificar(cfg.pasta_dados, linha["caminho"], linha["sha256"]):
            falhas += 1
            print(f"FALHA de integridade: {linha['caminho']}")
    print(f"{total} arquivos verificados; {falhas} falha(s)")
    return 1 if falhas else 0


def cmd_backup(args: argparse.Namespace) -> int:
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    print(banco.fazer_backup(conexao, cfg.backups))
    return 0


def cmd_restaurar(args: argparse.Namespace) -> int:
    """Restaura o banco a partir de uma cópia de dados/backups. O banco atual é copiado antes (nada se perde)."""
    import sqlite3

    cfg = configuracao.carregar()
    copias = sorted(cfg.backups.glob("acervo-*.sqlite"))
    if not args.arquivo:
        print("Cópias disponíveis em", cfg.backups)
        for c in copias:
            print(f"  {c.name}  ({c.stat().st_size // 1024} KB)")
        print("Uso: restaurar <nome-da-copia> --confirmar")
        return 0
    origem = Path(args.arquivo)
    if not origem.is_absolute():
        origem = cfg.backups / origem
    if not origem.is_file():
        print(f"cópia não encontrada: {origem}")
        return 1
    if not args.confirmar:
        print(f"O banco atual ({cfg.banco}) será substituído por {origem.name}.\n"
              "Antes, uma cópia do banco atual será guardada em dados/backups. Repita com --confirmar para executar.")
        return 1
    atual = banco.abrir(cfg.banco, cfg.backups)
    guardado = banco.fazer_backup(atual, cfg.backups, "antes-restauracao")
    with sqlite3.connect(origem) as fonte:
        fonte.backup(atual)
    atual.close()
    banco.abrir(cfg.banco, cfg.backups).close()  # aplica migrações, se a cópia for de versão anterior
    print(f"banco restaurado de {origem.name}; o banco anterior foi guardado em {guardado}")
    return 0


def cmd_ler_catalogo(args: argparse.Namespace) -> int:
    from repositorio_cvm.coleta.inventario import familias_a_ler, ler_catalogo
    cfg = configuracao.carregar()
    log = _preparar(cfg, "leitura-catalogo")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    familias = familias_a_ler(conexao, args.familia, args.refazer)
    if not familias:
        log.info("todas as famílias têm leitura completa recente (use --refazer para ler de novo)")
        return 0
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("leitura do catálogo oficial: " + ", ".join(familias))

    def avanco(familia, pagina, paginas, lidos, informado):
        if pagina == 1 or pagina % 10 == 0 or pagina == paginas:
            log.info("%s: página %d de %s (%d de %s atos)", familia, pagina, paginas, lidos, informado)

    resumo = {}
    try:
        for familia in familias:
            r = ler_catalogo(coletor, familia, avanco)
            resumo[familia] = f"{r['status']}: {r['total_lido']} de {r['total_informado']}"
            log.info("%s: leitura %s (%d atos lidos de %s informados)", familia, r["status"], r["total_lido"],
                     r["total_informado"])
    except ColetaInterrompida as erro:
        log.error("leitura interrompida: %s (rode de novo depois; famílias completas não são relidas)", erro)
        coletor.encerrar("interrompida", resumo | {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", resumo)
    log.info("leitura concluída: %s; requisições: %s", resumo, json.dumps(cliente.stats))
    return 0


def cmd_coletar_audiencias(args: argparse.Namespace) -> int:
    from repositorio_cvm.coleta.audiencias import ColetorAudiencias
    cfg = configuracao.carregar()
    log = _preparar(cfg, "audiencias")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("audiências públicas das normas do acervo")

    def avanco(audiencia_id, status):
        log.info("%s: %s", audiencia_id, status)

    try:
        contagem = ColetorAudiencias(coletor).executar(args.documento or None, refazer=args.refazer, ao_avancar=avanco)
    except ColetaInterrompida as erro:
        log.error("coleta interrompida: %s (rode de novo depois; o que já foi baixado não é baixado de novo)", erro)
        coletor.encerrar("interrompida", {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", contagem)
    log.info("audiências: %s; requisições: %s", contagem, json.dumps(cliente.stats))
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_coletar_justificativas(args: argparse.Namespace) -> int:
    from repositorio_cvm.coleta.justificativas import ColetorJustificativas
    cfg = configuracao.carregar()
    log = _preparar(cfg, "justificativas")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("justificativas de dispensa de AIR das normas do acervo")

    def avanco(documento_id, status):
        log.info("%s: %s", documento_id, status)

    try:
        contagem = ColetorJustificativas(coletor).executar(args.documento or None, refazer=args.refazer,
                                                           ao_avancar=avanco)
    except ColetaInterrompida as erro:
        log.error("coleta interrompida: %s (rode de novo depois; o que já foi baixado não é baixado de novo)", erro)
        coletor.encerrar("interrompida", {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", contagem)
    log.info("justificativas: %s; requisições: %s", contagem, json.dumps(cliente.stats))
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_atualizar(args: argparse.Namespace) -> int:
    from repositorio_cvm.coleta.atualizacao import Atualizador, relatorio_markdown
    cfg = configuracao.carregar()
    log = _preparar(cfg, "atualizacao")
    conexao = banco.abrir(cfg.banco, cfg.backups)
    cliente = PoliteClient(min_interval=cfg.intervalo_minimo, max_retries=cfg.retentativas,
                           user_agent=cfg.user_agent,
                           log_path=cfg.logs / f"http-{datetime.now().strftime('%Y%m%d')}.jsonl")
    coletor = Coletor(cfg, conexao, cliente)
    coletor.iniciar("atualização incremental" + (" (com arquivos)" if args.arquivos else ""))
    inicio = banco.agora()
    atualizador = Atualizador(coletor, arquivos=args.arquivos)

    def avanco(i, total, documento_id, mudancas):
        log.info("[%d/%d] %s: %s", i, total, documento_id,
                 "; ".join(f"{m.tipo}{': ' + m.detalhe[:200] if m.detalhe else ''}" for m in mudancas))

    try:
        resultado = atualizador.executar(args.documento or None, novidades=not args.sem_novidades,
                                         ao_avancar=avanco)
        # Alteradora nova listada numa ficha: coletada para que a consolidação a aplique (D-21).
        _coletar_alteradoras(coletor, conexao, log)
    except ColetaInterrompida as erro:
        log.error("atualização interrompida: %s (rode de novo depois; as normas já verificadas ficam por último)", erro)
        coletor.encerrar("interrompida", {"erro": str(erro)})
        return 2
    coletor.encerrar("concluída", resultado.resumo())
    destino = cfg.relatorios / f"atualizacao-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(relatorio_markdown(resultado, inicio, banco.agora()), encoding="utf-8")
    log.info("atualização concluída: %s; relatório: %s; requisições: %s", resultado.resumo(), destino,
             json.dumps(cliente.stats))
    _consolidar(cfg, conexao, log)
    _atualizar_biblioteca(cfg, conexao, log)
    return 0


def cmd_interface(args: argparse.Namespace) -> int:
    import threading
    import webbrowser

    import uvicorn

    from repositorio_cvm.web.app import criar_app
    cfg = configuracao.carregar()
    endereco = f"http://127.0.0.1:{args.porta}/"
    print(f"Interface em {endereco} (feche esta janela ou tecle Ctrl+C para encerrar)")
    if not args.sem_navegador:
        threading.Timer(1.5, lambda: webbrowser.open(endereco)).start()
    uvicorn.run(criar_app(cfg), host="127.0.0.1", port=args.porta, log_level="warning")
    return 0


def cmd_relatorio_cobertura(args: argparse.Namespace) -> int:
    from repositorio_cvm.relatorios import gerar_cobertura
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
    md = cfg.relatorios / f"cobertura-{carimbo}.md"
    dados = gerar_cobertura(conexao, md, cfg.relatorios / f"cobertura-{carimbo}.csv")
    print(f"relatório: {md}\n" + ", ".join(f"{k}: {v}" for k, v in dados["totais"].items()))
    return 0


def cmd_publicar_acervo(args: argparse.Namespace) -> int:
    from repositorio_cvm import publicacao
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    try:
        r = publicacao.gerar(cfg.pasta_dados, conexao, Path(args.destino))
    except RuntimeError as erro:
        print(f"acervo não gerado: {erro}")
        return 1
    print(f"{r.pasta}: {r.normas} normas ({r.sem_texto} sem texto integral), {r.audiencias} audiências públicas, "
          f"{r.arquivos} arquivos Markdown")
    for aviso in r.avisos:
        print(f"aviso: {aviso}")
    return 0


def cmd_exportar(args: argparse.Namespace) -> int:
    from repositorio_cvm import acervo, exportacao
    cfg = configuracao.carregar()
    conexao = banco.abrir(cfg.banco, cfg.backups)
    doc = acervo.carregar(conexao, args.documento)
    if doc is None:
        print(f"documento não encontrado no acervo: {args.documento}")
        return 1
    try:
        saida = exportacao.exportar(doc, cfg.pasta_dados, args.formato, args.versao, conexao=conexao, parte=args.parte)
    except exportacao.ExportacaoError as erro:
        print(f"exportação não realizada: {erro}")
        return 1
    destino = Path(args.saida or ".") / saida.nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(saida.conteudo)
    print(destino)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="repositorio_cvm", description="Repositório Normativo CVM")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("coletar", help="coleta os atos do gabarito (retomável)")
    p.add_argument("--gabarito", action="store_true", help="coletar os atos do gabarito (único escopo nesta versão)")
    p.add_argument("--arquivo", help="arquivo de gabarito alternativo")
    p.add_argument("--refazer", action="store_true", help="reverificar também os atos já coletados")
    p.set_defaults(func=cmd_coletar)

    p = sub.add_parser("baixar-arquivos", help="baixa os PDF/DOCX de texto dos atos do gabarito (retomável)")
    p.set_defaults(func=cmd_baixar_arquivos)

    p = sub.add_parser("converter", help="converte os PDF/DOCX baixados do gabarito em Markdown (sem rede)")
    p.set_defaults(func=cmd_converter)

    p = sub.add_parser("relatorio-gabarito", help="gera a tabela de conferência do gabarito")
    p.add_argument("--saida")
    p.set_defaults(func=cmd_relatorio)

    p = sub.add_parser("pesquisar", help='pesquisa ("Resolução CVM 50, artigo 1" ou palavras)')
    p.add_argument("consulta", nargs="+")
    p.add_argument("--especie")
    p.add_argument("--situacao")
    p.add_argument("--desde")
    p.add_argument("--ate")
    p.add_argument("--limite", type=int, default=20)
    p.add_argument("--versao", choices=["consolidado", "alterada", "oficial", "original"], default="consolidado",
                   help="consolidado: só o texto vigente (padrão); alterada/oficial: com a redação tachada; original")
    p.set_defaults(func=cmd_pesquisar)

    p = sub.add_parser("verificar", help="confere o hash de todos os originais armazenados")
    p.set_defaults(func=cmd_verificar)

    p = sub.add_parser("backup", help="copia o banco para dados/backups")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("atualizar", help="verifica novidades e alterações nas fontes oficiais (incremental, retomável)")
    p.add_argument("--arquivos", action="store_true",
                   help="baixar de novo os arquivos de texto mesmo quando a ficha não mudou")
    p.add_argument("--sem-novidades", action="store_true", help="não ler o catálogo em busca de publicações novas")
    p.add_argument("--documento", action="append", help="verificar só esta norma (pode repetir)")
    p.set_defaults(func=cmd_atualizar)

    p = sub.add_parser("coletar-alteradoras",
                       help="coleta as normas alteradoras das normas do acervo, para a consolidação (retomável)")
    p.set_defaults(func=cmd_coletar_alteradoras)

    p = sub.add_parser("coletar-catalogo",
                       help="coleta histórica: atos do catálogo oficial ainda ausentes do acervo (retomável)")
    p.add_argument("--familia", action="append", choices=["resolucao", "instrucao", "deliberacao",
                   "parecer_orientacao", "oficio_circular", "nota_explicativa"], help="só esta família (pode repetir)")
    p.add_argument("--amostra", type=int, help="piloto: N atos por família, espalhados pelo período do catálogo")
    p.add_argument("--limite", type=int, help="no máximo N atos por família nesta execução")
    p.add_argument("--sem-revogados", action="store_true",
                   help="não coletar os atos marcados como revogados no catálogo (a situação é confirmada pela ficha)")
    p.set_defaults(func=cmd_coletar_catalogo)

    p = sub.add_parser("validar-consolidacao",
                       help="compara a consolidação gerada pelo sistema com a dos consolidados oficiais (relatório)")
    p.add_argument("--documento", action="append", help="só esta norma (pode repetir)")
    p.set_defaults(func=cmd_validar_consolidacao)

    p = sub.add_parser("consolidar", help="gera a versão consolidada (só o texto vigente) das normas alteradas")
    p.add_argument("--documento", action="append", help="só esta norma (pode repetir)")
    p.set_defaults(func=cmd_consolidar)

    p = sub.add_parser("organizar", help="gera dados/biblioteca: os documentos em pastas com nomes legíveis")
    p.set_defaults(func=cmd_organizar)

    p = sub.add_parser("coletar-audiencias",
                       help="audiências públicas das normas do acervo: edital, prazo, fase e relatório (sem manifestações)")
    p.add_argument("--documento", action="append", help="só esta norma (pode repetir)")
    p.add_argument("--refazer", action="store_true", help="relê páginas lidas nos últimos 30 dias")
    p.set_defaults(func=cmd_coletar_audiencias)

    p = sub.add_parser("coletar-justificativas",
                       help="justificativas de dispensa de Análise de Impacto Regulatório (AIR) citadas nas fichas")
    p.add_argument("--documento", action="append", help="só esta norma (pode repetir)")
    p.add_argument("--refazer", action="store_true", help="baixar e converter de novo")
    p.set_defaults(func=cmd_coletar_justificativas)

    p = sub.add_parser("ler-catalogo", help="lê o catálogo oficial completo da CVM (base da cobertura)")
    p.add_argument("--familia", action="append", help="só esta família (pode repetir)")
    p.add_argument("--refazer", action="store_true", help="ler também famílias com leitura completa recente")
    p.set_defaults(func=cmd_ler_catalogo)

    p = sub.add_parser("restaurar",help="restaura o banco a partir de uma cópia em dados/backups")
    p.add_argument("arquivo", nargs="?", help="nome da cópia (sem argumento: lista as cópias)")
    p.add_argument("--confirmar", action="store_true", help="executa a restauração")
    p.set_defaults(func=cmd_restaurar)

    p = sub.add_parser("interface",help="abre a interface de pesquisa no navegador (http://127.0.0.1:8000)")
    p.add_argument("--porta", type=int, default=8000)
    p.add_argument("--sem-navegador", action="store_true", help="não abrir o navegador automaticamente")
    p.set_defaults(func=cmd_interface)

    p = sub.add_parser("relatorio-cobertura", help="gera o relatório de cobertura (Markdown e CSV em dados/relatorios)")
    p.set_defaults(func=cmd_relatorio_cobertura)

    p = sub.add_parser("publicar-acervo",
                       help="gera <destino>/acervo: as normas em Markdown com cabeçalho YAML, para publicar (ex.: GitHub)")
    p.add_argument("destino", help="pasta do repositório público (a subpasta acervo/ é substituída)")
    p.set_defaults(func=cmd_publicar_acervo)

    p = sub.add_parser("exportar", help="exporta uma norma (ex.: exportar resolucao-cvm-175 docx)")
    p.add_argument("documento", help="identificador da norma no acervo (ex.: resolucao-cvm-175)")
    p.add_argument("formato", choices=["docx", "pdf", "md", "txt"])
    p.add_argument("--versao", choices=["consolidado", "alterada", "oficial", "original"], default="consolidado",
                   help="consolidado: só o texto vigente; alterada/oficial: com a redação anterior tachada")
    p.add_argument("--saida", help="pasta de destino (padrão: pasta atual)")
    p.add_argument("--parte", help="só uma parte da norma (ex.: principal, anexo-normativo-i, suplementos)")
    p.set_defaults(func=cmd_exportar)

    args = parser.parse_args(argv)
    return args.func(args)
