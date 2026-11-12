"""Logs e trilha de auditoria.

Três artefatos por execução, todos na pasta de logs:
- `robo_AAAAMMDD.log`        log legível, uma linha por acontecimento;
- `auditoria_AAAAMMDD.jsonl` um evento JSON por item processado (trilha de auditoria);
- `resumo_<execução>.json`   totais da execução.

LGPD: nenhum deles recebe descrição livre, perfil ou hash do cidadão. Os eventos
citam só o número do relato, o tipo do obstáculo e o código da regra aplicada.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

FORMATO = "%(asctime)s | %(levelname)-7s | %(run_id)s | %(message)s"


def criar_logger(logs_dir: Path, run_id: str, agora: datetime, *, console: bool = True) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"passo_livre_rpa.{run_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formato = logging.Formatter(FORMATO, datefmt="%Y-%m-%d %H:%M:%S")
    arquivo = logging.FileHandler(logs_dir / f"robo_{agora:%Y%m%d}.log", encoding="utf-8")
    arquivo.setFormatter(formato)
    logger.addHandler(arquivo)
    if console:
        tela = logging.StreamHandler(sys.stdout)
        tela.setFormatter(formato)
        logger.addHandler(tela)
    return logging.LoggerAdapter(logger, {"run_id": run_id})  # type: ignore[return-value]


def fechar_logger(logger: logging.Logger) -> None:
    base = getattr(logger, "logger", logger)
    for handler in list(base.handlers):
        handler.close()
        base.removeHandler(handler)


class Auditoria:
    """Grava um evento por linha em JSON (JSONL), apenas com dados não pessoais."""

    def __init__(self, logs_dir: Path, run_id: str, agora: datetime):
        logs_dir.mkdir(parents=True, exist_ok=True)
        self._caminho = logs_dir / f"auditoria_{agora:%Y%m%d}.jsonl"
        self._run_id = run_id

    def registrar(self, etapa: str, resultado: str, **detalhes: object) -> None:
        evento = {
            "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
            "execucao": self._run_id,
            "etapa": etapa,
            "resultado": resultado,
            **detalhes,
        }
        with self._caminho.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evento, ensure_ascii=False) + "\n")


def gravar_resumo(logs_dir: Path, run_id: str, resumo: dict) -> Path:
    caminho = logs_dir / f"resumo_{run_id}.json"
    caminho.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")
    return caminho
