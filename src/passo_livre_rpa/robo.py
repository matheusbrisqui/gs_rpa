"""Orquestração do processo "do relato ao chamado".

Etapas de uma execução:
  1. confere se a API do MVP está no ar;
  2. lê os arquivos de retorno da prefeitura e marca como resolvidos os relatos concluídos;
  3. busca os relatos novos, os relatos em aberto e os pontos de ônibus;
  4. para cada relato novo: valida, procura duplicado, define a prioridade, busca o
     endereço, gera o protocolo, atualiza o MVP e grava o chamado no lote de saída;
  5. grava logs, trilha de auditoria e resumo.

Nenhuma falha é silenciosa: toda exceção vira linha de log, evento de auditoria e
contador no resumo, e o código de saída do processo reflete o resultado.
"""

from __future__ import annotations

import csv
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import regras, retorno_prefeitura
from .cliente_api import ApiErro, ApiIndisponivel, CredencialRecusada, MvpClient
from .config import Config
from .geocodificador import Geocodificador
from .registro import Auditoria, criar_logger, fechar_logger, gravar_resumo

CODIGOS_SAIDA = {"sucesso": 0, "sucesso_com_falhas": 1, "abortado": 2, "ja_em_execucao": 3}
TRAVA_VENCE_EM_S = 2 * 60 * 60
FALHAS_SEGUIDAS_PARA_ABORTAR = 2
COLUNAS_CHAMADO = [
    "protocolo", "relato_id", "tipo", "prioridade", "regra_prioridade", "latitude", "longitude",
    "endereco", "ponto_onibus_codigo", "ponto_onibus_nome", "distancia_ponto_m", "relatado_em", "encaminhado_em",
]


@dataclass
class Resumo:
    execucao: str
    inicio: str
    fim: str | None = None
    situacao: str = "sucesso"
    relatos_lidos: int = 0
    encaminhados: int = 0
    duplicados: int = 0
    invalidos: int = 0
    falhas: int = 0
    prioridades: dict[str, int] = field(default_factory=lambda: {"alta": 0, "media": 0, "normal": 0})
    sem_endereco: int = 0
    retorno_arquivos_lidos: int = 0
    retorno_arquivos_rejeitados: int = 0
    retorno_linhas_invalidas: int = 0
    retorno_resolvidos: int = 0
    retorno_sem_relato: int = 0
    retorno_indeferidos: int = 0
    arquivo_chamados: str | None = None
    erros: list[str] = field(default_factory=list)

    @property
    def codigo_saida(self) -> int:
        return CODIGOS_SAIDA[self.situacao]


class _LoteChamados:
    """Arquivo estruturado com os chamados do lote (o que seria enviado ao canal da prefeitura)."""

    def __init__(self, saida_dir: Path, run_id: str):
        self.caminho = saida_dir / f"chamados_{run_id}.csv"
        self.linhas = 0

    def adicionar(self, linha: dict) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        novo = not self.caminho.exists()
        with self.caminho.open("a", encoding="utf-8-sig" if novo else "utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=COLUNAS_CHAMADO, delimiter=";")
            if novo:
                escritor.writeheader()
            escritor.writerow(linha)
        self.linhas += 1


def _agora_utc() -> datetime:
    return datetime.now(UTC)


def _adquirir_trava(trava: Path) -> bool:
    """Impede duas execuções simultâneas. Trava com mais de 2 horas é considerada abandonada."""
    trava.parent.mkdir(parents=True, exist_ok=True)
    if trava.exists() and time.time() - trava.stat().st_mtime > TRAVA_VENCE_EM_S:
        trava.unlink(missing_ok=True)
    try:
        descritor = os.open(trava, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(descritor, str(os.getpid()).encode())
    os.close(descritor)
    return True


def _mover(arquivo: Path, destino_dir: Path, run_id: str) -> Path:
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / arquivo.name
    if destino.exists():
        destino = destino_dir / f"{arquivo.stem}_{run_id}{arquivo.suffix}"
    shutil.move(str(arquivo), str(destino))
    return destino


def executar(
    config: Config,
    *,
    cliente: MvpClient | None = None,
    geocodificador: Geocodificador | None = None,
    agora: Callable[[], datetime] = _agora_utc,
    console: bool = True,
) -> Resumo:
    inicio = agora()
    local = inicio.astimezone()
    run_id = f"{local:%Y%m%dT%H%M%S}"
    logger = criar_logger(config.logs_dir, run_id, local, console=console)
    auditoria = Auditoria(config.logs_dir, run_id, local)
    resumo = Resumo(execucao=run_id, inicio=local.isoformat(timespec="seconds"))
    trava = config.logs_dir / ".robo.lock"

    if not _adquirir_trava(trava):
        resumo.situacao = "ja_em_execucao"
        logger.warning("Outra execução está em andamento (trava %s). Encerrando sem processar.", trava.name)
        fechar_logger(logger)
        return resumo

    cliente_proprio = cliente is None
    geo_proprio = geocodificador is None
    try:
        logger.info("Início da execução | API %s", config.api_url)
        if cliente is None:
            cliente = MvpClient(
                config.api_url,
                config.automation_token,
                timeout_s=config.http_timeout_s,
                tentativas=config.http_tentativas,
                espera_s=config.http_espera_s,
                logger=logger,
            )
        if geocodificador is None:
            geocodificador = Geocodificador(
                config.geocoder_url, intervalo_s=config.geocoder_intervalo_s, logger=logger
            )
        _rodar(config, cliente, geocodificador, logger, auditoria, resumo, inicio, run_id)
    except ApiIndisponivel as exc:
        resumo.situacao = "abortado"
        resumo.erros.append(str(exc))
        logger.error("Execução abortada: API do MVP indisponível (%s)", exc)
        auditoria.registrar("execucao", "abortada", motivo=str(exc))
    except CredencialRecusada as exc:
        resumo.situacao = "abortado"
        resumo.falhas += 1
        resumo.erros.append(str(exc))
        logger.error("Execução abortada: %s. Nenhum relato foi alterado por esta falha.", exc)
        auditoria.registrar("execucao", "abortada", motivo=str(exc))
    except Exception as exc:
        resumo.situacao = "abortado"
        resumo.erros.append(f"erro inesperado: {type(exc).__name__}: {exc}")
        logger.exception("Execução abortada por erro inesperado")
        auditoria.registrar("execucao", "abortada", motivo=f"{type(exc).__name__}: {exc}")
    finally:
        if resumo.situacao == "sucesso" and (resumo.falhas or resumo.retorno_arquivos_rejeitados or resumo.erros):
            resumo.situacao = "sucesso_com_falhas"
        resumo.fim = agora().astimezone().isoformat(timespec="seconds")
        caminho_resumo = gravar_resumo(config.logs_dir, run_id, asdict(resumo))
        logger.info(
            "Fim da execução | situação=%s | lidos=%d encaminhados=%d duplicados=%d inválidos=%d falhas=%d "
            "| retornos resolvidos=%d | resumo em %s",
            resumo.situacao, resumo.relatos_lidos, resumo.encaminhados, resumo.duplicados, resumo.invalidos,
            resumo.falhas, resumo.retorno_resolvidos, caminho_resumo.name,
        )
        if cliente_proprio and cliente is not None:
            cliente.fechar()
        if geo_proprio and geocodificador is not None:
            geocodificador.fechar()
        trava.unlink(missing_ok=True)
        fechar_logger(logger)
    return resumo


def _rodar(config, cliente, geocodificador, logger, auditoria, resumo, inicio, run_id) -> None:
    # 1. API no ar?
    saude = cliente.saude()
    logger.info("API do MVP disponível (%s %s)", saude.get("servico", "?"), saude.get("versao", ""))

    # 2. Retorno da prefeitura
    _processar_retornos(config, cliente, logger, auditoria, resumo, run_id)

    # 3. Dados para a triagem
    novos = sorted(cliente.listar_relatos(status="novo"), key=lambda r: (r.get("criado_em") or "", r["id"]))
    em_aberto = cliente.listar_relatos(status="validado") + cliente.listar_relatos(status="encaminhado")
    pontos = cliente.listar_pontos()
    resumo.relatos_lidos = len(novos)
    logger.info(
        "Triagem: %d relato(s) novo(s), %d em aberto para comparação, %d ponto(s) de ônibus",
        len(novos), len(em_aberto), len(pontos),
    )
    if not novos:
        logger.info("Nenhum relato novo para processar")
        return

    # 4. Um relato por vez
    lote = _LoteChamados(config.saida_dir, run_id)
    falhas_seguidas = 0
    try:
        for posicao, relato in enumerate(novos, start=1):
            try:
                aceito = _processar_relato(
                    config, cliente, geocodificador, logger, auditoria, resumo, lote, relato, em_aberto, pontos, inicio
                )
                falhas_seguidas = 0
                if aceito:
                    em_aberto.append(aceito)  # passa a valer para a busca de duplicados dentro do mesmo lote
            except CredencialRecusada:
                raise  # não adianta tentar os próximos: aborta a execução
            except ApiErro as exc:
                falhas_seguidas = 0
                resumo.falhas += 1
                logger.error("Relato #%d: a API recusou a atualização (%s). Relato mantido como novo.", relato["id"], exc)
                auditoria.registrar("triagem", "falha", relato_id=relato["id"], motivo=str(exc))
            except ApiIndisponivel as exc:
                falhas_seguidas += 1
                resumo.falhas += 1
                logger.error("Relato #%d: API indisponível (%s). Relato mantido como novo.", relato["id"], exc)
                auditoria.registrar("triagem", "falha", relato_id=relato["id"], motivo=str(exc))
                if falhas_seguidas >= FALHAS_SEGUIDAS_PARA_ABORTAR:
                    restantes = len(novos) - posicao
                    raise ApiIndisponivel(
                        f"API caiu durante o lote; {restantes} relato(s) não processado(s) ficam para a próxima execução"
                    ) from exc
    finally:
        # Mesmo se o lote for interrompido, o que já foi encaminhado fica registrado no resumo
        if lote.linhas:
            resumo.arquivo_chamados = lote.caminho.name
            logger.info("Lote de chamados gravado: %s (%d linha(s))", lote.caminho.name, lote.linhas)


def _processar_relato(
    config, cliente, geocodificador, logger, auditoria, resumo, lote, relato, em_aberto, pontos, inicio
) -> dict | None:
    """Trata um relato novo. Devolve o relato quando ele foi encaminhado (para a busca de duplicados)."""
    rid, tipo = relato["id"], relato.get("tipo")

    # Decisão 1: dados válidos?
    motivos = regras.validar(relato, config.area, inicio)
    if motivos:
        cliente.atualizar_relato(rid, status="invalido")
        resumo.invalidos += 1
        logger.warning("Relato #%d (%s): inválido (%s)", rid, tipo, ", ".join(motivos))
        auditoria.registrar("triagem", "invalido", relato_id=rid, tipo=tipo, motivos=motivos)
        return None

    # Decisão 2: já existe relato em aberto do mesmo tipo no mesmo lugar?
    duplicado = regras.encontrar_duplicado(
        relato, em_aberto, config.raio_duplicado_m, config.janela_duplicado_dias, inicio
    )
    if duplicado:
        original, distancia = duplicado
        cliente.atualizar_relato(rid, status="duplicado", duplicado_de=original)
        resumo.duplicados += 1
        logger.info("Relato #%d (%s): duplicado do relato #%d (a %.0f m)", rid, tipo, original, distancia)
        auditoria.registrar(
            "triagem", "duplicado", relato_id=rid, tipo=tipo, duplicado_de=original, distancia_m=round(distancia, 1)
        )
        return None

    # Decisão 3: prioridade
    proximo = regras.ponto_mais_proximo(relato, pontos)
    ponto, dist_ponto = proximo if proximo else (None, None)
    prioridade, regra = regras.definir_prioridade(relato.get("perfil"), dist_ponto, config.raio_ponto_m)

    # Enriquecimento opcional: endereço
    endereco = geocodificador.endereco(relato["lat"], relato["lon"])
    if endereco is None:
        resumo.sem_endereco += 1

    protocolo = regras.gerar_protocolo(rid, inicio.astimezone())
    cliente.atualizar_relato(rid, status="encaminhado", prioridade=prioridade, protocolo=protocolo)
    junto_ao_ponto = ponto is not None and dist_ponto <= config.raio_ponto_m
    try:
        lote.adicionar(
            {
                "protocolo": protocolo,
                "relato_id": rid,
                "tipo": tipo,
                "prioridade": prioridade,
                "regra_prioridade": regra,
                "latitude": f"{relato['lat']:.6f}",
                "longitude": f"{relato['lon']:.6f}",
                "endereco": endereco or "",
                "ponto_onibus_codigo": ponto["codigo"] if junto_ao_ponto else "",
                "ponto_onibus_nome": ponto["nome"] if junto_ao_ponto else "",
                "distancia_ponto_m": f"{dist_ponto:.0f}" if junto_ao_ponto else "",
                "relatado_em": relato.get("criado_em") or "",
                "encaminhado_em": inicio.astimezone().isoformat(timespec="seconds"),
            }
        )
    except OSError as exc:
        # Não conseguiu gravar o chamado: desfaz a atualização para o relato voltar na próxima execução
        cliente.atualizar_relato(rid, status="novo", prioridade=None, protocolo=None)
        resumo.falhas += 1
        logger.error("Relato #%d: falha ao gravar o chamado (%s). Atualização desfeita.", rid, exc)
        auditoria.registrar("triagem", "falha", relato_id=rid, motivo=f"gravação do chamado: {exc}")
        return None

    resumo.encaminhados += 1
    resumo.prioridades[prioridade] += 1
    logger.info(
        "Relato #%d (%s): encaminhado | prioridade %s (%s) | protocolo %s%s",
        rid, tipo, prioridade, regra, protocolo, "" if endereco else " | sem endereço",
    )
    auditoria.registrar(
        "triagem", "encaminhado", relato_id=rid, tipo=tipo, prioridade=prioridade, regra=regra,
        protocolo=protocolo, junto_a_ponto=junto_ao_ponto, com_endereco=endereco is not None,
    )
    return {**relato, "status": "encaminhado"}


def _processar_retornos(config, cliente, logger, auditoria, resumo, run_id) -> None:
    arquivos = retorno_prefeitura.localizar(config.entrada_dir) if config.entrada_dir.is_dir() else []
    if not arquivos:
        logger.info("Nenhum arquivo de retorno da prefeitura em %s; etapa ignorada", config.entrada_dir.name)
        return
    for arquivo in arquivos:
        try:
            validas, problemas = retorno_prefeitura.ler(arquivo)
        except retorno_prefeitura.ArquivoInvalido as exc:
            resumo.retorno_arquivos_rejeitados += 1
            destino = _mover(arquivo, config.entrada_dir / "rejeitados", run_id)
            logger.error("Arquivo de retorno %s rejeitado (%s). Movido para rejeitados/%s", arquivo.name, exc, destino.name)
            auditoria.registrar("retorno_prefeitura", "arquivo_rejeitado", arquivo=arquivo.name, motivo=str(exc))
            continue

        resumo.retorno_arquivos_lidos += 1
        logger.info("Arquivo de retorno %s: %d linha(s) válida(s), %d com problema", arquivo.name, len(validas), len(problemas))
        for problema in problemas:
            resumo.retorno_linhas_invalidas += 1
            logger.warning("Arquivo %s, %s", arquivo.name, problema)
            auditoria.registrar("retorno_prefeitura", "linha_invalida", arquivo=arquivo.name, motivo=problema)

        for item in validas:
            try:
                _aplicar_retorno(cliente, logger, auditoria, resumo, item)
            except CredencialRecusada:
                raise  # arquivo continua na entrada para a próxima execução
            except ApiErro as exc:
                resumo.falhas += 1
                logger.error("Protocolo %s: a API recusou a atualização (%s)", item.protocolo, exc)
                auditoria.registrar("retorno_prefeitura", "falha", protocolo=item.protocolo, motivo=str(exc))
        # Só sai da entrada depois de lido até o fim. Se a API cair no meio, o arquivo fica para a próxima execução.
        _mover(arquivo, config.entrada_dir / "processados", run_id)


def _aplicar_retorno(cliente, logger, auditoria, resumo, item) -> None:
    if item.situacao == "EM_ANDAMENTO":
        auditoria.registrar("retorno_prefeitura", "sem_alteracao", protocolo=item.protocolo)
        return
    if item.situacao == "INDEFERIDO":
        resumo.retorno_indeferidos += 1
        logger.warning("Protocolo %s indeferido pela prefeitura: requer revisão humana", item.protocolo)
        auditoria.registrar("retorno_prefeitura", "indeferido", protocolo=item.protocolo)
        return
    encontrados = cliente.listar_relatos(protocolo=item.protocolo)
    if not encontrados:
        resumo.retorno_sem_relato += 1
        logger.warning("Protocolo %s concluído, mas não há relato com esse protocolo", item.protocolo)
        auditoria.registrar("retorno_prefeitura", "sem_relato", protocolo=item.protocolo)
        return
    relato = encontrados[0]
    if relato["status"] == "resolvido":
        auditoria.registrar("retorno_prefeitura", "ja_resolvido", protocolo=item.protocolo, relato_id=relato["id"])
        return
    cliente.atualizar_relato(relato["id"], status="resolvido")
    resumo.retorno_resolvidos += 1
    logger.info(
        "Protocolo %s concluído em %s: relato #%d marcado como resolvido",
        item.protocolo, item.data_conclusao, relato["id"],
    )
    auditoria.registrar(
        "retorno_prefeitura", "resolvido", protocolo=item.protocolo, relato_id=relato["id"],
        data_conclusao=str(item.data_conclusao),
    )
